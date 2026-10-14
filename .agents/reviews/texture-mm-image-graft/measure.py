import sys,json,hashlib,collections
from pathlib import Path
sys.dont_write_bytecode=True
REPO=Path('/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808')
sys.path.insert(0,str(REPO/'src'))
from obed_edom import preview_textures as pt
from obed_edom.iwa_runs import slide_order
from obed_edom.iwa_kindindex import derive_kind_index
OUT=Path(__file__).parent
objects=json.loads((OUT/'f2-iwa.json').read_text())
order=slide_order(objects)
fixtures=Path('/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures')
roots=[Path('/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html')]
roots += sorted(p.parent.parent for p in fixtures.rglob('header.json') if p.parent.name=='assets' and (p.parent.parent.name.startswith('html-unmodified') or p.parent.parent.name=='html'))
def rect(a):
 r=a['targetRectangle'];return tuple(r[k] for k in ('x','y','width','height'))
def tight(l,a):
 x,y,w,h=l;X,Y,W,H=a
 return all(-.001<=v<=4.001 for v in (X-x,Y-y,x+w-X-W,y+h-Y-H))
def contains(l,a):
 x,y,w,h=l;X,Y,W,H=a
 return x<=X+.001 and y<=Y+.001 and x+w>=X+W-.001 and y+h>=Y+H-.001
results=[];details=[]
for root in roots:
 header=json.loads((root/'assets/header.json').read_text());uuids=header['slideList']
 entries=[dict(originalOrdinal=i+1,playerIndex=i,exportedUuid=u) for i,u in enumerate(uuids)]
 slides=pt._load(root,entries);c=collections.Counter();samples=[]
 main=next(iter(root.rglob('main.js')),None)
 digest=hashlib.sha256(main.read_bytes()).hexdigest() if main else None
 for i,s in enumerate(slides):
  recs=derive_kind_index(objects[order[i][0]],objects) if root==roots[0] else []
  allrecs=[r for r in recs if all(r[k] is not None for k in ('x','y','w','h'))]
  c['slides']+=1;c['events']+=len(s.events)
  for ev,event in enumerate(s.events):
   acc=[a for a in event.get('accessibility',[]) if 'targetRectangle'in a]
   leaves=[l for l in s.leaves if l.is_base and l.event==ev]
   images=[l for l in leaves if l.kind==5 and pt._movie_of(s,l) is None]
   c['access_entries']+=len(acc);c['base_leaves']+=len(leaves);c['image_leaves']+=len(images)
   if ev==0:c['ev0_image_leaves']+=len(images)
   for ai,a in enumerate(acc):
    aa=rect(a); matches=[l for l in leaves if tight(l.rect,aa)]
    c['acc_tight_'+str(min(len(matches),2))]+=1
    full=[l for l in leaves if contains(l.rect,aa)]
    c['acc_containment_'+str(min(len(full),2))]+=1
    if recs:
     rr=[r for r in allrecs if pt._close((r['x'],r['y'],r['w'],r['h']),aa,.001)]
     c['acc_iwa_'+str(min(len(rr),2))]+=1
   for l in images:
    matches=[(ai,a) for ai,a in enumerate(acc) if tight(l.rect,rect(a))]
    c['image_tight_'+str(min(len(matches),2))]+=1
    mutual=len(matches)==1 and sum(tight(q.rect,rect(matches[0][1])) for q in leaves)==1
    c['image_mutual']+=mutual
    state=l.node['initialState']
    c['image_hidden']+=bool(state.get('hidden'));c['image_opacity0']+=state.get('opacity')==0
    if recs:
     rr=[r for r in allrecs if len(matches)==1 and pt._close((r['x'],r['y'],r['w'],r['h']),rect(matches[0][1]),.001)]
     resolved=mutual and len(rr)==1 and rr[0]['kind']=='image'
     c['image_iwa_resolved']+=resolved
     if ev==0:c['ev0_image_iwa_resolved']+=resolved
     row=dict(slide=i+1,event=ev,path=l.key,rect=l.rect,texture=l.texture,access=[a for _,a in matches],iwa=rr,resolved=resolved)
     details.append(row)
    if not mutual and len(samples)<5:samples.append(dict(slide=i+1,event=ev,path=l.key,rect=l.rect,matches=matches))
  if i>0:
   c['mm_contents_landings']+=len(pt._landings(slides[i-1],s))
 c['json_hits']=len(pt._json_hits(slides))
 result=dict(root=str(root),digest=digest,counts=dict(c),samples=samples)
 results.append(result)
 print(root.name,str(root.relative_to(fixtures)) if root!=roots[0] else 'F2',digest[:8] if digest else '-',dict(c))
(OUT/'corpus-measurements.json').write_text(json.dumps(results,indent=2))
(OUT/'f2-leaf-identities.json').write_text(json.dumps(details,indent=2))
