#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_glossary.py — 프로파일 용어집으로 자막 고유명사/오인식을 일괄 교정한다.

Whisper 오인식은 회차마다 조금씩 형태가 달라서, 매번 손으로 잡으면 같은 일을 반복하게 된다.
프로파일별 glossary.txt 에 쌓아두고 회차마다 적용 → 거듭할수록 정확해진다.

중요: **subtitle_polish(분할) 이전에** 돌려야 한다. 분할 후에는 줄 나눔이 바뀌어
      문맥이 걸린 규칙이 안 맞는다.

사용:
  python apply_glossary.py "output/<base>_cut.srt" --profile 부동산롱폼
  python apply_glossary.py "자막.srt" --glossary "경로/glossary.txt"
  python apply_glossary.py "자막.srt" --profile 부동산롱폼 --dry-run
"""
import sys, os, re, shutil

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_glossary(path):
    rules = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.split("#", 1)[0].rstrip()
        if not ln.strip() or "=>" not in ln:
            continue
        a, _, b = ln.partition("=>")
        a, b = a.strip(), b.strip()
        if a:
            rules.append((a, b))
    # 긴 규칙 먼저 — 짧은 규칙이 긴 문맥을 먼저 깨뜨리지 않게
    rules.sort(key=lambda r: -len(r[0]))
    return rules


def split_blocks(raw):
    return [b.splitlines() for b in re.split(r"\r?\n\r?\n", raw.strip("﻿").strip())]


def main():
    args = sys.argv[1:]
    profile = gloss = None
    dry = "--dry-run" in args
    if dry:
        args.remove("--dry-run")
    for flag, var in (("--profile", "profile"), ("--glossary", "gloss")):
        if flag in args:
            i = args.index(flag)
            val = args[i + 1]
            del args[i:i + 2]
            if var == "profile":
                profile = val
            else:
                gloss = val
    if not args:
        print(__doc__); sys.exit(1)
    srt = args[0]
    if gloss is None:
        if not profile:
            print("--profile 또는 --glossary 가 필요합니다"); sys.exit(1)
        gloss = os.path.join(PROJ, "profiles", profile, "glossary.txt")
    for p in (srt, gloss):
        if not os.path.exists(p):
            print("파일 없음:", p); sys.exit(2)

    rules = load_glossary(gloss)
    blocks = split_blocks(open(srt, encoding="utf-8").read())
    parsed = [(b[:2], "\n".join(b[2:])) for b in blocks if len(b) >= 3]
    joined = "\n\n".join(t for _h, t in parsed)

    applied, missed, blocked = [], [], []
    for a, b in rules:
        n = joined.count(a)
        if n:
            joined = joined.replace(a, b); applied.append((a, b, n))
            continue
        # 자막 경계로 쪼개졌을 수 있음 → 공백 하나를 블록 경계로 바꿔 재시도.
        # 단 교체 문구도 경계 양쪽에 나눠 담을 수 있어야 한다. 못 담으면 구분자가 사라져
        # 자막 블록이 통째로 합쳐지므로(실측 633→631) 그런 규칙은 건너뛰고 보고한다.
        hit = False
        parts, bp = a.split(" "), b.split(" ")
        for k in range(len(parts) - 1):
            alt = " ".join(parts[:k + 1]) + "\n\n" + " ".join(parts[k + 1:])
            if alt not in joined:
                continue
            if b and len(bp) > k + 1:
                rep = " ".join(bp[:k + 1]) + "\n\n" + " ".join(bp[k + 1:])
            elif not b:
                rep = "\n\n"                      # 삭제 규칙 — 구분자는 유지
            else:
                blocked.append((a, b)); hit = True; break
            joined = joined.replace(alt, rep)
            applied.append((a + " (경계)", b, 1)); hit = True; break
        if not hit:
            missed.append(a)

    texts = joined.split("\n\n")
    if len(texts) != len(parsed):
        print(f"[중단] 블록 수 불일치 {len(texts)} != {len(parsed)} — 치환이 자막 경계를 깨뜨림")
        sys.exit(3)

    print(f"용어집 {len(rules)}개 규칙 · 적용 {len(applied)} / 해당없음 {len(missed)}"
          + (f" / 보류 {len(blocked)}" if blocked else ""))
    for a, b, n in applied:
        print(f"   {a}  →  {b or '(삭제)'}" + (f"  x{n}" if n > 1 else ""))
    for a, b in blocked:
        print(f"   [보류] {a!r} — 자막 경계에 걸쳤는데 교체 문구를 양쪽에 나눌 수 없음. 수동 확인 필요")
    if dry:
        print("\n[dry-run] 파일을 건드리지 않았습니다."); return

    # 비워진 자막은 통째로 제거하고 번호를 다시 매긴다
    kept = [(h, t.strip()) for (h, _o), t in zip(parsed, texts) if t.strip()]
    dropped = len(parsed) - len(kept)
    body = "\n\n".join(f"{i}\n{h[1]}\n" + t for i, (h, t) in enumerate(kept, 1))
    shutil.copy(srt, srt + ".pre_glossary")
    open(srt, "w", encoding="utf-8").write(body + "\n")
    print(f"\n저장: {os.path.basename(srt)} (이전본 .pre_glossary)"
          + (f" · 빈 자막 {dropped}개 제거" if dropped else ""))
    print("다음: python engine/subtitle_polish.py 로 분할·마감")


if __name__ == "__main__":
    main()
