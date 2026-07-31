"""두 캠을 같은 톤·밝기로 맞춘다 — **기준 캠 대비 상대 매칭**이 기본이다.

    python engine/match_cams.py "<cam01.MP4>" "<cam02.MP4>" --at 300 600 900

**왜 상대 매칭인가** (비블, 2026-07-31): **"고정 값이라는 건 존재하지 않는다.
도착점도 외부에서 찍느냐 노출이 강한 곳에서 찍느냐에 따라 전부 달라진다."**

절대 목표(저장된 수치)로 수렴시키면 실내 스튜디오에서만 맞는다. 야외·역광이면
`neutral_mask` 가 하늘이나 바닥을 '중성면'으로 잡고, 중앙값 같은 절대 밝기도 의미가 없다.
**반면 "cam02 를 cam01 에 맞춘다"는 환경이 바뀌어도 항상 유효하다** — 상대값이니까.

그래서 기본 동작은 `--ref-cam 1`(첫 캠 기준)이다. 기준 캠 자체는 소스를 재서 스스로 잡고
(`eye_grade`), 나머지 캠은 그 **결과**에 맞춘다.

**맞추는 우선순위: 피부톤 → 벽 → 밝기.** 벽만 맞추면 얼굴이 창백하게 남는다(실측 피부 G
14.7 차이). 프레이밍이 다르면 `p90` 은 뺀다 — 밝은 영역 비율이 달라 오히려 어긋난다.
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
    ap.add_argument("--ref-cam", type=int, default=1,
                    help="이 캠(1부터)의 보정 결과를 기준으로 나머지를 맞춘다 (기본 1)")
    ap.add_argument("--use-stored-target", action="store_true",
                    help="저장된 도착점(tone_reference.json)으로 수렴시킨다. "
                         "**실내 스튜디오 전용** — 환경이 다르면 쓰지 말 것")
    a = ap.parse_args()

    tmp = a.outdir or tempfile.mkdtemp(prefix="match_")
    os.makedirs(tmp, exist_ok=True)
    if a.use_stored_target:
        target = load_target(a.profile)
        print("[주의] 저장된 도착점으로 수렴시킨다 — 260729 실내 스튜디오 기준이다.")
        print("       야외·역광·노출이 다른 환경이면 이 숫자는 맞지 않는다.")
        print("목표:", " ".join(f"{k} {v}" for k, v in target.items()))
        a.ref_cam = None
    else:
        target = None
        print(f"기준 캠: cam{a.ref_cam} (상대 매칭 — 환경이 바뀌어도 유효하다)")

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
