#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_edl.py — 컷 결과를 CMX3600 EDL로 내보낸다.

Premiere Pro 26(2026)에서 FCP7 XML 임포터가 제거돼(설치 폴더에 xmeml 모듈 없음,
가져오기 형식 목록에도 없음) XML 경로를 대체한다. EDL 가져오기는 26.3에도 살아 있다
(Settings/EveScripts/ImportFromEDLDialog.adam.eve).

전제: 먼저 auto_cut.py 를 돌려 output/<base>_cut.xml 이 있어야 한다(그 keep 구간을 읽는다).

사용:
  python make_edl.py <마스터영상> [--cam2 <영상> <offset초>] [--audio-reel wav|source]

출력(output/):
  <base>_cam01.edl   V = 마스터 · A = 정리오디오(기본) 또는 원본 카메라 오디오
  <base>_cam02.edl   V = 보조캠 (같은 레코드 타임라인 → 스택하면 싱크)
  <base>_simple.edl  V+A 모두 마스터 원본에서 (가장 단순 — relink 실패 시 대안)
"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from silence_cut import probe_media, FFPROBE, run

NTSC_FPS = 30000 / 1001


# ── 드롭프레임 타임코드 ──────────────────────────────────────────────
def df_to_frames(tc):
    """'HH:MM:SS;FF' 또는 'HH:MM:SS:FF' (29.97 DF) → 프레임 번호."""
    h, m, s, f = (int(x) for x in re.split(r"[:;]", tc.strip()))
    total_min = 60 * h + m
    return (108000 * h + 1800 * m + 30 * s + f) - 2 * (total_min - total_min // 10)


def frames_to_df(fr, sep=":"):
    """프레임 번호 → 29.97 드롭프레임 타임코드."""
    if fr < 0:
        fr = 0
    d, m = divmod(fr, 17982)              # 10분 = 17982 프레임(DF)
    if m < 2:
        m += 2
    fr += 18 * d + 2 * ((m - 2) // 1798)
    return (f"{(fr // 108000) % 24:02d}{sep}{(fr // 1800) % 60:02d}"
            f"{sep}{(fr // 30) % 60:02d}{sep}{fr % 30:02d}")


def source_tc(path):
    """미디어에 박힌 시작 타임코드. 없으면 00:00:00:00."""
    r = run([FFPROBE, "-v", "error", "-show_entries",
             "format_tags=timecode:stream_tags=timecode", "-of", "default=nw=1", path])
    m = re.search(r"timecode=(\d+[:;]\d+[:;]\d+[:;]\d+)", r.stdout)
    return m.group(1) if m else "00:00:00:00"


# ── EDL 조립 ────────────────────────────────────────────────────────
def parse_keeps(cut_xml):
    """마스터 _cut.xml 비디오 클립의 (in, out) 프레임."""
    t = open(cut_xml, encoding="utf-8").read()
    keeps = []
    for ci in re.finditer(r'<clipitem id="cv\d+">.*?</clipitem>', t, re.S):
        b = ci.group(0)
        i = re.search(r"<in>(\d+)</in>", b)
        o = re.search(r"<out>(\d+)</out>", b)
        if i and o:
            keeps.append((int(i.group(1)), int(o.group(1))))
    return keeps


def reel(name):
    """EDL 릴명은 8자 제한, 영숫자."""
    s = re.sub(r"[^A-Za-z0-9]", "", name.upper())[:8]
    return s.ljust(8)


def build(title, keeps, tracks, path_note):
    """tracks = [(채널, 릴명, 매핑기준프레임, 미디어TC시작, 미디어길이)] — 이벤트별 줄 생성.

    매핑기준프레임에는 싱크 오프셋이 이미 반영돼 있을 수 있다. 따라서 유효 범위는
    반드시 '미디어 자체의 TC 구간' [tc0, tc0+length] 로 판정해야 한다.

    범위를 벗어나는 이벤트(그 카메라가 아직/이미 안 찍고 있던 구간)는 **버리지 않고**
    소스 구간만 유효 범위 안으로 밀어 넣는다(clamp). 컷 개수·컷 지점·러닝타임이
    카메라마다 완전히 동일해야 레이어를 겹쳐 교차편집할 수 있기 때문이다.
    클램프된 이벤트는 그 클립만 내용이 최대 1초 어긋나므로 호출부에서 보고한다.
    """
    out = [f"TITLE: {title}", "FCM: DROP FRAME", ""]
    rec, clamped = 0, []
    n = 0
    for a, b in keeps:
        dur = b - a
        r_in, r_out = rec, rec + dur
        rec = r_out
        n += 1
        lines = []
        for ch, rl, src_base, tc0, src_len in tracks:
            s_in, s_out = src_base + a, src_base + b
            if src_len is not None:
                lo, hi = tc0, tc0 + src_len
                if s_in < lo:                      # 아직 녹화 전 → 뒤로 민다
                    clamped.append((n, rl.strip(), lo - s_in))
                    s_in, s_out = lo, lo + dur
                elif s_out > hi:                   # 이미 녹화 종료 → 앞으로 당긴다
                    clamped.append((n, rl.strip(), s_out - hi))
                    s_out, s_in = hi, hi - dur
            lines.append(f"{{n}}  {reel(rl)} {ch:<5} C        "
                         f"{frames_to_df(s_in)} {frames_to_df(s_out)} "
                         f"{frames_to_df(r_in)} {frames_to_df(r_out)}")
        out += [l.replace("{n}", f"{n:03d}") for l in lines]
        out.append(f"* FROM CLIP NAME: {path_note}")
        out.append("")
    return "\n".join(out) + "\n", n, clamped


def main():
    args = [a for a in sys.argv[1:]]
    cam2, off2 = None, 0.0
    if "--cam2" in args:
        i = args.index("--cam2")
        cam2, off2 = args[i + 1], float(args[i + 2])
        del args[i:i + 3]
    audio_reel = "wav"
    if "--audio-reel" in args:
        i = args.index("--audio-reel")
        audio_reel = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__); sys.exit(1)

    master = args[0]
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.splitext(os.path.basename(master))[0]
    outdir = os.path.join(proj, "output")
    cut_xml = os.path.join(outdir, base + "_cut.xml")
    wav = os.path.join(outdir, base + "_cut_audio.wav")
    if not os.path.exists(cut_xml):
        print("먼저 auto_cut.py 를 돌리세요. 없음:", cut_xml); sys.exit(2)

    keeps = parse_keeps(cut_xml)
    if not keeps:
        print("keep 구간을 못 읽음:", cut_xml); sys.exit(2)

    m_tc = source_tc(master)
    m_base = df_to_frames(m_tc)
    m_len = int(round(probe_media(master)["duration"] * NTSC_FPS))
    print(f"컷 {len(keeps)}개 · 마스터 시작 TC {m_tc} (프레임 {m_base}, 길이 {m_len})")

    written = []

    def emit(fname, title, tracks, note):
        body, n, cl = build(title, keeps, tracks, note)
        p = os.path.join(outdir, fname)
        open(p, "w", encoding="utf-8", newline="\r\n").write(body)
        written.append((p, n, cl))

    # 자정을 넘는 소스는 TC가 23:59:59:29 → 00:00:00:00 으로 되돌아가, EDL 이벤트의
    # 소스 TC가 미디어 시작 TC보다 작아진다(= 매칭 실패). 그런 경우 0 기준 버전을 같이 낸다.
    wraps = (m_base + m_len) > df_to_frames("23:59:59:29") + 1
    if wraps:
        print(f"  [주의] 마스터가 자정을 넘어감 ({m_tc} + {m_len}프레임)")
    # TC0 변형은 자정 넘김과 무관하게 **항상** 만든다. 표준 워크플로가 TC0 리먹스 사본을
    # 프리미어에 연결하기 때문. (cam02는 자정을 안 넘는다고 실제 TC 만 냈다가,
    # 미디어 TC 와 안 맞아 23시간짜리 유령 클립이 생기고 컷이 전부 어긋났었다)

    # 오디오는 EDL에 넣지 않는다. 릴 2개를 한 이벤트에 묶으면 프리미어가 오디오 소스 in점을
    # 못 살리고 매 컷마다 0부터 재생한다(실측). 오디오는 make_cut_audio.py 로 만든
    # '컷 적용된 단일 WAV'를 타임라인 0에 한 번만 올린다.
    emit(base + "_cam01_v_tc0.edl", f"{base} CAM01 V TC0",
         [("V", "CAM01", 0, 0, m_len)], os.path.basename(master))
    emit(base + "_cam01_v.edl", f"{base} CAM01 V",
         [("V", "CAM01", m_base, m_base, m_len)], os.path.basename(master))
    # 카메라 원본 오디오까지 한 릴에서 받고 싶을 때(음량정리 없음)
    emit(base + "_cam01_av_tc0.edl", f"{base} CAM01 AV TC0",
         [("AA/V", "CAM01", 0, 0, m_len)], os.path.basename(master))

    # 3) cam02 = 같은 레코드 타임라인, 소스만 오프셋만큼 당김
    if cam2:
        c_tc = source_tc(cam2)
        c_base = df_to_frames(c_tc)
        c_len = int(round(probe_media(cam2)["duration"] * NTSC_FPS))
        shift = int(round(off2 * NTSC_FPS))       # cam2가 늦게 시작한 프레임 수
        print(f"cam02 시작 TC {c_tc} (프레임 {c_base}, 길이 {c_len}) · 오프셋 {off2}s = {shift}프레임")
        emit(base + "_cam02_v_tc0.edl", f"{base} CAM02 V TC0",
             [("V", "CAM02", -shift, 0, c_len)], os.path.basename(cam2))
        emit(base + "_cam02_v.edl", f"{base} CAM02 V",
             [("V", "CAM02", c_base - shift, c_base, c_len)], os.path.basename(cam2))

    total = sum(b - a for a, b in keeps)
    print(f"시퀀스 길이 {frames_to_df(total)} ({total} 프레임) · 컷 {len(keeps)}개")
    for p, n, cl in written:
        print(f"  생성: {os.path.basename(p)}  ({n}이벤트)")
        for ev, rl, d in cl:
            print(f"      [클램프] 이벤트 {ev:03d} {rl}: 소스가 {d}프레임({d/NTSC_FPS:.2f}초) 부족 "
                  f"→ 그 클립만 내용이 그만큼 밀림 (컷 지점·길이는 동일)")
    print("\n프리미어:")
    print("  1) 각 .edl 을 가져오기 → 오프라인 릴에 파일 연결")
    print("  2) cam02 시퀀스 전체 복사 → cam01 시퀀스의 V2 에 00:00:00:00 기준으로 붙여넣기")
    print("  3) 오디오는 _cut_audio_flat.wav 를 A1 의 00:00:00:00 에 올린다")
    print("  ※ 모든 EDL 이 같은 컷 개수·같은 레코드 TC 라서 레이어가 정확히 겹칩니다.")


if __name__ == "__main__":
    main()
