# 다른 PC에서 쓰기 (집 작업용 세팅)

이 폴더를 통째로 옮기면 됩니다. 영상·자막·전사캐시는 들어 있지 않습니다.

## 1) 필요한 것

| | |
|---|---|
| Python | 3.10+ |
| ffmpeg | ffprobe 포함 |
| 편집 | Premiere Pro (26 이상이면 **EDL** 로 넘김 — FCP7 XML 임포터가 없음) |
| GPU | 선택. NVIDIA 있으면 전사가 훨씬 빠름 |

## 2) 설치 — 자동

```bash
python setup_check.py            # 뭐가 부족한지 점검만
python setup_check.py --install  # 부족한 것 설치 + 전사 모델 미리 받기
```

Python·ffmpeg·패키지·GPU 가속·전사 모델·프로파일을 한 번에 확인합니다.
관리자 권한 팝업이나 Homebrew 비밀번호는 직접 승인해 주셔야 하고,
ffmpeg 설치 직후 PATH 가 안 잡히면 터미널을 새로 열고 다시 돌리면 됩니다.

Claude Code 로 폴더를 열고 "세팅해줘" 라고 해도 됩니다 — 같은 스크립트를 돌립니다.

## 2-1) 설치 — 수동

**Windows**
```bash
winget install Gyan.FFmpeg
pip install -r requirements.txt
```

NVIDIA GPU로 전사를 가속하려면 (없으면 CPU로 돌아감, 대신 느림):
```bash
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

**macOS (Apple Silicon)**
```bash
brew install ffmpeg
pip install -r requirements.txt
```
mlx-whisper가 자동 선택됩니다. 엔진이 OS에 맞는 전사 백엔드를 알아서 고릅니다.

`setup_check.py` 가 "준비 완료" 를 찍으면 끝입니다.

## 3) 회차 작업

```bash
python engine/run_episode.py \
  --cam1 "<cam01 원본.MP4>" \
  --cam2 "<cam02 원본.MP4>" \
  --profile 부동산롱폼
```

자세한 순서와 각 단계의 이유는 [profiles/부동산롱폼/README.md](profiles/부동산롱폼/README.md) 에 있습니다.
Claude Code로 이 폴더를 열면 `CLAUDE.md` 를 읽고 워크플로를 파악합니다.

## 4) 회차별로 쌓이는 것

- `profiles/부동산롱폼/glossary.txt` — 새 오인식이 나오면 여기에 추가.
  회차를 거듭할수록 자막 교정이 정확해집니다.
- `profiles/부동산롱폼/README.md` 의 회차 기록 표.

두 PC에서 번갈아 작업한다면 이 **프로파일 폴더를 동기화**해야 축적이 유지됩니다
(클라우드 드라이브에 두거나, 나중에 git 저장소로 관리).

## 옮기면 안 되는 것

`output/` 은 회차 산출물이라 새 PC에서 다시 생성됩니다. 특히 `_words.json`(전사 캐시)은
회차별 파일이라 옮길 필요가 없지만, **같은 회차를 이어서 작업한다면 반드시 함께 옮기세요.**
지우고 재전사하면 GPU 비결정성 때문에 컷 개수가 달라집니다(실측 210컷 ↔ 285컷).
