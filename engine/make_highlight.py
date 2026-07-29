#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_highlight.py — 컷 결과를 '카테고리를 붙인 단일 시퀀스' 로 정리한다.

만드는 것(전부 시퀀스 하나짜리 EDL — 트랙에 쌓지 않는다):

  <base>_final.edl          keep=true 구간만 이어붙인 축약본  ← 보통 이걸 쓴다
  <base>_full_labeled.edl   컷편집 전체(컷 개수 그대로)
  <base>_highlight.srt      축약본 시간축에 맞춘 자막
  <base>_highlight_audio.wav 축약본 길이에 맞춘 정리 오디오
  <base>_categories.md      구간 판단 근거 + 조립 순서

카테고리는 **클립 이름**으로 넣는다(`사례일화_037`). 프리미어가 * FROM CLIP NAME 을
클립 이름으로 읽으므로 타임라인에서 바로 구분되고, 이름으로 묶어 선택해 레이블 색을
줄 수도 있다.

[하지 말 것] 카테고리마다 EDL 을 따로 뽑아 V2·V3… 에 쌓는 방식.
처음에 그렇게 만들었다가 실패했다 — 카테고리 경계가 컷 중간을 잘라 104컷이 129조각이
되고, 각 EDL 이 자기 구간만 갖고 나머지는 비어 있어 타임라인이 알아볼 수 없게 된다.
그래서 컷은 쪼개지 않고, 각 컷을 '가장 많이 겹치는 카테고리'에 통째로 배정한다.

전제: auto_cut.py 로 output/<base>_cut.xml · <base>_cut.srt 가 있어야 한다.

사용:
  python make_highlight.py <마스터영상> --segments <구간.json>

구간.json:
  {
    "categories": {"오프닝": "Violet", "사례·일화": "Mango", ...},   # 권장 레이블 색
    "segments": [
      {"start": "0:00", "end": "1:31", "cat": "오프닝", "keep": true, "note": "..."},
      ...
    ]
  }
  start/end 는 **컷 타임라인**(= _cut.srt 와 같은 기준) 의 M:SS 또는 초.
  keep=false 는 축약본에서 빠진다(제작지시·잡담·중복).
"""
import sys, os, re, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_edl
from make_edl import frames_to_df, parse_keeps, reel, tc_rate
from silence_cut import probe_media


def parse_t(v):
    """'12:34' · '1:02:03' · 74.5 → 초."""
    if isinstance(v, (int, float)):
        return float(v)
    p = [float(x) for x in str(v).strip().split(":")]
    s = 0.0
    for x in p:
        s = s * 60 + x
    return s


def slice_timeline(keeps, t0, t1, fps):
    """컷 타임라인 [t0,t1)초 → [(소스in, 소스out, 레코드in)] 프레임.

    keeps 는 소스 구간이 레코드 타임라인에 순서대로 이어붙어 있는 구조라,
    레코드 구간을 keep 단위로 잘라 소스 좌표로 되돌린다.
    """
    r0, r1 = int(round(t0 * fps)), int(round(t1 * fps))
    out, acc = [], 0
    for a, b in keeps:
        ln = b - a
        s, e = acc, acc + ln
        acc = e
        if e <= r0 or s >= r1:
            continue
        lo, hi = max(r0, s), min(r1, e)
        if hi > lo:
            out.append((a + (lo - s), a + (hi - s), lo))
    return out


def build_edl(title, events, reel_name, note, renumber_record):
    """events = [(src_in, src_out, rec_in)].

    renumber_record=True 면 레코드를 0부터 빈틈없이 다시 매긴다(하이라이트용).
    False 면 원래 레코드 위치를 유지한다(카테고리 레이어용 — 그래야 본편과 겹친다).
    """
    fcm = "DROP FRAME" if tc_rate()[1] else "NON-DROP FRAME"
    out = [f"TITLE: {title}", f"FCM: {fcm}", ""]
    rec = 0
    for i, (si, so, ri) in enumerate(events, 1):
        dur = so - si
        r_in = rec if renumber_record else ri
        r_out = r_in + dur
        rec = r_in + dur
        out.append(f"{i:03d}  {reel(reel_name)} V     C        "
                   f"{frames_to_df(si)} {frames_to_df(so)} "
                   f"{frames_to_df(r_in)} {frames_to_df(r_out)}")
        out.append(f"* FROM CLIP NAME: {note}")
        out.append("")
    return "\n".join(out) + "\n"


def cues(p):
    out = []
    for b in re.split(r"\r?\n\r?\n", open(p, encoding="utf-8").read().strip()):
        L = b.splitlines()
        if len(L) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", L[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        out.append([g[0]*3600+g[1]*60+g[2]+g[3]/1000,
                    g[4]*3600+g[5]*60+g[6]+g[7]/1000, "\n".join(L[2:])])
    return out


def srt_time(t):
    h, r = divmod(max(0.0, t), 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1)*1000)):03d}"


def main():
    if "--segments" not in sys.argv:
        print(__doc__); sys.exit(1)
    master = sys.argv[1]
    segp = sys.argv[sys.argv.index("--segments") + 1]

    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.splitext(os.path.basename(master))[0]
    o = os.path.join(proj, "output")
    cut_xml = os.path.join(o, base + "_cut.xml")
    srt = os.path.join(o, base + "_cut.srt")
    for p in (cut_xml, segp):
        if not os.path.exists(p):
            print("필요 파일 없음:", p); sys.exit(2)

    make_edl.FPS = fps = probe_media(master)["fps"]
    keeps = parse_keeps(cut_xml)
    total_f = sum(b - a for a, b in keeps)
    spec = json.load(open(segp, encoding="utf-8"))
    segs = spec["segments"]
    colors = spec.get("categories", {})
    note = os.path.basename(master)
    print(f"소스 {fps}fps · 컷 {len(keeps)}개 · 본편 {total_f/fps/60:.2f}분")

    # ── 1) 카테고리 레이어 EDL (레코드 위치 유지) ─────────────────
    bycat = {}
    for s in segs:
        bycat.setdefault(s["cat"], []).extend(
            slice_timeline(keeps, parse_t(s["start"]), parse_t(s["end"]), fps))
    # 카테고리별 EDL 을 따로 뽑아 트랙에 쌓는 방식은 쓰지 않는다 — 아래 3) 참고.
    # 여기서는 분량 집계만 하고, 구분은 클립 이름으로 넣는다.
    print("\n── 카테고리 분량")
    rows = []
    for i, (cat, evs) in enumerate(bycat.items(), 1):
        dur = sum(b - a for a, b, _ in evs) / fps
        rows.append((i, cat, colors.get(cat, "-"), len(evs), dur))
        print(f"  {cat:<14} {dur/60:5.2f}분")

    # ── 2) 하이라이트 (keep=true 만 이어붙임) ──────────────────────
    hl, cuts = [], []
    for s in segs:
        if not s.get("keep", True):
            continue
        t0, t1 = parse_t(s["start"]), parse_t(s["end"])
        hl.extend(slice_timeline(keeps, t0, t1, fps))
        cuts.append((t0, t1))
    hl_f = sum(b - a for a, b, _ in hl)
    fn = f"{base}_highlight.edl"
    open(os.path.join(o, fn), "w", encoding="utf-8", newline="\r\n").write(
        build_edl(f"{base} HIGHLIGHT", hl, "CAM01", note, renumber_record=True))
    print(f"\n── 하이라이트\n  {len(hl)}클립 · {hl_f/fps/60:.2f}분  {fn}")

    # 하이라이트 자막 — 남긴 구간만 골라 시간축을 당긴다
    if os.path.exists(srt):
        out, off = [], 0.0
        for t0, t1 in cuts:
            for a, b, tx in cues(srt):
                if b <= t0 or a >= t1:
                    continue
                out.append((max(a, t0) - t0 + off, min(b, t1) - t0 + off, tx))
            off += t1 - t0
        hs = os.path.join(o, base + "_highlight.srt")
        with open(hs, "w", encoding="utf-8") as f:
            for i, (a, b, tx) in enumerate(out, 1):
                f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{tx}\n\n")
        print(f"  자막 {len(out)}줄  {os.path.basename(hs)}")

    # 하이라이트 오디오 — 본편 플랫 WAV 를 같은 구간으로 다시 자른다.
    # (본편용 _cut_audio_flat.wav 는 21분짜리라 하이라이트 시퀀스에 못 쓴다)
    flat = os.path.join(o, base + "_cut_audio_flat.wav")
    if os.path.exists(flat):
        import wave
        with wave.open(flat, "rb") as w:
            nch, sw, sr, nf = (w.getnchannels(), w.getsampwidth(),
                               w.getframerate(), w.getnframes())
            pcm = w.readframes(nf)
        bpf = nch * sw
        parts, tot = [], 0
        for t0, t1 in cuts:
            s0 = max(0, min(int(round(t0 * sr)), nf))
            s1 = max(s0, min(int(round(t1 * sr)), nf))
            parts.append(pcm[s0*bpf:s1*bpf]); tot += s1 - s0
        ha = os.path.join(o, base + "_highlight_audio.wav")
        with wave.open(ha, "wb") as w:
            w.setnchannels(nch); w.setsampwidth(sw); w.setframerate(sr)
            w.writeframes(b"".join(parts))
        d = abs(tot/sr - hl_f/fps) * 1000
        print(f"  오디오 {tot/sr/60:.2f}분  {os.path.basename(ha)}  (영상과 차이 {d:.1f}ms)")
        if d > 50:
            print("  [주의] 영상/오디오 길이 차가 큽니다 — 확인 필요")

    # ── 3) 단일 시퀀스 EDL — 카테고리를 '클립 이름'으로 ──────────────
    # 카테고리별 EDL 을 트랙에 쌓는 방식은 실패했다. 카테고리 경계가 컷 중간을 잘라
    # 클립이 산산조각 나고, 각 EDL 이 자기 구간만 갖고 나머지는 비어 있어 조립이 안 된다.
    # 대신 시퀀스 하나에 다 담고, 컷은 쪼개지 않은 채(원래 104개 그대로) 각 컷을
    # '가장 많이 겹치는 카테고리'에 배정해 * FROM CLIP NAME 으로 적는다.
    # 프리미어가 이 값을 클립 이름으로 읽으므로 타임라인에서 바로 구분된다.
    def clean(s):
        return re.sub(r"[·:/]", "", s).strip()

    spans = []                                  # (레코드in, 레코드out, 카테고리)
    for s in segs:
        spans.append((int(round(parse_t(s["start"]) * fps)),
                      int(round(parse_t(s["end"]) * fps)), s["cat"], s.get("keep", True)))

    def dominant(r0, r1):
        best, bw, bk = "미분류", 0, True
        for s0, s1, cat, kp in spans:
            w = min(r1, s1) - max(r0, s0)
            if w > bw:
                best, bw, bk = cat, w, kp
        return best, bk

    def labeled(events, renumber, fname, title):
        fcm = "DROP FRAME" if tc_rate()[1] else "NON-DROP FRAME"
        out, rec, tally = [f"TITLE: {title}", f"FCM: {fcm}", ""], 0, {}
        for i, (si, so, ri) in enumerate(events, 1):
            dur = so - si
            r_in = rec if renumber else ri
            r_out = r_in + dur
            rec = r_out
            cat, _ = dominant(ri, ri + dur)
            tally[cat] = tally.get(cat, 0) + dur
            out.append(f"{i:03d}  {reel('CAM01')} V     C        "
                       f"{frames_to_df(si)} {frames_to_df(so)} "
                       f"{frames_to_df(r_in)} {frames_to_df(r_out)}")
            out.append(f"* FROM CLIP NAME: {clean(cat)}_{i:03d}")
            out.append("")
        open(os.path.join(o, fname), "w", encoding="utf-8",
             newline="\r\n").write("\n".join(out) + "\n")
        return tally

    print("\n── 단일 시퀀스 (카테고리 = 클립 이름)")
    full_ev, acc = [], 0
    for a, b in keeps:
        full_ev.append((a, b, acc)); acc += b - a
    t1 = labeled(full_ev, True, base + "_full_labeled.edl", f"{base} FULL")
    print(f"  본편   {len(full_ev):3d}클립 {acc/fps/60:5.2f}분  {base}_full_labeled.edl")
    t2 = labeled(hl, True, base + "_final.edl", f"{base} FINAL")
    print(f"  하이라이트 {len(hl):3d}클립 {hl_f/fps/60:5.2f}분  {base}_final.edl  ← 이걸 쓰면 됨")
    for cat, f_ in sorted(t2.items(), key=lambda x: -x[1]):
        print(f"      {clean(cat):<12} {f_/fps/60:5.2f}분")

    # ── 4) 카테고리 표 ────────────────────────────────────────────
    md = [f"# {base} — 카테고리 / 하이라이트", "",
          f"본편 {total_f/fps/60:.2f}분 · 하이라이트 {hl_f/fps/60:.2f}분", "",
          "## 0) 먼저 — TC0 사본",
          "",
          "모든 EDL 이 **TC 0 기준**이다. 원본에 카메라 시계가 박혀 있으면 프리미어가",
          "그 차이만큼 유령 클립을 만들어 컷이 전부 어긋난다. 재인코딩 없음(1~3분).",
          "",
          "```bash",
          "ffmpeg -i 원본.MP4 -map 0:v:0 -map 0:a:0 -c copy \\",
          "       -timecode 00:00:00:00 원본_TC0.MP4",
          "```",
          "",
          "## 1) 시퀀스는 하나면 된다",
          "",
          f"**`{base}_final.edl`** 하나만 가져오면 된다(15분 하이라이트).",
          f"본편 전체가 필요하면 `{base}_full_labeled.edl`(21분).",
          "",
          "카테고리별로 EDL 을 나눠 트랙에 쌓는 방식은 쓰지 않는다 — 카테고리 경계가",
          "컷 중간을 잘라 클립이 산산조각 나고, 각 EDL 이 자기 구간만 갖고 나머지는",
          "비어 있어 조립이 안 된다. 대신 **컷을 쪼개지 않고** 각 클립에 카테고리를",
          "이름으로 붙였다(`001 사례일화` 형식). 타임라인에서 클립 이름으로 바로 구분된다.",
          "",
          "1. EDL 가져오기 → 오프라인 릴 **CAM01** 을 `_TC0.MP4` 에 연결.",
          f"2. `{base}_highlight_audio.wav` 를 **A1 의 00:00:00:00** 에.",
          "   (본편을 쓸 거면 `_cut_audio_flat.wav`) V1 클립의 원본 오디오는 음소거.",
          f"3. `{base}_highlight.srt` 가져오기. (본편은 `_cut.srt`)",
          "4. 전체 선택 → `Cmd/Ctrl+Shift+D` (컷 클릭음 제거).",
          "5. 색으로 보고 싶으면 — 타임라인에서 같은 이름 클립을 선택",
          "   (오른쪽 클릭 > 레이블). 이름이 이미 카테고리라 고르기 쉽다.",
          "",
          "| 카테고리 | 권장 레이블 색 | 길이 |",
          "|---|---|---|"]
    for i, cat, col, n, dur in rows:
        md.append(f"| {cat} | {col} | {dur/60:.2f}분 |")
    md += ["", "## 2) 하이라이트 시퀀스 (별도)", "",
           f"본편과 **다른 시퀀스**로 만든다. 길이 {hl_f/fps/60:.2f}분.", "",
           f"1. `{base}_highlight.edl` 가져오기 → 릴 **CAM01** 을 `_TC0.MP4` 에 연결.",
           f"2. `{base}_highlight_audio.wav` 를 **A1 의 00:00:00:00** 에.",
           "   (본편용 `_cut_audio_flat.wav` 는 길이가 달라서 안 맞는다)",
           f"3. `{base}_highlight.srt` 가져오기 — 하이라이트 시간축에 맞춰 재생성된 자막이다.",
           "4. 전체 선택 → `Cmd/Ctrl+Shift+D`.", "",
           "### 구간 (○ 남김 / ✕ 제외)", ""]
    for s in segs:
        mark = "○" if s.get("keep", True) else "✕"
        md.append(f"- {mark} `{s['start']}–{s['end']}` **{s['cat']}** — {s.get('note','')}")
    mp = os.path.join(o, base + "_categories.md")
    open(mp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"  표   {os.path.basename(mp)}")


if __name__ == "__main__":
    main()
