"""Warm the inspect cache for the Wall/CG gold pairs.

Keynote is single-instance and each of these decks is 1-7 GB, so they are read
one at a time rather than in parallel. Results land in output/.cache/inspect,
keyed by deck digest, so later scoring runs are offline.

    .venv/bin/python scripts/inspect_gold.py [--previews] [--template-only]

`--template-only` re-reads just Base_CG_Assets.key, which is what you need after
editing the template, since that is the only deck whose digest changed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from obed_edom.inspect import inspect_keynote
from obed_edom.paths import find_repo_root

GOLD_DIR = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")

# The recipe is learned from this, so it is read first: editing it (resizing the
# map to leave gutters, say) changes the deck digest and invalidates its cache.
TEMPLATE = "Base_CG_Assets.key"

# (wall, cg) pairs, smallest first so failures surface early.
PAIRS = [
    ("Map_Extracted_Wall_1st.key", "Map_Extracted_CG_1st.key"),
    ("Map_Extracted_Wall_2nd.key", "Map_Extracted_CG_2nd.key"),
    ("Full_Report_Card_Wall.key", "Full_Report_Card_CG.key"),
]


def warm(path: Path, *, previews: bool) -> None:
    export_dir = None
    if previews:
        from obed_edom.baseline import cache_root  # noqa: PLC0415

        export_dir = cache_root() / "goldpreviews" / path.stem
    started = time.perf_counter()
    try:
        payload = inspect_keynote(path, export_dir=export_dir, use_cache=True)
    except Exception as exc:  # noqa: BLE001 - one bad deck must not stop the rest
        print(f"FAIL  {path.name}: {exc}", flush=True)
        return
    elapsed = time.perf_counter() - started
    items = sum(len(s.get("items") or []) for s in payload.get("slides") or [])
    dupes = sum(
        1
        for s in payload.get("slides") or []
        for it in s.get("items") or []
        if it.get("duplicateOf")
    )
    print(
        f"OK    {path.name}: {payload.get('slideCount')} slides "
        f"{payload.get('slideWidth'):.0f}x{payload.get('slideHeight'):.0f}, "
        f"{items} items ({dupes} dup), cached={payload.get('_cached')}, {elapsed:.1f}s",
        flush=True,
    )


def main(argv: list[str]) -> int:
    previews = "--previews" in argv
    template = GOLD_DIR / TEMPLATE
    if template.exists():
        warm(template, previews=previews)
    else:
        print(f"SKIP  {TEMPLATE}: not found", flush=True)
    if "--template-only" in argv:
        return 0
    for wall, cg in PAIRS:
        for name in (wall, cg):
            path = GOLD_DIR / name
            if not path.exists():
                print(f"SKIP  {name}: not found", flush=True)
                continue
            warm(path, previews=previews)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
