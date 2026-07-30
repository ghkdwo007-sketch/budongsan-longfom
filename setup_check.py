#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_check.py — 새 PC에서 이 도구를 돌릴 준비가 됐는지 점검하고, 필요하면 설치한다.

  python setup_check.py             점검만 (아무것도 설치 안 함)
  python setup_check.py --install   부족한 것 설치 + 전사 모델 미리 받기

점검 항목: Python · ffmpeg/ffprobe · 파이썬 패키지 · GPU 가속 · 전사 모델 · 프로파일
"""
import sys, os, subprocess, shutil, platform, argparse

HERE = os.path.dirname(os.path.abspath(__file__))

# 모델을 프로젝트 안에 받게 한다(외장 SSD 를 오갈 때 OS 마다 재다운로드 방지).
# --install 이 띄우는 자식 프로세스도 이 값을 물려받는다. make_subtitles.py 와 같은 규칙.
os.environ.setdefault("HF_HOME", os.path.join(HERE, ".hf-cache"))

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_ARM_MAC = IS_MAC and platform.machine() == "arm64"

OK, WARN, BAD = "OK  ", "주의", "없음"
problems, actions = [], []


def say(state, label, detail=""):
    print(f"  [{state}] {label}" + (f" — {detail}" if detail else ""))


def run(cmd, quiet=False):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not quiet and r.returncode != 0:
        print((r.stderr or r.stdout or "")[-800:])
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def pip_install(*pkgs):
    print(f"    → pip install {' '.join(pkgs)}")
    ok, _ = run([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])
    return ok


def check_python():
    v = sys.version_info
    good = v >= (3, 10)
    say(OK if good else BAD, "Python", f"{v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if not good:
        problems.append("Python 3.10 이상이 필요합니다")


def check_ffmpeg(install):
    found = {n: shutil.which(n) for n in ("ffmpeg", "ffprobe")}
    if all(found.values()):
        _, out = run(["ffmpeg", "-version"], quiet=True)
        say(OK, "ffmpeg / ffprobe", out.splitlines()[0][:60] if out else "")
        return
    say(BAD, "ffmpeg / ffprobe", "PATH 에서 못 찾음")
    cmd = (["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-source-agreements",
            "--accept-package-agreements"] if IS_WIN else ["brew", "install", "ffmpeg"])
    if not install:
        actions.append(" ".join(cmd))
        return
    if not shutil.which(cmd[0]):
        problems.append(f"{cmd[0]} 이 없어 자동 설치 불가 — ffmpeg 을 직접 설치하세요")
        return
    print(f"    → {' '.join(cmd)}")
    run(cmd)
    if not shutil.which("ffmpeg"):
        problems.append("ffmpeg 설치 후 PATH 가 갱신되지 않았습니다 — 터미널을 새로 열고 다시 실행하세요")


def check_packages(install):
    need = ["numpy", "scipy"]
    need += ["mlx_whisper"] if IS_ARM_MAC else ["faster_whisper"]
    missing = []
    for m in need:
        try:
            __import__(m)
            say(OK, m)
        except Exception as e:
            say(BAD, m, type(e).__name__)
            missing.append(m)
    if missing and install:
        pip_install("-r", os.path.join(HERE, "requirements.txt"))
    elif missing:
        actions.append(f"pip install -r requirements.txt")


def check_gpu(install):
    if IS_ARM_MAC:
        say(OK, "가속", "Apple Silicon — mlx 가 GPU 를 직접 씁니다")
        return
    if not shutil.which("nvidia-smi"):
        say(WARN, "NVIDIA GPU", "없음 → CPU 전사(느림). 30분 영상에 20분 이상 걸릴 수 있습니다")
        return
    _, out = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], quiet=True)
    gpu = out.strip().splitlines()[0] if out.strip() else "NVIDIA"
    try:
        import nvidia, glob
        root = list(nvidia.__path__)[0]
        has = all(glob.glob(os.path.join(root, s, "bin", "*.dll")) or
                  glob.glob(os.path.join(root, s, "lib", "*")) for s in ("cublas", "cudnn"))
    except Exception:
        has = False
    if has:
        say(OK, "GPU 가속", gpu)
    else:
        say(BAD, "CUDA 라이브러리", f"{gpu} 는 있는데 cuBLAS/cuDNN 미설치")
        if install:
            pip_install("nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10")
        else:
            actions.append('pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"')


def check_model(install):
    """전사 모델은 프로젝트 안 `.hf-cache/` 에 받는다 — 외장 SSD 를 오가도 따라온다.

    `make_subtitles.py` 가 HF_HOME 을 거기로 잡는다. 사용자 홈(~/.cache/huggingface)에
    예전에 받아둔 게 있으면 그것도 인정한다(HF_HOME 을 직접 쓰는 환경 포함).
    """
    roots = [os.path.join(HERE, ".hf-cache", "hub")]
    if os.environ.get("HF_HOME"):
        roots.append(os.path.join(os.environ["HF_HOME"], "hub"))
    roots.append(os.path.expanduser("~/.cache/huggingface/hub"))
    for cache in roots:
        if os.path.isdir(cache) and any("large-v3-turbo" in d for d in os.listdir(cache)):
            where = "프로젝트 .hf-cache" if cache.startswith(HERE) else cache
            say(OK, "전사 모델", f"캐시에 있음 ({where})")
            return
    say(BAD, "전사 모델", "~1.6GB 첫 실행 시 다운로드 (인터넷 필요)")
    if not install:
        actions.append("python setup_check.py --install   (모델 미리 받기)")
        return
    print("    → 모델 내려받는 중… 몇 분 걸립니다")
    if IS_ARM_MAC:
        run([sys.executable, "-c",
             "import mlx_whisper,sys;mlx_whisper.load_models.load_model("
             "'mlx-community/whisper-large-v3-turbo')"])
    else:
        run([sys.executable, "-c",
             "from faster_whisper import WhisperModel;WhisperModel('large-v3-turbo',"
             "device='cpu',compute_type='int8')"])


def check_git_unicode(install):
    """맥에서 한글 폴더명이 NFD 로 커밋되는 걸 막는다.

    맥은 '부동산롱폼' 을 자모 분해(NFD)해 저장하고 윈도우는 NFC 로 쓴다. 이 설정이 없으면
    같은 프로파일 폴더가 두 벌로 중복 커밋된다(실제로 겪음). git init 이 윈도우에서 됐다면
    이 값이 안 잡혀 있다.
    """
    if not IS_MAC or not os.path.isdir(os.path.join(HERE, ".git")):
        return
    ok, out = run(["git", "-C", HERE, "config", "--get", "core.precomposeunicode"], quiet=True)
    if ok and out.strip() == "true":
        say(OK, "git 한글 파일명", "precomposeunicode=true")
        return
    say(BAD, "git 한글 파일명", "precomposeunicode 미설정 — 프로파일이 NFC/NFD 두 벌로 커밋됨")
    if install:
        print("    → git config core.precomposeunicode true")
        run(["git", "-C", HERE, "config", "core.precomposeunicode", "true"])
    else:
        actions.append("git config core.precomposeunicode true")


def check_profile():
    sys.path.insert(0, os.path.join(HERE, "engine"))
    try:
        import config as C
        c = C.load("표준", project_dir=HERE, profile="부동산롱폼")
        say(OK if c.get("_profile") else BAD, "부동산롱폼 프로파일",
            f"자막 {c.get('SUB_MAX_CHARS')}자 · 문장부호제거 {bool(c.get('SUB_STRIP_PUNCT'))}")
        if not c.get("_profile"):
            problems.append("프로파일을 못 읽었습니다 — profiles/budongsan-longfom/config.json 확인")
    except Exception as e:
        say(BAD, "프로파일 로딩", f"{type(e).__name__}: {e}")
        problems.append("엔진 임포트 실패")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true", help="부족한 것을 실제로 설치")
    a = ap.parse_args()

    print(f"\n{platform.system()} {platform.machine()} · {HERE}\n")
    print("── 런타임");      check_python(); check_ffmpeg(a.install)
    print("\n── 파이썬 패키지"); check_packages(a.install)
    print("\n── 전사");        check_gpu(a.install); check_model(a.install)
    print("\n── 프로젝트");    check_git_unicode(a.install); check_profile()

    print("\n" + "─" * 60)
    if problems:
        print("직접 처리해야 할 것:")
        for p in problems:
            print("  •", p)
    if actions:
        print("설치가 필요합니다. 아래를 실행하거나 `python setup_check.py --install` :")
        for c in actions:
            print("  ", c)
    if not problems and not actions:
        print("준비 완료. 회차 작업:")
        print('  python engine/run_episode.py --cam1 "cam01/원본.MP4" '
              '--cam2 "cam02/원본.MP4" --profile 부동산롱폼')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
