import sys,json,zipfile
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808');sys.path.insert(0,str(R/'src'))
from obed_edom import preview_textures as pt
from obed_edom.offline_inspect import data_member_index
from pypdf import PdfReader
OUT=Path(__file__).parent
root=Path('/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html');h=json.loads((root/'assets/header.json').read_text())
s=pt._load(root,[dict(originalOrdinal=i+1,playerIndex=i,exportedUuid=u) for i,u in enumerate(h['slideList'])]);rend=pt._Renderer()
z=zipfile.ZipFile(root.with_name('F2.key'));idx=data_member_index(z.namelist())
results=[]
for did,prefix,other,native in [('44137','DF3DB700','C0C026F1',(176,205)),('44140','B37026D5','E7CF3AAD',(357,235))]:
 src=OUT/Path(idx[did]).name;src.write_bytes(z.read(idx[did]));tex=next(t for t in s[2].assets if t.startswith(prefix));othertex=next(t for t in s[2].assets if t.startswith(other))
 source=rend.thumb(src,0);donor=pt._thumb(rend,s[2],tex);wrong=pt._thumb(rend,s[3],next(t for t in s[3].assets if t.startswith('DF3DB700')))
 rows=[]
 for t,a in s[2].assets.items():
  if pt._is_pdf(a):
   c=pt._corr(source,pt._thumb(rend,s[2],t))
   if c is not None:rows.append((c,t,a['width'],a['height']))
 row=dict(dataId=did,member=idx[did],sourceMediaBox=list(PdfReader(src).pages[0].mediabox),donorTexture=tex,donorPage=s[2].page_index(tex)+1,donorSize=(s[2].assets[tex]['width'],s[2].assets[tex]['height']),donorCorr=pt._corr(source,donor),wrongCorr=pt._corr(source,wrong),top=sorted(rows,reverse=True)[:5])
 pt.THUMB=native;rr=pt._Renderer();a=rr.thumb(src,0);b=pt._thumb(rr,s[2],tex)
 row['nativeCorr']=pt._corr(a,b);row['nativeExact']=bool((a==b).all());row['nativeMeanAbsDiff']=float(abs(a-b).mean());pt.THUMB=(64,36)
 results.append(row)
print(json.dumps(results,indent=2));(OUT/'pixel-measurements.json').write_text(json.dumps(results,indent=2))
print('DETECT',[(x.slide+1,x.rule,x.leaf.key,x.detail) for x in pt._detect(s,rend)])
