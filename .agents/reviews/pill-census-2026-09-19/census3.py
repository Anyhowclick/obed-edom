import json,math
from collections import Counter
P="/Users/anyhowclick/Desktop/work/obed-edom/.cache/inspect/dc036aea828742c1a1faa773efb72d497fcfe630f9d32c05919c1abf9678f1c6.v5.k15.3.1.json"
d=json.load(open(P))
def R(i): return (i['x'],i['y'],i['w'],i['h'])
def pair_rule(lr,pr):
    lx,ly,lw,lh=lr; px,py,pw,ph=pr
    if not (px<=lx+4 and px+pw>=lx+lw-4): return False       # x contains label (tol 4)
    lcy=ly+lh/2
    if not (py-0.25*lh<=lcy<=py+ph+0.25*lh): return False     # label centre inside pill band
    if not (0.6*lh<=ph<=3.0*lh): return False                 # height sane
    if pw>lw+0.8*lw+40: return False
    return True
def isdot(i,lh):
    return i.get('kind')=='shape' and 0<i['w']<=1.6*lh and 0<i['h']<=1.6*lh and abs(i['w']-i['h'])<=2
rows=[]
for n in (5,8,13,17,18):
    sl=d['slides'][n-1]; its=sl['items']
    labels=[i for i in its if i.get('kind')=='text' and str(i.get('text','')).startswith('CHC')]
    shapes=[i for i in its if i.get('kind')=='shape']
    hist=Counter(); pairs=[]
    for L in labels:
        lr=R(L)
        dots=[c for c in shapes if isdot(c,lr[3])]
        cands=[c for c in shapes if c is not L and not isdot(c,lr[3]) and pair_rule(lr,R(c))]
        hist[len(cands)]+=1
        if len(cands)==1:
            pairs.append((L,cands[0],dots))
        elif len(cands)>1:
            print(f"  s{n} MULTI '{L['text']}' {[R(c) for c in cands]}")
        else:
            print(f"  s{n} NONE '{L['text']}' {lr}")
    # dot association
    claimed=Counter(); dists=[]; sides=Counter(); nodot=0
    for L,Pl,dots in pairs:
        pr=R(Pl); pcx,pcy=pr[0]+pr[2]/2,pr[1]+pr[3]/2
        best=None
        for dd in dots:
            dcx,dcy=dd['x']+dd['w']/2,dd['y']+dd['h']/2
            # distance from dot centre to pill rect
            dx=max(pr[0]-dcx,0,dcx-(pr[0]+pr[2])); dy=max(pr[1]-dcy,0,dcy-(pr[1]+pr[3]))
            dist=math.hypot(dx,dy)
            if best is None or dist<best[0]: best=(dist,dd,dcx,dcy)
        RAD=2.5*pr[3]+30
        if best is None or best[0]>RAD:
            nodot+=1; sides['none']+=1; continue
        dists.append(round(best[0],1)); claimed[id(best[1])]+=1
        dcx,dcy=best[2],best[3]
        h='L' if dcx<pr[0] else 'R' if dcx>pr[0]+pr[2] else 'C'
        v='U' if dcy<pr[1] else 'D' if dcy>pr[1]+pr[3] else 'M'
        sides[h+v]+=1
    rows.append((n,len(labels),dict(hist),sorted(dists),dict(sides),nodot,sum(1 for v in claimed.values() if v>1)))
for r in rows: print("slide",r[0],"labels",r[1],"candhist",r[2],"\n   dists",r[3],"\n   sides",r[4],"nodot",r[5],"shared_dots",r[6])
