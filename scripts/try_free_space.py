"""Offline check of negative-space list placement, no Keynote needed.

Learns the recipe from the cached wall + template inspects, predicts the CG
raster by cropping the wall preview through the learned affine (wall and CG are
both 1080 tall, so the transform is a crop), then packs the real list boxes into
whatever background is left. Writes a before/after visual.

    .venv/bin/python scripts/try_free_space.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from obed_edom.baseline import deck_digest, inspect_cache_path, preview_cache_dir
from obed_edom.free_space import Box, occupancy_from_image, place_boxes, predict_cg_raster
from obed_edom.map_remap import (
    is_list_item,
    learn_recipe,
    occluder_rects,
    plan_slide_transforms,
    sits_on_background,
)
from obed_edom.paths import find_repo_root

GOLD = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
WALL = GOLD / "Map_Extracted_Wall_1st.key"
TEMPLATE = GOLD / "Base_CG_Assets.key"
SLIDE = 2


def cached(path: Path) -> dict:
    digest = deck_digest(path)
    blob = inspect_cache_path(digest)
    if not blob.is_file():
        raise SystemExit(f"No cached inspect for {path.name}; run scripts/inspect_gold.py first.")
    payload = json.loads(blob.read_text(encoding="utf-8"))
    payload["_previewDir"] = str(preview_cache_dir(digest))
    return payload


def main() -> int:
    wall = cached(WALL)
    template = cached(TEMPLATE)
    slide = next(s for s in wall["slides"] if int(s.get("number") or 0) == SLIDE)
    # Learn from this slide alone, as plan_payload_transforms does. Handed a whole
    # deck, learn_recipe takes the first slide holding map-like art, which on this
    # deck is the Taiwan photo, and the resulting affine describes nothing.
    recipe = learn_recipe(
        {
            "slideWidth": wall["slideWidth"],
            "slideHeight": wall["slideHeight"],
            "slides": [slide],
        },
        template,
    )
    transforms = plan_slide_transforms(slide, recipe, include_lists=True)

    dest_w = float(recipe.get("destWidth") or 1920)
    dest_h = float(recipe.get("destHeight") or 1080)
    group = (recipe.get("groups") or [{}])[0]
    scale = float(group.get("s") or 1.0)
    tx = float(group.get("tx") or 0.0)
    ty = float(group.get("ty") or 0.0)
    print(f"recipe {recipe.get('source')}: s={scale} tx={tx} ty={ty}")

    pngs = sorted(Path(wall["_previewDir"]).glob("*.png"))
    if len(pngs) < SLIDE:
        raise SystemExit("Wall previews missing; re-run scripts/inspect_gold.py --previews.")
    full = Image.open(pngs[SLIDE - 1]).convert("RGB")
    wall_w = float(wall["slideWidth"])
    wall_h = float(wall["slideHeight"])
    px = full.width / wall_w
    py = full.height / wall_h


    crop, bg = predict_cg_raster(
        full,
        wall_w=wall_w,
        wall_h=wall_h,
        scale=scale,
        tx=tx,
        ty=ty,
        dest_w=dest_w,
        dest_h=dest_h,
    )
    print(f"predicted CG frame {crop.size}, background {bg}")

    # Only text that sat on bare background is free to move. Text overlapping
    # artwork is a label for it, keeps its affine position, and therefore stays
    # in the mask as something later boxes must avoid.
    occluders = occluder_rects(slide, float(wall["slideWidth"]), float(wall["slideHeight"]))
    movable = [
        item
        for item in slide.get("items") or []
        if is_list_item(item) and sits_on_background(item, occluders)
    ]
    stays = [
        item
        for item in slide.get("items") or []
        if is_list_item(item) and not sits_on_background(item, occluders)
    ]
    print(f"{len(movable)} list boxes free to move, {len(stays)} pinned to artwork")

    cx = crop.width / dest_w
    cy = crop.height / dest_h
    eraser = ImageDraw.Draw(crop)
    for item in movable:
        mx = float(item.get("x") or 0) * scale + tx
        my = float(item.get("y") or 0) * scale + ty
        mw = float(item.get("w") or 0) * scale
        mh = float(item.get("h") or 0) * scale
        eraser.rectangle([mx * cx, my * cy, (mx + mw) * cx, (my + mh) * cy], fill=bg)

    space = occupancy_from_image(crop, slide_w=dest_w, slide_h=dest_h, bg=bg)
    print(f"free fraction of the CG frame: {space.free_fraction:.1%}")

    # Take the planner's sizes (already font-matched to the CG sample) for the
    # boxes that are free to move. Matching is by item identity, not position:
    # _pack_list_transforms has already rewritten x/y by this point, which is the
    # behaviour the real integration replaces.
    movable_keys = {(str(i.get("kind")), int(i.get("kindIndex") or 0)) for i in movable}
    lists = [
        t for t in transforms if t.role == "list" and (t.kind, t.kind_index) in movable_keys
    ]
    print(f"{len(lists)} of {sum(1 for t in transforms if t.role == 'list')} list boxes to place")
    for t in lists[:4]:
        print(f"   current plan x={t.x:.0f} y={t.y:.0f} w={t.w:.0f} h={t.h:.0f}")

    boxes = [Box(t.x, t.y, t.w, t.h) for t in sorted(lists, key=lambda t: (-t.x, t.y))]
    placed = place_boxes(space, boxes, gap=10, margin=16)
    clean = sum(1 for p in placed if p.clean)
    print(f"placed all {len(placed)}: {clean} on clean background, {len(placed) - clean} overlapping")
    for i, p in enumerate(placed):
        if not p.clean:
            print(f"   box {i}: {p.overlap:.0%} covered at x={p.box.x:.0f} y={p.box.y:.0f}")

    canvas = crop.resize((int(dest_w), int(dest_h))).convert("RGB")
    shade = Image.new("RGB", canvas.size, (255, 0, 128))
    mask = Image.new("L", (space.cols, space.rows))
    mask.putdata([0 if space.is_free(Box(c * space.cell, r * space.cell, space.cell, space.cell)) else 90
                  for r in range(space.rows) for c in range(space.cols)])
    canvas = Image.composite(shade, canvas, mask.resize(canvas.size).point(lambda v: 255 if v > 45 else 0))
    draw = ImageDraw.Draw(canvas)
    for old, spot in zip(boxes, placed, strict=True):
        draw.rectangle([old.x, old.y, old.x + old.w, old.y + old.h], outline=(255, 80, 80), width=2)
        new = spot.box
        colour = (60, 255, 120) if spot.clean else (255, 210, 40)
        draw.rectangle([new.x, new.y, new.x + new.w, new.y + new.h], outline=colour, width=3)

    out = find_repo_root() / "output" / ".resize" / "freespace_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
