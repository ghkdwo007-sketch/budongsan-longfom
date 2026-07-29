# Premiere Pro 자동 편집 프로젝트

## 하네스: 비블 유튜브 영상 편집

**목표:** 원본 영상 1개 → 기획·리서치·컷편집·자막·검수를 전문 에이전트 팀으로 처리해 프리미어 핸드오프까지 자동화.

**트리거:** 비블 영상 편집 전반(기획~자막~쇼츠) 요청 시 `video-edit-pipeline` 스킬을 사용하라. 단일 작업은 전문 스킬 직접 호출 가능 — 컷편집만=`cut-editing`, 자막만=`subtitle-editing`, 리서치만=`content-research`, 기획만=`video-planning`, 검수만=`edit-direction`, 쇼츠만=`shorts-production`. 단순 질문은 직접 응답.

**프로그램 프로파일:** `profiles/<이름>/` — 코너별 설정·용어집·워크플로를 모아둔다.
현재 **`부동산롱폼`** (대표님&미빅님 Q&A 등, 2캠 교차편집). 회차 작업은 `profiles/budongsan-longfom/README.md`
순서를 그대로 따르고, 새로 알게 된 건 그 문서와 `glossary.txt` 에 계속 쌓는다.
실행: `python engine/auto_cut.py "영상.mp4" --preset 표준 --profile 부동산롱폼`

**폴더는 ASCII, 이름은 한글.** 폴더명이 `budongsan-longfom` 인데 `--profile 부동산롱폼` 으로
부르는 건 오타가 아니다 — `config.json` 의 `"_프로파일"` 값을 별칭으로 찾는다(`config._find_profile_dir`).
맥은 한글 폴더명을 NFD 로, 윈도우는 NFC 로 저장해서 외장 SSD 를 오가면 같은 폴더가 두 벌로
중복 커밋된다. **새 프로파일도 폴더는 ASCII 로 만들 것.**

**핵심 엔진:** `engine/auto_cut.py` (= `./edit.sh "영상.mp4" --preset 보수|표준|공격`). 무음·추임새·말더듬 제거 + -14 LUFS 음량정리 + 컷정렬 자막을 한 번에 생성. 설정은 `engine/config.py`(프리셋) + `config.json`(사용자 override). 개선 계획은 `ROADMAP.md`.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-14 | 초기 구성 (에이전트 5 + 스킬 6) | 전체 | 영상 편집 워크플로우 자동화 |
| 2026-06-14 | 설정 프리셋 + 버린컷/백업/검증 + 자연스러움 가드 | engine, config | 로드맵 Task1·3 |
| 2026-06-14 | 제1원칙 '자연스러움 > 최대 제거' 격상 | edit-director, cut-editing | 비블 피드백 |
| 2026-06-14 | 자막 한줄30자+Pretendard Bold 스타일, 어/음 음향검출, 오디오후처리, 문맥필러+false-start, 전사export, 배치, HTML리포트 | engine 전반 | 로드맵 Task5~10 |
| 2026-06-14 | 에이전트 5팀 전용도구 — analyze_video(프리셋추천)·make_shorts(9:16)·emphasis_subs(강조자막) + 스킬 강화(리텐션·정량검수) | engine, .claude | 에이전트별 디벨롭 |
| 2026-06-14 | 끊김(클릭) 개선(비대칭패딩·미세컷절제·오디오페이드) + 숏폼 PD 에이전트(1분 쇼츠 5개 자동) | engine, .claude | 끊김 피드백 + 쇼츠 자동화 |
| 2026-07-29 | Windows 지원 — STT 백엔드 자동 선택(mlx-whisper ↔ faster-whisper, CUDA/CPU 폴백), edit.sh/batch.sh python3→python | make_subtitles, edit.sh, batch.sh, requirements | 작업 PC가 Windows(RTX 4060) |
| 2026-07-29 | 오디오 분석 패스에 `-vn -sn -dn` 추가 (491배 단축: 4K 30분 기준 패스당 19분→3초) | silence_cut, analyze_video | 4K HEVC 소스에서 비디오를 불필요하게 전체 디코딩하던 버그 |
| 2026-07-29 | probe_media가 본편 비디오 스트림을 고르도록 수정(커버 제외 + 최대 해상도, 비정상 fps 방어) | silence_cut | DJI 파일의 mjpeg 썸네일(1280x720@90000fps)을 본편으로 잡아 XML 프레임 계산이 깨지던 버그 |
| 2026-07-29 | `<pathurl>` 생성을 공용 `silence_cut.path_to_url()`로 통일 (`file://localhost/D:/...`) | silence_cut, mcam_xml, shorts_xml, shorts_cut, shorts_premiere, xml_to_mp4 | 윈도우에서 `\`→%5C, `:`→%3A 로 인코딩돼 프리미어가 미디어를 못 찾고 전부 오프라인으로 뜨던 버그 |
| 2026-07-29 | **EDL 내보내기 추가** (`make_edl.py`, CMX3600 · 29.97 DF · 자정넘김 대응 TC0 변형) | engine | **Premiere Pro 26.3에서 FCP7 XML 임포터 제거됨** — 설치 폴더에 xmeml 모듈 없음, 가져오기 형식 목록에도 없음. EDL/AAF만 남아 XML 경로 전면 대체 |
| 2026-07-29 | 컷 적용 단일 오디오(`make_cut_audio.py`, 샘플 단위 절단) + 멀티캠 컷 clamp | engine | 오디오를 EDL 이벤트로 쪼개면 프리미어가 소스 in점을 무시하고 매 컷 0부터 재생 / 컷을 빼면 캠별 컷 구조가 달라져 교차편집 불가 |
| 2026-07-29 | 자막 한 줄 25자 + 균형 분할(`_balanced_chunks`, 한국어 어미 사전 재사용) | subtitle_polish | 비블 자막이 '한 줄 + 검은 박스'라 38자는 화면 폭 초과. 그리디 분할은 '25자+7자' 토막 양산 |
| 2026-07-29 | **프로파일 체계 도입** — `profiles/budongsan-longfom/`(config·glossary·README) + `--profile` 옵션 + `apply_glossary.py` | config, auto_cut, engine | 코너별 설정·고유명사 교정·워크플로를 회차마다 재사용하고 계속 축적하기 위해 |
| 2026-07-29 | **자막 싱크 드리프트 수정** — `regroup(max_chars=)` 로 처음부터 25자 생성 + `build_mapper(fps=)` 프레임 양자화 | make_subtitles, auto_cut | ① 사후 분할이 시간을 글자수 비례로 나눠 최대 850ms 오차 ② 영상은 프레임 반올림 누적인데 자막은 실수 누적이라 285컷에 평균 204ms 드리프트 |
| 2026-07-29 | 자막 문장부호 정리 `SUB_STRIP_PUNCT` — 단독 온점·쉼표만 제거 | subtitle_polish, 프로파일 | 비블 자막 스타일. `? !` 와 `... …`, 숫자 안의 점/쉼표는 유지 |
| 2026-07-29 | **회차 실행기 `run_episode.py` + 검증기 `verify_episode.py`** · EDL TC0 변형 항상 생성 | engine | 순서 자체가 학습 결과라 손으로 돌리면 틀린다(용어집→분할, TC0 선행). 검증기 항목은 전부 실제로 깨졌던 것들 |

## [중요] Premiere Pro 26(2026) 호환

**FCP7 XML 가져오기가 제거됐다.** 26.3.0 설치 폴더에 xmeml 계열 임포터가 없고(`AAFCOAPI.dll`·OMF는 있음), 가져오기 대화상자에 "Final Cut Pro XML" 항목도 없다. 실측: 5~10컷 XML은 우연히 통과하지만 20컷부터 "프로젝트가 손상되어 열 수 없습니다"로 실패.

→ **핸드오프는 `make_edl.py`(EDL)를 쓴다.** `_cut.xml`/`_mcam.xml`은 Premiere 25 이하 및 타 NLE용으로만 유지.
→ EDL은 비디오 트랙 1개만 지원 → 2캠은 시퀀스 2개로 내보내 타임라인에서 겹쳐 쓴다.
→ 소스 TC가 자정을 넘으면(`23:50` 시작 등) `_tc0` 변형을 쓰고, **소스 파일 자체를 TC 0으로 리먹스**한다
(`ffmpeg -i src.MP4 -map 0:v:0 -map 0:a:0 -c copy -timecode 00:00:00:00 out.MP4` — 재인코딩 없음).
프리미어 '클립 수정 > 시간 코드'는 **오프라인 클립에서 비활성**이라 EDL 워크플로에서 쓸 수 없다.
→ 정리 오디오 WAV는 `-map_metadata -1` 로 원본 TC를 물려받지 않게 한다(안 그러면 카메라 TC가 박혀 정렬이 어긋남).
→ **오디오를 EDL 이벤트로 쪼개지 말 것.** 한 이벤트에 릴 2개(비디오+오디오)를 쓰면 프리미어가
오디오 소스 in점을 무시하고 매 컷마다 0부터 재생한다. `make_cut_audio.py` 로 컷 적용된 단일 WAV를 만들어 A1의 0에 올린다.
→ **멀티캠은 컷을 절대 빼지 말 것.** 범위를 벗어나는 컷은 소스만 clamp 한다. 컷 개수·레코드 TC가
카메라마다 같아야 레이어를 겹쳐 교차편집(클립 활성/비활성)할 수 있다.

## 자막 스타일

한 줄 **25자** (`subtitle_polish.MAX_CHARS_LINE`, 환경변수 `SUB_MAX_CHARS` 로 override).
비블 자막은 '한 줄 + 검은 박스'라 화면 폭에 바로 걸린다 — 레퍼런스 프레임 실측 기준 25자가 폭의 약 2/3.
분할은 그리디가 아니라 **균형 분할**(`_balanced_chunks`)로, `make_subtitles.end_score` 의 한국어 어미
사전을 써서 자연스러운 자리에서 끊는다. (그리디는 '25자 + 7자' 식 토막을 대량 생성함)

## [주의] 전사 비결정성

faster-whisper(GPU float16 + `condition_on_previous_text=True`)는 같은 입력에도 결과가 미세하게
달라지고, 그 차이가 말더듬/숨소리 판정으로 증폭돼 **컷 개수가 크게 바뀐다**(실측 210컷 ↔ 285컷).
`output/<base>_words.json` 캐시가 있으면 재전사를 건너뛰므로 재현된다 — **이 파일을 지우지 말 것.**
