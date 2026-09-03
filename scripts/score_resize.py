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
    DEFAULT_CARD_STROKE,
    align_by_geometry,
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
    try:
        from obed_edom.iwa_runs import attach_group_captions

        attach_group_captions(TEMPLATE, template)
    except Exception as exc:  # noqa: BLE001 — score without card samples rather than crash
        print(f"    template caption data unavailable ({type(exc).__name__}: {exc})")

    slide_range = resolve_slides(spec=args.slides, range_from=None, range_to=None) if args.slides else None

    for wall_name, cg_name in PAIRS:
        wall = cached(GOLD_DIR / wall_name)
        gold = cached(GOLD_DIR / cg_name)
        print(f"\n=== {wall_name} -> {cg_name}")
        if wall is None or gold is None:
            missing = wall_name if wall is None else cg_name
            print(f"    skipped: {missing} is not cached")
            continue

        card_stroke = DEFAULT_CARD_STROKE
        try:
            from obed_edom.iwa_runs import _load_deck, attach_group_captions, attach_group_child_text
            from obed_edom.iwa_write import card_styles, select_card_styles

            wall_path = GOLD_DIR / wall_name
            deck = _load_deck(wall_path)
            attach_group_child_text(wall_path, wall, deck=deck)
            attach_group_captions(wall_path, wall, deck=deck)
            objects, id_to_file, _file_ids = deck
            selected = [
                s
                for s in select_card_styles(card_styles(objects, id_to_file), min_refs=10)
                if not s.get("inherited")
            ]
            widths = sorted(s["width"] for s in selected if s.get("width") is not None)
            if widths:
                card_stroke = widths[len(widths) // 2]
        except Exception as exc:  # noqa: BLE001 — score without card data rather than crash
            print(f"    card data unavailable ({type(exc).__name__}: {exc})")

        recipe = learn_recipe(wall, template)
        wanted = sorted(slide_range) if slide_range else None
        previews = {} if args.no_previews else previews_for(wall, wanted)
        placements: list[dict[str, Any]] = []
        hidden: list[int] = []
        card_grid: list[dict[str, Any]] = []
        transforms = plan_payload_transforms(
            wall,
            recipe,
            slide_range=slide_range,
            include_lists=True,
            template=template,
            previews=previews or None,
            placement_report=placements,
            skipped_slides=hidden,
            card_stroke=card_stroke,
            card_grid_report=card_grid,
        )
        counts = summarize_plan(transforms)
        print(f"    recipe {recipe.get('source')}, planned {counts['total']} objects {dict(counts)}")
        if hidden:
            print(f"    left {len(hidden)} skipped slide(s) alone: {hidden[:8]}")
        for row in card_grid:
            print(
                f"    card slide {row['slide']}: n={row['n']} {row['cols']}x{row['rows']} "
                f"pitch={row['pitchX']}/{row['pitchY']} origin=({row['x0']},{row['y0']}) "
                f"offCanvas={row['offCanvas']} overlapping={len(row.get('overlaps') or [])}"
            )
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

        # Slide N against slide N only holds when the decks run in step. The
        # report deck is 158 wall slides against 207 CG slides, so pair by shape.
        slide_map = align_by_geometry(wall.get("slides") or [], gold.get("slides") or [])
        pairs_off_diagonal = sum(1 for w, g in slide_map.items() if w != g)
        if slide_map and pairs_off_diagonal:
            print(
                f"    slide alignment: {len(slide_map)} pairs by geometry, "
                f"{pairs_off_diagonal} not on the diagonal"
            )
        score = score_against_gold(transforms, gold, wall=wall, slide_map=slide_map or None)
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
