"""Score planned remaps against the human-made CG decks.

Runs offline from the inspect cache, so heuristics can be changed and re-measured
without a Keynote round trip. Warm the cache first:

    .venv/bin/python scripts/inspect_gold.py --previews
    .venv/bin/python scripts/score_resize.py [--slides 2]

Read the per-role rows, not just the total. `predicted` far from `gold` means
content was dropped or invented, which a good RMSE on the few matched pairs will
happily hide.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from obed_edom.baseline import deck_digest, inspect_cache_path, preview_cache_dir
from obed_edom.map_remap import (
    learn_recipe,
    plan_payload_transforms,
    resolve_slides,
    score_against_gold,
    summarize_plan,
)

GOLD_DIR = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
TEMPLATE = GOLD_DIR / "Base_CG_Assets.key"
PAIRS = [
    ("Map_Extracted_Wall_1st.key", "Map_Extracted_CG_1st.key"),
    ("Map_Extracted_Wall_2nd.key", "Map_Extracted_CG_2nd.key"),
    ("Full_Report_Card_Wall.key", "Full_Report_Card_CG.key"),
]


def cached(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    blob = inspect_cache_path(deck_digest(path))
    if not blob.is_file():
        return None
    payload = json.loads(blob.read_text(encoding="utf-8"))
    payload["_previewDir"] = str(preview_cache_dir(deck_digest(path)))
    return payload


def previews_for(payload: dict[str, Any], wanted: list[int] | None) -> dict[int, Any]:
    from PIL import Image

    from obed_edom.diff_keynotes import map_preview_pngs
    from obed_edom.inspect import preview_media

    folder = Path(payload.get("_previewDir") or "")
    if not folder.is_dir():
        return {}
    images = [p for p in preview_media(folder) if p.suffix.lower() != ".mov"]
    slides = payload.get("slides") or []
    out: dict[int, Any] = {}
    for index, png in map_preview_pngs(slides, images).items():
        if index >= len(slides):
            continue
        number = int(slides[index].get("number") or index + 1)
        if wanted and number not in wanted:
            continue
        try:
            out[number] = Image.open(png).convert("RGB")
        except OSError:
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", help="Slide spec, e.g. '2' or '1-3'. Default: every slide.")
    parser.add_argument(
        "--no-previews",
        action="store_true",
        help="Score without measured text placement, to compare against the old packing.",
    )
    args = parser.parse_args(argv)

    template = cached(TEMPLATE)
    if template is None:
        print(f"No cached inspect for {TEMPLATE.name}. Run scripts/inspect_gold.py first,")
        print("or re-inspect it if you have edited the template since.")
        return 1

    slide_range = resolve_slides(spec=args.slides, range_from=None, range_to=None) if args.slides else None

    for wall_name, cg_name in PAIRS:
        wall = cached(GOLD_DIR / wall_name)
        gold = cached(GOLD_DIR / cg_name)
        print(f"\n=== {wall_name} -> {cg_name}")
        if wall is None or gold is None:
            missing = wall_name if wall is None else cg_name
            print(f"    skipped: {missing} is not cached")
            continue

        recipe = learn_recipe(wall, template)
        wanted = sorted(slide_range) if slide_range else None
        previews = {} if args.no_previews else previews_for(wall, wanted)
        placements: list[dict[str, Any]] = []
        hidden: list[int] = []
        transforms = plan_payload_transforms(
            wall,
            recipe,
            slide_range=slide_range,
            include_lists=True,
            template=template,
            previews=previews or None,
            placement_report=placements,
            skipped_slides=hidden,
        )
        counts = summarize_plan(transforms)
        print(f"    recipe {recipe.get('source')}, planned {counts['total']} objects {dict(counts)}")
        if hidden:
            print(f"    left {len(hidden)} skipped slide(s) alone: {hidden[:8]}")
        if placements:
            crowded = [p for p in placements if p.get("overlap")]
            print(
                f"    text placement: {len(placements)} moved, {len(crowded)} overlapping"
                + (f" (worst {max(p['overlap'] for p in crowded):.0%})" if crowded else "")
            )
        elif not args.no_previews:
            reason = (
                "no wall previews cached"
                if not previews
                else "nothing sitting on bare background, so nothing to move"
            )
            print(f"    text placement: {reason}; blind packing used")

        score = score_against_gold(transforms, gold, wall=wall)
        if not score["slides"]:
            print("    no comparable slides")
            continue
        print(f"    {'slide':>5} {'role':<6} {'pred':>5} {'gold':>5} {'matched':>7} {'goldRmse':>9}")
        for number in sorted(score["slides"]):
            rows = score["slides"][number]
            aff = rows.get("_goldAffine")
            if aff:
                print(f"    slide {number}: gold used s={aff['s']} tx={aff['tx']} ty={aff['ty']}")
            for role, row in sorted(rows.items()):
                if role.startswith("_"):
                    continue
                got = "-" if row["goldRmse"] is None else f"{row['goldRmse']:.1f}"
                note = "  (reflowed by hand; expect a big number)" if role == "list" else ""
                print(
                    f"    {number:>5} {role:<6} {row['predicted']:>5} {row['gold']:>5} "
                    f"{row['matched']:>7} {got:>9}{note}"
                )
        overall = "-" if score["overallRmse"] is None else f"{score['overallRmse']:.1f}"
        print(f"    overall: {score['overallPairs']} matched, goldRmse {overall}")
        print(
            "    goldRmse = our placement vs where the gold's own transform would put\n"
            "    that same wall object. 0 means we chose the human's layout exactly."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
