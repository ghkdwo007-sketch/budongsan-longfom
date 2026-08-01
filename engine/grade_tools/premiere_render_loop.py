"""벽 색이 맞을 때까지 cam02 를 자동으로 반복 보정한다.
프리미어에서 직접 렌더 → 측정 → 값 조정 → 다시 렌더."""
import sys, os, json, time, subprocess
sys.path.insert(0,'engine')
import numpy as np
from PIL import Image
from premiere_mcp import Premiere
import apply_grade_still as G

LW=np.array([.2126,.7152,.0722],np.float32)
SP=os.path.dirname(os.path.abspath(__file__))
PRESET=f"{SP}/lowbr.epr"
pr=Premiere()

def seq_js(body):
    return f"""(function(){{
      var sqs=app.project.sequences,s=null;
      for(var i=0;i<sqs.numSequences;i++) if(sqs[i].name.indexOf('260415_빌딩롱폼')>=0) s=sqs[i];
      if(!s) return 'NO_SEQ';
      app.project.activeSequence=s;
      {body}
    }})()"""

def set_v2(mute):
    pr.call("execute_extendscript", script=seq_js(
        f"s.videoTracks[1].setMute({1 if mute else 0}); return 'v2mute={1 if mute else 0}';"))

def render(tag):
    out=f"/tmp/loop_{tag}.mp4"
    if os.path.exists(out): os.remove(out)
    r=pr.call("execute_extendscript", script=seq_js(
        f"app.encoder.launchEncoder();"
        f"var r=app.encoder.encodeSequence(s,'{out}','{PRESET}',app.encoder.ENCODE_IN_TO_OUT,0,1);"
        f"return 'ok='+r;"))
    for _ in range(60):
        if os.path.exists(out) and os.path.getsize(out)>50000: break
        time.sleep(2)
    time.sleep(2)
    png=f"/tmp/loop_{tag}.png"
    subprocess.run(["ffmpeg","-y","-loglevel","error","-ss","0.2","-i",out,"-frames:v","1",png],check=True)
    return png

def wall(png):
    f=np.array(Image.open(png).convert("RGB")).astype(np.float32); im=f.astype(np.uint8)
    lum=f@LW; mx,mn=f.max(2),f.min(2)
    s=np.where(mx>0,(mx-mn)/np.maximum(mx,1),0); scr=(lum>200)&(s<0.10)
    m=G.neutral_mask(im)&~scr
    if m.sum()<100: return None
    w=np.array([f[...,c][m].mean() for c in range(3)])
    sk=G.skin_mask(im); k=np.array([f[...,c][sk].mean() for c in range(3)])
    return dict(w=w, skin=k, mid=float(np.median(lum[~scr])))

def set_lumetri(tk, vals):
    sets="".join(f"try{{lum.properties[{k}].setValue({v},true);}}catch(e){{}}" for k,v in vals.items())
    pr.call("execute_extendscript", script=seq_js(
        f"var c=s.videoTracks[{tk}].clips[0], lum=null;"
        "for(var k=0;k<c.components.numItems;k++)"
        "  if(c.components[k].displayName.indexOf('Lumetri')>=0) lum=c.components[k];"
        f"if(!lum) return 'NO_LUM'; {sets} return 'set';"))

def match_pct(a,b):
    return 100.0*(1 - float(np.mean(np.abs(a-b)))/float(np.mean(a)))

def frame_stat(png):
    """화면 전체 기준 — 자체발광 모니터만 제외한 전 픽셀의 색·밝기."""
    f=np.array(Image.open(png).convert("RGB")).astype(np.float32)
    lum=f@LW; mx,mn=f.max(2),f.min(2)
    s=np.where(mx>0,(mx-mn)/np.maximum(mx,1),0)
    scr=(lum>200)&(s<0.10)              # 모니터(밝고 무채색)
    keep=~scr
    rgb=np.array([f[...,c][keep].mean() for c in range(3)])
    return dict(rgb=rgb, mid=float(np.median(lum[keep])),
                mean=float(lum[keep].mean()), sat=float(s[keep].mean()*100))

def frame_match(a,b):
    """색(채널) + 밝기 일치도"""
    dc=float(np.mean(np.abs(a['rgb']-b['rgb'])))/float(np.mean(a['rgb']))
    db=abs(a['mid']-b['mid'])/max(a['mid'],1)
    return 100.0*(1-(dc*0.6+db*0.4))
