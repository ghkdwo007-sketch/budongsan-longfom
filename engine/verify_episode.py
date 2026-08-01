#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_episode.py — 한 회차 산출물의 불변식을 검사한다.

여기 있는 항목은 전부 **실제로 한 번씩 깨져서 시간을 잡아먹었던 것들**이다.
납품 전에 돌려서 전부 OK 인지 확인한다.

사용:
  python engine/verify_episode.py "<cam01 원본.MP4>" [--cam2]
"""
import sys, os, re, wave

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import make_edl
from make_edl import df_to_frames, parse_keeps
from silence_cut import probe_media

# 윈도우 콘솔 기본 인코딩(cp949)에는 em dash 같은 기호가 없어 출력하다 죽는다.
# 한글은 cp949 에 있어서 평소엔 안 드러나다가 --help 나 기호가 섞이면 터진다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# 소스 실제 fps 로 맞춘다. 상수 29.97 로 두면 59.94p 회차에서 오디오 길이와 EDL 소스
# in/out 이 정확히 2배로 어긋나 '멀쩡한 산출물'을 FAIL 로 잡는다(실측).
FPS = 30000 / 1001
TCDIV = 1
FAIL = []

# 자막 규칙은 프로파일에서 읽는다(환경변수가 있으면 그게 우선).
# `--profile` 없이 불려도 되도록, 없으면 엔진 기본값을 쓴다.
def _sub_cfg(profile=None):
    """(모드, 최대글자수). 모드는 subtitle_polish 와 같은 규칙으로 읽는다.

    "all" 온점+쉼표 제거 / "comma" 쉼표만 / "none" 그대로.
    예전 config 의 true 는 "all" 로 읽는다.
    """
    import config
    cfg = config.load(project_dir=PROJ, profile=profile)
    raw = os.environ.get("SUB_STRIP_PUNCT", cfg.get("SUB_STRIP_PUNCT", True))
    if raw in (False, "0", "", "false", "False", None):
        mode = "none"
    elif raw in ("comma", "쉼표"):
        mode = "comma"
    else:
        mode = "all"
    maxc = int(os.environ.get("SUB_MAX_CHARS", cfg.get("SUB_MAX_CHARS", 25)))
    return mode, maxc


STRIP_MODE, MAX_CHARS = "all", 25   # main() 에서 프로파일 값으로 덮어쓴다


def check(ok, label, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def cues(p):
    out = []
    for b in re.split(r"\r?\n\r?\n", open(p, encoding="utf-8").read().strip()):
        L = b.splitlines()
        if len(L) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", L[1])
        g = [int(x) for x in m.groups()]
        out.append((g[0]*3600+g[1]*60+g[2]+g[3]/1000,
                    g[4]*3600+g[5]*60+g[6]+g[7]/1000, "\n".join(L[2:])))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    master = sys.argv[1]
    base = os.path.splitext(os.path.basename(master))[0]
    has_cam2 = "--cam2" in sys.argv
    profile = None
    if "--profile" in sys.argv:
        i = sys.argv.index("--profile")
        profile = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    o = os.path.join(PROJ, "output")
    P = lambda s: os.path.join(o, base + s)

    global FPS, TCDIV, STRIP_MODE, MAX_CHARS
    STRIP_MODE, MAX_CHARS = _sub_cfg(profile)
    if os.path.exists(master):
        FPS = probe_media(master)["fps"]
        # EDL 은 30프레임 TC 로 기록된다(59.94p 는 소스 2프레임 = TC 1프레임).
        TCDIV = 2 if round(FPS) > 30 else 1
        make_edl.FPS = FPS / TCDIV   # df_to_frames 가 EDL 과 같은 기준으로 읽도록
        print(f"  (소스 {FPS}fps · EDL 은 {FPS/TCDIV:.2f}fps TC 기준으로 검증)")

    print("── 컷 / 타임라인")
    keeps = parse_keeps(P("_cut.xml"))
    # EDL·오디오는 컷 경계를 TC 격자로 스냅해서 쓴다(make_edl.snap_keeps). 길이 비교는
    # 그쪽 기준으로 해야 한다 — 스냅 전 값과 비교하면 정상인데도 어긋난 것처럼 보인다.
    keeps_snapped = make_edl.snap_keeps(keeps, TCDIV) if TCDIV > 1 else keeps
    total_f = sum(b - a for a, b in keeps_snapped)
    check(len(keeps) > 0, "컷 존재", f"{len(keeps)}컷 · {total_f}프레임 ({total_f/FPS/60:.2f}분)")
    check(all(b > a for a, b in keeps), "컷 길이 양수")

    print("\n── 자막")
    c = cues(P("_cut.srt"))
    L = [len(t) for _s, _e, t in c]
    maxc = MAX_CHARS
    check(max(L) <= maxc, f"한 줄 {maxc}자 이하",
          f"최장 {max(L)}자 · 중앙 {sorted(L)[len(L)//2]}자 · 초과 {sum(1 for x in L if x > maxc)}개")
    check(all("\n" not in t for _s, _e, t in c), "모두 한 줄")
    check(all(e > s for s, e, _ in c), "시작 < 끝")
    check(all(c[i][0] >= c[i-1][1] - 1e-6 for i in range(1, len(c))), "겹침 없음")
    check(c[-1][1] <= total_f / FPS + 0.05, "시퀀스 길이 안에 들어옴",
          f"자막 끝 {c[-1][1]:.2f}s / 시퀀스 {total_f/FPS:.2f}s")

    # 컷 지점마다 '직후 자막이 얼마나 뒤에 뜨는지' — 음수면 자막이 앞 컷 화면에 미리 뜬 것
    tl = 0; cut_pts = []
    for a, b in keeps:
        cut_pts.append(tl / FPS); tl += b - a
    import bisect
    cs = [x[0] for x in c]
    lag = []
    for cp in cut_pts:
        i = bisect.bisect_left(cs, cp)
        if i < len(c):
            lag.append((c[i][0] - cp) * 1000)
    lag.sort()
    check(all(x >= -1 for x in lag), "컷보다 먼저 시작하는 자막 없음",
          f"최소 {lag[0]:.0f}ms")
    print(f"       (참고) 컷 직후 자막까지 지연 중앙값 {lag[len(lag)//2]:.0f}ms — "
          f"컷 뒤 여백 + 발화 시작까지의 시간이라 정상")
    print(f"       (참고) 자막은 FILL_GAPS 로 다음 자막 시작까지 이어진다 → "
          f"컷 경계를 넘어가는 건 의도된 동작")

    # 문장부호는 **프로파일 설정을 따라간다.** 환경변수만 보면 프로파일에서 끈 걸 못 읽어
    # 멀쩡한 산출물을 FAIL 로 잡는다(실측 — 260630 회차가 이걸로 막혔다).
    flat = " ".join(t for _s, _e, t in c)
    noell = re.sub(r"\.{2,}|…", "", flat)
    dots = len(re.findall(r"(?<!\d)\.(?!\d)", noell))
    commas = len(re.findall(r"(?<!\d),(?!\d)", noell))
    if STRIP_MODE == "all":
        check(dots == 0, "단독 온점 없음")
        check(commas == 0, "단독 쉼표 없음")
    elif STRIP_MODE == "comma":
        check(commas == 0, "단독 쉼표 없음")
        print(f"       (참고) 온점 유지 — {dots}개 · 줄당 {dots/max(1,len(c)):.2f} "
              f"(비블 완성본 0.30)")
    else:
        print(f"       (참고) 문장부호 그대로 — 온점 {dots}개 · 쉼표 {commas}개 "
              f"(비블 완성본은 온점 225·쉼표 65)")

    print("\n── 오디오")
    wav = P("_cut_audio_flat.wav")
    if os.path.exists(wav):
        with wave.open(wav) as w:
            af = w.getnframes() / w.getframerate() * FPS
        # 마지막 컷이 미디어 끝을 넘으면 make_cut_audio 가 소스 길이에서 끊는다(=클램프).
        # 기대값에도 같은 클램프를 걸어야 한다 — 안 걸면 정상인 꼬리 잘림이 실패로 뜬다.
        mlen_src = probe_media(master)["duration"] * FPS if os.path.exists(master) else None
        want = total_f
        if mlen_src is not None:
            want = sum(min(b, mlen_src) - a for a, b in keeps_snapped if min(b, mlen_src) > a)
        check(abs(af - want) < 2.0, "플랫 오디오 길이 = 컷 총합(클램프 반영)",
              f"{af:.1f}프레임 vs {want:.1f}프레임")
    else:
        check(False, "플랫 오디오 존재")

    print("\n── EDL")
    EV = re.compile(r"^(\d{3})\s+(\S+)\s+(\S+)\s+C\s+"
                    r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)\s+"
                    r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)")
    def rows(f):
        return [(df_to_frames(m.group(4)), df_to_frames(m.group(5)),
                 df_to_frames(m.group(6)), df_to_frames(m.group(7)))
                for m in map(EV.match, open(f, encoding="utf-8")) if m]

    e1 = P("_cam01_v_tc0.edl")
    check(os.path.exists(e1), "cam01 TC0 EDL 존재")
    if os.path.exists(e1):
        r1 = rows(e1)
        check(len(r1) == len(keeps), "cam01 이벤트 수 = 컷 수", f"{len(r1)} vs {len(keeps)}")
        # EDL 은 TC 기준(59.94p 면 소스 2프레임=TC 1프레임)이라 컷도 같은 기준으로 접어 비교.
        # 마지막 컷이 미디어 끝을 몇 프레임 넘으면 make_edl 이 소스 구간만 안으로 당긴다
        # (클램프 — 컷 개수·레코드 TC 는 그대로 두려는 의도된 동작이라 실패가 아니다).
        # 같은 기준으로 접어 비교하려면 기대값에도 같은 클램프를 걸어야 한다.
        mlen = int(round(probe_media(master)["duration"] * FPS / TCDIV)) if os.path.exists(master) else None
        def clamp(a, b):
            if mlen is None or b <= mlen:
                return a, b
            return a - (b - mlen), mlen          # 길이는 유지한 채 뒤로만 당긴다
        keeps_tc = [clamp(a // TCDIV, b // TCDIV) for a, b in keeps_snapped]
        off = [i + 1 for i, ((si, so, _a, _b), k) in enumerate(zip(r1, keeps_tc))
               if (si, so) != k]
        check(not off, "cam01 소스 in/out = XML 컷",
              "" if not off else f"이벤트 {off} 불일치")
        check(r1[0][2] == 0, "레코드 00:00:00:00 시작")
        check(all(r1[i][2] == r1[i-1][3] for i in range(1, len(r1))), "레코드 연속(갭 없음)")

        # **오디오를 EDL 레코드 타임라인과 직접 비교한다.** 예전엔 오디오를 '컷 합계'와만
        # 재서, 둘 다 반올림 전 값이라 항상 통과했다 — EDL 만 컷마다 접히며 오차가 쌓이는
        # 걸 못 잡았다(실측 45컷에 234ms, 뒤로 갈수록 오디오가 앞서감).
        if os.path.exists(wav):
            edl_end = r1[-1][3]                       # 마지막 레코드 out (TC 프레임)
            with wave.open(wav) as w:
                a_tc = w.getnframes() / w.getframerate() * (FPS / TCDIV)
            check(abs(a_tc - edl_end) < 1.0, "플랫 오디오 길이 = EDL 시퀀스 길이",
                  f"오디오 {a_tc:.1f} vs EDL {edl_end} TC프레임 "
                  f"(차이 {(a_tc-edl_end)*1001/30000*1000:+.0f}ms)")

    if has_cam2:
        e2 = P("_cam02_v_tc0.edl")
        check(os.path.exists(e2), "cam02 TC0 EDL 존재")
        if os.path.exists(e2) and os.path.exists(e1):
            r2 = rows(e2)
            check(len(r2) == len(r1), "cam02 이벤트 수 = cam01", f"{len(r2)} vs {len(r1)}")
            same = all((x[2], x[3]) == (y[2], y[3]) for x, y in zip(r1, r2))
            check(same, "두 캠의 레코드 TC 완전 일치 (= 레이어 겹침 가능)")

    print("\n" + ("전부 통과" if not FAIL else f"실패 {len(FAIL)}건: " + ", ".join(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
