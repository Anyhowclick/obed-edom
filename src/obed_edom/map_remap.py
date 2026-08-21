"""Wall 7680×1080 → CG 1920×1080 layout remap.

Copy the wall deck and move existing objects (so builds survive). A 16:9
template teaches where those objects should sit. Objects that share the same
scale+translation become one layout group; unpaired items (pins, extra
overlays) inherit the group they sit in. Later slides can have several groups
(a photo vs a text column).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

CG_WIDTH = 1920
CG_HEIGHT = 1080
MIN_PIN_PX = 28.0
# Wall map + pins live on slide 2 of the extracted wall deck.
MVP_MAP_SLIDE = 2

MAP_NAME_RE = re.compile(r"map\s*bg", re.I)
PIN_NAME_RE = re.compile(r"pin\s*drop", re.I)
CHURCH_LIST_RE = re.compile(r"\b(CHC|CHLI|CHEL)\b")
PIN_KIND_MAX = 180.0
# Asia-Pacific map art on the wall and CG_Template is pasted PDFs, not map BG.png.
MAP_LAYER_MIN_W = 400.0
MAP_LAYER_MIN_H = 200.0
MAP_LAYER_MAX_W = 2500.0
MAP_LAYER_MAX_H = 1200.0
# Orange/country overlays sit on the rim of the white map; center-in-box misses them.
MAP_NEAR_PAD = 400.0


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class Affine:
    """Uniform scale + translation: (x, y) → (s*x + tx, s*y + ty).

    Layout groups (map cluster, a photo, a text column) each get one Affine.
    Unpaired objects (pins, extra overlays) inherit the group they sit in.
    """

    s: float
    tx: float
    ty: float

    def similar(self, other: Affine, *, s_tol: float = 0.02, t_tol: float = 2.0) -> bool:
        return (
            abs(self.s - other.s) <= s_tol
            and abs(self.tx - other.tx) <= t_tol
            and abs(self.ty - other.ty) <= t_tol
        )

    def apply_rect(self, rect: Rect) -> Rect:
        return Rect(
            rect.x * self.s + self.tx,
            rect.y * self.s + self.ty,
            rect.w * self.s,
            rect.h * self.s,
        )

    def as_dict(self) -> dict[str, float]:
        return {"s": round(self.s, 6), "tx": round(self.tx, 2), "ty": round(self.ty, 2)}


@dataclass
class ItemTransform:
    slide_number: int
    item_index: int
    kind: str
    x: float
    y: float
    w: float
    h: float
    locked: bool = False
    font_size: float | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    role: str = "other"
    kind_index: int | None = None
    opacity: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slide": self.slide_number,
            "itemIndex": self.item_index,
            "kindIndex": self.kind_index if self.kind_index is not None else self.item_index,
            "kind": self.kind,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "locked": self.locked,
            "role": self.role,
        }
        # Map and pins send size so we can restore after Keynote's slide-size scale.
        # Apply size before position (Keynote resets position when size changes).
        if self.role in {"map", "list", "pin"}:
            payload["w"] = round(self.w, 2)
            payload["h"] = round(self.h, 2)
        if self.font_size is not None:
            payload["fontSize"] = round(self.font_size, 2)
        if self.start is not None:
            payload["start"] = [round(self.start[0], 2), round(self.start[1], 2)]
        if self.end is not None:
            payload["end"] = [round(self.end[0], 2), round(self.end[1], 2)]
        if self.opacity is not None:
            payload["opacity"] = self.opacity
        return payload


def _median(values: list[float]) -> float:
    if not values:
        return 1.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def item_rect(item: dict) -> Rect:
    return Rect(_f(item.get("x")), _f(item.get("y")), _f(item.get("w")), _f(item.get("h")))


def item_center(item: dict) -> tuple[float, float]:
    return item_rect(item).center()


def file_name(item: dict) -> str:
    return str(item.get("fileName") or "")


def point_in_rect(x: float, y: float, rect: Rect, pad: float = 0.0) -> bool:
    return (rect.x - pad) <= x <= (rect.x + rect.w + pad) and (rect.y - pad) <= y <= (
        rect.y + rect.h + pad
    )


def rects_near(a: Rect, b: Rect, pad: float = 0.0) -> bool:
    return not (
        a.x + a.w + pad < b.x
        or b.x + b.w + pad < a.x
        or a.y + a.h + pad < b.y
        or b.y + b.h + pad < a.y
    )


def is_map_layer(item: dict, map_src: Rect | None = None) -> bool:
    """Vector map pieces (pasted-image.pdf), including overlays that hang off the white map."""
    name = file_name(item).lower()
    if "pasted-image" not in name and not name.endswith(".pdf"):
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    if w <= 0 or h <= 0 or w > MAP_LAYER_MAX_W or h > MAP_LAYER_MAX_H:
        return False
    if w >= MAP_LAYER_MIN_W and h >= MAP_LAYER_MIN_H:
        return True
    if map_src is None:
        return False
    return rects_near(item_rect(item), map_src, pad=MAP_NEAR_PAD)


def is_map_item(item: dict, map_src: Rect | None = None) -> bool:
    if MAP_NAME_RE.search(file_name(item)):
        return True
    return is_map_layer(item, map_src)


def is_pin_item(item: dict, map_src: Rect | None = None) -> bool:
    name = file_name(item)
    if PIN_NAME_RE.search(name):
        return True
    kind = item.get("kind") or ""
    w, h = _f(item.get("w")), _f(item.get("h"))
    if kind == "movie" and 0 < w <= 800 and 0 < h <= 800:
        return True
    if kind in {"shape", "group"} and 0 < w <= PIN_KIND_MAX and 0 < h <= PIN_KIND_MAX:
        if map_src is None:
            return True
        cx, cy = item_center(item)
        return point_in_rect(cx, cy, map_src, pad=MAP_NEAR_PAD)
    return False


def is_list_item(item: dict) -> bool:
    if (item.get("kind") or "") != "text":
        return False
    text = (item.get("text") or "").strip()
    if not text:
        return False
    if CHURCH_LIST_RE.search(text):
        return True
    return text.count("\n") >= 3


def map_rect_from_slide(slide: dict) -> Rect | None:
    maps = [item for item in slide.get("items") or [] if is_map_item(item)]
    if not maps:
        return None
    maps.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    return item_rect(maps[0])


def primary_map_rect(items: Iterable[dict]) -> Rect | None:
    """Largest white/base map piece — the affine origin, not the union of overlays."""
    large = [
        it
        for it in items
        if is_map_item(it) and _f(it.get("w")) >= MAP_LAYER_MIN_W and _f(it.get("h")) >= MAP_LAYER_MIN_H
    ]
    if not large:
        named = [it for it in items if is_map_item(it)]
        if not named:
            return None
        named.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
        return item_rect(named[0])
    large.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    return item_rect(large[0])


def effective_wall_map_src(wall: dict, mapped: Rect) -> Rect:
    """If the wall canvas is 7680 but a full-frame 1920×1080 panel inspected, use the canvas.

    Do not expand the CG_Template map art (~1248×771) — that layout is already 16:9-sized
    and only needs to be translated from the wall's center into the CG frame.
    """
    canvas_w = _f(wall.get("slideWidth"), 0)
    canvas_h = _f(wall.get("slideHeight"), 1080)
    full_panel = abs(mapped.w - CG_WIDTH) <= 80 and abs(mapped.h - CG_HEIGHT) <= 80
    if canvas_w >= 7000 and full_panel:
        return Rect(0, 0, canvas_w, canvas_h if canvas_h > 0 else 1080)
    return mapped


def union_rect(items: Iterable[dict]) -> Rect | None:
    rects = [item_rect(it) for it in items if _f(it.get("w")) > 0 or _f(it.get("h")) > 0]
    if not rects:
        return None
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def cover_rect(src: Rect, frame_w: float, frame_h: float) -> Rect:
    """Uniform scale of `src` so it covers the frame. x/y may be negative (crop)."""
    if src.w <= 0 or src.h <= 0:
        return Rect(0, 0, frame_w, frame_h)
    scale = max(frame_w / src.w, frame_h / src.h)
    w, h = src.w * scale, src.h * scale
    return Rect((frame_w - w) / 2.0, (frame_h - h) / 2.0, w, h)


def affine_of(src: Rect, dst: Rect) -> tuple[float, float, float]:
    """Uniform scale + translation mapping src's top-left onto dst's top-left."""
    if src.w <= 0 or src.h <= 0:
        return 1.0, dst.x - src.x, dst.y - src.y
    s = min(dst.w / src.w, dst.h / src.h)
    return s, dst.x - src.x * s, dst.y - src.y * s


def affine_from_rects(src: Rect, dst: Rect) -> Affine:
    return Affine(*affine_of(src, dst))


def map_point(x: float, y: float, src: Rect, dst: Rect) -> tuple[float, float]:
    s, tx, ty = affine_of(src, dst)
    return (x * s + tx, y * s + ty)


def map_rect(rect: Rect, src: Rect, dst: Rect) -> Rect:
    s, tx, ty = affine_of(src, dst)
    return Rect(rect.x * s + tx, rect.y * s + ty, rect.w * s, rect.h * s)


def enforce_min_size(rect: Rect, minimum: float) -> Rect:
    if minimum <= 0:
        return rect
    w, h = rect.w, rect.h
    if w >= minimum and h >= minimum:
        return rect
    cx, cy = rect.center()
    if w <= 0 or h <= 0:
        return Rect(cx - minimum / 2.0, cy - minimum / 2.0, minimum, minimum)
    scale = max(minimum / w, minimum / h)
    w2, h2 = w * scale, h * scale
    return Rect(cx - w2 / 2.0, cy - h2 / 2.0, w2, h2)


def _basename(name: str) -> str:
    stem = name.rsplit("/", 1)[-1]
    return re.sub(r"-\d+\.[A-Za-z0-9]+$", "", stem).lower()


def pair_by_order(left: list[dict], right: list[dict]) -> list[tuple[dict, dict]]:
    n = min(len(left), len(right))
    return list(zip(left[:n], right[:n], strict=False))


def pair_pins(wall: list[dict], gold: list[dict]) -> list[tuple[dict, dict]]:
    """1:1 pins: same count prefers reading order, else spatial (x, y)."""
    if not wall or not gold:
        return []
    if len(wall) == len(gold):
        return list(zip(wall, gold, strict=True))
    wall_s = sorted(wall, key=lambda it: (item_center(it)[0], item_center(it)[1]))
    gold_s = sorted(gold, key=lambda it: (item_center(it)[0], item_center(it)[1]))
    return pair_by_order(wall_s, gold_s)


def is_layout_image(item: dict) -> bool:
    """Images that can be paired wall→template (not full-bleed photo chrome)."""
    if (item.get("kind") or "") != "image":
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    if w <= 0 or h <= 0 or w > MAP_LAYER_MAX_W or h > MAP_LAYER_MAX_H:
        return False
    return True


def pair_by_size(wall: list[dict], dest: list[dict]) -> list[tuple[dict, dict]]:
    """1:1 by (width, height). Same-size copies (stacked map PDFs) pair in order."""
    used: set[int] = set()
    pairs: list[tuple[dict, dict]] = []
    for item in sorted(wall, key=lambda it: (_f(it.get("w")) * _f(it.get("h")), _f(it.get("x"))), reverse=True):
        key = (round(_f(item.get("w"))), round(_f(item.get("h"))))
        if key[0] <= 0 or key[1] <= 0:
            continue
        for j, other in enumerate(dest):
            if j in used:
                continue
            if (round(_f(other.get("w"))), round(_f(other.get("h")))) == key:
                pairs.append((item, other))
                used.add(j)
                break
    return pairs


def merge_affine_groups(pairs: list[tuple[dict, dict]]) -> list[dict[str, Any]]:
    """Collapse object-pairs that share (s, tx, ty) into layout groups."""
    groups: list[dict[str, Any]] = []
    for src_item, dst_item in pairs:
        aff = affine_from_rects(item_rect(src_item), item_rect(dst_item))
        matched = None
        for group in groups:
            if group["affine"].similar(aff):
                matched = group
                break
        if matched is None:
            matched = {"affine": aff, "members": []}
            groups.append(matched)
        matched["members"].append((src_item, dst_item))
    out: list[dict[str, Any]] = []
    for group in groups:
        members: list[tuple[dict, dict]] = group["members"]
        src = union_rect([a for a, _ in members])
        dst = union_rect([b for _, b in members])
        # Prefer the affine of the largest member so overlays don't shift the origin.
        members.sort(key=lambda pair: _f(pair[0].get("w")) * _f(pair[0].get("h")), reverse=True)
        aff = affine_from_rects(item_rect(members[0][0]), item_rect(members[0][1]))
        out.append(
            {
                "affine": aff,
                "src": src,
                "dst": dst,
                "members": members,
            }
        )
    out.sort(key=lambda g: (g["src"].w * g["src"].h) if g["src"] else 0, reverse=True)
    return out


def pair_maps(wall: list[dict], gold: list[dict]) -> list[tuple[dict, dict]]:
    if len(wall) == 1 and len(gold) == 1:
        return [(wall[0], gold[0])]
    gold_by = {_basename(file_name(it)): it for it in gold}
    pairs: list[tuple[dict, dict]] = []
    used: set[int] = set()
    for item in wall:
        key = _basename(file_name(item))
        other = gold_by.get(key)
        if other is not None and id(other) not in used:
            pairs.append((item, other))
            used.add(id(other))
    if pairs:
        return pairs
    return pair_by_order(
        sorted(wall, key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True),
        sorted(gold, key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True),
    )


def pair_list(wall: list[dict], gold: list[dict]) -> list[tuple[dict, dict]]:
    gold_by: dict[str, dict] = {}
    for item in gold:
        text = re.sub(r"\s+", " ", (item.get("text") or "").strip())
        if text and text not in gold_by:
            gold_by[text] = item
    pairs: list[tuple[dict, dict]] = []
    used: set[int] = set()
    for item in wall:
        text = re.sub(r"\s+", " ", (item.get("text") or "").strip())
        other = gold_by.get(text)
        if other is not None and id(other) not in used:
            pairs.append((item, other))
            used.add(id(other))
    return pairs


def rmse_points(pairs: list[tuple[tuple[float, float], tuple[float, float]]]) -> float:
    if not pairs:
        return 0.0
    acc = 0.0
    for (ax, ay), (bx, by) in pairs:
        acc += (ax - bx) ** 2 + (ay - by) ** 2
    return math.sqrt(acc / len(pairs))


def recipe_from_cover(map_src: Rect, *, dest_w: int = CG_WIDTH, dest_h: int = CG_HEIGHT) -> dict[str, Any]:
    dst = cover_rect(map_src, dest_w, dest_h)
    return {
        "destWidth": dest_w,
        "destHeight": dest_h,
        "mapSrc": map_src.as_dict(),
        "mapDst": dst.as_dict(),
        "minPin": MIN_PIN_PX,
        "pinSizeScale": round(min(dst.w / map_src.w, dst.h / map_src.h), 4) if map_src.w and map_src.h else 1.0,
        "source": "cover",
    }


def map_dst_for_cg(wall_map: Rect, template_map: Rect, dest_w: float, dest_h: float) -> Rect:
    """Fill 16:9 by cropping the wall map, not by scaling the whole 7680 canvas down.

    If the template already stores a wide map (negative x / width > 1920), use that
    crop. A full-frame 1920×1080 image, or a letterboxed strip from scale-to-fit,
    means “cover this canvas” — not “shrink 7680 into 1920.”
    """
    if template_map.w >= dest_w + 80 or template_map.x < -10:
        return template_map
    wall_is_wide = wall_map.w >= dest_w * 2
    if not wall_is_wide:
        return template_map
    template_fills_frame = template_map.h >= dest_h * 0.85 and template_map.w >= dest_w * 0.85
    letterboxed = template_map.w >= dest_w * 0.85 and template_map.h < dest_h * 0.6
    if template_fills_frame or letterboxed:
        return cover_rect(wall_map, dest_w, dest_h)
    return template_map


def _rect_from_dict(data: dict | None) -> Rect | None:
    if not data:
        return None
    return Rect(_f(data.get("x")), _f(data.get("y")), _f(data.get("w")), _f(data.get("h")))


def _first_slide_with(slides: list[dict], pred) -> dict | None:
    for slide in slides:
        if any(pred(it) for it in slide.get("items") or []):
            return slide
    return None


def _score_template_slide(wall_slide: dict, template_slide: dict) -> int:
    """Prefer the CG slide whose images share sizes with the wall map cluster."""
    wall_imgs = [it for it in wall_slide.get("items") or [] if is_layout_image(it)]
    tmpl_imgs = [it for it in template_slide.get("items") or [] if is_layout_image(it)]
    pairs = len(pair_by_size(wall_imgs, tmpl_imgs)) if wall_imgs and tmpl_imgs else 0
    if pairs:
        return pairs * 100
    return len([it for it in template_slide.get("items") or [] if is_map_item(it)])


def _best_matching_slide(wall_slide: dict | None, candidates: list[dict]) -> dict | None:
    if not wall_slide:
        return _first_slide_with(candidates, is_map_item) or _first_slide_with(
            candidates, is_pin_item
        )
    best: dict | None = None
    best_score = -1
    for slide in candidates:
        score = _score_template_slide(wall_slide, slide)
        if score > best_score:
            best_score = score
            best = slide
    if best is not None and best_score > 0:
        return best
    return _first_slide_with(candidates, is_map_item) or _first_slide_with(
        candidates, is_pin_item
    )


def learn_recipe(wall: dict, template: dict) -> dict[str, Any]:
    """Fit map rects from a 16:9 CG template inspect payload."""
    dest_w = int(template.get("slideWidth") or CG_WIDTH)
    dest_h = int(template.get("slideHeight") or CG_HEIGHT)
    wall_slides = wall.get("slides") or []
    template_slides = template.get("slides") or []
    w_slide = _first_slide_with(wall_slides, is_map_item) or _first_slide_with(wall_slides, is_pin_item)
    g_slide = _best_matching_slide(w_slide, template_slides)
    map_src = None
    map_dst = None
    list_src = None
    list_dst = None
    pin_pairs_n = 0
    pin_rmse = None
    pin_size_scale = None
    grouped: list[dict[str, Any]] = []
    if w_slide and g_slide:
        w_imgs = [it for it in w_slide.get("items") or [] if is_layout_image(it)]
        g_imgs = [it for it in g_slide.get("items") or [] if is_layout_image(it)]
        size_pairs = pair_by_size(w_imgs, g_imgs)
        grouped = merge_affine_groups(size_pairs) if size_pairs else []
        if grouped:
            biggest = grouped[0]["members"][0]
            map_src = effective_wall_map_src(wall, item_rect(biggest[0]))
            raw_dst = item_rect(biggest[1])
            map_dst = map_dst_for_cg(map_src, raw_dst, dest_w, dest_h)
            # Cover replaces the template box; keep a single group with that affine.
            if abs(map_dst.w - raw_dst.w) > 80 or abs(map_dst.x - raw_dst.x) > 80:
                grouped = [
                    {
                        "affine": affine_from_rects(map_src, map_dst),
                        "src": map_src,
                        "dst": map_dst,
                        "members": grouped[0]["members"],
                    }
                ]
        else:
            w_maps = [it for it in w_slide.get("items") or [] if is_map_item(it)]
            g_maps = [it for it in g_slide.get("items") or [] if is_map_item(it)]
            w_primary = primary_map_rect(w_maps) or union_rect(w_maps)
            g_primary = primary_map_rect(g_maps) or union_rect(g_maps)
            if w_primary:
                map_src = effective_wall_map_src(wall, w_primary)
            if map_src and g_primary:
                map_dst = map_dst_for_cg(map_src, g_primary, dest_w, dest_h)
            elif g_primary:
                map_dst = g_primary
        if map_src is None:
            raw = map_rect_from_slide(w_slide)
            map_src = effective_wall_map_src(wall, raw) if raw else None
        if map_src and map_dst:
            w_pins = [it for it in w_slide.get("items") or [] if is_pin_item(it)]
            g_pins = [it for it in g_slide.get("items") or [] if is_pin_item(it)]
            pairs = pair_pins(w_pins, g_pins)
            pin_pairs_n = len(pairs)
            predicted = [map_point(*item_center(a), map_src, map_dst) for a, _ in pairs]
            actual = [item_center(b) for _, b in pairs]
            pin_rmse = rmse_points(list(zip(predicted, actual, strict=False)))
            size_scales = []
            for src_pin, dst_pin in pairs:
                sw = _f(src_pin.get("w"))
                dw = _f(dst_pin.get("w"))
                if sw > 0 and dw > 0:
                    size_scales.append(dw / sw)
            pin_size_scale = _median(size_scales) if size_scales else min(
                map_dst.w / map_src.w, map_dst.h / map_src.h
            )
            w_list = [it for it in w_slide.get("items") or [] if is_list_item(it)]
            g_list = [it for it in g_slide.get("items") or [] if is_list_item(it)]
            named = pair_list(w_list, g_list)
            list_src = union_rect([a for a, _ in named] or w_list)
            list_dst = union_rect([b for _, b in named] or g_list)
    if map_src is None:
        for slide in wall_slides:
            raw = map_rect_from_slide(slide)
            if raw:
                map_src = effective_wall_map_src(wall, raw)
                break
    if map_src is None:
        map_src = Rect(0, 0, _f(wall.get("slideWidth"), 7680), _f(wall.get("slideHeight"), 1080))
    else:
        map_src = effective_wall_map_src(wall, map_src)
    if map_dst is None:
        recipe = recipe_from_cover(map_src, dest_w=dest_w, dest_h=dest_h)
        recipe["source"] = "cover-fallback"
        recipe["groups"] = [
            {
                **affine_from_rects(map_src, _rect_from_dict(recipe["mapDst"]) or map_src).as_dict(),
                "src": map_src.as_dict(),
                "dst": recipe["mapDst"],
                "members": 0,
            }
        ]
        return recipe
    recipe: dict[str, Any] = {
        "destWidth": dest_w,
        "destHeight": dest_h,
        "mapSrc": map_src.as_dict(),
        "mapDst": map_dst.as_dict(),
        "minPin": MIN_PIN_PX,
        "source": _recipe_source(map_src, map_dst, dest_w),
        "pinPairs": pin_pairs_n,
        "pinRmse": round(pin_rmse, 2) if pin_rmse is not None else None,
        "pinSizeScale": round(pin_size_scale, 4) if pin_size_scale is not None else None,
    }
    if list_src and list_dst and list_src.w > 1 and list_src.h > 1:
        recipe["listSrc"] = list_src.as_dict()
        recipe["listDst"] = list_dst.as_dict()
    if grouped:
        recipe["groups"] = [
            {
                **g["affine"].as_dict(),
                "src": g["src"].as_dict() if g["src"] else None,
                "dst": g["dst"].as_dict() if g["dst"] else None,
                "members": len(g["members"]),
            }
            for g in grouped
        ]
    return recipe


def cg_layout_name(name: str) -> str:
    """Wall `MAP BLANK` → CG `MAP BLANK (16:9)`. Already-suffixed names stay put."""
    text = (name or "").strip()
    if not text:
        return ""
    if re.search(r"\(16:9\)\s*$", text):
        return text
    return f"{text} (16:9)"


def _recipe_source(map_src: Rect, map_dst: Rect, dest_w: float) -> str:
    if map_src.w <= 0:
        return "template"
    scale = map_dst.w / map_src.w
    if 0.9 <= scale <= 1.1 and map_dst.w < dest_w + 80:
        return "template-layout"
    if map_dst.w > dest_w + 80 or map_dst.x < -10:
        return "template-cover"
    return "template"


def _groups_from_recipe(recipe: dict[str, Any]) -> list[tuple[Affine, Rect]]:
    groups: list[tuple[Affine, Rect]] = []
    for raw in recipe.get("groups") or []:
        src = _rect_from_dict(raw.get("src"))
        if src is None:
            continue
        groups.append((Affine(_f(raw.get("s"), 1.0), _f(raw.get("tx")), _f(raw.get("ty"))), src))
    if groups:
        return groups
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    if map_src and map_dst:
        return [(affine_from_rects(map_src, map_dst), map_src)]
    return []


def _affine_for_item(item: dict, groups: list[tuple[Affine, Rect]]) -> Affine | None:
    if not groups:
        return None
    rect = item_rect(item)
    cx, cy = rect.center()
    for aff, src in groups:
        if rects_near(rect, src, MAP_NEAR_PAD) or point_in_rect(cx, cy, src, MAP_NEAR_PAD):
            return aff
    return None


def classify_item(item: dict, map_src: Rect | None = None) -> str:
    if is_map_item(item, map_src):
        return "map"
    if is_pin_item(item, map_src):
        return "pin"
    if is_list_item(item):
        return "list"
    return "other"


def _item_index(item: dict, fallback: int) -> int:
    if item.get("index") is not None:
        return int(item["index"])
    return fallback


def _item_kind_index(item: dict, fallback: int) -> int:
    if item.get("kindIndex") is not None:
        return int(item["kindIndex"])
    return fallback


def plan_slide_transforms(
    slide: dict,
    recipe: dict[str, Any],
    *,
    include_lists: bool = False,
) -> list[ItemTransform]:
    groups = _groups_from_recipe(recipe)
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    if not groups and (map_src is None or map_dst is None):
        return []
    number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
    out: list[ItemTransform] = []
    for fallback_i, item in enumerate(slide.get("items") or []):
        aff = _affine_for_item(item, groups)
        cluster = groups[0][1] if groups else map_src
        role = classify_item(item, cluster)
        if role == "other" and aff is None:
            continue
        if role == "other" and aff is not None:
            # Extra overlay that sits on a layout group but isn't named as map/pin.
            role = "map" if is_layout_image(item) else "other"
        if role == "other":
            continue
        item_index = _item_index(item, fallback_i)
        kind_index = _item_kind_index(item, item_index)
        if role == "list" and not include_lists:
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "text"),
                    x=_f(item.get("x")),
                    y=_f(item.get("y")),
                    w=_f(item.get("w")),
                    h=_f(item.get("h")),
                    locked=bool(item.get("locked")),
                    role="hide",
                    kind_index=kind_index,
                    opacity=0.0,
                )
            )
            continue
        if aff is None and map_src and map_dst:
            mapped = map_rect(item_rect(item), map_src, map_dst)
            font_scale = map_dst.h / map_src.h if map_src.h else 1.0
        elif aff is not None:
            mapped = aff.apply_rect(item_rect(item))
            font_scale = aff.s
        else:
            continue
        font = None
        if role == "list" and item.get("size"):
            font = max(8.0, _f(item.get("size")) * font_scale)
        start = end = None
        if role == "line" or item.get("start") or item.get("end"):
            if item.get("start"):
                x0, y0 = item["start"][0], item["start"][1]
                if aff is not None:
                    start = (aff.s * _f(x0) + aff.tx, aff.s * _f(y0) + aff.ty)
                elif map_src and map_dst:
                    start = map_point(_f(x0), _f(y0), map_src, map_dst)
            if item.get("end"):
                x1, y1 = item["end"][0], item["end"][1]
                if aff is not None:
                    end = (aff.s * _f(x1) + aff.tx, aff.s * _f(y1) + aff.ty)
                elif map_src and map_dst:
                    end = map_point(_f(x1), _f(y1), map_src, map_dst)
        out.append(
            ItemTransform(
                slide_number=number,
                item_index=item_index,
                kind=str(item.get("kind") or "item"),
                x=mapped.x,
                y=mapped.y,
                w=mapped.w,
                h=mapped.h,
                locked=bool(item.get("locked")),
                font_size=font,
                start=start,
                end=end,
                role=role,
                kind_index=kind_index,
            )
        )
    role_order = {"map": 0, "pin": 1, "list": 2, "hide": 3, "line": 4, "other": 5}
    out.sort(key=lambda t: role_order.get(t.role, 9))
    return out


def resolve_slide_range(
    range_from: int | None,
    range_to: int | None = None,
    *,
    default: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    """`2` → (2, 2). `1` and `9` → (1, 9). Both missing → `default`."""
    if range_from is None and range_to is None:
        return default
    start = range_from if range_from is not None else range_to
    end = range_to if range_to is not None else range_from
    if start is None or end is None:
        return default
    start_i, end_i = int(start), int(end)
    if start_i < 1 or end_i < start_i:
        raise ValueError(f"Invalid slide range {start_i}-{end_i}")
    return (start_i, end_i)


def plan_payload_transforms(
    payload: dict[str, Any],
    recipe: dict[str, Any],
    *,
    slide_range: tuple[int, int] | None = None,
    include_lists: bool = False,
) -> list[ItemTransform]:
    transforms: list[ItemTransform] = []
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if slide_range and (number < slide_range[0] or number > slide_range[1]):
            continue
        transforms.extend(plan_slide_transforms(slide, recipe, include_lists=include_lists))
    return transforms


def score_against_gold(
    predicted: list[ItemTransform],
    gold: dict[str, Any],
) -> dict[str, Any]:
    """RMSE of remapped pin centers vs gold pins on the first overlapping map slide."""
    by_slide: dict[int, list[ItemTransform]] = {}
    for spec in predicted:
        if spec.role != "pin":
            continue
        by_slide.setdefault(spec.slide_number, []).append(spec)
    best: dict[str, Any] = {"pinPairs": 0, "pinRmse": None}
    for slide in gold.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        pred = by_slide.get(number) or []
        gold_pins = [it for it in slide.get("items") or [] if is_pin_item(it)]
        if not pred or not gold_pins:
            continue
        pred_s = sorted(pred, key=lambda t: (t.x + t.w / 2.0, t.y + t.h / 2.0))
        gold_s = sorted(gold_pins, key=lambda it: item_center(it))
        n = min(len(pred_s), len(gold_s))
        pairs = [
            ((pred_s[i].x + pred_s[i].w / 2.0, pred_s[i].y + pred_s[i].h / 2.0), item_center(gold_s[i]))
            for i in range(n)
        ]
        best = {"pinPairs": n, "pinRmse": round(rmse_points(pairs), 2)}
        break
    return best


def summarize_plan(transforms: list[ItemTransform]) -> dict[str, int]:
    counts: dict[str, int] = {"map": 0, "pin": 0, "list": 0, "line": 0, "other": 0}
    for spec in transforms:
        counts[spec.role] = counts.get(spec.role, 0) + 1
    counts["total"] = len(transforms)
    return counts
