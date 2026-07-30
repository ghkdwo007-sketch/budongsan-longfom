#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cut_gate.py — 컷 경계가 '진짜 무음'인지 오디오로 검증하는 가드.

무음 컷(silencedetect)은 경계가 정의상 조용하다. 문제는 **단어 기반 제거**다 —
말더듬/중복, NG, 망설임(어/음), 음향 어/음, 숨소리는 전사본의 단어 타임스탬프로
구간을 잡는데, whisper 의 단어 경계는 ±100~200ms 씩 흔들린다. 그래서 전사본상으로는
'단어 사이 빈틈'인 자리가 실제로는 아직 말이 울리는 중이라, 거기서 이어붙이면
음절이 잘리거나 툭 끊기는 소리가 난다. (WORD_SNAP 은 경계가 단어 구간을 '엄격히
관통'할 때만 고치므로 이 경우를 못 잡는다 — 타임스탬프 자체가 틀린 것이기 때문)

이 모듈은 제안된 제거 구간마다 이어붙을 두 지점의 실제 RMS 를 재서:
  ① 둘 다 조용하면 그대로 통과
  ② 아니면 근처(search)에서 조용한 자리를 찾아 경계를 옮긴다
  ③ 그래도 못 찾으면 **그 제거를 아예 포기한다** (겹쳐 있는 반복 등 — 놔두는 게 낫다)

'자연스러움 > 최대 제거' 원칙의 연장. 포기한 구간은 로그로 남겨 확인할 수 있다.
"""

import numpy as np


def _rms_db(x, sr, t0, t1):
    """[t0,t1) 구간의 RMS(dBFS). 범위를 벗어나면 None."""
    i0, i1 = int(round(t0 * sr)), int(round(t1 * sr))
    i0, i1 = max(0, i0), min(len(x), i1)
    if i1 - i0 < 8:                       # 표본이 너무 적으면 판단 불가
        return None
    seg = x[i0:i1]
    return 20.0 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)


def estimate_floor(x, sr, win=0.04, pct=5.0):
    """노이즈 플로어(dBFS) 추정 — 창 단위 RMS 의 하위 백분위수.

    원본에서 잰 값을 쓰면 안 된다. 가드는 **정리된 오디오**(-14 LUFS 로 노멀라이즈된
    신호)를 재기 때문에, 같은 신호에서 뽑아야 기준이 맞는다.
    """
    if x is None or len(x) == 0:
        return None
    w = max(int(win * sr), 8)
    n = len(x) // w
    if n < 10:
        return None
    fr = x[:n * w].reshape(n, w)
    rms = np.sqrt((fr ** 2).mean(1) + 1e-12)
    return float(20.0 * np.log10(np.percentile(rms, pct) + 1e-9))


def quantize(t, fps):
    """프레임 격자로 반올림. fps 가 없으면 그대로."""
    return t if not fps else round(t * fps) / fps


def _find_quiet(x, sr, t, thresh_db, win, search, before, lo, hi, fps=None):
    """t 근처에서 조용한 지점을 찾아 반환. 못 찾으면 None.

    before=True  → 이어붙기 전 조각의 '끝'  → [t-win, t) 를 본다
    before=False → 이어붙은 뒤 조각의 '시작' → [t, t+win) 를 본다
    이동량이 작은 후보부터 검사해서, 경계를 최소로만 움직인다.

    후보는 **프레임 격자에 올려놓고** 판정한다. XML/EDL 은 프레임 단위로 반올림되므로,
    실수 초로 '조용하다'고 판정한 자리가 반올림 뒤엔 최대 반 프레임(29.97p 기준 17ms)
    밀려 발화 시작에 걸릴 수 있다. 검증한 값과 실제 나가는 값이 같아야 한다.
    """
    step = max(win / 2.0, 0.01)
    n = int(search / step)
    cands = [0.0]
    for k in range(1, n + 1):
        cands += [-k * step, k * step]     # 가까운 쪽부터 양방향
    seen = set()
    for d in cands:
        t2 = quantize(t + d, fps)
        if not (lo <= t2 <= hi) or t2 in seen:
            continue
        seen.add(t2)
        db = _rms_db(x, sr, t2 - win, t2) if before else _rms_db(x, sr, t2, t2 + win)
        if db is not None and db <= thresh_db:
            return t2
    return None


def gate(removes, x, sr, thresh_db, win=0.04, search=0.20, total=None):
    """제거 구간들을 오디오로 검증한다.

    removes: [[s,e], ...]  (제거 예정 구간 — 순서 무관)
    반환: (통과한 removes, 포기 로그, 옮긴 횟수)
          포기 로그 = [(s, e, "사유"), ...]
    """
    if x is None or len(x) == 0 or not removes:
        return removes, [], 0

    dur = total if total is not None else len(x) / sr
    out, dropped, moved = [], [], 0

    for r in removes:
        s, e = float(r[0]), float(r[1])
        if e <= s:
            continue

        # 이어붙는 두 지점: s 직전(앞 조각의 끝), e 직후(뒷 조각의 시작)
        a_db = _rms_db(x, sr, s - win, s)
        b_db = _rms_db(x, sr, e, e + win)
        a_ok = a_db is None or a_db <= thresh_db      # 측정 불가는 통과(파일 양끝)
        b_ok = b_db is None or b_db <= thresh_db

        if a_ok and b_ok:
            out.append([s, e])
            continue

        s2, e2 = s, e
        if not a_ok:
            # 경계를 옮겨도 구간이 뒤집히지 않게 상한을 e 로 묶는다
            f = _find_quiet(x, sr, s, thresh_db, win, search,
                            before=True, lo=max(win, s - search), hi=min(e, s + search))
            if f is None:
                dropped.append((s, e, f"앞 경계가 말 중간 ({a_db:.0f}dB) — 제거 포기"))
                continue
            s2 = f
            moved += 1
        if not b_ok:
            f = _find_quiet(x, sr, e, thresh_db, win, search,
                            before=False, lo=max(s2, e - search),
                            hi=min(dur - win, e + search))
            if f is None:
                dropped.append((s, e, f"뒤 경계가 말 중간 ({b_db:.0f}dB) — 제거 포기"))
                continue
            e2 = f
            moved += 1

        if e2 - s2 > 0.01:
            out.append([s2, e2])
        else:
            dropped.append((s, e, "경계 보정 후 남는 구간 없음 — 제거 포기"))

    return out, dropped, moved


def gate_keeps(keeps, x, sr, thresh_db, win=0.04, search=0.20, total=None, fps=None):
    """최종 컷 목록의 접합부를 검증하는 마지막 패스.

    gate() 는 '제거 구간'을 보지만, 최종 접합부는 그 뒤 단계에서도 움직인다 —
    WORD_SNAP 이 경계를 단어 끝(we+pad)으로 되돌리고, 무음 컷 경계는 애초에
    gate() 를 거치지 않는다. 그래서 실제 이어붙는 자리를 한 번 더 본다.

    여기서 '포기'는 **두 컷을 합쳐 그 자리를 안 끊는 것**이다.
    (반복 구간에서 소리가 겹쳐 끊을 자리가 없으면 놔두라는 편집 방향)

    반환: (keeps, 합친 횟수, 경계 이동 횟수)
    """
    if x is None or len(x) == 0 or len(keeps) < 2:
        return keeps, 0, 0

    dur = total if total is not None else len(x) / sr
    out = [list(keeps[0])]
    merged = moved = 0

    for nxt in keeps[1:]:
        cur = out[-1]
        # XML 이 반올림할 위치에서 판정한다 — 검증한 값과 나가는 값을 일치시킨다
        a_end, b_start = quantize(float(cur[1]), fps), quantize(float(nxt[0]), fps)

        a_db = _rms_db(x, sr, a_end - win, a_end)
        b_db = _rms_db(x, sr, b_start, b_start + win)
        a_ok = a_db is None or a_db <= thresh_db
        b_ok = b_db is None or b_db <= thresh_db

        if a_ok and b_ok:
            out.append(list(nxt))
            continue

        # 경계를 옮겨 조용한 자리를 찾는다. 왼쪽 끝은 자기 구간 안에서,
        # 오른쪽 시작은 자기 구간 안에서만 움직여 서로를 침범하지 않게 한다.
        new_a, new_b = a_end, b_start
        if not a_ok:
            f = _find_quiet(x, sr, a_end, thresh_db, win, search, before=True,
                            lo=max(cur[0] + win, a_end - search),
                            hi=min(b_start, a_end + search), fps=fps)
            if f is None:
                cur[1] = max(cur[1], nxt[1])       # 못 찾음 → 합쳐서 안 끊는다
                merged += 1
                continue
            new_a = f
            moved += 1
        if not b_ok:
            f = _find_quiet(x, sr, b_start, thresh_db, win, search, before=False,
                            lo=max(new_a, b_start - search),
                            hi=min(float(nxt[1]) - win, b_start + search, dur - win),
                            fps=fps)
            if f is None:
                cur[1] = max(cur[1], nxt[1])
                merged += 1
                continue
            new_b = f
            moved += 1

        cur[1] = new_a
        out.append([new_b, float(nxt[1])])

    return [(a, b) for a, b in out if b > a], merged, moved


def boundary_levels(keeps, x, sr, win=0.04):
    """최종 컷들의 이어붙는 지점 음량(dBFS) 목록. 검증·리포트용.

    반환: [(시각, 앞조각끝 dB, 뒷조각시작 dB), ...]  (내부 접합부만)
    """
    if x is None or len(x) == 0 or len(keeps) < 2:
        return []
    lv = []
    for i in range(len(keeps) - 1):
        a_end = float(keeps[i][1])
        b_start = float(keeps[i + 1][0])
        lv.append((a_end,
                   _rms_db(x, sr, a_end - win, a_end),
                   _rms_db(x, sr, b_start, b_start + win)))
    return lv
