import sys, collections, math
from obed_edom.iwa_geometry import _geom_dict,_xywha,_mask_geom,_masked_rect,compose_geometry,_is_rotated
from obed_edom.iwa_runs import _load_deck, slide_order
import obed_edom.iwa_write as iw
SL=set(range(1,130))|set(range(135,144))|set(range(145,156))
objects,id_to_file,_=_load_deck(sys.argv[1])
c=collections.Counter(); ang=collections.Counter(); rows=[]
for idx,(sid,_s) in enumerate(slide_order(objects)):
    n=idx+1
    if n not in SL or sid not in objects: continue
    for rec in compose_geometry(objects[sid],objects):
        if rec['kind'] not in ('image','movie'): continue
        o=objects[rec['id']]; mref=(o.get('mask') or {}).get('identifier')
        if mref is None: continue
        mid=str(mref); mg=_mask_geom(o,objects)
        if not mg: c['mask-unresolved']+=1; continue
        fx,fy,fw,fh,fa=_xywha(_geom_dict(o)); mx,my,mw,mh,ma=_xywha(mg)
        cross = id_to_file.get(mid)!=id_to_file.get(rec['id'])
        rot = _is_rotated(fa) or _is_rotated(ma)
        over = max(-mx, -my, mx+mw-fw, my+mh-fh) > 1e-9
        ok = iw._is_identity_mask(fw,fh,fa,mx,my,mw,mh,ma) or iw._is_axis_aligned_crop(fw,fh,fa,mx,my,mw,mh,ma)
        tag=[]
        if rot: tag.append('rotated'); ang[(round(fa,4),round(ma,4))]+=1
        if over and not rot: tag.append('overhang')
        if cross: tag.append('cross-member')
        if not tag and not ok: tag.append('other-refuse')
        c['+'.join(tag) or 'convertible']+=1
        if tag: rows.append((n,rec['kindIndex'],'+'.join(tag)))
print(sys.argv[1].split('/')[-1]); print(c)
print('rotation angle pairs',ang.most_common(12))
print('per-slide',sorted(collections.Counter(r[0] for r in rows).items(),key=lambda t:-t[1])[:15])
print('total refused',len(rows))
