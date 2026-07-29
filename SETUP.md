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

macOS 기본 `python3` 는 3.9(Command Line Tools)라 엔진이 안 돕니다. 3.12를 따로 깔고
**프로젝트 폴더에 venv** 를 만듭니다 — 이후 `edit.sh`·`batch.sh` 는 이 venv를 자동으로 찾습니다.

```bash
brew install ffmpeg python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_check.py --install
```

mlx-whisper가 자동 선택됩니다. 엔진이 OS에 맞는 전사 백엔드를 알아서 고릅니다.
`python engine/...` 로 직접 돌릴 때는 `.venv-mac/bin/python engine/...` 로 부르세요.

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

폴더째 외장 SSD에 두면 프로파일도 `output/` 도 같이 따라다니므로 축적이 그대로 유지됩니다.

## 5) 외장 SSD로 맥 ↔ 윈도우 오가기

폴더를 외장 SSD(exFAT)에 두고 두 OS에서 번갈아 쓰는 구성입니다. 걸리는 것들과 대응:

**venv 는 OS별로 따로.** `.venv-mac/` 과 `.venv-win/` 을 각각 만듭니다. 한 경로를 공유하면
서로 덮어써서 매번 깨집니다. `edit.sh`·`batch.sh` 는 둘 다 찾아보고 있는 쪽을 씁니다.
처음 쓰는 OS에서 한 번만 위 설치 절차를 돌리면, 이후로는 그 SSD를 꽂기만 하면 됩니다.

**전사 캐시(`output/<base>_words.json`)를 지우지 마세요.** 맥은 mlx-whisper,
윈도우는 faster-whisper라 **백엔드가 아예 다릅니다.** 같은 회차를 다른 OS에서 재전사하면
컷 개수가 크게 바뀝니다(실측 210컷 ↔ 285컷). 캐시가 있으면 재전사를 건너뛰므로,
SSD에 그대로 두는 한 어느 쪽에서 이어 작업해도 결과가 유지됩니다.

**한글 폴더명은 두 OS가 다르게 저장합니다.** 맥은 자모를 분해해(NFD) `부동산롱폼` 을
저장하고 윈도우는 합친 형태(NFC)로 씁니다. 바이트가 달라 그냥 비교하면 못 찾습니다.
- 엔진은 `config._find_profile_dir` 이 두 형태를 모두 찾아주므로 `--profile 부동산롱폼` 은 그대로 됩니다.
- git 은 `core.precomposeunicode=true` 로 NFC 통일 (이 저장소에 설정돼 있고 `.git` 이 SSD에
  같이 있으므로 두 PC에 모두 적용됩니다). **이 설정이 없으면 프로파일 폴더가 NFC/NFD 두 벌로
  중복 커밋됩니다.**

**줄바꿈은 `.gitattributes` 로 LF 고정.** 작업 트리가 하나뿐이라 윈도우에서 CRLF로 받으면
맥도 그 CRLF를 보게 되고, `.sh` 가 CRLF면 Git Bash가 바로 죽습니다.

**`._*` 파일은 무시하세요.** exFAT에는 맥이 파일마다 리소스 포크 사이드카를 만듭니다.
윈도우에서 잡동사니로 보이지만 지워도 되고 `.gitignore` 에서 걸러집니다.
