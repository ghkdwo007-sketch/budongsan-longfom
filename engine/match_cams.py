"""두 캠을 같은 톤·밝기로 맞춘다.

    python engine/match_cams.py "<cam01.MP4>" "<cam02.MP4>" --at 300 600 900

**왜 '각 캠에 60% 적용'으로는 안 맞나** — 60% 는 *그 소스 기준의 상대량*이라, 캐스트와
노출이 다른 두 캠에 각각 60% 를 먹이면 **도착점이 서로 다르다.** 캠 매칭은 상대량이 아니라
**같은 도착점으로 수렴시키는 문제**다.

그래서 이 도구는 캠마다 **따로** 푼다 — 목표는 하나, 파라미터는 캠별로 다르게.
목표는 `profiles/<프로파일>/tone_reference.json` 의 '도착점'이고, 그건 비블이
"거의 완벽하다"고 확인한 화면의 수치다.

맞추는 항목: 벽(중성면) R·G·B · 루마 중앙값 · p90 · 화면 채도.
**벽을 맞추는 게 제일 중요하다** — 두 캠의 벽 색이 다르면 컷이 바뀔 때마다 색이 튄다.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from eye_grade import correct, diagnose, neutral_mask, skin_stats, LW

KNOBS = {"warm": (-8.0, 8.0), "tint": (-8.0, 12.0), "whites": (0.0, 0.50),
         "sat": (1.0, 2.0), "skin": (1.0, 2.0),
         "contrast": (0.0, 0.25), "strength": (0.35, 1.0)}


def load_target(profile="부동산롱폼"):
    import config
    d = config._find_profile_dir(PROJ, profile)
    with open(os.path.join(d, "tone_reference.json"), encoding="utf-8") as f:
        return json.load(f)["도착점"]


def frames(src, times, outdir, tag, width=960):
    out = []
    for t in times:
        p = os.path.join(outdir, f"{tag}_{int(t)}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src,
                        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2",
                        "-y", p], check=False)
        if os.path.exists(p):
            out.append(p)
    return out


def apply(img, p):
    full = correct(img, wb=1.0, whites=p["whites"], blacks=0.0,
                   contrast=p["contrast"], sat=p["sat"], skin=p.get("skin", 1.35),
                   warm=p["warm"], tint=p.get("tint", 0.0))
    s = p["strength"]
    return np.clip(img.astype(np.float32) * (1 - s) + full.astype(np.float32) * s,
                   0, 255).astype(np.uint8)


def cost(imgs, p, target, use_p90=True):
    """target 은 tone_reference 의 '도착점' 형식.

    `use_p90=False` 는 **기준 캠에 맞출 때** 쓴다 — 캠마다 프레이밍이 달라
    밝은 영역 비율이 다르므로 p90 을 강제하면 오히려 어긋난다(실측 차이 20.8).
    프레이밍에 안 흔들리는 건 **벽(중성면) 색**이라 그걸 주 지표로 삼는다.
    """
    graded = [apply(im, p) for im in imgs]
    ds = [diagnose(g) for g in graded]
    m = {k: float(np.mean([d[k] for d in ds]))
         for k in ("median", "p90", "sat", "wallR", "wallG", "wallB")}
    sk = [skin_stats(g) for g in graded]
    sk = [x for x in sk if x]
    if sk:
        for k in ("R", "G", "B", "lum", "sat"):
            m["skin" + k] = float(np.mean([x[k] for x in sk]))
    c = 0.0
    c += ((m["median"] - target["중앙값"]) / 6.0) ** 2
    if use_p90:
        c += ((m["p90"] - target["p90"]) / 10.0) ** 2
    c += ((m["sat"] - target["화면채도"]) / 1.5) ** 2
    # 벽은 개별 채널로 맞춘다 — 평균만 맞으면 캠끼리 색이 어긋난다
    for k, t in (("wallR", "벽R"), ("wallG", "벽G"), ("wallB", "벽B")):
        c += ((m[k] - target[t]) / 2.0) ** 2 * 2.0
    # **피부톤이 1순위다.** 벽만 맞추면 얼굴이 창백한 채로 남는다(비블 지적).
    for k, t in (("skinR", "피부R"), ("skinG", "피부G"), ("skinB", "피부B"),
                 ("skinlum", "피부밝기"), ("skinsat", "피부채도")):
        if k in m and t in target:
            c += ((m[k] - target[t]) / 2.5) ** 2 * 3.0
    return c, m


def as_target(stats):
    """diagnose 평균값 → target 형식으로."""
    t = {"중앙값": stats["median"], "p90": stats["p90"], "화면채도": stats["sat"],
         "벽R": stats["wallR"], "벽G": stats["wallG"], "벽B": stats["wallB"]}
    for k, n in (("skinR", "피부R"), ("skinG", "피부G"), ("skinB", "피부B"),
                 ("skinlum", "피부밝기"), ("skinsat", "피부채도")):
        if k in stats:
            t[n] = stats[k]
    return t


def solve(imgs, target, rounds=4, steps=5, use_p90=True, start=None):
    cur = dict(start or {"warm": 4.0, "tint": 0.0, "whites": 0.30, "sat": 1.375,
                         "skin": 1.35, "contrast": 0.08, "strength": 0.60})
    best, bm = cost(imgs, cur, target, use_p90)
    for _ in range(rounds):
        for k, (lo, hi) in KNOBS.items():
            span = (hi - lo) / 4
            for v in np.linspace(max(lo, cur[k] - span), min(hi, cur[k] + span), steps):
                t = dict(cur, **{k: float(v)})
                c, m = cost(imgs, t, target, use_p90)
                if c < best:
                    best, bm, cur = c, m, t
    return cur, bm, best


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cams", nargs="+", help="캠 원본 파일들 (2개 이상)")
    ap.add_argument("--at", type=float, nargs="+", default=[300, 600, 900])
    ap.add_argument("--profile", default="부동산롱폼")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--ref-cam", type=int, default=None,
                    help="이 캠(1부터)의 보정 결과를 기준으로 나머지를 맞춘다")
    a = ap.parse_args()

    target = load_target(a.profile)
    tmp = a.outdir or tempfile.mkdtemp(prefix="match_")
    os.makedirs(tmp, exist_ok=True)
    print("목표(도착점):", " ".join(f"{k} {v}" for k, v in target.items()))

    # 기준 캠이 지정되면 그 캠을 먼저 풀고, 그 **결과**를 나머지의 목표로 삼는다.
    # 저장된 도착점보다 실제 화면이 낫다고 비블이 판단하면 이 모드를 쓴다.
    order = list(enumerate(a.cams, 1))
    if a.ref_cam:
        order.sort(key=lambda x: (x[0] != a.ref_cam))

    results = {}
    for i, cam in order:
        fs = frames(cam, a.at, tmp, f"cam{i}")
        if not fs:
            print(f"\ncam{i}: 프레임 실패 — 경로/--at 확인"); continue
        imgs = [np.array(Image.open(p).convert("RGB")) for p in fs]
        before = {k: float(np.mean([diagnose(im)[k] for im in imgs]))
                  for k in ("median", "p90", "sat", "wallR", "wallG", "wallB")}
        if a.ref_cam and i != a.ref_cam and f"cam{a.ref_cam}" in results:
            tgt = as_target(results[f"cam{a.ref_cam}"]["got"])
            p, got, c = solve(imgs, tgt, use_p90=False)   # 프레이밍이 달라 p90 은 뺀다
            print(f"\n  (기준: cam{a.ref_cam} 의 보정 결과)")
        else:
            p, got, c = solve(imgs, target)
        results[f"cam{i}"] = dict(params=p, got=got)
        print(f"\ncam{i}  {os.path.basename(cam)}")
        print(f"  전  중앙{before['median']:6.1f} p90{before['p90']:6.1f} 채도{before['sat']:5.1f}%"
              f"  벽 R{before['wallR']:6.1f} G{before['wallG']:6.1f} B{before['wallB']:6.1f}")
        print(f"  후  중앙{got['median']:6.1f} p90{got['p90']:6.1f} 채도{got['sat']:5.1f}%"
              f"  벽 R{got['wallR']:6.1f} G{got['wallG']:6.1f} B{got['wallB']:6.1f}   (비용 {c:.2f})")
        if "skinR" in got:
            print(f"  피부 R{got['skinR']:6.1f} G{got['skinG']:6.1f} B{got['skinB']:6.1f}"
                  f"  밝기{got['skinlum']:6.1f}  채도{got['skinsat']:5.1f}%")
        print(f"  값  " + " ".join(f"{k}={v:.3f}" for k, v in p.items()))
        Image.fromarray(apply(imgs[len(imgs) // 2], p)).save(
            os.path.join(tmp, f"cam{i}_graded.jpg"), quality=94)

    if len(results) >= 2:
        ks = list(results)
        g = [results[k]["got"] for k in ks]
        print("\n=== 캠 간 차이 (작을수록 잘 맞은 것) ===")
        for f, t in (("median", "중앙값"), ("p90", "p90"), ("sat", "채도"),
                     ("wallR", "벽R"), ("wallG", "벽G"), ("wallB", "벽B"),
                     ("skinR", "피부R"), ("skinG", "피부G"), ("skinB", "피부B"),
                     ("skinlum", "피부밝기"), ("skinsat", "피부채도")):
            if not all(f in x for x in g):
                continue
            sp = max(x[f] for x in g) - min(x[f] for x in g)
            print(f"  {t:<7} {sp:5.2f}")
    print(f"\n미리보기 폴더: {tmp}")
