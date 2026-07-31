"""화면을 보고 판단해서 잡는 색보정 — 고정값을 쓰지 않는다.

    python engine/eye_grade.py "<원본.MP4>" --at 189            # 프레임 뽑아 보정 + 미리보기
    python engine/eye_grade.py "<이미지>" -o out.jpg

**왜 고정값이 아닌가** (비블, 2026-07-31):

> "색보정에 고정값 같은 건 존재하지 않아. 모든 컷은 색상이 다 다르기 때문에 고정 값으로
> 보정해버리면 일관적인 색이 절대 나올 수가 없어. 니가 보고 인간의 눈으로 봤을 때 가장
> 화사하고 컬러풀한 예쁜 색을 스스로 판단해서 만들어주길 바래."

그래서 이 도구는 **소스를 재서 진단하고, 그 진단대로 잡는다.** 파라미터는 캐스트·노출·채도
측정에서 나오고, 마지막에 **60% 강도**로 섞는다. 100% 는 과하다(비블 확인).

## 작업 순서 — 이걸 지킬 것

1. 원본 프레임을 **직접 보고** 무엇이 문제인지 말로 진단한다 (녹색이 돈다 / 노출이 부족하다 …)
2. 그 진단대로 잡는다
3. **결과를 다시 보고** 스스로 비평한다 (아직 밋밋하다 / 피부가 뜬다 …)
4. 강도를 5단계로 나눠 비블에게 확인받는다

수치만 맞추면 실패한다 — 목표 수치를 세워 최적화했더니 "색보정이라 부를 수도 없다"는
평가를 받았다. **눈으로 보는 단계를 건너뛰지 말 것.**

## 용어 (비블 기준)

- **"블랙이 무겁다/뭉갠다"** = Lumetri **색상 휠 '어두운 영역'의 세로 막대바**를 올려라.
  화면 전체 저역을 들어올리는 토(toe) 리프트가 아니다 — 그건 화면이 뜬다.
- **"대비를 푼다"** = 대비를 **낮춘다**. 다만 낮추면 **화면 전체가 허옇게 뜬다**(비블 확인).
  → 창백함을 대비로 해결하려 하지 말 것.
- **"화사하다/컬러풀하다"** = 채도. 밝기가 아니다.
"""
import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

LW = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
STRENGTH = 0.60          # 비블 확정 — 100% 는 과하다

def neutral_mask(img):
    """원래 중성이어야 할 면(벽·천장). 나무·피부까지 끌어오면 화면이 죽는다."""
    f = img.astype(np.float32)
    mx, mn = f.max(2), f.min(2)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    l = f @ LW
    return (s < 0.14) & (l > np.percentile(l, 55)) & (l < 250)


def knee(x, t=0.80):
    """하이라이트를 눕혀 날아가지 않게."""
    return np.where(x > t, t + (1 - t) * np.tanh((x - t) / (1 - t)), x)


def skin_stats(img):
    """피부 영역의 평균 R·G·B 와 채도. **캠 매칭의 1순위 지표다.**

    벽만 맞추면 얼굴이 창백한 채로 남는다(실측) — 사람 얼굴이 화면의 중심이라
    피부가 안 맞으면 컷이 바뀔 때 바로 눈에 띈다.
    """
    x = img.astype(np.float32) / 255.0
    mx, mn = x.max(2), x.min(2)
    d = mx - mn
    h = np.zeros_like(mx)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    nz = d > 1e-6
    i = (mx == r) & nz; h[i] = ((g - b)[i] / d[i]) % 6
    i = (mx == g) & nz; h[i] = (b - r)[i] / d[i] + 2
    i = (mx == b) & nz; h[i] = (r - g)[i] / d[i] + 4
    h *= 60
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    m = ((h < 50) | (h > 345)) & (sat > 0.10) & (sat < 0.65) & (mx > 0.25)
    if m.sum() < 200:
        return None
    f = img.astype(np.float32)
    return dict(R=float(f[..., 0][m].mean()), G=float(f[..., 1][m].mean()),
                B=float(f[..., 2][m].mean()), sat=float(sat[m].mean() * 100),
                lum=float((f @ LW)[m].mean()), area=float(m.mean() * 100))


def diagnose(img):
    """원본을 재서 무엇이 문제인지 숫자로 잡는다."""
    f = img.astype(np.float32)
    l = f @ LW
    q = np.percentile(l, [1, 10, 50, 90, 99])
    mx, mn = f.max(2), f.min(2)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    m = neutral_mask(img)
    R, G, B = (f[..., c][m].mean() for c in range(3))
    return dict(p1=q[0], p10=q[1], median=q[2], p90=q[3], p99=q[4],
                sat=s.mean() * 100, wallR=R, wallG=G, wallB=B,
                green=G - (R + B) / 2, rb=R - B)


def correct(img, wb=1.0, whites=0.0, blacks=0.0, contrast=0.0,
            sat=1.0, skin=1.0, warm=0.0, tint=0.0):
    """warm = 주황↔파랑 (R/B 축) · tint = 마젠타↔초록 (G 축).

    **tint 가 없으면 창백함을 못 잡는다.** 피부가 핏기 없어 보이는 건 대개 G 가 높은
    것인데, warm 은 R 과 B 만 움직여서 손을 못 댄다(캠 매칭 실측: 피부 G 가 14.7 어긋남).
    """
    x = img.astype(np.float32) / 255.0
    if wb:                                   # ① 캐스트 제거 (벽 기준)
        m = neutral_mask(img)
        mean = np.array([x[..., c][m].mean() for c in range(3)])
        x = x * (1 + (mean.mean() / mean - 1) * wb)
    if warm:
        x[..., 0] *= 1 + warm * 0.01
        x[..., 2] *= 1 - warm * 0.01
    if tint:                                 # + = 마젠타(초록 빼기), − = 초록
        x[..., 1] *= 1 - tint * 0.01
        x[..., 0] *= 1 + tint * 0.004
        x[..., 2] *= 1 + tint * 0.004
    if whites:                               # ② 밝은 쪽만 (하이라이트는 니로 보호)
        w = np.clip((x @ LW - 0.30) / 0.70, 0, 1)[..., None] ** 0.7
        x = x * (1 + whites * w)
    if blacks:
        x = x + blacks * ((1 - np.clip(x @ LW, 0, 1)) ** 4)[..., None]
    if contrast:
        x = (x - 0.5) * (1 + contrast) + 0.5
    if sat != 1.0:                           # ③ 채도 — '화사함'은 여기서 나온다
        l = (x @ LW)[..., None]
        x = l + (x - l) * sat
    if skin != 1.0:
        mx, mn = x.max(2), x.min(2)
        d = mx - mn
        h = np.zeros_like(mx)
        r, g_, b = x[..., 0], x[..., 1], x[..., 2]
        nz = d > 1e-6
        i = (mx == r) & nz; h[i] = ((g_ - b)[i] / d[i]) % 6
        i = (mx == g_) & nz; h[i] = (b - r)[i] / d[i] + 2
        i = (mx == b) & nz; h[i] = (r - g_)[i] / d[i] + 4
        h *= 60
        sm = (((h < 50) | (h > 345)) & (d / np.maximum(mx, 1e-6) > 0.08) & (mx > 0.2))[..., None]
        l = (x @ LW)[..., None]
        x = np.where(sm, l + (x - l) * skin, x)
    return (np.clip(knee(x), 0, 1) * 255).astype(np.uint8)


def shadow_wheel(img, val, scale=0.18):
    """Lumetri '어두운 영역' 휠의 세로 막대바. 0.5 중앙, 올리면 섀도우만 열린다.

    **"블랙이 무겁다"는 이걸 말한다.** 밝기 중간 이상은 거의 안 건드려서 벽·흰옷은
    그대로 두고 머리카락·정장만 열린다.
    """
    x = img.astype(np.float32) / 255.0
    sh = np.clip(1.0 - (x @ LW) * 2.0, 0, 1)[..., None]
    return (np.clip(knee(x + sh * ((val - 0.5) * 2.0 * scale)), 0, 1) * 255).astype(np.uint8)


def auto(img, strength=STRENGTH):
    """진단 → 보정 → strength 로 섞기. 파라미터가 소스에서 나온다."""
    d = diagnose(img)
    # 노출이 모자란 만큼만 올린다 (p90 을 205 근처로)
    whites = float(np.clip((205 - d["p90"]) / 100.0, 0.0, 0.45))
    # 채도가 낮을수록 더 올린다 (목표 24% 안팎)
    sat = float(np.clip(24.0 / max(d["sat"], 1.0), 1.0, 1.8))
    full = correct(img, wb=1.0, whites=whites, blacks=0.02, contrast=0.10,
                   sat=sat, skin=1.30, warm=2.5)
    blend = img.astype(np.float32) * (1 - strength) + full.astype(np.float32) * strength
    return np.clip(blend, 0, 255).astype(np.uint8), dict(whites=whites, sat=sat)


def yellow_shift(img, amt):
    """붉은 기를 빼고 노랑 쪽으로. R 내리고 G 올리고 B 내린다.

    캠 매칭 마무리에서 쓴다 — warm(R/B 축)·tint(G 축)만으로는 '마젠타가 높다'는
    지적을 못 잡는 경우가 있어서, 세 채널을 한 방향으로 같이 미는 축을 따로 뒀다.
    **블렌드 뒤에 적용한다**(순서가 바뀌면 결과가 달라진다).
    """
    if not amt:
        return img
    f = img.astype(np.float32) / 255.0
    f[..., 0] *= 1 - amt * 0.004
    f[..., 1] *= 1 + amt * 0.006
    f[..., 2] *= 1 - amt * 0.010
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def grade_cam(img, p):
    """캠 프리셋 한 벌을 그대로 적용한다 — 보정 → 강도 블렌드 → 노랑 마무리.

    `profiles/<프로파일>/cam_presets.json` 의 값을 그대로 받는다.
    **순서를 바꾸지 말 것.**
    """
    full = correct(img, wb=p.get("wb", 1.0), whites=p.get("whites", 0.0),
                   blacks=p.get("blacks", 0.0), contrast=p.get("contrast", 0.0),
                   sat=p.get("sat", 1.0), skin=p.get("skin", 1.0),
                   warm=p.get("warm", 0.0), tint=p.get("tint", 0.0))
    s = p.get("strength", STRENGTH)
    out = np.clip(img.astype(np.float32) * (1 - s) + full.astype(np.float32) * s, 0, 255)
    return yellow_shift(out.astype(np.uint8), p.get("yellow", 0.0))


def report(img, tag):
    d = diagnose(img)
    mx = img.astype(np.float32).max(2)
    print(f"  {tag:<16} 중앙{d['median']:5.0f} p90{d['p90']:5.0f} p10{d['p10']:4.0f} "
          f"채도{d['sat']:5.1f}%  벽 R{d['wallR']:5.1f} G{d['wallG']:5.1f} B{d['wallB']:5.1f}"
          f"  날아감{(mx>=254).mean()*100:4.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="영상 또는 이미지")
    ap.add_argument("--at", type=float, default=None, help="영상이면 이 시각(초)의 프레임")
    ap.add_argument("-o", "--out", default="graded.jpg")
    ap.add_argument("--strength", type=float, default=STRENGTH)
    a = ap.parse_args()

    src_path = a.source
    if a.at is not None:
        tmp = tempfile.mkdtemp(prefix="eye_")
        src_path = os.path.join(tmp, "f.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a.at), "-i", a.source,
                        "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "2",
                        "-y", src_path], check=False)

    src = np.array(Image.open(src_path).convert("RGB"))
    out, used = auto(src, a.strength)
    report(src, "원본")
    report(out, f"보정 {int(a.strength*100)}%")
    print(f"  (측정에서 나온 값) whites={used['whites']:.3f}  sat={used['sat']:.2f}")
    Image.fromarray(out).save(a.out, quality=94)
    print(f"\n저장: {a.out}")
