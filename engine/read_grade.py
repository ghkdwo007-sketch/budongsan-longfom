"""프리미어 시퀀스의 Lumetri 색보정 값을 읽는다 (클립별 → 서로 다른 설정만 묶어서).

    python engine/read_grade.py                 # 활성 시퀀스
    python engine/read_grade.py --tracks 0 1 2

**MCP `list_clip_effects` 는 쓰지 말 것** — trackIndex/clipIndex 인자를 무시하고 항상
첫 클립만 돌려준다(실측). ExtendScript 로 직접 순회한다.

Lumetri 파라미터는 그룹 헤더까지 포함된 평면 배열(130개)이라 **인덱스로 읽는다**.
이름은 로케일별로 번역되고(한글판 '온도'/'채도') 같은 이름이 그룹마다 반복돼 못 믿는다.
"""
import argparse
import struct
import sys

from premiere_mcp import Premiere

# 인덱스 → 이름 (한글판 Premiere 26.3 실측)
BASIC = {14: "온도", 15: "색조", 16: "채도", 19: "노출", 20: "대비",
         21: "밝은 영역", 22: "어두운 영역", 23: "흰색", 24: "검정"}
CREATIVE = {34: "룩", 38: "룩 강도", 40: "빛바랜 필름", 41: "선명",
            42: "생동감", 43: "채도", 45: "색조 균형"}
OTHER = {6: "LUT 입력", 79: "색상 휠 블롭", 110: "비네팅 양", 125: "AutoTone"}
ALL = {**BASIC, **CREATIVE, **OTHER}

_FIND_LUM = ("var l=null;for(var k=0;k<cl.components.numItems;k++){"
             "if(cl.components[k].displayName.indexOf('Lumetri')>=0)l=cl.components[k];}")


def _js(track, clip, body):
    return ("(function(){var cl=app.project.activeSequence.videoTracks[%d].clips[%d];%s"
            "if(!l)return 'NO_LUMETRI';%s})()" % (track, clip, _FIND_LUM, body))


def read_clip(pr, track, clip, indices=tuple(sorted(ALL))):
    """한 클립의 Lumetri 값 {인덱스: 문자열}."""
    body = ("var o=[];var ids=[%s];for(var i=0;i<ids.length;i++){var v;"
            "try{v=String(l.properties[ids[i]].getValue());}catch(e){v='ERR';}"
            "o.push(ids[i]+'='+v.substring(0,24));}return o.join(';');"
            % ",".join(str(i) for i in indices))
    r = pr.call("execute_extendscript", script=_js(track, clip, body))
    if not isinstance(r, str) or r == "NO_LUMETRI":
        return None
    out = {}
    for part in r.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[int(k)] = v
    return out


WHEEL_NAMES = ("어두운 영역", "미드톤", "밝은 영역")


def read_wheels(pr, track, clip):
    """색상 휠 블롭(36 UTF-16 단위 = 9 double)을 숫자로 푼다.

    3개씩 **(각도°, 루마 0~1, 채도 0~1)** 이고 어두운 영역 → 미드톤 → 밝은 영역 순이다.
    Lumetri 패널 스크린샷과 대조해 확인했다 — 260729 cam01 의 루마가 0.032/0.846/0.940
    으로 읽혔고 패널의 세로 슬라이더가 각각 맨아래/위/위였다. 채도는 크로스헤어가
    중심에서 벗어난 정도로, 0.1~0.19 면 눈에 겨우 보이는 수준이다.

    (처음엔 (각도, 채도, 밝기) 로 읽었는데 틀렸다 — 휠이 거의 중앙인데 두 번째 값이
    0.85, 0.94 로 커서 앞뒤가 안 맞았다. 가운데가 루마다.)
    """
    body = ("var v=String(l.properties[79].getValue());var h=[];"
            "for(var j=0;j<v.length;j++){h.push(v.charCodeAt(j));}return h.join(',');")
    r = pr.call("execute_extendscript", script=_js(track, clip, body))
    if not isinstance(r, str) or "," not in r:
        return None
    raw = b"".join(struct.pack("<H", int(u)) for u in r.split(","))
    n = len(raw) // 8
    return struct.unpack("<%dd" % n, raw[:n * 8])


def clip_count(pr, track):
    # 숫자만 돌아오면 클라이언트가 JSON 으로 파싱해 int 로 준다 — 둘 다 받는다
    r = pr.call("execute_extendscript", script=(
        "(function(){return String(app.project.activeSequence.videoTracks[%d]"
        ".clips.numItems);})()" % track))
    if isinstance(r, (int, float)):
        return int(r)
    return int(r) if isinstance(r, str) and r.isdigit() else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=int, nargs="+", default=[0, 1])
    ap.add_argument("--max-clips", type=int, default=400)
    a = ap.parse_args()

    with Premiere() as pr:
        name = pr.call("execute_extendscript",
                       script="(function(){return app.project.activeSequence.name;})()")
        print(f"시퀀스: {name}\n")
        for t in a.tracks:
            n = min(clip_count(pr, t), a.max_clips)
            groups = {}
            for c in range(n):
                vals = read_clip(pr, t, c)
                key = "NO_LUMETRI" if vals is None else ";".join(
                    f"{k}={vals.get(k)}" for k in sorted(ALL))
                groups.setdefault(key, []).append(c)
            print(f"── V{t+1}: 클립 {n}개 → 서로 다른 설정 {len(groups)}가지")
            for key, clips in sorted(groups.items(), key=lambda x: -len(x[1])):
                print(f"   [{len(clips)}클립] 예: clip {clips[0]}")
                if key == "NO_LUMETRI":
                    print("      Lumetri 없음")
                    continue
                vals = dict(p.split("=", 1) for p in key.split(";"))
                for grp, tbl in (("기본", BASIC), ("크리에이티브", CREATIVE), ("기타", OTHER)):
                    s = "  ".join(f"{nm}={vals.get(str(i))}" for i, nm in tbl.items()
                                  if i != 79)
                    print(f"      {grp:<7} {s}")
                w = read_wheels(pr, t, clips[0])
                if w:
                    for wi, nm in enumerate(WHEEL_NAMES):
                        ang, luma, sat = w[wi * 3:wi * 3 + 3]
                        print(f"      {nm:<8} 각도 {ang:6.2f}°  루마 {luma:.3f}  채도 {sat:.3f}")
            print()
