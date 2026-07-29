#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_highlight.py — 컷 타임라인을 '카테고리별 레이어' + '하이라이트 축약본' 으로 나눈다.

두 가지를 만든다.

1) 카테고리 레이어 EDL — 카테고리마다 EDL 을 하나씩. 각 EDL 은 **원래 레코드 위치**를
   그대로 유지하므로, 프리미어에서 트랙(V2, V3 …)에 하나씩 올리면 카테고리별로
   층이 갈린다. 트랙별 전체 선택 → 라벨 색 지정으로 색 구분이 끝난다.
   (CMX3600 EDL 에는 클립 라벨 색상 필드가 없고, 색을 담을 수 있는 FCP7 XML 은
    Premiere 26 이 못 읽는다. 그래서 '색' 대신 '레이어'로 가른다.)

2) 하이라이트 EDL + 자막 — keep=true 인 구간만 이어붙인 축약 시퀀스.

전제: auto_cut.py 로 output/<base>_cut.xml · <base>_cut.srt 가 있어야 한다.

사용:
  python make_highlight.py <마스터영상> --segments <구간.json>

구간.json:
  {
    "categories": {"오프닝": "Violet", "사례": "Mango", ...},
    "segments": [
      {"start": "0:00", "end": "1:31", "cat": "오프닝", "keep": true, "note": "..."},
      ...
    ]
  }
  start/end 는 **컷 타임라인**(= _cut.srt 와 같은 기준) 의 M:SS 또는 초.
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
    print("\n── 카테고리 레이어")
    rows = []
    for i, (cat, evs) in enumerate(bycat.items(), 1):
        dur = sum(b - a for a, b, _ in evs) / fps
        slug = f"cat{i:02d}"
        fn = f"{base}_{slug}.edl"
        open(os.path.join(o, fn), "w", encoding="utf-8", newline="\r\n").write(
            build_edl(f"{base} {cat}", evs, "CAM01", note, renumber_record=False))
        rows.append((i, cat, colors.get(cat, "-"), len(evs), dur, fn))
        print(f"  V{i+1}  {cat:<14} {len(evs):3d}클립 {dur/60:5.2f}분  {fn}")

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

    # ── 3) 카테고리 표 ────────────────────────────────────────────
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
          "## 1) 본편 시퀀스 (카테고리 색 구분)",
          "",
          "1. `_cam01_v_tc0.edl` 가져오기 → 시퀀스가 생긴다. 오프라인 릴 **CAM01** 을",
          "   `_TC0.MP4` 에 연결. 이게 본편(V1)이다.",
          "2. `_cut_audio_flat.wav` 를 **A1 의 00:00:00:00** 에 올린다.",
          "   V1 클립의 원본 오디오는 음소거 — EDL 에는 오디오가 없고 이 WAV 가 정리본이다.",
          "3. `_cut.srt` 가져오기 → 캡션 트랙.",
          "4. 아래 카테고리 EDL 을 각각 가져온다(EDL 하나 = 시퀀스 하나).",
          "   각 시퀀스를 열어 **전체 선택 → 복사** → 본편 시퀀스의 해당 트랙에",
          "   **00:00:00:00 기준으로 붙여넣기**. 레코드 위치가 본편과 같으므로 그대로 겹친다.",
          "5. 트랙별로 클립 전체 선택 → 오른쪽 클릭 > 레이블 > 아래 색.",
          "6. 색 확인이 끝나면 V2 이상은 숨기거나 지운다 — **실제 편집본은 V1** 이다.",
          "7. 타임라인 전체 선택 → `Cmd/Ctrl+Shift+D` (컷 클릭음 제거).",
          "",
          "| 트랙 | 카테고리 | 레이블 색 | 클립 | 길이 | EDL |",
          "|---|---|---|---|---|---|"]
    for i, cat, col, n, dur, f_ in rows:
        md.append(f"| V{i+1} | {cat} | {col} | {n} | {dur/60:.2f}분 | `{f_}` |")
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
