#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_cut_audio.py — 정리 오디오를 '컷이 적용된 한 덩어리 WAV'로 만든다.

왜: EDL 로 오디오를 210개 이벤트로 쪼개 넣으면 프리미어가 각 클립의 소스 in점을
    못 살리고 전부 0부터 재생하는 문제가 있다. 그래서 오디오는 아예 컷을 미리 적용한
    단일 파일로 만들어 타임라인 0에 한 번만 올린다.

전제: output/<base>_cut.xml (keep 구간) + output/<base>_cut_audio.wav (전체길이 정리오디오)

사용:
  python make_cut_audio.py <마스터영상>
출력:
  output/<base>_cut_audio_flat.wav   ← 타임라인 00:00:00:00 에 그대로 올리면 됨
"""
import sys, os, re, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from silence_cut import FFMPEG, FFPROBE, run

NTSC_FPS = 30000 / 1001


def parse_keeps(cut_xml):
    t = open(cut_xml, encoding="utf-8").read()
    keeps = []
    for ci in re.finditer(r'<clipitem id="cv\d+">.*?</clipitem>', t, re.S):
        b = ci.group(0)
        i = re.search(r"<in>(\d+)</in>", b)
        o = re.search(r"<out>(\d+)</out>", b)
        if i and o:
            keeps.append((int(i.group(1)), int(o.group(1))))
    return keeps


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    master = sys.argv[1]
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.splitext(os.path.basename(master))[0]
    outdir = os.path.join(proj, "output")
    cut_xml = os.path.join(outdir, base + "_cut.xml")
    src_wav = os.path.join(outdir, base + "_cut_audio.wav")
    out_wav = os.path.join(outdir, base + "_cut_audio_flat.wav")
    for p in (cut_xml, src_wav):
        if not os.path.exists(p):
            print("필요 파일 없음:", p); sys.exit(2)

    keeps = parse_keeps(cut_xml)
    if not keeps:
        print("keep 구간을 못 읽음"); sys.exit(2)

    # 샘플 단위로 직접 자른다. ffmpeg concat 디먹서의 inpoint/outpoint 는 구간마다
    # 수십 ms 씩 밀려(실측 285구간에 12.6초 초과) 컷과 안 맞는다.
    import wave
    with wave.open(src_wav, "rb") as w:
        nch, sw, sr, nframes = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        pcm = w.readframes(nframes)
    bpf = nch * sw                                   # 샘플프레임당 바이트

    def smp(video_frame):                            # 영상 프레임 → 오디오 샘플 인덱스
        return int(round(video_frame / NTSC_FPS * sr))

    parts, total = [], 0
    for a, b in keeps:
        s0, s1 = smp(a), smp(b)
        s0 = max(0, min(s0, nframes)); s1 = max(s0, min(s1, nframes))
        parts.append(pcm[s0 * bpf:s1 * bpf])
        total += s1 - s0

    with wave.open(out_wav, "wb") as w:
        w.setnchannels(nch); w.setsampwidth(sw); w.setframerate(sr)
        w.writeframes(b"".join(parts))
    print(f"  샘플 단위 절단: {nch}ch {sr}Hz · {total} 샘플 ({total/sr:.3f}s)")
    if not os.path.exists(out_wav) or os.path.getsize(out_wav) == 0:
        print("생성 실패"); sys.exit(3)

    total_f = sum(b - a for a, b in keeps)
    want = total_f / NTSC_FPS
    got = float(run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", out_wav]).stdout.strip())
    print(f"생성: {os.path.basename(out_wav)}")
    print(f"  컷 {len(keeps)}개 · 기대 {want:.3f}s ({total_f}프레임) · 실제 {got:.3f}s "
          f"· 차이 {abs(got-want)*1000:.1f}ms")
    if abs(got - want) > 0.05:
        print("  [주의] 길이 차가 큽니다 — 확인 필요")
    else:
        print("  길이 일치 (프레임 1개 = 33.4ms 기준 안전)")
    print("\n프리미어: 이 WAV 를 오디오 트랙 00:00:00:00 에 그대로 올리면 컷과 맞습니다.")


if __name__ == "__main__":
    main()
