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
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

# region agent log
def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    import json
    import time

    try:
        with open(
            "/Users/anyhowclick/Desktop/work/obed-edom/.cursor/debug-6310d1.log",
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    {
                        "sessionId": "6310d1",
                        "runId": "post-fix",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except OSError:
        pass
# endregion

CG_WIDTH = 1920
CG_HEIGHT = 1080
MIN_PIN_PX = 28.0

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
# Title plate / globe sit beside the map; keep that cluster on one affine.
TITLE_NEAR_PAD = 120.0
# Map crop is often s≈1; unmatched wall text still needs to shrink for 16:9.
TEXT_DOWN_SCALE = 0.42
# Fraction of a page's visible objects that must still land on the CG canvas for
# the learned affine to be believed. Judged on the outcome rather than on how
# many objects agreed, because a good template can be deliberately sparse — one
# anchor image per layout is the documented advice — and counting agreements
# would punish exactly that.
MIN_ON_CANVAS_FRACTION = 0.5
# A text box counts as sitting on bare background when at least this much of the
# pixels under it are the background colour. Its own glyphs are in the sample, so
# this never approaches 1.0; landmass under a box drops it far below.
FREE_TEXT_BACKGROUND_MIN = 0.55
# An object showing less than this much of itself inside the CG frame is
# reported. Bleeding off an edge is normal and intended; disappearing is not.
OFFFRAME_MIN_VISIBLE = 0.5


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
    font: str | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    role: str = "other"
    kind_index: int | None = None
    opacity: float | None = None
    color: tuple[float, float, float] | None = None
    match_text: str | None = None

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
        if self.role in {"map", "list", "pin", "title", "other"}:
            payload["w"] = round(self.w, 2)
            payload["h"] = round(self.h, 2)
        if self.font_size is not None:
            payload["fontSize"] = round(self.font_size, 2)
        if self.font:
            payload["font"] = self.font
        if self.color is not None:
            bits = rgb16(self.color)
            if bits:
                payload["color"] = bits
        if self.start is not None:
            payload["start"] = [round(self.start[0], 2), round(self.start[1], 2)]
        if self.end is not None:
            payload["end"] = [round(self.end[0], 2), round(self.end[1], 2)]
        if self.opacity is not None:
            payload["opacity"] = self.opacity
        if self.match_text:
            payload["matchText"] = self.match_text
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
    start = item.get("start")
    end = item.get("end")
    if (
        isinstance(start, (list, tuple))
        and isinstance(end, (list, tuple))
        and len(start) >= 2
        and len(end) >= 2
    ):
        x0, y0 = _f(start[0]), _f(start[1])
        x1, y1 = _f(end[0]), _f(end[1])
        return Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    return Rect(_f(item.get("x")), _f(item.get("y")), _f(item.get("w")), _f(item.get("h")))


def item_center(item: dict) -> tuple[float, float]:
    return item_rect(item).center()


def file_name(item: dict) -> str:
    return str(item.get("fileName") or "")


def norm_rgb(color: Any) -> tuple[float, float, float] | None:
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        return None
    try:
        r, g, b = float(color[0]), float(color[1]), float(color[2])
    except (TypeError, ValueError):
        return None
    if max(r, g, b) > 2.0:
        r, g, b = r / 65535.0, g / 65535.0, b / 65535.0
    return (
        max(0.0, min(1.0, r)),
        max(0.0, min(1.0, g)),
        max(0.0, min(1.0, b)),
    )


def item_rgb(item: dict) -> tuple[float, float, float] | None:
    return norm_rgb(item.get("color"))


def rgb16(color: Any) -> list[int] | None:
    rgb = norm_rgb(color)
    if rgb is None:
        return None
    return [int(round(c * 65535)) for c in rgb]


def color_distance(
    left: tuple[float, float, float] | None,
    right: tuple[float, float, float] | None,
) -> float:
    if left is None or right is None:
        return 0.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def point_in_rect(x: float, y: float, rect: Rect, pad: float = 0.0) -> bool:
    return (rect.x - pad) <= x <= (rect.x + rect.w + pad) and (rect.y - pad) <= y <= (
        rect.y + rect.h + pad
    )


def dist_to_rect(x: float, y: float, rect: Rect) -> float:
    dx = max(rect.x - x, 0.0, x - (rect.x + rect.w))
    dy = max(rect.y - y, 0.0, y - (rect.y + rect.h))
    return math.hypot(dx, dy)


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


# The badge wording changes with the series — "Global Missions" one term,
# "Missions Update" the next, in English or Chinese. A phrase this misses is a
# badge that gets treated as ordinary content and can walk off the CG frame, so
# the list lives in masters.yaml under `cg.title_phrases` where staff can extend
# it without a code change.
DEFAULT_TITLE_PHRASES = (
    "global missions",
    "全球使命",
    "missions update",
    "宣教近况",
)


@lru_cache(maxsize=1)
def title_pattern() -> re.Pattern[str]:
    phrases: list[str] = []
    try:
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load((Path(__file__).resolve().parent / "masters.yaml").read_text())
        configured = ((raw or {}).get("cg") or {}).get("title_phrases") or []
        phrases = [str(p).strip() for p in configured if str(p).strip()]
    except Exception:  # noqa: BLE001 - a broken key must not stop a remap
        phrases = []
    if not phrases:
        phrases = list(DEFAULT_TITLE_PHRASES)
    return re.compile("|".join(re.escape(p) for p in phrases), re.I)


def is_title_item(item: dict) -> bool:
    if (item.get("kind") or "") != "text":
        return False
    return bool(title_pattern().search((item.get("text") or "").strip()))


def is_placeholder_text(item: dict) -> bool:
    """Empty layout text boxes (MAP BLANK's 0×0 AzoSans seeds)."""
    if (item.get("kind") or "") != "text":
        return False
    if (item.get("text") or "").strip():
        return False
    return _f(item.get("w")) <= 1 and _f(item.get("h")) <= 1


def is_visible(item: dict, slide_w: float, slide_h: float) -> bool:
    """Does any part of this object fall on the canvas?

    Wall decks carry genuinely off-slide leftovers — cropped videos and photos,
    stray pins, map fragments parked above the top edge. Only what shows matters,
    and ignoring the rest is not merely tidy: an off-canvas object put through the
    affine can land inside the CG frame and appear in output it was never in.

    Partly-visible objects are kept, since their visible part is real content.
    """
    if slide_w <= 0 or slide_h <= 0:
        return True
    rect = item_rect(item)
    # Keynote reports a 90° line as width=length, height=0 (or the reverse after
    # we rebuild the box from start/end). Zero thickness is still a visible stroke.
    if rect.w <= 0 and rect.h <= 0:
        return False
    w = rect.w if rect.w > 0 else 1.0
    h = rect.h if rect.h > 0 else 1.0
    return rect.x < slide_w and rect.y < slide_h and rect.x + w > 0 and rect.y + h > 0


def is_backdrop(item: dict, slide_w: float, slide_h: float) -> bool:
    """A full-canvas image or shape: the slide's background, not content on it."""
    if (item.get("kind") or "") not in {"image", "shape"}:
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    if w <= 0 or h <= 0 or slide_w <= 0 or slide_h <= 0:
        return False
    return w >= slide_w * 0.98 and h >= slide_h * 0.98


def occluder_rects(slide: dict, slide_w: float, slide_h: float) -> list[Rect]:
    """Artwork a text box could be sitting on top of.

    Backdrops and LED chrome tiles are excluded: they cover everything, so
    counting them would make every text box look anchored to something.
    """
    out: list[Rect] = []
    for item in slide.get("items") or []:
        if (item.get("kind") or "") not in {"image", "movie", "shape", "group"}:
            continue
        if item.get("duplicateOf") or is_chrome_bg(item):
            continue
        if is_backdrop(item, slide_w, slide_h) or not is_visible(item, slide_w, slide_h):
            continue
        rect = item_rect(item)
        if rect.w > 0 and rect.h > 0:
            out.append(rect)
    return out


def sits_on_background(item: dict, occluders: list[Rect]) -> bool:
    """True when there is nothing under this text but the slide background.

    This is the test for whether a text box may be moved. On the wall these
    boxes sat in open space on the side panels, so the crop to 16:9 leaves them
    nowhere to be; they should be re-placed into whatever space is left. Text
    that overlaps artwork is a label for it and has to keep that relationship,
    even if the result is cramped.
    """
    if (item.get("kind") or "") != "text":
        return False
    rect = item_rect(item)
    if rect.w <= 0 or rect.h <= 0:
        return False
    return not any(_rects_overlap(rect, other) for other in occluders)


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def is_style_sample(item: dict) -> bool:
    """A CG text swatch staff can drop on Empty_Map (font + size, not a 0×0 leftover)."""
    if (item.get("kind") or "") != "text" or is_placeholder_text(item):
        return False
    if _f(item.get("size")) <= 0:
        return False
    return bool((item.get("font") or "").strip() or (item.get("text") or "").strip())


def split_font(name: str) -> tuple[str, str]:
    raw = (name or "").strip()
    if not raw:
        return "", ""
    if "-" in raw:
        family, weight = raw.rsplit("-", 1)
        return family.lower(), weight.lower()
    return raw.lower(), ""


def template_character_styles(slides: list[dict]) -> list[dict[str, Any]]:
    """Deduped (font, size, colour) palette from the template's sample text."""
    styles: list[dict[str, Any]] = []
    seen: set[tuple[str, float, tuple[float, ...] | None]] = set()
    for slide in slides:
        for item in slide.get("items") or []:
            if not is_style_sample(item):
                continue
            font = (item.get("font") or "").strip()
            size = round(_f(item.get("size")), 2)
            rgb = item_rgb(item)
            key = (font.lower(), size, tuple(round(c, 3) for c in rgb) if rgb else None)
            if key in seen:
                continue
            seen.add(key)
            rec: dict[str, Any] = {
                "font": font,
                "size": size,
                "text": (item.get("text") or "").strip()[:40],
            }
            if rgb:
                rec["color"] = [round(c, 4) for c in rgb]
            styles.append(rec)
    return styles


def match_character_style(
    item: dict,
    styles: list[dict[str, Any]],
    *,
    size_ratio: float = 0.5,
) -> dict[str, Any] | None:
    """Return a CG swatch only when the wall face matches (family + weight).

    Colour then size break ties among matching faces. No swatch → caller resizes
    with the map affine and leaves the wall font/colour alone.
    """
    if not styles:
        return None
    family, weight = split_font(item.get("font") or "")
    if not family:
        return None
    wall_size = _f(item.get("size"))
    predicted = wall_size * size_ratio if wall_size > 0 else 0.0
    wall_rgb = item_rgb(item)
    candidates: list[dict[str, Any]] = []
    for style in styles:
        sf, sw = split_font(style.get("font") or "")
        if sf != family:
            continue
        if (weight or "") != (sw or ""):
            continue
        candidates.append(style)
    if not candidates:
        return None

    def penalty(style: dict[str, Any]) -> tuple[float, float]:
        colour = color_distance(wall_rgb, norm_rgb(style.get("color")))
        size_pen = abs(_f(style.get("size")) - predicted) if predicted else 0.0
        return (colour, size_pen)

    return min(candidates, key=penalty)


def slide_has_column_lists(slide: dict) -> bool:
    lists = [it for it in slide.get("items") or [] if is_list_item(it)]
    if len(lists) >= 2:
        return True
    return any("\n" in (it.get("text") or "") for it in lists)


def template_list_sample(slides: list[dict]) -> tuple[float | None, Rect | None]:
    """Prefer a one-line church-name seed (Empty_Map's resized CHC Aaliana) over a column."""
    candidates: list[tuple[int, float, Rect]] = []
    for slide in slides:
        for item in slide.get("items") or []:
            if not is_list_item(item):
                continue
            size = _f(item.get("size"))
            if size <= 0:
                continue
            text = (item.get("text") or "").strip()
            lines = text.count("\n") + 1
            candidates.append((lines, size, item_rect(item)))
    if not candidates:
        return None, None
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][1], candidates[0][2]


def template_title_item(slides: list[dict]) -> dict | None:
    for slide in slides:
        for item in slide.get("items") or []:
            if is_title_item(item) and _f(item.get("w")) > 0:
                return item
    return None


def pack_columns_from_right(
    boxes: list[Rect],
    dest_w: float,
    dest_h: float,
    map_dst: Rect | None = None,
    *,
    gap: float = 10.0,
    margin: float = 16.0,
) -> list[Rect]:
    """Stack boxes into columns anchored to the right edge (top to bottom, then left).

    The first columns sit in the gutter beside the map when they fit. Extra
    columns step left and may overlap the map — staff can nudge those by hand.
    """
    if not boxes:
        return []
    top = margin
    bottom = max(margin + 8.0, dest_h - margin)
    placed: list[Rect] = []
    col_left: float | None = None
    y = top
    for box in boxes:
        w = max(8.0, box.w)
        h = max(8.0, box.h)
        if col_left is None:
            col_left = dest_w - margin - w
            y = top
        elif y + h > bottom + 0.5:
            col_left = col_left - gap - w
            y = top
        x = max(margin - w * 0.15, col_left)
        placed.append(Rect(x, y, w, h))
        y += h + gap
    return placed


def _attach_text_style(recipe: dict[str, Any], template_slides: list[dict]) -> dict[str, Any]:
    font, sample = template_list_sample(template_slides)
    if font:
        recipe["listFontSize"] = round(font, 2)
        if sample:
            recipe["listSample"] = sample.as_dict()
    title = template_title_item(template_slides)
    if title:
        recipe["titleDst"] = item_rect(title).as_dict()
        if title.get("size"):
            recipe["titleFontSize"] = round(_f(title.get("size")), 2)
        if title.get("font"):
            recipe["titleFont"] = str(title.get("font") or "")
        title_rgb = item_rgb(title)
        if title_rgb:
            recipe["titleColor"] = [round(c, 4) for c in title_rgb]
    styles = template_character_styles(template_slides)
    if styles:
        recipe["characterStyles"] = styles
    return recipe


def map_rect_from_slide(slide: dict) -> Rect | None:
    maps = [item for item in slide.get("items") or [] if is_map_item(item)]
    if not maps:
        return None
    maps.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    return item_rect(maps[0])




def primary_map_rect(items: Iterable[dict]) -> Rect | None:
    """Largest white/base map piece — the affine origin, not the union of overlays.

    LED panel tiles are excluded even though they are named `map BG.png` and so
    pass is_map_item. A 1920x1080 tile outweighs real map art on area, and taking
    it as the origin puts the whole affine on a backdrop: on one wall deck that
    made the base map (0,0,1920,1080) instead of the Asia art at 1364x947, which
    pushed every pin about 2500px from where the finished CG has it.
    """
    candidates = [it for it in items if is_map_item(it) and not is_chrome_bg(it)]
    large = [
        it
        for it in candidates
        if _f(it.get("w")) >= MAP_LAYER_MIN_W and _f(it.get("h")) >= MAP_LAYER_MIN_H
    ]
    if not large:
        if not candidates:
            return None
        named = sorted(candidates, key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
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


def is_chrome_bg(item: dict) -> bool:
    """LED-panel `map BG.png` tiles (1920×1080). The full-wall map art is not chrome."""
    if not MAP_NAME_RE.search(file_name(item)):
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    return abs(w - CG_WIDTH) <= 80 and abs(h - CG_HEIGHT) <= 80


def is_pairable_image(item: dict) -> bool:
    """Any real image except layout chrome — including huge photos the template cropped."""
    if (item.get("kind") or "") != "image" or is_chrome_bg(item):
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    return w > 0 and h > 0


def is_layout_image(item: dict) -> bool:
    """Images that can be paired wall→template (not full-bleed photo chrome)."""
    if not is_pairable_image(item):
        return False
    w, h = _f(item.get("w")), _f(item.get("h"))
    if w > MAP_LAYER_MAX_W or h > MAP_LAYER_MAX_H:
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


def pair_by_area_rank(
    wall: list[dict],
    dest: list[dict],
    *,
    ar_tolerance: float = 0.15,
) -> list[tuple[dict, dict]]:
    """1:1 by descending area. Survives a template whose artwork was resized.

    `pair_by_size` needs identical dimensions, so it finds nothing the moment the
    template's map is scaled down — which is exactly the edit an operator makes
    to leave room for the name lists. Rank by area instead: the same stack of map
    layers keeps its size order whatever the scale.

    Pairs whose aspect ratios disagree are dropped. A misranked pair would
    otherwise teach a bogus affine, and one bad affine on the base map moves
    every pin that inherits it.
    """
    w_sorted = sorted(wall, key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    d_sorted = sorted(dest, key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
    pairs: list[tuple[dict, dict]] = []
    for item, other in zip(w_sorted, d_sorted, strict=False):
        sw, sh = _f(item.get("w")), _f(item.get("h"))
        dw, dh = _f(other.get("w")), _f(other.get("h"))
        if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
            continue
        src_ar, dst_ar = sw / sh, dw / dh
        if abs(src_ar - dst_ar) / max(src_ar, dst_ar) > ar_tolerance:
            continue
        pairs.append((item, other))
    return pairs


def pairing_quality(pairs: list[tuple[dict, dict]]) -> tuple[int, int]:
    """How much one affine explains a pairing: (largest group, total pairs).

    A pairing that is telling the truth collapses into one dominant affine —
    every map layer moved the same way. A wrong pairing scatters into many small
    groups. This is a better guide than counting matches, because counting
    exact-size matches rewards a template nobody has adjusted.
    """
    if not pairs:
        return (0, 0)
    groups = merge_affine_groups(pairs)
    if not groups:
        return (0, len(pairs))
    return (max(len(g["members"]) for g in groups), len(pairs))


def best_image_pairs(wall: list[dict], dest: list[dict]) -> list[tuple[dict, dict]]:
    """Pair wall artwork to template artwork, whichever way explains it best.

    Exact-size pairing wins ties because identical dimensions are unambiguous;
    area-rank pairing takes over once the template has been scaled.
    """
    exact = pair_by_size(wall, dest)
    exact = exact + pair_resized_leftovers(wall, dest, exact)
    ranked = pair_by_area_rank(wall, dest)
    if pairing_quality(ranked) > pairing_quality(exact):
        return ranked
    return exact


def pair_resized_leftovers(
    wall: list[dict],
    dest: list[dict],
    existing: list[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    """When the template resized one leftover image (e.g. 124×124 globe → 80×80)."""
    used_w = {id(a) for a, _ in existing}
    used_d = {id(b) for _, b in existing}
    w_left = [it for it in wall if id(it) not in used_w]
    d_left = [it for it in dest if id(it) not in used_d]
    if not w_left or not d_left:
        return []
    if len(d_left) != 1:
        return []
    tmpl = d_left[0]
    tw, th = _f(tmpl.get("w")), _f(tmpl.get("h"))
    if tw <= 0 or th <= 0:
        return []
    tmpl_ar = tw / th
    tmpl_area = tw * th

    def score(item: dict) -> float:
        w, h = _f(item.get("w")), _f(item.get("h"))
        if w <= 0 or h <= 0:
            return 1e9
        return abs((w / h) - tmpl_ar) * 10.0 + abs(math.log((w * h) / tmpl_area))

    best = min(w_left, key=score)
    return [(best, tmpl)]


def pair_largest_shapes(wall: list[dict], dest: list[dict]) -> list[tuple[dict, dict]]:
    """Title plates / badges: the largest non-pin shape on each slide."""

    def big(items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for it in items:
            if (it.get("kind") or "") != "shape":
                continue
            w, h = _f(it.get("w")), _f(it.get("h"))
            if w > PIN_KIND_MAX or h > PIN_KIND_MAX:
                out.append(it)
        out.sort(key=lambda it: _f(it.get("w")) * _f(it.get("h")), reverse=True)
        return out

    w_s, d_s = big(wall), big(dest)
    if w_s and d_s:
        return [(w_s[0], d_s[0])]
    return []


def merge_affine_groups(pairs: list[tuple[dict, dict]]) -> list[dict[str, Any]]:
    """Collapse object-pairs that share (s, tx, ty) into layout groups."""
    groups: list[dict[str, Any]] = []
    for src_item, dst_item in pairs:
        aff = affine_from_rects(item_rect(src_item), item_rect(dst_item))
        src = item_rect(src_item)
        t_tol = max(2.0, 0.02 * max(src.w, src.h, 1.0))
        matched = None
        for group in groups:
            if group["affine"].similar(aff, t_tol=t_tol):
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
    """Prefer the CG slide that best explains the wall slide with one transform.

    This used to score exact width/height matches, which quietly punished the
    operator for doing the right thing: scaling the template's map down to leave
    room for the name lists reduced the match count, so a leftover slide holding
    full-size artwork — teaching "translate, don't scale" — could win instead and
    throw away the gutters. Scoring by how well a single affine explains the
    pairing has no such incentive, and treats a scaled template as first class.
    """
    wall_imgs = [it for it in wall_slide.get("items") or [] if is_pairable_image(it)]
    tmpl_imgs = [it for it in template_slide.get("items") or [] if is_pairable_image(it)]
    if wall_imgs and tmpl_imgs:
        dominant, total = pairing_quality(best_image_pairs(wall_imgs, tmpl_imgs))
        if dominant:
            return dominant * 100 + total
    return len([it for it in template_slide.get("items") or [] if is_map_item(it)])


def _framing_fit(
    wall_slide: dict,
    template_slide: dict,
    wall_w: float,
    wall_h: float,
    dest_w: float,
    dest_h: float,
) -> float:
    """How well this framing uses the CG frame: keeps content in, and fills it.

    The same map often appears on several template slides at different framings —
    one showing it whole, another cropping in — and those pair equally well, so
    pairing quality ties and the winner would be whichever was listed first.

    Both halves are needed. Scoring only how much content stays inside the frame
    is maximised by shrinking everything into a corner, which is exactly what
    happened: a small framing scored a perfect 1.0 and won every tie, leaving the
    frame empty. Scoring only how much of the frame is filled would pick a
    framing so large that most of the map hangs off the edge. Multiplying the two
    prefers the framing that shows the whole thing, at a size that uses the space.
    """
    wall_imgs = [
        it
        for it in wall_slide.get("items") or []
        if is_pairable_image(it) and is_visible(it, wall_w, wall_h)
    ]
    tmpl_imgs = [
        it
        for it in template_slide.get("items") or []
        if is_pairable_image(it) and is_visible(it, dest_w, dest_h)
    ]
    if not wall_imgs or not tmpl_imgs:
        return 0.0
    groups = merge_affine_groups(best_image_pairs(wall_imgs, tmpl_imgs))
    if not groups:
        return 0.0
    aff = groups[0]["affine"]
    # Measure the artwork this framing is about, not every visible thing. The
    # whole-slide extent includes the side-panel name lists, which run three
    # times wider than the map and get relocated anyway — so judging by it
    # punished the framing that keeps the map at true size and rewarded one that
    # shrank the map until the side panels fitted too.
    src = union_rect_of([item_rect(a) for a, _ in groups[0]["members"]])
    if src is None or src.w <= 0 or src.h <= 0:
        return 0.0
    mapped = aff.apply_rect(src)
    if mapped.w <= 0 or mapped.h <= 0 or dest_w <= 0 or dest_h <= 0:
        return 0.0
    x0 = max(0.0, mapped.x)
    y0 = max(0.0, mapped.y)
    x1 = min(dest_w, mapped.x + mapped.w)
    y1 = min(dest_h, mapped.y + mapped.h)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    visible = (x1 - x0) * (y1 - y0)
    kept = visible / (mapped.w * mapped.h)
    fills = min(1.0, visible / (dest_w * dest_h))
    return kept * fills


def _best_matching_slide(
    wall_slide: dict | None,
    candidates: list[dict],
    *,
    wall_size: tuple[float, float] | None = None,
    dest_size: tuple[float, float] | None = None,
) -> dict | None:
    if not wall_slide:
        return _first_slide_with(candidates, is_map_item) or _first_slide_with(
            candidates, is_pin_item
        )
    best: dict | None = None
    best_key: tuple[int, float] | None = None
    for slide in candidates:
        score = _score_template_slide(wall_slide, slide)
        fit = 0.0
        if wall_size and dest_size and score > 0:
            fit = _framing_fit(wall_slide, slide, *wall_size, *dest_size)
        # Rank on how many objects agreed, not on the raw score: that also
        # carries a pair total, and a one-pair difference used to outrank a fit
        # two and a half times better. Agreement is the real signal; how well the
        # framing uses the frame settles everything within one level of it.
        key = (score // 100, fit)
        if best_key is None or key > best_key:
            best_key = key
            best = slide
    if best is not None and best_key and _score_template_slide(wall_slide, best) > 0:
        return best
    return _first_slide_with(candidates, is_map_item) or _first_slide_with(
        candidates, is_pin_item
    )


def _slide_number_of(slide: dict) -> int:
    return int(slide.get("number") or (int(slide.get("index") or 0) + 1))


def rank_framing_candidates(
    wall_slide: dict,
    template_slides: list[dict],
    *,
    wall_size: tuple[float, float],
    dest_size: tuple[float, float],
) -> list[dict[str, Any]]:
    """Every template framing this wall slide could use, best first.

    The same ranking `_best_matching_slide` applies, exposed so the operator can
    be shown the runners-up and pick one. Which crop of a map is wanted is an
    editorial choice the geometry cannot express, so the point is to offer the
    alternatives rather than to add another metric.
    """
    rows: list[dict[str, Any]] = []
    for slide in template_slides:
        score = _score_template_slide(wall_slide, slide)
        fit = (
            _framing_fit(wall_slide, slide, *wall_size, *dest_size)
            if score > 0
            else 0.0
        )
        rows.append(
            {
                "templateSlide": _slide_number_of(slide),
                "name": str(slide.get("master") or ""),
                # Agreement level is the real signal; fit only settles ties within
                # one level of it. Both are shown so a close call reads as close.
                "agreement": score // 100,
                "pairTotal": score % 100,
                "fit": round(fit, 4),
            }
        )
    rows.sort(key=lambda r: (r["agreement"], r["fit"]), reverse=True)
    for row in rows:
        row["autoPick"] = False
    if rows and rows[0]["agreement"] > 0:
        rows[0]["autoPick"] = True
    return rows


def learn_recipe(
    wall: dict, template: dict, *, template_slide: int | None = None
) -> dict[str, Any]:
    """Fit map rects from a 16:9 CG template inspect payload.

    `template_slide` pins the framing to that template slide number, skipping the
    automatic choice. An unknown number falls back to choosing automatically
    rather than failing, so a stale confirmation cannot break a run.
    """
    dest_w = int(template.get("slideWidth") or CG_WIDTH)
    dest_h = int(template.get("slideHeight") or CG_HEIGHT)
    wall_slides = wall.get("slides") or []
    template_slides = template.get("slides") or []
    if len(wall_slides) == 1:
        w_slide = wall_slides[0]
    else:
        w_slide = _first_slide_with(wall_slides, is_map_item) or _first_slide_with(
            wall_slides, is_pin_item
        )
    g_slide = None
    if template_slide is not None:
        g_slide = next(
            (s for s in template_slides if _slide_number_of(s) == int(template_slide)),
            None,
        )
    pinned = g_slide is not None
    if g_slide is None:
        g_slide = _best_matching_slide(
            w_slide,
            template_slides,
            wall_size=(_f(wall.get("slideWidth"), 7680), _f(wall.get("slideHeight"), 1080)),
            dest_size=(float(dest_w), float(dest_h)),
        )
    map_src = None
    map_dst = None
    list_src = None
    list_dst = None
    list_paired = False
    pin_pairs_n = 0
    pin_rmse = None
    pin_size_scale = None
    grouped: list[dict[str, Any]] = []
    if w_slide and g_slide:
        wall_w = _f(wall.get("slideWidth"), 7680)
        wall_h = _f(wall.get("slideHeight"), 1080)
        # An off-slide leftover must never teach an affine: it is invisible, so
        # its position says nothing about where visible art should land.
        w_items = [it for it in w_slide.get("items") or [] if is_visible(it, wall_w, wall_h)]
        g_items = [it for it in g_slide.get("items") or [] if is_visible(it, dest_w, dest_h)]
        w_imgs = [it for it in w_items if is_pairable_image(it)]
        g_imgs = [it for it in g_items if is_pairable_image(it)]
        size_pairs = list(best_image_pairs(w_imgs, g_imgs))
        size_pairs.extend(pair_largest_shapes(w_items, g_items))
        size_pairs = uniform_pairs(size_pairs)
        grouped = merge_affine_groups(size_pairs) if size_pairs else []
        grouped = drop_outlier_groups(grouped)
        if grouped:
            biggest = grouped[0]["members"][0]
            map_src = effective_wall_map_src(wall, item_rect(biggest[0]))
            raw_dst = item_rect(biggest[1])
            map_dst = map_dst_for_cg(map_src, raw_dst, dest_w, dest_h)
            # Cover replaces the template box; keep a single group with that affine.
            if abs(map_dst.w - raw_dst.w) > 80 or abs(map_dst.x - raw_dst.x) > 80:
                grouped[0] = {
                    "affine": affine_from_rects(map_src, map_dst),
                    "src": map_src,
                    "dst": map_dst,
                    "members": grouped[0]["members"],
                }
        else:
            w_maps = [it for it in w_items if is_map_item(it)]
            g_maps = [it for it in g_items if is_map_item(it)]
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
            w_pins = [it for it in w_items if is_pin_item(it)]
            g_pins = [it for it in g_items if is_pin_item(it)]
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
            w_list = [it for it in w_items if is_list_item(it)]
            g_list = [it for it in g_items if is_list_item(it)]
            named = pair_list(w_list, g_list)
            list_paired = bool(named)
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
        # Carry the provenance even though no template framing was usable. A pin
        # that was applied and then found unbuildable is a different answer from a
        # pin that was ignored, and only the first tells the operator that this
        # template slide cannot frame this page.
        recipe["templateSlide"] = _slide_number_of(g_slide) if g_slide else None
        recipe["framingPinned"] = pinned
        recipe["pairQuality"] = 0
        recipe["groups"] = [
            {
                **affine_from_rects(map_src, _rect_from_dict(recipe["mapDst"]) or map_src).as_dict(),
                "src": map_src.as_dict(),
                "dst": recipe["mapDst"],
                "members": 0,
            }
        ]
        return _attach_text_style(recipe, template_slides)
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
        # How many objects agreed on one affine. Low means no template slide
        # describes this page, and the caller should fall back to fitting.
        "pairQuality": max((len(g["members"]) for g in grouped), default=0),
        # Which template slide taught this. Worth surfacing: picking the wrong
        # framing looks like a geometry bug until you can see the choice.
        "templateSlide": (_slide_number_of(g_slide) if g_slide else None),
        # True only when a requested framing was actually found. A stale
        # confirmation naming a slide the template no longer has falls back to
        # choosing automatically, and must not report itself as honoured.
        "framingPinned": pinned,
    }
    if list_src and list_dst and list_src.w > 1 and list_src.h > 1:
        recipe["listSrc"] = list_src.as_dict()
        recipe["listDst"] = list_dst.as_dict()
    if list_paired:
        recipe["listPaired"] = True
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
    return _attach_text_style(recipe, template_slides)


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


OUTLIER_SCALE_FACTOR = 2.0
# A pair may differ this much between its width and height scale and still count
# as the same artwork uniformly resized.
PAIR_UNIFORM_TOLERANCE = 0.05


def uniform_pairs(
    pairs: Iterable[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    """Keep only pairs that one uniform scale can actually explain.

    `Affine` is a uniform scale, so a pair whose width ratio and height ratio
    disagree cannot be represented by it: `affine_from_rects` takes the width and
    gets the other axis wrong. On a missions map a 634x425 layer paired with a
    473x364 one gave sx=0.746 against sy=0.856, and the layer was placed at 87% of
    the height the rest of the map used — the white base map and the orange country
    fill ended up at different sizes on the same slide.

    A mismatched pair says the two objects are not the same artwork, or that one is
    cropped differently, and neither can teach a transform.
    """
    kept: list[tuple[dict, dict]] = []
    for src_item, dst_item in pairs:
        src = item_rect(src_item)
        dst = item_rect(dst_item)
        if src.w <= 0 or src.h <= 0:
            continue
        sx = dst.w / src.w
        sy = dst.h / src.h
        if sy <= 0 or sx <= 0:
            continue
        if abs(sx - sy) / max(sx, sy) <= PAIR_UNIFORM_TOLERANCE:
            kept.append((src_item, dst_item))
    return kept


def drop_outlier_groups(grouped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Discard clusters whose scale no other object agrees with.

    Map layers all inspect as `pasted-image.pdf`, so pairing matches on size alone
    and sometimes matches a layer to something unrelated: on a missions map a
    306x316 layer paired with an 80x80 template item (s=0.2532) and a 306x295 with
    an 11x11 one (s=0.0359), against a consensus of 0.8547 that three objects
    agreed on. Any object landing in those clusters is destroyed — the 0.0359 one
    shrank Australia to 3.6% of its size, so it vanished from the CG.

    Only outliers are dropped, and only when there is a consensus to judge them
    against: with every cluster holding one object there is nothing to prefer, so
    the list is left alone. Objects that lose their cluster fall back to the
    nearest surviving one, which is the consensus affine.
    """
    if len(grouped) < 2:
        return grouped
    dominant = max(grouped, key=lambda g: len(g["members"]))
    if len(dominant["members"]) < 2:
        return grouped
    scale = dominant["affine"].s
    if scale <= 0:
        return grouped
    kept: list[dict[str, Any]] = []
    dropped: list[float] = []
    for group in grouped:
        ratio = group["affine"].s / scale
        if group is dominant or 1 / OUTLIER_SCALE_FACTOR <= ratio <= OUTLIER_SCALE_FACTOR:
            kept.append(group)
        else:
            dropped.append(round(group["affine"].s, 4))
    return kept


def _group_for_item(
    item: dict, groups: list[tuple[Affine, Rect]]
) -> tuple[Affine | None, Rect | None]:
    """The cluster this object belongs to: nearest by centre, then the smallest
    cluster big enough to hold it.

    Ranking ties purely by smallest area let an overlay capture the artwork it sits
    on: on a missions map, a 306x316 overlay and the 1248x771 map both contained
    the map's own centre, so the map was placed with the overlay's affine at
    s=0.2532 instead of its own s=0.8547 — 316px wide instead of 1067px, and
    pushed off the left edge. A cluster smaller than the object cannot be the
    cluster that object belongs to. Preferring clusters that can hold it keeps the
    behaviour that matters for pins, where the smallest containing cluster is the
    inset a pin sits in rather than the whole map.
    """
    if not groups:
        return None, None
    rect = item_rect(item)
    cx, cy = rect.center()
    item_area = max(rect.w * rect.h, 1.0)
    best: tuple[Affine, Rect] | None = None
    best_key: tuple[float, float, float] | None = None
    for aff, src in groups:
        d = dist_to_rect(cx, cy, src)
        area = max(src.w * src.h, 1.0)
        too_small = 0 if area >= item_area else 1
        key = (d, too_small, area)
        if best_key is None or key < best_key:
            best_key = key
            best = (aff, src)
    return best if best else (None, None)


def _affine_for_item(item: dict, groups: list[tuple[Affine, Rect]]) -> Affine | None:
    return _group_for_item(item, groups)[0]


def _groups_for_slide(slide: dict, recipe: dict[str, Any]) -> list[tuple[Affine, Rect]]:
    """Layout affines from the recipe. The badge is not one of them."""
    return list(_groups_from_recipe(recipe))


def _title_badge(
    slide: dict, recipe: dict[str, Any]
) -> tuple[Affine | None, Rect | None, set[int]]:
    """Globe, plate and title text that share the title's vertical centre.

    Returns identity ids (`id(item)`) so membership does not collide when two
    inspect records share `index` 0, which tests and some payloads do.
    """
    title = next((it for it in slide.get("items") or [] if is_title_item(it)), None)
    dst = _rect_from_dict(recipe.get("titleDst"))
    if title is None or dst is None or dst.w <= 0:
        return None, None, set()
    src = item_rect(title)
    members = [title]
    ids: set[int] = {id(title)}
    for item in slide.get("items") or []:
        if item is title or is_map_item(item) or is_pin_item(item) or is_placeholder_text(item):
            continue
        cx, cy = item_center(item)
        if point_in_rect(cx, cy, src, TITLE_NEAR_PAD):
            members.append(item)
            ids.add(id(item))
    aff = affine_from_rects(src, dst)
    # region agent log
    _dbg(
        "H18",
        "map_remap.py:_title_badge",
        "title cluster members",
        {
            "title": {
                "text": (title.get("text") or "")[:40],
                "rect": {"x": round(src.x, 1), "y": round(src.y, 1), "w": round(src.w, 1), "h": round(src.h, 1)},
            },
            "titleDst": {"x": round(dst.x, 1), "y": round(dst.y, 1), "w": round(dst.w, 1), "h": round(dst.h, 1)},
            "members": [
                {
                    "kind": it.get("kind"),
                    "idx": it.get("index"),
                    "x": round(_f(it.get("x")), 1),
                    "y": round(_f(it.get("y")), 1),
                    "w": round(_f(it.get("w")), 1),
                    "h": round(_f(it.get("h")), 1),
                }
                for it in members
            ],
        },
    )
    # endregion
    return aff, src, ids


def classify_item(item: dict, map_src: Rect | None = None) -> str:
    if (item.get("kind") or "") == "line":
        return "line"
    if is_map_item(item, map_src):
        return "map"
    if is_pin_item(item, map_src):
        return "pin"
    if is_title_item(item):
        return "title"
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


def _style_text_box(
    item: dict,
    aff: Affine | None,
    style: dict[str, Any] | None,
) -> tuple[Rect, float | None, str | None, tuple[float, float, float] | None]:
    src = item_rect(item)
    wall_font = _f(item.get("size"))
    dst_size = _f(style.get("size")) if style else 0.0
    font_name = (str(style.get("font") or "") or None) if style else None
    colour = norm_rgb(style.get("color")) if style else None
    snippet = (item.get("text") or "").replace("\n", " ")[:48]
    interesting = bool(
        re.search(
            r"global|missions|oct|183|269|total|churches|countries",
            snippet,
            re.I,
        )
    )
    if style and dst_size > 0 and wall_font > 0:
        ratio = dst_size / wall_font
        if aff is not None:
            origin = aff.apply_rect(Rect(src.x, src.y, 1.0, 1.0))
            mapped = Rect(origin.x, origin.y, max(8.0, src.w * ratio), max(8.0, src.h * ratio))
        else:
            mapped = Rect(src.x, src.y, max(8.0, src.w * ratio), max(8.0, src.h * ratio))
        # region agent log
        if interesting:
            _dbg(
                "H15",
                "map_remap.py:_style_text_box",
                "styled branch",
                {
                    "text": snippet,
                    "path": "styled",
                    "affS": round(aff.s, 4) if aff else None,
                    "ratio": round(ratio, 4),
                    "wallFont": round(wall_font, 2),
                    "dstSize": round(dst_size, 2),
                    "src": {"x": round(src.x, 1), "y": round(src.y, 1), "w": round(src.w, 1), "h": round(src.h, 1)},
                    "mapped": {"x": round(mapped.x, 1), "y": round(mapped.y, 1), "w": round(mapped.w, 1), "h": round(mapped.h, 1)},
                },
            )
        # endregion
        return mapped, dst_size, font_name, colour
    if aff is not None:
        origin = aff.apply_rect(Rect(src.x, src.y, 1.0, 1.0))
        scale = min(aff.s, TEXT_DOWN_SCALE)
        mapped = Rect(origin.x, origin.y, max(8.0, src.w * scale), max(8.0, src.h * scale))
        font = max(8.0, wall_font * scale) if wall_font else None
        # region agent log
        if interesting:
            _dbg(
                "H15",
                "map_remap.py:_style_text_box",
                "clamp branch",
                {
                    "text": snippet,
                    "path": "clamp",
                    "affS": round(aff.s, 4),
                    "clamp": TEXT_DOWN_SCALE,
                    "scaleUsed": round(scale, 4),
                    "clampBound": aff.s > TEXT_DOWN_SCALE,
                    "wallFont": round(wall_font, 2),
                    "fontOut": round(font, 2) if font else None,
                    "src": {"x": round(src.x, 1), "y": round(src.y, 1), "w": round(src.w, 1), "h": round(src.h, 1)},
                    "mapped": {"x": round(mapped.x, 1), "y": round(mapped.y, 1), "w": round(mapped.w, 1), "h": round(mapped.h, 1)},
                    "hadStyle": bool(style),
                },
            )
        # endregion
        return mapped, font, font_name, colour
    # region agent log
    if interesting:
        _dbg(
            "H15",
            "map_remap.py:_style_text_box",
            "passthrough branch",
            {
                "text": snippet,
                "path": "passthrough",
                "hadStyle": bool(style),
                "wallFont": round(wall_font, 2),
                "src": {"x": round(src.x, 1), "y": round(src.y, 1), "w": round(src.w, 1), "h": round(src.h, 1)},
            },
        )
    # endregion
    return src, (wall_font or None), font_name, colour


def _pack_list_transforms(transforms: list[ItemTransform], recipe: dict[str, Any]) -> None:
    lists = [t for t in transforms if t.role == "list"]
    if not lists:
        return
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    order = sorted(range(len(lists)), key=lambda i: (-lists[i].x, lists[i].y))
    boxes = [Rect(lists[i].x, lists[i].y, lists[i].w, lists[i].h) for i in order]
    placed = pack_columns_from_right(boxes, dest_w, dest_h, map_dst)
    for idx, rect in zip(order, placed, strict=True):
        lists[idx].x = rect.x
        lists[idx].y = rect.y
        lists[idx].w = rect.w
        lists[idx].h = rect.h


def plan_slide_transforms(
    slide: dict,
    recipe: dict[str, Any],
    *,
    include_lists: bool = False,
    wall_size: tuple[float, float] | None = None,
    defer_list_packing: bool = False,
    free_text_keys: set[tuple[str, int]] | None = None,
) -> list[ItemTransform]:
    groups = _groups_for_slide(slide, recipe)
    title_aff, title_src, title_ids = _title_badge(slide, recipe)
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    if not groups and (map_src is None or map_dst is None):
        return []
    number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
    styles = list(recipe.get("characterStyles") or [])
    # Blind right-to-left packing moves every list box, including labels that
    # belong to artwork. A map label dragged into a column at the frame edge
    # leaves its red plate behind on the map and reads as a bug in the deck, so
    # when a rendered slide is available the placement decision is deferred to
    # repack_free_text, which can tell a free-floating column from a label.
    pack_lists = bool(
        include_lists
        and not defer_list_packing
        and recipe.get("listFontSize")
        and slide_has_column_lists(slide)
    )
    from obed_edom.inspect import is_duplicate_item  # noqa: PLC0415

    out: list[ItemTransform] = []
    wall_w, wall_h = wall_size or (0.0, 0.0)
    list_count = sum(1 for it in slide.get("items") or [] if is_list_item(it))
    # region agent log
    _text_rows: list[dict[str, Any]] = []
    # endregion
    for fallback_i, item in enumerate(slide.get("items") or []):
        if is_placeholder_text(item) or is_duplicate_item(item):
            continue
        # Off-slide leftovers are invisible on the wall, and the affine would
        # drag some of them into the CG frame.
        if wall_size and not is_visible(item, wall_w, wall_h):
            continue
        item_index = _item_index(item, fallback_i)
        kind_index = _item_kind_index(item, item_index)
        if is_chrome_bg(item):
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "image"),
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
        # Classify against the cluster this object actually sits in. Using the
        # first group instead loses every pin belonging to a second map on the
        # same slide — on a report-card page with two country insets that dropped
        # 9 of 10 pins, because they were 700px from the group that happened to
        # be listed first.
        aff, cluster = _group_for_item(item, groups)
        if title_aff is not None and id(item) in title_ids:
            aff, cluster = title_aff, title_src
        if cluster is None:
            cluster = map_src
        role = classify_item(item, cluster)
        if role == "other" and aff is not None and is_layout_image(item):
            role = "map"
        if role == "other" and aff is None and (item.get("kind") or "") != "text":
            continue
        # Leaving the lists out means dropping side-panel name columns, never
        # blanking the labels on the map: both look like lists to is_list_item,
        # and hiding a label leaves its plate behind with no name on it. When a
        # rendered slide told us which is which, honour that; blind, keep the
        # old behaviour of dropping them all, since the flag is an explicit
        # instruction and the operator can see the result.
        loose = free_text_keys is None or (str(item.get("kind") or "text"), kind_index) in free_text_keys
        if role == "list" and not include_lists and loose:
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
        if role == "title":
            dst = _rect_from_dict(recipe.get("titleDst"))
            if dst is None:
                continue
            # region agent log
            _src = item_rect(item)
            _text_rows.append(
                {
                    "path": "title",
                    "role": "title",
                    "text": (item.get("text") or "").replace("\n", " ")[:48],
                    "src": {"x": round(_src.x, 1), "y": round(_src.y, 1), "w": round(_src.w, 1), "h": round(_src.h, 1)},
                    "mapped": {"x": round(dst.x, 1), "y": round(dst.y, 1), "w": round(dst.w, 1), "h": round(dst.h, 1)},
                    "affS": round(aff.s, 4) if aff else None,
                    "font": recipe.get("titleFontSize"),
                }
            )
            # endregion
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "text"),
                    x=dst.x,
                    y=dst.y,
                    w=dst.w,
                    h=dst.h,
                    locked=bool(item.get("locked")),
                    font_size=(
                        float(recipe["titleFontSize"])
                        if recipe.get("titleFontSize")
                        else (_f(item.get("size")) or None)
                    ),
                    font=str(recipe["titleFont"]) if recipe.get("titleFont") else None,
                    color=norm_rgb(recipe.get("titleColor")),
                    role="title",
                    kind_index=kind_index,
                )
            )
            continue
        # Snapping to the template's list destination only makes sense for a
        # single column. With fifteen map labels it puts all fifteen on the same
        # point, which the old blind packing then spread out again and so hid.
        if role == "list" and include_lists and recipe.get("listPaired") and list_count == 1:
            dst = _rect_from_dict(recipe.get("listDst"))
            style = match_character_style(item, styles)
            size_only = {"size": recipe.get("listFontSize")} if recipe.get("listFontSize") else None
            mapped, font, font_name, colour = _style_text_box(item, None, style or size_only)
            if not style:
                font_name, colour = None, None
            if dst is not None:
                mapped = Rect(dst.x, dst.y, mapped.w, mapped.h)
            # region agent log
            _text_rows.append(
                {
                    "path": "listDst",
                    "role": "list",
                    "text": (item.get("text") or "").replace("\n", " ")[:48],
                    "mapped": {"x": round(mapped.x, 1), "y": round(mapped.y, 1), "w": round(mapped.w, 1), "h": round(mapped.h, 1)},
                    "snapped": dst is not None,
                    "listCount": list_count,
                    "style": (style or {}).get("size") if style else None,
                }
            )
            # endregion
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "text"),
                    x=mapped.x,
                    y=mapped.y,
                    w=mapped.w,
                    h=mapped.h,
                    locked=bool(item.get("locked")),
                    font_size=font,
                    font=font_name,
                    color=colour,
                    role="list",
                    kind_index=kind_index,
                )
            )
            continue
        if role == "list" and pack_lists:
            src = item_rect(item)
            wall_font = _f(item.get("size"))
            style = match_character_style(item, styles)
            font_dst = _f(style.get("size")) if style else 0.0
            if not font_dst:
                font_dst = _f(recipe.get("listFontSize"))
            if font_dst and wall_font > 0:
                ratio = font_dst / wall_font
                mapped = Rect(src.x, src.y, max(8.0, src.w * ratio), max(8.0, src.h * ratio))
                font: float | None = font_dst
            elif aff is not None:
                mapped = aff.apply_rect(src)
                font = max(8.0, wall_font * aff.s) if wall_font else None
            elif map_src and map_dst:
                mapped = map_rect(src, map_src, map_dst)
                font = (
                    max(8.0, wall_font * (map_dst.h / map_src.h))
                    if wall_font and map_src.h
                    else None
                )
            else:
                continue
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "text"),
                    x=mapped.x,
                    y=mapped.y,
                    w=mapped.w,
                    h=mapped.h,
                    locked=bool(item.get("locked")),
                    font_size=font,
                    font=(style.get("font") or None) if style else None,
                    color=norm_rgb(style.get("color")) if style else None,
                    role="list",
                    kind_index=kind_index,
                )
            )
            continue
        if role in {"list", "other"} and (item.get("kind") or "") == "text":
            style = match_character_style(item, styles)
            mapped, font, font_name, colour = _style_text_box(item, aff, style)
            # region agent log
            _text_rows.append(
                {
                    "path": "style_text",
                    "role": role,
                    "text": (item.get("text") or "").replace("\n", " ")[:48],
                    "src": {
                        "x": round(_f(item.get("x")), 1),
                        "y": round(_f(item.get("y")), 1),
                        "w": round(_f(item.get("w")), 1),
                        "h": round(_f(item.get("h")), 1),
                    },
                    "mapped": {"x": round(mapped.x, 1), "y": round(mapped.y, 1), "w": round(mapped.w, 1), "h": round(mapped.h, 1)},
                    "affS": round(aff.s, 4) if aff else None,
                    "styleMatched": bool(style),
                    "styleSize": _f(style.get("size")) if style else None,
                    "wallFont": _f(item.get("size")),
                    "fontOut": font,
                    "fontName": font_name,
                }
            )
            # endregion
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind="text",
                    x=mapped.x,
                    y=mapped.y,
                    w=mapped.w,
                    h=mapped.h,
                    locked=bool(item.get("locked")),
                    font_size=font,
                    font=font_name,
                    color=colour,
                    role="other" if role == "other" else "list",
                    kind_index=kind_index,
                )
            )
            continue
        if aff is None and map_src and map_dst:
            mapped = map_rect(item_rect(item), map_src, map_dst)
        elif aff is not None:
            mapped = aff.apply_rect(item_rect(item))
        else:
            continue
        # Left-column infographics sit beside the wall map, so the map affine
        # throws them off the CG's left edge (x≈-900). Shift them onto the
        # canvas rather than leaving them invisible or parking them on the badge.
        # Setting the affine-scaled w/h on a group does not scale its children:
        # Keynote keeps wall-sized text/logo/rules, so the box clips (missing
        # CHC logo, short inner rule, truncated date, overflow +). Restore the
        # wall size and only move the group. Pins stay affine-scaled.
        if str(item.get("kind") or "") == "group" and role == "other":
            src_box = item_rect(item)
            mapped = Rect(
                16.0 if mapped.x < 16 else mapped.x,
                mapped.y,
                src_box.w,
                src_box.h,
            )
        # region agent log
        if str(item.get("kind") or "") == "group":
            _dbg(
                "H18",
                "map_remap.py:plan_slide_transforms",
                "group placement",
                {
                    "idx": item_index,
                    "src": {
                        "x": round(_f(item.get("x")), 1),
                        "y": round(_f(item.get("y")), 1),
                        "w": round(_f(item.get("w")), 1),
                        "h": round(_f(item.get("h")), 1),
                    },
                    "mapped": {
                        "x": round(mapped.x, 1),
                        "y": round(mapped.y, 1),
                        "w": round(mapped.w, 1),
                        "h": round(mapped.h, 1),
                    },
                    "affS": round(aff.s, 4) if aff else None,
                    "role": role,
                    "runId": "post-fix",
                },
            )
        # endregion
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
        # The map affine parks gutter meridians at x≈-386. Leaving them unplanned
        # used to keep the 7680→1920 leftover (~164px). Translate back onto the
        # x the document scale already chose (on the map) and keep affine y/length.
        dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
        if (
            start is not None
            and end is not None
            and (max(start[0], end[0]) <= 0 or min(start[0], end[0]) >= dest_w)
        ):
            doc_s = (dest_w / wall_w) if wall_w > 0 else 1.0
            x_keep = _f((item.get("start") or [item.get("x")])[0]) * doc_s
            start = (x_keep, start[1])
            end = (x_keep, end[1])
            mapped = Rect(
                min(start[0], end[0]),
                min(start[1], end[1]),
                abs(end[0] - start[0]),
                abs(end[1] - start[1]),
            )
        # region agent log
        if role == "line":
            _dbg(
                "H22",
                "map_remap.py:plan_slide_transforms",
                "line placement",
                {
                    "idx": item_index,
                    "src": {
                        "x": round(_f(item.get("x")), 1),
                        "y": round(_f(item.get("y")), 1),
                        "w": round(_f(item.get("w")), 1),
                        "h": round(_f(item.get("h")), 1),
                    },
                    "mapped": {
                        "x": round(mapped.x, 1),
                        "y": round(mapped.y, 1),
                        "w": round(mapped.w, 1),
                        "h": round(mapped.h, 1),
                    },
                    "start": [round(start[0], 1), round(start[1], 1)] if start else None,
                    "end": [round(end[0], 1), round(end[1], 1)] if end else None,
                    "affS": round(aff.s, 4) if aff else None,
                    "runId": "post-fix",
                },
            )
        # endregion
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
                start=start,
                end=end,
                role=role,
                kind_index=kind_index,
            )
        )
    if pack_lists:
        _pack_list_transforms(out, recipe)
    # Apply order *is* stacking order, and the wall's real stacking cannot be
    # read (see inspect_keynote.js: slide.iWorkItems() reports 0). So this sort
    # is the stacking policy, not a reconstruction: base maps first and largest
    # first, so country overlays land on top of the plate they belong to, then
    # pins, then loose text, with the title cluster last so it is never buried.
    role_order = {"map": 0, "pin": 1, "other": 2, "list": 3, "hide": 4, "line": 5, "title": 6}
    out.sort(
        key=lambda t: (
            role_order.get(t.role, 9),
            -(t.w * t.h) if t.role == "map" else 0.0,
        )
    )
    # region agent log
    if number == 4:
        text_final = [
            {
                "role": t.role,
                "kind": t.kind,
                "x": round(t.x, 1),
                "y": round(t.y, 1),
                "w": round(t.w, 1),
                "h": round(t.h, 1),
                "font": t.font_size,
                "idx": t.item_index,
            }
            for t in out
            if t.kind == "text" or t.role in {"title", "list"}
        ]
        extras = [
            {
                "role": t.role,
                "kind": t.kind,
                "idx": t.item_index,
                "ki": t.kind_index,
                "x": round(t.x, 1),
                "y": round(t.y, 1),
                "w": round(t.w, 1),
                "h": round(t.h, 1),
                "start": [round(t.start[0], 1), round(t.start[1], 1)] if t.start else None,
                "end": [round(t.end[0], 1), round(t.end[1], 1)] if t.end else None,
                "payloadWH": t.role in {"map", "list", "pin", "title", "other"},
            }
            for t in out
            if t.kind in {"line", "group"} or (t.kind == "image" and t.item_index == 3)
        ]
        _dbg(
            "H22",
            "map_remap.py:plan_slide_transforms",
            "slide 4 text plan",
            {
                "include_lists": include_lists,
                "pack_lists": pack_lists,
                "list_count": list_count,
                "titleDst": recipe.get("titleDst"),
                "titleFontSize": recipe.get("titleFontSize"),
                "styleCount": len(styles),
                "rows": _text_rows,
                "final": text_final,
                "extras": extras,
            },
        )
    # endregion
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


_SLIDE_PART = re.compile(r"^(\d+)(?:\s*[-–—]\s*(\d+))?$")

SlideRange = frozenset[int] | tuple[int, int] | None


def expand_slide_range(slide_range: SlideRange) -> frozenset[int] | None:
    if slide_range is None:
        return None
    if isinstance(slide_range, tuple):
        lo, hi = int(slide_range[0]), int(slide_range[1])
        return frozenset(range(lo, hi + 1))
    return frozenset(int(n) for n in slide_range)


def wants_slide(number: int, slide_range: SlideRange) -> bool:
    selected = expand_slide_range(slide_range)
    return True if selected is None else number in selected


def slides_for_plan(slide_range: SlideRange) -> list[int] | None:
    selected = expand_slide_range(slide_range)
    return None if selected is None else sorted(selected)


def format_slide_range(slide_range: SlideRange) -> str:
    """`{2,4,5,6}` → `2, 4–6`. No selection → `""`, meaning the whole deck.

    Takes the same SlideRange as the other helpers, None included. It used to
    require an iterable, which was fine only while a slide always defaulted to 2.
    """
    if slide_range is None:
        return ""
    if isinstance(slide_range, tuple) and len(slide_range) == 2:
        nums = expand_slide_range(slide_range) or frozenset()
    else:
        nums = frozenset(int(n) for n in slide_range)
    ordered = sorted(nums)
    if not ordered:
        return ""
    parts: list[str] = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}–{prev}")
    return ", ".join(parts)


def parse_slide_spec(
    raw: str | None,
    *,
    default: frozenset[int] | tuple[int, int] | None = None,
) -> frozenset[int] | None:
    """`2, 4-6` → {2, 4, 5, 6}. Blank → `default`."""
    if raw is None or not str(raw).strip():
        return expand_slide_range(default) if isinstance(default, tuple) else default
    out: set[int] = set()
    for chunk in str(raw).split(","):
        token = chunk.strip()
        if not token:
            continue
        match = _SLIDE_PART.match(token)
        if not match:
            raise ValueError(f"Invalid slide range {raw!r}")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < start:
            raise ValueError(f"Invalid slide range {token!r}")
        out.update(range(start, end + 1))
    if not out:
        return expand_slide_range(default) if isinstance(default, tuple) else default
    return frozenset(out)


def resolve_slides(
    *,
    spec: str | None = None,
    range_from: int | None = None,
    range_to: int | None = None,
    default: frozenset[int] | tuple[int, int] | None = None,
) -> frozenset[int] | None:
    if spec and str(spec).strip():
        return parse_slide_spec(spec)
    bounds = resolve_slide_range(range_from, range_to)
    if bounds is not None:
        return expand_slide_range(bounds)
    return expand_slide_range(default) if isinstance(default, tuple) else default


# Shared map + pins across duplicated wall slides; below this, remap from scratch.
REUSE_MIN_PERSIST = 40


def item_content_key(item: dict) -> tuple[Any, ...]:
    """Pre-transform identity including geometry (unchanged map/dots match)."""
    kind = str(item.get("kind") or "")
    x = round(_f(item.get("x")))
    y = round(_f(item.get("y")))
    w = round(_f(item.get("w")))
    h = round(_f(item.get("h")))
    if kind == "image":
        return (kind, file_name(item), w, h, x, y)
    if kind == "text":
        return (kind, (item.get("text") or "").strip(), round(_f(item.get("size"))), w, h, x, y)
    if kind == "movie":
        return (kind, file_name(item), w, h, x, y)
    return (kind, w, h, x, y)


def item_identity(item: dict) -> tuple[Any, ...]:
    """Identity that survives a size/position tweak (same church name, new point size)."""
    kind = str(item.get("kind") or "")
    if kind == "text":
        return ("text", (item.get("text") or "").strip())
    if kind == "image":
        return (
            "image",
            file_name(item),
            round(_f(item.get("w"))),
            round(_f(item.get("h"))),
            round(_f(item.get("x"))),
            round(_f(item.get("y"))),
        )
    if kind == "movie":
        return ("movie", file_name(item), round(_f(item.get("w"))), round(_f(item.get("h"))))
    return (kind, round(_f(item.get("w"))), round(_f(item.get("h"))), round(_f(item.get("x"))), round(_f(item.get("y"))))


def _live_items(slide: dict) -> list[dict]:
    from obed_edom.inspect import is_duplicate_item  # noqa: PLC0415

    counts: dict[str, int] = {}
    out: list[dict] = []
    for i, item in enumerate(slide.get("items") or []):
        if is_placeholder_text(item) or is_duplicate_item(item):
            continue
        rec = dict(item)
        kind = str(rec.get("kind") or "")
        if rec.get("kindIndex") is None:
            rec["kindIndex"] = counts.get(kind, 0)
        counts[kind] = max(counts.get(kind, 0), int(rec["kindIndex"]) + 1)
        rec["_index"] = i
        out.append(rec)
    return out


def _ref(item: dict) -> dict[str, Any]:
    return {
        "kind": str(item.get("kind") or "item"),
        "kindIndex": int(item.get("kindIndex") or 0),
        "itemIndex": int(item.get("index") if item.get("index") is not None else item.get("_index") or 0),
    }


def _spec_key(spec: ItemTransform) -> tuple[str, int]:
    return (str(spec.kind), int(spec.kind_index if spec.kind_index is not None else spec.item_index))


def plan_slide_reuses(
    payload: dict[str, Any],
    transforms: list[ItemTransform],
    slide_range: SlideRange = None,
) -> list[dict[str, Any]]:
    """Reuse a post-transform donor slide; only strip extras and apply the delta.

    Wall slides are compared *before* remap. If map+dots are unchanged, JXA
    duplicates the already-remapped donor, deletes objects the new slide lacks,
    pastes leftover objects from the original slide, and transforms that delta.
    """
    slides: list[dict] = []
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if not wants_slide(number, slide_range):
            continue
        slides.append(slide)
    by_slide: dict[int, list[ItemTransform]] = {}
    for spec in transforms:
        by_slide.setdefault(spec.slide_number, []).append(spec)
    jobs: list[dict[str, Any]] = []
    done: list[tuple[int, dict]] = []
    for slide in slides:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if not done:
            done.append((number, slide))
            continue
        curr_items = _live_items(slide)
        curr_keys = {item_content_key(it): it for it in curr_items}
        best: tuple[int, int, int, dict, list, list, list] | None = None
        for prev_n, prev in done:
            prev_items = _live_items(prev)
            prev_keys = {item_content_key(it): it for it in prev_items}
            persist = [curr_keys[k] for k in curr_keys if k in prev_keys]
            persist_pairs = [(curr_keys[k], prev_keys[k]) for k in curr_keys if k in prev_keys]
            if len(persist) < REUSE_MIN_PERSIST:
                continue
            prev_by_id: dict[tuple[Any, ...], dict] = {}
            for it in prev_items:
                ident = item_identity(it)
                if ident[0] == "text" and not ident[1]:
                    continue
                prev_by_id.setdefault(ident, it)
            remove = [prev_keys[k] for k in prev_keys if k not in curr_keys]
            incoming = [curr_keys[k] for k in curr_keys if k not in prev_keys]
            mutate: list[tuple[dict, dict]] = []
            add: list[dict] = []
            mutate_prev_keys: set[tuple[Any, ...]] = set()
            for it in incoming:
                ident = item_identity(it)
                donor_it = prev_by_id.get(ident)
                if donor_it is not None and ident[0] == "text" and ident[1]:
                    mutate.append((donor_it, it))
                    mutate_prev_keys.add(item_content_key(donor_it))
                else:
                    add.append(it)
            remove = [it for it in remove if item_content_key(it) not in mutate_prev_keys]
            cost = len(remove) + len(add)
            rank = (len(persist), -cost)
            if best is None or rank > (best[0], -best[1]):
                best = (len(persist), cost, prev_n, prev, persist, remove, add, mutate, persist_pairs)  # type: ignore[assignment]
        if best is None:
            done.append((number, slide))
            continue
        persist_n, cost, from_n, _prev, persist, remove, add, mutate, persist_pairs = best  # type: ignore[misc]
        specs = by_slide.get(number) or []
        spec_map = {_spec_key(t): t for t in specs}

        def _xf(item: dict, match: str | None = None) -> dict[str, Any] | None:
            spec = spec_map.get((str(item.get("kind") or ""), int(item.get("kindIndex") or 0)))
            if spec is None:
                return None
            payload = spec.as_dict()
            payload["slide"] = number
            text = match if match is not None else (item.get("text") or "").strip()
            if text:
                payload["matchText"] = text
            return payload

        add_specs: list[dict[str, Any]] = []
        for it in add:
            payload = _xf(it)
            if payload is None:
                payload = {
                    "slide": number,
                    "kind": str(it.get("kind") or "item"),
                    "kindIndex": int(it.get("kindIndex") or 0),
                    "itemIndex": int(it.get("index") if it.get("index") is not None else it.get("_index") or 0),
                }
                text = (it.get("text") or "").strip()
                if text:
                    payload["matchText"] = text
            add_specs.append(payload)
        add_specs = [p for p in add_specs if p.get("role") != "hide"]
        mutate_specs = []
        for _donor_it, it in mutate:
            payload = _xf(it, (it.get("text") or "").strip())
            if payload is None:
                payload = {**_ref(it), "slide": number}
                text = (it.get("text") or "").strip()
                if text:
                    payload["matchText"] = text
            if payload.get("role") != "hide":
                mutate_specs.append(payload)
        strip_builds = [
            _ref(prev)
            for curr, prev in persist_pairs
            if int(curr.get("buildCount") or 0) == 0 and int(prev.get("buildCount") or 0) > 0
        ]
        jobs.append(
            {
                "slide": number,
                "from": from_n,
                "persist": persist_n,
                "remove": [_ref(it) for it in remove],
                # The delta is pasted with a select-all on the original slide, so
                # everything the donor copy already carries has to go first — the
                # persisting objects, and the mutated ones the donor supplies too.
                "strip": [_ref(it) for it in persist] + [_ref(it) for _donor, it in mutate],
                "stripBuilds": strip_builds,
                "add": add_specs,
                "mutate": mutate_specs,
            }
        )
        done.append((number, slide))
    return jobs


def visible_content_union(slide: dict, slide_w: float, slide_h: float) -> Rect | None:
    """Bounding box of everything the audience can see on this slide."""
    rects: list[Rect] = []
    for item in slide.get("items") or []:
        if is_placeholder_text(item) or item.get("duplicateOf"):
            continue
        if is_chrome_bg(item) or is_backdrop(item, slide_w, slide_h):
            continue
        if not is_visible(item, slide_w, slide_h):
            continue
        rect = item_rect(item)
        if rect.w <= 0 or rect.h <= 0:
            continue
        # Clip to the canvas: a map bleeding 1600px off the top should not drag
        # the fit down to nothing.
        x0 = max(0.0, rect.x)
        y0 = max(0.0, rect.y)
        x1 = min(slide_w, rect.x + rect.w)
        y1 = min(slide_h, rect.y + rect.h)
        if x1 > x0 and y1 > y0:
            rects.append(Rect(x0, y0, x1 - x0, y1 - y0))
    return union_rect_of(rects)


def union_rect_of(rects: list[Rect]) -> Rect | None:
    if not rects:
        return None
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def is_degenerate_scale(recipe: dict[str, Any], wall_w: float, wall_h: float) -> bool:
    """True when a recipe shrinks the wall past any useful size.

    Fitting the entire wall into the frame is the smallest sensible scale — going
    below it shows less than the whole wall would, at a smaller size, which no
    layout wants. A run picked a framing at s=0.063 against a floor of 0.25 and
    delivered slides squeezed into the top-left corner. The off-canvas check
    cannot catch that, because collapsed content is entirely on canvas.
    """
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    if wall_w <= 0 or wall_h <= 0 or dest_w <= 0 or dest_h <= 0:
        return False
    # Judge the transform that governs the frame, not the most generous of the
    # groups: a sane minor group does not rescue a collapsed primary one, and
    # mapSrc/mapDst — hence the whole layout — comes from the primary.
    aff = frame_affine(recipe)
    if aff is None or aff.s <= 0:
        return False
    floor = min(dest_w / wall_w, dest_h / wall_h) * 0.9
    return aff.s < floor


def on_canvas_fraction(
    slide: dict,
    recipe: dict[str, Any],
    wall_w: float,
    wall_h: float,
) -> float:
    """How much of this page's visible content the recipe keeps on the CG canvas.

    A template framing that does not describe a page does not fail subtly: it
    throws most of the page off the edge. Measuring that is a direct test of
    whether the learned affine applies here, and unlike counting agreeing object
    pairs it does not penalise a deliberately sparse template.
    """
    groups = _groups_from_recipe(recipe)
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    seen = inside = 0
    for item in slide.get("items") or []:
        if is_placeholder_text(item) or item.get("duplicateOf"):
            continue
        if not is_visible(item, wall_w, wall_h) or is_chrome_bg(item):
            continue
        # Name lists are re-placed rather than carried by the affine, so where
        # the affine would put them says nothing about whether it fits.
        if is_list_item(item):
            continue
        rect = item_rect(item)
        if rect.w <= 0 or rect.h <= 0:
            continue
        aff = _affine_for_item(item, groups)
        if aff is not None:
            mapped = aff.apply_rect(rect)
        elif map_src and map_dst:
            mapped = map_rect(rect, map_src, map_dst)
        else:
            continue
        seen += 1
        cx, cy = mapped.center()
        if 0 <= cx <= dest_w and 0 <= cy <= dest_h:
            inside += 1
    if not seen:
        return 1.0
    return inside / seen


def fit_to_frame_recipe(
    slide: dict,
    wall_w: float,
    wall_h: float,
    dest_w: float,
    dest_h: float,
    *,
    margin: float = 24.0,
) -> dict[str, Any] | None:
    """Last resort: shrink what is visible until it fits the CG frame.

    Report-card pages are framed per country by hand, so a template can only
    teach framings it has already seen and next week's countries will not match
    any of them. Rather than apply the closest wrong affine — which put objects
    2000px from where they belonged — scale the visible content to fit and flag
    the slide. The operator gets everything present, readable and roughly placed,
    which is a far better starting point than confidently wrong geometry.
    """
    src = visible_content_union(slide, wall_w, wall_h)
    if src is None or src.w <= 0 or src.h <= 0:
        return None
    usable_w = max(1.0, dest_w - 2 * margin)
    usable_h = max(1.0, dest_h - 2 * margin)
    scale = min(usable_w / src.w, usable_h / src.h)
    dst = Rect(
        margin + (usable_w - src.w * scale) / 2.0,
        margin + (usable_h - src.h * scale) / 2.0,
        src.w * scale,
        src.h * scale,
    )
    return {
        "destWidth": dest_w,
        "destHeight": dest_h,
        "mapSrc": src.as_dict(),
        "mapDst": dst.as_dict(),
        "minPin": MIN_PIN_PX,
        "pinSizeScale": round(scale, 4),
        "source": "fit-to-frame",
        "groups": [
            {
                "s": round(scale, 6),
                "tx": round(dst.x - src.x * scale, 3),
                "ty": round(dst.y - src.y * scale, 3),
                "src": src.as_dict(),
                "dst": dst.as_dict(),
                "members": 0,
            }
        ],
    }


def frame_affine(recipe: dict[str, Any]) -> Affine | None:
    """How the wall canvas maps into the CG frame.

    Individual objects may ride their own group affine, but predicting what the
    CG will look like needs the one transform that governs the frame as a whole.
    """
    src = _rect_from_dict(recipe.get("mapSrc"))
    dst = _rect_from_dict(recipe.get("mapDst"))
    if src and dst and src.w > 0 and src.h > 0:
        return affine_from_rects(src, dst)
    for group in recipe.get("groups") or []:
        gsrc = _rect_from_dict(group.get("src"))
        gdst = _rect_from_dict(group.get("dst"))
        if gsrc and gdst and gsrc.w > 0 and gsrc.h > 0:
            return affine_from_rects(gsrc, gdst)
    return None


def repack_free_text(
    transforms: list[ItemTransform],
    slide: dict,
    recipe: dict[str, Any],
    *,
    preview: Any,
    wall_w: float,
    wall_h: float,
) -> list[dict[str, Any]]:
    """Re-place background-only text into whatever space the CG frame has left.

    The wall keeps its church-name lists on side panels outside the centre
    1920x1080, so cropping to 16:9 leaves them with nowhere to be and the old
    right-to-left packing walked them across the map. This instead measures where
    the CG is actually empty and puts them there.

    Emptiness is measured on pixels, not rectangles: the map image covers the
    whole frame while most of it is ocean. The CG raster is predicted by cropping
    the wall's own preview through the frame affine, which works because the two
    canvases are the same height, so no second Keynote render is needed.

    Text overlapping artwork is left alone — it is a label, and its group affine
    already keeps it with the thing it labels. Returns one report row per moved
    box so the caller can flag the crowded ones.
    """
    analysis = analyse_free_text(slide, recipe, preview=preview, wall_w=wall_w, wall_h=wall_h)
    if analysis is None:
        return []
    return _place_free_text(transforms, slide, recipe, analysis)


def analyse_free_text(
    slide: dict,
    recipe: dict[str, Any],
    *,
    preview: Any,
    wall_w: float,
    wall_h: float,
) -> dict[str, Any] | None:
    """Work out, from a rendered wall slide, which list text is free to move.

    Done once per slide and shared, because two decisions depend on it: whether
    an unticked "include lists" should drop a piece of text, and where to put it
    if it is kept. Deciding twice by different rules is how a label ends up
    hidden on one path and relocated on the other.
    """
    from obed_edom.free_space import (  # noqa: PLC0415
        Box,
        background_fraction,
        predict_cg_raster,
    )

    aff = frame_affine(recipe)
    if aff is None or preview is None or aff.s <= 0:
        return None
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)

    frame, bg = predict_cg_raster(
        preview,
        wall_w=wall_w,
        wall_h=wall_h,
        scale=aff.s,
        tx=aff.tx,
        ty=aff.ty,
        dest_w=dest_w,
        dest_h=dest_h,
    )
    # Decide what may move from the pixels beneath it on the wall, not from
    # overlapping rectangles. Fall back to the rect test only where no raster is
    # available, since transparent artwork makes rects far too pessimistic.
    px = preview.width / wall_w if wall_w else 1.0
    py = preview.height / wall_h if wall_h else 1.0
    movable: set[tuple[str, int]] = set()
    for item in slide.get("items") or []:
        if not is_list_item(item):
            continue
        rect = item_rect(item)
        clear = background_fraction(
            preview,
            Box(rect.x * px, rect.y * py, rect.w * px, rect.h * py),
            bg=bg,
        )
        if clear >= FREE_TEXT_BACKGROUND_MIN:
            movable.add((str(item.get("kind")), int(item.get("kindIndex") or 0)))
    return {"frame": frame, "bg": bg, "affine": aff, "free": movable, "dest": (dest_w, dest_h)}


def _place_free_text(
    transforms: list[ItemTransform],
    slide: dict,
    recipe: dict[str, Any],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    from obed_edom.free_space import Box, occupancy_from_image, place_boxes  # noqa: PLC0415
    from PIL import ImageDraw  # noqa: PLC0415

    movable: set[tuple[str, int]] = analysis["free"]
    if not movable:
        return []
    frame = analysis["frame"]
    bg = analysis["bg"]
    aff: Affine = analysis["affine"]
    dest_w, dest_h = analysis["dest"]

    cx = frame.width / dest_w
    cy = frame.height / dest_h
    eraser = ImageDraw.Draw(frame)
    for item in slide.get("items") or []:
        if (str(item.get("kind")), int(item.get("kindIndex") or 0)) not in movable:
            continue
        rect = aff.apply_rect(item_rect(item))
        eraser.rectangle(
            [rect.x * cx, rect.y * cy, (rect.x + rect.w) * cx, (rect.y + rect.h) * cy], fill=bg
        )

    space = occupancy_from_image(frame, slide_w=dest_w, slide_h=dest_h, bg=bg)
    targets = [t for t in transforms if _spec_key(t) in movable]
    if not targets:
        return []
    # Right-to-left, top-to-bottom: the order the lists read on the wall.
    targets.sort(key=lambda t: (-t.x, t.y))
    placed = place_boxes(space, [Box(t.x, t.y, t.w, t.h) for t in targets])
    report: list[dict[str, Any]] = []
    for spec, spot in zip(targets, placed, strict=True):
        spec.x, spec.y = spot.box.x, spot.box.y
        report.append(
            {
                "slide": spec.slide_number,
                "kind": spec.kind,
                "kindIndex": spec.kind_index,
                "overlap": round(spot.overlap, 3),
                "x": round(spot.box.x, 1),
                "y": round(spot.box.y, 1),
            }
        )
    return report


def offframe_rows(
    transforms: list[ItemTransform],
    slide: dict,
    recipe: dict[str, Any],
    wall_w: float,
    wall_h: float,
    *,
    min_visible: float = OFFFRAME_MIN_VISIBLE,
) -> list[dict[str, Any]]:
    """Objects that showed on the wall but land outside the CG frame.

    Nothing else reports these. `bounds.offcanvas` only measures vertical cuts
    and `bounds.straddles` looks for LED panel seams, so an object pushed off the
    left edge is invisible to both — a title badge vanished from a deck with no
    warning at all. The planner is the right place to notice, because only it
    knows the object was visible before it was moved.
    """
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    if dest_w <= 0 or dest_h <= 0:
        return []
    was_visible = {
        (str(it.get("kind") or "item"), _item_kind_index(it, _item_index(it, i)))
        for i, it in enumerate(slide.get("items") or [])
        if is_visible(it, wall_w, wall_h) and not is_placeholder_text(it)
    }
    rows: list[dict[str, Any]] = []
    for spec in transforms:
        if spec.role == "hide" or spec.w <= 0 or spec.h <= 0:
            continue
        if _spec_key(spec) not in was_visible:
            continue
        x0 = max(0.0, spec.x)
        y0 = max(0.0, spec.y)
        x1 = min(dest_w, spec.x + spec.w)
        y1 = min(dest_h, spec.y + spec.h)
        shown = 0.0 if x1 <= x0 or y1 <= y0 else ((x1 - x0) * (y1 - y0)) / (spec.w * spec.h)
        if shown < min_visible:
            rows.append(
                {
                    "slide": spec.slide_number,
                    "kind": spec.kind,
                    "kindIndex": spec.kind_index,
                    "role": spec.role,
                    "visible": round(shown, 3),
                    "x": round(spec.x, 1),
                    "y": round(spec.y, 1),
                }
            )
    return rows


def plan_payload_transforms(
    payload: dict[str, Any],
    recipe: dict[str, Any],
    *,
    slide_range: SlideRange = None,
    include_lists: bool = False,
    template: dict[str, Any] | None = None,
    previews: dict[int, Any] | None = None,
    placement_report: list[dict[str, Any]] | None = None,
    skipped_slides: list[int] | None = None,
    fitted_slides: list[int] | None = None,
    offframe_report: list[dict[str, Any]] | None = None,
    framing_overrides: dict[int, int] | None = None,
    framing_report: list[dict[str, Any]] | None = None,
    min_on_canvas: float = MIN_ON_CANVAS_FRACTION,
) -> list[ItemTransform]:
    """Plan every slide's moves.

    `previews` maps slide number to a rendered wall image. Supplying it switches
    loose text from blind right-to-left packing onto measured empty space; rows
    describing what moved land in `placement_report` for flagging. Slides hidden
    with Skip Slide are not planned, and their numbers land in `skipped_slides`.

    `framing_overrides` maps a wall slide number to the template slide number the
    operator confirmed, replacing the automatic choice for that slide only. The
    fit-to-frame fallback still applies afterwards, so a confirmation that turns
    out unusable degrades the same way an automatic choice does rather than
    throwing content out of frame. What each slide ended up using lands in
    `framing_report`.
    """
    wall_w = _f(payload.get("slideWidth"), CG_WIDTH)
    wall_h = _f(payload.get("slideHeight"), CG_HEIGHT)
    transforms: list[ItemTransform] = []
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if not wants_slide(number, slide_range):
            continue
        # A skipped slide is hidden from the show, so remapping it is wasted
        # Keynote time. It is left at wall geometry rather than deleted, so
        # un-skipping it in Keynote and re-running still works.
        if slide.get("skipped"):
            if skipped_slides is not None:
                skipped_slides.append(number)
            continue
        slide_recipe = recipe
        if template and (template.get("slides") or []):
            wanted = (framing_overrides or {}).get(number)
            slide_recipe = learn_recipe(
                {
                    "slideWidth": payload.get("slideWidth"),
                    "slideHeight": payload.get("slideHeight"),
                    "slides": [slide],
                },
                template,
                template_slide=wanted,
            )
            if framing_report is not None:
                framing_report.append(
                    {
                        "slide": number,
                        "templateSlide": slide_recipe.get("templateSlide"),
                        "requested": wanted,
                        "confirmed": bool(slide_recipe.get("framingPinned")),
                        "source": slide_recipe.get("source"),
                        "pairQuality": slide_recipe.get("pairQuality"),
                        "fitted": False,
                    }
                )
            # No template framing describes this page. Applying the closest one
            # anyway either throws objects thousands of pixels out of frame or
            # collapses them into a corner; fitting what is visible does neither.
            unusable = on_canvas_fraction(
                slide, slide_recipe, wall_w, wall_h
            ) < min_on_canvas or is_degenerate_scale(slide_recipe, wall_w, wall_h)
            if unusable:
                fitted = fit_to_frame_recipe(
                    slide,
                    wall_w,
                    wall_h,
                    _f(slide_recipe.get("destWidth"), CG_WIDTH),
                    _f(slide_recipe.get("destHeight"), CG_HEIGHT),
                )
                if fitted:
                    for carry in ("characterStyles", "listFontSize", "listSample"):
                        if slide_recipe.get(carry) is not None:
                            fitted[carry] = slide_recipe[carry]
                    slide_recipe = fitted
                    if fitted_slides is not None:
                        fitted_slides.append(number)
                    if framing_report:
                        framing_report[-1]["fitted"] = True
        preview = (previews or {}).get(number)
        # One raster read per slide, shared by the drop decision and the
        # placement decision so they can never disagree.
        analysis = (
            analyse_free_text(
                slide, slide_recipe, preview=preview, wall_w=wall_w, wall_h=wall_h
            )
            if preview is not None
            else None
        )
        planned = plan_slide_transforms(
            slide,
            slide_recipe,
            include_lists=include_lists,
            wall_size=(wall_w, wall_h),
            defer_list_packing=include_lists and analysis is not None,
            free_text_keys=analysis["free"] if analysis else None,
        )
        if include_lists and analysis is not None:
            rows = _place_free_text(planned, slide, slide_recipe, analysis)
            if placement_report is not None:
                placement_report.extend(rows)
        if offframe_report is not None:
            offframe_report.extend(
                offframe_rows(planned, slide, slide_recipe, wall_w, wall_h)
            )
        transforms.extend(planned)
    return transforms


SCORED_ROLES = ("map", "pin", "list", "title")


def _geometry_signature(slide: dict) -> tuple[int, int]:
    items = [
        it
        for it in slide.get("items") or []
        if not is_placeholder_text(it) and not it.get("duplicateOf")
    ]
    return (
        sum(1 for it in items if is_pin_item(it)),
        sum(1 for it in items if is_map_item(it)),
    )


def _signature_score(a: tuple[int, int], b: tuple[int, int]) -> float:
    """How alike two slides look geometrically. Pins carry most of the signal.

    Pin count is close to an identifier: it is how many churches that page
    reports. Map layer counts agree far less, because the human often flattens
    layers on the way to the CG.
    """
    pins_a, maps_a = a
    pins_b, maps_b = b
    if pins_a == 0 and pins_b == 0 and maps_a == 0 and maps_b == 0:
        return 0.0
    score = 0.0
    if pins_a or pins_b:
        score += 3.0 * (1.0 - abs(pins_a - pins_b) / max(pins_a, pins_b, 1))
    if maps_a or maps_b:
        score += 1.0 * (1.0 - abs(maps_a - maps_b) / max(maps_a, maps_b, 1))
    return score


def align_by_geometry(
    wall_slides: list[dict],
    gold_slides: list[dict],
    *,
    min_score: float = 2.0,
) -> dict[int, int]:
    """Pair wall slides to gold CG slides by shape, returning wall number -> gold number.

    `align_slides` cannot do this job here. It leads on text, and its
    perceptual-hash fallback only engages when both slides are short-title
    (diff_keynotes.py), so text-heavy report pages never reach it — and the CG is
    translated to Chinese for the Chinese service, so the text will never match
    anyway.

    Geometry sidesteps language entirely, and it is the right signal for a
    geometry score. Both decks present the same report in the same order, so the
    alignment is kept monotonic: pairings cannot cross, which stops a page
    matching a similar-looking page elsewhere in the deck.
    """
    left = [s for s in wall_slides if not s.get("skipped")]
    right = [s for s in gold_slides if not s.get("skipped")]
    if not left or not right:
        return {}
    lsig = [_geometry_signature(s) for s in left]
    rsig = [_geometry_signature(s) for s in right]

    n, m = len(left), len(right)
    # Longest-common-subsequence style DP: skipping a slide on either side is
    # free, since each deck holds pages the other does not.
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            skip_left = best[i + 1][j]
            skip_right = best[i][j + 1]
            pair = 0.0
            score = _signature_score(lsig[i], rsig[j])
            if score >= min_score:
                pair = score + best[i + 1][j + 1]
            best[i][j] = max(skip_left, skip_right, pair)

    out: dict[int, int] = {}
    i = j = 0
    while i < n and j < m:
        score = _signature_score(lsig[i], rsig[j])
        paired = score + best[i + 1][j + 1] if score >= min_score else -1.0
        if paired >= best[i + 1][j] and paired >= best[i][j + 1] and score >= min_score:
            wall_no = int(left[i].get("number") or (int(left[i].get("index") or 0) + 1))
            gold_no = int(right[j].get("number") or (int(right[j].get("index") or 0) + 1))
            out[wall_no] = gold_no
            i += 1
            j += 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def gold_frame_affine(
    wall_slide: dict,
    gold_slide: dict,
    *,
    wall_size: tuple[float, float] | None = None,
    gold_size: tuple[float, float] | None = None,
) -> Affine | None:
    """The transform the human actually used, read off the base map on each side.

    Sizes matter: an off-canvas map fragment is invisible, so deriving the
    reference transform from one describes nothing the audience ever saw.
    """
    ww, wh = wall_size or (0.0, 0.0)
    gw, gh = gold_size or (0.0, 0.0)
    wall_maps = [
        it
        for it in wall_slide.get("items") or []
        if is_map_item(it) and (not wall_size or is_visible(it, ww, wh))
    ]
    gold_maps = [
        it
        for it in gold_slide.get("items") or []
        if is_map_item(it) and (not gold_size or is_visible(it, gw, gh))
    ]
    src = primary_map_rect(wall_maps) or union_rect(wall_maps)
    dst = primary_map_rect(gold_maps) or union_rect(gold_maps)
    if not src or not dst or src.w <= 0 or src.h <= 0:
        return None
    return affine_from_rects(src, dst)


def _wall_item_lookup(
    wall_slide: dict, slide_w: float = 0.0, slide_h: float = 0.0
) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    for i, item in enumerate(wall_slide.get("items") or []):
        if is_placeholder_text(item) or item.get("duplicateOf"):
            continue
        if slide_w > 0 and slide_h > 0 and not is_visible(item, slide_w, slide_h):
            continue
        key = (str(item.get("kind") or "item"), _item_kind_index(item, _item_index(item, i)))
        out.setdefault(key, item)
    return out


def _greedy_match(
    predicted: list[tuple[float, float]],
    gold: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Pair each prediction with its nearest unused gold point, closest pairs first.

    Sorting by position instead (what this used to do) silently mispairs whole
    rows whenever the two sides hold different counts, which is the normal case:
    a deck may gain or lose a pin between the wall and the finished CG.
    """
    candidates = sorted(
        (
            ((px - gx) ** 2 + (py - gy) ** 2, i, j)
            for i, (px, py) in enumerate(predicted)
            for j, (gx, gy) in enumerate(gold)
        ),
    )
    used_pred: set[int] = set()
    used_gold: set[int] = set()
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for _, i, j in candidates:
        if i in used_pred or j in used_gold:
            continue
        used_pred.add(i)
        used_gold.add(j)
        out.append((predicted[i], gold[j]))
    return out


def fit_similarity(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> tuple[float, float, float] | None:
    """Best uniform scale + translation taking predicted points onto gold ones.

    Raw distance to a gold deck answers two questions at once and so answers
    neither: "are the pins right relative to the map" and "did we put the map
    where the human did". Deliberately shrinking the template map to make room
    for the name lists changes the second and leaves the first untouched, yet
    raw RMSE reports it as a large regression.

    Fitting a transform first splits them. The residual afterwards is geometric
    fidelity, which is what the resizer controls; the fitted scale and offset
    describe the layout choice, which the template controls.
    """
    n = len(pairs)
    if n < 2:
        return None
    px = sum(p[0] for p, _ in pairs) / n
    py = sum(p[1] for p, _ in pairs) / n
    gx = sum(g[0] for _, g in pairs) / n
    gy = sum(g[1] for _, g in pairs) / n
    num = sum((p[0] - px) * (g[0] - gx) + (p[1] - py) * (g[1] - gy) for p, g in pairs)
    den = sum((p[0] - px) ** 2 + (p[1] - py) ** 2 for p, _ in pairs)
    if den <= 1e-9:
        return None
    s = num / den
    return s, gx - s * px, gy - s * py


def residual_rmse(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
    fit: tuple[float, float, float],
) -> float:
    s, tx, ty = fit
    moved = [((s * p[0] + tx, s * p[1] + ty), g) for p, g in pairs]
    return rmse_points(moved)


def score_against_gold(
    predicted: list[ItemTransform],
    gold: dict[str, Any],
    *,
    wall: dict[str, Any] | None = None,
    slide_map: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Placement error per role against a human-made CG deck.

    Feed this the *gold* CG, not the template the recipe was learned from.
    Scoring against the template compares predictions to the template's own
    content — a different week's pins — which reports a large error on output
    that is in fact correct.

    Pass `wall` to get the number worth trusting. Both our output and the gold
    derive from the same wall objects, so the wall gives an exact
    correspondence: project each wall object through the gold's own transform and
    compare our placement of that same object. `goldRmse` is that figure.

    Without `wall` the only correspondence available is proximity, and that is
    unreliable here: 138 pins share about 886px, roughly 6px apart, while a
    layout difference offsets everything by up to 190px — so every pin matches
    one about thirty places away and the result is noise. `nearestRmse` is
    reported for continuity but should not be used to judge a change.

    Results stay per slide and per role rather than averaged, so a
    slide-alignment mistake shows up as one enormous row instead of quietly
    inflating everything.
    """
    by_slide: dict[int, list[ItemTransform]] = {}
    for spec in predicted:
        by_slide.setdefault(spec.slide_number, []).append(spec)
    wall_slides = {
        int(s.get("number") or (int(s.get("index") or 0) + 1)): s
        for s in (wall or {}).get("slides") or []
    }
    gold_w = _f(gold.get("slideWidth"), CG_WIDTH)
    gold_h = _f(gold.get("slideHeight"), CG_HEIGHT)
    wall_w = _f((wall or {}).get("slideWidth"), 0.0)
    wall_h = _f((wall or {}).get("slideHeight"), 0.0)
    slides: dict[int, dict[str, Any]] = {}
    all_pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    legacy_pins = 0
    legacy_rmse: float | None = None

    for gold_slide in gold.get("slides") or []:
        # Skipped slides are hidden alternates the operator parked in the deck.
        # On one gold CG they held 21% of all items, which would have been scored
        # as content the resizer failed to produce.
        if gold_slide.get("skipped"):
            continue
        gold_number = int(gold_slide.get("number") or (int(gold_slide.get("index") or 0) + 1))
        pred_number = gold_number
        if slide_map:
            match = [p for p, g in slide_map.items() if g == gold_number]
            if not match:
                continue
            pred_number = match[0]
        pred = by_slide.get(pred_number) or []
        if not pred:
            continue
        gold_items = [
            it
            for it in gold_slide.get("items") or []
            if not is_placeholder_text(it)
            and not it.get("duplicateOf")
            # Both decks carry the same off-slide leftovers, and comparing them
            # dominated the score: one report page held 10 pins of which 9 were
            # parked above the canvas on the wall and off to the left on the CG.
            and is_visible(it, gold_w, gold_h)
        ]
        wall_slide = wall_slides.get(pred_number)
        gold_aff = (
            gold_frame_affine(
                wall_slide,
                gold_slide,
                wall_size=(wall_w, wall_h) if wall_w and wall_h else None,
                gold_size=(gold_w, gold_h),
            )
            if wall_slide
            else None
        )
        wall_items = _wall_item_lookup(wall_slide, wall_w, wall_h) if wall_slide else {}

        per_role: dict[str, Any] = {}
        for role in SCORED_ROLES:
            specs = [t for t in pred if t.role == role]
            pred_pts = [(t.x + t.w / 2.0, t.y + t.h / 2.0) for t in specs]
            gold_pts = [item_center(it) for it in gold_items if classify_item(it) == role]
            if not pred_pts and not gold_pts:
                continue

            # Exact comparison: same wall object, our placement versus where the
            # gold's own transform would have put it.
            projected: list[tuple[tuple[float, float], tuple[float, float]]] = []
            if gold_aff is not None:
                for spec in specs:
                    source = wall_items.get(_spec_key(spec))
                    if source is None:
                        continue
                    ideal = gold_aff.apply_rect(item_rect(source))
                    projected.append(
                        (
                            (spec.x + spec.w / 2.0, spec.y + spec.h / 2.0),
                            (ideal.x + ideal.w / 2.0, ideal.y + ideal.h / 2.0),
                        )
                    )

            nearest = _greedy_match(pred_pts, gold_pts) if pred_pts and gold_pts else []
            per_role[role] = {
                "predicted": len(pred_pts),
                "gold": len(gold_pts),
                "matched": len(projected),
                "goldRmse": round(rmse_points(projected), 2) if projected else None,
                "nearestRmse": round(rmse_points(nearest), 2) if nearest else None,
            }
            all_pairs.extend(projected)
            if role == "pin" and projected and legacy_rmse is None:
                legacy_pins = len(projected)
                legacy_rmse = round(rmse_points(projected), 2)
        if per_role:
            slides[pred_number] = per_role
            if gold_aff is not None:
                slides[pred_number]["_goldAffine"] = {
                    "s": round(gold_aff.s, 4),
                    "tx": round(gold_aff.tx, 1),
                    "ty": round(gold_aff.ty, 1),
                }

    return {
        "slides": slides,
        "overallPairs": len(all_pairs),
        "overallRmse": round(rmse_points(all_pairs), 2) if all_pairs else None,
        # Kept for the CLI and dashboard, which print a single pin number.
        "pinPairs": legacy_pins,
        "pinRmse": legacy_rmse,
    }


def summarize_plan(transforms: list[ItemTransform]) -> dict[str, int]:
    counts: dict[str, int] = {"map": 0, "pin": 0, "list": 0, "title": 0, "line": 0, "other": 0}
    for spec in transforms:
        counts[spec.role] = counts.get(spec.role, 0) + 1
    counts["total"] = len(transforms)
    return counts
