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

# 소스 실제 fps 로 맞춘다. 상수 29.97 로 두면 59.94p 회차에서 오디오 길이와 EDL 소스
# in/out 이 정확히 2배로 어긋나 '멀쩡한 산출물'을 FAIL 로 잡는다(실측).
FPS = 30000 / 1001
FAIL = []


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
    o = os.path.join(PROJ, "output")
    P = lambda s: os.path.join(o, base + s)

    global FPS
    if os.path.exists(master):
        FPS = probe_media(master)["fps"]
        make_edl.FPS = FPS          # df_to_frames 가 같은 기준으로 EDL TC 를 읽도록
        print(f"  (소스 {FPS}fps 기준으로 검증)")

    print("── 컷 / 타임라인")
    keeps = parse_keeps(P("_cut.xml"))
    total_f = sum(b - a for a, b in keeps)
    check(len(keeps) > 0, "컷 존재", f"{len(keeps)}컷 · {total_f}프레임 ({total_f/FPS/60:.2f}분)")
    check(all(b > a for a, b in keeps), "컷 길이 양수")

    print("\n── 자막")
    c = cues(P("_cut.srt"))
    L = [len(t) for _s, _e, t in c]
    maxc = int(os.environ.get("SUB_MAX_CHARS", 25))
    check(max(L) <= maxc, f"한 줄 {maxc}자 이하", f"최장 {max(L)}자 · 초과 {sum(1 for x in L if x > maxc)}개")
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

    flat = " ".join(t for _s, _e, t in c)
    noell = re.sub(r"\.{2,}|…", "", flat)
    if os.environ.get("SUB_STRIP_PUNCT", "1") not in ("0", "false"):
        check(len(re.findall(r"(?<!\d)\.(?!\d)", noell)) == 0, "단독 온점 없음")
        check(len(re.findall(r"(?<!\d),(?!\d)", noell)) == 0, "단독 쉼표 없음")

    print("\n── 오디오")
    wav = P("_cut_audio_flat.wav")
    if os.path.exists(wav):
        with wave.open(wav) as w:
            af = w.getnframes() / w.getframerate() * FPS
        check(abs(af - total_f) < 1.0, "플랫 오디오 길이 = 컷 총합",
              f"{af:.1f}프레임 vs {total_f}프레임")
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
        check(all((si, so) == k for (si, so, _a, _b), k in zip(r1, keeps)),
              "cam01 소스 in/out = XML 컷")
        check(r1[0][2] == 0, "레코드 00:00:00:00 시작")
        check(all(r1[i][2] == r1[i-1][3] for i in range(1, len(r1))), "레코드 연속(갭 없음)")

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
