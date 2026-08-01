"""색보정을 프리미어에서 쓸 수 있는 .cube 3D LUT 로 굽는다.

    python engine/make_lut.py <프리셋.json> --ref-cam01 <cam01프레임> --ref-cam02 <cam02프레임>

**왜 LUT 인가** — `_grade_preset.json` 의 값(`skin_dr`, `skin_smin` …)은 이 엔진의
파라미터라서 Lumetri 슬라이더와 1:1 로 대응하지 않는다. 손으로 옮기면 반드시 어긋난다.
반면 이 보정은 화이트밸런스 게인만 고정하면 **전부 픽셀 단위 색 변환**이다 —
피부 보정도 HSV 조건(색상<45° 또는 >350°, 채도·명도 범위)이라 공간 정보가 아니다.
그래서 3D LUT 로 정확히 담긴다.

**화이트밸런스만 프레임 의존적이다.** `neutral_mask` 로 그 프레임의 벽 픽셀을 찾아
채널 평균을 맞추는데, 결과는 결국 RGB 게인 3개다. 참고 프레임에서 한 번 재서 굽는다.
→ **조명이 바뀌면 LUT 를 다시 구워야 한다.** 같은 회차·같은 세팅 안에서만 유효하다.

프리미어 적용: Lumetri > 크리에이티브 > Look > 찾아보기 에서 .cube 선택.
(기본 교정 > 입력 LUT 는 로그 소스 변환용이라 여기서는 크리에이티브 쪽을 쓴다)
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import eye_grade as E
import apply_grade_still as G

LW = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def wb_gains(img):
    """참고 프레임의 벽(중성면)에서 채널 게인을 뽑는다. 이후엔 상수로 쓴다."""
    x = img.astype(np.float32) / 255.0
    m = E.neutral_mask(img)
    if m.sum() < 100:
        print("  [주의] 중성면 픽셀이 부족하다 — 화이트밸런스 없이 굽는다", file=sys.stderr)
        return np.ones(3, dtype=np.float32)
    mean = np.array([x[..., c][m].mean() for c in range(3)], dtype=np.float32)
    return (mean.mean() / mean).astype(np.float32)


def grade_rgb(x, p, gains):
    """0~1 RGB 배열(…,3) → 보정된 0~1 RGB. **픽셀 단위 순수 함수.**

    engine/grade_260415.py 의 apply() 와 같은 순서·같은 수식이다.
    한쪽만 고치면 LUT 와 스틸이 갈라지므로 바꿀 때는 둘 다 본다.
    """
    x = x * gains                                             # ① 캐스트 제거(게인 고정)

    w = np.clip((x @ LW - 0.30) / 0.70, 0, 1)[..., None] ** 0.7
    x = x * (1 + p["whites"] * w)                             # ② 밝은 쪽만
    x = x + p["blacks"] * ((1 - np.clip(x @ LW, 0, 1)) ** 4)[..., None]
    x = (x - 0.5) * (1 + p["contrast"]) + 0.5                 # ③ 대비
    l = (x @ LW)[..., None]
    x = l + (x - l) * p["sat"]                                # ④ 전체 채도
    x = np.clip(E.knee(x), 0, 1)                              # 하이라이트 니

    # ⑤ 피부만 — 마스크는 0~255 기준 HSV 라 스틸 코드와 같게 맞춘다.
    # _hsv 는 (H,W,3) 을 기대하므로 평평한 격자는 잠시 2D 로 세워서 넘긴다.
    u8 = (x * 255).astype(np.uint8)
    flat = u8.ndim == 2
    h, s, v = G._hsv(u8[:, None, :] if flat else u8)
    if flat:
        h, s, v = h[:, 0], s[:, 0], v[:, 0]
    sk = (((h < 45) | (h > 350)) & (s > p["skin_smin"]) & (s < 0.65) & (v > 0.25))
    y = x * 255.0
    y[..., 0] += p["skin_dr"] * sk
    y[..., 2] -= p["skin_db"] * sk
    ll = (y @ LW)[..., None]
    y = np.where(sk[..., None], ll + (y - ll) * p["skin_sat"], y)
    x = np.clip(y / 255.0, 0, 1)

    if p.get("gamma", 1.0) != 1.0:                            # ⑥ 미드톤
        x = np.power(x, 1.0 / p["gamma"])
    return np.clip(x, 0, 1)


def build_cube(p, gains, size=33):
    """N^3 격자를 굽는다. .cube 는 R 이 가장 빨리 도는 순서다."""
    g = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")            # b 가 가장 느리게
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    return grade_rgb(grid, p, gains)


def write_cube(path, table, size, title):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"TITLE \"{title}\"\n")
        f.write(f"LUT_3D_SIZE {size}\n")
        f.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n\n")
        for v in table:
            f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")


def apply_cube(img, table, size):
    """트라이리니어 보간으로 LUT 를 적용 — 굽힌 결과를 검증하는 용도."""
    x = img.astype(np.float32) / 255.0
    idx = x * (size - 1)
    lo = np.floor(idx).astype(np.int32)
    lo = np.clip(lo, 0, size - 2)
    fr = idx - lo
    t = table.reshape(size, size, size, 3)                    # [b, g, r]

    def at(dr, dg, db):
        return t[np.clip(lo[..., 2] + db, 0, size - 1),
                 np.clip(lo[..., 1] + dg, 0, size - 1),
                 np.clip(lo[..., 0] + dr, 0, size - 1)]

    wr, wg, wb_ = fr[..., 0:1], fr[..., 1:2], fr[..., 2:3]
    c00 = at(0, 0, 0) * (1 - wr) + at(1, 0, 0) * wr
    c01 = at(0, 0, 1) * (1 - wr) + at(1, 0, 1) * wr
    c10 = at(0, 1, 0) * (1 - wr) + at(1, 1, 0) * wr
    c11 = at(0, 1, 1) * (1 - wr) + at(1, 1, 1) * wr
    c0 = c00 * (1 - wg) + c10 * wg
    c1 = c01 * (1 - wg) + c11 * wg
    return np.clip((c0 * (1 - wb_) + c1 * wb_) * 255, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preset")
    ap.add_argument("--ref", action="append", default=[],
                    help="cam01=프레임.png 형식. 캠마다 하나씩")
    ap.add_argument("--size", type=int, default=33)
    ap.add_argument("-o", "--outdir", default=".")
    a = ap.parse_args()

    preset = json.load(open(a.preset, encoding="utf-8"))
    for spec in a.ref:
        cam, path = spec.split("=", 1)
        p = preset[cam]
        img = np.array(Image.open(path).convert("RGB"))
        gains = wb_gains(img)
        print(f"{cam}  화이트밸런스 게인 R{gains[0]:.4f} G{gains[1]:.4f} B{gains[2]:.4f}")
        table = build_cube(p, gains, a.size)
        out = os.path.join(a.outdir, f"{cam}.cube")
        write_cube(out, table, a.size, f"{cam} — {preset.get('_회차', '')}")

        # 검증: LUT 결과 vs 직접 계산 결과
        direct = (grade_rgb(img.astype(np.float32) / 255.0, p, gains) * 255).astype(np.uint8)
        viaLut = apply_cube(img, table, a.size)
        d = np.abs(direct.astype(np.int16) - viaLut.astype(np.int16))
        print(f"  {os.path.basename(out)}  {a.size}^3  "
              f"LUT 오차 평균 {d.mean():.2f} · 최대 {d.max()} (0~255)")


if __name__ == "__main__":
    main()
