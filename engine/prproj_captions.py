"""`.prproj` 에서 비블이 고친 자막(캡션)을 뽑는다.

**프리미어는 캡션 읽기 API 가 없다.** MCP `read_sequence_captions` 는 캡션 트랙이
멀쩡히 있어도 항상 `trackCount:0` 을 돌려준다(Adobe 제한 — `createCaptionTrack` 은
쓰기만 되고 읽는 짝이 없다). 그래서 프로젝트 파일을 직접 판다.

구조: `.prproj` = gzip XML → `<Caption>` 이 `TimeStart/TimeEnd`(틱, 1초=254016000000)와
`<Block>` 참조를 갖고, `<Block>` 의 `FormattedTextData` 는 base64 FlatBuffer 안에
UTF-8 본문을 담고 있다.

    python engine/prproj_captions.py "<프로젝트.prproj>" [-o out.json]

자막 교정 학습에 쓴다 — 우리 `_cut.srt` 와 대조하면 오타·분할·문장부호 규칙이 나온다
(`engine/sub_diff.py`).
"""
import argparse
import base64
import gzip
import json
import re
import sys

TICKS_PER_SEC = 254016000000


def _block_text(b64):
    """FlatBuffer 문자열(4바이트 LE 길이 + UTF-8 + NUL)에서 본문을 고른다.

    폰트명 등 다른 문자열도 같은 버퍼에 있어서 '한글이 있고 제어문자가 없는 것' 중
    가장 긴 것을 쓴다. 길이·NUL 종단을 확인하지 않으면 앞뒤 바이너리가 딸려 온다.
    """
    data = base64.b64decode(b64)
    best = ""
    for i in range(len(data) - 4):
        n = int.from_bytes(data[i:i + 4], "little")
        if not (1 <= n <= 500) or i + 4 + n >= len(data):
            continue
        if data[i + 4 + n] != 0:
            continue
        try:
            text = data[i + 4:i + 4 + n].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not re.search(r"[가-힣]", text):
            continue
        if any(ord(ch) < 0x20 and ch != "\n" for ch in text):
            continue
        if len(text) > len(best):
            best = text
    return best.strip()


def extract(prproj_path):
    """[{start, end, text}] — 초 단위, 시작 시각 오름차순."""
    raw = gzip.open(prproj_path, "rb").read().decode("utf-8", "replace")
    blocks = dict(re.findall(
        r'<Block ObjectID="(\d+)".*?<FormattedTextData[^>]*>\s*'
        r'([A-Za-z0-9+/=\s]+?)\s*</FormattedTextData>', raw, re.S))
    caps = []
    for m in re.finditer(
            r'<Caption ObjectID="\d+".*?<BlockVectorItem Index="0" ObjectRef="(\d+)"/>'
            r'.*?<TimeStart>(\d+)</TimeStart>\s*<TimeEnd>(\d+)</TimeEnd>', raw, re.S):
        b64 = blocks.get(m.group(1))
        if not b64:
            continue
        text = _block_text(re.sub(r"\s", "", b64))
        if text:
            caps.append({"start": int(m.group(2)) / TICKS_PER_SEC,
                         "end": int(m.group(3)) / TICKS_PER_SEC,
                         "text": text})
    caps.sort(key=lambda c: c["start"])
    return caps


def to_srt(caps):
    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round(s % 1 * 1000)):03d}"
    return "\n".join(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n"
                     for i, c in enumerate(caps, 1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("prproj")
    ap.add_argument("-o", "--out", help="JSON 저장 경로")
    ap.add_argument("--srt", help="SRT 로도 저장")
    a = ap.parse_args()

    caps = extract(a.prproj)
    print(f"자막 {len(caps)}개  {caps[0]['start']:.2f}s ~ {caps[-1]['end']:.2f}s")
    if a.out:
        json.dump(caps, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.srt:
        open(a.srt, "w", encoding="utf-8").write(to_srt(caps))
    for c in caps[:8]:
        print(f"  {c['start']:7.2f}-{c['end']:7.2f} ({len(c['text']):>2}자) {c['text']}")
