import sys, zipfile, json
sys.path.insert(0, sys.argv[1])
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_builds import deck_builds
from obed_edom.offline_inspect import _build_data_index, _data_identifier
from obed_edom.iwa_kindindex import _geometry, _owned_text, _memberships

P = sys.argv[2]
objs, _, _ = _load_deck(P); order = slide_order(objs); d = deck_builds(P, deck=(objs, _, _))
with zipfile.ZipFile(P) as zf: files = _build_data_index(zf.namelist())
TRANS = {6, 34, 86, 103, 121}
SEL = {5: 'all', 7: 'all', 87: 'movie', 101: {0, 1, 2, 5, 8, 11}, 103: 'movie', 104: 'movie', 122: {0, 1, 2}, 124: {1, 6}, 57: {1}}
SLIDES = [5, 6, 7, 34, 35, 86, 87, 101, 103, 104, 121, 122, 124, 57]
FX = ('apple:wipe-iris', 'com.apple.iWork.Keynote.KLNSparkle', 'com.apple.iWork.Keynote.BUKAnvil', 'apple:movie-start')

def ref(o, k):
    r = (o or {}).get(k); return str(r['identifier']) if isinstance(r, dict) and 'identifier' in r else None

def opacity(o):
    sid = ref(o, 'style') or ref(o.get('super') or {}, 'style') or ref((o.get('super') or {}).get('super') or {}, 'style')
    for _ in range(10):
        st = objs.get(sid) if sid else None
        if not st: return 1.0
        for holder in (st, st.get('super') or {}):
            for pk in ('mediaProperties', 'shapeProperties'):
                v = (holder.get(pk) or {}).get('opacity')
                if v is not None: return round(float(v), 3)
        sup = st.get('super') or {}
        sid = ref(sup, 'parent') or ref(sup.get('super') or {}, 'parent')
    return 1.0

def kind(o):
    t = o.get('_pbtype')
    return {'TSD.ImageArchive': 'image', 'TSD.MovieArchive': 'movie', 'TSD.GroupArchive': 'group'}.get(t) or '/'.join(_memberships(o)) or t

def desc(oid, depth=0):
    o = objs[oid]; k = kind(o)
    if k in ('image', 'movie'):
        did = _data_identifier(o); s = files.get(did, '?')
    elif k == 'group':
        s = 'group[' + '; '.join(desc(ref({'x': c}, 'x'), depth + 1) for c in (o.get('children') or [])[:6]) + (' …' if len(o.get('children') or []) > 6 else '') + ']'
        return s
    else:
        s = '"' + _owned_text(o, objs).strip().replace('\n', ' / ')[:40] + '"' if _owned_text(o, objs).strip() else '(no text)'
    extra = []
    op = opacity(o)
    if op != 1.0: extra.append(f'opacity {op}')
    if ref(o, 'mask'): extra.append('masked/cropped')
    return f"{k} {s}" + (f" ({', '.join(extra)})" if extra else '')

from collections import Counter
out = ["# Increment-1 artwork appendix — Full_Report_Card_Wall.key (coordinator, offline IWA read, 2026-10-14)\n",
       "Front-to-back order per slide (1 = frontmost). Overlaps are computed from wall-canvas frames (7680×1080 points). Status: SELECTED = build target in the sheet; STATIC = keep as built/static art; NEVER-BUILT = no build on the wall slide, keep; OMIT = only dropped builds target it, leave out (build slides only). Opacity shown only when ≠ 1; group opacity is the group archive's own (none observed unless shown).\n"]
for n in SLIDES:
    sid, _skip = order[n - 1]; s = objs[sid]
    by_target = {}
    for b in d[n]['builds']:
        did = ref(objs.get(b['buildId']) or {}, 'drawable')
        by_target.setdefault(did, []).append(b)
    zo = [str(r['identifier']) for r in s.get('drawablesZOrder', [])][::-1]
    rows = []; geoms = {}
    for i, oid in enumerate(zo, 1):
        o = objs.get(oid)
        if not o: continue
        bs = by_target.get(oid, [])
        sel = SEL.get(n)
        def is_sel(b):
            if sel == 'all': return b['effect'] in FX
            if sel == 'movie': return b['effect'] == 'apple:movie-start'
            if isinstance(sel, set): return b['effect'] in FX and b['chunkOrder'] and b['chunkOrder'][0] in sel
            return False
        if any(is_sel(b) for b in bs):
            st = 'SELECTED ' + ', '.join(f"{b['effect'].split('.')[-1]} [#{b['chunkOrder'][0] if b['chunkOrder'] else '?'}]" for b in bs if is_sel(b))
        elif not bs: st = 'NEVER-BUILT'
        elif n in TRANS: st = 'STATIC (dropped: ' + ', '.join(sorted({b['effect'].split(':')[-1].split('.')[-1] for b in bs})) + ')'
        else: st = 'OMIT (only dropped builds)'
        x, y, w, h = _geometry(o)
        if x is not None and not st.startswith('OMIT'): geoms[i] = (x, y, x + w, y + h, st.startswith('SELECTED') or kind(o) == 'movie')
        rows.append((i, desc(oid), st, x, y, w, h))
    kept = [r for r in rows if not r[2].startswith('OMIT')]
    om = len(rows) - len(kept)
    out.append(f"## Wall slide {n} — keep {len(kept)} objects" + (f", leave out {om}" if om else ''))
    name = {r[0]: r[1] for r in rows}
    keyrows = [r for r in kept if r[2].startswith('SELECTED') or r[1].startswith('movie')]
    other = [r for r in kept if r not in keyrows]
    if len(kept) <= 20:
        for i, ds, st, *_ in kept: out.append(f"{i}. {ds} — {st}")
    else:
        for i, ds, st, *_ in keyrows: out.append(f"{i}. {ds} — {st}")
        tx = [ds for _, ds, st, *_ in other if ds.startswith('text ')]
        c = Counter((ds, 'STATIC' if st.startswith('STATIC') else st) for _, ds, st, *_ in other if not (len(tx) > 8 and ds.startswith('text ')))
        if len(tx) > 8: c[(f"text labels (e.g. {', '.join(t[5:] for t in tx[:3])})", 'mixed' if any(st.startswith('STATIC') for _, ds, st, *_ in other if ds.startswith('text ')) else 'NEVER-BUILT')] = len(tx)
        out.append("- Other kept objects (front-to-back numbers span " + f"{min(r[0] for r in other)}–{max(r[0] for r in other)}" + "): " + '; '.join(f"{v}× {k[0]} [{k[1]}]" for k, v in c.most_common()))
    def names(js):
        c = Counter(name[j] for j in js); return ', '.join(f"{v}× {k}" if v > 1 else k for k, v in c.most_common()) or 'nothing'
    for i, (a0, a1, a2, a3, key) in geoms.items():
        if not key: continue
        fr = [j for j, (b0, b1, b2, b3, _) in geoms.items() if j < i and a0 < b2 and b0 < a2 and a1 < b3 and b1 < a3]
        bh = [j for j, (b0, b1, b2, b3, _) in geoms.items() if j > i and a0 < b2 and b0 < a2 and a1 < b3 and b1 < a3]
        out.append(f"- #{i} {name[i]}: in front of it: {names(fr)}. Behind it: {names(bh)}.")
    out.append('')
out.append("Notes: text-box frames are stored with height 0 (autosize), so text overlaps are not detected — place text as on the wall slide. Objects at opacity 0 are invisible on the wall slide; copying them is harmless. 'masked/cropped' = the object has a mask in Keynote; copy-paste keeps it. Wall canvas is 7680×1080 points; most foreground sits in the centre band x 1920–5760 (3840×1080), and the map BG images span the full 7680 width (masked).")
print('\n'.join(out))
