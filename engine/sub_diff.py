"""우리 `_cut.srt` ↔ 비블이 프리미어에서 고친 자막 비교 — 자막 학습 도구.

    python engine/sub_diff.py "<프로젝트.prproj>" "output/<base>_cut.srt"

보는 것:
  A 일치율    문장부호·공백을 무시했을 때 같은 원본인지 (99%+ 면 우리 SRT 를 손본 것)
  B 문장부호  우리가 지운 온점·쉼표를 비블이 되살렸는지
  C 줄 길이   상한(25자)이 아니라 **실제 목표 길이**가 얼마인지
  D 오타      실제로 글자가 바뀐 곳 = `glossary.txt` 후보
"""
import argparse
import difflib
import re
import statistics as st
import sys

from prproj_captions import extract

STRIP = re.compile(r"[\s.,!?…·\"'’”“~]")


def load_srt(path):
    rows = []
    for block in re.split(r"\n\s*\n", open(path, encoding="utf-8").read().strip()):
        lines = [x for x in block.splitlines() if x.strip()]
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        rows.append({"start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                     "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                     "text": " ".join(lines[2:])})
    return rows


def report(ours, theirs):
    a = STRIP.sub("", " ".join(r["text"] for r in ours))
    b = STRIP.sub("", " ".join(r["text"] for r in theirs))
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)

    print(f"A. 우리 {len(ours)}줄/{len(a)}자   비블 {len(theirs)}줄/{len(b)}자   "
          f"일치율 {sm.ratio()*100:.2f}%\n")

    print("B. 문장부호")
    for nm, rows in (("우리", ours), ("비블", theirs)):
        txt = [r["text"] for r in rows]
        j = " ".join(txt)
        end_dot = sum(1 for t in txt if t.rstrip().endswith(".")) / len(txt) * 100
        none = sum(1 for t in txt if not re.search(r"[.,!?…]$", t.rstrip())) / len(txt) * 100
        print(f"   {nm}: 온점 {j.count('.')-j.count('...')*3:>4} 쉼표 {j.count(','):>4} "
              f"물음표 {j.count('?'):>3} 말줄임 {j.count('...')+j.count('…'):>3} | "
              f"줄끝 온점 {end_dot:5.1f}% 부호없음 {none:5.1f}%")

    print("\nC. 줄 길이")
    for nm, rows in (("우리", ours), ("비블", theirs)):
        d = sorted(len(r["text"]) for r in rows)
        n = len(d)
        band = lambda lo, hi: sum(1 for x in d if lo <= x <= hi) / n * 100
        print(f"   {nm}: 중앙 {st.median(d):>4.0f}자 평균 {sum(d)/n:5.1f}자 "
              f"p90 {d[int(n*.9)]:>2} 최대 {d[-1]:>2} | "
              f"~10 {band(0,10):4.1f}% 11~15 {band(11,15):4.1f}% "
              f"16~20 {band(16,20):4.1f}% 21~25 {band(21,25):4.1f}%")

    print("\nD. 글자가 바뀐 곳 = 오타·오인식 (glossary 후보)")
    ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
    for tag, i1, i2, j1, j2 in ops:
        print(f"   [{tag:<7}] …{a[max(0,i1-14):i1]}『{a[i1:i2]}』"
              f"→『{b[j1:j2]}』{a[i2:i2+14]}…")
    print(f"   총 {len(ops)}곳")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("prproj")
    ap.add_argument("srt")
    a = ap.parse_args()
    report(load_srt(a.srt), extract(a.prproj))
