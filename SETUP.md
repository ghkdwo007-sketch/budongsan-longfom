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

`edit.sh`·`batch.sh` 가 윈도우에서 `.venv-win` 을 찾으므로 venv 로 만듭니다.
(시스템 파이썬에 깔면 `python engine/...` 직접 호출만 되고 셸 스크립트는 안 됩니다)

```bash
winget install Gyan.FFmpeg
python -m venv .venv-win
.venv-win/Scripts/python -m pip install -r requirements.txt
```

NVIDIA GPU로 전사를 가속하려면 (없으면 CPU로 돌아감, 대신 느림):
```bash
.venv-win/Scripts/python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

cudnn/cublas 가 커서 venv 가 약 3.3GB 됩니다.

**macOS (Apple Silicon)**

macOS 기본 `python3` 는 3.9(Command Line Tools)라 엔진이 안 돕니다. 3.12를 따로 깔고
**프로젝트 폴더에 venv** 를 만듭니다 — 이후 `edit.sh`·`batch.sh` 는 이 venv를 자동으로 찾습니다.

```bash
brew install ffmpeg python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv-mac
.venv-mac/bin/python -m pip install -r requirements.txt
.venv-mac/bin/python setup_check.py --install
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

자세한 순서와 각 단계의 이유는 [profiles/budongsan-longfom/README.md](profiles/budongsan-longfom/README.md) 에 있습니다.
Claude Code로 이 폴더를 열면 `CLAUDE.md` 를 읽고 워크플로를 파악합니다.

## 4) 회차별로 쌓이는 것

- `profiles/budongsan-longfom/glossary.txt` — 새 오인식이 나오면 여기에 추가.
  회차를 거듭할수록 자막 교정이 정확해집니다.
- `profiles/budongsan-longfom/README.md` 의 회차 기록 표.

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

**프로파일 폴더 이름은 ASCII 로 둡니다** — `profiles/budongsan-longfom/`.
맥은 한글 폴더명을 자모 분해해(NFD) 저장하고 윈도우는 합친 형태(NFC)로 씁니다. 바이트가
달라서, 한글 폴더명을 쓰면 **같은 폴더가 반대 OS 에서 "미추적 + 삭제됨" 으로 보이고
`git add -A` 한 번에 두 벌로 중복 커밋됩니다** (실제로 겪음).

명령은 한글 그대로 씁니다 — `--profile 부동산롱폼`. `config._find_profile_dir` 이
각 프로파일 `config.json` 의 `"_프로파일"` 값을 별칭으로 읽어 폴더를 찾습니다.
(예전 한글 폴더명과 NFD 입력도 계속 인식합니다)

새 프로파일을 만들 때도 **폴더는 ASCII, 한글 이름은 `_프로파일` 에** 넣으세요.

git 의 `core.precomposeunicode=true` 도 켜 둡니다(맥에서 `setup_check.py` 가 점검·설정).
한글이 들어간 자막·영상 파일명에도 같은 문제가 생기기 때문입니다.

**줄바꿈은 `.gitattributes` 로 LF 고정.** 작업 트리가 하나뿐이라 윈도우에서 CRLF로 받으면
맥도 그 CRLF를 보게 되고, `.sh` 가 CRLF면 Git Bash가 바로 죽습니다.

**`._*` 파일은 무시하세요.** exFAT에는 맥이 파일마다 리소스 포크 사이드카를 만듭니다.
윈도우에서 잡동사니로 보이지만 지워도 되고 `.gitignore` 에서 걸러집니다.

**git `safe.directory` 는 OS별로 한 번씩 등록해야 합니다.** exFAT는 파일 소유권을 기록하지 않아
git이 `dubious ownership` 으로 **모든 명령을 거부**합니다. 이 설정은 사용자 홈(`~/.gitconfig`)에
들어가서 **드라이브를 따라가지 않고**, 경로도 OS마다 다릅니다.

```bash
# 윈도우
git config --global --add safe.directory E:/budongsan-longfom/PremierePro-edit
# 맥
git config --global --add safe.directory /Volumes/T7/budongsan-longfom/PremierePro-edit
```

반대로 `core.filemode=false` · `symlinks=false` · `ignorecase=true` · `precomposeunicode=true` 는
`.git/config`, 즉 **드라이브 안에** 있어서 두 OS가 그대로 공유합니다. 다시 설정할 필요 없습니다.

**드라이브 문자·마운트 지점이 바뀌면 venv 경로와 프리미어 미디어 링크가 전부 틀어집니다.**
윈도우는 디스크 관리에서 문자를 고정해 두세요(현재 `E:`). 맥은 볼륨 이름으로 붙습니다(`/Volumes/T7`).

**반드시 안전 제거(꺼내기) 후 뽑으세요.** exFAT는 저널링이 없어서 300MB짜리 WAV를 쓰는 중에
뽑으면 그 파일이 그대로 깨집니다.

**전사 모델 캐시는 프로젝트 안 `.hf-cache/` 에 있습니다** (약 1.6GB, git 제외).
`make_subtitles.py`·`setup_check.py` 가 `HF_HOME` 을 거기로 잡으므로 드라이브를 따라옵니다 —
새 PC·새 OS 에서 1.6GB 를 다시 받지 않습니다. 기본값(`~/.cache/huggingface`)은 사용자 홈이라
드라이브를 안 따라오기 때문입니다. `HF_HOME` 을 직접 쓰는 환경이면 그 값이 우선합니다.

## 6) 학습 내용은 어떻게 따라오는가

회차를 거듭하며 알아낸 것(컷·자막·색보정 기준)은 **드라이브 안에** 있어야 다른 환경에서도
이어집니다. 무엇이 따라오고 무엇이 안 따라오는지:

| | 위치 | 드라이브를 따라오나 |
|---|---|---|
| 학습 요약 | `LEARNED.md` | ✅ (git 포함) |
| 상세 근거·수치 | `profiles/budongsan-longfom/README.md` | ✅ |
| 자막 교정 사전 | `profiles/budongsan-longfom/glossary.txt` | ✅ |
| 색보정 레시피 | `engine/apply_grade_still.py` 의 `RECIPE` | ✅ |
| 학습 루프 기준선 | `output/_prev_260728_부동산/`, `output/_v207_260730/` | ⚠️ **git 제외 — 드라이브에만** |
| Claude 메모리 | 작업 PC 의 `~/.claude/projects/.../memory/` | ❌ **안 따라옴** |

**`LEARNED.md` 가 메모리의 드라이브 사본입니다.** Claude Code 메모리는 작업 PC 사용자 폴더에
저장돼서 SSD 를 따라오지 않습니다. 그래서 같은 내용을 `LEARNED.md` 에 두고 `CLAUDE.md` 맨 앞에서
가리킵니다 — 새 환경에서 이 폴더를 열면 Claude 가 그걸 읽고 이어서 작업합니다.
**새로 배운 게 생기면 메모리와 `LEARNED.md` 양쪽에 남기세요.**

**기준선 폴더를 지우지 마세요.** `output/` 은 `.gitignore` 라 git 으로는 안 따라오지만
드라이브에는 그대로 있습니다. 이게 있어야 다음 회차에 "엔진이 얼마나 어긋났는지"를 잽니다.
git clone 으로 코드만 받은 환경에서는 이 비교가 안 됩니다 — **드라이브째 들고 다니는 이유입니다.**

## 7) 프리미어 MCP (선택)

비블의 수정본을 프리미어에서 직접 읽어 학습하는 경로입니다. 없어도 편집 파이프라인은 다 돕니다.

**MCP 서버는 드라이브 밖에 있습니다** — 새 PC 에서 한 번 설치해야 합니다.

```bash
git clone <Adobe_Premiere_Pro_MCP 리포지토리>
cd Adobe_Premiere_Pro_MCP && npm install && npm run build   # dist/index.js 생성
```

`engine/premiere_mcp.py` 가 서버를 **환경변수 → `~/.claude.json` → 흔한 폴더** 순으로 자동
탐색합니다. 못 찾으면 알려주세요:

```bash
# 윈도우
set PREMIERE_MCP_SERVER=C:\...\Adobe_Premiere_Pro_MCP\dist\index.js
# 맥
export PREMIERE_MCP_SERVER=/.../Adobe_Premiere_Pro_MCP/dist/index.js
```

쓰기 전에 **프리미어를 열고 CEP 브리지 패널에서 Start Bridge** 를 눌러야 합니다.
패널의 Temp Directory 가 `PREMIERE_TEMP_DIR`(기본 `C:\temp\premiere-mcp-bridge`)와 같아야 합니다.

```bash
python engine/premiere_mcp.py get_project_info     # 연결 확인
```
