"""Can template-slide selection pick the right map framing out of several?

Report pages are framed per country, so a base template would need one slide per
framing. That only works if _best_matching_slide reliably picks the framing the
human actually used for a given wall page. This tests that offline: it harvests
the distinct framings out of a finished CG deck, treats them as a candidate
template, and asks how often selection lands on the right one.

    .venv/bin/python scripts/try_multi_framing.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from obed_edom.baseline import deck_digest, inspect_cache_path
from obed_edom.map_remap import (
    _best_matching_slide,
    align_by_geometry,
    is_map_item,
    is_visible,
    primary_map_rect,
)

GOLD_DIR = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
WALL = GOLD_DIR / "Full_Report_Card_Wall.key"
CG = GOLD_DIR / "Full_Report_Card_CG.key"


def cached(path: Path) -> dict[str, Any] | None:
    blob = inspect_cache_path(deck_digest(path))
    if not blob.is_file():
        return None
    return json.loads(blob.read_text(encoding="utf-8"))


def framing(slide: dict, w: float, h: float):
    vis = [
        it
        for it in slide.get("items") or []
        if not it.get("duplicateOf") and is_visible(it, w, h) and is_map_item(it)
    ]
    if not vis:
        return None
    return primary_map_rect(vis)


def key(rect) -> tuple[int, int, int, int] | None:
    if rect is None:
        return None
    return (round(rect.x / 20) * 20, round(rect.y / 20) * 20, round(rect.w / 20) * 20, round(rect.h / 20) * 20)


def main() -> int:
    wall = cached(WALL)
    gold = cached(CG)
    # Editing either deck changes its digest, so say which one needs re-reading
    # rather than dying on a missing path.
    for name, payload in (("wall", wall), ("CG", gold)):
        if payload is None:
            source = WALL if name == "wall" else CG
            print(f"No cached inspect for the {name} deck ({source.name}).")
            print("Warm it with scripts/inspect_gold.py, or re-inspect it if you have edited it.")
            return 1
    assert wall is not None and gold is not None
    ww, wh = float(wall["slideWidth"]), float(wall["slideHeight"])
    gw, gh = float(gold["slideWidth"]), float(gold["slideHeight"])
    gold_by = {int(s.get("number") or 0): s for s in gold["slides"]}
    wall_by = {int(s.get("number") or 0): s for s in wall["slides"]}

    # One representative CG slide per distinct framing: the candidate template.
    representatives: dict[tuple[int, int, int, int], dict] = {}
    for s in gold["slides"]:
        if s.get("skipped"):
            continue
        k = key(framing(s, gw, gh))
        if k and k not in representatives:
            representatives[k] = s
    template_slides = list(representatives.values())
    print(f"harvested {len(template_slides)} distinct framings as template slides:")
    for k in representatives:
        print(f"   x={k[0]:5d} y={k[1]:5d} {k[2]:5d}x{k[3]:4d}")

    pairs = align_by_geometry(wall["slides"], gold["slides"])
    checked = right = 0
    misses: list[str] = []
    for wnum, gnum in sorted(pairs.items()):
        w_slide, g_slide = wall_by[wnum], gold_by[gnum]
        want = key(framing(g_slide, gw, gh))
        if want is None or framing(w_slide, ww, wh) is None:
            continue
        picked = _best_matching_slide(w_slide, template_slides)
        got = key(framing(picked, gw, gh)) if picked else None
        checked += 1
        if got == want:
            right += 1
        elif len(misses) < 10:
            misses.append(f"   wall {wnum:3d} -> gold {gnum:3d}: wanted {want}, picked {got}")

    print(f"\nselection picked the human's framing on {right}/{checked} pages", end="")
    if checked:
        print(f" ({right / checked:.0%})")
    else:
        print()
    if misses:
        print("misses:")
        for line in misses:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
