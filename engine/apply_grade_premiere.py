"""프리미어 시퀀스의 **맨 앞 1컷**에 확정 색보정(Lumetri)을 얹는다.

    python engine/apply_grade_premiere.py "<시퀀스 이름 일부>"
    python engine/apply_grade_premiere.py "0014_D" --all      # 전 클립 (느리다)

**왜 1컷만인가** — 시퀀스 전체에 넣으면 오래 걸린다(100클립에 수 분). 비블이 맨 앞 컷을
복사해 **특성 붙여넣기**로 나머지에 퍼뜨리는 게 훨씬 빠르다. 그래서 납품은 '컷편집된
시퀀스 + 첫 컷 색보정' 상태로 한다.

값은 `profiles/<프로파일>/grade_lumetri.json` 에서 읽는다 — 비블이 프리미어에서 직접
잡아 준 것을 그대로 저장해 둔 것이다(260630 기준).

전제: 프리미어 실행 중 + CEP 브리지 패널에서 Start Bridge. `engine/premiere_mcp.py` 참고.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from premiere_mcp import Premiere

# Lumetri 속성은 그룹 헤더까지 포함된 평면 배열이라 **인덱스로** 읽고 쓴다.
# 이름은 로케일마다 번역되고 그룹마다 중복돼서 못 믿는다(한글판 26.3 실측).
IDX = {"온도": 14, "색조": 15, "기본채도": 16, "노출": 19, "대비": 20,
       "밝은영역": 21, "어두운영역": 22, "흰색": 23, "검정": 24,
       "크리에이티브채도": 43, "색상휠": 79}

_FIND = ("var lum=null;for(var k=0;k<c.components.numItems;k++)"
         "if(c.components[k].displayName.indexOf('Lumetri')>=0)lum=c.components[k];")


def _js(seq_key, body):
    """대상 시퀀스를 **매 호출마다** 이름으로 다시 활성화한다.

    브리지 호출 사이에 프리미어가 활성 시퀀스를 되돌린다 — 지정하지 않으면
    엉뚱한 시퀀스(예: 비블 완성본)를 건드린다. 실제로 그럴 뻔했다.
    """
    return f"""(function(){{
      var sq=app.project.sequences, target=null;
      for(var s=0;s<sq.numSequences;s++)
        if(sq[s].name.indexOf({json.dumps(seq_key)})>=0){{ target=sq[s]; break; }}
      if(!target) return 'NO_SEQ';
      app.project.activeSequence = target;
      {body}
    }})()"""


def load_grade(profile="부동산롱폼"):
    import config
    d = config._find_profile_dir(PROJ, profile)
    with open(os.path.join(d, "grade_lumetri.json"), encoding="utf-8") as f:
        return json.load(f)


def apply(pr, seq_key, grade, count=1):
    sets = "".join(
        f"try{{lum.properties[{IDX[k]}].setValue({v},true);}}catch(e){{}}"
        for k, v in grade["기본교정"].items() if k in IDX)
    sets += (f"try{{lum.properties[{IDX['크리에이티브채도']}]"
             f".setValue({grade['크리에이티브채도']},true);}}catch(e){{}}")
    # 색상 휠은 문자열 블롭이다 — UTF-16 코드로 되살려 넣는다(각도·루마·채도가 다 들어 있다)
    codes = ",".join(str(c) for c in grade["색상휠_블롭"])
    sets += (f"var cs=[{codes}], blob='';"
             f"for(var z=0;z<cs.length;z++) blob+=String.fromCharCode(cs[z]);"
             f"try{{lum.properties[{IDX['색상휠']}].setValue(blob,true);}}catch(e){{}}")

    return pr.call("execute_extendscript", script=_js(seq_key, f"""
      app.enableQE();
      var qtr=qe.project.getActiveSequence().getVideoTrackAt(0);
      var tr=target.videoTracks[0];
      var n = {count} < 0 ? tr.clips.numItems : Math.min({count}, tr.clips.numItems);
      var done=0;
      for(var i=0;i<n;i++){{
        var c=tr.clips[i]; {_FIND}
        if(!lum){{
          qtr.getItemAt(i).addVideoEffect(qe.project.getVideoEffectByName('Lumetri 색상'));
          {_FIND}
        }}
        if(!lum) continue;
        {sets}
        done++;
      }}
      return target.name+'|clips='+tr.clips.numItems+'|graded='+done;
    """))


def read_back(pr, seq_key, i=0):
    body = "".join(f"o.push('{k}='+lum.properties[{v}].getValue());"
                   for k, v in IDX.items() if k != "색상휠")
    return pr.call("execute_extendscript", script=_js(seq_key, f"""
      var c=target.videoTracks[0].clips[{i}]; {_FIND}
      if(!lum) return 'NO_LUMETRI';
      var o=[]; {body}
      o.push('색상휠길이='+String(lum.properties[{IDX['색상휠']}].getValue()).length);
      return o.join(' ');
    """))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence", help="시퀀스 이름의 일부 (예: 0014_D)")
    ap.add_argument("--profile", default="부동산롱폼")
    ap.add_argument("--all", action="store_true", help="전 클립에 적용 (느리다)")
    a = ap.parse_args()

    grade = load_grade(a.profile)
    with Premiere() as pr:
        r = apply(pr, a.sequence, grade, count=-1 if a.all else 1)
        print("적용:", r)
        print("확인:", read_back(pr, a.sequence, 0))
    if not a.all:
        print("\n비블: 맨 앞 컷을 복사(Ctrl+C) → 나머지 전체 선택 →"
              " 특성 붙여넣기(Ctrl+Alt+V)로 퍼뜨리세요.")
