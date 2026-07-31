"""학습한 cam01 Lumetri 값을 스틸에 재현한다.

읽어낸 값 (미보정 기준선 대비):
  크리에이티브 채도  163.23 → 127.74  = ×0.783
  색상 휠 (각도°, 루마, 채도)
     어두운 영역  35.29  0.032  0.115
     미드톤       21.72  0.846  0.191
     밝은 영역    20.65  0.940  0.100

여기에 비블 피드백 4회를 반영한 게 `RECIPE`/`full_grade()` 다 — 스틸에 먹여 확인받은 값이다.

    python engine/apply_grade_still.py <이미지>            # 확정 레시피 적용
    python engine/apply_grade_still.py <이미지> --compare  # 단계별 비교 시트

각도 0° 기준(빨강, 양수=주황)은 비블이 골라 확정했다. **아직 미확인은 휠 루마 0~1 의
실제 스톱 환산 하나**다(`--luma-scale`). 프리미어에서 보정본 프레임을 뽑아 원본과
픽셀 비교하면 역산된다.
"""
import argparse
import sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

SAT_MUL = 127.74 / 163.23           # 0.7826
WHEELS = [("어두운 영역", 35.29, 0.032, 0.115),
          ("미드톤", 21.72, 0.846, 0.191),
          ("밝은 영역", 20.65, 0.940, 0.100)]

# 각도 → RGB 방향. **0° = 빨강, 양수 = 노랑 쪽(주황/웜)** 으로 확정했다.
# 비블이 세 후보 중 +35.3°(주황) 를 골랐다 — R+0.66 G+0.08 B-0.75 로
# 파란 기를 빼고 붉은 기를 올리는 방향이다.
TINTS = {
    "warm":    lambda a: _hue_rgb(a * +1.0),   # 주황 — 확정
    "magenta": lambda a: _hue_rgb(a * -1.0),   # 핑크 — 기각
    "none":    lambda a: np.zeros(3),
}


def _hue_rgb(deg):
    """빨강(0°)을 기준으로 deg 만큼 돌린 방향의 단위 색 벡터 (합 0 = 밝기 보존)."""
    import colorsys
    h = (deg % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
    v = np.array([r, g, b]) - np.mean([r, g, b])
    n = np.linalg.norm(v)
    return v / n if n else v


def zone_weights(luma):
    """섀도우/미드/하이라이트 가중치 (합 = 1)."""
    sh = np.clip(1.0 - luma * 2.0, 0, 1)
    hi = np.clip(luma * 2.0 - 1.0, 0, 1)
    return sh, 1.0 - sh - hi, hi


def grade(img, tint="warm", luma_scale=0.18, sat_mul=SAT_MUL, tint_scale=0.35):
    x = img.astype(np.float32) / 255.0
    luma = x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    sh, mid, hi = (w[..., None] for w in zone_weights(luma))

    # ① 휠 루마 — 0.5 를 중립으로 보고 편차를 밝기 오프셋으로
    off = np.zeros_like(x)
    tint_vec = np.zeros_like(x)
    for (name, ang, lum, sat), w in zip(WHEELS, (sh, mid, hi)):
        off += w * ((lum - 0.5) * 2.0 * luma_scale)
        tint_vec += w * (TINTS[tint](ang) * sat * tint_scale)
    x = x + off + tint_vec

    # ② 전체 채도 — 크리에이티브 채도 비율
    l2 = (x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
    x = l2 + (x - l2) * sat_mul

    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


def neutral_mask(img):
    """원래 중성이어야 할 면(벽·천장)만 고른다 — 밝고 채도 낮은 픽셀.

    전체 평균(grey-world)으로 화이트밸런스를 잡으면 나무 책상·피부·초록 셔츠 같은
    '원래 유채색인 것'까지 중성으로 끌고 가서 화면이 죽는다. 벽을 기준으로 잡아야 한다.
    """
    f = img.astype(np.float32)
    mx, mn = f.max(2), f.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    lum = f @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return (sat < 0.12) & (lum > np.percentile(lum, 60)) & (lum < 250)


def whitebalance(img):
    """중성면의 R·G·B 평균이 같아지도록 채널 게인을 건다 = 캐스트 제거.

    비블의 제1원칙("지배적인 캐스트를 걷어내 중성으로")을 그대로 구현한 것이다.
    소스가 무슨 색으로 치우쳤든 알아서 반대로 민다 — 값을 복사하지 않는다.
    """
    f = img.astype(np.float32)
    m = neutral_mask(img)
    means = np.array([f[..., c][m].mean() for c in range(3)])
    return np.clip(f * (means.mean() / means), 0, 255).astype(np.uint8)


def stats(img, label):
    f = img.astype(np.float32)
    l = f @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mx = f.max(2)
    mn = f.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    print(f"  {label:<16} 밝기 평균 {l.mean():6.2f}  R{f[...,0].mean():6.2f} "
          f"G{f[...,1].mean():6.2f} B{f[...,2].mean():6.2f}  채도 {sat.mean()*100:5.2f}%  "
          f"R-B {f[...,0].mean()-f[...,2].mean():+6.2f}")



# ── 확정 레시피 (2026-07-30, 비블이 스틸 테스트로 고른 값) ──────────────
# 읽어낸 값에서 출발해 피드백 4회를 반영한 최종본. 자세한 근거는 프로파일 README.
RECIPE = dict(tint="warm", luma_scale=0.18, tint_scale=0.27,
              sat_ui=98, whites=0.12, blue_points=5, skin_points=40)


def knee(x, t=0.85):
    """소프트 니 — 밝은 쪽 곡선을 눕혀 하이라이트가 날아가지 않게."""
    return np.where(x > t, t + (1 - t) * np.tanh((x - t) / (1 - t)), x)


def lift_whites(img, amount):
    """흰색(화이트포인트)을 올려 밝게. 채널 동일 배율이라 색균형은 유지된다."""
    x = img.astype(np.float32) / 255.0
    w = np.clip((x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) - 0.25) / 0.75, 0, 1) ** 0.8
    return (np.clip(knee(x * (1.0 + amount * w)[..., None]), 0, 1) * 255).astype(np.uint8)


def blue_tint(img, points):
    """중화가 끝난 뒤 취향으로 아주 살짝 쿨하게. 1포인트 = R,B 를 각 0.2% 반대로.

    **니를 안 걸면 이미 밝던 파랑이 254 를 넘어 7% 가 날아간다**(실측).
    """
    k = points * 0.002
    x = img.astype(np.float32) / 255.0
    x[..., 0] *= (1 - k)
    x[..., 2] *= (1 + k)
    return (np.clip(knee(x), 0, 1) * 255).astype(np.uint8)


def _hsv(img):
    x = img.astype(np.float32) / 255.0
    mx, mn = x.max(2), x.min(2)
    d = mx - mn
    h = np.zeros_like(mx)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    nz = d > 1e-6
    i = (mx == r) & nz; h[i] = ((g - b)[i] / d[i]) % 6
    i = (mx == g) & nz; h[i] = (b - r)[i] / d[i] + 2
    i = (mx == b) & nz; h[i] = (r - g)[i] / d[i] + 4
    return h * 60, np.where(mx > 0, d / np.maximum(mx, 1e-6), 0), mx


def skin_mask(img):
    """피부톤 — 색상 0~45°, 채도 0.12~0.65, 명도 0.25 이상."""
    h, s, v = _hsv(img)
    return ((h < 45) | (h > 350)) & (s > 0.12) & (s < 0.65) & (v > 0.25)


def boost_skin(img, points):
    """피부톤만 채도를 올린다 (Lumetri 의 HSL 보조에 해당).

    전체 채도로 올리면 초록 셔츠·모니터 UI 까지 따라 오르고, 무엇보다
    **블루 틴트가 같이 증폭돼 어렵게 맞춘 중성이 밀린다**(실측 R−B −2.51 → −3.35).
    피부만 올리면 중성면은 −2.15 로 고정된 채 피부만 산다.
    """
    x = img.astype(np.float32) / 255.0
    m = skin_mask(img)[..., None]
    lum = (x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
    boosted = lum + (x - lum) * (1 + points / 100.0)
    return (np.clip(knee(np.where(m, boosted, x)), 0, 1) * 255).astype(np.uint8)


def full_grade(src, **kw):
    """확정 레시피 전체. **순서가 중요하다** — 중성화가 먼저, 스타일은 그 위에."""
    r = dict(RECIPE, **kw)
    x = grade(src, tint=r["tint"], luma_scale=r["luma_scale"],
              sat_mul=r["sat_ui"] / 100.0, tint_scale=r["tint_scale"])
    x = whitebalance(x)                              # ③ 캐스트 제거
    x = whitebalance(lift_whites(x, r["whites"]))    # ④ 밝기 (올린 뒤 다시 중성화)
    x = blue_tint(x, r["blue_points"])               # ⑥ 아주 살짝 쿨하게
    return boost_skin(x, r["skin_points"])           # ⑦ 피부만 살리기


def report(img, label):
    """중성면 편차와 '날아간 픽셀'까지 같이 본다 — 둘 다 매번 확인할 것."""
    f = img.astype(np.float32)
    lum = f @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    nm = [f[..., c][neutral_mask(img)].mean() for c in range(3)]
    mx, mn = f.max(2), f.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    sk = skin_mask(img)
    print(f"  {label:<16} 밝기 {lum.mean():6.2f}  채도 {sat.mean()*100:5.2f}%  "
          f"피부채도 {sat[sk].mean()*100:5.2f}%  중성면 R−B {nm[0]-nm[2]:+5.2f}  "
          f"날아감 {(mx >= 254).mean()*100:4.2f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default="graded.png")
    ap.add_argument("--compare", action="store_true", help="단계별 비교 시트도 저장")
    for k, v in (("luma-scale", 0.18), ("tint-scale", 0.27), ("whites", 0.12),
                 ("sat-ui", 98.0), ("blue-points", 5.0), ("skin-points", 40.0)):
        ap.add_argument(f"--{k}", type=float, default=v)
    a = ap.parse_args()

    src = np.array(Image.open(a.src).convert("RGB"))
    out = full_grade(src, luma_scale=a.luma_scale, tint_scale=a.tint_scale,
                     whites=a.whites, sat_ui=a.sat_ui,
                     blue_points=a.blue_points, skin_points=a.skin_points)
    print(f"원본 {src.shape[1]}x{src.shape[0]}\n")
    report(src, "원본(미보정)")
    report(out, "확정 레시피")
    Image.fromarray(out).save(a.out)
    print(f"\n저장: {a.out}")

    if a.compare:
        h, w = src.shape[:2]
        gap = 8
        sheet = np.full((h, w * 2 + gap, 3), 24, dtype=np.uint8)
        sheet[:, :w], sheet[:, w + gap:] = src, out
        Image.fromarray(sheet).save("compare.png")
        print("저장: compare.png")
