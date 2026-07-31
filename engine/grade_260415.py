import sys, os, json, numpy as np
sys.path.insert(0,'engine')
from PIL import Image
import eye_grade as E, apply_grade_still as G
LW=np.array([.2126,.7152,.0722],np.float32)

REC = {
 "cam01": dict(whites=0.348, blacks=0.02, contrast=0.10, sat=1.12,
               skin_smin=0.18, skin_dr=12, skin_db=9, skin_sat=1.30, gamma=1.10),
 "cam02": dict(whites=0.115, blacks=0.02, contrast=0.10, sat=1.12,
               skin_smin=0.30, skin_dr=9,  skin_db=6, skin_sat=1.20, gamma=1.00),
}
def screen(img):
    f=img.astype(np.float32); lum=f@LW; mx,mn=f.max(2),f.min(2)
    s=np.where(mx>0,(mx-mn)/np.maximum(mx,1),0); return (lum>200)&(s<0.10)
def skin(img,smin):
    h,s,v=G._hsv(img); return ((h<45)|(h>350))&(s>smin)&(s<0.65)&(v>0.25)
def apply(img,p):
    x=E.correct(img,wb=1.0,whites=p["whites"],blacks=p["blacks"],
                contrast=p["contrast"],sat=p["sat"])
    f=x.astype(np.float32); sk=skin(x,p["skin_smin"]).astype(np.float32)
    y=f.copy(); y[...,0]+=p["skin_dr"]*sk; y[...,2]-=p["skin_db"]*sk
    l=(y@LW)[...,None]; y=np.where(sk[...,None]>0,l+(y-l)*p["skin_sat"],y)
    y=np.clip(y,0,255).astype(np.uint8)
    if p["gamma"]!=1.0:
        y=np.clip(np.power(np.clip(y.astype(np.float32)/255,0,1),1/p["gamma"])*255,0,255).astype(np.uint8)
    return y
def stat(img,scr):
    f=img.astype(np.float32); lum=f@LW; mx,mn=f.max(2),f.min(2)
    sat=np.where(mx>0,(mx-mn)/np.maximum(mx,1),0)
    m=G.neutral_mask(img)&~scr; sk=skin(img,0.18)
    w=[f[...,c][m].mean() for c in range(3)]; k=[f[...,c][sk].mean() for c in range(3)]
    return dict(mid=float(np.median(lum[~scr])), p90=float(np.percentile(lum[~scr],90)),
                blown=float((mx[~scr]>=254).mean()*100), wall=float(max(w)-min(w)),
                rb=float(k[0]-k[2]), rg=float(k[0]-k[1]), sat=float(sat[sk].mean()*100))
if __name__=="__main__":
    HERE=os.path.dirname(os.path.abspath(__file__)); out={}
    for cam,src in [("cam01","cam01_300.jpg"),("cam02","cam02_300.jpg")]:
        img=np.array(Image.open(f"{HERE}/{src}").convert("RGB"))
        g=apply(img,REC[cam]); scr=screen(img)
        b,a=stat(img,scr),stat(g,scr); out[cam]=a
        print(f"{cam}  중앙 {b['mid']:5.1f}→{a['mid']:5.1f}  p90 {b['p90']:5.1f}→{a['p90']:5.1f}  "
              f"날아감 {a['blown']:.2f}%  벽 {b['wall']:4.1f}→{a['wall']:4.1f}  "
              f"피부R-B {b['rb']:+5.1f}→{a['rb']:+5.1f}  채도 {b['sat']:4.1f}→{a['sat']:4.1f}%")
        Image.fromarray(g).save(f"{HERE}/OUT_{cam}.jpg",quality=93)
    print(f"\n두 캠 차이  R-B {abs(out['cam01']['rb']-out['cam02']['rb']):.1f}  "
          f"채도 {abs(out['cam01']['sat']-out['cam02']['sat']):.1f}%p  "
          f"중앙 {abs(out['cam01']['mid']-out['cam02']['mid']):.1f}")
