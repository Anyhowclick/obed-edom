#!/usr/bin/env python3
"""A/B byte-identity + timing check for bulk-read inspect.

Runs `inspect_keynote` on the SAME deck twice — once with OBED_BULK_READ=1 (bulk) and
once with =0 (legacy per-object) — with the cache bypassed so both actually hit Keynote,
then diffs the two payloads object-by-object. The bulk path is only safe if the payload is
byte-identical to the legacy one; the one thing unit tests can't prove is that Keynote's
whole-collection reads (esp. nested objectText.size/font/color) come back in collection
order. A clean diff here is that proof.

    .venv/bin/python scripts/bulk_read_ab.py "<deck.key>" [--slides 1,3,8]

Pick a deck/slide with several text items AND text-bearing shapes at DIFFERING
size/font/color, plus an image, a file-less image, lines, and a group — that exercises the
nested reads and the drift guard. Zero diff + bulk faster (or equal) = ship it.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

VOLATILE = {"_timing", "_cached", "_digest"}


def _inspect(deck: Path, slide_range, bulk: bool):
    os.environ["OBED_BULK_READ"] = "1" if bulk else "0"
    from obed_edom.inspect import inspect_keynote  # imported after env is set

    t = time.perf_counter()
    payload = inspect_keynote(deck, slide_range=slide_range, use_cache=False)
    return payload, time.perf_counter() - t


def _items_by_slide(payload: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for s in payload.get("slides") or []:
        n = int(s.get("number") or (int(s.get("index") or 0) + 1))
        out[n] = list(s.get("items") or [])
    return out


def _diff(a: dict, b: dict, path: str, diffs: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in dict.fromkeys(list(a) + list(b)):
            if k in VOLATILE:
                continue
            if k not in a:
                diffs.append(f"{path}.{k}: only in BULK={b[k]!r}")
            elif k not in b:
                diffs.append(f"{path}.{k}: only in LEGACY={a[k]!r}")
            else:
                _diff(a[k], b[k], f"{path}.{k}", diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: list len BULK={len(b)} LEGACY={len(a)}")
        for i in range(min(len(a), len(b))):
            _diff(a[i], b[i], f"{path}[{i}]", diffs)
    elif a != b:
        diffs.append(f"{path}: LEGACY={a!r} != BULK={b!r}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck")
    ap.add_argument("--slides", default=None, help="e.g. 1,3,8 (ranged read bypasses cache)")
    args = ap.parse_args(argv)
    deck = Path(args.deck).expanduser()
    sr = None
    if args.slides:
        sr = frozenset(int(x) for x in args.slides.replace(" ", "").split(","))

    print("legacy (OBED_BULK_READ=0) …", flush=True)
    legacy, t_legacy = _inspect(deck, sr, bulk=False)
    print(f"  {t_legacy:.1f}s", flush=True)
    print("bulk   (OBED_BULK_READ=1) …", flush=True)
    bulk, t_bulk = _inspect(deck, sr, bulk=True)
    print(f"  {t_bulk:.1f}s", flush=True)

    la, lb = _items_by_slide(legacy), _items_by_slide(bulk)
    diffs: list[str] = []
    for n in sorted(set(la) | set(lb)):
        _diff(la.get(n, []), lb.get(n, []), f"slide{n}", diffs)

    total = sum(len(v) for v in la.values())
    print(f"\nobjects compared: {total}")
    print(f"timing: legacy {t_legacy:.1f}s  vs  bulk {t_bulk:.1f}s  "
          f"({'bulk faster by %.0f%%' % (100 * (t_legacy - t_bulk) / t_legacy) if t_legacy else 'n/a'})")
    if not diffs:
        print("\n✅ BYTE-IDENTICAL — bulk payload matches legacy exactly. Safe to trust default-ON.")
        return 0
    print(f"\n❌ {len(diffs)} DIFFERENCE(S) — do NOT trust default-ON; set OBED_BULK_READ=0. First 30:")
    for d in diffs[:30]:
        print(f"  {d}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
