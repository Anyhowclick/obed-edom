import json,math
from itertools import combinations
P="/Users/anyhowclick/Desktop/work/obed-edom/.cache/inspect/dc036aea828742c1a1faa773efb72d497fcfe630f9d32c05919c1abf9678f1c6.v5.k15.3.1.json"
d=json.load(open(P))
def R(i): return [i['x'],i['y'],i['w'],i['h']]
def ov(a,b):
    return not(a[0]+a[2]<=b[0] or b[0]+b[2]<=a[0] or a[1]+a[3]<=b[1] or b[1]+b[3]<=a[1])
def pair_rule(lr,pr):
    lx,ly,lw,lh=lr; px,py,pw,ph=pr
    if not (px<=lx+4 and px+pw>=lx+lw-4): return False
    lcy=ly+lh/2
    if not (py-0.25*lh<=lcy<=py+ph+0.25*lh): return False
    if not (0.6*lh<=ph<=3.0*lh): return False
    return True
for n,r in ((13,25.0/15.0),(5,1.0),(18,1.0)):
    sl=d['slides'][n-1]; its=sl['items']
    labels=[i for i in its if i.get('kind')=='text' and str(i.get('text','')).startswith('CHC')]
    shapes=[i for i in its if i.get('kind')=='shape']
    def isdot(i,lh): return 0<i['w']<=1.6*lh and 0<i['h']<=1.6*lh and abs(i['w']-i['h'])<=2
    pairs=[]
    for L in labels:
        lr=R(L); dots=[c for c in shapes if isdot(c,lr[3])]
        c=[x for x in shapes if not isdot(x,lr[3]) and pair_rule(lr,R(x))]
        if len(c)==1 and L['h']<60: pairs.append((L,c[0],dots))
    alldots=[c for c in shapes if isdot(c,22 if n==13 else 46)]
    def grow(P,mode,dots):
        px,py,pw,ph=P; nw,nh=pw*r,ph*r
        best=None
        for dd in dots:
            dcx,dcy=dd['x']+dd['w']/2,dd['y']+dd['h']/2
            dx=max(px-dcx,0,dcx-(px+pw)); dy=max(py-dcy,0,dcy-(py+ph))
            dist=math.hypot(dx,dy)
            if best is None or dist<best[0]: best=(dist,dcx,dcy)
        RAD=2.5*ph+30
        if mode=='centre' or best is None or best[0]>RAD:
            nx=px+(pw-nw)/2
        else:
            _,dcx,dcy=best
            if dcx<px: nx=(px+pw)-nw
            elif dcx>px+pw: nx=px
            else: nx=px+(pw-nw)/2
        ny=py+(ph-nh)/2
        return [nx,ny,nw,nh]
    for mode in ('today','centre','awaydot'):
        rects=[]
        for L,Pl,dots in pairs:
            rects.append(R(Pl) if mode=='today' else grow(R(Pl),'centre' if mode=='centre' else 'away',dots))
        pp=sum(1 for a,b in combinations(rects,2) if ov(a,b))
        pd=sum(1 for a in rects for dd in alldots if ov(a,R(dd)))
        xs=[a[0] for a in rects]+[a[0]+a[2] for a in rects]
        ys=[a[1] for a in rects]+[a[1]+a[3] for a in rects]
        print(f"slide {n} r={r:.3f} mode={mode:8s} pairs={len(pairs)} pill-pill={pp} pill-dot={pd} xspan={min(xs):.0f}..{max(xs):.0f} ({max(xs)-min(xs):.0f}) yspan={min(ys):.0f}..{max(ys):.0f}")

# label-level baseline on slide 13
sl=d['slides'][12]; its=sl['items']; r=25.0/15.0
labels=[i for i in its if i.get('kind')=='text' and str(i.get('text','')).startswith('CHC') and i['h']<60]
shapes=[i for i in its if i.get('kind')=='shape']
def isdot(i): return 0<i['w']<=35 and 0<i['h']<=35 and abs(i['w']-i['h'])<=2
dots=[c for c in shapes if isdot(c)]
pairs=[]
for L in labels:
    lr=R(L); c=[x for x in shapes if not isdot(x) and pair_rule(lr,R(x))]
    if len(c)==1: pairs.append((L,c[0]))
today=[[L['x'],L['y'],L['w']*r,L['h']*r] for L,_ in pairs]
print("TODAY label-label overlaps:",sum(1 for a,b in combinations(today,2) if ov(a,b)),
      " label escapes pill:",sum(1 for (L,Pl),t in zip(pairs,today) if not(Pl['x']-1<=t[0] and Pl['x']+Pl['w']+1>=t[0]+t[2] and Pl['y']-1<=t[1] and Pl['y']+Pl['h']+1>=t[1]+t[3])))
for mode in ('centre','away'):
    out=[]
    for L,Pl in pairs:
        P=R(Pl); pw,ph=P[2]*r,P[3]*r
        best=None
        for dd in dots:
            dcx,dcy=dd['x']+dd['w']/2,dd['y']+dd['h']/2
            dx=max(P[0]-dcx,0,dcx-(P[0]+P[2])); dy=max(P[1]-dcy,0,dcy-(P[1]+P[3]))
            dist=math.hypot(dx,dy)
            if best is None or dist<best[0]: best=(dist,dcx,dcy)
        if mode=='centre' or best[0]>2.5*P[3]+30: nx=P[0]+(P[2]-pw)/2
        elif best[1]<P[0]: nx=P[0]+P[2]-pw
        elif best[1]>P[0]+P[2]: nx=P[0]
        else: nx=P[0]+(P[2]-pw)/2
        ny=P[1]+(P[3]-ph)/2
        out.append([nx+(L['x']-P[0])*r, ny+(L['y']-P[1])*r, L['w']*r, L['h']*r])
    print(mode,"label-label overlaps:",sum(1 for a,b in combinations(out,2) if ov(a,b)))
