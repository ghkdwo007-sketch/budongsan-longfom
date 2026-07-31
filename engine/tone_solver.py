"""소스를 보고 **톤을 맞춰 푼다** — 고정값을 복사하지 않는다.

    python engine/tone_solver.py "<원본.MP4>"                 # 풀고 미리보기
    python engine/tone_solver.py "<원본.MP4>" --at 60 200 400

**설계 이유** — 비블이 원하는 건 "고정값 재사용"이 아니라 "화면을 보고 네추럴한 톤으로
스스로 맞추는 것"이다. 그래서 톤을 **슬라이더 값이 아니라 결과 이미지의 수치**로 정의하고,
소스마다 그 수치에 닿도록 파라미터를 푼다.

**목표 수치의 출처**: 비블이 스틸에서 단계별로 직접 고른 결과들이다(2026-07-30~31).
블랙 5단계에서 0.50, 피부 채도 5단계에서 +80, 흰색 3단계에서 +12 를 골랐고,
그때 측정된 값이 아래 TARGET 이다. **실제로 보고 승인한 화면의 수치**라 믿을 수 있다.

**믿지 않는 것**: 프리미어 Lumetri 를 흉내 낸 시뮬레이션. 실측해 보니 하이라이트를 16.9%
날려먹고 블랙을 p5=0 으로 뭉갠다 — 그 출력을 목표로 삼으면 쓰레기를 학습한다.
"""
import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from apply_grade_still import full_grade, neutral_mask, skin_mask

LW = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# 비블이 고른 결과의 수치 = 톤의 정의
TARGET = {
    "중앙값": 162.0,      # 루마 중앙값 — **평균이 아니라 이걸 봐야 한다** ↓
    "대비": 205.0,        # p90 − p10. 낮으면 물이 빠진다
    "어두운영역": 22.0,   # 원본 기준 어두운 픽셀의 평균. 낮으면 뭉개고 높으면 뜬다
    "피부채도": 40.0,     # "화사하고" — 낮으면 창백해진다
    "날아감": 0.0,        # 하이라이트는 절대 날리지 않는다
    "화면RB": -1.0,       # 화면 전체 R−B. 벽만 맞추면 붉게 남는다
}

# **평균 밝기를 목표로 삼았다가 "밝고 창백하다"는 피드백을 받았다.** 평균은 161 로 맞는데
# 중앙값이 182(승인본 162)까지 떠 있었다 — 미드톤이 통째로 들려 대비가 182(승인본 205)로
# 주저앉은 것이다. 평균은 밝은 화면 하나에도 끌려가지만 중앙값·대비는 안 속는다.
# 푸는 값과 탐색 범위
KNOBS = {"whites": (0.0, 0.35), "shadow_luma": (0.10, 0.90),
         "mid_luma": (0.45, 0.95), "high_luma": (0.15, 0.70),
         "contrast": (0.0, 0.60),
         "skin_points": (0.0, 160.0), "sat_ui": (95.0, 150.0),
         "blue_points": (0.0, 40.0)}

# **화면RB 를 목표에 넣은 이유** — 벽(중성면)만 보고 맞췄더니 "화면에 붉은 기가 남았다"는
# 피드백을 받았다. 실측하니 중성면은 −1.72 로 이미 중성인데 화면 전체는 +4.63 이었다.
# 나무·피부·정장 같은 유채색이 전체를 붉게 끌기 때문이다. 비블이 5단계 중 화면 R−B
# −1.07(블루 +15)을 골랐다. **판정은 벽이 아니라 화면 전체로 한다.**


def frames(src, times, outdir, width=960):
    """탐색용이라 **작게 뽑는다.** 4K 원본 그대로 풀면 한 번에 수 분씩 걸린다
    (실측: 8MP × 160회 시도 = 10분 초과). 통계값은 축소해도 거의 그대로다."""
    out = []
    for t in times:
        p = os.path.join(outdir, f"ts_{int(t)}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src,
                        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2",
                        "-y", p], check=False)
        if os.path.exists(p):
            out.append(p)
    return out


def measure(img, dark_mask):
    f = img.astype(np.float32)
    lum = f @ LW
    mx, mn = f.max(2), f.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    sk = skin_mask(img)
    q = np.percentile(lum, [10, 90])
    return {
        "중앙값": float(np.median(lum)),
        "대비": float(q[1] - q[0]),
        "어두운영역": float(lum[dark_mask].mean()) if dark_mask.any() else 0.0,
        "피부채도": float(sat[sk].mean() * 100) if sk.any() else 0.0,
        "날아감": float((mx >= 254).mean() * 100),
        "화면RB": float(f[..., 0].mean() - f[..., 2].mean()),
    }


def cost(m):
    """목표에서 얼마나 벗어났나. 날아감은 절대 안 되므로 무겁게 벌점."""
    c = 0.0
    c += ((m["중앙값"] - TARGET["중앙값"]) / 8.0) ** 2
    c += ((m["대비"] - TARGET["대비"]) / 12.0) ** 2
    c += ((m["어두운영역"] - TARGET["어두운영역"]) / 6.0) ** 2
    c += ((m["피부채도"] - TARGET["피부채도"]) / 4.0) ** 2
    c += max(0.0, m["날아감"] - TARGET["날아감"]) ** 2 * 4.0
    c += ((m["화면RB"] - TARGET["화면RB"]) / 1.5) ** 2
    return c


def solve(imgs, rounds=3, steps=5):
    """좌표 하강 — 손잡이를 하나씩 격자 탐색하며 비용을 줄인다.

    소스마다 조명·노출이 달라 같은 숫자가 다른 결과를 낸다. 그래서 값을 옮겨 심지 않고
    **결과 수치가 목표에 닿을 때까지 푼다**. 이게 '화면을 보고 맞춘다'의 구현이다.
    """
    dark = [(np.array(Image.open(p).convert("RGB")).astype(np.float32) @ LW) < 40
            for p in imgs]
    src = [np.array(Image.open(p).convert("RGB")) for p in imgs]
    cur = {k: (lo + hi) / 2 for k, (lo, hi) in KNOBS.items()}
    cur.update(whites=0.31, shadow_luma=0.3253, mid_luma=0.8995, high_luma=0.3317,
               contrast=0.15, skin_points=80.0, sat_ui=115.0, blue_points=15.0)

    def score(params):
        ms = [measure(full_grade(s, **params), d) for s, d in zip(src, dark)]
        avg = {k: float(np.mean([m[k] for m in ms])) for k in ms[0]}
        return cost(avg), avg

    best_c, best_m = score(cur)
    for _ in range(rounds):
        for k, (lo, hi) in KNOBS.items():
            span = (hi - lo) / 4
            for v in np.linspace(max(lo, cur[k] - span), min(hi, cur[k] + span), steps):
                trial = dict(cur, **{k: float(v)})
                c, m = score(trial)
                if c < best_c:
                    best_c, best_m, cur = c, m, trial
    return cur, best_m, best_c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--at", type=float, nargs="+", default=[120, 300, 480, 700])
    ap.add_argument("--preview", help="미리보기 저장 경로")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="tone_")
    fs = frames(a.source, a.at, tmp)
    if not fs:
        raise SystemExit("프레임을 못 뽑았다 — 경로와 --at 을 확인할 것")

    dark0 = (np.array(Image.open(fs[0]).convert("RGB")).astype(np.float32) @ LW) < 40
    before = measure(np.array(Image.open(fs[0]).convert("RGB")), dark0)
    print(f"원본  중앙값 {before['중앙값']:6.1f}  대비 {before['대비']:6.1f}  "
          f"어두운영역 {before['어두운영역']:5.1f}  피부채도 {before['피부채도']:5.1f}%  "
          f"날아감 {before['날아감']:.2f}%\n")

    params, got, c = solve(fs)
    print("푼 값:", {k: round(v, 3) for k, v in params.items()}, f"(비용 {c:.3f})")
    print("결과 :", " ".join(f"{k} {v:.2f}" for k, v in got.items()))
    print("목표 :", " ".join(f"{k} {v:.2f}" for k, v in TARGET.items()))

    out = a.preview or os.path.join(tmp, "solved.jpg")
    Image.fromarray(full_grade(np.array(Image.open(fs[len(fs) // 2]).convert("RGB")),
                               **params)).save(out, quality=93)
    print("\n미리보기:", out)
