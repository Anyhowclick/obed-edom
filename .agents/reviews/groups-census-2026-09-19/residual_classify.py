import json,collections
p='/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-friendly-sammet-32dab4/210c2283-b223-4ac7-84f6-63a949c7ee38/scratchpad/census_wall.json'
d=json.load(open(p))
res=[x for x in d['groups'] if x['needs']=='group-residual']
def cls(x):
    tb=[z for z in x['zero_extent_text'] if z['isTextBox']]
    nt=[z for z in x['zero_extent_text'] if not z['isTextBox']]
    if x['off_axis_mask']: return 'off-axis-mask'
    if nt and tb: return 'text+zeroshape'
    if nt: return 'zeroshape-only'
    if tb: return 'textbox-only'
    return '?'
c=collections.Counter(cls(x) for x in res)
print(c)
for k in ('zeroshape-only','text+zeroshape','off-axis-mask'):
    for x in res:
        if cls(x)==k: print(k,'slide',x['slide'],'ki',x['ki'],'nchild',x['n_children'],'depth',x['depth'],'kinds',x['child_kinds'], [ (z['w'],z['h'],z['nw'],z['nh']) for z in x['zero_extent_text'] if not z['isTextBox']][:3], x['off_axis_mask'][:2])
# per-slide for textbox-only
print('textbox-only per slide', sorted(collections.Counter(x['slide'] for x in res if cls(x)=='textbox-only').items()))
