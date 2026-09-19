import sys, collections
from obed_edom.iwa_geometry import _geom_dict,_xywha,_mask_geom,compose_geometry,_is_rotated
from obed_edom.iwa_runs import _load_deck, slide_order
SL=set(range(1,130))|set(range(135,144))|set(range(145,156))
objects,_i,_=_load_deck(sys.argv[1]); vals=[]
for idx,(sid,_s) in enumerate(slide_order(objects)):
    n=idx+1
    if n not in SL or sid not in objects: continue
    for rec in compose_geometry(objects[sid],objects):
        if rec['kind'] not in ('image','movie'): continue
        o=objects[rec['id']]; mg=_mask_geom(o,objects)
        if not mg: continue
        fx,fy,fw,fh,fa=_xywha(_geom_dict(o)); mx,my,mw,mh,ma=_xywha(mg)
        if _is_rotated(fa) or _is_rotated(ma): continue
        over=max(-mx,-my,mx+mw-fw,my+mh-fh)
        if over>1e-9: vals.append((round(over,3),round(over/max(fw,fh),4),n,rec['kindIndex']))
vals.sort(reverse=True)
print('overhang n',len(vals))
print('worst',vals[:8]); print('median px',vals[len(vals)//2] if vals else None)
print('<=0.01px',sum(1 for v in vals if v[0]<=0.01),'<=0.5px',sum(1 for v in vals if v[0]<=0.5),'<=2px',sum(1 for v in vals if v[0]<=2),'>10px',sum(1 for v in vals if v[0]>10))
