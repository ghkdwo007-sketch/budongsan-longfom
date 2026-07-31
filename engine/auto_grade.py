"""소스를 재서 색보정을 스스로 잡고 프리미어에 넣는다.

    python engine/auto_grade.py "<원본.MP4>" "<시퀀스 이름 일부>"
    python engine/auto_grade.py "<원본.MP4>" "<시퀀스>" --preview-only   # 프리미어 없이 미리보기만

**무엇이 자동이고 무엇이 고정인가** — 비블이 잡아 준 값을 뜯어보면 두 종류가 섞여 있다.

  캐스트 중화 (온도·색조)   소스마다 달라져야 한다 → **측정해서 계산**
  톤 (색상 휠·채도·흰색·검정)  회차가 바뀌어도 유지하는 '룩' → **고정값 재사용**

제1원칙("색을 입히는 게 아니라 지배적인 캐스트를 걷어내 중성으로")이 그대로 이 구조다.

**한계**: 프리미어는 프레임 내보내기를 지원하지 않아(`export_frame` 은 성공이라 응답하고
파일을 안 만들고, ExtendScript 에도 `exportFramePNG` 가 없다) **결과를 스스로 검증할 수 없다.**
그래서 소스 프레임으로 미리보기 이미지를 만들어 보여주고, 최종 판단은 비블이 화면으로 한다.
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

from apply_grade_still import neutral_mask
from apply_grade_premiere import load_grade, apply, read_back
from premiere_mcp import Premiere

LW = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# 단일 회차(260630) 로 잡은 1점 교정이다 — 캐스트 편차(%)를 Lumetri 눈금으로 옮기는 계수.
# 그 회차는 녹색 초과 +4.2% 에 색조 +8, R−B 초과 +1.25% 에 온도 −4 였다.
# 회차가 쌓이면 다시 맞출 것. 프리미어 출력을 못 재서 이보다 정밀하게는 못 간다.
TINT_PER_PCT = 1.9      # 녹색 초과 1% 당 색조
TEMP_PER_PCT = -3.2     # R−B 초과 1% 당 온도


def sample_frames(src, times, outdir):
    """ffmpeg 로 대표 프레임을 뽑는다."""
    paths = []
    for t in times:
        p = os.path.join(outdir, f"ag_{int(t)}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src,
                        "-frames:v", "1", "-q:v", "2", "-y", p],
                       check=False, encoding="utf-8")
        if os.path.exists(p):
            paths.append(p)
    return paths


def measure_cast(paths):
    """중성면(벽·천장)의 채널 평균으로 캐스트를 잰다.

    전체 평균(grey-world)이 아니라 '원래 중성인 면'을 쓴다 — 나무 책상·피부·옷까지
    중성으로 끌고 가면 화면이 죽는다.
    """
    rows = []
    for p in paths:
        img = np.array(Image.open(p).convert("RGB"))
        f = img.astype(np.float32)
        m = neutral_mask(img)
        if m.sum() < 1000:
            continue
        rows.append([f[..., c][m].mean() for c in range(3)])
    if not rows:
        raise SystemExit("중성면을 못 찾았다 — 벽처럼 무채색인 면이 보이는 구간을 --at 으로 지정할 것")
    R, G, B = np.mean(rows, axis=0)
    mean = (R + G + B) / 3
    return dict(R=R, G=G, B=B,
                green_pct=(G - (R + B) / 2) / mean * 100,   # +면 녹색 과다
                rb_pct=(R - B) / mean * 100)                # +면 붉은기 과다


def derive(cast, grade):
    """캐스트 → 온도·색조. 나머지는 저장된 톤 그대로."""
    out = json.loads(json.dumps(grade))          # 깊은 복사
    out["기본교정"]["색조"] = round(cast["green_pct"] * TINT_PER_PCT, 1)
    out["기본교정"]["온도"] = round(cast["rb_pct"] * TEMP_PER_PCT, 1)
    return out


def preview(src_path, grade, out_path):
    """프리미어 결과를 못 보므로, 소스 프레임에 근사 적용해 미리보기를 만든다.

    Lumetri 내부 연산과 같지 않다 — **방향과 세기를 가늠하는 용도**다.
    """
    img = np.array(Image.open(src_path).convert("RGB"))
    x = img.astype(np.float32) / 255.0
    m = neutral_mask(img)
    means = np.array([x[..., c][m].mean() for c in range(3)])
    x = np.clip(x * (means.mean() / means), 0, 1)            # 캐스트 중화

    lum = x @ LW
    sh = np.clip(1 - lum * 2, 0, 1)[..., None]
    hi = np.clip(lum * 2 - 1, 0, 1)[..., None]
    mid = 1 - sh - hi
    wheels = [grade["색상휠"]["어두운영역"], grade["색상휠"]["미드톤"], grade["색상휠"]["밝은영역"]]
    import colorsys
    for w, zone in zip(wheels, (sh, mid, hi)):
        ang, luma, sat = w
        x = x + zone * ((luma - 0.5) * 0.36)                 # 막대바(밝기)
        r, g, b = colorsys.hsv_to_rgb((ang % 360) / 360, 1, 1)
        v = np.array([r, g, b]) - np.mean([r, g, b])
        n = np.linalg.norm(v)
        if n:
            x = x + zone * (v / n) * sat * 0.35              # 휠(색)

    l = (x @ LW)[..., None]
    x = l + (x - l) * (grade["크리에이티브채도"] / 100.0)     # 크리에이티브 채도
    x = np.where(x > 0.85, 0.85 + 0.15 * np.tanh((x - 0.85) / 0.15), x)
    Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8)).save(out_path, quality=93)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="원본 영상")
    ap.add_argument("sequence", nargs="?", help="프리미어 시퀀스 이름 일부")
    ap.add_argument("--profile", default="부동산롱폼")
    ap.add_argument("--at", type=float, nargs="+", default=[120, 300, 480, 700],
                    help="캐스트를 잴 시각(초)")
    ap.add_argument("--preview", help="미리보기 저장 경로")
    ap.add_argument("--preview-only", action="store_true", help="프리미어에 쓰지 않는다")
    a = ap.parse_args()

    base = load_grade(a.profile)
    tmp = tempfile.mkdtemp(prefix="autograde_")
    frames = sample_frames(a.source, a.at, tmp)
    if not frames:
        raise SystemExit("프레임을 못 뽑았다 — 경로와 --at 을 확인할 것")
    cast = measure_cast(frames)
    grade = derive(cast, base)

    print(f"측정 프레임 {len(frames)}장 · 중성면 R{cast['R']:.1f} G{cast['G']:.1f} B{cast['B']:.1f}")
    print(f"  녹색 과다 {cast['green_pct']:+.2f}%  →  색조 {grade['기본교정']['색조']:+.1f}")
    print(f"  붉은기    {cast['rb_pct']:+.2f}%  →  온도 {grade['기본교정']['온도']:+.1f}")
    print(f"  (고정) 흰색 {base['기본교정']['흰색']:+.0f} · 검정 {base['기본교정']['검정']:+.0f} · "
          f"크리에이티브 채도 {base['크리에이티브채도']:.1f} · 색상 휠 3개")

    out = a.preview or os.path.join(tmp, "preview.jpg")
    print("\n미리보기:", preview(frames[len(frames) // 2], grade, out))

    if a.sequence and not a.preview_only:
        with Premiere() as pr:
            print("\n적용:", apply(pr, a.sequence, grade, count=1))
            print("확인:", read_back(pr, a.sequence, 0))
        print("\n비블: 맨 앞 컷 복사 → 전체 선택 → 특성 붙여넣기(Ctrl+Alt+V)")
