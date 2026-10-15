from pathlib import Path
import ast, hashlib, json, math, collections
OUT = Path(__file__).resolve().parent
REPO = Path('/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808')
CORPUS = Path('/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures')
TEX = OUT.parent.parent / 'tex'
MM = 'apple:magic-move-implied-motion-path'
EB = {MM, 'apple:ca-text-shimmer', 'apple:ca-text-sparkle'}
def sha(b): return hashlib.sha256(b).hexdigest()
def signature(n):
    if isinstance(n, dict): return {k:signature(v) for k,v in n.items() if k not in ('texture','toTexture','objectID')}
    if isinstance(n, list): return [signature(v) for v in n]
    return n
def fp(n): return sha(json.dumps(signature(n), sort_keys=True, separators=(',', ':')).encode())
def effects(n,path=''):
    if isinstance(n,dict):
        if n.get('name') in EB and n.get('type')=='transition' and 'baseLayer' in n: yield path,n
        for k,v in n.items(): yield from effects(v,path+'/'+k)
    elif isinstance(n,list):
        for i,v in enumerate(n): yield from effects(v,path+'/'+str(i))
def anims(n):
    return [a for g in n.get('animations',[]) for a in ([g] if g.get('property') else g.get('animations',[]))]
def node_op(n):
    st=n['initialState'];aa=anims(n);oo=[a for a in aa if a.get('property')=='opacity']
    if st.get('hidden') or len(oo)>1 or any(a.get('property')=='hidden' or 'animations' in a for a in aa):return None
    if oo:
        a=oo[0]
        if a['from']['scalar']!=a['to']['scalar'] or a.get('fillMode')!='both':return None
        v=a['to']['scalar']
    else:v=st['opacity']
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None

def leaves(n,path='',chain=(),xy=(0,0)):
    st=n['initialState'];xy=tuple(xy[k]+round(st['position']['point'+v]-st['anchorPoint']['point'+v]*st[z],6) for k,v,z in [(0,'X','width'),(1,'Y','height')])
    if n.get('texture'):
        yield path,n,chain,list(xy)+[st['width'],st['height']]
    else:
        for i,c in enumerate(n.get('layers',[])):yield from leaves(c,path+'/layers/'+str(i),chain+(n,),xy)
def classify(effect):
    result=[]
    for ordinal,(path,n,chain,rect) in enumerate(leaves(effect['baseLayer'])):
        rawzero=any(a['initialState']['opacity']==0 for a in chain)
        values=[node_op(a) for a in chain];product=None if None in values else math.prod(values)
        aa=anims(n);props=[a.get('property') for a in aa]
        opacity_hidden_only=bool(aa) and set(props)<= {'opacity','hidden'}
        if rawzero or product==0:
            result.append(dict(ordinal=ordinal,path=path,texture=n['texture'],rect=rect,initial=n['initialState'],ancestorValues=values,ancestorProduct=product,rawZeroAncestor=rawzero,opacityHiddenOnly=opacity_hidden_only,animations=n['animations'],nodeOpacity=node_op(n),ancestors=[dict(initial=a['initialState'],animations=a.get('animations')) for a in chain]))
    return result

records={};errors=[];files=sorted(CORPUS.rglob('*.json'));parsed=0
for p in files:
    if any(x in p.parts for x in ('Extensions','chrome-profile','Default')): continue
    try:d=json.loads(p.read_bytes());parsed+=1
    except (ValueError,OSError) as e:errors.append([str(p),str(e)]);continue
    for path,e in effects(d):
        f=fp(e)
        if f not in records: records[f]=dict(fingerprint=f,name=e['name'],duration=e['duration'],leaves=sum(1 for _ in leaves(e['baseLayer'])),candidates=classify(e),sources=[])
        records[f]['sources'].append(dict(file=str(p),path=path))

players={}
for p in sorted(CORPUS.rglob('main.js')):
    if p.parent.name!='player':continue
    b=p.read_bytes();h=sha(b)
    players.setdefault(h,dict(path=str(p),size=len(b),copies=0))['copies']+=1
runtime={};exec(compile((REPO/'src/obed_edom/live_runtime.py').read_bytes(),str(REPO/'src/obed_edom/live_runtime.py'),'exec'),runtime)
stock=(TEX/'g3/raw-unrepaired/assets/player/main.js').read_bytes()
tokens=[b'class QB{',b'renderFrameWithContext(A,B,g){',b'case"opacity":if(d=R.scalar',b'var T=i.hidden?0:e.parentOpacity*i.opacity;',b'class eB{',b'var w=e.initialState.hidden?0:this.parentOpacity*e.initialState.opacity;',b'class pB extends',b'class fB{',b'setupTexture(A){',b'textureInfoFromEffect(A,B,g,C,Q){',b'animate(){var A=new Date',b'renderEffects(A){for(var B=[]',b'animateEffectWillBegin(A){',b'handleAnimateEffectDidBegin(A){',b'handleEffectDidComplete(A){',b'removeEvent(){',b'class VB{',b'class WB{',b'function s(A){setTimeout(A,100)}',b'advanceToNextBuild(A){',b'jumpToScene_partFour(A,B){',b'displayScene(A,B){',b'playCurrentScene(A){',b'currentSceneDidComplete(A){',b'case"hidden":',b',isEvalSupported:!1']
anchors={}
for h in runtime['SUPPORTED_PLAYERS']:
    p=Path(players[h]['path']);b=p.read_bytes();rows=[]
    for t in tokens:
        pos=[];at=0
        while (at:=b.find(t,at))!=-1:pos.append(at);at+=1
        rows.append(dict(token=t.decode(),offsets=pos))
    anchors[h]=dict(path=str(p),size=len(b),anchors=rows,replacements=[dict(number=i+1,offset=b.find(before),count=b.count(before)) for i,(before,_) in enumerate(runtime['_MM_OPACITY_REPLACEMENTS'])],outputPins={k:sha(v) for k,v in [('on',runtime['patch_player'](b)),('off',runtime['patch_player'](b,mm_opacity=False)),('rendering',runtime['patch_rendering'](b))]})

exports={}
for label in ['g3/raw-unrepaired','g3/real-patched','newexp3']:
    root=TEX/label;h=json.loads((root/'assets/header.json').read_bytes());slides=[]
    for sn in (2,3):
        sid=h['slideList'][sn];p=root/'assets'/sid/(sid+'.json');d=json.loads(p.read_bytes());ee=[]
        for i,e in enumerate(d['events']):
            ee.append(dict(event=i,automaticPlay=e['automaticPlay'],effects=[{k:v for k,v in ef.items() if k!='baseLayer'} for ef in e['effects']],baseLeaves=[dict(path=path,texture=n['texture'],rect=rect,ancestorValues=[node_op(a) for a in chain]) for path,n,chain,rect in leaves(e['baseLayer'])]))
        for path,e in effects(d):
            ee.append(dict(path=path,fingerprint=fp(e),candidates=classify(e)))
        slides.append(dict(number=sn+1,id=sid,file=str(p),sha256=sha(p.read_bytes()),events=ee))
    exports[label]=dict(header=h,slides=slides,playerSha256=sha((root/'assets/player/main.js').read_bytes()))

summary=dict(jsonFilesFound=len(files),jsonFilesParsed=parsed,parseErrors=errors,effects=len(records),effectNames=dict(collections.Counter(x['name'] for x in records.values())),leaves=sum(x['leaves'] for x in records.values()),rawZeroAncestorLeaves=sum(len(x['candidates']) for x in records.values()),rawZeroOpacityHiddenOnly=sum(c['rawZeroAncestor'] and c['opacityHiddenOnly'] for x in records.values() for c in x['candidates']),provenZeroOpacityHiddenOnly=sum(c['ancestorProduct']==0 and c['opacityHiddenOnly'] for x in records.values() for c in x['candidates']))
(OUT/'offline_evidence.json').write_text(json.dumps(dict(summary=summary,corpus=list(records.values()),players=players,anchors=anchors,exports=exports),indent=2)+'\n')
print(json.dumps(summary,indent=2))
for r in records.values():
    cs=[c for c in r['candidates'] if c['opacityHiddenOnly']]
    if cs:print(r['fingerprint'],len(r['sources']),r['sources'][0],[(c['ordinal'],c['ancestorProduct'],c['texture'],[(a.get('property'),a.get('from'),a.get('to'),a.get('fillMode')) for g in c['animations'] for a in g.get('animations',[])]) for c in cs])
print('exports players',[(k,v['playerSha256']) for k,v in exports.items()])
print('old patched equals current rendering', (TEX/'g3/real-patched/assets/player/main.js').read_bytes()==runtime['patch_rendering'](stock))
all_shapes=[];seen=set();header_list=sorted(CORPUS.rglob('assets/header.json'))
for p in files:
    if any(x in p.parts for x in ('Extensions','chrome-profile','Default')):continue
    try:d=json.loads(p.read_bytes())
    except (ValueError,OSError):continue
    for path,e in effects(d):
        fingerprint=fp(e)
        if fingerprint in seen:continue
        seen.add(fingerprint)
        for ordinal,(lp,n,chain,rect) in enumerate(leaves(e['baseLayer'])):
            aa=anims(n)
            if not aa or not set(a.get('property') for a in aa)<={'opacity','hidden'}:continue
            values=[node_op(a) for a in chain]
            all_shapes.append(dict(fingerprint=fingerprint,file=str(p),path=path,ordinal=ordinal,rect=rect,ancestorProduct=None if None in values else math.prod(values),initial=n['initialState'],animations=n['animations']))
summary['exportHeaders']=len(header_list)
summary['effectOccurrences']=sum(len(x['sources']) for x in records.values())
summary['opacityHiddenOnlyLeaves']=len(all_shapes)
summary['opacityHiddenAncestorProducts']=dict(collections.Counter(str(x['ancestorProduct']) for x in all_shapes))
summary['constantZeroOpacityAndHiddenTrue']=sum(any(a.get('property')=='opacity' and a.get('from',{}).get('scalar')==a.get('to',{}).get('scalar')==0 for g in x['animations'] for a in g.get('animations',[])) and any(a.get('property')=='hidden' and a.get('from',{}).get('scalar') is True and a.get('to',{}).get('scalar') is True for g in x['animations'] for a in g.get('animations',[])) for x in all_shapes)
old=(TEX/'g3/real-patched/assets/player/main.js').read_bytes()
old_rows=[]
for token,size in [(b'__obedNodeOpacity(A){',2050),(b'renderFrameWithContext(A,B,g){',2000),(b'__obedHandbackTextures(A,B){',1800),(b'animateEffectWillBegin(A){',650),(b'currentSceneDidComplete(A){',570)]:
    pos=old.find(token);old_rows.append(dict(token=token.decode(),offset=pos,snippet=old[pos:pos+size].decode()))
changes=[]
for p in sorted((TEX/'g3/raw-unrepaired/assets').glob('*/*.json')):
    q=TEX/'g3/real-patched/assets'/p.relative_to(TEX/'g3/raw-unrepaired/assets')
    if not q.exists():continue
    def diff(a,b,path=''):
        if type(a)!=type(b):changes.append(dict(file=str(p),path=path,before=a,after=b));return
        if isinstance(a,dict):
            for k in a.keys()|b.keys():
                if k not in a or k not in b:changes.append(dict(file=str(p),path=path+'/'+k,before=a.get(k),after=b.get(k)))
                else:diff(a[k],b[k],path+'/'+k)
        elif isinstance(a,list):
            if len(a)!=len(b):changes.append(dict(file=str(p),path=path,beforeLength=len(a),afterLength=len(b)))
            else:
                for i,(x,y) in enumerate(zip(a,b)):diff(x,y,path+'/'+str(i))
        elif a!=b:changes.append(dict(file=str(p),path=path,before=a,after=b))
    diff(json.loads(p.read_bytes()),json.loads(q.read_bytes()))
source=(REPO/'src/obed_edom/live_runtime.py').read_bytes()
result=dict(summary=summary,corpus=list(records.values()),relatedLeaves=all_shapes,headers=[str(p) for p in header_list],players=players,anchors=anchors,exports=exports,immutablePatchedAnchors=old_rows,repairDiff=changes,runtimeReadSha256=sha(source))
(OUT/'offline_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
(OUT/'runtime_read_snapshot.py').write_bytes(source)
print('FINAL SUMMARY',json.dumps(summary,indent=2));print('REPAIR DIFF',json.dumps(changes));print('runtime snapshot',sha(source))
