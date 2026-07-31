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

# 윈도우 콘솔 기본 인코딩(cp949)에는 em dash 같은 기호가 없어 출력하다 죽는다.
# 한글은 cp949 에 있어서 평소엔 안 드러나다가 --help 나 기호가 섞이면 터진다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

NTSC_FPS = 30000 / 1001            # 기본값(29.97). 실제 소스 fps 는 main() 이 FPS 에 넣는다.
FPS = NTSC_FPS


def tc_rate(fps=None):
    """(공칭프레임수, 분당드롭수) — 드롭프레임은 NTSC(29.97·59.94)에만 쓴다.

    59.94 는 분당 4프레임을 떨어뜨린다(29.97 의 2프레임과 같은 비율). 25p·24p·정수
    30p 는 드롭프레임이 없으므로 drop=0 → 논드롭 타임코드가 된다.
    """
    fps = FPS if fps is None else fps
    nominal = int(round(fps))
    drop = nominal // 15 if (nominal in (30, 60) and abs(fps - nominal) > 1e-3) else 0
    return nominal, drop


# ── 타임코드 ────────────────────────────────────────────────────────
def df_to_frames(tc, fps=None):
    """'HH:MM:SS;FF' 또는 'HH:MM:SS:FF' → 프레임 번호."""
    n, d = tc_rate(fps)
    h, m, s, f = (int(x) for x in re.split(r"[:;]", tc.strip()))
    total_min = 60 * h + m
    return ((3600 * n * h + 60 * n * m + n * s + f)
            - d * (total_min - total_min // 10))


def frames_to_df(fr, sep=":", fps=None):
    """프레임 번호 → 타임코드(드롭프레임이면 드롭 보정 포함)."""
    n, d = tc_rate(fps)
    if fr < 0:
        fr = 0
    if d:
        fp10 = 600 * n - 9 * d            # 10분: 29.97=17982 · 59.94=35964
        fpm = 60 * n                      # 1분(공칭): 1800 · 3600
        q, m = divmod(fr, fp10)
        if m < d:
            m += d
        fr += 9 * d * q + d * ((m - d) // (fpm - d))
    return (f"{(fr // (3600 * n)) % 24:02d}{sep}{(fr // (60 * n)) % 60:02d}"
            f"{sep}{(fr // n) % 60:02d}{sep}{fr % n:02d}")


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
    fcm = "DROP FRAME" if tc_rate()[1] else "NON-DROP FRAME"
    out = [f"TITLE: {title}", f"FCM: {fcm}", ""]
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

    # _cut.xml 의 프레임 번호는 **소스 실제 fps** 단위다. 타임코드도 같은 fps 로 찍어야
    # 한다 — 59.94p 를 29.97 로 찍으면 모든 컷이 정확히 2배로 어긋난다.
    global FPS
    raw_fps = probe_media(master)["fps"]
    # [중요] EDL 타임코드는 30프레임까지다. 59.94p 를 60프레임 TC 로 쓰면 프리미어가
    # 프레임 필드 30 이상을 못 읽어 클립이 엉뚱한 자리에 놓인다 — 타임라인에 빈 공백이
    # 생기고 오디오와 싱크가 어긋난다(실측). 관례대로 소스 2프레임 = TC 1프레임으로 접는다.
    tcdiv = 2 if round(raw_fps) > 30 else 1
    FPS = raw_fps / tcdiv
    nominal, drop = tc_rate()
    print(f"소스 {raw_fps}fps → {nominal}프레임 타임코드 "
          f"({'드롭프레임' if drop else '논드롭'}"
          + (f", 소스 {tcdiv}프레임 = TC 1프레임" if tcdiv > 1 else "") + ")")
    if tcdiv > 1:                       # 프레임 값도 같은 기준으로 접는다
        keeps = [(int(round(a / tcdiv)), int(round(b / tcdiv))) for a, b in keeps]

    m_tc = source_tc(master)
    m_base = df_to_frames(m_tc)
    m_len = int(round(probe_media(master)["duration"] * FPS))
    print(f"컷 {len(keeps)}개 · 마스터 시작 TC {m_tc} (프레임 {m_base}, 길이 {m_len})")

    # tc0 변형은 TC0 리먹스 사본에 연결한다. 클립 이름을 그 파일명과 같게 두면
    # '미디어 연결' 대화상자가 파일을 자동으로 찾는다. (이름은 모든 이벤트가 같아야
    # 한다 — 다르면 프리미어가 이벤트마다 별개 오프라인 항목으로 잡는다)
    _tc0 = os.path.join(os.path.dirname(os.path.abspath(master)), base + "_TC0.MP4")
    tc0_name = os.path.basename(_tc0) if os.path.exists(_tc0) else os.path.basename(master)

    written = []

    def emit(fname, title, tracks, note):
        body, n, cl = build(title, keeps, tracks, note)
        p = os.path.join(outdir, fname)
        open(p, "w", encoding="utf-8", newline="\r\n").write(body)
        written.append((p, n, cl))

    # 자정을 넘는 소스는 TC가 23:59:59:29 → 00:00:00:00 으로 되돌아가, EDL 이벤트의
    # 소스 TC가 미디어 시작 TC보다 작아진다(= 매칭 실패). 그런 경우 0 기준 버전을 같이 낸다.
    wraps = (m_base + m_len) > df_to_frames(f"23:59:59:{nominal - 1:02d}") + 1
    if wraps:
        print(f"  [주의] 마스터가 자정을 넘어감 ({m_tc} + {m_len}프레임)")
    # TC0 변형은 자정 넘김과 무관하게 **항상** 만든다. 표준 워크플로가 TC0 리먹스 사본을
    # 프리미어에 연결하기 때문. (cam02는 자정을 안 넘는다고 실제 TC 만 냈다가,
    # 미디어 TC 와 안 맞아 23시간짜리 유령 클립이 생기고 컷이 전부 어긋났었다)

    # 오디오는 EDL에 넣지 않는다. 릴 2개를 한 이벤트에 묶으면 프리미어가 오디오 소스 in점을
    # 못 살리고 매 컷마다 0부터 재생한다(실측). 오디오는 make_cut_audio.py 로 만든
    # '컷 적용된 단일 WAV'를 타임라인 0에 한 번만 올린다.
    emit(base + "_cam01_v_tc0.edl", f"{base} CAM01 V TC0",
         [("V", "CAM01", 0, 0, m_len)], tc0_name)
    emit(base + "_cam01_v.edl", f"{base} CAM01 V",
         [("V", "CAM01", m_base, m_base, m_len)], os.path.basename(master))
    # 카메라 원본 오디오까지 한 릴에서 받고 싶을 때(음량정리 없음)
    emit(base + "_cam01_av_tc0.edl", f"{base} CAM01 AV TC0",
         [("AA/V", "CAM01", 0, 0, m_len)], tc0_name)

    # 3) cam02 = 같은 레코드 타임라인, 소스만 오프셋만큼 당김
    if cam2:
        c_tc = source_tc(cam2)
        c_base = df_to_frames(c_tc)
        c_len = int(round(probe_media(cam2)["duration"] * FPS))
        shift = int(round(off2 * FPS))       # cam2가 늦게 시작한 프레임 수
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
            print(f"      [클램프] 이벤트 {ev:03d} {rl}: 소스가 {d}프레임({d/FPS:.2f}초) 부족 "
                  f"→ 그 클립만 내용이 그만큼 밀림 (컷 지점·길이는 동일)")
    print("\n프리미어:")
    print("  1) 각 .edl 을 가져오기 → 오프라인 릴에 파일 연결")
    print("  2) cam02 시퀀스 전체 복사 → cam01 시퀀스의 V2 에 00:00:00:00 기준으로 붙여넣기")
    print("  3) 오디오는 _cut_audio_flat.wav 를 A1 의 00:00:00:00 에 올린다")
    print("  ※ 모든 EDL 이 같은 컷 개수·같은 레코드 TC 라서 레이어가 정확히 겹칩니다.")


if __name__ == "__main__":
    main()
