"""Keynote-free byte/compose oracle for the IWA natural-size/sentinel unification.

``--dump DECK.key OUT.json`` walks ``compose_deck_geometry`` over the whole deck and
writes ``{"id#kind#kindIndex": [x, y, w, h, geom_source, needs_keynote]}`` sorted by
key, floats formatted with ``repr()`` via ``json.dumps`` (no rounding). ``--compare
BEFORE.json AFTER.json`` exits 0 iff the two dumps are identical after
``json.dumps(sort_keys=True)``, else prints up to 20 differing keys with both tuples
and exits 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _dump(deck_path: str, out_path: str) -> None:
    from obed_edom.iwa_geometry import compose_deck_geometry

    per_slide = compose_deck_geometry(deck_path)
    flat: dict[str, list] = {}
    for records in per_slide.values():
        for rec in records:
            key = f"{rec['id']}#{rec['kind']}#{rec['kindIndex']}"
            flat[key] = [rec["x"], rec["y"], rec["w"], rec["h"], rec["geom_source"], rec["needs_keynote"]]
    Path(out_path).write_text(json.dumps(flat, sort_keys=True))


def _compare(before_path: str, after_path: str) -> int:
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    if json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True):
        print("IDENTICAL")
        return 0
    keys = sorted(set(before) | set(after))
    diffs = [k for k in keys if before.get(k) != after.get(k)]
    print(f"DIFFERENT: {len(diffs)} key(s) differ")
    for k in diffs[:20]:
        print(f"  {k}: before={before.get(k)!r} after={after.get(k)!r}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dump", nargs=2, metavar=("DECK", "OUT"))
    group.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    if args.dump:
        _dump(*args.dump)
        return 0
    return _compare(*args.compare)


if __name__ == "__main__":
    sys.exit(main())
