#!/usr/bin/env python3
"""Read-only Keynote export census. All reports are confined to this script's OUT directory."""
import collections
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
FIXTURES = Path('/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures')
CONTINUITY = Path('/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def walk(value, pointer=''):
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            yield from walk(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from walk(child, pointer + '/' + str(i))


def layers(layer, path='root'):
    if not isinstance(layer, dict):
        return []
    result = [{'path': path, 'texture': layer.get('texture'),
               'objectID': layer.get('objectID'), 'initialState': layer.get('initialState'),
               'isVideoLayer': layer.get('isVideoLayer'),
               'isWebVideoPosterLayer': layer.get('isWebVideoPosterLayer'),
               'animations': layer.get('animations', [])}]
    for i, child in enumerate(layer.get('layers', [])):
        result.extend(layers(child, path + '/' + str(i)))
    return result


def shape(layer):
    if not isinstance(layer, dict):
        return '-'
    flags = ('T' if layer.get('texture') else 'N') + ('V' if layer.get('isVideoLayer') else '')
    props = sorted({node.get('property', 'group') for _, node in walk(layer.get('animations', []))
                    if 'duration' in node or 'property' in node})
    suffix = '{' + ','.join(props) + '}' if props else ''
    children = layer.get('layers', [])
    return flags + suffix + ('[' + ','.join(shape(c) for c in children) + ']' if children else '')


def main():
    candidates = [('fixtures', p.parent.parent) for p in FIXTURES.rglob('assets/header.json')]
    if CONTINUITY.exists():
        for root in CONTINUITY.glob('*-html'):
            candidates.extend(('continuity', p.parent.parent) for p in root.rglob('assets/header.json'))
    roots = sorted(set(candidates), key=lambda item: (item[0], str(item[1])))
    rows, exports, errors = [], [], []
    for source, root in roots:
        header_path = root / 'assets/header.json'
        try:
            header_bytes = header_path.read_bytes()
            header = json.loads(header_bytes)
            player_path = root / 'assets/player/main.js'
            player_sha = digest(player_path.read_bytes()) if player_path.exists() else None
            slide_list = header['slideList']
            files = sorted((root / 'assets').glob('*/*.json'))
            listed_files = {root / 'assets' / sid / (sid + '.json') for sid in slide_list}
            missing = sorted(str(f) for f in listed_files if not f.exists())
            if missing:
                errors.append({'root': str(root), 'missingSlides': missing})
            begin = len(rows)
            for path in files:
                data = path.read_bytes()
                doc = json.loads(data)
                if 'events' not in doc:
                    continue
                sid = path.stem
                slide = slide_list.index(sid) + 1 if sid in slide_list else None
                for pointer, effect in walk(doc):
                    if 'name' not in effect or effect.get('type') not in ('transition', 'buildIn', 'buildOut', 'actionBuild', 'smartBuild'):
                        continue
                    layer_rows = layers(effect.get('baseLayer'))
                    animations = [node for layer in layer_rows for _, node in walk(layer['animations'])
                                  if 'property' in node or 'duration' in node]
                    row = {'source': source, 'root': str(root), 'deck': header.get('filename'),
                           'slide': slide, 'slideID': sid, 'json': str(path), 'jsonSha256': digest(data),
                           'pointer': pointer, 'type': effect['type'], 'name': effect['name'],
                           'beginTime': effect.get('beginTime'), 'duration': effect.get('duration'),
                           'attributes': effect.get('attributes'), 'objectID': effect.get('objectID'),
                           'shape': shape(effect.get('baseLayer')), 'layers': layer_rows,
                           'animationDurations': sorted({compact(a.get('duration')) for a in animations}),
                           'timingFunctions': sorted({compact(a.get('timingFunction', '<absent>')) for a in animations}
                                                     | {compact(t) for a in animations for t in a.get('timingFunctions', [])}),
                           'fillModes': sorted({compact(a.get('fillMode', '<absent>')) for a in animations}),
                           'properties': sorted({a['property'] for a in animations if 'property' in a})}
                    rows.append(row)
            exports.append({'source': source, 'root': str(root), 'deck': header.get('filename'),
                            'slideCount': len(slide_list), 'headerSha256': digest(header_bytes),
                            'playerSha256': player_sha, 'effectCount': len(rows)-begin,
                            'unlistedSlideFiles': [str(f) for f in files if f not in listed_files]})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'root': str(root), 'error': str(exc)})
    result = {'roots': exports, 'effects': rows, 'errors': errors,
              'method': 'Each physical JSON effect occurrence once, including nested effects and hyperlinks; JSONP not counted. No deduplication of copied decks.'}
    (OUT / 'census_f2.json').write_text(json.dumps(result, indent=2) + '\n')
    by_name = collections.Counter((r['source'], r['type'], r['name']) for r in rows)
    text = ['# Census run', '', '| Source | Type | Effect | Count |', '|---|---|---|---:|']
    for (src, typ, name), count in sorted(by_name.items()):
        text.append(f'| {src} | {typ} | `{name}` | {count} |')
    text += ['', '| Source | Export root (relative to source) | Transitions | Other effects |', '|---|---|---:|---:|']
    for export in exports:
        selected = [r for r in rows if r['root'] == export['root']]
        transitions = sum(r['type'] == 'transition' for r in selected)
        base = FIXTURES if export['source'] == 'fixtures' else CONTINUITY
        text.append(f"| {export['source']} | `{Path(export['root']).relative_to(base)}` | {transitions} | {len(selected)-transitions} |")
    text += ['', f'Export roots: {len(exports)}; effect occurrences: {len(rows)}; read/schema errors: {len(errors)}.', '',
             'N = untextured layer; T = textured layer; V = video flag; braces = animation properties (group included); brackets = children in order.', '',
             'Full source paths, SHA-256, JSON pointers, attributes, initial states and animation trees: `census_f2.json`.',
             'One occurrence per row, with shape/timing: `census_f2_rows.tsv`. Missing timing is recorded as `<absent>`, not inferred.', '']
    (OUT / 'census_f2_tables.md').write_text('\n'.join(text))
    columns = ['source','root','deck','slide','slideID','pointer','type','name','duration','shape','animationDurations','timingFunctions','fillModes','properties']
    with (OUT / 'census_f2_rows.tsv').open('w') as out:
        out.write('\t'.join(columns)+'\n')
        for r in rows:
            out.write('\t'.join(compact(r[key]) for key in columns)+'\n')
    variants = collections.defaultdict(list)
    for r in rows:
        key = (r['type'],r['name'],r['shape'],compact(r['duration']),compact(r['animationDurations']),compact(r['timingFunctions']),compact(r['fillModes']))
        variants[key].append(r)
    table=['# Shape and timing variants', '', '| Type / name | Count | Shape | Effect duration (s) | Animation durations (s) | Timing functions | fillMode | First source anchor |', '|---|---:|---|---|---|---|---|---|']
    for key, occurrences in sorted(variants.items()):
        r=occurrences[0]
        table.append('| '+ ' | '.join([f'`{key[0]} / {key[1]}`', str(len(occurrences)), f'`{key[2]}`', *[f'`{v}`' for v in key[3:]], f"`{r['json']}#{r['pointer']}`"])+ ' |')
    (OUT / 'census_f2_shapes.md').write_text('\n'.join(table)+'\n')
    print('\n'.join(text[:text.index('| Source | Export root (relative to source) | Transitions | Other effects |')]))
    print(f'Roots={len(exports)}, effects={len(rows)}, errors={len(errors)}, variants={len(variants)}')
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
