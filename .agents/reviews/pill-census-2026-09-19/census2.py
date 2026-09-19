import json,math
P="/Users/anyhowclick/Desktop/work/obed-edom/.cache/inspect/dc036aea828742c1a1faa773efb72d497fcfe630f9d32c05919c1abf9678f1c6.v5.k15.3.1.json"
d=json.load(open(P))
s=d['slides'][17]
L=[i for i in s['items'] if i.get('text','').startswith('CHC Jiang Shou')][0]
print("label",L)
lx,ly,lw,lh=L['x'],L['y'],L['w'],L['h']
for c in s['items']:
    if c.get('kind')!='shape':continue
    if abs(c['x']-lx)<60 and abs(c['y']-ly)<60:
        print("near shape",c['kindIndex'],c['x'],c['y'],c['w'],c['h'],c['color'])
print("---- small-shape census across map slides")
for n in (2,5,8,13,17,18,20,21,22):
    sl=d['slides'][n-1]
    sm=[i for i in sl['items'] if i.get('kind')=='shape' and 0<i['w']<=40 and 0<i['h']<=40]
    from collections import Counter
    print(n,"small shapes",len(sm),Counter((i['w'],i['h'],i['rotation']) for i in sm).most_common(5), Counter(tuple(i['color'] or ()) for i in sm).most_common(3))
