import json, math, sys
P="/Users/anyhowclick/Desktop/work/obed-edom/.cache/inspect/dc036aea828742c1a1faa773efb72d497fcfe630f9d32c05919c1abf9678f1c6.v5.k15.3.1.json"
d=json.load(open(P))
def R(i): return (i['x'],i['y'],i['w'],i['h'])
def contains(p,l,tol):
    px,py,pw,ph=p; lx,ly,lw,lh=l
    return px<=lx+tol and py<=ly+tol and px+pw>=lx+lw-tol and py+ph>=ly+lh-tol
SL=[int(x) for x in sys.argv[1:]] or [2,5,8,13,17,18,20,21,22]
for n in SL:
    s=d['slides'][n-1]; its=s['items']
    labels=[i for i in its if i.get('kind')=='text' and str(i.get('text','')).startswith('CHC')]
    shapes=[i for i in its if i.get('kind')=='shape']
    dots=[i for i in shapes if 0<i['w']<=30 and 0<i['h']<=30 and abs(i['w']-i['h'])<=2]
    print(f"=== slide {n}: labels={len(labels)} shapes={len(shapes)} dots={len(dots)}")
    fonts=sorted({i['size'] for i in labels})
    print("  label fonts:",fonts, " label h:",sorted({i['h'] for i in labels}))
    stats={}
    for L in labels:
        lr=R(L)
        cands=[c for c in shapes if c is not L and c not in dots and contains(R(c),lr,3.0) and c['w']*c['h']<lr[2]*lr[3]*6]
        stats[L['kindIndex']]=len(cands)
        pads=[]
        for c in cands:
            cx,cy,cw,ch=R(c)
            pads.append((round(lr[0]-cx,1),round(cx+cw-(lr[0]+lr[2]),1),round(lr[1]-cy,1),round(cy+ch-(lr[1]+lr[3]),1)))
        if len(cands)!=1:
            print(f"   !! '{L['text']}' {lr} cands={len(cands)} {pads}")
        else:
            c=cands[0]
            # dot association
            pr=R(c); pcx,pcy=pr[0]+pr[2]/2,pr[1]+pr[3]/2
            ds=sorted(((math.hypot(dd['x']+dd['w']/2-pcx,dd['y']+dd['h']/2-pcy),dd) for dd in dots),key=lambda t:t[0])
            dd=ds[0] if ds else None
            side=''
            if dd:
                dx=dd[1]['x']+dd[1]['w']/2-pcx; dy=dd[1]['y']+dd[1]['h']/2-pcy
                side=('L' if dx<-pr[2]/2 else 'R' if dx>pr[2]/2 else 'C')+('U' if dy<-pr[3]/2 else 'D' if dy>pr[3]/2 else 'M')
            print(f"   '{L['text']}' lbl={lr} pill={pr} pad={pads[0]} dot_d={round(dd[0],1) if dd else None} side={side} dotki={dd[1]['kindIndex'] if dd else None}")
    from collections import Counter
    print("  cand-count histogram:",dict(Counter(stats.values())))
