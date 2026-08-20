"""Wall 7680×1080 → CG 1920×1080 geometry for map + pins.

Mutates existing Keynote objects (via a JXA plan) so builds and pin-drop
movies keep their identity. The map is a rect-to-rect map learned from a
same-weekend gold CG, or a cover-crop of the wall map onto 16:9.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

CG_WIDTH = 1920
CG_HEIGHT = 1080
MIN_PIN_PX = 28.0

MAP_NAME_RE = re.compile(r"map\s*bg", re.I)
PIN_NAME_RE = re.compile(r"pin\s*drop", re.I)
PIN_KIND_MAX = 180.0


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

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slide": self.slide_number,
            "itemIndex": self.item_index,
            "kind": self.kind,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "w": round(self.w, 2),
            "h": round(self.h, 2),
            "locked": self.locked,
            "role": self.role,
        }
        if self.font_size is not None:
            payload["fontSize"] = round(self.font_size, 2)
        if self.start is not None:
            payload["start"] = [round(self.start[0], 2), round(self.start[1], 2)]
        if self.end is not None:
            payload["end"] = [round(self.end[0], 2), round(self.end[1], 2)]
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


def is_map_item(item: dict) -> bool:
    name = file_name(item)
    if MAP_NAME_RE.search(name):
        return True
    kind = item.get("kind") or ""
    w, h = _f(item.get("w")), _f(item.get("h"))
    return kind == "image" and w >= 3000 and h >= 600


def is_pin_item(item: dict) -> bool:
    name = file_name(item)
    if PIN_NAME_RE.search(name):
        return True
    kind = item.get("kind") or ""
    w, h = _f(item.get("w")), _f(item.get("h"))
    if kind == "movie" and 0 < w <= 800 and 0 < h <= 800:
        return True
    if kind in {"shape", "group"} and 0 < w <= PIN_KIND_MAX and 0 < h <= PIN_KIND_MAX:
        return True
    return False


def is_list_item(item: dict) -> bool:
    if (item.get("kind") or "") != "text":
        return False
    return bool((item.get("text") or "").strip())


def map_rect_from_slide(slide: dict) -> Rect | None:
    maps = [item for item in slide.get("items") or [] if is_map_item(item)]
    if not maps:
        return None
    maps.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    return item_rect(maps[0])


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


def map_point(x: float, y: float, src: Rect, dst: Rect) -> tuple[float, float]:
    sx = dst.w / src.w if src.w else 1.0
    sy = dst.h / src.h if src.h else 1.0
    return (dst.x + (x - src.x) * sx, dst.y + (y - src.y) * sy)


def map_rect(rect: Rect, src: Rect, dst: Rect) -> Rect:
    x, y = map_point(rect.x, rect.y, src, dst)
    sx = dst.w / src.w if src.w else 1.0
    sy = dst.h / src.h if src.h else 1.0
    return Rect(x, y, rect.w * sx, rect.h * sy)


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


def _rect_from_dict(data: dict | None) -> Rect | None:
    if not data:
        return None
    return Rect(_f(data.get("x")), _f(data.get("y")), _f(data.get("w")), _f(data.get("h")))


def _first_slide_with(slides: list[dict], pred) -> dict | None:
    for slide in slides:
        if any(pred(it) for it in slide.get("items") or []):
            return slide
    return None


def learn_recipe(wall: dict, gold: dict) -> dict[str, Any]:
    """Fit map (and optional list) rects from a same-weekend gold CG inspect payload."""
    dest_w = int(gold.get("slideWidth") or CG_WIDTH)
    dest_h = int(gold.get("slideHeight") or CG_HEIGHT)
    wall_slides = wall.get("slides") or []
    gold_slides = gold.get("slides") or []
    w_slide = _first_slide_with(wall_slides, is_map_item) or _first_slide_with(wall_slides, is_pin_item)
    g_slide = _first_slide_with(gold_slides, is_map_item) or _first_slide_with(gold_slides, is_pin_item)
    map_src = None
    map_dst = None
    list_src = None
    list_dst = None
    pin_pairs_n = 0
    pin_rmse = None
    pin_size_scale = None
    if w_slide and g_slide:
        w_maps = [it for it in w_slide.get("items") or [] if is_map_item(it)]
        g_maps = [it for it in g_slide.get("items") or [] if is_map_item(it)]
        for src_item, dst_item in pair_maps(w_maps, g_maps):
            map_src = item_rect(src_item)
            map_dst = item_rect(dst_item)
            break
        if map_src is None:
            map_src = map_rect_from_slide(w_slide)
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
            map_src = map_rect_from_slide(slide)
            if map_src:
                break
    if map_src is None:
        map_src = Rect(0, 0, _f(wall.get("slideWidth"), 7680), _f(wall.get("slideHeight"), 1080))
    if map_dst is None:
        recipe = recipe_from_cover(map_src, dest_w=dest_w, dest_h=dest_h)
        recipe["source"] = "cover-fallback"
        return recipe
    recipe: dict[str, Any] = {
        "destWidth": dest_w,
        "destHeight": dest_h,
        "mapSrc": map_src.as_dict(),
        "mapDst": map_dst.as_dict(),
        "minPin": MIN_PIN_PX,
        "source": "gold",
        "pinPairs": pin_pairs_n,
        "pinRmse": round(pin_rmse, 2) if pin_rmse is not None else None,
        "pinSizeScale": round(pin_size_scale, 4) if pin_size_scale is not None else None,
    }
    if list_src and list_dst and list_src.w > 1 and list_src.h > 1:
        recipe["listSrc"] = list_src.as_dict()
        recipe["listDst"] = list_dst.as_dict()
    return recipe


def classify_item(item: dict, map_src: Rect | None = None) -> str:
    if is_map_item(item):
        return "map"
    if is_pin_item(item):
        return "pin"
    if is_list_item(item):
        return "list"
    return "other"


def _item_index(item: dict, fallback: int) -> int:
    if item.get("index") is not None:
        return int(item["index"])
    return fallback


def plan_slide_transforms(
    slide: dict,
    recipe: dict[str, Any],
) -> list[ItemTransform]:
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    list_src = _rect_from_dict(recipe.get("listSrc"))
    list_dst = _rect_from_dict(recipe.get("listDst"))
    min_pin = _f(recipe.get("minPin"), MIN_PIN_PX)
    if map_src is None or map_dst is None:
        return []
    number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
    out: list[ItemTransform] = []
    for fallback_i, item in enumerate(slide.get("items") or []):
        role = classify_item(item, map_src)
        if role == "other":
            continue
        if role == "list" and (list_src is None or list_dst is None):
            continue
        src, dst = (list_src, list_dst) if role == "list" else (map_src, map_dst)
        assert src is not None and dst is not None
        mapped = map_rect(item_rect(item), src, dst)
        if role == "pin":
            pin_scale = recipe.get("pinSizeScale")
            if pin_scale:
                cx, cy = mapped.center()
                w = max(min_pin, _f(item.get("w")) * float(pin_scale))
                h = max(min_pin, _f(item.get("h")) * float(pin_scale))
                mapped = Rect(cx - w / 2.0, cy - h / 2.0, w, h)
            else:
                mapped = enforce_min_size(mapped, min_pin)
        font = None
        if role == "list" and item.get("size"):
            sy = dst.h / src.h if src.h else 1.0
            font = max(8.0, _f(item.get("size")) * sy)
        start = end = None
        if role == "line" or item.get("start") or item.get("end"):
            if item.get("start"):
                start = map_point(_f(item["start"][0]), _f(item["start"][1]), src, dst)
            if item.get("end"):
                end = map_point(_f(item["end"][0]), _f(item["end"][1]), src, dst)
        out.append(
            ItemTransform(
                slide_number=number,
                item_index=_item_index(item, fallback_i),
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
            )
        )
    return out


def plan_payload_transforms(
    payload: dict[str, Any],
    recipe: dict[str, Any],
    *,
    slide_range: tuple[int, int] | None = None,
) -> list[ItemTransform]:
    transforms: list[ItemTransform] = []
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if slide_range and (number < slide_range[0] or number > slide_range[1]):
            continue
        transforms.extend(plan_slide_transforms(slide, recipe))
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
