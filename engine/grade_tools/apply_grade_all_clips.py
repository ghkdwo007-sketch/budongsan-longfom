"""캠별 확정값을 트랙의 모든 클립에 얹는다.
QE 인덱스는 빈 구간을 포함해 clips 인덱스와 어긋난다 → 시작 시각으로 매칭한다."""
import sys, os, json
sys.path.insert(0,'engine'); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from loop import pr, seq_js

V1={14:-12.0,15:16.6,16:124,19:0.72,20:12,21:0,22:8,23:35,24:4,42:34,43:128}
V2={14:-20.0,15:10.5,16:118,19:0.18,20:12,21:0,22:8,23:20,24:4,42:28,43:123}

def batch(tk, vals, lo, hi):
    sets="".join(f"try{{lum.properties[{k}].setValue({v},true);}}catch(e){{}}" for k,v in vals.items())
    js=(f"app.enableQE();"
        f"var qs=qe.project.getActiveSequence(), qt=qs.getVideoTrackAt({tk});"
        f"var tr=s.videoTracks[{tk}], done=0, added=0;"
        f"for(var i={lo};i<Math.min({hi},tr.clips.numItems);i++){{"
        "  var c=tr.clips[i], lum=null;"
        "  for(var k=0;k<c.components.numItems;k++)"
        "   if(c.components[k].displayName.indexOf('Lumetri')>=0){lum=c.components[k];break;}"
        "  if(!lum){"
        "    var st=c.start.seconds, qi=-1;"
        "    for(var q=0;q<qt.numItems;q++){"
        "      var it=qt.getItemAt(q);"
        "      if(it && it.start && Math.abs(it.start.secs-st)<0.02){qi=q;break;}}"
        "    if(qi>=0){"
        "      try{ qt.getItemAt(qi).addVideoEffect(qe.project.getVideoEffectByName('Lumetri Color')); added++; }catch(e){}"
        "      for(var k=0;k<c.components.numItems;k++)"
        "       if(c.components[k].displayName.indexOf('Lumetri')>=0){lum=c.components[k];break;}}}"
        "  if(!lum) continue;"
        f"  {sets}"
        "  done++;"
        "}"
        "return 'set='+done+' added='+added;")
    return pr.call("execute_extendscript", script=seq_js(js))

if __name__=="__main__":
    tk=int(sys.argv[1]); lo=int(sys.argv[2]); hi=int(sys.argv[3])
    print(f"V{tk+1} {lo}~{hi}:", batch(tk, V1 if tk==0 else V2, lo, hi))
