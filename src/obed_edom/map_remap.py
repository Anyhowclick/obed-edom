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
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


CG_WIDTH = 1920
CG_HEIGHT = 1080
MIN_PIN_PX = 28.0

MAP_NAME_RE = re.compile(r"map\s*bg", re.I)
PIN_NAME_RE = re.compile(r"pin\s*drop", re.I)
CHURCH_LIST_RE = re.compile(r"\b(CHC|CHLI|CHEL)\b")
PIN_KIND_MAX = 180.0
# Asia-Pacific wall/CG map art is pasted PDFs, not map BG.png.
MAP_LAYER_MIN_W = 400.0
MAP_LAYER_MIN_H = 200.0
MAP_LAYER_MAX_W = 2500.0
MAP_LAYER_MAX_H = 1200.0
# Country overlays sit on the map rim; centre-in-box misses them.
MAP_NEAR_PAD = 400.0
# Title plate/globe sit beside the map; keep that cluster on one affine.
TITLE_NEAR_PAD = 120.0
# Small so a nearby badge does not swallow other content (plate already is the extent).
BADGE_PLATE_PAD = 24.0
# Separates a paragraph from a phrase/label.
BODY_TEXT_MIN_CHARS = 60
# ≥6 church-name boxes is a list, not map labels (those come 1–5 at a time).
LIST_SUMMARY_MIN = 6
# Rejects full-height side columns; real plates are ~0.1 of canvas height.
PLATE_MAX_H_FRACTION = 0.5
# Map crop is often s≈1; unmatched wall text still needs to shrink for 16:9.
TEXT_DOWN_SCALE = 0.42
# Believe the affine only if this much visible art still lands on CG.
MIN_ON_CANVAS_FRACTION = 0.5
# Under-box background fraction (glyphs keep it < 1; landmass drops it).
FREE_TEXT_BACKGROUND_MIN = 0.55
# Report objects that mostly disappear; edge bleed is intended.
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
    """Uniform scale + translation: (x, y) → (s*x + tx, s*y + ty)."""

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
    src: Rect | None = None

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
        # Size before position (Keynote resets position when size changes).
        if self.role in {"map", "list", "pin", "title", "other"}:
            payload["w"] = round(self.w, 2)
            payload["h"] = round(self.h, 2)
        elif self.role == "line" and self.start is not None and self.end is not None:
            # Line width=length / height=0; Keynote ignores endpoints.
            payload["w"] = round(
                math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1]), 2
            )
            payload["h"] = 0.0
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


# Title phrases live in masters.yaml `cg.title_phrases`; a miss treats the badge as ordinary content.
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
    """True if any part sits on-canvas; off-slide leftovers must not remap on-frame."""
    if slide_w <= 0 or slide_h <= 0:
        return True
    rect = item_rect(item)
    # Keynote reports a 90° line as width=length, height=0; zero thickness is still a visible stroke.
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


# LW wall is three 1920 panels; CG keeps the centre [1920..5760]. Side-panel-only content is dropped unless kept.
LW_WALL_SIZE = (7680.0, 1080.0)
CENTRE_PANEL_RECT = Rect(1920.0, 0.0, 3840.0, 1080.0)


def is_lw_wall(wall_w: float, wall_h: float) -> bool:
    return round(wall_w) == round(LW_WALL_SIZE[0]) and round(wall_h) == round(LW_WALL_SIZE[1])


def is_side_panel_item(item: dict, wall_w: float, wall_h: float) -> bool:
    """Content wholly on the LW left/right 1920 panels; centre crop [1920..5760] is kept."""
    if not is_lw_wall(wall_w, wall_h) or not is_visible(item, wall_w, wall_h):
        return False
    r = item_rect(item)
    c = CENTRE_PANEL_RECT
    overlaps_centre = (
        r.x < c.x + c.w and r.x + r.w > c.x and r.y < c.y + c.h and r.y + r.h > c.y
    )
    return not overlaps_centre


def occluder_rects(slide: dict, slide_w: float, slide_h: float) -> list[Rect]:
    """Artwork a text box could sit on; backdrops/chrome excluded so they don't pin every box."""
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
    """True when the text sits on bare background and may be packed; labels on artwork stay."""
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
    """CG swatch only when family+weight match; colour then size break ties. No swatch → keep wall face."""
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


def template_list_sample(
    slides: list[dict], slide_size: tuple[float, float] | None = None
) -> tuple[float | None, Rect | None]:
    """One-line church-name seed, skipping the page title so a CHC heading is not the list size."""
    candidates: list[tuple[int, float, Rect]] = []
    for slide in slides:
        title = slide_title_item(slide, slide_size)
        for item in slide.get("items") or []:
            if title is not None and item is title:
                continue
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


def template_title_item(
    slides: list[dict], slide_size: tuple[float, float] | None = None
) -> dict | None:
    for slide in slides:
        title = slide_title_item(slide, slide_size)
        if title is not None:
            return title
    return None


def template_body_text(
    slides: list[dict], slide_size: tuple[float, float] | None = None
) -> dict | None:
    """Body box on the chosen template slide only."""
    if not slides:
        return None
    return slide_body_text_item(slides[0], slide_size)


def pack_columns_from_right(
    boxes: list[Rect],
    dest_w: float,
    dest_h: float,
    map_dst: Rect | None = None,
    *,
    gap: float = 10.0,
    margin: float = 16.0,
) -> list[Rect]:
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


def pack_columns_from_left(
    boxes: list[Rect],
    dest_w: float,
    dest_h: float,
    *,
    gap: float = 10.0,
    margin: float = 16.0,
) -> list[Rect]:
    """Stack left-edge columns; a new column must clear the widest box in the previous one."""
    if not boxes:
        return []
    top = margin
    bottom = max(margin + 8.0, dest_h - margin)
    placed: list[Rect] = []
    col_left = margin
    col_max_w = 0.0
    y = top
    for box in boxes:
        w = max(8.0, box.w)
        h = max(8.0, box.h)
        if placed and y + h > bottom + 0.5:
            col_left = col_left + col_max_w + gap
            y = top
            col_max_w = 0.0
        placed.append(Rect(col_left, y, w, h))
        col_max_w = max(col_max_w, w)
        y += h + gap
    return placed


def template_line_slots(
    slides: list[dict], slide_number: int | None = None
) -> list[dict[str, Any]]:
    """Template rules left to right; a gutter divider must not inherit the crop's leftover length."""
    slide = None
    if slide_number is not None:
        slide = next((s for s in slides if _slide_number_of(s) == slide_number), None)
    if slide is None or not any(str(it.get("kind") or "") == "line" for it in slide.get("items") or []):
        slide = _first_slide_with(
            slides,
            lambda s: any(str(it.get("kind") or "") == "line" for it in s.get("items") or []),
        )
    if slide is None:
        return []
    lines = [it for it in slide.get("items") or [] if str(it.get("kind") or "") == "line"]
    out: list[dict[str, Any]] = []
    for item in sorted(lines, key=lambda it: (_f(it.get("x")), _f(it.get("y")))):
        slot: dict[str, Any] = dict(item_rect(item).as_dict())
        if item.get("start"):
            slot["start"] = [_f(item["start"][0]), _f(item["start"][1])]
        if item.get("end"):
            slot["end"] = [_f(item["end"][0]), _f(item["end"][1])]
        out.append(slot)
    return out


def slides_preferring(template_slides: list[dict], number: int | None) -> list[dict]:
    """Chosen template slide first so title/badge geometry follow that framing, not the first title in the deck."""
    if number is None:
        return list(template_slides)
    chosen = [s for s in template_slides if _slide_number_of(s) == number]
    if not chosen:
        return list(template_slides)
    return chosen + [s for s in template_slides if _slide_number_of(s) != number]


# PLATE_COLOR_TOLERANCE: a different plate colour is not the badge (snapping onto it drags it into the map).
PLATE_COLOR_TOLERANCE = 0.2


def _rgb_close(a: list[float] | None, b: list[float] | None, tol: float) -> bool:
    if not a or not b or len(a) < 3 or len(b) < 3:
        return False
    return sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])) <= tol * tol


def _attach_text_style(
    recipe: dict[str, Any],
    template_slides: list[dict],
    *,
    source_plate_color: list[float] | None = None,
) -> dict[str, Any]:
    dest = (_f(recipe.get("destWidth"), CG_WIDTH), _f(recipe.get("destHeight"), CG_HEIGHT))
    ordered = slides_preferring(template_slides, recipe.get("templateSlide"))
    font, sample = template_list_sample(ordered, dest)
    if font:
        recipe["listFontSize"] = round(font, 2)
        if sample:
            recipe["listSample"] = sample.as_dict()
    # Badge slots come from the template slide whose plate colour matches the source, not the chosen map framing.
    if source_plate_color is not None:
        matched = [
            s
            for s in ordered
            if (p := title_plate(s, dest)) is not None
            and _rgb_close(source_plate_color, item_rgb(p), PLATE_COLOR_TOLERANCE)
        ]
        badge_ordered = matched + [s for s in ordered if s not in matched]
    else:
        badge_ordered = ordered
    title = template_title_item(badge_ordered, dest)
    if title:
        recipe["titleDst"] = item_rect(title).as_dict()
        if title.get("size"):
            recipe["titleFontSize"] = round(_f(title.get("size")), 2)
        if title.get("font"):
            recipe["titleFont"] = str(title.get("font") or "")
        title_rgb = item_rgb(title)
        if title_rgb:
            recipe["titleColor"] = [round(c, 4) for c in title_rgb]
    body = template_body_text(ordered, dest)
    if body is not None:
        body_rect = item_rect(body)
        if body_rect.w > 0 and body_rect.h > 0:
            recipe["bodyTextDst"] = body_rect.as_dict()
            if body.get("size"):
                recipe["bodyTextFontSize"] = round(_f(body.get("size")), 2)
    slots = template_badge_slots(badge_ordered, dest)
    if slots:
        recipe["badgeSlots"] = slots
    badge_plate = template_badge_plate(badge_ordered, dest)
    if badge_plate is not None and badge_plate.w > 0:
        recipe["badgePlateDst"] = badge_plate.as_dict()
    rules = template_line_slots(template_slides, recipe.get("templateSlide"))
    if rules:
        recipe["lineSlots"] = rules
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
    """Largest real map piece, excluding LED `map BG.png` tiles that would steal the affine origin."""
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
    """7680 canvas with a 1920×1080 inspected panel → use the canvas; do not expand already-16:9 CG map art."""
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


# Centre panel: ~2 CG frames wide × 1 tall, 1:1 centre-cropped.
CENTRE_PANEL_MIN_WIDTH_FRAMES = 1.7
CENTRE_PANEL_MAX_HEIGHT_FRAMES = 1.3
CENTRE_PANEL_CENTRE_TOLERANCE = 0.25
# Below this share of panel area, overlays ride the panel affine instead of voting on the crop.
CENTRE_PANEL_OVERLAY_MAX_AREA_FRACTION = 0.25


def centre_panel_image(
    items: Iterable[dict], wall_w: float, wall_h: float, dest_w: float, dest_h: float
) -> Rect | None:
    if dest_w <= 0 or dest_h <= 0 or wall_w <= 0 or wall_h <= 0:
        return None
    best: Rect | None = None
    for item in items:
        if not is_pairable_image(item):
            continue
        r = item_rect(item)
        if r.w < dest_w * CENTRE_PANEL_MIN_WIDTH_FRAMES:
            continue
        if not (wall_h * 0.9 <= r.h <= wall_h * CENTRE_PANEL_MAX_HEIGHT_FRAMES):
            continue
        if abs((r.x + r.w / 2) - wall_w / 2) > wall_w * CENTRE_PANEL_CENTRE_TOLERANCE:
            continue
        if best is None or r.w * r.h > best.w * best.h:
            best = r
    return best


def _slide_for_panel_framing(slide: dict, panel: Rect) -> dict:
    """Framing view without centre-panel thumbnails — they ride the panel affine."""
    threshold = panel.w * panel.h * CENTRE_PANEL_OVERLAY_MAX_AREA_FRACTION

    def keep(item: dict) -> bool:
        if not is_pairable_image(item):
            return True
        r = item_rect(item)
        return r.w * r.h >= threshold

    return {**slide, "items": [it for it in slide.get("items") or [] if keep(it)]}


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
    """1:1 by descending area when the template was resized; drop pairs whose aspect ratios disagree."""
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
    """How much one affine explains a pairing: (largest group, total pairs)."""
    if not pairs:
        return (0, 0)
    groups = merge_affine_groups(pairs)
    if not groups:
        return (0, len(pairs))
    return (max(len(g["members"]) for g in groups), len(pairs))


def drop_outlier_pairs(pairs: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    """Drop pairs whose scale no other pair agrees with (median consensus, ≥3 pairs)."""
    if len(pairs) < 3:
        return pairs
    scales = []
    for src_item, dst_item in pairs:
        src = item_rect(src_item)
        scales.append(item_rect(dst_item).w / src.w if src.w > 0 else 0.0)
    consensus = _median([s for s in scales if s > 0])
    if consensus <= 0:
        return pairs
    lo, hi = consensus / OUTLIER_SCALE_FACTOR, consensus * OUTLIER_SCALE_FACTOR
    return [pair for pair, s in zip(pairs, scales) if lo <= s <= hi]


def best_image_pairs(wall: list[dict], dest: list[dict]) -> list[tuple[dict, dict]]:
    """Exact-size pairing wins ties; area-rank takes over once the template has been scaled."""
    exact = pair_by_size(wall, dest)
    exact = exact + pair_resized_leftovers(wall, dest, exact)
    ranked = drop_outlier_pairs(pair_by_area_rank(wall, dest))
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
    """Fill 16:9 by cropping the wall map, not by scaling the whole 7680 canvas down."""
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
    """Prefer the CG slide that one affine explains; exact size matches punish a correctly scaled template."""
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
    """How well this framing stays in-frame and fills it. Either half alone picks a collapsed or overflowing crop."""
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
    """Template framings for this wall slide, best first, so the operator can pick an editorial crop."""
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
    """Fit map rects from a 16:9 CG template. Unknown `template_slide` falls back to automatic choice."""
    dest_w = int(template.get("slideWidth") or CG_WIDTH)
    dest_h = int(template.get("slideHeight") or CG_HEIGHT)
    wall_slides = wall.get("slides") or []
    template_slides = template.get("slides") or []
    if len(wall_slides) == 1:
        w_slide = wall_slides[0]
    else:
        live_slides = [s for s in wall_slides if not s.get("skipped")]
        w_slide = _first_slide_with(live_slides, is_map_item) or _first_slide_with(
            live_slides, is_pin_item
        )
    g_slide = None
    if template_slide is not None:
        g_slide = next(
            (s for s in template_slides if _slide_number_of(s) == int(template_slide)),
            None,
        )
    pinned = g_slide is not None
    # Frame a centre-panel panorama as if overlays were absent, so a photo-grid map matches the plain map beside it.
    wall_w0 = _f(wall.get("slideWidth"), 7680)
    wall_h0 = _f(wall.get("slideHeight"), 1080)
    # Source badge plate colour: refuse template slots that belong to a differently-coloured object.
    src_plate = title_plate(w_slide, (wall_w0, wall_h0)) if w_slide is not None else None
    source_plate_color = item_rgb(src_plate) if src_plate is not None else None
    panel = None
    if w_slide is not None:
        w_vis0 = [it for it in w_slide.get("items") or [] if is_visible(it, wall_w0, wall_h0)]
        panel = centre_panel_image(w_vis0, wall_w0, wall_h0, float(dest_w), float(dest_h))
    framing_slide = _slide_for_panel_framing(w_slide, panel) if (w_slide and panel) else w_slide
    if g_slide is None:
        g_slide = _best_matching_slide(
            framing_slide,
            template_slides,
            wall_size=(wall_w0, wall_h0),
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
        w_items = [it for it in w_slide.get("items") or [] if is_visible(it, wall_w, wall_h)]
        g_items = [it for it in g_slide.get("items") or [] if is_visible(it, dest_w, dest_h)]
        framing_imgs = [it for it in (framing_slide.get("items") or []) if is_visible(it, wall_w, wall_h)]
        w_imgs = [it for it in framing_imgs if is_pairable_image(it)]
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
        # No template framing: cover the centre-panel panorama, not the whole wall (side panels are chrome the 16:9 crop sheds).
        cover_src = effective_wall_map_src(wall, panel) if panel is not None else map_src
        recipe = recipe_from_cover(cover_src, dest_w=dest_w, dest_h=dest_h)
        recipe["source"] = "cover-fallback"
        recipe["templateSlide"] = _slide_number_of(g_slide) if g_slide else None
        recipe["framingPinned"] = pinned
        recipe["pairQuality"] = 0
        recipe["groups"] = [
            {
                **affine_from_rects(cover_src, _rect_from_dict(recipe["mapDst"]) or cover_src).as_dict(),
                "src": cover_src.as_dict(),
                "dst": recipe["mapDst"],
                "members": 0,
            }
        ]
        return _attach_text_style(recipe, template_slides, source_plate_color=source_plate_color)
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
        "pairQuality": max((len(g["members"]) for g in grouped), default=0),
        "templateSlide": (_slide_number_of(g_slide) if g_slide else None),
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
    return _attach_text_style(recipe, template_slides, source_plate_color=source_plate_color)


def cg_layout_name(name: str) -> str:
    """Wall `MAP BLANK` → CG `MAP BLANK (16:9)`. Already-suffixed names stay put."""
    text = (name or "").strip()
    if not text:
        return ""
    if re.search(r"\(16:9\)\s*$", text):
        return text
    return f"{text} (16:9)"


# Cover sources crop to the frame centre and shed what lies beyond; a map framing places the whole page.
_COVER_SOURCES = frozenset({"template-cover", "cover-fallback", "sibling-affine"})


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
# PAIR_UNIFORM_TOLERANCE: max relative sx/sy disagreement for one uniform scale.
PAIR_UNIFORM_TOLERANCE = 0.05


def uniform_pairs(
    pairs: Iterable[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    """Keep pairs one uniform scale can explain; disagreeing sx/sy cannot teach an Affine."""
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
    """Drop clusters whose scale no other object agrees with; a lone mismatch can vanish a country."""
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
    """Nearest cluster that can hold this object; smallest-area ties used to let an overlay steal the map."""
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
    return list(_groups_from_recipe(recipe))


def title_plate(slide: dict, slide_size: tuple[float, float] | None = None) -> dict | None:
    """Badge plate: a short lettered shape, not the largest shape (side columns are taller)."""
    items = slide.get("items") or []
    texts = [
        it
        for it in items
        if (it.get("kind") or "") == "text" and (it.get("text") or "").strip()
    ]
    if not texts:
        return None
    best: dict | None = None
    best_key: tuple[float, float] | None = None
    for item in items:
        if (item.get("kind") or "") != "shape":
            continue
        w, h = _f(item.get("w")), _f(item.get("h"))
        if w <= PIN_KIND_MAX and h <= PIN_KIND_MAX:
            continue
        if slide_size and is_backdrop(item, slide_size[0], slide_size[1]):
            continue
        if slide_size and slide_size[1] > 0 and h > slide_size[1] * PLATE_MAX_H_FRACTION:
            continue
        rect = item_rect(item)
        if not any(point_in_rect(*item_center(t), rect) for t in texts):
            continue
        key = (-(w * h), rect.y)
        if best_key is None or key < best_key:
            best_key, best = key, item
    return best


def slide_title_item(
    slide: dict, slide_size: tuple[float, float] | None = None
) -> dict | None:
    """Title by `cg.title_phrases`, else the single text on the plate."""
    for item in slide.get("items") or []:
        if is_title_item(item) and _f(item.get("w")) > 0:
            return item
    plate = title_plate(slide, slide_size)
    if plate is None:
        return None
    rect = item_rect(plate)
    inside = [
        it
        for it in slide.get("items") or []
        if (it.get("kind") or "") == "text"
        and (it.get("text") or "").strip()
        and _f(it.get("w")) > 0
        and point_in_rect(*item_center(it), rect)
    ]
    if len(inside) != 1:
        return None
    return inside[0]


def slide_body_text_item(
    slide: dict, slide_size: tuple[float, float] | None = None
) -> dict | None:
    """Largest non-title paragraph (≥ BODY_TEXT_MIN_CHARS); church-name lists are not body text."""
    title = slide_title_item(slide, slide_size)
    if title is None:
        return None
    title_rect = item_rect(title)
    title_area = title_rect.w * title_rect.h
    best: dict | None = None
    best_area = 0.0
    for item in slide.get("items") or []:
        if (item.get("kind") or "") != "text" or not (item.get("text") or "").strip():
            continue
        if item is title or is_placeholder_text(item):
            continue
        if is_list_item(item):
            continue
        r = item_rect(item)
        area = r.w * r.h
        if area > best_area:
            best, best_area = item, area
    if best is None or best_area <= title_area:
        return None
    if len((best.get("text") or "").strip()) < BODY_TEXT_MIN_CHARS:
        return None
    return best


def _norm_for_overlay(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip().lower()


def sparkle_overlays(
    slide: dict, body_item: dict | None
) -> set[int]:
    """Emphasis copies of body phrases (substring + overlap); they take the body's final size."""
    if body_item is None:
        return set()
    body_text = _norm_for_overlay(body_item.get("text") or "")
    if not body_text:
        return set()
    body_rect = item_rect(body_item)
    out: set[int] = set()
    for item in slide.get("items") or []:
        if item is body_item or (item.get("kind") or "") != "text":
            continue
        phrase = _norm_for_overlay(item.get("text") or "")
        if not phrase or len(phrase) >= len(body_text):
            continue
        if phrase in body_text and _rects_overlap(item_rect(item), body_rect):
            out.add(id(item))
    return out


COINCIDENT_DUP_TOL = 4.0


def coincident_duplicate_ids(items: list[dict]) -> set[int]:
    """Magic-move leftover group/text copies at the same spot; images are never deduped (stacked map layers)."""
    kept: list[tuple[str, Rect, str, int]] = []
    dup: set[int] = set()
    for item in items:
        kind = str(item.get("kind") or "")
        if kind not in {"group", "text"}:
            continue
        rect = item_rect(item)
        sig = (
            (item.get("text") or "").strip()
            if kind == "text"
            else str(item.get("childCount") or len(item.get("children") or []))
        )
        for k2, r2, s2, _ in kept:
            if (
                k2 == kind
                and s2 == sig
                and abs(rect.x - r2.x) <= COINCIDENT_DUP_TOL
                and abs(rect.y - r2.y) <= COINCIDENT_DUP_TOL
                and abs(rect.w - r2.w) <= COINCIDENT_DUP_TOL
                and abs(rect.h - r2.h) <= COINCIDENT_DUP_TOL
            ):
                dup.add(id(item))
                break
        else:
            kept.append((kind, rect, sig, id(item)))
    return dup


def badge_members(slide: dict, title: dict) -> list[dict]:
    """Plate, logo and rule sharing the title's box — the badge minus its words."""
    src = item_rect(title)
    out: list[dict] = []
    for item in slide.get("items") or []:
        if item is title or is_map_item(item) or is_pin_item(item) or is_placeholder_text(item):
            continue
        cx, cy = item_center(item)
        if point_in_rect(cx, cy, src, TITLE_NEAR_PAD):
            out.append(item)
    return out


def badge_plate_members(slide: dict, plate: dict) -> list[dict]:
    """Badge by plate, not wording — a multi-word badge has no single title."""
    src = item_rect(plate)
    out: list[dict] = []
    for item in slide.get("items") or []:
        if is_map_item(item) or is_pin_item(item) or is_placeholder_text(item):
            continue
        if item.get("duplicateOf"):
            continue
        if item is plate:
            out.append(item)
            continue
        if point_in_rect(*item_center(item), src, BADGE_PLATE_PAD):
            out.append(item)
    return out


def badge_slot_keys(members: Iterable[dict]) -> dict[int, str]:
    """Name badge objects `kind:n` largest-first; z-order differs between wall and template."""
    counts: dict[str, int] = {}
    keys: dict[int, str] = {}
    ordered = sorted(
        members,
        key=lambda it: (-(_f(it.get("w")) * _f(it.get("h"))), _f(it.get("x"))),
    )
    for item in ordered:
        kind = str(item.get("kind") or "item")
        n = counts.get(kind, 0)
        counts[kind] = n + 1
        keys[id(item)] = f"{kind}:{n}"
    return keys


def template_badge_slots(
    slides: list[dict], slide_size: tuple[float, float] | None = None
) -> dict[str, dict[str, float]]:
    """Template badge rects; plate/logo/title each moved by a different ratio so no single affine works."""
    for slide in slides:
        plate = title_plate(slide, slide_size)
        if plate is None:
            continue
        title = slide_title_item(slide, slide_size)
        members = [it for it in badge_plate_members(slide, plate) if it is not title]
        if not members:
            continue
        keys = badge_slot_keys(members)
        return {keys[id(it)]: item_rect(it).as_dict() for it in members}
    return {}


def template_badge_plate(
    slides: list[dict], slide_size: tuple[float, float] | None = None
) -> Rect | None:
    """Template badge-plate rect, from the same slide as the slots."""
    for slide in slides:
        plate = title_plate(slide, slide_size)
        if plate is None:
            continue
        title = slide_title_item(slide, slide_size)
        members = [it for it in badge_plate_members(slide, plate) if it is not title]
        if not members:
            continue
        return item_rect(plate)
    return None


def _title_badge(
    slide: dict, recipe: dict[str, Any], slide_size: tuple[float, float] | None = None
) -> tuple[Affine | None, Rect | None, set[int], dict[int, str], dict | None]:
    """Globe, plate and title sharing the plate (or title box if no plate)."""
    title = slide_title_item(slide, slide_size)
    plate = title_plate(slide, slide_size)
    plate_dst = _rect_from_dict(recipe.get("badgePlateDst"))
    # Plate-to-plate badge affine. Title-box anchoring scaled the logo/plate wrong when the wall title was wider.
    if plate is not None and plate_dst is not None and plate_dst.w > 0:
        src = item_rect(plate)
        if src.w > 0 and src.h > 0:
            members = badge_plate_members(slide, plate)
            rest = [it for it in members if it is not title]
            ids: set[int] = {id(it) for it in members}
            if title is not None:
                ids.add(id(title))
            return affine_from_rects(src, plate_dst), src, ids, badge_slot_keys(rest), title
    dst = _rect_from_dict(recipe.get("titleDst"))
    if title is None or dst is None or dst.w <= 0:
        return None, None, set(), {}, title
    src = item_rect(title)
    rest = badge_members(slide, title)
    members = [title, *rest]
    ids = {id(it) for it in members}
    slots = badge_slot_keys(rest)
    aff = affine_from_rects(src, dst)
    return aff, src, ids, slots, title


def classify_item(
    item: dict,
    map_src: Rect | None = None,
    title: dict | None = None,
    group_child_text: str | None = None,
) -> str:
    """Pass the resolved title so a church-named heading is not packed as a list.

    ``group_child_text`` is this group's DFS leaf-text signature (``slide['groupChildText']``,
    keyed by kindIndex — see ``child_resize_report``). A caption-bearing group (normalized
    text >= 3 chars, e.g. "UPG"/"CHC"/a city name) is never a pin and must reach the font
    pass; a numeral/letter dot-pin label stays too short and stays a pin. Only the
    size/proximity branch of ``is_pin_item`` can lose text-bearing groups this way — the
    filename/movie short-circuits there are never overruled by text.
    """
    if (item.get("kind") or "") == "line":
        return "line"
    if is_map_item(item, map_src):
        return "map"
    if is_pin_item(item, map_src):
        name = file_name(item)
        kind = item.get("kind") or ""
        if not (PIN_NAME_RE.search(name) or kind == "movie"):
            if len((group_child_text or "").strip()) >= 3:
                return "other"
        return "pin"
    if title is not None:
        if item is title:
            return "title"
    elif is_title_item(item):
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


def _source_face(item: dict) -> str | None:
    """Item's own font, or None. A matched swatch lends size only — never overwrite source colour/face."""
    return str(item.get("font") or "").strip() or None


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
        return mapped, dst_size, font_name, colour
    if aff is not None:
        origin = aff.apply_rect(Rect(src.x, src.y, 1.0, 1.0))
        scale = min(aff.s, TEXT_DOWN_SCALE)
        mapped = Rect(origin.x, origin.y, max(8.0, src.w * scale), max(8.0, src.h * scale))
        font = max(8.0, wall_font * scale) if wall_font else None
        return mapped, font, font_name, colour
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


def _pack_left_groups(groups: list["ItemTransform"], recipe: dict[str, Any]) -> None:
    """Re-place left-column groups parked at x=16. Group width does not scale children, so only move."""
    if len(groups) < 2:
        return
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    order = sorted(range(len(groups)), key=lambda i: (groups[i].src.y, groups[i].src.x))
    boxes = [Rect(groups[i].x, groups[i].y, groups[i].w, groups[i].h) for i in order]
    placed = pack_columns_from_left(boxes, dest_w, dest_h)
    for idx, rect in zip(order, placed, strict=True):
        groups[idx].x = rect.x
        groups[idx].y = rect.y


# FIT_MAX_DELTA_FRACTION: max body nudge back on-screen, so it stays near where it was placed.
FIT_MAX_DELTA_FRACTION = 0.10
FIT_MARGIN = 8.0


def _fully_on_frame(r: Rect, dest_w: float, dest_h: float) -> bool:
    return r.x >= 0 and r.y >= 0 and r.x + r.w <= dest_w and r.y + r.h <= dest_h


def _couple_overlays_to_body(
    body_tf: ItemTransform,
    body_wall: Rect,
    overlays: list[tuple[ItemTransform, Rect]],
) -> None:
    """Re-seat sparkle overlays on the body after it has been placed and fitted."""
    if body_wall.w <= 0 or body_wall.h <= 0:
        return
    sx = body_tf.w / body_wall.w
    sy = body_tf.h / body_wall.h
    for ov_tf, ov_wall in overlays:
        ov_tf.x = body_tf.x + (ov_wall.x - body_wall.x) * sx
        ov_tf.y = body_tf.y + (ov_wall.y - body_wall.y) * sy
        ov_tf.w = max(8.0, ov_wall.w * sx)
        ov_tf.h = max(8.0, ov_wall.h * sy)


def _fit_body_to_frame(t: ItemTransform, dest_w: float, dest_h: float) -> None:
    """Narrow/nudge only the body verse; labels and plates that bleed off an edge stay put."""
    if dest_w <= 0 or dest_h <= 0:
        return
    rect = Rect(t.x, t.y, t.w, t.h)
    if _fully_on_frame(rect, dest_w, dest_h):
        return
    max_dx = dest_w * FIT_MAX_DELTA_FRACTION
    max_dy = dest_h * FIT_MAX_DELTA_FRACTION
    if t.x < 0:
        t.x += min(-t.x, max_dx)
    elif t.x + t.w > dest_w:
        t.x += max(dest_w - (t.x + t.w), -max_dx)
    if t.y < 0:
        t.y += min(-t.y, max_dy)
    elif t.y + t.h > dest_h:
        t.y += max(dest_h - (t.y + t.h), -max_dy)
    if t.x < FIT_MARGIN:
        t.x = FIT_MARGIN
    if t.x + t.w > dest_w - FIT_MARGIN:
        t.w = max(FIT_MARGIN, dest_w - FIT_MARGIN - t.x)


def _hide_item_transform(
    item: dict, number: int, item_index: int, kind_index: int
) -> ItemTransform:
    """role=hide: delete after geometry. Skipping lets the 16:9 canvas scale it back on-frame."""
    return ItemTransform(
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


def plan_slide_transforms(
    slide: dict,
    recipe: dict[str, Any],
    *,
    include_lists: bool = False,
    wall_size: tuple[float, float] | None = None,
    defer_list_packing: bool = False,
    free_text_keys: set[tuple[str, int]] | None = None,
    child_resize_report: list[dict[str, Any]] | None = None,
    badge_raise_report: list[dict[str, Any]] | None = None,
) -> list[ItemTransform]:
    groups = _groups_for_slide(slide, recipe)
    title_aff, title_src, title_ids, badge_slots, title_item = _title_badge(
        slide, recipe, wall_size
    )
    _badge_hits: dict[int, dict[str, Any]] = {}
    # Corner labels are not missions badges: Keynote cannot script corner radius, so a resize squares the plate. Translate at wall size.
    corner_ids: set[int] = set()
    corner_translate: Affine | None = None
    _clabel_plate = title_plate(slide, wall_size)
    _clabel_plate_dst = _rect_from_dict(recipe.get("badgePlateDst"))
    if _clabel_plate is not None and _clabel_plate_dst is not None and title_item is not None:
        _members = badge_plate_members(slide, _clabel_plate)
        _texts = [m for m in _members if (m.get("kind") or "") == "text"]
        _imgs = [m for m in _members if (m.get("kind") or "") == "image"]
        _cdw = _f(recipe.get("destWidth"), CG_WIDTH)
        _cdh = _f(recipe.get("destHeight"), CG_HEIGHT)
        _pd = _clabel_plate_dst
        _bleeds = _pd.x < 0 or _pd.y < 0 or _pd.x + _pd.w > _cdw or _pd.y + _pd.h > _cdh
        if len(_texts) == 1 and not _imgs and _bleeds:
            _ps = item_rect(_clabel_plate)
            corner_translate = Affine(1.0, _clabel_plate_dst.x - _ps.x, _clabel_plate_dst.y - _ps.y)
            corner_ids = {id(m) for m in _members}
    body_dst = _rect_from_dict(recipe.get("bodyTextDst"))
    body_for_body = slide_body_text_item(slide, wall_size)
    body_item = body_for_body if body_dst is not None else None
    badge_dsts = dict(recipe.get("badgeSlots") or {})
    styles_pre = list(recipe.get("characterStyles") or [])
    overlay_ids = sparkle_overlays(slide, body_for_body)
    body_final_size: float | None = None
    if overlay_ids and body_for_body is not None:
        if body_dst is not None and recipe.get("bodyTextFontSize"):
            body_final_size = float(recipe["bodyTextFontSize"])
        else:
            _bm, body_final_size, _bf, _bc = _style_text_box(
                body_for_body,
                _affine_for_item(body_for_body, _groups_for_slide(slide, recipe)),
                match_character_style(body_for_body, styles_pre),
            )
    body_wall_rect = item_rect(body_for_body) if (overlay_ids and body_for_body) else None
    body_tf: ItemTransform | None = None
    overlay_tfs: list[tuple[ItemTransform, Rect]] = []
    line_slots = list(recipe.get("lineSlots") or [])
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    if not groups and (map_src is None or map_dst is None):
        return []
    number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
    styles = list(recipe.get("characterStyles") or [])
    # Blind packing would drag map labels off their plates. With a preview, only free (background) text is packed — never drop labels.
    pack_lists = bool(
        include_lists
        and not defer_list_packing
        and recipe.get("listFontSize")
        and slide_has_column_lists(slide)
    )
    from obed_edom.inspect import is_duplicate_item  # noqa: PLC0415

    out: list[ItemTransform] = []
    left_groups: list[ItemTransform] = []
    wall_w, wall_h = wall_size or (0.0, 0.0)
    group_child_text: dict[int, str] = slide.get("groupChildText") or {}
    list_count = sum(1 for it in slide.get("items") or [] if is_list_item(it))
    coincident_dups = coincident_duplicate_ids(slide.get("items") or [])
    for fallback_i, item in enumerate(slide.get("items") or []):
        if is_placeholder_text(item) or is_duplicate_item(item):
            continue
        item_index = _item_index(item, fallback_i)
        kind_index = _item_kind_index(item, item_index)
        parked_left = False
        # Hide coincident magic-move copies; skipping them lets the canvas scale ghosts back on-frame.
        if id(item) in coincident_dups:
            out.append(_hide_item_transform(item, number, item_index, kind_index))
            continue
        # Hide off-slide leftovers; the 16:9 canvas scales every still-owned object back on-frame.
        if wall_size and not is_visible(item, wall_w, wall_h):
            out.append(_hide_item_transform(item, number, item_index, kind_index))
            continue
        if is_chrome_bg(item):
            out.append(_hide_item_transform(item, number, item_index, kind_index))
            continue
        if not include_lists and is_side_panel_item(item, wall_w, wall_h):
            out.append(_hide_item_transform(item, number, item_index, kind_index))
            continue
        if corner_translate is not None and id(item) in corner_ids:
            mapped = corner_translate.apply_rect(item_rect(item))
            is_text = (item.get("kind") or "") == "text"
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind=str(item.get("kind") or "shape"),
                    x=mapped.x,
                    y=mapped.y,
                    w=mapped.w,
                    h=mapped.h,
                    locked=bool(item.get("locked")),
                    font_size=(_f(item.get("size")) or None) if is_text else None,
                    font=_source_face(item) if is_text else None,
                    color=None,
                    role="other",
                    kind_index=kind_index,
                )
            )
            continue
        aff, cluster = _group_for_item(item, groups)
        badge_dst: Rect | None = None
        if title_aff is not None and id(item) in title_ids:
            aff, cluster = title_aff, title_src
            badge_dst = _rect_from_dict(badge_dsts.get(badge_slots.get(id(item), "")))
            if badge_raise_report is not None:
                _badge_hits[id(item)] = {"kind": str(item.get("kind") or "shape"), "index": kind_index + 1}
        if cluster is None:
            cluster = map_src
        role = classify_item(item, cluster, title_item, group_child_text.get(kind_index))
        if role == "other" and aff is not None and is_layout_image(item):
            role = "map"
        if role == "other" and aff is None and (item.get("kind") or "") != "text":
            continue
        # Unticked lists drop name columns, never map labels; ≥ LIST_SUMMARY_MIN names is a list even over the map.
        loose = free_text_keys is None or (str(item.get("kind") or "text"), kind_index) in free_text_keys
        is_summary_list = list_count >= LIST_SUMMARY_MIN
        if role == "list" and not include_lists and (loose or is_summary_list):
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
                    # Title keeps source font/colour; only titleDst + titleFontSize change. Applying template colour repaints operator copy.
                    font=_source_face(item),
                    color=None,
                    role="title",
                    kind_index=kind_index,
                )
            )
            continue
        if body_dst is not None and item is body_item:
            # Body takes the template box/size. Do not set the whole-box font — Keynote flattens mixed runs.
            out.append(
                ItemTransform(
                    slide_number=number,
                    item_index=item_index,
                    kind="text",
                    x=body_dst.x,
                    y=body_dst.y,
                    w=body_dst.w,
                    h=body_dst.h,
                    locked=bool(item.get("locked")),
                    font_size=(
                        float(recipe["bodyTextFontSize"])
                        if recipe.get("bodyTextFontSize")
                        else (_f(item.get("size")) or None)
                    ),
                    font=None,
                    color=None,
                    role="other",
                    kind_index=kind_index,
                )
            )
            if item is body_for_body:
                body_tf = out[-1]
            continue
        if role == "list" and include_lists and recipe.get("listPaired") and list_count == 1:
            dst = _rect_from_dict(recipe.get("listDst"))
            style = match_character_style(item, styles)
            size_only = {"size": recipe.get("listFontSize")} if recipe.get("listFontSize") else None
            mapped, font, _face, _colour = _style_text_box(item, None, style or size_only)
            if dst is not None:
                mapped = Rect(dst.x, dst.y, mapped.w, mapped.h)
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
                    font=_source_face(item) if style else None,
                    color=None,
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
                    font=_source_face(item) if style else None,
                    color=None,
                    role="list",
                    kind_index=kind_index,
                )
            )
            continue
        if role in {"list", "other"} and (item.get("kind") or "") == "text":
            style = match_character_style(item, styles)
            mapped, font, _face, _colour = _style_text_box(item, aff, style)
            if id(item) in overlay_ids and body_final_size is not None:
                src = item_rect(item)
                own = _f(item.get("size")) or body_final_size
                ratio = body_final_size / own if own > 0 else 1.0
                if aff is not None:
                    origin = aff.apply_rect(Rect(src.x, src.y, 1.0, 1.0))
                    mapped = Rect(origin.x, origin.y, max(8.0, src.w * ratio), max(8.0, src.h * ratio))
                else:
                    mapped = Rect(src.x, src.y, max(8.0, src.w * ratio), max(8.0, src.h * ratio))
                font = body_final_size
            # Unpaired LW text keeps source font/colour; a swatch may change size only. Never set whole-box font on mixed runs.
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
                    font=_source_face(item) if style else None,
                    color=None,
                    role="other" if role == "other" else "list",
                    kind_index=kind_index,
                )
            )
            if item is body_for_body:
                body_tf = out[-1]
            elif id(item) in overlay_ids:
                overlay_tfs.append((out[-1], item_rect(item)))
            continue
        if badge_dst is not None:
            mapped = badge_dst
        elif aff is None and map_src and map_dst:
            mapped = map_rect(item_rect(item), map_src, map_dst)
        elif aff is not None:
            mapped = aff.apply_rect(item_rect(item))
        else:
            continue
        if wall_size and is_backdrop(item, wall_w, wall_h):
            # A full-canvas backdrop must sit flush at the top; a translate-only affine
            # (e.g. inherited from the title slot) can otherwise pin it below y=0.
            mapped = Rect(mapped.x, 0.0, mapped.w, mapped.h)
            if mapped.h < CG_HEIGHT:
                warnings.warn(
                    f"backdrop on slide {number} pinned to y=0 with h={mapped.h} < CG_HEIGHT"
                )
        if str(item.get("kind") or "") == "group" and role == "other":
            # The map affine can throw a left-column infographic off the CG's left edge
            # (x≈-900); clamp it back on-canvas. Keep the affine-scaled w/h — the geometry
            # pass scales grouped children (AS and JXA both do on Keynote 15.3.1), so the
            # old source-w/h override is obsolete and only made the box oversized.
            if mapped.x < 16:
                mapped = Rect(16.0, mapped.y, mapped.w, mapped.h)
            if child_resize_report is not None:
                _gct = slide.get("groupChildText") or {}
                _src_w = item_rect(item).w
                child_resize_report.append(
                    {
                        "slide": number,
                        "groupIndex": kind_index + 1,
                        "childSig": _gct.get(kind_index),
                        # Group frame scales by this; fonts don't, so the pass scales them.
                        "s": (mapped.w / _src_w) if _src_w else 1.0,
                    }
                )
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
        if role == "line" and kind_index < len(line_slots):
            slot = line_slots[kind_index]
            mapped = Rect(
                _f(slot.get("x")), _f(slot.get("y")), _f(slot.get("w")), _f(slot.get("h"))
            )
            if slot.get("start"):
                start = (_f(slot["start"][0]), _f(slot["start"][1]))
            if slot.get("end"):
                end = (_f(slot["end"][0]), _f(slot["end"][1]))
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
                src=item_rect(item),
            )
        )
        if parked_left:
            left_groups.append(out[-1])
    if pack_lists:
        _pack_list_transforms(out, recipe)
    _pack_left_groups(left_groups, recipe)
    if body_tf is not None:
        _fit_body_to_frame(
            body_tf,
            _f(recipe.get("destWidth"), CG_WIDTH),
            _f(recipe.get("destHeight"), CG_HEIGHT),
        )
    if body_tf is not None and overlay_tfs and body_wall_rect is not None:
        _couple_overlays_to_body(body_tf, body_wall_rect, overlay_tfs)
    # No z-order on Keynote 15.3.1; this sort is placement order only.
    role_order = {"map": 0, "pin": 1, "other": 2, "list": 3, "hide": 4, "line": 5, "title": 6}
    out.sort(
        key=lambda t: (
            role_order.get(t.role, 9),
            -(t.w * t.h) if t.role == "map" else 0.0,
        )
    )
    if badge_raise_report is not None and _badge_hits:
        # badge_slots is already largest-first (badge_slot_keys); the title goes last.
        _title_id = id(title_item) if title_item is not None else None
        _badge_order = list(badge_slots.keys())
        if _title_id is not None:
            _badge_order.append(_title_id)
        for _bid in _badge_order:
            if _bid in _badge_hits:
                badge_raise_report.append(
                    {"slide": number, "isTitle": _bid == _title_id, **_badge_hits[_bid]}
                )
    return out


def skipped_positions(payload: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for i, slide in enumerate(payload.get("slides") or []):
        if slide.get("skipped"):
            out.append(int(slide.get("number") or (i + 1)))
    return out


def to_document_range(
    payload: dict[str, Any], slide_range: SlideRange
) -> frozenset[int] | None:
    """Convert Keynote navigator numbers (skipped slides omitted) to document positions."""
    wanted = expand_slide_range(slide_range)
    if not wanted:
        return wanted
    positions: dict[int, int] = {}
    seen = 0
    for i, slide in enumerate(payload.get("slides") or []):
        if slide.get("skipped"):
            continue
        seen += 1
        positions[seen] = int(slide.get("number") or (i + 1))
    if not positions:
        return wanted
    return frozenset(positions.get(int(n), int(n)) for n in wanted)


def navigator_numbering(payload: dict[str, Any]) -> str:
    """Note when Skip Slide makes navigator numbers differ from document positions."""
    skipped = skipped_positions(payload)
    if not skipped:
        return ""
    shown: list[str] = []
    seen = 0
    for i, slide in enumerate(payload.get("slides") or []):
        position = int(slide.get("number") or (i + 1))
        if slide.get("skipped"):
            continue
        seen += 1
        if seen != position and len(shown) < 4:
            shown.append(f"{position}→{seen}")
    where = ", ".join(str(n) for n in skipped[:6]) + ("…" if len(skipped) > 6 else "")
    tail = f" Positions shift: {', '.join(shown)}…" if shown else ""
    return (
        f"{len(skipped)} slide(s) are set to Skip Slide (position {where}). "
        f"A range is read as the numbers Keynote shows; everything reported back "
        f"counts every slide, so the two differ.{tail}"
    )


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
    """`{2,4,5,6}` → `2, 4–6`. None/empty → whole deck."""
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


# Shared map+pins across duplicated wall slides; below this, remap from scratch.
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


def adjust_child_resize_indexes(
    child_resize: list[dict[str, Any]],
    transforms: list[ItemTransform],
    reuse_slides: set[int],
) -> list[dict[str, int]]:
    """One place owns which index is trustworthy: shift for deleted group hides; void reuse slides to 0."""
    group_hides: dict[int, list[int]] = {}
    for t in transforms:
        if t.role != "hide" or str(t.kind) != "group":
            continue
        ki = t.kind_index if t.kind_index is not None else t.item_index
        group_hides.setdefault(int(t.slide_number), []).append(int(ki))
    adjustments: list[dict[str, int]] = []
    for job in child_resize:
        slide = int(job["slide"])
        if slide in reuse_slides:
            adjustments.append(
                {
                    "slide": slide,
                    "from": int(job["groupIndex"]),
                    "to": 0,
                }
            )
            job["groupIndex"] = 0
            continue
        job_ki = int(job["groupIndex"]) - 1
        shift = sum(1 for ki in group_hides.get(slide, []) if ki < job_ki)
        if shift:
            adjustments.append(
                {
                    "slide": slide,
                    "from": int(job["groupIndex"]),
                    "to": int(job["groupIndex"]) - shift,
                }
            )
            job["groupIndex"] = int(job["groupIndex"]) - shift
    return adjustments


def plan_slide_reuses(
    payload: dict[str, Any],
    transforms: list[ItemTransform],
    slide_range: SlideRange = None,
) -> list[dict[str, Any]]:
    """Reuse a remapped donor when map+dots are unchanged: duplicate, strip extras, paste the
    delta; group dedup counts derive from the donor's modeled pre-dedup output state."""
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

    def _keyed(items: list[dict]) -> dict[tuple[Any, ...], dict]:
        seen: dict[tuple[Any, ...], int] = {}
        out: dict[tuple[Any, ...], dict] = {}
        for it in items:
            ck = item_content_key(it)
            ordinal = seen.get(ck, 0)
            seen[ck] = ordinal + 1
            out[(ck, ordinal)] = it
        return out

    # Output-rect map for reuse removals: donor copies drift, so JXA deletes by geometry, not wall kindIndex.
    donor_out: dict[int, dict[tuple[Any, ...], tuple[float, float, float, float]]] = {}

    def _wall_rect(it: dict) -> tuple[float, float, float, float]:
        return (_f(it.get("x")), _f(it.get("y")), _f(it.get("w")), _f(it.get("h")))

    def _out_rect(
        it: dict, spec_map: dict[tuple[str, int], ItemTransform]
    ) -> tuple[float, float, float, float]:
        wx, wy, ww, wh = _wall_rect(it)
        spec = spec_map.get((str(it.get("kind") or ""), int(it.get("kindIndex") or 0)))
        if spec is None:
            return (wx, wy, ww, wh)
        d = spec.as_dict()
        if d.get("x") is None:
            return (wx, wy, ww, wh)
        w = float(d["w"]) if d.get("w") is not None else ww
        h = float(d["h"]) if d.get("h") is not None else wh
        return (float(d["x"]), float(d["y"]), w, h)

    # Per planned slide: ordered (childSig, origin) list of its pre-dedup JXA group output.
    group_out: dict[int, list[tuple[str, tuple[str, int] | None]]] = {}

    def _record_nonreuse(num: int, sl: dict) -> None:
        smap = {_spec_key(t): t for t in (by_slide.get(num) or [])}
        donor_out[num] = {k: _out_rect(it, smap) for k, it in _keyed(_live_items(sl)).items()}
        gct = {int(k): v for k, v in (sl.get("groupChildText") or {}).items()}
        hidden = {
            int(t.kind_index if t.kind_index is not None else t.item_index)
            for t in (by_slide.get(num) or [])
            if t.role == "hide" and str(t.kind) == "group"
        }
        kis = sorted(
            int(it.get("kindIndex") or 0)
            for it in _live_items(sl)
            if str(it.get("kind") or "") == "group"
        )
        group_out[num] = [(gct[ki], ("group", ki)) for ki in kis if ki in gct and ki not in hidden]

    for slide in slides:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if not done:
            _record_nonreuse(number, slide)
            done.append((number, slide))
            continue
        curr_items = _live_items(slide)
        curr_keys = _keyed(curr_items)
        best: tuple[int, int, int, dict, list, list, list] | None = None
        for prev_n, prev in done:
            prev_items = _live_items(prev)
            prev_keys = _keyed(prev_items)
            persist = [curr_keys[k] for k in curr_keys if k in prev_keys]
            persist_pairs = [(curr_keys[k], prev_keys[k]) for k in curr_keys if k in prev_keys]
            if len(persist) < REUSE_MIN_PERSIST:
                continue
            prev_key_of = {id(it): k for k, it in prev_keys.items()}
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
                    mutate_prev_keys.add(prev_key_of[id(donor_it)])
                else:
                    add.append(it)
            remove = [it for it in remove if prev_key_of[id(it)] not in mutate_prev_keys]
            cost = len(remove) + len(add)
            rank = (len(persist), -cost)
            if best is None or rank > (best[0], -best[1]):
                best = (len(persist), cost, prev_n, prev, persist, remove, add, mutate, persist_pairs, prev_key_of)  # type: ignore[assignment]
        if best is None:
            _record_nonreuse(number, slide)
            done.append((number, slide))
            continue
        persist_n, cost, from_n, _prev, persist, remove, add, mutate, persist_pairs, prev_key_of = best  # type: ignore[misc]
        specs = by_slide.get(number) or []
        spec_map = {_spec_key(t): t for t in specs}
        donor_keys = donor_out.get(from_n, {})
        donor_out[number] = {
            k: (donor_keys[k] if k in donor_keys else _out_rect(it, spec_map))
            for k, it in curr_keys.items()
        }

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
        # Select-all paste: strip everything on the original except the add-delta first, or leftovers ride onto the finished slide.
        add_keys = {(str(p.get("kind") or ""), int(p.get("kindIndex") or 0)) for p in add_specs}
        strip_items = [
            it
            for it in (slide.get("items") or [])
            if (str(it.get("kind") or ""), int(it.get("kindIndex") or 0)) not in add_keys
        ]
        strip_builds = [
            _ref(prev)
            for curr, prev in persist_pairs
            if int(curr.get("buildCount") or 0) == 0 and int(prev.get("buildCount") or 0) > 0
        ]
        # Delete drifted copies by output rect; groups re-derive their frame after duplicate — those go to groupRemove.
        donor_gct = {int(k): v for k, v in (_prev.get("groupChildText") or {}).items()}
        target_gct = {int(k): v for k, v in (slide.get("groupChildText") or {}).items()}
        remove_refs: list[dict[str, Any]] = []
        removed_groups: list[dict] = []
        for it in remove:
            if str(it.get("kind") or "") == "group":
                removed_groups.append(it)
                continue
            ref = _ref(it)
            key = prev_key_of.get(id(it))
            rect = donor_keys.get(key) if key is not None else None
            if rect is not None:
                ref["x"], ref["y"], ref["w"], ref["h"] = rect
            remove_refs.append(ref)
        # Group counts model the donor's pre-dedup JXA OUTPUT, not its wall: all duplications
        # run before the single dedup pass, so stranded donor copies ride into the target and
        # accumulate down the chain. output = inherited entries (origin remapped through
        # persist, else stray) ++ pasted adds; keep = persisted+pasted target groups minus
        # hides; del = output − keep (real partition refs first, capped, then synthetics).
        # A keep cross-check mismatch or a stray outliving a keeper downgrades to sig-less.
        hide_keys = {
            ("group", int(t.kind_index if t.kind_index is not None else t.item_index))
            for t in specs
            if t.role == "hide" and str(t.kind) == "group"
        }
        persist_map = {
            ("group", int(prev.get("kindIndex") or 0)): ("group", int(curr.get("kindIndex") or 0))
            for curr, prev in persist_pairs
            if str(prev.get("kind") or "") == "group"
        }
        pasted_keys = [
            ("group", int(p.get("kindIndex") or 0)) for p in add_specs if p.get("kind") == "group"
        ]
        out_state: list[tuple[str, tuple[str, int] | None]] = [
            (sig, persist_map.get(origin) if origin is not None else None)
            for sig, origin in group_out[from_n]
        ]
        out_state += [(target_gct[key[1]], key) for key in pasted_keys if key[1] in target_gct]
        group_out[number] = out_state
        keep_counts: dict[str, int] = {}
        for key in [*(k for k in persist_map.values() if k not in hide_keys), *pasted_keys]:
            sig = target_gct.get(key[1])
            if sig is not None:
                keep_counts[sig] = keep_counts.get(sig, 0) + 1
        check_counts: dict[str, int] = {}
        for it in curr_items:
            ki = int(it.get("kindIndex") or 0)
            sig = target_gct.get(ki)
            if str(it.get("kind") or "") != "group" or ("group", ki) in hide_keys or sig is None:
                continue
            check_counts[sig] = check_counts.get(sig, 0) + 1
        out_counts: dict[str, int] = {}
        for sig, _origin in out_state:
            out_counts[sig] = out_counts.get(sig, 0) + 1
        sig_less = {
            s
            for s in set(keep_counts) | set(check_counts)
            if keep_counts.get(s, 0) != check_counts.get(s, 0)
        }
        for sig, count in out_counts.items():
            keep = keep_counts.get(sig, 0)
            if count <= keep or keep == 0 or sig in sig_less:
                continue
            survivors = [origin for s, origin in out_state if s == sig][-keep:]
            if any(origin is None for origin in survivors):
                sig_less.add(sig)
        group_removes: list[dict[str, Any]] = []
        removed_by_sig: dict[str, list[dict]] = {}
        for it in removed_groups:
            sig = donor_gct.get(int(it.get("kindIndex") or 0))
            if sig is None:
                group_removes.append(_ref(it))  # no donor gct: sig-less passthrough
            else:
                removed_by_sig.setdefault(sig, []).append(it)
        synth = {"kind": "group", "kindIndex": -1, "itemIndex": -1}
        for sig in dict.fromkeys([*out_counts, *removed_by_sig]):
            keep = keep_counts.get(sig, 0)
            total = max(0, out_counts.get(sig, 0) - keep)
            real = removed_by_sig.get(sig, [])
            if sig in sig_less:
                if real:
                    group_removes += [_ref(it) for it in real]
                elif total:
                    group_removes.append(dict(synth))
                continue
            n_real = min(len(real), total)
            group_removes += [
                {**_ref(it), "childSig": sig, "expectedKeep": keep} for it in real[:n_real]
            ]
            group_removes += [
                {**synth, "childSig": sig, "expectedKeep": keep} for _ in range(total - n_real)
            ]
        job: dict[str, Any] = {
            "slide": number,
            "from": from_n,
            "persist": persist_n,
            "remove": remove_refs,
            "strip": [_ref(it) for it in strip_items],
            "stripBuilds": strip_builds,
            "add": add_specs,
            "mutate": mutate_specs,
        }
        if group_removes:
            job["groupRemove"] = group_removes
        jobs.append(job)
        done.append((number, slide))
    return jobs


def visible_content_union(slide: dict, slide_w: float, slide_h: float) -> Rect | None:
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
    """True when the primary affine shrinks past fitting the whole wall into the frame."""
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    if wall_w <= 0 or wall_h <= 0 or dest_w <= 0 or dest_h <= 0:
        return False
    aff = frame_affine(recipe)
    if aff is None or aff.s <= 0:
        return False
    floor = min(dest_w / wall_w, dest_h / wall_h) * 0.9
    return aff.s < floor


def _clipped(rect: Rect, wall_w: float, wall_h: float) -> Rect:
    x0, y0 = max(rect.x, 0.0), max(rect.y, 0.0)
    x1, y1 = min(rect.x + rect.w, wall_w), min(rect.y + rect.h, wall_h)
    return Rect(x0, y0, max(x1 - x0, 0.0), max(y1 - y0, 0.0))


def _replaced_item_ids(
    slide: dict, recipe: dict[str, Any], slide_size: tuple[float, float]
) -> set[int]:
    """Items the template re-places (badge, title, body, overlays) — their affine landing is not a framing test."""
    ignore: set[int] = set()
    if recipe.get("titleDst") or recipe.get("badgeSlots") or recipe.get("badgePlateDst"):
        title = slide_title_item(slide, slide_size)
        plate = title_plate(slide, slide_size)
        if plate is not None:
            ignore |= {id(it) for it in badge_plate_members(slide, plate)}
            if title is not None:
                ignore.add(id(title))
        elif title is not None:
            ignore |= {id(title)} | {id(it) for it in badge_members(slide, title)}
    if recipe.get("bodyTextDst"):
        body = slide_body_text_item(slide, slide_size)
        if body is not None:
            ignore.add(id(body))
            ignore |= sparkle_overlays(slide, body)
    panel = centre_panel_image(
        slide.get("items") or [],
        slide_size[0],
        slide_size[1],
        _f(recipe.get("destWidth"), CG_WIDTH),
        _f(recipe.get("destHeight"), CG_HEIGHT),
    )
    if panel is not None:
        threshold = panel.w * panel.h * CENTRE_PANEL_OVERLAY_MAX_AREA_FRACTION
        for item in slide.get("items") or []:
            if is_pairable_image(item):
                r = item_rect(item)
                if r.w * r.h < threshold:
                    ignore.add(id(item))
    return ignore


def on_canvas_fraction(
    slide: dict,
    recipe: dict[str, Any],
    wall_w: float,
    wall_h: float,
) -> float:
    """Share of affine-governed art still on the CG canvas."""
    groups = _groups_from_recipe(recipe)
    map_src = _rect_from_dict(recipe.get("mapSrc"))
    map_dst = _rect_from_dict(recipe.get("mapDst"))
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    ignore = _replaced_item_ids(slide, recipe, (wall_w, wall_h))
    # A cover sheds side panels on purpose; a map framing that sends content off-frame is a failed framing.
    crop_footprint = map_src if recipe.get("source") in _COVER_SOURCES else None
    seen = inside = 0
    for item in slide.get("items") or []:
        if is_placeholder_text(item) or item.get("duplicateOf"):
            continue
        if not is_visible(item, wall_w, wall_h) or is_chrome_bg(item):
            continue
        if is_list_item(item) or id(item) in ignore:
            continue
        if crop_footprint is not None:
            cx0, _cy0 = item_center(item)
            if not (crop_footprint.x <= cx0 <= crop_footprint.x + crop_footprint.w):
                continue
        rect = _clipped(item_rect(item), wall_w, wall_h)
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


# FILL_MAX_CROP_FRACTION: fill toward cover; never crop more than this of the binding dimension.
FILL_MAX_CROP_FRACTION = 0.47


def fit_to_frame_recipe(
    slide: dict,
    wall_w: float,
    wall_h: float,
    dest_w: float,
    dest_h: float,
    *,
    margin: float = 24.0,
    max_crop: float = FILL_MAX_CROP_FRACTION,
) -> dict[str, Any] | None:
    """Last resort: fill the frame with visible content, cropping overflow (capped by FILL_MAX_CROP_FRACTION)."""
    src = visible_content_union(slide, wall_w, wall_h)
    if src is None or src.w <= 0 or src.h <= 0:
        return None
    usable_w = max(1.0, dest_w - 2 * margin)
    usable_h = max(1.0, dest_h - 2 * margin)
    fit = min(usable_w / src.w, usable_h / src.h)
    cover = max(usable_w / src.w, usable_h / src.h)
    ceiling = fit / max(1e-6, 1.0 - max_crop)
    scale = max(fit, min(cover, ceiling, 1.0))
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
    """Pack background-only text. Never drop text: crowded boxes stay at the least-overlapping spot."""
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
    """From a wall preview, which list text is free to move (pixels under the box, not rectangles)."""
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


def _framing_unusable(
    slide: dict, recipe: dict[str, Any], wall_w: float, wall_h: float, min_on_canvas: float
) -> bool:
    """A framing that throws the page off the edge or collapses it to a sliver."""
    return (
        on_canvas_fraction(slide, recipe, wall_w, wall_h) < min_on_canvas
        or is_degenerate_scale(recipe, wall_w, wall_h)
    )


def _recipe_reusing_affine(
    slide: dict, recipe: dict[str, Any], affine: Affine, wall_w: float, wall_h: float
) -> dict[str, Any] | None:
    """Re-anchor this recipe on an adjacent same-pin sibling's affine so a magic-move map stays 1:1."""
    dest_w = _f(recipe.get("destWidth"), CG_WIDTH)
    dest_h = _f(recipe.get("destHeight"), CG_HEIGHT)
    panel = centre_panel_image(slide.get("items") or [], wall_w, wall_h, dest_w, dest_h)
    src = panel or _rect_from_dict(recipe.get("mapSrc"))
    if src is None or src.w <= 0 or src.h <= 0 or affine.s <= 0:
        return None
    dst = affine.apply_rect(src)
    out = dict(recipe)
    out["mapSrc"] = src.as_dict()
    out["mapDst"] = dst.as_dict()
    out["source"] = "sibling-affine"
    out["framingPinned"] = False
    out["groups"] = [
        {**affine.as_dict(), "src": src.as_dict(), "dst": dst.as_dict(), "members": 0}
    ]
    return out


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
    side_content_slides: set[int] | None = None,
    child_resize_report: list[dict[str, Any]] | None = None,
    badge_raise_report: list[dict[str, Any]] | None = None,
    min_on_canvas: float = MIN_ON_CANVAS_FRACTION,
) -> list[ItemTransform]:
    """Plan every slide's moves. `side_content_slides` keeps side panels; skipped slides stay at wall geometry."""
    wall_w = _f(payload.get("slideWidth"), CG_WIDTH)
    wall_h = _f(payload.get("slideHeight"), CG_HEIGHT)
    transforms: list[ItemTransform] = []
    prev_number: int | None = None
    prev_pin: int | None = None
    prev_affine: Affine | None = None
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if not wants_slide(number, slide_range):
            continue
        if slide.get("skipped"):
            if skipped_slides is not None:
                skipped_slides.append(number)
            continue
        slide_recipe = recipe
        wanted = None
        if template and (template.get("slides") or []):
            single = {
                "slideWidth": payload.get("slideWidth"),
                "slideHeight": payload.get("slideHeight"),
                "slides": [slide],
            }
            wanted = (framing_overrides or {}).get(number)
            slide_recipe = learn_recipe(single, template, template_slide=wanted)
            pin_overridden = False
            reused_sibling = False
            if wanted is not None and _framing_unusable(
                slide, slide_recipe, wall_w, wall_h, min_on_canvas
            ):
                # Pinned magic-move: if this page's art pairs to a sliver, reuse the previous same-pin sibling's affine so the map stays 1:1.
                if (
                    prev_number == number - 1
                    and prev_pin == wanted
                    and prev_affine is not None
                ):
                    reused = _recipe_reusing_affine(
                        slide, slide_recipe, prev_affine, wall_w, wall_h
                    )
                    if reused is not None and not _framing_unusable(
                        slide, reused, wall_w, wall_h, min_on_canvas
                    ):
                        slide_recipe = reused
                        reused_sibling = True
                if not reused_sibling:
                    auto_recipe = learn_recipe(single, template, template_slide=None)
                    if not _framing_unusable(slide, auto_recipe, wall_w, wall_h, min_on_canvas):
                        slide_recipe = auto_recipe
                        pin_overridden = True
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
                        "pinOverridden": pin_overridden,
                        "reusedSibling": reused_sibling,
                    }
                )
        if template and (template.get("slides") or []):
            unusable = _framing_unusable(slide, slide_recipe, wall_w, wall_h, min_on_canvas)
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
        analysis = (
            analyse_free_text(
                slide, slide_recipe, preview=preview, wall_w=wall_w, wall_h=wall_h
            )
            if preview is not None
            else None
        )
        slide_lists = include_lists or (
            side_content_slides is not None and number in side_content_slides
        )
        planned = plan_slide_transforms(
            slide,
            slide_recipe,
            include_lists=slide_lists,
            wall_size=(wall_w, wall_h),
            defer_list_packing=slide_lists and analysis is not None,
            free_text_keys=analysis["free"] if analysis else None,
            child_resize_report=child_resize_report,
            badge_raise_report=badge_raise_report,
        )
        if slide_lists and analysis is not None:
            rows = _place_free_text(planned, slide, slide_recipe, analysis)
            if placement_report is not None:
                placement_report.extend(rows)
        if offframe_report is not None:
            offframe_report.extend(
                offframe_rows(planned, slide, slide_recipe, wall_w, wall_h)
            )
        transforms.extend(planned)
        used_affine = frame_affine(slide_recipe)
        prev_affine = (
            used_affine
            if used_affine is not None
            and not _framing_unusable(slide, slide_recipe, wall_w, wall_h, min_on_canvas)
            else None
        )
        prev_number = number
        prev_pin = wanted
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
    """Geometric likeness; pin count dominates because it is how many churches the page reports."""
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
    """Pair wall→gold by shape (monotonic). Text alignment fails on translated CG decks."""
    left = [s for s in wall_slides if not s.get("skipped")]
    right = [s for s in gold_slides if not s.get("skipped")]
    if not left or not right:
        return {}
    lsig = [_geometry_signature(s) for s in left]
    rsig = [_geometry_signature(s) for s in right]

    n, m = len(left), len(right)
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
    """Human transform, read off the visible base map on each side."""
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
    """Nearest unused gold point, closest pairs first — not a position sort, which mispairs unequal counts."""
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
    """Uniform scale+translation of predicted points onto gold; residual is geometric fidelity, not layout choice."""
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
    """Placement error vs a finished CG deck. goldRmse is geometric; nearestRmse is proximity noise."""
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
        "pinPairs": legacy_pins,
        "pinRmse": legacy_rmse,
    }


def summarize_plan(transforms: list[ItemTransform]) -> dict[str, int]:
    counts: dict[str, int] = {"map": 0, "pin": 0, "list": 0, "title": 0, "line": 0, "other": 0}
    for spec in transforms:
        counts[spec.role] = counts.get(spec.role, 0) + 1
    counts["total"] = len(transforms)
    return counts
