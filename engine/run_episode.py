#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_episode.py — 2캠 롱폼 한 회차를 처음부터 끝까지 돌린다.

profiles/<프로파일>/README.md 의 0~5단계를 순서대로 실행한다. 순서 자체가 학습 결과라서
(특히 '용어집 → 분할' 순서, TC0 리먹스 선행) 손으로 돌리다 순서를 틀리면 결과가 망가진다.

사용:
  python engine/run_episode.py --cam1 "<cam01 원본.MP4>" --cam2 "<cam02 원본.MP4>" \
                               --profile 부동산롱폼 [--offset 1.0377] [--skip-remux]

--offset 을 생략하면 sync_2cam.py 로 자동 측정한다.

출력은 output/ 에. 프리미어에는 **TC0 사본**을 연결한다(EDL 릴 CAM01/CAM02).
"""
import sys, os, re, json, subprocess, shutil, argparse

# 윈도우 콘솔 기본 인코딩(cp949)에는 em dash 같은 기호가 없어 출력하다 죽는다.
# 한글은 cp949 에 있어서 평소엔 안 드러나다가 --help 나 기호가 섞이면 터진다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
PY = sys.executable

from make_edl import source_tc, df_to_frames      # --skip-remux 의 자정 넘김 사전 검사
from silence_cut import probe_media


def run(cmd, **kw):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(cmd, env=env, text=True, encoding="utf-8",
                       capture_output=True, **kw)
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr[-2000:])
        sys.exit(f"[중단] 실패: {' '.join(str(c) for c in cmd[:3])}…")
    return r.stdout


def step(n, title):
    print(f"\n{'─'*66}\n[{n}] {title}\n{'─'*66}")


def tc0_copy(src):
    """타임코드 0 사본 경로. 없으면 만든다(재인코딩 없음)."""
    d, f = os.path.split(src)
    out = os.path.join(d, os.path.splitext(f)[0] + "_TC0.MP4")
    if os.path.exists(out):
        print(f"   이미 있음: {os.path.basename(out)}")
        return out
    print(f"   생성 중: {os.path.basename(out)} (컨테이너만 재작성 · 화질 손실 없음)")
    run(["ffmpeg", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0",
         "-c", "copy", "-timecode", "00:00:00:00", out, "-loglevel", "error"])
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--cam1", required=True)
    ap.add_argument("--cam2")
    ap.add_argument("--profile", default="부동산롱폼")
    ap.add_argument("--preset", default="표준")
    ap.add_argument("--offset", type=float)
    ap.add_argument("--skip-remux", action="store_true")
    ap.add_argument("--segments", help="구간 JSON — 주면 카테고리·하이라이트까지 만든다")
    a = ap.parse_args()

    for p in (a.cam1, a.cam2):
        if p and not os.path.exists(p):
            sys.exit(f"파일 없음: {p}")
    base = os.path.splitext(os.path.basename(a.cam1))[0]
    outdir = os.path.join(PROJ, "output")
    srt = os.path.join(outdir, base + "_cut.srt")

    # ── 0) TC0 사본 ──────────────────────────────────────────────
    step(0, "TC0 사본 (프리미어 연결용 · EDL 과 TC 기준을 맞춘다)")
    if a.skip_remux:
        print("   건너뜀 (--skip-remux) — 원본에 그대로 연결한다")
        tc1 = tc2 = None
        # 사본 없이 가려면 원본의 실제 TC 로 EDL 을 쓰는 수밖에 없는데, TC 가 자정을 넘으면
        # 23:59:59;29 → 00:00:00;00 으로 되돌아가 이벤트 TC 가 미디어 시작 TC 보다 작아진다
        # (= 매칭 실패). 그런 소스는 TC0 사본이 반드시 필요하다 — 미리 잡아서 알린다.
        for label, path in (("cam01", a.cam1), ("cam02", a.cam2)):
            if not path:
                continue
            tc = source_tc(path)
            n = probe_media(path)["fps"]
            fold = 2 if n > 30 else 1          # 59.94 → 29.97 로 접어서 센다
            end = df_to_frames(tc) + int(round(probe_media(path)["duration"] * n / fold))
            if end > df_to_frames("23:59:59;29") + 1:
                sys.exit(f"[중단] {label} 의 TC 가 자정을 넘는다 ({tc}). "
                         f"이 소스는 --skip-remux 로 갈 수 없다 — 사본을 만들어야 한다.")
            print(f"   {label} 시작 TC {tc} · 자정 안 넘음 → 실제 TC EDL 사용 가능")
    else:
        tc1 = tc0_copy(a.cam1)
        tc2 = tc0_copy(a.cam2) if a.cam2 else None

    # ── 1) 싱크 오프셋 ───────────────────────────────────────────
    off = a.offset
    if a.cam2 and off is None:
        step(1, "싱크 오프셋 측정")
        out = run([PY, os.path.join(HERE, "sync_2cam.py"), a.cam1, a.cam2])
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
        off = j["startB_sec"] if j["startB_sec"] else -j["startA_sec"]
        print(f"   cam02 지연 {off:.4f}s (신뢰도 {j['confidence_peak']})")
        if j["confidence_peak"] < 0.4:
            print("   [주의] 신뢰도가 낮습니다 — 구간별로 재측정해 확인하세요")
    elif a.cam2:
        step(1, f"싱크 오프셋 (지정값 {off}s)")

    # ── 2) 컷편집 ────────────────────────────────────────────────
    # 주의: 원본 파일명으로 돌려야 _words.json 전사 캐시가 맞는다(TC0 사본은 base 가 다름)
    step(2, "컷편집 + 자막 초안")
    run([PY, os.path.join(HERE, "auto_cut.py"), a.cam1,
         "--preset", a.preset, "--profile", a.profile])

    # ── 3) 자막: 용어집 → 분할 (순서 중요) ───────────────────────
    step(3, "자막 교정(용어집) → 마감")
    run([PY, os.path.join(HERE, "apply_glossary.py"), srt, "--profile", a.profile])
    run([PY, os.path.join(HERE, "subtitle_polish.py"), srt])

    # ── 4) 컷 적용 오디오 ────────────────────────────────────────
    step(4, "컷 적용 오디오 (단일 WAV)")
    run([PY, os.path.join(HERE, "make_cut_audio.py"), a.cam1])

    # ── 5) EDL ───────────────────────────────────────────────────
    step(5, "EDL")
    cmd = [PY, os.path.join(HERE, "make_edl.py"), a.cam1]
    if a.cam2:
        cmd += ["--cam2", a.cam2, str(off)]
    run(cmd)

    # ── 6) 검증 ──────────────────────────────────────────────────
    step(6, "검증")
    # 프로파일을 넘겨야 자막 규칙(문장부호·길이)을 같은 기준으로 본다
    run([PY, os.path.join(HERE, "verify_episode.py"), a.cam1] +
        (["--cam2"] if a.cam2 else []) +
        (["--profile", a.profile] if a.profile else []))

    # ── 7) 카테고리 + 하이라이트 (구간 JSON 이 있을 때만) ────────
    # 구간 판단은 전사본을 읽고 사람(또는 Claude)이 해야 하는 일이라 자동화하지 않는다.
    # --segments 없이 돌리면 여기서 안내만 하고 끝난다.
    if a.segments:
        step(7, "카테고리 + 하이라이트")
        run([PY, os.path.join(HERE, "make_highlight.py"), a.cam1,
             "--segments", a.segments])
    else:
        step(7, "카테고리 + 하이라이트 — 건너뜀")
        print(f"   자막을 읽고 구간 JSON 을 만든 뒤 아래를 돌리면 된다:")
        print(f"     python engine/make_highlight.py \"{a.cam1}\" \\")
        print(f"       --segments output/{base}_segments.json")
        print(f"   형식은 make_highlight.py 상단 주석 참고. Claude Code 에 "
              f"'{base} 카테고리 나누고 15분 하이라이트' 라고 하면 만들어 준다.")

    print(f"\n{'='*66}\n완료 — 프리미어 조립")
    if a.segments:
        print(f"  [축약본]  {base}_final.edl        + _highlight_audio.wav + _highlight.srt")
        print(f"  [전체]    {base}_full_labeled.edl + _cut_audio_flat.wav  + _cut.srt")
        print(f"  둘 다 릴 CAM01 → {os.path.basename(tc1) if tc1 else 'TC0 사본'} 에 연결(1회). "
              f"오디오는 A1 의 00:00:00:00.")
        print(f"  자세한 순서·구간 근거: output/{base}_categories.md")
        print(f"{'='*66}")
        return
    # 사본을 안 만들었으면(--skip-remux) TC0 EDL 을 쓰면 안 된다. TC0 EDL 은 소스 TC 를 0 으로
    # 쓰는데 원본에는 실제 TC(예: 05:59:45;03)가 박혀 있어, 프리미어가 둘을 못 맞추고
    # 23시간짜리 유령 클립을 만들며 컷이 전부 어긋난다(실측). 실제 TC 변형(_v.edl)을 쓴다.
    if tc1:
        v1, v2, link1 = "_cam01_v_tc0.edl", "_cam02_v_tc0.edl", os.path.basename(tc1)
        link2 = os.path.basename(tc2) if tc2 else None
    else:
        v1, v2, link1 = "_cam01_v.edl", "_cam02_v.edl", os.path.basename(a.cam1)
        link2 = os.path.basename(a.cam2) if a.cam2 else None
        print("  [사본 없음] 원본의 실제 TC 를 그대로 쓰는 _v.edl 을 쓴다 "
              "— _v_tc0.edl 은 이 모드에서 쓰면 안 된다")
    print(f"  V1  {base}{v1}   → CAM01 을 {link1} 에 연결")
    if a.cam2:
        print(f"  V2  {base}{v2}   → CAM02 를 {link2} 에 연결")
        print(f"      cam02 시퀀스 전체 복사 → cam01 시퀀스 V2 에 00:00:00:00 기준 붙여넣기")
    print(f"  A1  {base}_cut_audio_flat.wav → 00:00:00:00 에 배치")
    print(f"  자막 {base}_cut.srt")
    print(f"  마무리: 타임라인 전체 선택 → Ctrl+Shift+D")


if __name__ == "__main__":
    main()
