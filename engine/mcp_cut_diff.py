"""비블 수정본(프리미어에서 직접 읽음) ↔ 엔진 컷(_cut.xml) 비교.

편집 학습 루프의 측정 도구. 비블이 손으로 고친 시퀀스를 EDL 로 재내보내지 않고
프리미어 MCP 로 읽어, 엔진 산출물과 **소스 시간축에서** 대조한다.

    python engine/mcp_cut_diff.py "대표님미빅님 Q&A3편(최종본)" \
        output/_prev_260728_부동산/..._cut.xml output/_v207_260730/..._cut.xml

여러 버전을 함께 넘겨야 한다 — 납품본 기준으로만 보면 그 뒤에 이미 고친 것까지
두 번 보정하게 된다(과보정). 자세한 이유는 `output/_prev_.../BASELINE.md`.

읽는 값의 의미:
  1 축약률   원본 대비 유지 시간. 엔진(무음·더듬)과 비블(+내용 컷)의 몫을 가른다
  2 처리분류 우리 컷을 통째 삭제 / 일부만 / 그대로 로 나눈다
  3 되살림   우리가 버렸는데 비블이 되살린 양 = **과잉 제거**. 엔진이 실제로 틀린 곳
  4 경계델타 유지된 컷의 머리/꼬리 차이. 중앙값이 0 이면 패딩 값은 손댈 필요 없다
"""
import argparse
import sys
import xml.etree.ElementTree as ET

from premiere_mcp import Premiere


def engine_segs(xml_path):
    """_cut.xml → 소스 구간 [(in초, out초)]. 프레임은 소스 실제 fps 단위다."""
    root = ET.parse(xml_path).getroot()
    seq = root.find(".//sequence")
    tb = int(seq.findtext("rate/timebase"))
    fps = tb * 1000 / 1001 if (seq.findtext("rate/ntsc") or "").upper() == "TRUE" else tb
    segs = [(int(c.findtext("in")) / fps, int(c.findtext("out")) / fps)
            for c in seq.findall(".//video//clipitem")]
    src_dur = int(root.findtext(".//file/duration")) / fps
    stem = (root.findtext(".//file/name") or "").rsplit(".", 1)[0]
    return segs, src_dur, stem


def revision_segs(seq_name, media_prefix, max_clip=60.0):
    """프리미어의 수정본 시퀀스에서 소스 구간을 읽는다.

    참고용으로 원본 전체를 통째로 올려둔 클립이 섞여 있어 `max_clip` 초 이상은 뺀다.
    편집 트랙은 캠별로 나뉘므로 `media_prefix` 로 해당 캠 클립만 고른다.
    """
    with Premiere() as pr:
        found = [s for s in pr.call("list_sequences")["sequences"] if s["name"] == seq_name]
        if not found:
            raise SystemExit(f"시퀀스 '{seq_name}' 없음")
        info = pr.call("get_full_sequence_info", sequenceId=found[0]["id"])
    best = []
    for track in info["data"]["videoTracks"]:
        segs = [(c["inPoint"], c["outPoint"]) for c in track["clips"]
                if c["name"].startswith(media_prefix) and c["outPoint"] - c["inPoint"] < max_clip]
        if len(segs) > len(best):
            best = segs
    return best


def merge(segs):
    out = []
    for a, b in sorted(segs):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def overlap(seg, others):
    a, b = seg
    return sum(max(0.0, min(b, d) - max(a, c)) for c, d in others)


def gaps(segs, dur):
    """유지 구간의 여집합 = 버린 구간"""
    out, prev = [], 0.0
    for a, b in merge(segs):
        if a - prev > 1e-6:
            out.append((prev, a))
        prev = b
    if dur - prev > 1e-6:
        out.append((prev, dur))
    return out


def total(segs):
    return sum(b - a for a, b in segs)


def best_match(seg, others):
    best, bov = None, 0.0
    for o in others:
        ov = min(seg[1], o[1]) - max(seg[0], o[0])
        if ov > bov:
            bov, best = ov, o
    return best, bov


def report(rev, versions, src_dur):
    rev_m = merge(rev)
    print(f"원본 {src_dur/60:.2f}분 / 수정본 {len(rev)}컷 "
          f"{total(rev)/60:.2f}분 (유지 {total(rev)/src_dur*100:.1f}%)\n")
    for label, segs in versions:
        t = total(segs)
        dropped = [s for s in segs if overlap(s, rev_m) < 0.10 * (s[1] - s[0])]
        partial = [s for s in segs if 0.10 * (s[1] - s[0]) <= overlap(s, rev_m) < 0.90 * (s[1] - s[0])]
        kept = [s for s in segs if overlap(s, rev_m) >= 0.90 * (s[1] - s[0])]
        revived = sum(overlap(g, rev_m) for g in gaps(segs, src_dur))
        din, dout = [], []
        for s in segs:
            m, ov = best_match(s, rev)
            if m and ov >= 0.5 * (s[1] - s[0]):
                din.append(m[0] - s[0])
                dout.append(s[1] - m[1])

        def med(v):
            return sorted(v)[len(v) // 2] if v else float("nan")

        print(f"[{label}] {len(segs)}컷 유지 {t/60:.2f}분 ({t/src_dur*100:.1f}%)")
        print(f"   통째 삭제 {len(dropped):>4}컷 {total(dropped)/60:5.2f}분  ← 내용 컷")
        print(f"   일부만    {len(partial):>4}컷 {total(partial)/60:5.2f}분")
        print(f"   그대로    {len(kept):>4}컷 {total(kept)/60:5.2f}분")
        print(f"   되살림    {revived:5.2f}s  ← 과잉 제거 (엔진이 틀린 양)")
        print(f"   경계델타  머리 중앙 {med(din):+.3f}s / 꼬리 중앙 {med(dout):+.3f}s "
              f"(n={len(din)}, +면 비블이 더 잘랐다)\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence", help="프리미어의 수정본 시퀀스 이름")
    ap.add_argument("cut_xml", nargs="+", help="비교할 엔진 _cut.xml (여러 버전)")
    ap.add_argument("--media-prefix", default=None,
                    help="수정본에서 고를 캠 클립 이름 접두사 (기본: _cut.xml 의 소스 파일명)")
    a = ap.parse_args()

    versions, src_dur, stem = [], None, None
    for p in a.cut_xml:
        segs, dur, s = engine_segs(p)
        src_dur, stem = dur, s
        versions.append((f"{len(segs)}컷", segs))

    # 접두사를 잘못 주면 다른 캠 트랙을 읽어 싱크 오프셋이 경계델타로 나타난다
    # (실측: cam01 XML ↔ cam02 트랙 → 머리/꼬리 중앙 ∓1.03s = cam02 지연 그 값)
    report(revision_segs(a.sequence, a.media_prefix or stem), versions, src_dur)
