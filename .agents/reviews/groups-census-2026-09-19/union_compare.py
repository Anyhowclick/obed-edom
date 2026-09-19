import sys, json, collections
from obed_edom.iwa_geometry import (_geom_dict,_xywha,_autosize_rect,_leaf_bbox,_is_real_box,
    _group_union,_is_rotated,compose_geometry,_corners_aabb,_frame_transform)
from obed_edom.iwa_runs import _load_deck, slide_order
SLIDES=set(range(1,130))|set(range(135,144))|set(range(145,156))

def union2(gid,ox,oy,objects,seen,include_auto):
    if gid in seen: return None
    seen.add(gid); g=objects.get(gid)
    if not g: return None
    boxes=[]
    for ref in g.get('children') or []:
        cid=ref.get('identifier')
        if cid is None: continue
        c=objects.get(str(cid))
        if not c: continue
        if c.get('_pbtype')=='TSD.GroupArchive':
            cx,cy,_,_,_=_xywha(_geom_dict(c))
            s=union2(str(cid),ox+cx,oy+cy,objects,seen,include_auto)
            if s and _is_real_box(s): boxes.append(s)
            continue
        geom=_geom_dict(c); x,y,w,h,a=_xywha(geom)
        if include_auto and c.get('_pbtype')=='TSWP.ShapeInfoArchive' and (w==0.0 or h==0.0) and c.get('isTextBox'):
            ax,ay,aw,ah=_autosize_rect(c,geom,objects)
            if aw>0 and ah>0:
                boxes.append((ax+ox,ay+oy,ax+ox+aw,ay+oy+ah)); continue
        b=_leaf_bbox(c,ox,oy,objects)
        if _is_real_box(b): boxes.append(b)
    if not boxes: return None
    return (min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))

objects,_i,_f=_load_deck(sys.argv[1])
rows=[]
for idx,(sid,_sk) in enumerate(slide_order(objects)):
    n=idx+1
    if n not in SLIDES or sid not in objects: continue
    for rec in compose_geometry(objects[sid],objects):
        if rec['kind']!='group' or rec.get('needs_keynote')!='group-residual': continue
        o=objects[rec['id']]; gx,gy,gw,gh,_a=_xywha(_geom_dict(o))
        u0=_group_union(rec['id'],gx,gy,objects,set())
        u1=union2(rec['id'],gx,gy,objects,set(),True)
        def box(u): return None if not u else [round(u[0],2),round(u[1],2),round(u[2]-u[0],2),round(u[3]-u[1],2)]
        rows.append({'slide':n,'ki':rec['ki'] if 'ki' in rec else rec['kindIndex'],'stored':[round(v,2) for v in (gx,gy,gw,gh)],
                     'u_real':box(u0),'u_auto':box(u1)})
def d(a,b): return None if not (a and b) else round(max(abs(p-q) for p,q in zip(a,b)),2)
print('n',len(rows))
dr=[d(r['stored'],r['u_real']) for r in rows]
da=[d(r['stored'],r['u_auto']) for r in rows]
du=[d(r['u_real'],r['u_auto']) for r in rows]
import statistics
for name,v in (('stored vs union_real',dr),('stored vs union_auto',da),('union_real vs union_auto',du)):
    v=[x for x in v if x is not None]
    print(name,'n',len(v),'max',max(v),'median',statistics.median(v),'<=0.5px',sum(1 for x in v if x<=0.5),'<=2px',sum(1 for x in v if x<=2))
json.dump(rows,open('/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-friendly-sammet-32dab4/210c2283-b223-4ac7-84f6-63a949c7ee38/scratchpad/union_compare.json','w'))
for r in rows[:8]: print(r)
