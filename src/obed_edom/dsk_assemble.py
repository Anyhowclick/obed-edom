"""DSK deck assembly: pure planning over the offline payload/classifier, plus the
AppleScript emitter that carries out the plan live -- copy-and-transform, not build-from-template.
Clip slides are force-set to `no transition effect` since the clip owns timing; the verify
report's transition note on clip slides is expected, not a defect.
"""
from __future__ import annotations

import copy
import math
import os
import re
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from obed_edom import dsk_live
from obed_edom.dsk_live import (
    DEFAULT_LAYOUT_TEMPLATE,
    DEFAULT_RSS_LIMIT_BYTES,
    DEFAULT_TRANSPARENT_LAYOUT_NAMES,
    LiveBatch,
    LayoutImportRefusal,
    _applescript_string_list,
    _as_escape,
    _ERROR_RE,
    _find_layout_by_name,
    _keynote_tell,
    _keynote_terms,
    _osascript_path,
    _theme_layout_slides,
    layout_alpha_safe,
    layout_import_lines,
    ordinal_map,
)
from obed_edom.dsk_live import check_layout_import_preconditions as _live_check_layout_import_preconditions
from obed_edom.dsk_plan import (
    Band,
    CropRefusal,
    CropSpec,
    DEFAULT_TEXT_SLIDE_WORDS,
    ItemId,
    Run,
    SlideClass,
    TextBox,
    _box_min_t,
    _content_item_aabb,
    _delete_order,
    _intersect,
    _item_object_ids,
    _TEXT_GAP_PT,
    _word_count,
    classify_deck,
    fit_heading_pt,
    fit_slide,
    fit_text_stack,
    line_count as _line_count,
    plan_crops,
    read_band,
    visible_union,
    wrapped_height,
)
from obed_edom.iwa_builds import deck_builds
from obed_edom.iwa_geometry import (
    _frame_rect,
    _geom_dict,
    _leaf_bbox,
    _mask_geom,
    _masked_rect,
    _natural_size,
    _xywha,
    compose_geometry,
)
from obed_edom.iwa_kindindex import _memberships, derive_kind_index
from obed_edom.iwa_runs import (
    _load_deck,
    _normalize_text,
    attach_group_captions,
    attach_group_child_runs,
    attach_group_child_text,
    attach_group_content_signature,
    attach_runs,
    slide_order,
)
from obed_edom.iwa_write import OfflineWriteCorrupted, reorder_drawables
from obed_edom.map_remap import CENTRE_PANEL_RECT, LW_WALL_SIZE, Rect, item_rect
from obed_edom.offline_inspect import (
    _build_data_index,
    _canvas_size,
    _data_identifier,
    offline_text_rects,
    offline_wall_payload,
)
from obed_edom.remap_keynote import _AS_KIND_NAMES, _as_num, _delete_or_hide_placeholder_lines, copy_keynote

DEFAULT_BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)
DEFAULT_MIN_TEXT_PT = 24.0
_TEXT_STACK_GAP = _TEXT_GAP_PT

LayoutPolicy = Literal["preserve", "import"]

DEFAULT_DSK_LAYOUT_NAMES: tuple[str, ...] = (
    "Verse Standard (Variation 2)",
    "Verse 1 Line (Variation 2)",
    "Point 3 Lines",
    "Point (2 Lines)",
    "Blank Black",
)


@dataclass(frozen=True)
class LayoutSlot:
    """One layout's measured slots (plan §1.2), re-measured via
    ``plan-layout/p6_template_table.py`` against the template deck. ``verse``/``text``
    are the autosize body slot (``verse`` for the two verse layouts, ``text`` for the
    two point layouts); ``badge`` is the verse reference/badge text slot; ``panel`` is
    the inherited panel artwork rect, informational only -- it is never slide-owned."""

    verse: Rect | None = None
    verse_pt: float = 45.0
    verse_align: str = "left"
    text: Rect | None = None
    text_pt: float = 45.0
    text_align: str = "centre"
    badge: Rect | None = None
    badge_pt: float = 40.0
    panel: Rect | None = None


LAYOUT_SLOTS: dict[str, LayoutSlot] = {
    "Verse Standard (Variation 2)": LayoutSlot(
        verse=Rect(53.6, 866.4, 1799.0, 177.0), verse_pt=45.0, verse_align="left",
        badge=Rect(63.1, 785.8, 933.1, 82.1), badge_pt=40.0,
        panel=Rect(25.5, 840.4, 1869.0, 213.0),
    ),
    "Verse 1 Line (Variation 2)": LayoutSlot(
        verse=Rect(53.6, 967.0, 1812.9, 73.0), verse_pt=45.0, verse_align="left",
        badge=Rect(63.1, 878.4, 945.9, 77.0), badge_pt=40.0,
        panel=Rect(26.0, 929.8, 1868.0, 120.0),
    ),
    "Point 3 Lines": LayoutSlot(
        text=Rect(53.6, 860.9, 1812.9, 177.0), text_pt=45.0, text_align="centre",
        panel=Rect(26.0, 842.9, 1868.0, 213.0),
    ),
    "Point (2 Lines)": LayoutSlot(
        text=Rect(53.6, 886.9, 1812.9, 177.0), text_pt=45.0, text_align="centre",
        panel=Rect(26.0, 893.9, 1868.0, 163.0),
    ),
    "Blank Black": LayoutSlot(),
}


LayoutSlideCategory = Literal["verse", "point", "content"]


def layout_for_slide(*, category: LayoutSlideCategory, two_column: bool, line_count: int | None) -> str | None:
    """Class -> layout mapping (plan §2.2). ``category="content"`` (image/movie/
    full-bleed) always resolves to ``Blank Black`` regardless of ``line_count``.
    ``two_column`` (D1b's hand heading+verse geometry) always resolves to
    ``Point 3 Lines`` unchanged, taking precedence over ``category``. For
    ``category="verse"``, 1 rendered line resolves to ``Verse 1 Line (Variation 2)``,
    2-3 lines to ``Verse Standard (Variation 2)``; a verse needing more than 3 lines at
    45pt in the Standard slot returns ``None`` -- the caller must route it into the
    split path (owner Q2), never a 4-line panel. For ``category="point"``, <=2 lines
    resolves to ``Point (2 Lines)``, 3 lines to ``Point 3 Lines``; more than 3 lines
    also returns ``None``."""
    if two_column:
        return "Point 3 Lines"
    if category == "content":
        return "Blank Black"
    if line_count is None:
        return None
    if category == "verse":
        if line_count <= 1:
            return "Verse 1 Line (Variation 2)"
        if line_count <= 3:
            return "Verse Standard (Variation 2)"
        return None
    if category == "point":
        if line_count <= 2:
            return "Point (2 Lines)"
        if line_count <= 3:
            return "Point 3 Lines"
        return None
    return None


def _find_verse_badge_id(cls: SlideClass, items_by_id: Mapping[ItemId, dict]) -> ItemId | None:
    """The single kept top-level ``text`` item, other than a long (verse) text, carrying
    non-empty text -- the verse reference/badge tag (GW13-shaped). ``None`` when there is
    none or more than one (ambiguous, so the slide is treated as ``point`` rather than
    guessed at)."""
    long_ids = set(cls.long_text_ids)
    candidates = [
        item_id for item_id in cls.kept
        if item_id[0] == "text" and item_id not in long_ids
        and (items_by_id.get(item_id) or {}).get("text", "").strip()
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def apply_layout_slot_rects(
    plan: AssemblyPlan,
    classes: Sequence[SlideClass],
    payload: Mapping[str, Any],
    slide_layout_names: Mapping[int, str],
) -> AssemblyPlan:
    """Snaps a verse/point slide's long text (and verse badge, when found) rect and
    45pt/40pt size to its resolved layout's slot (plan §1.2/§3 L3), instead of the
    band-fitted rect ``plan_assembly`` already computed -- covers the common
    single-long-text-box, non-two-column, non-split case; two-column slides
    (``plan.two_column``, D1b's hand geometry) and split slides (``plan.splits``, owner
    Q2) are left untouched, since both already carry their own measured placement."""
    classes_by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload.get("slides") or []}
    fits = {number: dict(rects) for number, rects in plan.fits.items()}
    text_sizes = {number: dict(sizes) for number, sizes in plan.text_sizes.items()}
    changed = False
    for number, layout_name in slide_layout_names.items():
        if number in plan.two_column or number in plan.splits:
            continue
        slot = LAYOUT_SLOTS.get(layout_name)
        if slot is None or (slot.verse is None and slot.text is None):
            continue
        cls = classes_by_number.get(number)
        if cls is None:
            continue
        long_ids = [iid for iid in cls.long_text_ids if iid[0] == "text"]
        if len(long_ids) != 1:
            continue
        long_id = long_ids[0]
        if long_id not in fits.get(number, {}):
            continue
        slide = slides_by_number.get(number) or {}
        items_by_id = {(item["kind"], item["kindIndex"]): item for item in (slide.get("items") or [])}
        if slot.verse is not None:
            fits[number][long_id] = slot.verse
            text_sizes.setdefault(number, {})[long_id] = slot.verse_pt
            badge_id = _find_verse_badge_id(cls, items_by_id)
            if badge_id is not None and slot.badge is not None and badge_id in fits.get(number, {}):
                fits[number][badge_id] = slot.badge
                text_sizes.setdefault(number, {})[badge_id] = slot.badge_pt
        elif slot.text is not None:
            fits[number][long_id] = slot.text
            text_sizes.setdefault(number, {})[long_id] = slot.text_pt
        changed = True
    if not changed:
        return plan
    return _dc_replace(plan, fits=fits, text_sizes=text_sizes)


def resolve_slide_layouts(
    payload: Mapping[str, Any],
    classes: Sequence[SlideClass],
    plan: AssemblyPlan,
) -> dict[int, str]:
    """Per kept slide (keyed by slide ``number``, plan §2.2/§3 L3): resolves the base
    layout name from the slide's own category (verse/point/content), whether it is a
    D1b two-column slide (``plan.two_column``, always ``Point 3 Lines``, hand geometry
    unchanged), and its rendered line count at 45pt in the candidate slot's width. A
    split slide (``plan.splits``, owner Q2 -- a verse needing more than 3 lines at 45pt)
    always resolves to ``Verse Standard (Variation 2)`` for a verse, ``Point 3 Lines``
    for a point -- every part shares the slide's one base layout (Keynote's
    ``duplicate slide`` copies it). A slide whose category/line-count cannot be
    determined offline (font unresolved, no single long text box) falls back to
    ``Blank Black`` rather than guessing."""
    classes_by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload.get("slides") or []}
    out: dict[int, str] = {}
    for number in plan.kept:
        cls = classes_by_number.get(number)
        if cls is None:
            out[number] = "Blank Black"
            continue
        if number in plan.two_column:
            out[number] = "Point 3 Lines"
            continue
        slide = slides_by_number.get(number) or {}
        items_by_id = {(item["kind"], item["kindIndex"]): item for item in (slide.get("items") or [])}
        long_ids = [iid for iid in cls.long_text_ids if iid[0] == "text"]
        if not cls.is_text or len(long_ids) != 1:
            out[number] = "Blank Black"
            continue
        long_id = long_ids[0]
        category: LayoutSlideCategory = "verse" if _find_verse_badge_id(cls, items_by_id) else "point"
        if number in plan.splits:
            out[number] = "Verse Standard (Variation 2)" if category == "verse" else "Point 3 Lines"
            continue
        item = items_by_id.get(long_id)
        rect = plan.fits.get(number, {}).get(long_id)
        lines = None
        if item is not None and rect is not None and rect.w > 0:
            lines = _line_count(item.get("text") or "", item.get("font") or "", 45.0, rect.w)
        name = layout_for_slide(category=category, two_column=False, line_count=lines)
        if name is None:
            name = "Verse Standard (Variation 2)" if category == "verse" else "Point 3 Lines"
        out[number] = name
    return out

_OBED_PROP_RE = re.compile(r"^OBED\t(\d+)\t([^\t]+)\t(.*)$")
_HIDDEN_RE = re.compile(r"^HIDDEN\t(\d+)\t([^\t]+)\t(title|body)$")
_MISS_RE = re.compile(r"^MISS\t(\d+)\t([^\t]+)\t(.*)$")
_ADDR_RE = re.compile(r"^(.+) (\d+) of slide \d+$")
_AS_KIND_NAMES_REV = {v: k for k, v in _AS_KIND_NAMES.items()}


def _item_id_from_addr(addr: str) -> ItemId | None:
    """Reverses `f"{name} {kindIndex + 1} of slide {ordinal}"` back to `(kind, kindIndex)`."""
    m = _ADDR_RE.match(addr)
    if not m:
        return None
    kind = _AS_KIND_NAMES_REV.get(m.group(1))
    if kind is None:
        return None
    return (kind, int(m.group(2)) - 1)


class AssemblyRefusal(ValueError):
    """A `plan_assembly` precondition failed -- refuse rather than guess."""


@dataclass(frozen=True)
class SlideDecision:
    """One slide's operator decision for the DSK assembly review page."""

    slide: int
    action: str
    anchor: str = "centre"
    keep_side: bool = False
    overlay_bake: bool = True


@dataclass(frozen=True)
class SplitPart:
    """One part of a text slide split N ways (D4/D6): its own long box, the slide's short
    items at their shared affine, and the deletes/text size that go with just this part."""

    fits: dict[ItemId, Rect]
    deletes: tuple[ItemId, ...]
    text_sizes: dict[ItemId, float]
    run_sizes: dict[ItemId, tuple[tuple[int, int, float], ...]] = field(default_factory=dict)
    stacked_ids: frozenset[ItemId] = frozenset()
    autosize: frozenset[ItemId] = frozenset()


@dataclass(frozen=True)
class AssemblyPlan:
    """For a slide in ``splits``, ``fits[number]`` holds only the short items' part-0
    row rects -- each part's own long-box rect lives in ``splits[number][part].fits``."""

    kept: tuple[int, ...]
    ordinals: dict[int, int]
    fits: dict[int, dict[ItemId, Rect]]
    deletes: dict[int, tuple[ItemId, ...]]
    clips: dict[int, tuple[Path, ItemId]]
    text_sizes: dict[int, dict[ItemId, float]]
    autosize: dict[int, frozenset[ItemId]]
    warnings: tuple[str, ...]
    canvas: tuple[int, int] = (1920, 1080)
    group_scale: dict[int, float] = field(default_factory=dict)
    group_children: dict[int, dict[int, list[dict]]] = field(default_factory=dict)
    group_text_sizes: dict[int, dict[int, float]] = field(default_factory=dict)
    group_origin: dict[int, dict[int, tuple[float, float]]] = field(default_factory=dict)
    shrink_text_sizes: dict[int, dict[ItemId, float]] = field(default_factory=dict)
    parts: dict[int, int] = field(default_factory=dict)
    ordinal_to_number: dict[int, int] = field(default_factory=dict)
    splits: dict[int, tuple[SplitPart, ...]] = field(default_factory=dict)
    run_sizes: dict[int, dict[ItemId, tuple[tuple[int, int, float], ...]]] = field(default_factory=dict)
    stacked_ids: dict[int, frozenset[ItemId]] = field(default_factory=dict)
    stack_bands: dict[int, Band] = field(default_factory=dict)
    stack_t: dict[int, float] = field(default_factory=dict)
    short_fit: dict[int, dict[ItemId, Rect]] = field(default_factory=dict)
    short_row_h: dict[int, float] = field(default_factory=dict)
    crops: dict[int, dict[ItemId, CropSpec]] = field(default_factory=dict)
    anchors: dict[int, str] = field(default_factory=dict)
    two_column: dict[int, Band] = field(default_factory=dict)
    two_column_cluster: dict[int, HeadingCluster] = field(default_factory=dict)


def _intersect(a: Rect, b: Rect) -> Rect | None:
    """`None` only on true separation; mirrors `dsk_plan._intersect`."""
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    if x1 < x0 or y1 < y0:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _union_rect(rects: Sequence[Rect]) -> Rect:
    """Mirrors ``dsk_plan._union_rect`` (private there); kept local rather than editing
    dsk_plan.py."""
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _stacked_text_rects(boxes: Sequence[TextBox], heights: dict[ItemId, float], band: Band) -> dict[ItemId, Rect]:
    """One long box per part or per slide, full band width, stacked from the band bottom
    upward in ``boxes`` order, using the heights ``fit_text_stack`` already computed (D4)."""
    total = sum(heights.values()) + _TEXT_STACK_GAP * (len(boxes) - 1)
    y = band.bottom - total
    rects: dict[ItemId, Rect] = {}
    for box in boxes:
        h = heights[box.item_id]
        rects[box.item_id] = Rect(band.x_min, y, band.width, h)
        y += h + _TEXT_STACK_GAP
    return rects


def _item_label(item_id: ItemId) -> str:
    """Log/refusal-message identifier: ``groupchild {g}:{kind}:{idx}`` for a
    ``GroupChildId``, else the bare ``kindIndex`` -- ``item_id[1]`` alone is the group's
    index for a groupchild id, not the child's (F8)."""
    if item_id[0] == "groupchild":
        return f"groupchild {item_id[1]}:{item_id[2]}:{item_id[3]}"
    return str(item_id[1])


def _refuse_on_short_row_overlap(number: int, short_fit: dict[ItemId, Rect]) -> None:
    """Refuses when a group's short-row child (badge or short label) overlaps another
    short-row item (F1) -- a pre-existing pair of ordinary short-row items may
    legitimately share one rect (e.g. a shape stacked behind its caption), so only pairs
    touching a ``GroupChildId`` -- the newly-placed entries this rule protects -- are
    checked. Compares x-intervals only, as a conservative proxy: `_short_row_rects`
    bottom-aligns every short-row rect into one row, so an x overlap there is a real
    overlap; it can also flag a pair vertically separated inside a tall row."""
    items = list(short_fit.items())
    for i, (iid_a, rect_a) in enumerate(items):
        for iid_b, rect_b in items[i + 1:]:
            if iid_a[0] != "groupchild" and iid_b[0] != "groupchild":
                continue
            if rect_a.x < rect_b.x + rect_b.w and rect_b.x < rect_a.x + rect_a.w:
                raise AssemblyRefusal(
                    f"slide {number}: short-row items {_item_label(iid_a)} and "
                    f"{_item_label(iid_b)} overlap"
                )


def _short_row_rects(short_fit: dict[ItemId, Rect], row_h: float, stack_top: float) -> dict[ItemId, Rect]:
    """Bottom-align ``short_fit``'s own rects (unchanged x/w/h) into a row whose bottom
    sits one gap above ``stack_top`` -- the badge moves with the verse, per the golden deck."""
    row_bottom = stack_top - _TEXT_STACK_GAP
    row_top = row_bottom - row_h
    return {iid: _dc_replace(rect, y=row_top + (row_h - rect.h)) for iid, rect in short_fit.items()}


def _run_size_ranges(
    item: dict, scale: float, *, item_id: ItemId | None = None, slide_number: int | None = None,
    warnings: list[str] | None = None,
) -> tuple[tuple[tuple[int, int, float], ...] | float | None, bool]:
    """Per-run 1-indexed character ranges ``(start, end, size * scale)``; a single ``float``
    (the covered run size ``* scale``) when every run shares one size; or ``(None, unresolved)``
    -- ``unresolved`` marks a size gap where the caller must preserve source sizing."""
    runs = item.get("runs") or []
    full_len = len(item.get("text") or "")
    ranges: list[tuple[int, int, float]] = []
    pos = 1
    gap = False
    for r in runs:
        text = r.get("text") or ""
        length = len(text)
        size = r.get("size")
        if length == 0:
            continue
        if size is None:
            gap = True
            pos += length
            continue
        ranges.append((pos, pos + length - 1, float(size) * scale))
        pos += length
    if not ranges:
        if gap and warnings is not None and item_id is not None:
            warnings.append(
                f"slide {slide_number} text {_item_label(item_id)}: run ranges leave a gap"
            )
        return None, gap
    covered = not gap and ranges[0][0] == 1 and ranges[-1][1] == full_len
    if covered:
        covered = all(b[0] == a[1] + 1 for a, b in zip(ranges, ranges[1:]))
    if not covered:
        if warnings is not None and item_id is not None:
            warnings.append(
                f"slide {slide_number} text {_item_label(item_id)}: run ranges leave a gap"
            )
        return None, True
    if len({round(sz, 6) for _s, _e, sz in ranges}) <= 1:
        return ranges[0][2], False
    return tuple(ranges), False


def _group_child_geometry(
    group_children: Mapping[int, Sequence[dict]], group_ki: int, child_kind: str, child_ki: int
) -> dict | None:
    for child in group_children.get(group_ki, ()):
        if child.get("kindIndex") == child_ki and child.get("kind") == child_kind:
            return child
    return None


def _text_boxes(
    long_ids: Sequence[ItemId],
    items_by_id: Mapping[ItemId, dict],
    *,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    group_child_runs: Mapping[int, Mapping[int, dict]] | None = None,
) -> tuple[list[TextBox], list[str]]:
    """``([TextBox, ...], [warning, ...])`` for ``long_ids`` in source order (y then x);
    a box whose font/size can't be resolved is omitted and warned about (D4 fallback). A
    ``GroupChildId`` reads geometry from ``group_children`` and text/font/size/runs from
    ``group_child_runs`` -- never matched back by text equality (Design A step 3)."""
    group_children = group_children or {}
    group_child_runs = group_child_runs or {}

    def sort_key(iid: ItemId) -> tuple[float, float]:
        if iid[0] == "groupchild":
            _tag, group_ki, child_kind, child_ki = iid
            child = _group_child_geometry(group_children, group_ki, child_kind, child_ki)
            if child is None:
                return (0.0, 0.0)
            return (child.get("y", child.get("cy", 0.0)), child.get("x", 0.0))
        item = items_by_id[iid]
        return (item.get("y", 0.0), item.get("x", 0.0))

    ordered = sorted(long_ids, key=sort_key)
    boxes: list[TextBox] = []
    warnings: list[str] = []
    for iid in ordered:
        if iid[0] == "groupchild":
            _tag, group_ki, _child_kind, child_ki = iid
            info = (group_child_runs.get(group_ki) or {}).get(child_ki)
            font_name = (info or {}).get("font") or None
            size = (info or {}).get("size") or None
            if not info or not font_name or not size:
                warnings.append(
                    f"group {group_ki} text {child_ki}: font/size unresolved, skipping band-stretch fit"
                )
                continue
            box = TextBox(iid, info.get("text") or "", font_name, float(size))
            boxes.append(_box_with_runs(box, info))
            continue
        item = items_by_id[iid]
        font_name = item.get("font") or None
        size = item.get("size") or None
        if not font_name or not size:
            warnings.append(f"text {iid[1]}: font/size unresolved, skipping band-stretch fit")
            continue
        box = TextBox(iid, item.get("text") or "", font_name, float(size))
        boxes.append(_box_with_runs(box, item))
    return boxes, warnings


def slide_affine_scale(
    items: Sequence[dict],
    band: Band,
    *,
    include_side: bool,
    anchor: str,
    wall: tuple[float, float],
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> float | None:
    """The one shared uniform scale ``fit_slide`` applies across a slide; ``None`` when
    the slide has no visible/fit content."""
    union = visible_union(
        items, include_side=include_side, wall=wall, group_child_text=group_child_text,
        group_child_words=group_child_words, group_children=group_children,
        text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )
    if union is None:
        return None
    fit = fit_slide(
        items, band, include_side=include_side, anchor=anchor, wall=wall, group_child_text=group_child_text,
        group_child_words=group_child_words, group_children=group_children,
        text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )
    if not fit:
        return None
    fitted_union = _union_rect(list(fit.values()))
    if union.w > 0:
        return fitted_union.w / union.w
    if union.h > 0:
        return fitted_union.h / union.h
    return None


def _discard_pending_crop_writes(pending: Sequence[tuple[Path, Path]]) -> None:
    """Best-effort delete of temp crop files planned so far; final paths are untouched."""
    for temp_path, _final_path in pending:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
    for temp_path, _final_path in pending:
        try:
            Path(temp_path).parent.rmdir()
        except OSError:
            pass


def _commit_pending_crop_writes(pending: Sequence[tuple[Path, Path]]) -> None:
    """Atomically rename every planned crop's temp file onto its final path."""
    committed: list[Path] = []
    for i, (temp_path, final_path) in enumerate(pending):
        try:
            os.replace(temp_path, final_path)
        except OSError as exc:
            for remaining_temp, _final_path in pending[i:]:
                Path(remaining_temp).unlink(missing_ok=True)
            for remaining_temp, _final_path in pending[i:]:
                try:
                    Path(remaining_temp).parent.rmdir()
                except OSError:
                    pass
            raise AssemblyRefusal(
                f"could not commit crop {final_path}: {exc}; already replaced: "
                f"{', '.join(str(p) for p in committed) or 'none'}"
            ) from exc
        committed.append(final_path)


def _slide_archive_for_number(objects: dict[str, dict], number: int) -> dict | None:
    """Raw slide archive for a 1-based payload ``number`` (same addressing as
    ``offline_wall_payload``/``slide_order``)."""
    order = slide_order(objects)
    if number < 1 or number > len(order):
        return None
    slide_id, _skipped = order[number - 1]
    return objects.get(slide_id)


def _group_has_media(signature: str | None) -> bool:
    """True when `signature` has an ``image:``/``movie:`` leaf; missing/empty is not content."""
    if not signature:
        return False
    return any(part.startswith(("image:", "movie:")) for part in signature.split("\n") if part)


_LW_ASPECT_MIN = 2.5
_LW_ASPECT_TOL = 1e-9

HEADING_COL_W = 450.0
COL_GUTTER = 8.0
NUMBER_BADGE_PT = 46.0
MAX_HEADING_PT = 80.0
MAX_HEADING_BLOCK_PT = 140.0

_HEADING_FONT_PREFIX = "ArgentCF"
_HEADING_MAX_WORDS = 5
_HEADING_NUMBER_MAX_CHARS = 2
_HEADING_CIRCLE_PT = 81.0
_HEADING_GEOM_TOL_PT = 1.0


@dataclass(frozen=True)
class HeadingCluster:
    """A point heading's three paired items: its ``ArgentCF*`` text, its point-number
    text, and the 81x81 circle behind the number (the offline payload exposes no fill
    property, so the circle is identified by geometry alone, not by fill state)."""

    heading_id: ItemId
    number_id: ItemId
    circle_id: ItemId


def _rect_of(item: dict) -> tuple[float, float, float, float]:
    return (float(item.get("x", 0.0)), float(item.get("y", 0.0)), float(item.get("w", 0.0)), float(item.get("h", 0.0)))


def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _rects_match(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tol: float) -> bool:
    return all(abs(av - bv) <= tol for av, bv in zip(a, b))


def _heading_cluster(cls: SlideClass, items_by_id: Mapping[ItemId, dict]) -> HeadingCluster | None:
    """One kept top-level ``ArgentCF*`` heading (<= 5 words) paired with the single kept
    top-level all-digit point number (<= 2 chars) found anywhere -- a second such digit
    text elsewhere always refuses -- whose rect centre lies within 1pt of the radius of
    exactly one kept textless 81x81 top-level ``shape`` (the number circle). At most one
    other kept top-level text is allowed -- besides the top-level long text itself, when
    ``cls.long_text_ids`` names one -- and it must be the verse badge: its normalised
    (whitespace-collapsed, stripped) non-empty text must match exactly one kept top-level
    shape's rect (tolerance 1pt) and normalised text, other than the circle -- measured on
    GW 46/52, where the badge is a top-level text+shape pair sharing one rect and text; on
    GW 44/50/51/53 the badge is a group child and leaves no top-level text behind. Two or
    more extra top-level texts, or an unmatched one, refuses the cluster. Requires exactly
    one long text (``cls.long_text_ids``). Never raises."""
    if len(cls.long_text_ids) != 1:
        return None
    texts: list[tuple[ItemId, dict]] = []
    shapes: list[tuple[ItemId, dict]] = []
    for item_id in cls.kept:
        kind, _kind_index = item_id
        item = items_by_id.get(item_id)
        if item is None:
            continue
        if kind == "text":
            texts.append((item_id, item))
        elif kind == "shape":
            shapes.append((item_id, item))

    circle_candidates = [
        (item_id, item)
        for item_id, item in shapes
        if not (item.get("text") or "").strip()
        and item.get("w") == _HEADING_CIRCLE_PT
        and item.get("h") == _HEADING_CIRCLE_PT
    ]
    if len(circle_candidates) != 1:
        return None
    circle_id, circle_item = circle_candidates[0]
    circle_rect = _rect_of(circle_item)

    heading_ids = [
        item_id
        for item_id, item in texts
        if (item.get("font") or "").startswith(_HEADING_FONT_PREFIX)
        and (item.get("text") or "").strip()
        and _word_count((item.get("text") or "").strip()) <= _HEADING_MAX_WORDS
    ]
    if len(heading_ids) != 1:
        return None
    heading_id = heading_ids[0]

    digit_ids = [
        item_id
        for item_id, item in texts
        if (item.get("text") or "").strip().isdigit()
        and len((item.get("text") or "").strip()) <= _HEADING_NUMBER_MAX_CHARS
    ]
    if len(digit_ids) != 1:
        return None
    number_id = digit_ids[0]
    nx, ny, nw, nh = _rect_of(items_by_id[number_id])
    centre = (nx + nw / 2.0, ny + nh / 2.0)
    cx, cy, cw, ch = circle_rect
    circle_centre = (cx + cw / 2.0, cy + ch / 2.0)
    radius = math.hypot(centre[0] - circle_centre[0], centre[1] - circle_centre[1])
    if radius > (_HEADING_CIRCLE_PT / 2.0) + _HEADING_GEOM_TOL_PT:
        return None

    long_text_ids = set(cls.long_text_ids)
    extra_texts = [
        (item_id, item)
        for item_id, item in texts
        if item_id not in (heading_id, number_id) and item_id not in long_text_ids
    ]
    if len(extra_texts) > 1:
        return None
    if extra_texts:
        badge_id, badge_item = extra_texts[0]
        badge_text = _normalise_ws(badge_item.get("text") or "")
        if not badge_text:
            return None
        rect = _rect_of(badge_item)
        matching_shapes = [
            (shape_id, shape_item)
            for shape_id, shape_item in shapes
            if shape_id != circle_id
            and _rects_match(rect, _rect_of(shape_item), _HEADING_GEOM_TOL_PT)
            and _normalise_ws(shape_item.get("text") or "") == badge_text
        ]
        if len(matching_shapes) != 1:
            return None

    return HeadingCluster(heading_id, number_id, circle_id)


def _heading_text_for_repeat_check(cls: SlideClass, items_by_id: Mapping[ItemId, dict]) -> str | None:
    """The slide's single kept top-level ``ArgentCF*`` heading text (stripped), or
    ``None`` when there is none or more than one -- used for the D1b Q1 repeat-heading
    drop, which must also see heading-only slides (no verse, so `_heading_cluster`
    itself never fires for them)."""
    candidates = [
        item.get("text", "").strip()
        for item_id, item in items_by_id.items()
        if item_id[0] == "text"
        and item_id in cls.kept
        and (item.get("font") or "").startswith(_HEADING_FONT_PREFIX)
        and (item.get("text") or "").strip()
        and _word_count((item.get("text") or "").strip()) <= _HEADING_MAX_WORDS
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _full_classes_by_number(
    payload: Mapping[str, Any],
    classes: Sequence[SlideClass],
    all_classes: Sequence[SlideClass] | None,
) -> dict[int, SlideClass]:
    """The whole deck's `SlideClass`es for `_repeat_heading_state`, so a predecessor
    outside the planning batch is classified through the exact same inputs
    (`cls.kept`, `long_text_ids`, group-child text/children, dedupe, backdrop,
    `include_side`, connection-line settings) as `_heading_cluster` requires --
    never an approximation. Prefers caller-supplied `all_classes` (the real CLI
    path: `load_assembly_inputs` already classifies the whole deck via
    `classify_deck`); else, when `classes` itself already covers every slide in
    `payload` (a synthetic single-/few-slide payload built to match `classes`),
    uses `classes` directly. There is no other fallback: reclassifying a subset
    payload without the whole deck's `include_side`/connection-line-build inputs
    previously could disagree with batch classification's `category`, which
    `_repeat_heading_state` reads -- planning a subset of a deck-backed payload
    now requires `all_classes`."""
    if all_classes is not None:
        return {c.number: c for c in all_classes}
    payload_numbers = {slide["number"] for slide in payload.get("slides") or []}
    classes_by_number = {c.number: c for c in classes}
    if payload_numbers <= classes_by_number.keys():
        return classes_by_number
    raise ValueError(
        "plan_assembly: planning a subset of the deck needs all_classes (the whole-deck classification)"
    )


def _repeat_heading_state(
    slides_by_number: Mapping[int, dict],
    full_classes_by_number: Mapping[int, SlideClass],
) -> dict[int, bool]:
    """Per slide number, whether its heading cluster repeats the immediately preceding
    non-empty slide's heading text -- walking `slides_by_number` in full deck order,
    independent of the planning batch (`kept_numbers`), so `--slides 51` alone drops
    the heading exactly like a full-deck run. Suppression additionally requires that
    predecessor to itself be heading+verse (two-column-eligible): a heading-only
    predecessor (heading cluster with no verse, e.g. GW45 "Prayer") does not suppress
    (owner-pinned rule, D1b-p2 fix round 2). A slide with no heading text breaks the
    run. `full_classes_by_number` (see `_full_classes_by_number`) must be the whole
    deck's classification, not just the planning batch's -- every predecessor is read
    through the same `_heading_cluster`/`_heading_text_for_repeat_check` as the batch
    slides, off its real `SlideClass` (`cls.kept`, group-child verses, dedupe,
    backdrop settings all included), never an approximation. A number missing from
    `full_classes_by_number` (should not happen) breaks the run, same as an empty
    slide."""
    repeats: dict[int, bool] = {}
    prev_heading_text: str | None = None
    prev_has_cluster = False
    for number in sorted(slides_by_number):
        cls = full_classes_by_number.get(number)
        if cls is None:
            prev_heading_text = None
            prev_has_cluster = False
            continue
        if cls.category == "empty":
            continue
        items_by_id = {(it["kind"], it["kindIndex"]): it for it in slides_by_number[number].get("items") or []}
        heading_text = _heading_text_for_repeat_check(cls, items_by_id)
        has_cluster = _heading_cluster(cls, items_by_id) is not None
        if (
            has_cluster
            and heading_text is not None
            and prev_heading_text is not None
            and prev_has_cluster
        ):
            repeats[number] = heading_text == prev_heading_text
        prev_heading_text = heading_text
        prev_has_cluster = has_cluster
    return repeats


def _autosize_text_ids(
    item_ids: Iterable[ItemId],
    id_by_item: Mapping[ItemId, str] | None,
    objects_graph: Mapping[str, dict] | None,
) -> frozenset[ItemId]:
    """Single detector for both `plan.autosize` and `SplitPart.autosize`: a text id is
    autosize only when the source-deck objects graph proves its raw frame height is 0
    (live r12 finding, live-probed round 2, generalised to any top-level text id, not only
    a two-column cluster's heading/numeral -- same test `iwa_geometry._compose_record`
    uses). Without a graph (no `id_by_item`/`objects_graph`), nothing is autosize -- the
    former `w == 0.0 or h == 0.0` payload heuristic is gone, since `offline_wall_payload`
    fills a genuine autosize frame's zero height with its saved `naturalSize` and so
    cannot tell autosize from fixed-frame on its own. `position` is the live visual
    top-left for an autosize box (no vertical-alignment offset applies -- probe log:
    `<scratchpad>/probe-autosize/log.txt`), so no alignment is resolved or returned."""
    ids: set[ItemId] = set()
    if id_by_item is None or objects_graph is None:
        return frozenset(ids)
    for item_id in item_ids:
        obj_id = id_by_item.get(item_id)
        obj = objects_graph.get(obj_id) if obj_id is not None else None
        if obj is None:
            continue
        geom = _geom_dict(obj)
        if _xywha(geom)[3] != 0.0:
            continue
        ids.add(item_id)
    return frozenset(ids)


def _two_column_rects(
    number: int,
    cluster: HeadingCluster,
    items_by_id: Mapping[ItemId, dict],
    band: Band,
    verse_block_top: float,
    min_text_pt: float,
    warnings: list[str],
) -> tuple[dict[ItemId, Rect], dict[ItemId, float], dict[ItemId, tuple[tuple[int, int, float], ...]], Band]:
    """Left-column rects (heading text, number circle, numeral) for a two-column
    heading+verse band (D1b Section 4); ``verse_block_top`` is the top y of the already
    -placed right column (the verse badge when present, else the verse text itself),
    used to vertically centre the left block on it. Returns
    ``(rects, text_sizes, run_sizes, left_band)``, both size maps disjoint per item id.
    Raises `AssemblyRefusal` per the Section 4 refusals (heading does not fit, or its
    font/numeral size is unresolved)."""
    left = Band(band.bottom, band.height, band.x_min, band.x_min + HEADING_COL_W, band.sample_count)
    heading_item = items_by_id[cluster.heading_id]
    heading_text = heading_item.get("text") or ""
    heading_font = heading_item.get("font") or ""
    heading_source_size = heading_item.get("size")
    number_item = items_by_id[cluster.number_id]
    numeral_source_size = number_item.get("size")
    if not heading_font or not heading_source_size or not numeral_source_size:
        raise AssemblyRefusal(
            f"slide {number}: two-column heading font or number size unresolved -- refusing to "
            "write blind"
        )
    avail_h = band.height - NUMBER_BADGE_PT - _TEXT_STACK_GAP
    heading_pt = fit_heading_pt(
        heading_text, heading_font, HEADING_COL_W, avail_h,
        max_pt=MAX_HEADING_PT, max_block_pt=MAX_HEADING_BLOCK_PT, min_pt=min_text_pt,
    )
    if heading_pt is None:
        raise AssemblyRefusal(
            f"slide {number}: two-column heading does not fit the heading column -- refusing to split"
        )
    heading_h = wrapped_height(heading_text, heading_font, heading_pt, HEADING_COL_W)
    if heading_h is None:
        raise AssemblyRefusal(f"slide {number}: two-column heading height unresolved -- refusing to write blind")

    block_h = NUMBER_BADGE_PT + _TEXT_STACK_GAP + heading_h
    right_block_centre = (verse_block_top + band.bottom) / 2.0
    circle_y = right_block_centre - block_h / 2.0
    heading_y = circle_y + NUMBER_BADGE_PT + _TEXT_STACK_GAP
    circle_x = left.x_min + HEADING_COL_W / 2.0 - NUMBER_BADGE_PT / 2.0

    rects = {
        cluster.heading_id: Rect(left.x_min, heading_y, HEADING_COL_W, heading_h),
        cluster.circle_id: Rect(circle_x, circle_y, NUMBER_BADGE_PT, NUMBER_BADGE_PT),
        cluster.number_id: Rect(circle_x, circle_y, NUMBER_BADGE_PT, NUMBER_BADGE_PT),
    }
    heading_t = heading_pt / float(heading_source_size)
    numeral_t = NUMBER_BADGE_PT / _HEADING_CIRCLE_PT
    text_sizes: dict[ItemId, float] = {}
    run_sizes: dict[ItemId, tuple[tuple[int, int, float], ...]] = {}
    for item_id, item, scale, flat_pt in (
        (cluster.heading_id, heading_item, heading_t, heading_pt),
        (cluster.number_id, number_item, numeral_t, float(numeral_source_size) * numeral_t),
    ):
        ranges, unresolved = _run_size_ranges(item, scale, item_id=item_id, slide_number=number, warnings=warnings)
        if isinstance(ranges, tuple):
            run_sizes[item_id] = ranges
        elif ranges is not None:
            text_sizes[item_id] = ranges
        else:
            if unresolved:
                warnings.append(
                    f"slide {number} text {_item_label(item_id)}: run ranges leave a gap, "
                    "preserving the flat two-column size"
                )
            text_sizes[item_id] = flat_pt
    return rects, text_sizes, run_sizes, left


def _content_ids(
    cls: SlideClass,
    *,
    group_signature: Mapping[int, str | None] | None = None,
    exclude_group_kis: Iterable[int] | None = None,
) -> list[ItemId]:
    """Kept image/movie/group item ids; text-only content never counts towards them.
    `exclude_group_kis` drops a group already used as a text carrier (its child text
    triggered the text-slide classification), matching this docstring's own rule.
    Side-only status is NOT decided here: a rotated item's true (transformed-AABB) extent
    can cross into the centre panel even though its unrotated frame does not, so that
    filter lives in `_content_visibles_by_kept`'s centre-panel intersection instead --
    only positive-area intersections count as anchoring content."""
    group_signature = group_signature or {}
    exclude = set(exclude_group_kis or ())
    ids: list[ItemId] = []
    for kind, kind_index in cls.kept:
        if kind not in ("image", "movie", "group"):
            continue
        if kind == "group" and kind_index in exclude:
            continue
        if kind == "group" and not _group_has_media(group_signature.get(kind_index)):
            continue
        ids.append((kind, kind_index))
    return ids


def _content_visibles_by_kept(items: Sequence[dict], kept: Iterable[ItemId]) -> dict[ItemId, Rect]:
    """Like ``dsk_plan._visibles_by_kept(..., include_side=False)`` but measuring each kept
    item's exact transformed AABB (``_content_item_aabb``) rather than its unrotated frame,
    so a rotated item's clip to the centre panel reflects its true visual extent."""
    kept_set = set(kept)
    visibles: dict[ItemId, Rect] = {}
    for item in items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        if item_id not in kept_set:
            continue
        visible = _intersect(_content_item_aabb(item), CENTRE_PANEL_RECT)
        if visible is not None:
            visibles[item_id] = visible
    return visibles


def _content_anchor(
    cls: SlideClass,
    items: Sequence[dict],
    *,
    wall: tuple[float, float],
    group_signature: Mapping[int, str | None] | None = None,
    include_side: bool = False,
    exclude_group_kis: Iterable[int] | None = None,
) -> str:
    """Auto anchor ("centre" or "right") for a content slide with no explicit anchor:
    the union of the kept content rects — always clipped to the centre panel,
    regardless of `keep_side`/`include_side` — being LW-dimension (w/h >= 2.5) forces
    centre; otherwise squarish items go right at 1-2 and centre at 3+. Side panels
    never count as content for anchoring (decided by `_content_visibles_by_kept`'s
    positive-area centre-panel intersection, not by their unrotated frame). `wall` and
    `include_side` are accepted but unused. `exclude_group_kis` is forwarded to
    `_content_ids` so a group used as a text carrier never anchors content."""
    content_ids = _content_ids(cls, group_signature=group_signature, exclude_group_kis=exclude_group_kis)
    if not content_ids:
        return "centre"
    visibles = _content_visibles_by_kept(items, content_ids)
    rects = [r for r in visibles.values() if r.w > 0 and r.h > 0]
    if not rects:
        return "centre"
    union = _union_rect(rects)
    if union.w / union.h >= _LW_ASPECT_MIN - _LW_ASPECT_TOL:
        return "centre"
    return "right" if len(rects) <= 2 else "centre"


def plan_assembly(
    payload: dict,
    classes: Sequence[SlideClass],
    *,
    decisions: Mapping[int, SlideDecision],
    band: Band,
    clips: Mapping[int, Path],
    runs: Mapping[int, Mapping[ItemId, Sequence[float]]] | None = None,
    min_text_pt: float = DEFAULT_MIN_TEXT_PT,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    allow_split: bool = True,
    text_fit: Literal["warn", "shrink"] = "warn",
    deck: Any = None,
    fw_deck: str | Path | None = None,
    crop_dir: str | Path | None = None,
    no_image_crop: bool = False,
    builds: Mapping[int, dict] | None = None,
    no_auto_anchor: bool = False,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
    split_overrides: Mapping[int, int] | None = None,
    all_classes: Sequence[SlideClass] | None = None,
) -> AssemblyPlan:
    """Pure planning over `payload`/`classes`, EXCEPT the cropped image files under
    `crop_dir` (unless `no_image_crop`), committed only once every slide validates.
    `all_classes`, when given, is the whole deck's classification (see
    `_full_classes_by_number`) -- used only for the repeat-heading predecessor check,
    so a `--slides` batch drops a repeated heading exactly like a full-deck run.
    Planning a subset of a deck-backed payload (`classes` narrower than `payload`'s
    slides) requires `all_classes`; omitting it then raises `ValueError`."""
    classes_by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    wall = (payload["slideWidth"], payload["slideHeight"])

    kept_numbers = sorted(
        number
        for number, decision in decisions.items()
        if decision.action in ("in_deck", "both")
        and classes_by_number[number].category != "empty"
    )
    full_classes_by_number = _full_classes_by_number(payload, classes, all_classes)
    repeat_heading_by_number = _repeat_heading_state(slides_by_number, full_classes_by_number)

    fits: dict[int, dict[ItemId, Rect]] = {}
    deletes: dict[int, tuple[ItemId, ...]] = {}
    clips_out: dict[int, tuple[Path, ItemId]] = {}
    text_sizes: dict[int, dict[ItemId, float]] = {}
    autosize: dict[int, frozenset[ItemId]] = {}
    group_scale: dict[int, float] = {}
    group_children: dict[int, dict[int, list[dict]]] = {}
    group_text_sizes: dict[int, dict[int, float]] = {}
    group_origin: dict[int, dict[int, tuple[float, float]]] = {}
    shrink_text_sizes: dict[int, dict[ItemId, float]] = {}
    parts: dict[int, int] = {}
    splits: dict[int, tuple[SplitPart, ...]] = {}
    run_sizes: dict[int, dict[ItemId, tuple[tuple[int, int, float], ...]]] = {}
    stacked_id_map: dict[int, frozenset[ItemId]] = {}
    stack_band_map: dict[int, Band] = {}
    stack_t_map: dict[int, float] = {}
    short_fit_map: dict[int, dict[ItemId, Rect]] = {}
    short_row_h_map: dict[int, float] = {}
    crops_out: dict[int, dict[ItemId, CropSpec]] = {}
    anchors_out: dict[int, str] = {}
    two_column_map: dict[int, Band] = {}
    two_column_cluster_map: dict[int, HeadingCluster] = {}
    cluster_autosize_map: dict[int, frozenset[ItemId]] = {}
    warnings: list[str] = []
    objects_graph = deck[0] if isinstance(deck, tuple) else deck
    if objects_graph is None and fw_deck is not None:
        objects_graph = _load_deck(fw_deck)[0]

    pending_crop_writes: list[tuple[Path, Path]] = []
    consumed_splits: set[int] = set()

    for number in kept_numbers:
        try:
            decision = decisions[number]
            cls = classes_by_number[number]
            slide = slides_by_number[number]
            items = slide.get("items") or []
            items_by_id = {(item["kind"], item["kindIndex"]): item for item in items}
            group_child_text = slide.get("groupChildSignature")
            group_child_words = slide.get("groupChildText")
            group_children_geo = slide.get("groupChildren") or {}
            group_child_runs_map = slide.get("groupChildRuns") or {}
            warnings.extend(f"slide {number}: {w}" for w in cls.mirror_warnings)

            text_group_kis = {iid[1] for iid in cls.long_text_ids if iid[0] == "groupchild"}
            for group_ki in text_group_kis:
                for child in group_children_geo.get(group_ki, ()):
                    if child.get("group_path"):
                        raise AssemblyRefusal(
                            f"slide {number}: group {group_ki} child {child['kindIndex']} is nested "
                            "inside a text-triggering group -- unsupported"
                        )

            # Finding 2 (D1 Codex fix round): a group's DFS word join can exceed
            # ``text_slide_words`` (making the group text-triggering) even when NONE of
            # its children is a supported AUTOSIZE text child -- a fixed-frame text-
            # bearing child never contributes a long groupchild id (`_is_text_slide_kept`,
            # D1 Codex fix round 2: autosize-only, regardless of its own ``kind``), so the
            # group would be silently left off `text_group_kis`, taking the normal affine
            # path (keeping a full-wall photo) instead. Piece D1 handles autosize group
            # text only -- refuse explicitly rather than write that blind. The check is
            # kind-agnostic (any ``has_text`` + ``autosize is False`` child, not just one
            # whose ``kind`` collapsed to ``shape``); the group-level exemption above
            # (``group_ki in text_group_kis``) still lets a real badge-only fixed-frame
            # child through untouched once the group has a supported autosize verse.
            for iid in cls.kept:
                if iid[0] != "group":
                    continue
                group_ki = iid[1]
                if group_ki in text_group_kis:
                    continue
                if _word_count(group_child_words.get(group_ki) if group_child_words else None) <= text_slide_words:
                    continue
                for child in group_children_geo.get(group_ki, ()):
                    if child.get("has_text") and child.get("autosize") is False:
                        raise AssemblyRefusal(
                            f"slide {number}: fixed-frame text inside group {group_ki} unsupported "
                            "(piece D1 handles autosize group text only)"
                        )

            if decision.anchor in (None, "auto"):
                anchor = "centre" if no_auto_anchor else _content_anchor(
                    cls, items, wall=wall,
                    group_signature=slide.get("groupChildSignature"),
                    exclude_group_kis=text_group_kis,
                )
            else:
                anchor = decision.anchor
            anchors_out[number] = anchor

            fit = fit_slide(
                items,
                band,
                include_side=decision.keep_side,
                anchor=anchor,
                wall=wall,
                group_child_text=group_child_text,
                group_child_words=group_child_words,
                group_children=group_children_geo,
                text_slide_words=text_slide_words,
                no_dedupe=no_dedupe,
                no_drop_panel_backdrop=no_drop_panel_backdrop,
            )
            fits[number] = fit

            id_by_item: dict[ItemId, str] | None = None
            if objects_graph is not None:
                id_slide_archive = _slide_archive_for_number(objects_graph, number)
                if id_slide_archive is not None:
                    id_by_item = _item_object_ids(id_slide_archive, objects_graph)

            slide_crops: dict[ItemId, CropSpec] = {}
            if objects_graph is not None and fw_deck is not None:
                slide_archive = _slide_archive_for_number(objects_graph, number)
                if slide_archive is not None:
                    build_target_ids = {
                        (b["kind"], b["kindIndex"])
                        for b in ((builds or {}).get(number) or {}).get("builds") or []
                    }
                    try:
                        slide_crops, crop_warnings, slide_pending = plan_crops(
                            fw_deck,
                            slide_archive,
                            objects_graph,
                            items,
                            cls.kept,
                            include_side=decision.keep_side,
                            crop_dir=crop_dir if crop_dir is not None else Path(fw_deck).parent / "crops",
                            number=number,
                            build_targets=build_target_ids,
                            dry_run=no_image_crop,
                        )
                    except CropRefusal as exc:
                        raise AssemblyRefusal(str(exc)) from exc
                    warnings.extend(f"slide {number}: {w}" for w in crop_warnings)
                    pending_crop_writes.extend(slide_pending)
            if slide_crops:
                crops_out[number] = slide_crops

            top_level_movie_ids = tuple(iid for iid in cls.kept if iid[0] == "movie")
            if cls.category in ("movie", "mixed") and cls.movie_count > len(top_level_movie_ids):
                raise AssemblyRefusal(f"slide {number}: movie nested in group unsupported")

            group_ids = [iid for iid in cls.kept if iid[0] == "group"]
            if group_ids:
                scale = slide_affine_scale(
                    items,
                    band,
                    include_side=decision.keep_side,
                    anchor=anchor,
                    wall=wall,
                    group_child_text=group_child_text,
                    group_child_words=group_child_words,
                    group_children=group_children_geo,
                    text_slide_words=text_slide_words,
                    no_dedupe=no_dedupe,
                    no_drop_panel_backdrop=no_drop_panel_backdrop,
                )
                if scale is not None:
                    group_scale[number] = scale
                slide_group_children: dict[int, list[dict]] = {}
                slide_group_text_sizes: dict[int, float] = {}
                slide_group_origin: dict[int, tuple[float, float]] = {}
                children_payload = slide.get("groupChildren") or {}
                child_text_payload = slide.get("groupChildText") or {}
                caption_payload = slide.get("groupCaption") or {}
                for iid in group_ids:
                    kind_index = iid[1]
                    has_text = bool((child_text_payload.get(kind_index) or "").strip())
                    has_media = _group_has_media(group_child_text.get(kind_index) if group_child_text else None)
                    children = children_payload.get(kind_index)
                    if (has_text or has_media) and children is None:
                        raise AssemblyRefusal(
                            f"slide {number}: group {kind_index} has text or media but no offline "
                            "child metadata (nested/rotated/masked group, or an autosize child "
                            "whose naturalSize disagrees with its frame) -- refusing to write blind"
                        )
                    # A group whose child text triggered the text-slide classification
                    # takes no affine path (Design A step 4) -- its children are stacked
                    # into the band below instead, so it is excluded here entirely.
                    if children is not None and kind_index not in text_group_kis:
                        slide_group_children[kind_index] = children
                        group_item = items_by_id.get(iid)
                        if group_item is not None:
                            slide_group_origin[kind_index] = (group_item.get("x", 0.0), group_item.get("y", 0.0))
                        caption = caption_payload.get(kind_index)
                        if caption is not None and caption.get("size") and scale is not None:
                            slide_group_text_sizes[kind_index] = caption["size"] * scale
                if slide_group_children:
                    group_children[number] = slide_group_children
                if slide_group_text_sizes:
                    group_text_sizes[number] = slide_group_text_sizes
                if slide_group_origin:
                    group_origin[number] = slide_group_origin

            dropped = () if decision.keep_side else cls.dropped_side
            movie_ids: tuple[ItemId, ...] = ()
            if cls.category in ("movie", "mixed"):
                movie_ids = tuple(iid for iid in cls.kept if iid[0] == "movie")

            all_ids = {(item["kind"], item["kindIndex"]) for item in items}
            excluded_ids = all_ids - set(cls.kept) - set(cls.dropped_side)

            crop_ids = tuple(sorted(slide_crops.keys()))
            base_deletes = _delete_order(
                list(dropped) + list(movie_ids) + list(excluded_ids) + list(crop_ids), id_by_item
            )
            deletes[number] = base_deletes

            cluster = _heading_cluster(cls, items_by_id)
            is_repeat_heading = cluster is not None and repeat_heading_by_number.get(number, False)
            cluster_ids: set[ItemId] = set()
            if cluster is not None:
                cluster_ids = {cluster.heading_id, cluster.number_id, cluster.circle_id}
            if is_repeat_heading:
                for cid in cluster_ids:
                    fit.pop(cid, None)
                deletes[number] = _delete_order(list(base_deletes) + list(cluster_ids), id_by_item)
                cluster = None
                cluster_ids = set()
            elif cluster is not None and slide_crops:
                raise AssemblyRefusal(
                    f"slide {number}: two-column verse and image crop both apply -- unsupported"
                )

            stacked_ids: set[ItemId] = set()
            stacked_text_sizes: dict[ItemId, float] = {}
            stacked_shrink_only_sizes: dict[ItemId, float] = {}
            stacked_run_sizes: dict[ItemId, tuple[tuple[int, int, float], ...]] = {}
            if cls.is_text and cls.long_text_ids:
                long_ids = []
                for iid in cls.long_text_ids:
                    if iid[0] == "groupchild":
                        _tag, g_ki, _c_kind, c_ki = iid
                        c_info = (group_child_runs_map.get(g_ki) or {}).get(c_ki) or {}
                        if not (c_info.get("text") and c_info.get("font") and c_info.get("size")):
                            raise AssemblyRefusal(
                                f"slide {number}: group {g_ki} child {c_ki} text/font could not be "
                                "resolved -- refusing to write blind"
                            )
                        if _word_count(c_info["text"]) > text_slide_words:
                            long_ids.append(iid)
                    elif iid in fit:
                        long_ids.append(iid)
                boxes, box_warnings = _text_boxes(
                    long_ids, items_by_id,
                    group_children=group_children_geo, group_child_runs=group_child_runs_map,
                )
                warnings.extend(f"slide {number}: {w}" for w in box_warnings)
                if boxes and len(boxes) == len(long_ids):
                    long_id_set = set(long_ids)
                    group_top_ids = {("group", ki) for ki in text_group_kis}
                    # The group's own affine-fitted rect is captured before it is popped
                    # below -- a short (non-stacked) child of the same group is placed
                    # relative to it rather than centred, so it does not collide with
                    # other short-row content (F1).
                    group_top_rects = {ki: fit.get(("group", ki)) for ki in text_group_kis}
                    short_fit = {
                        iid: rect for iid, rect in fit.items()
                        if iid not in long_id_set and iid not in group_top_ids and iid not in cluster_ids
                    }
                    col_band = band
                    if cluster is not None:
                        col_band = Band(
                            band.bottom, band.height, band.x_min + HEADING_COL_W + COL_GUTTER,
                            band.x_max, band.sample_count,
                        )
                    # The group itself takes no affine path on a text slide (Design A
                    # step 4): drop its own top-level fit entry so `_slide_lines` never
                    # falls into `_group_blind_child_lines` for it.
                    for group_top_id in group_top_ids:
                        fit.pop(group_top_id, None)
                    short_children: list[tuple[int, dict, Rect | None, float]] = []
                    for group_ki in text_group_kis:
                        group_rect = group_top_rects.get(group_ki)
                        group_item = items_by_id.get(("group", group_ki))
                        origin_x = group_item.get("x", 0.0) if group_item is not None else 0.0
                        for child in group_children_geo.get(group_ki, ()):
                            child_id: ItemId = ("groupchild", group_ki, child["kind"], child["kindIndex"])
                            if child_id in long_id_set:
                                continue
                            if child["kind"] == "image":
                                raise AssemblyRefusal(
                                    f"slide {number}: image nested in text-triggering group "
                                    f"{group_ki} unsupported"
                                )
                            # The group-level exemption above (skipping the fixed-frame
                            # refusal once a group has a supported autosize verse) only
                            # holds for a child PROVEN short -- an autosize sibling never
                            # excuses a fixed-frame LONG child (Codex D1 fix round 3).
                            if child.get("has_text") and child.get("autosize") is False:
                                words = child.get("words")
                                if words is None or words > text_slide_words:
                                    raise AssemblyRefusal(
                                        f"slide {number}: fixed-frame text inside group "
                                        f"{group_ki} unsupported (piece D1 handles autosize "
                                        "group text only)"
                                    )
                            if not _AS_KIND_NAMES.get(child["kind"]):
                                continue
                            short_children.append((group_ki, child, group_rect, origin_x))
                    sole_occupant = not short_fit and len(short_children) == 1
                    for group_ki, child, group_rect, origin_x in short_children:
                        badge_id = ("groupchild", group_ki, child["kind"], child["kindIndex"])
                        badge_w = float(child.get("w", 0.0))
                        badge_h = float(child.get("h", 0.0))
                        if badge_w > col_band.width:
                            raise AssemblyRefusal(
                                f"slide {number}: group {group_ki} child {child['kindIndex']} is "
                                "wider than the band -- refusing to place"
                            )
                        if sole_occupant or group_rect is None:
                            badge_x = col_band.x_min + (col_band.width - badge_w) / 2.0
                        else:
                            badge_x = group_rect.x + (float(child.get("x", 0.0)) - origin_x)
                        clamped_x = min(max(badge_x, col_band.x_min), col_band.x_max - badge_w)
                        if clamped_x != badge_x:
                            warnings.append(
                                f"slide {number}: group {group_ki} child {child['kindIndex']} badge x "
                                f"clamped {badge_x:.1f} -> {clamped_x:.1f} to stay in the band"
                            )
                        badge_x = clamped_x
                        short_fit[badge_id] = Rect(badge_x, 0.0, badge_w, badge_h)
                    if cluster is not None:
                        for badge_id, rect in short_fit.items():
                            if rect.w > col_band.width:
                                raise AssemblyRefusal(
                                    f"slide {number}: verse badge {_item_label(badge_id)} is wider "
                                    "than the two-column verse column -- refusing to place"
                                )
                        short_fit = {iid: _dc_replace(rect, x=col_band.x_min) for iid, rect in short_fit.items()}
                    _refuse_on_short_row_overlap(number, short_fit)
                    stack_band = col_band
                    short_row_h = 0.0
                    if short_fit:
                        short_row_h = max(rect.h for rect in short_fit.values())
                        budget = max(0.0, col_band.height - short_row_h - _TEXT_STACK_GAP)
                        stack_band = _dc_replace(col_band, height=budget)

                    forced_parts = (split_overrides or {}).get(number)
                    if forced_parts is not None:
                        consumed_splits.add(number)
                    if forced_parts is not None and len(boxes) != forced_parts:
                        raise AssemblyRefusal(
                            f"slide {number}: --split requests {forced_parts} part(s) but the slide "
                            f"has {len(boxes)} long text box(es) to split"
                        )
                    result = None if forced_parts is not None else fit_text_stack(boxes, stack_band, min_text_pt)
                    if result is not None:
                        t, sizes, heights = result
                        stack_t_map[number] = t
                        long_rects = _stacked_text_rects(boxes, heights, stack_band)
                        fit.update(long_rects)
                        short_rects: dict[ItemId, Rect] = {}
                        if short_fit:
                            stack_top = min(rect.y for rect in long_rects.values())
                            short_rects = _short_row_rects(short_fit, short_row_h, stack_top)
                            fit.update(short_rects)
                        stacked_ids = {box.item_id for box in boxes}
                        for box in boxes:
                            if box.item_id[0] == "groupchild":
                                _tag, g_ki, _c_kind, c_ki = box.item_id
                                c_info = (group_child_runs_map.get(g_ki) or {}).get(c_ki) or {}
                                run_item = {"runs": c_info.get("runs") or [], "text": c_info.get("text") or ""}
                            else:
                                run_item = items_by_id[box.item_id]
                            ranges, unresolved = _run_size_ranges(
                                run_item, t, item_id=box.item_id,
                                slide_number=number, warnings=warnings,
                            )
                            if isinstance(ranges, tuple):
                                stacked_run_sizes[box.item_id] = ranges
                            elif ranges is not None:
                                stacked_text_sizes[box.item_id] = ranges
                            elif unresolved:
                                if t < 1.0:
                                    if text_fit == "warn":
                                        raise AssemblyRefusal(
                                            f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap and "
                                            f"fit t={t:.2f} < 1.0, would overflow with un-shrunken text"
                                        )
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap and "
                                        f"fit t={t:.2f} < 1.0, flattening run sizes to the lead size under "
                                        "--text-fit shrink"
                                    )
                                elif text_fit == "shrink":
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap, "
                                        "flattening run sizes to the lead size under --text-fit shrink"
                                    )
                                else:
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap, "
                                        "preserving source sizing"
                                    )
                                stacked_shrink_only_sizes[box.item_id] = sizes[box.item_id]
                            else:
                                stacked_text_sizes[box.item_id] = sizes[box.item_id]
                        if cluster is not None:
                            verse_block_top = min((short_rects or long_rects).values(), key=lambda r: r.y).y
                            two_col_rects, two_col_sizes, two_col_run_sizes, left_band = _two_column_rects(
                                number, cluster, items_by_id, band, verse_block_top, min_text_pt, warnings,
                            )
                            fit.update(two_col_rects)
                            stacked_text_sizes.update(two_col_sizes)
                            stacked_run_sizes.update(two_col_run_sizes)
                            two_column_map[number] = left_band
                            two_column_cluster_map[number] = cluster
                            cluster_autosize = _autosize_text_ids(
                                (cluster.heading_id, cluster.number_id), id_by_item, objects_graph
                            )
                            if cluster_autosize:
                                cluster_autosize_map[number] = cluster_autosize
                    elif cluster is not None:
                        raise AssemblyRefusal(
                            f"slide {number}: two-column verse does not fit the verse column at "
                            f"--min-text-pt {min_text_pt}"
                        )
                    elif not allow_split:
                        raise AssemblyRefusal(
                            f"slide {number}: text does not fit the band at --min-text-pt {min_text_pt}"
                        )
                    elif any(box.item_id[0] == "groupchild" for box in boxes):
                        raise AssemblyRefusal(
                            f"slide {number}: grouped verse text does not fit the band at "
                            f"--min-text-pt {min_text_pt} -- refusing to split text inside a group"
                        )
                    elif len(boxes) < 2:
                        raise AssemblyRefusal(
                            f"slide {number} box {_item_label(boxes[0].item_id)} does not fit the band even alone at --min-text-pt {min_text_pt}"
                        )
                    else:
                        if slide_crops:
                            raise AssemblyRefusal(
                                f"slide {number}: text split and image crop both apply -- unsupported"
                            )
                        stacked_ids = set(long_ids)
                        part_list: list[SplitPart] = []
                        for box in boxes:
                            single = fit_text_stack([box], stack_band, min_text_pt)
                            if single is None:
                                raise AssemblyRefusal(
                                    f"slide {number} box {_item_label(box.item_id)} does not fit the band even alone at --min-text-pt {min_text_pt}"
                                )
                            t1, sizes1, heights1 = single
                            rect = _stacked_text_rects([box], heights1, stack_band)[box.item_id]
                            part_fit = dict(short_fit)
                            if short_fit:
                                part_fit.update(_short_row_rects(short_fit, short_row_h, rect.y))
                            part_fit[box.item_id] = rect
                            other_long = [b.item_id for b in boxes if b.item_id != box.item_id]
                            part_deletes = _delete_order(list(base_deletes) + other_long, id_by_item)
                            part_ranges, part_unresolved = _run_size_ranges(
                                items_by_id[box.item_id], t1, item_id=box.item_id,
                                slide_number=number, warnings=warnings,
                            )
                            part_autosize = _autosize_text_ids(
                                (box.item_id,), id_by_item, objects_graph
                            )
                            part_text_sizes: dict[ItemId, float] = {}
                            if isinstance(part_ranges, float):
                                part_text_sizes[box.item_id] = part_ranges
                            elif part_ranges is None and not part_unresolved:
                                part_text_sizes[box.item_id] = sizes1[box.item_id]
                            elif part_unresolved:
                                if t1 < 1.0:
                                    if text_fit == "warn":
                                        raise AssemblyRefusal(
                                            f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap and "
                                            f"fit t={t1:.2f} < 1.0, would overflow with un-shrunken text"
                                        )
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap and "
                                        f"fit t={t1:.2f} < 1.0, flattening run sizes to the lead size under "
                                        "--text-fit shrink"
                                    )
                                elif text_fit == "shrink":
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap, "
                                        "flattening run sizes to the lead size under --text-fit shrink"
                                    )
                                else:
                                    warnings.append(
                                        f"slide {number} box {_item_label(box.item_id)}: run ranges leave a gap, "
                                        "preserving source sizing"
                                    )
                                stacked_shrink_only_sizes[box.item_id] = sizes1[box.item_id]
                            part_list.append(
                                SplitPart(
                                    fits=part_fit, deletes=part_deletes,
                                    text_sizes=part_text_sizes,
                                    run_sizes={box.item_id: part_ranges} if isinstance(part_ranges, tuple) else {},
                                    stacked_ids=frozenset({box.item_id}),
                                    autosize=part_autosize,
                                )
                            )
                        parts[number] = len(part_list)
                        splits[number] = tuple(part_list)
                        for iid in long_ids:
                            fit.pop(iid, None)
                        if short_fit:
                            fit.update({iid: r for iid, r in part_list[0].fits.items() if iid in short_fit})
                elif text_group_kis:
                    raise AssemblyRefusal(
                        f"slide {number}: group {sorted(text_group_kis)} child text/font could "
                        "not be resolved -- refusing to write blind"
                    )

            if cls.category in ("movie", "mixed"):
                clip_path = clips.get(number)
                if clip_path is None:
                    raise AssemblyRefusal(f"no clip provided for movie slide {number}")
                if not movie_ids:
                    raise AssemblyRefusal(f"slide {number} classified {cls.category} with no kept movie")
                first_movie = min(movie_ids, key=lambda iid: iid[1])
                clips_out[number] = (clip_path, first_movie)

            wall_rect = Rect(0.0, 0.0, *LW_WALL_SIZE) if decision.keep_side else CENTRE_PANEL_RECT
            slide_text_sizes: dict[ItemId, float] = {}
            slide_shrink_sizes: dict[ItemId, float] = {}
            slide_autosize: set[ItemId] = set(cluster_autosize_map.get(number, frozenset()))
            all_kept_text_ids = [iid for iid in cls.kept if iid[0] == "text" and iid not in cluster_ids]
            slide_autosize.update(_autosize_text_ids(all_kept_text_ids, id_by_item, objects_graph))
            candidate_text_ids = [iid for iid in all_kept_text_ids if iid not in stacked_ids]
            for iid in candidate_text_ids:
                item = items_by_id.get(iid)
                if item is None:
                    continue
                if runs is not None:
                    item_sizes = list(runs.get(number, {}).get(iid) or [])
                else:
                    item_sizes = [
                        r["size"] for r in (item.get("runs") or []) if r.get("size") is not None
                    ]
                if not item_sizes:
                    continue
                fitted = fit.get(iid)
                if fitted is None:
                    continue
                visible = _intersect(item_rect(item), wall_rect)
                if visible is None:
                    continue
                if visible.w > 0:
                    scale = fitted.w / visible.w
                elif visible.h > 0:
                    scale = fitted.h / visible.h
                else:
                    continue
                distinct = set(item_sizes)
                if len(distinct) > 1:
                    warnings.append(f"slide {number} text {iid[1]} mixed run sizes")
                    if iid in slide_autosize:
                        slide_shrink_sizes[iid] = max(distinct) * scale
                    continue
                slide_text_sizes[iid] = next(iter(distinct)) * scale

            slide_text_sizes.update(stacked_text_sizes)
            slide_shrink_sizes.update(stacked_text_sizes)
            slide_shrink_sizes.update(stacked_shrink_only_sizes)
            for iid, ranges in stacked_run_sizes.items():
                slide_shrink_sizes[iid] = max(size for _s, _e, size in ranges)
            if slide_text_sizes:
                text_sizes[number] = slide_text_sizes
            if slide_shrink_sizes:
                shrink_text_sizes[number] = slide_shrink_sizes
            if slide_autosize:
                autosize[number] = frozenset(slide_autosize)
            if stacked_run_sizes:
                run_sizes[number] = stacked_run_sizes
            if stacked_ids:
                stacked_id_map[number] = frozenset(stacked_ids)
                stack_band_map[number] = stack_band
                short_fit_map[number] = dict(short_fit)
                short_row_h_map[number] = short_row_h
        except Exception:
            _discard_pending_crop_writes(pending_crop_writes)
            raise

    unconsumed_splits = sorted((split_overrides or {}).keys() - consumed_splits)
    if unconsumed_splits:
        _discard_pending_crop_writes(pending_crop_writes)
        raise AssemblyRefusal(
            f"slide {unconsumed_splits[0]}: --split does not apply -- slide has no long "
            "text boxes to split"
        )

    _commit_pending_crop_writes(pending_crop_writes)

    ordinals = ordinal_map(kept_numbers, parts)
    ordinal_to_number: dict[int, int] = {}
    for number in kept_numbers:
        first = ordinals[number]
        for part in range(parts.get(number, 1)):
            ordinal_to_number[first + part] = number

    return AssemblyPlan(
        kept=tuple(kept_numbers),
        ordinals=ordinals,
        fits=fits,
        deletes=deletes,
        clips=clips_out,
        text_sizes=text_sizes,
        autosize=autosize,
        warnings=tuple(warnings),
        group_scale=group_scale,
        group_children=group_children,
        group_text_sizes=group_text_sizes,
        shrink_text_sizes=shrink_text_sizes,
        group_origin=group_origin,
        parts=parts,
        ordinal_to_number=ordinal_to_number,
        splits=splits,
        run_sizes=run_sizes,
        stacked_ids=stacked_id_map,
        stack_bands=stack_band_map,
        stack_t=stack_t_map,
        short_fit=short_fit_map,
        short_row_h=short_row_h_map,
        crops=crops_out,
        anchors=anchors_out,
        two_column=two_column_map,
        two_column_cluster=two_column_cluster_map,
    )


def _all_group_child_records(
    group_obj: dict,
    objects: dict[str, dict],
    *,
    ox: float = 0.0,
    oy: float = 0.0,
    group_path: tuple[int, ...] = (),
) -> list[dict] | None:
    """Per-child address + source-deck geometry for a flat OR nested top-level group, for
    ANY top-level group (not only one holding an autosize text child). Local re-derivation
    of ``iwa_runs._group_child_records`` without its autosize-only gate, extended to
    recurse into nested groups and to keep a leaf's own rotation -- iwa_runs.py is out of
    out of scope here. ``group_path`` is this call's ancestor nested-group
    kindIndex chain, innermost first, relative to the top-level group. ``None`` means
    "refuse": a rotated group (top-level or nested), unresolvable child kind, or an
    off-axis mask."""
    gx, gy, _gw, _gh, gangle = _xywha(_geom_dict(group_obj))
    if gangle % 360.0:
        return None
    abs_gx, abs_gy = ox + gx, oy + gy
    counters: dict[str, int] = {}
    out: list[dict] = []
    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        child = objects.get(str(cid)) if cid is not None else None
        if child is None:
            return None
        kinds = _memberships(child)
        if not kinds:
            return None
        assigned: dict[str, int] = {}
        for kind in kinds:
            assigned[kind] = counters.get(kind, 0)
            counters[kind] = assigned[kind] + 1

        if child.get("_pbtype") == "TSD.GroupArchive":
            nested = _all_group_child_records(
                child, objects, ox=abs_gx, oy=abs_gy,
                group_path=(assigned["group"],) + group_path,
            )
            if nested is None:
                return None
            out.extend(nested)
            continue

        geom = _geom_dict(child)
        cx, cy, cw, ch, ca = _xywha(geom)
        rotated = bool(ca % 360.0)
        masked = (child.get("mask") or {}).get("identifier") is not None
        if masked:
            mask_geom = _mask_geom(child, objects)
            if not mask_geom:
                return None
            _rect, off_axis = _masked_rect(geom, mask_geom)
            if off_axis:
                return None
        autosize = (
            child.get("_pbtype") == "TSWP.ShapeInfoArchive" and ch == 0.0 and "text" in assigned
        )
        if autosize:
            if rotated:
                return None
            nw, nh = _natural_size(child)
            if nw <= 0 or nh <= 0:
                return None
            if cw > 0 and abs(cw - nw) > 0.01 * nw:
                return None
            out.append({
                "kind": "text", "kindIndex": assigned["text"], "autosize": True,
                "has_text": True, "words": _child_word_count(child, objects),
                "x": abs_gx + cx, "cy": abs_gy + cy, "y": abs_gy + cy - nh / 2.0, "w": nw, "h": nh,
                "group_path": group_path,
            })
            continue
        kind = "shape" if "shape" in assigned else kinds[0]
        # A fixed-frame (non-autosize) text-bearing child keeps its own text membership
        # here (``has_text``) even though ``kind`` collapses to ``shape`` when it ALSO
        # carries shape membership -- Finding 2 (D1 Codex fix round) needs this to detect
        # a group whose long text lives in such a child, without touching the AppleScript
        # write path's kind label.
        has_text = "text" in assigned
        words = _child_word_count(child, objects) if has_text else None
        if rotated and not masked:
            fx, fy, fw, fh = _frame_rect(geom)
            out.append({
                "kind": kind, "kindIndex": assigned[kind], "autosize": False,
                "has_text": has_text, "words": words,
                "x": abs_gx + fx, "y": abs_gy + fy, "w": fw, "h": fh, "angle": ca,
                "group_path": group_path,
            })
            continue
        x0, y0, x1, y1 = _leaf_bbox(child, abs_gx, abs_gy, objects)
        out.append({
            "kind": kind, "kindIndex": assigned[kind], "autosize": False,
            "has_text": has_text, "words": words,
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "group_path": group_path,
        })
    return out


def _child_word_count(child: dict, objects: dict[str, dict]) -> int | None:
    """Word count of a fixed-frame text child's storage text, the same ``ownedStorage``
    -> ``TSWP.StorageArchive`` resolution ``iwa_runs._group_child_runs`` uses. ``None``
    when the text cannot be resolved."""
    stor_id = (child.get("ownedStorage") or {}).get("identifier")
    storage = objects.get(str(stor_id)) if stor_id is not None else None
    if not storage or storage.get("_pbtype") != "TSWP.StorageArchive":
        return None
    text = "".join(storage.get("text") or [])
    return _word_count(_normalize_text(text))


def _attach_full_group_children(fw_deck: Path, payload: dict, *, deck: Any = None) -> None:
    """Attach ``slide['groupChildren']`` for every flat top-level group (not just
    autosize ones, unlike ``iwa_runs.attach_group_children``). Read-only."""
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(fw_deck)
    kids_by_index: dict[int, dict[int, list[dict]]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        kids: dict[int, list[dict]] = {}
        for rec in derive_kind_index(slide_archive, objects):
            if rec.get("kind") != "group":
                continue
            group_obj = objects.get(str(rec["id"]))
            if not group_obj:
                continue
            records = _all_group_child_records(group_obj, objects)
            if records:
                kids[int(rec["kindIndex"])] = records
        if kids:
            kids_by_index[idx] = kids
    for slide in payload.get("slides") or []:
        kids = kids_by_index.get(slide.get("index"))
        if kids:
            slide["groupChildren"] = kids


def load_assembly_inputs(
    fw_deck: Path,
    *,
    include_side: frozenset[int] = frozenset(),
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> tuple[dict, list[SlideClass], dict[int, dict[ItemId, list[float]]]]:
    """The only I/O in the pure planning path: offline payload, classifier output, and
    per-text-item run sizes, all read from `fw_deck` once."""
    deck = _load_deck(fw_deck)
    payload = offline_wall_payload(fw_deck, deck=deck)
    attach_runs(fw_deck, payload, deck=deck)
    _attach_full_group_children(fw_deck, payload, deck=deck)
    attach_group_child_text(fw_deck, payload, deck=deck)
    attach_group_child_runs(fw_deck, payload, deck=deck)
    attach_group_content_signature(fw_deck, payload, deck=deck)
    attach_group_captions(fw_deck, payload, deck=deck)
    classes = classify_deck(
        fw_deck, include_side=include_side, deck=deck, payload=payload, text_slide_words=text_slide_words,
        no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )

    runs: dict[int, dict[ItemId, list[float]]] = {}
    for slide in payload.get("slides") or []:
        number = slide["number"]
        slide_runs: dict[ItemId, list[float]] = {}
        for item in slide.get("items") or []:
            if item.get("kind") != "text":
                continue
            sizes = [r["size"] for r in (item.get("runs") or []) if r.get("size") is not None]
            if sizes:
                slide_runs[(item["kind"], item["kindIndex"])] = sizes
        if slide_runs:
            runs[number] = slide_runs
    return payload, classes, runs


def template_layout_alpha_safe(template_path: Path, layout_name: str) -> bool:
    """Offline pre-check, never touches Keynote: resolves ``layout_name`` in
    ``template_path`` by walking ``KN.ThemeArchive.templates`` (Keynote's only offline
    representation of a slide layout -- there is no ``KN.SlideLayoutArchive``) and applies
    ``layout_alpha_safe`` against the template's own canvas size. Raises
    ``AssemblyRefusal`` if no layout with that name exists."""
    objects, _id_to_file, _file_ids = _load_deck(template_path)
    slide = _find_layout_by_name(objects, layout_name)
    if slide is None:
        raise AssemblyRefusal(f"layout {layout_name!r} not found in layout template {template_path}")
    return layout_alpha_safe(slide, objects, _canvas_size(objects))


def _slide_nodes(objects: dict[str, dict]) -> list[dict]:
    """``KN.SlideNodeArchive`` for every deck slide, in ``KN.ShowArchive.slideTree``
    order (mirrors ``iwa_runs.slide_order``, but keeps the node for ``templateSlideId``
    rather than resolving straight to the slide id)."""
    shows = [o for o in objects.values() if o.get("_pbtype") == "KN.ShowArchive"]
    if not shows:
        return []
    nodes = []
    for ref in shows[0].get("slideTree", {}).get("slides", []):
        node = objects.get(str(ref.get("identifier")))
        if node:
            nodes.append(node)
    return nodes


def _slide_archive_for_ordinal(objects: dict[str, dict], ordinal: int) -> dict | None:
    """The 1-based ``ordinal``-th slide's own ``KN.SlideArchive`` (not its layout)."""
    nodes = _slide_nodes(objects)
    if not (1 <= ordinal <= len(nodes)):
        return None
    slide_id = (nodes[ordinal - 1].get("slide") or {}).get("identifier")
    return objects.get(str(slide_id)) if slide_id is not None else None


def _base_layout_slide_for_ordinal(objects: dict[str, dict], ordinal: int) -> dict | None:
    """The 1-based ``ordinal``-th slide's base layout, resolved offline via
    ``KN.SlideArchive.templateSlide`` -- a direct object reference from the slide's own
    archive to its layout's ``KN.SlideArchive``, one hop. ``None`` if the ordinal is out
    of range or the reference doesn't resolve."""
    slide = _slide_archive_for_ordinal(objects, ordinal)
    if slide is None:
        return None
    target = (slide.get("templateSlide") or {}).get("identifier")
    if target is None:
        return None
    return objects.get(str(target))


def check_layout_import_preconditions(
    fw_deck: Path,
    *,
    layout_template: Path,
    layout_names: Sequence[str],
) -> None:
    """Offline plan-time precondition for ``layout_policy="import"``, run before Keynote
    ever launches, for every name in `layout_names`. Thin ``AssemblyRefusal`` wrapper
    over the shared ``dsk_live.check_layout_import_preconditions`` (also used by the
    movie/stage exporters) -- see that docstring for the refusal conditions."""
    try:
        _live_check_layout_import_preconditions(
            fw_deck, layout_template=layout_template, layout_names=layout_names
        )
    except LayoutImportRefusal as exc:
        raise AssemblyRefusal(str(exc)) from exc


def verify_staged_layouts_alpha_safe(staging_path: Path, plan: AssemblyPlan) -> None:
    """Offline post-check for ``layout_policy="import"``, run against the assembled
    STAGING deck before it is published to ``out_path``: every kept slide's base layout
    (resolved via ``templateSlideId``) must be alpha-safe, AND the slide's own drawables
    (backdrops the plan failed to delete included) must leave no full-canvas coverage.
    Refuses (``AssemblyRefusal``) naming the first offending slide rather than publishing
    a deck whose PNG stage export would come back opaque."""
    objects, _id_to_file, _file_ids = _load_deck(staging_path)
    canvas = _canvas_size(objects)
    ordinal_to_number = plan.ordinal_to_number or {
        ordinal: number for number, ordinal in plan.ordinals.items()
    }
    for ordinal, number in sorted(ordinal_to_number.items()):
        layout = _base_layout_slide_for_ordinal(objects, ordinal)
        if layout is None:
            raise AssemblyRefusal(f"slide {number} (ordinal {ordinal}): base layout not resolvable offline")
        if not layout_alpha_safe(layout, objects, canvas):
            raise AssemblyRefusal(
                f"slide {number} (ordinal {ordinal}): base layout {layout.get('name')!r} is not alpha-safe"
            )
        slide = _slide_archive_for_ordinal(objects, ordinal)
        if slide is None:
            raise AssemblyRefusal(f"slide {number} (ordinal {ordinal}): slide not resolvable offline")
        if not layout_alpha_safe(slide, objects, canvas):
            raise AssemblyRefusal(
                f"slide {number} (ordinal {ordinal}): a full-canvas drawable remains on the slide itself"
            )


def _locked_write_block(
    number: int, addr: str, body: list[str], *, obj_var: str = "theObj", locked_var: str = "wasLocked"
) -> list[str]:
    """Unlock `addr` if locked, run `body`, then guaranteed relock -- on normal completion
    and on any error. A failure anywhere is logged as a MISS line, never swallowed silently.
    `obj_var`/`locked_var` let a block nest inside another without name collisions."""
    escaped_addr = _as_escape(addr)
    return [
        f"        set {locked_var} to false",
        "        try",
        f"          set {obj_var} to {addr}",
        "          try",
        f"            if locked of {obj_var} then",
        f"              set locked of {obj_var} to false",
        f"              set {locked_var} to true",
        "            end if",
        "          end try",
        "          try",
        *body,
        "          end try",
        f"          if {locked_var} then set locked of {obj_var} to true",
        "        on error errMsg number errNum",
        "          try",
        f"            if {locked_var} then set locked of {obj_var} to true",
        "          end try",
        f'          log ("MISS" & tab & "{number}" & tab & "{escaped_addr}" & tab & errMsg)',
        "        end try",
    ]


def _wrap_group_locks(number: int, ordinal: int, group_chain: list[int], body: list[str]) -> list[str]:
    """Wraps `body` in a guaranteed lock/relock for every nested group in `group_chain`
    (outermost-to-innermost, top-level group first) EXCEPT the top-level one, which the
    caller already wraps. Innermost first, so each level nests inside its parent's own
    unlock -- required to reach a child address like `group 2 of group 1 of slide N`."""
    result = body
    for depth in range(len(group_chain) - 1, 0, -1):
        addr = " of ".join(f"group {k + 1}" for k in reversed(group_chain[: depth + 1])) + f" of slide {ordinal}"
        result = _locked_write_block(number, addr, result, obj_var=f"gObj{depth}", locked_var=f"gLocked{depth}")
    return result


def _group_known_child_lines(
    number: int,
    ordinal: int,
    kind_index: int,
    group_x: float,
    group_y: float,
    rect: Rect,
    scale: float,
    children: list[dict],
    text_size: float | None,
) -> list[str]:
    """Per-child writes for a flat OR nested group whose children are known offline
    (`_all_group_child_records`): position/size are affine-mapped from the plan's shared
    slide scale and the group's source-deck origin, rotation preserved verbatim, autosize
    text never gets a height write. Each child is unlocked/written/relocked individually;
    a nested child's ancestor groups are unlocked/relocked around it too via
    `_wrap_group_locks`."""
    text_children = [c for c in children if c["kind"] == "text"]
    caption_child = text_children[0] if text_size is not None and len(text_children) == 1 else None

    child_lines: list[str] = []
    for child in children:
        name = _AS_KIND_NAMES.get(child["kind"])
        if not name:
            continue
        child_index = child["kindIndex"]
        group_chain = [kind_index] + list(reversed(child.get("group_path") or ()))
        addr_prefix = " of ".join(f"group {k + 1}" for k in reversed(group_chain))
        addr = f"{name} {child_index + 1} of {addr_prefix} of slide {ordinal}"
        new_x = rect.x + (child["x"] - group_x) * scale
        new_y = rect.y + (child["y"] - group_y) * scale
        new_w = child["w"] * scale
        body = [f"            set width of theObj to {_as_num(new_w)}"]
        is_caption = caption_child is not None and child is caption_child
        if not child.get("autosize"):
            body.append(f"            set height of theObj to {_as_num(child['h'] * scale)}")
            body.append(f"            set position of theObj to {{{_as_num(new_x)}, {_as_num(new_y)}}}")
            if child.get("angle"):
                body.append(f"            set rotation of theObj to {_as_num(child['angle'])}")
            if is_caption:
                body.append(f"            set size of object text of theObj to {_as_num(text_size)}")
        else:
            if is_caption:
                body.append(f"            set size of object text of theObj to {_as_num(text_size)}")
            body.append(f"            set position of theObj to {{{_as_num(new_x)}, {_as_num(new_y)}}}")
            if child.get("angle"):
                body.append(f"            set rotation of theObj to {_as_num(child['angle'])}")
        write_block = _locked_write_block(number, addr, body)
        child_lines += _wrap_group_locks(number, ordinal, group_chain, write_block)

    group_addr = f"group {kind_index + 1} of slide {ordinal}"
    return _locked_write_block(
        number, group_addr, child_lines, obj_var="theGroupObj", locked_var="wasGroupLocked"
    )


def _group_blind_child_lines(number: int, ordinal: int, kind_index: int, rect: Rect, scale: float) -> list[str]:
    """Fallback for a text-free group (`attach_group_child_text` found nothing): scales
    +translates children live about the group's own live frame using the plan's
    precomputed shared scale (never `rect.w / live group width`). Safe only because no
    text child -- and so no autosize-freeze hazard -- exists on this group; per-child
    unlock/relock is not attempted here since children are enumerated live rather than
    addressed individually."""
    group_addr = f"group {kind_index + 1} of slide {ordinal}"
    return [
        f"          set gx to (item 1 of (position of {group_addr}))",
        f"          set gy to (item 2 of (position of {group_addr}))",
        f"          repeat with theChild in (iWork items of {group_addr})",
        "            set cx to (item 1 of (position of theChild))",
        "            set cy to (item 2 of (position of theChild))",
        "            set cw to (width of theChild)",
        "            set chh to (height of theChild)",
        f"            set position of theChild to {{{_as_num(rect.x)} + ((cx - gx) * {_as_num(scale)}), "
        f"{_as_num(rect.y)} + ((cy - gy) * {_as_num(scale)})}}",
        f"            set width of theChild to (cw * {_as_num(scale)})",
        f"            set height of theChild to (chh * {_as_num(scale)})",
        "          end repeat",
    ]


def _group_stacked_child_lines(
    number: int,
    ordinal: int,
    group_ki: int,
    entries: Sequence[tuple[dict, Rect, float | None, tuple[tuple[int, int, float], ...] | None]],
) -> list[str]:
    """Per-child writes for a text-triggering group's stacked children (Design A step 4):
    each child is unlocked/written/relocked individually, the whole set wrapped in one
    guaranteed lock/relock on the group itself (mirrors `_group_known_child_lines`). A
    stacked ``text`` child (the verse, carrying a resolved ``text_size``/``run_ranges``)
    gets width, its run/lead size, then position last, NEVER height (always autosize); every
    other child -- a short-row ``shape`` (the badge) or a short-row ``text`` label that
    did not pass the stack-vs-short-row word threshold -- gets position only, left at
    source size, per the owner decision. An unmapped kind is skipped, matching
    `_group_known_child_lines`. The group itself takes no affine path here."""
    child_lines: list[str] = []
    for child, rect, text_size, run_ranges in entries:
        name = _AS_KIND_NAMES.get(child["kind"])
        if not name:
            continue
        addr = f"{name} {child['kindIndex'] + 1} of group {group_ki + 1} of slide {ordinal}"
        body: list[str] = []
        if child["kind"] == "text" and (text_size is not None or run_ranges):
            body.append(f"            set width of theObj to {_as_num(rect.w)}")
            if run_ranges:
                for start, end, size in run_ranges:
                    body.append(
                        f"            set size of characters {start} thru {end} "
                        f"of object text of theObj to {_as_num(size)}"
                    )
            elif text_size is not None:
                body.append(f"            set size of object text of theObj to {_as_num(text_size)}")
            body.append(f"            set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}")
        else:
            body.append(f"            set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}")
        child_lines += _locked_write_block(number, addr, body)
    group_addr = f"group {group_ki + 1} of slide {ordinal}"
    return _locked_write_block(
        number, group_addr, child_lines, obj_var="theGroupObj", locked_var="wasGroupLocked"
    )


def _text_measure_lines(
    number: int, kind_index: int, addr: str, target_h: float, *, ordinal: int | None = None,
    item_key: str | None = None,
) -> list[str]:
    """One-shot diagnostic read of a text item's live height (single ``height of``, no
    poll -- the live read is known stale after ``set width/position/size`` and the offline
    naturalSize read of the saved deck is the refit authority, see D2b), logging
    `OBED\\t<n>\\tMEASURE\\ttext:<idx>\\t<h>`, then `OBED\\t<n>\\tOVERFLOW\\t...` when it still
    exceeds `target_h` by more than 2pt. ``item_key`` overrides the default ``text:<idx>``
    key -- a group child (D1 step 6) uses ``groupchild:<g>:<kind>:<idx>`` so it never
    collides with a top-level text item sharing the same ``kindIndex``."""
    if item_key is None:
        item_key = f"text:{kind_index}" if ordinal is None else f"text:{kind_index}:{ordinal}"
    return [
        "        try",
        f"          set curH to (height of {addr})",
        f'          log ("OBED" & tab & "{number}" & tab & "MEASURE" & tab & '
        f'"{item_key}" & tab & (curH as string))',
        f"          if curH > {_as_num(target_h)} + 2.0 then",
        f'            log ("OBED" & tab & "{number}" & tab & "OVERFLOW" & tab & '
        f'"{item_key}" & tab & (curH as string))',
        "          end if",
        "        end try",
    ]


_MEASURE_RE = re.compile(r"^OBED\t(\d+)\tMEASURE\t([^\t]+)\t([-\d.]+)$")


def _parse_measure_lines(stderr: str) -> dict[tuple[int, str], float]:
    """`{(slide number, item key): measured height}` from a batch's `MEASURE` lines."""
    measured: dict[tuple[int, str], float] = {}
    for line in stderr.splitlines():
        m = _MEASURE_RE.match(line)
        if m:
            measured[(int(m.group(1)), m.group(2))] = float(m.group(3))
    return measured


def _slide_lines(
    plan: AssemblyPlan, number: int, ordinal: int, *, part: int = 0, text_fit: Literal["warn", "shrink"] = "warn"
) -> list[str]:
    is_clip = number in plan.clips
    lines: list[str] = ["      try"]
    if is_clip:
        clip_path, movie_id = plan.clips[number]
        movie_addr = f"movie {movie_id[1] + 1} of slide {ordinal}"
        lines += [
            f"        set repMethod to (repetition method of {movie_addr})",
            f"        set movVol to (movie volume of {movie_addr})",
        ]

    split_parts = plan.splits.get(number)
    if split_parts is not None:
        split_part = split_parts[part]
        fit = split_part.fits
        deletes_here: tuple[ItemId, ...] = split_part.deletes
        text_sizes = {**plan.text_sizes.get(number, {}), **split_part.text_sizes}
        run_sizes_here = split_part.run_sizes
        stacked_ids_here = split_part.stacked_ids
        autosize_ids = plan.autosize.get(number, frozenset()) | split_part.autosize
        shrink_text_sizes = plan.shrink_text_sizes.get(number, {})
    else:
        fit = plan.fits.get(number, {})
        deletes_here = plan.deletes.get(number, ())
        text_sizes = plan.text_sizes.get(number, {})
        run_sizes_here = plan.run_sizes.get(number, {})
        stacked_ids_here = plan.stacked_ids.get(number, frozenset())
        autosize_ids = plan.autosize.get(number, frozenset())
        shrink_text_sizes = plan.shrink_text_sizes.get(number, {})
    known_children = plan.group_children.get(number, {})
    group_text_sizes = plan.group_text_sizes.get(number, {})
    group_origin = plan.group_origin.get(number, {})
    scale = plan.group_scale.get(number)
    slide_crops = plan.crops.get(number, {}) if split_parts is None else {}

    groupchild_by_group: dict[int, list[tuple[dict, Rect, float | None, tuple | None]]] = {}
    for item_id, rect in fit.items():
        if item_id[0] != "groupchild":
            continue
        _tag, group_ki, child_kind, child_ki = item_id
        child_rec = {"kind": child_kind, "kindIndex": child_ki}
        groupchild_by_group.setdefault(group_ki, []).append(
            (child_rec, rect, text_sizes.get(item_id), run_sizes_here.get(item_id))
        )
    for group_ki, entries in groupchild_by_group.items():
        lines += _group_stacked_child_lines(number, ordinal, group_ki, entries)
        for child_rec, child_rect, child_text_size, child_run_ranges in entries:
            if child_rec["kind"] != "text" or (child_text_size is None and not child_run_ranges):
                continue
            child_ki = child_rec["kindIndex"]
            addr = f"text item {child_ki + 1} of group {group_ki + 1} of slide {ordinal}"
            lines += _text_measure_lines(
                number, child_ki, addr, child_rect.h, item_key=f"groupchild:{group_ki}:text:{child_ki}"
            )

    for item_id, rect in fit.items():
        if item_id[0] == "groupchild":
            continue
        if item_id in slide_crops:
            continue
        kind, kind_index = item_id
        name = _AS_KIND_NAMES.get(kind)
        if not name:
            continue
        addr = f"{name} {kind_index + 1} of slide {ordinal}"

        if kind == "group":
            children = known_children.get(kind_index)
            if children is not None and scale is not None and kind_index in group_origin:
                group_x, group_y = group_origin[kind_index]
                lines += _group_known_child_lines(
                    number, ordinal, kind_index, group_x, group_y, rect, scale, children,
                    group_text_sizes.get(kind_index),
                )
            elif scale is not None:
                lines += _locked_write_block(
                    number, addr, body=_group_blind_child_lines(number, ordinal, kind_index, rect, scale)
                )
            continue

        body = [f"          set width of theObj to {_as_num(rect.w)}"]
        if item_id not in autosize_ids:
            body.append(f"          set height of theObj to {_as_num(rect.h)}")
        position_line = f"          set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}"
        size_lines: list[str] = []
        if kind == "text" and item_id in run_sizes_here:
            for start, end, size in run_sizes_here[item_id]:
                size_lines.append(
                    f"          set size of characters {start} thru {end} "
                    f"of object text of theObj to {_as_num(size)}"
                )
        elif kind == "text" and item_id in text_sizes:
            size_lines.append(f"          set size of object text of theObj to {_as_num(text_sizes[item_id])}")
        elif kind == "text" and text_fit == "shrink" and item_id in shrink_text_sizes:
            size_lines.append(
                f"          set size of object text of theObj to {_as_num(shrink_text_sizes[item_id])}"
            )
        if item_id in autosize_ids:
            body += size_lines
            body.append(position_line)
        else:
            body.append(position_line)
            body += size_lines
        lines += _locked_write_block(number, addr, body)
        if kind == "text" and (item_id not in text_sizes or item_id in stacked_ids_here):
            overflow_ordinal = ordinal if split_parts is not None else None
            lines += _text_measure_lines(number, kind_index, addr, rect.h, ordinal=overflow_ordinal)

    for item_id in deletes_here:
        kind, kind_index = item_id
        name = _AS_KIND_NAMES.get(kind)
        if not name:
            continue
        addr = f"{name} {kind_index + 1} of slide {ordinal}"
        lines += [
            f"        set theObj to {addr}",
            "        try",
            "          if locked of theObj then set locked of theObj to false",
            "        end try",
            *_delete_or_hide_placeholder_lines(number, ordinal, addr),
        ]

    for item_id, spec in slide_crops.items():
        rect = fit.get(item_id)
        if rect is None:
            continue
        kind_index = item_id[1]
        lines += [
            f"        set imgBefore to (count of images of slide {ordinal})",
            f"        tell slide {ordinal}",
            "          set newImg to make new image with properties "
            f'{{file:(POSIX file "{_as_escape(str(spec.path))}") as alias}}',
            "        end tell",
            f"        set position of newImg to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}",
            f"        set width of newImg to {_as_num(rect.w)}",
            f"        set height of newImg to {_as_num(rect.h)}",
            f'        if (count of images of slide {ordinal}) is not (imgBefore + 1) then '
            f'error "cropped image {kind_index} did not import"',
        ]

    if is_clip:
        clip_path, movie_id = plan.clips[number]
        clip_rect = plan.fits[number][movie_id]
        lines += [
            f"        set mBefore to (count of movies of slide {ordinal})",
            f"        tell slide {ordinal}",
            "          set newMov to make new image with properties "
            f'{{file:(POSIX file "{_as_escape(str(clip_path))}") as alias}}',
            "        end tell",
            f"        set position of newMov to {{{_as_num(clip_rect.x)}, {_as_num(clip_rect.y)}}}",
            f"        set width of newMov to {_as_num(clip_rect.w)}",
            f"        set height of newMov to {_as_num(clip_rect.h)}",
            f'        if (count of movies of slide {ordinal}) is not (mBefore + 1) then '
            'error "clip did not import as a movie"',
            "        set repetition method of newMov to repMethod",
            "        set movie volume of newMov to movVol",
            f'        log ("OBED" & tab & "{number}" & tab & "repetitionMethod" & tab & (repMethod as string))',
            f'        log ("OBED" & tab & "{number}" & tab & "movieVolume" & tab & (movVol as string))',
            f"        set transition properties of slide {ordinal} to "
            "{transition effect:no transition effect}",
        ]

    lines += [
        f'        log ("OBED" & tab & "{number}" & tab & ((current date) as string))',
        "      on error errMsg number errNum",
        f'        log ("ERR" & tab & "{number}" & tab & errNum & tab & errMsg)',
        "        error errMsg number errNum",
        "      end try",
    ]
    return lines


def build_assembly_script(
    plan: AssemblyPlan,
    *,
    scratch_path: Path,
    staging_path: Path,
    layout_policy: LayoutPolicy = "import",
    black_layout_names: Sequence[str] = DEFAULT_TRANSPARENT_LAYOUT_NAMES,
    import_layout_names: Sequence[str] = DEFAULT_DSK_LAYOUT_NAMES,
    layout_template: Path = DEFAULT_LAYOUT_TEMPLATE,
    text_fit: Literal["warn", "shrink"] = "warn",
    slide_layout_names: Mapping[int, str] | None = None,
) -> str:
    """One AppleScript for the whole assembly batch: deletes first, then layout policy, canvas
    resize, then per-slide geometry/text-size/deletes/clip-insert -- same idioms as
    `dsk_movie_export._build_export_script`. Saves-as to `staging_path` (Keynote's sdef
    does document a `save ... in` verb, per `maps_keynote.py`) inside the batch's own work
    dir rather than in place, so the caller can post-process and verify before publishing
    to the final `out_path`.

    `text_fit`: "warn" (default) leaves a mixed-run autosize text box at its own wrapped
    size and only logs an overflow past the fitted band; "shrink" additionally sets its
    size to the largest source run size (scaled), flattening its run sizes -- a real
    character-styling loss the operator should expect, not the default.

    `layout_policy`:
    - "import" (default): imports every layout in `import_layout_names` missing from the
      scratch doc from `layout_template` (see `check_layout_import_preconditions`, the
      plan-time dedupe-trap refusal), then sets every kept slide's base layout per
      `slide_layout_names` (plan §2.2/§3 L3, see `resolve_slide_layouts`) when given,
      else the single alpha-safe layout named in `black_layout_names` (the pre-L3
      blanket assignment) -- never an FW-owned layout matched by name, since a
      same-named layout the FW deck happens to own is not guaranteed to be alpha-safe.
    - "preserve": leaves every kept slide's base layout untouched -- no layout is
      searched for or imported.
    """
    stem_name = _as_escape(scratch_path.stem)
    doc_name = _as_escape(scratch_path.name)
    approved_names = _applescript_string_list(black_layout_names)
    keep = plan.kept
    base_ordinals = ordinal_map(keep)

    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  with timeout of 3600 seconds",
        "    activate",
        "    try",
        f'      close (every document whose name is "{stem_name}" or name is "{doc_name}") saving no',
        "      delay 0.3",
        "    end try",
        f'    set theFile to POSIX file "{_as_escape(str(scratch_path))}"',
        "    set theDoc to open theFile",
        "    delay 8",
        f'    if (name of theDoc) is not "{stem_name}" and (name of theDoc) is not "{doc_name}" then',
        '      error "scratch document name mismatch"',
        "    end if",
        "    tell theDoc",
        "      set slideCount to count of slides",
        f"      set keepList to {{{', '.join(str(n) for n in keep)}}}",
        "      repeat with i from slideCount to 1 by -1",
        "        if keepList does not contain i then delete slide i of theDoc",
        "      end repeat",
    ]

    if layout_policy == "import":
        lines += layout_import_lines("theDoc", import_layout_names, layout_template)
        if slide_layout_names:
            needed_names = sorted({slide_layout_names.get(number, black_layout_names[-1]) for number in keep})
            layout_vars: dict[str, str] = {}
            for i, name in enumerate(needed_names):
                var = f"resolvedLayout{i}"
                layout_vars[name] = var
                lines += [
                    f"      set {var} to missing value",
                    "      repeat with lay in slide layouts of theDoc",
                    "        ignoring case",
                    f'          if (name of lay as text) is "{_as_escape(name)}" then',
                    f"            set {var} to lay",
                    "          end if",
                    "        end ignoring",
                    f"        if {var} is not missing value then exit repeat",
                    "      end repeat",
                    f'      if {var} is missing value then error "resolved layout {_as_escape(name)} not found in theDoc"',
                ]
            for number in keep:
                ordinal = base_ordinals[number]
                name = slide_layout_names.get(number, black_layout_names[-1])
                lines.append(f"      set base layout of slide {ordinal} of theDoc to {layout_vars[name]}")
        else:
            lines += [
                f"      set blackNames to {approved_names}",
                "      set targetLayout to missing value",
                "      repeat with lay in slide layouts of theDoc",
                "        ignoring case",
                "          if (name of lay as text) is in blackNames then",
                "            set targetLayout to lay",
                "          end if",
                "        end ignoring",
                "        if targetLayout is not missing value then exit repeat",
                "      end repeat",
                '      if targetLayout is missing value then error "resolved black layout not found in theDoc"',
            ]
            for number in keep:
                ordinal = base_ordinals[number]
                lines.append(f"      set base layout of slide {ordinal} of theDoc to targetLayout")

    lines += [
        f"      set width of theDoc to {plan.canvas[0]}",
        f"      set height of theDoc to {plan.canvas[1]}",
    ]

    for number in sorted(keep, key=lambda n: base_ordinals[n], reverse=True):
        extra = plan.parts.get(number, 1) - 1
        if extra <= 0:
            continue
        base_ordinal = base_ordinals[number]
        for _ in range(extra):
            lines.append(f"      duplicate slide {base_ordinal} to after slide {base_ordinal} of theDoc")

    for number in keep:
        for part in range(plan.parts.get(number, 1)):
            ordinal = plan.ordinals[number] + part
            lines += _slide_lines(plan, number, ordinal, part=part, text_fit=text_fit)

    lines += [
        "    end tell",
        f'    save theDoc in POSIX file "{_as_escape(str(staging_path))}"',
        "    close theDoc saving no",
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class TextRefit:
    """One box's re-fitted geometry for a refit pass: ``run_sizes`` is per-run character
    ranges (`_run_size_ranges`'s tuple form), a single covering size, or ``None`` to leave
    the box's own text size untouched."""

    rect: Rect
    run_sizes: tuple[tuple[int, int, float], ...] | float | None = None


def build_refit_script(
    plan: AssemblyPlan,
    refits: Mapping[int, Mapping[ItemId, TextRefit]],
    *,
    ordinals: Mapping[int, int],
    scratch_path: Path,
    staging_path: Path,
    hidden: Mapping[int, frozenset[ItemId]] | None = None,
) -> str:
    """A refit round: re-open `scratch_path` by POSIX path -- bring-to-front if it is
    still the live document, or a plain reopen of a prior round's save (`keynote.py:532`'s
    precedent covers either) -- re-write only the boxes named in `refits` for each
    affected slide (size/run-ranges + position, addressed by staged post-delete index,
    with that slide's ``hidden`` delete targets treated as retained), re-measure them,
    then `save`/`close`."""
    stem_name = _as_escape(scratch_path.stem)
    doc_name = _as_escape(scratch_path.name)
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  with timeout of 3600 seconds",
        "    activate",
        f'    set theFile to POSIX file "{_as_escape(str(scratch_path))}"',
        "    set theDoc to open theFile",
        "    delay 0.5",
        f'    if (name of theDoc) is not "{stem_name}" and (name of theDoc) is not "{doc_name}" then',
        '      error "scratch document name mismatch"',
        "    end if",
        "    tell theDoc",
    ]
    for number, items in refits.items():
        ordinal = ordinals[number]
        autosize_ids = plan.autosize.get(number, frozenset())
        for item_id, refit in items.items():
            if item_id[0] == "groupchild":
                continue
            kind, kind_index = item_id
            staged_id = _staged_id_for(number, plan, item_id, hidden=(hidden or {}).get(number, frozenset()))
            if staged_id is None:
                continue
            name = _AS_KIND_NAMES.get(kind)
            if not name:
                continue
            addr = f"{name} {staged_id[1] + 1} of slide {ordinal}"
            rect = refit.rect
            position_line = f"          set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}"
            size_lines: list[str] = []
            if isinstance(refit.run_sizes, tuple):
                for start, end, size in refit.run_sizes:
                    size_lines.append(
                        f"          set size of characters {start} thru {end} "
                        f"of object text of theObj to {_as_num(size)}"
                    )
            elif isinstance(refit.run_sizes, (int, float)):
                size_lines.append(f"          set size of object text of theObj to {_as_num(refit.run_sizes)}")
            body = [f"          set width of theObj to {_as_num(rect.w)}"]
            if item_id in autosize_ids:
                body += size_lines
                body.append(position_line)
            else:
                body.append(f"          set height of theObj to {_as_num(rect.h)}")
                body.append(position_line)
                body += size_lines
            lines += _locked_write_block(number, addr, body)
            lines += _text_measure_lines(number, kind_index, addr, rect.h)
    lines.append("    end tell")
    lines += [
        f'    save theDoc in POSIX file "{_as_escape(str(staging_path))}"',
        "    close theDoc saving no",
    ]
    lines += [
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class AssembleResult:
    path: Path
    slides_kept: tuple[int, ...]
    ordinals: dict[int, int]
    fits: dict
    clips_inserted: dict[int, Path]
    stroke: dict
    zorder: dict
    builds: dict
    size_bytes: int
    source_size_bytes: int
    wall_s: float
    warnings: tuple[str, ...]
    movie_props: dict[int, dict[str, str]]
    overflows: tuple[dict, ...] = ()
    ordinal_to_number: dict[int, int] = field(default_factory=dict)
    hidden: tuple[dict, ...] = ()


def _package_size(path: Path) -> int:
    path = Path(path)
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return path.stat().st_size


def _restore_stroke(
    fw_deck: Path,
    out_path: Path,
    plan: AssemblyPlan,
    payload: dict,
    stroke_min_refs: int,
    warnings: list[str],
    log: Callable[[str], None],
    *,
    hidden: Mapping[int, frozenset[ItemId]] = {},
) -> dict:
    """Card-border stroke-width restore (paired styles) plus a default stroke grant for
    kept media whose style has none, restricted to styles every one of whose references
    -- in ``out_objects``, not just the image/movie leaves ``card_styles`` counts, so a
    layout/master reference or a non-retained (deleted/not-staged) object is caught too --
    resolves to retained staged media on a kept slide. Classification (grant vs width
    restore) is by the RESOLVED pattern regardless of whether the style carries its own
    stroke or inherits one; an inherited style's restore is written as the child style's
    own stroke via ``patch_media_stroke``, since ``patch_stroke_widths`` only patches an
    own stroke. Styles are re-keyed from output ordinals to source slide numbers before
    comparing against ``plan.kept``. Re-raises ``OfflineWriteCorrupted``; every other
    failure is reported in the returned dict and as a warning, never raised."""
    stroke: dict = {}
    try:
        from obed_edom.iwa_write import (
            OfflineWriteCorrupted,
            _collect_stroke_images,
            _resolve_stroke,
            card_styles,
            match_card_stroke_styles,
            mint_media_style,
            patch_media_stroke,
            patch_stroke_widths,
        )
    except Exception as exc:  # noqa: BLE001
        stroke["refused"] = True
        stroke["reason"] = f"iwa_write unavailable ({type(exc).__name__}: {exc})"
        warnings.append(f"stroke restore skipped: {stroke['reason']}")
        return stroke

    inverse_ordinals = dict(plan.ordinal_to_number) or {
        ordinal: number for number, ordinal in plan.ordinals.items()
    }

    def _rekey_slides(rows: list[dict]) -> None:
        """Output ordinal -> source slide number. An ordinal with no source (should not
        happen against a deck the script itself produced) maps to a negative sentinel --
        never a real slide number, so it always fails the kept-slides subset check below
        rather than silently vanishing."""
        for row in rows:
            row["slides"] = sorted(inverse_ordinals.get(o, -o) for o in row["slides"])

    try:
        out_objects, out_id_to_file, _out_fi = _load_deck(out_path)
        src_objects, src_id_to_file, _src_fi = _load_deck(fw_deck)
        out_styles = card_styles(out_objects, out_id_to_file)
        _rekey_slides(out_styles)
        src_styles = card_styles(src_objects, src_id_to_file)
        canvas_scale = 1920.0 / float(payload["slideWidth"])
        match = match_card_stroke_styles(
            out_styles, src_styles, canvas_scale=canvas_scale, min_refs=stroke_min_refs
        )
    except Exception as exc:  # noqa: BLE001
        stroke["refused"] = True
        stroke["reason"] = f"stroke matching failed ({type(exc).__name__}: {exc})"
        warnings.append(f"stroke restore skipped: {stroke['reason']}")
        return stroke

    stroke["notes"] = match["notes"]
    for note in match["notes"]:
        log(note)

    kept_set = set(plan.kept)
    grants: dict[str, dict] = {}
    leak_widths: dict[str, float] = {}
    refused_media: list[dict] = []

    media_status: dict[str, set[tuple[int, bool]]] = {}
    try:
        for idx, (slide_id, _skipped) in enumerate(slide_order(out_objects)):
            ordinal = idx + 1
            number = inverse_ordinals.get(ordinal)
            slide_archive = out_objects.get(slide_id) or {}
            part = ordinal - plan.ordinals[number] if number is not None else 0
            retained_staged_ids = (
                _staged_retained_ids(number, plan, part=part, hidden=hidden.get(number, frozenset()))
                if number is not None else set()
            )
            addressed = {rec["id"]: rec for rec in derive_kind_index(slide_archive, out_objects)}
            for ref in slide_archive.get("drawablesZOrder") or []:
                rid = ref.get("identifier")
                if rid is None:
                    continue
                rid = str(rid)
                rec = addressed.get(rid)
                retained = rec is None or (rec["kind"], rec["kindIndex"]) in retained_staged_ids
                images: list[str] = []
                seen: set[str] = set()
                _collect_stroke_images(rid, out_objects, seen, images)
                for obj_id in images:
                    placement = (-ordinal, True) if number is None else (number, retained)
                    media_status.setdefault(obj_id, set()).add(placement)
    except Exception as exc:  # noqa: BLE001
        stroke["refused"] = True
        stroke["reason"] = f"stroke media census failed ({type(exc).__name__}: {exc})"
        warnings.append(f"stroke restore skipped: {stroke['reason']}")
        return stroke

    def _layout_master_reachable_ids() -> set[str]:
        """Every drawable id reachable from any layout/master root's
        ``drawablesZOrder``, recursing ``TSD.GroupArchive`` children exactly like the
        slide walk above. A root is any ``KN.SlideArchive``, ``KN.SlideLayoutArchive``
        or ``KN.MasterSlideArchive`` object whose id is not in the show's own slide
        tree -- on decks with no dedicated layout/master archive type, layouts and
        masters are plain ``KN.SlideArchive`` objects living outside ``slide_order``."""
        reachable: set[str] = set()

        def _walk(obj_id: str) -> None:
            if obj_id in reachable:
                return
            reachable.add(obj_id)
            obj = out_objects.get(obj_id)
            if obj and obj.get("_pbtype") == "TSD.GroupArchive":
                for ref in obj.get("children") or []:
                    cid = ref.get("identifier")
                    if cid is not None:
                        _walk(str(cid))

        show_slide_ids = {sid for sid, _skipped in slide_order(out_objects)}
        for obj_id, obj in out_objects.items():
            if obj.get("_pbtype") not in (
                "KN.SlideArchive",
                "KN.SlideLayoutArchive",
                "KN.MasterSlideArchive",
            ):
                continue
            if obj_id in show_slide_ids:
                continue
            for ref in obj.get("drawablesZOrder") or []:
                rid = ref.get("identifier")
                if rid is not None:
                    _walk(str(rid))
        return reachable

    layout_master_ids = _layout_master_reachable_ids()
    orphan_refs: dict[str, int] = {}

    def _style_inheritors(style_id: str) -> set[str]:
        """Every ``TSD.MediaStyleArchive`` id in ``out_objects`` that actually resolves
        its stroke from ``style_id`` (``style_id`` itself excluded): the ``super.parent``
        walk, mirroring ``_resolve_stroke`` exactly, must reach ``style_id`` before any
        node carrying its own ``mediaProperties.stroke``. An intermediate style
        with its own stroke shadows ``style_id`` and stops the walk without counting."""
        inheritors: set[str] = set()
        for obj_id, obj in out_objects.items():
            if obj.get("_pbtype") != "TSD.MediaStyleArchive" or obj_id == style_id:
                continue
            cur: str | None = obj_id
            seen: set[str] = set()
            for _ in range(6):
                if cur is None or cur in seen:
                    break
                seen.add(cur)
                o = out_objects.get(cur)
                if not o:
                    break
                if cur == style_id:
                    inheritors.add(obj_id)
                    break
                if (o.get("mediaProperties") or {}).get("stroke") is not None:
                    break
                parent = ((o.get("super") or {}).get("parent") or {}).get("identifier")
                cur = str(parent) if parent is not None else None
        return inheritors

    def _escape_reasons(ref_id: str) -> list[str]:
        """Escape reason for every placement of ``ref_id``: layout/master reachability plus each
        recorded slide placement outside kept or not retained."""
        reasons: list[str] = []
        if ref_id in layout_master_ids:
            reasons.append("layout/master")
        for number, retained in media_status.get(ref_id) or set():
            if number not in kept_set:
                reasons.append(f"slide {number} outside kept")
            elif not retained:
                reasons.append("non-retained (deleted/not-staged) object")
        return reasons

    def _has_retained_placement(ref_id: str) -> bool:
        return any(number in kept_set and retained for number, retained in media_status.get(ref_id) or set())

    def _escaping_refs(style_id: str) -> list[tuple[str, str]]:
        """Every non-retained (or mixed retained/escaping, i.e. shared drawable) reference to
        ``style_id`` or an inheritor; orphans go to ``orphan_refs`` instead."""
        style_ids = {style_id} | _style_inheritors(style_id)
        escapes: list[tuple[str, str]] = []
        for ref_id, obj in out_objects.items():
            sid = (obj.get("style") or {}).get("identifier")
            if sid is None or str(sid) not in style_ids:
                continue
            ptype = obj.get("_pbtype")
            if ptype not in ("TSD.ImageArchive", "TSD.MovieArchive"):
                escapes.append((ref_id, f"non-media object ({ptype or 'unknown'})"))
                continue
            if ref_id not in media_status and ref_id not in layout_master_ids:
                orphan_refs[style_id] = orphan_refs.get(style_id, 0) + 1
                continue
            reasons = _escape_reasons(ref_id)
            if not reasons:
                continue
            if _has_retained_placement(ref_id):
                escapes.append((ref_id, "shared drawable"))
            else:
                escapes.append((ref_id, reasons[0]))
        return escapes

    def _retained_refs(style_id: str) -> list[str]:
        """Image/movie ids directly referencing ``style_id`` with only retained staged placements on kept slides."""
        retained_ids: list[str] = []
        for ref_id, obj in out_objects.items():
            sid = (obj.get("style") or {}).get("identifier")
            if sid is None or str(sid) != style_id:
                continue
            if obj.get("_pbtype") not in ("TSD.ImageArchive", "TSD.MovieArchive"):
                continue
            if _escape_reasons(ref_id):
                continue
            if _has_retained_placement(ref_id):
                retained_ids.append(ref_id)
        return retained_ids

    def _mint_spec_for(style: dict) -> dict | None:
        """Mint spec for ``style``, or ``None`` when none is buildable."""
        if style["pattern"] in (None, "TSDEmptyPattern"):
            return {"width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"}
        if style["width"] is None:
            return None
        source_width = match["widths"].get(style["id"], style["width"] / canvas_scale)
        parent_stroke, _inherited = _resolve_stroke(style["id"], out_objects)
        if parent_stroke is None:
            return None
        stroke_message = copy.deepcopy(parent_stroke)
        stroke_message["width"] = source_width
        return {"stroke_message": stroke_message}

    refused_style_ids: set[str] = set()
    minting_style_ids: set[str] = set()
    mint_specs: dict[str, tuple[list[str], dict, set[int]]] = {}

    def _refuse(
        style_id: str, slides: set[int], escapes: list[tuple[str, str]], reason: str | None = None
    ) -> None:
        if reason is None:
            kinds = sorted({kind for _rid, kind in escapes})
            reason = "style refs slides outside kept" if not kinds else (
                "style refs escaping media: " + "; ".join(kinds)
            )
        refused_media.append({"id": style_id, "reason": reason, "slides": sorted(slides)})
        refused_style_ids.add(style_id)

    def _mint_or_refuse(style_id: str, slides: set[int], escapes: list[tuple[str, str]], spec: dict | None) -> None:
        retained_ids = _retained_refs(style_id)
        if not retained_ids:
            _refuse(style_id, slides, escapes)
        elif spec is None:
            _refuse(style_id, slides, escapes, "no mint spec buildable (unresolvable stroke)")
        else:
            mint_specs[style_id] = (retained_ids, spec, slides)
            minting_style_ids.add(style_id)

    seen_style_ids: set[str] = set()
    for style in out_styles:
        seen_style_ids.add(style["id"])
        slides = set(style["slides"])
        if not slides:
            continue
        if not slides.issubset(kept_set):
            _refuse(style["id"], slides, [])
            continue
        escapes = _escaping_refs(style["id"])
        if escapes:
            _mint_or_refuse(style["id"], slides, escapes, _mint_spec_for(style))
            continue
        no_stroke = style["pattern"] in (None, "TSDEmptyPattern")
        if no_stroke:
            grants[style["id"]] = {"width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"}
        elif style["width"] is not None:
            if style["inherited"]:
                parent_stroke, _inherited = _resolve_stroke(style["id"], out_objects)
                stroke_message = copy.deepcopy(parent_stroke) if parent_stroke is not None else None
                if stroke_message is not None:
                    stroke_message["width"] = style["width"] / canvas_scale
                    grants[style["id"]] = {"stroke_message": stroke_message}
                else:
                    grants[style["id"]] = {
                        "width": style["width"] / canvas_scale,
                        "color": style["color"],
                        "pattern": style["pattern"],
                    }
            elif style["id"] not in match["widths"]:
                leak_widths[style["id"]] = style["width"] / canvas_scale

    matched_widths = {
        sid: w for sid, w in match["widths"].items() if sid not in (refused_style_ids | minting_style_ids)
    }
    widths = {**matched_widths, **leak_widths}
    if widths:
        try:
            restore_result = patch_stroke_widths(out_path, widths)
        except OfflineWriteCorrupted:
            raise
        except Exception as exc:  # noqa: BLE001
            restore_result = {"refused": True, "reason": f"patch_stroke_widths raised: {exc}"}
        stroke["restore"] = restore_result
        stroke["leak_widths"] = leak_widths
        if restore_result.get("refused"):
            warnings.append(f"stroke width restore refused: {restore_result.get('reason')}")

    try:
        strokeless_by_number: dict[str, set[int]] = {}
        for obj_id, placements in media_status.items():
            style_id = ((out_objects.get(obj_id) or {}).get("style") or {}).get("identifier")
            if style_id is None:
                continue
            style_id = str(style_id)
            if style_id in seen_style_ids or grants.get(style_id) is not None:
                continue
            stroke_data, _inherited = _resolve_stroke(style_id, out_objects)
            if stroke_data is not None:
                continue
            for number, _retained in placements:
                strokeless_by_number.setdefault(style_id, set()).add(number)
        for style_id, slides in strokeless_by_number.items():
            if not slides.issubset(kept_set):
                _refuse(style_id, slides, [])
                continue
            escapes = _escaping_refs(style_id)
            if escapes:
                _mint_or_refuse(
                    style_id, slides, escapes,
                    {"width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"},
                )
                continue
            grants[style_id] = {"width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"}
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"strokeless media collection failed ({type(exc).__name__}: {exc})")

    if grants:
        try:
            media_result = patch_media_stroke(out_path, grants)
        except OfflineWriteCorrupted:
            raise
        except Exception as exc:  # noqa: BLE001
            media_result = {"refused": True, "reason": f"patch_media_stroke raised: {exc}"}
        stroke["media"] = media_result
        if media_result.get("refused"):
            warnings.append(f"media stroke patch refused: {media_result.get('reason')}")
    if mint_specs:
        minted: dict[str, dict] = {}
        for style_id, (retained_ids, spec, slides) in mint_specs.items():
            try:
                mint_result = mint_media_style(out_path, style_id, retained_ids, spec)
            except OfflineWriteCorrupted:
                raise
            except Exception as exc:  # noqa: BLE001
                mint_result = {"refused": True, "reason": f"mint_media_style raised: {exc}"}
            if mint_result.get("refused"):
                reason = mint_result.get("reason") or "unknown"
                refused_media.append({"id": style_id, "reason": reason, "slides": sorted(slides), "mint": True})
                refused_style_ids.add(style_id)
            else:
                minted[style_id] = {"new_id": mint_result["new_id"], "drawables": mint_result["drawables"]}
        if minted:
            stroke["minted"] = minted
    excluded_style_ids = refused_style_ids | minting_style_ids
    stroke["chosen"] = [c for c in match["chosen"] if c["id"] not in excluded_style_ids]
    if refused_media:
        stroke["media_refused"] = refused_media
        for r in refused_media:
            label = "mint refused" if r.get("mint") else "refused"
            warnings.append(f"media stroke {r['id']} {label}: {r['reason']}")
    if orphan_refs:
        stroke["orphan_refs"] = orphan_refs
        for sid, n in orphan_refs.items():
            if sid in excluded_style_ids:
                continue
            warnings.append(f"media stroke {sid} patched with {n} unreached referrer(s)")

    return stroke


def _restore_crop_zorder(
    fw_deck: Path,
    out_path: Path,
    plan: AssemblyPlan,
    warnings: list[str],
    *,
    hidden: Mapping[int, frozenset[ItemId]] = {},
) -> dict[int, dict]:
    """Move each re-inserted cropped image back to its deleted source item's z-order
    index, per slide; a slide with nothing to move is absent from the result. ``hidden``
    (keyed by source slide number, same map as the refit loop's) keeps a delete-refused
    placeholder counted as present, not deleted, in the target-index computation."""
    result: dict[int, dict] = {}
    if not plan.crops:
        return result

    src_objects, _src_i2f, _src_fi = _load_deck(fw_deck)
    out_objects, _out_i2f, _out_fi = _load_deck(out_path)
    with zipfile.ZipFile(out_path) as zf:
        out_data_index = _build_data_index(zf.namelist())

    src_order = slide_order(src_objects)
    out_order = slide_order(out_objects)

    for number, crop_specs in plan.crops.items():
        if not crop_specs or plan.splits.get(number) is not None:
            continue
        ordinal = plan.ordinals.get(number)
        if ordinal is None or number > len(src_order) or ordinal > len(out_order):
            continue
        src_slide_id, _skipped = src_order[number - 1]
        out_slide_id, _skipped = out_order[ordinal - 1]
        src_slide = src_objects.get(src_slide_id)
        out_slide = out_objects.get(out_slide_id)
        if src_slide is None or out_slide is None:
            warnings.append(f"slide {number}: crop z-order restore skipped, slide archive missing")
            continue

        src_addr = {rec["id"]: (rec["kind"], rec["kindIndex"]) for rec in derive_kind_index(src_slide, src_objects)}
        src_z = [
            str(ref["identifier"]) for ref in (src_slide.get("drawablesZOrder") or []) if ref.get("identifier") is not None
        ]
        out_z = [
            str(ref["identifier"]) for ref in (out_slide.get("drawablesZOrder") or []) if ref.get("identifier") is not None
        ]
        deleted = set(plan.deletes.get(number, ()))
        deleted_not_cropped = deleted - set(crop_specs) - hidden.get(number, frozenset())

        targets: dict[str, int] = {}
        used_out_ids: set[str] = set()
        refused_target = False
        for source_iid in sorted(crop_specs):
            spec = crop_specs[source_iid]
            pos = next((i for i, zid in enumerate(src_z) if src_addr.get(zid) == source_iid), None)
            if pos is None:
                warnings.append(
                    f"slide {number} image {source_iid[1]}: source not found in z-order, crop z-order not restored"
                )
                continue
            target_index = sum(1 for zid in src_z[:pos] if src_addr.get(zid) not in deleted_not_cropped)

            out_id = None
            for zid in reversed(out_z):
                if zid in used_out_ids:
                    continue
                out_obj = out_objects.get(zid)
                if out_obj is None or out_obj.get("_pbtype") != "TSD.ImageArchive":
                    continue
                data_id = _data_identifier(out_obj)
                if data_id is not None and out_data_index.get(data_id) == spec.source_file_name:
                    out_id = zid
                    break
            if out_id is None:
                warnings.append(
                    f"slide {number} image {source_iid[1]}: cropped insert not found by fileName, "
                    "z-order not restored"
                )
                continue
            if target_index >= len(out_z):
                warnings.append(
                    f"slide {number} image {source_iid[1]}: target index {target_index} out of range "
                    f"for {len(out_z)} drawables, crop z-order not restored"
                )
                refused_target = True
                continue
            used_out_ids.add(out_id)
            targets[out_id] = target_index

        moves = dict(sorted(targets.items(), key=lambda kv: kv[1]))

        if not moves:
            if refused_target:
                warnings.append(f"slide {number}: crop z-order restore refused: target index out of range")
            continue
        try:
            move_result = reorder_drawables(out_path, out_slide_id, moves)
        except OfflineWriteCorrupted:
            raise
        except Exception as exc:  # noqa: BLE001
            move_result = {"refused": True, "reason": f"reorder_drawables raised: {exc}"}
        result[number] = move_result
        if move_result.get("refused"):
            warnings.append(f"slide {number}: crop z-order restore refused: {move_result.get('reason')}")

    return result


def _staged_kind_ranks(
    number: int, plan: AssemblyPlan, *, part: int = 0, hidden: frozenset[ItemId] = frozenset()
) -> dict[str, list[int]]:
    """Per-kind source ``kindIndex`` lists, sorted by post-delete staged index, for this
    slide/part's kept items (own fits/deletes for a split part); ``hidden`` delete targets
    (a default title/body item Keynote refused to delete) stay retained."""
    split_parts = plan.splits.get(number)
    if split_parts is not None:
        split_part = split_parts[part]
        fits_here = split_part.fits
        deleted = set(split_part.deletes)
    else:
        fits_here = plan.fits.get(number, {})
        deleted = set(plan.deletes.get(number, ()))
    retained_ids = (set(fits_here) - deleted) | (deleted & hidden)
    by_kind: dict[str, list[int]] = {}
    for iid in retained_ids:
        if iid[0] == "groupchild":
            continue  # not a top-level `<kind> items of slide N` AS collection member
        kind, idx = iid
        by_kind.setdefault(kind, []).append(idx)
    for kind, idxs in by_kind.items():
        by_kind[kind] = sorted(idxs)
    return by_kind


def _staged_retained_ids(
    number: int, plan: AssemblyPlan, *, part: int = 0, hidden: frozenset[ItemId] = frozenset()
) -> set[tuple[str, int]]:
    """Staged (post-delete/insert) `(kind, kindIndex)` for the items this slide keeps;
    an inserted clip becomes the last staged movie. ``hidden`` (keyed by source slide
    number, same map as the refit loop's) keeps a delete-refused placeholder retained."""
    by_kind = _staged_kind_ranks(number, plan, part=part, hidden=hidden)
    retained = {(kind, rank) for kind, idxs in by_kind.items() for rank in range(len(idxs))}
    if number in plan.clips:
        retained.add(("movie", len(by_kind.get("movie", []))))
    if plan.splits.get(number) is None:
        for i, _iid in enumerate(sorted(plan.crops.get(number, {}))):
            retained.add(("image", len(by_kind.get("image", [])) + i))
    return retained


def _staged_id_for(
    number: int,
    plan: AssemblyPlan,
    source_id: tuple[str, int] | None,
    *,
    part: int = 0,
    hidden: frozenset[ItemId] = frozenset(),
) -> tuple[str, int] | None:
    """Staged id for a source `(kind, kindIndex)`, or ``None`` if deleted or absent."""
    if source_id is None:
        return None
    kind, idx = source_id
    idxs = _staged_kind_ranks(number, plan, part=part, hidden=hidden).get(kind, [])
    if idx not in idxs:
        return None
    return (kind, idxs.index(idx))


def _merge_split_part_builds(
    ordinal_recs: list[tuple[int, dict]],
    plan: AssemblyPlan,
    number: int,
    *,
    hidden: frozenset[ItemId] = frozenset(),
) -> list[dict]:
    """Sums each part's own long-box builds; merges short-item builds, treating a key as
    "repeated" only when genuinely shared across every part (see plan D5). ``hidden`` is
    the source slide's placeholder-hide set (keyed by slide number, not by ordinal/part --
    a delete-refused placeholder is the same source item regardless of which split part
    produced the ``HIDDEN`` marker, so one set per source slide is sufficient here)."""
    split_parts = plan.splits.get(number, ())
    part_fits = [p.fits for p in split_parts]
    long_builds: list[dict] = []
    short_counts: list[Counter] = []
    short_reps: dict[tuple, dict] = {}
    repeated_keys: set[tuple] = set()
    for ordinal, rec in ordinal_recs:
        part = ordinal - plan.ordinals[number]
        source_long_id = next(iter(split_parts[part].stacked_ids), None) if part < len(split_parts) else None
        long_id = _staged_id_for(number, plan, source_long_id, part=part, hidden=hidden)
        staged_idxs = _staged_kind_ranks(number, plan, part=part, hidden=hidden)
        counts: Counter = Counter()
        for b in rec["builds"]:
            if (b["kind"], b["kindIndex"]) == long_id:
                long_builds.append(b)
                continue
            key = (b["effect"], b["animationType"], b["identity"])
            counts[key] += 1
            short_reps.setdefault(key, b)
            idxs = staged_idxs.get(b["kind"], [])
            if b["kindIndex"] < len(idxs):
                src_id = (b["kind"], idxs[b["kindIndex"]])
                if part_fits and all(src_id in fits for fits in part_fits):
                    repeated_keys.add(key)
        short_counts.append(counts)
    all_keys = set().union(*(set(c) for c in short_counts)) if short_counts else set()
    merged_counts: Counter = Counter()
    for key in all_keys:
        counts = [c.get(key, 0) for c in short_counts]
        if key in repeated_keys:
            if len(set(counts)) == 1:
                merged_counts[key] = counts[0]
        else:
            merged_counts[key] = sum(counts)
    return long_builds + [short_reps[key] for key, n in merged_counts.items() for _ in range(n)]


def _verify_builds(
    fw_deck: Path,
    out_path: Path,
    plan: AssemblyPlan,
    warnings: list[str],
    *,
    hidden: Mapping[int, frozenset[ItemId]] = {},
) -> dict:
    """Re-keys the output builds by inverse ordinal and multiset-compares against the
    kept source slides. Raises `AssemblyRefusal` on a surplus, on a missing build not
    attributable to a deletion, on a transition change unexplained by a clip insert, or
    on any reveal-order mismatch. A missing build is tolerated only when it matches (by
    kind/kindIndex, via the source build records) an item this slide's plan actually
    deleted. A surplus `apple:movie-start`/`In` on an inserted clip is tolerated only up to
    the count of matching `apple:movie-start`/`In` builds the slide's deleted source movie
    carried, and only when that deleted movie-start also shows up in `report["missing"]` --
    Keynote auto-attaches the build to a freshly imported movie, and it is legitimate only
    as a replacement for the ones the deleted source movie carried; each tolerated count is
    consumed so a later surplus cannot reuse the same source build, and any surplus beyond
    that (or with no such source build) is refused like any other."""
    from obed_edom.iwa_builds import deck_builds, verify_builds

    builds: dict = {}
    try:
        src = deck_builds(fw_deck)
        out = deck_builds(out_path)
    except Exception as exc:  # noqa: BLE001
        builds["error"] = f"{type(exc).__name__}: {exc}"
        warnings.append(f"builds verify skipped: {builds['error']}")
        return builds

    inverse_ordinals = plan.ordinal_to_number or {ordinal: number for number, ordinal in plan.ordinals.items()}
    number_recs: dict[int, list[tuple[int, dict]]] = {}
    for ordinal, rec in out.items():
        number = inverse_ordinals.get(ordinal)
        if number is None:
            continue
        number_recs.setdefault(number, []).append((ordinal, rec))

    out_by_number: dict[int, dict] = {}
    for number, ordinal_recs in number_recs.items():
        recs = [rec for _ordinal, rec in ordinal_recs]
        transition = recs[0].get("transition")
        for rec in recs[1:]:
            if rec.get("transition") != transition:
                raise AssemblyRefusal(
                    f"slide {number}: split parts disagree on transition "
                    f"({transition} vs {rec.get('transition')})"
                )
        if len(recs) == 1:
            merged_builds = list(recs[0]["builds"])
        else:
            merged_builds = _merge_split_part_builds(
                ordinal_recs, plan, number, hidden=hidden.get(number, frozenset())
            )
        out_by_number[number] = {"slideId": recs[0]["slideId"], "builds": merged_builds, "transition": transition}
    src_by_number = {number: rec for number, rec in src.items() if number in plan.kept}
    builds["out_rekeyed"] = out_by_number

    report = verify_builds(src_by_number, out_by_number, slides=plan.kept)
    builds["report"] = report

    tolerated_surplus: list[dict] = []
    real_surplus: list[dict] = []
    avail_movie_start: dict[int, int] = {}
    for s in report["surplus"]:
        clip = plan.clips.get(s["slide"])
        is_clip_movie_start = (
            clip is not None
            and s["effect"] == "apple:movie-start"
            and s["animationType"] == "In"
            and s["identity"] == ("movie", clip[0].name)
        )
        paired = False
        if is_clip_movie_start:
            matching_src = [
                b for b in src_by_number.get(s["slide"], {}).get("builds", [])
                if b["kind"] == "movie" and b["kindIndex"] == clip[1][1]
                and b["effect"] == "apple:movie-start" and b["animationType"] == "In"
            ]
            if s["slide"] not in avail_movie_start:
                matching_identities = {b["identity"] for b in matching_src}
                missing_count = sum(
                    m["count"] for m in report["missing"]
                    if m["slide"] == s["slide"] and m["effect"] == "apple:movie-start"
                    and m["animationType"] == "In" and m["identity"] in matching_identities
                )
                avail_movie_start[s["slide"]] = min(len(matching_src), missing_count)
            avail = avail_movie_start[s["slide"]]
            if s["count"] <= avail:
                paired = True
                avail_movie_start[s["slide"]] = avail - s["count"]
        (tolerated_surplus if paired else real_surplus).append(s)
    builds["tolerated_surplus"] = tolerated_surplus
    if real_surplus:
        raise AssemblyRefusal(f"builds verify surplus on assembled deck: {real_surplus}")

    src_identity_ids: dict[int, dict[tuple, list[ItemId]]] = {}
    for number, rec in src_by_number.items():
        by_key: dict[tuple, list[ItemId]] = {}
        for b in rec["builds"]:
            key = (b["effect"], b["animationType"], b["identity"])
            by_key.setdefault(key, []).append((b["kind"], b["kindIndex"]))
        src_identity_ids[number] = by_key

    tolerated_missing: list[dict] = []
    real_missing: list[dict] = []
    for m in report["missing"]:
        deleted_ids = set(plan.deletes.get(m["slide"], ()))
        parts = plan.splits.get(m["slide"], ())
        if parts:
            deleted_ids |= set.intersection(*(set(p.deletes) for p in parts))
        key = (m["effect"], m["animationType"], m["identity"])
        candidates = src_identity_ids.get(m["slide"], {}).get(key, [])
        deleted_count = sum(1 for c in candidates if c in deleted_ids)
        if deleted_count >= m["count"]:
            tolerated_missing.append(m)
        else:
            real_missing.append(m)
    builds["tolerated_missing"] = tolerated_missing
    if real_missing:
        raise AssemblyRefusal(f"builds verify missing build(s) not explained by a delete: {real_missing}")

    clip_slides = set(plan.clips)
    unexplained_transitions = [t for t in report["transitions"] if t["slide"] not in clip_slides]
    for t in report["transitions"]:
        if t["slide"] in clip_slides:
            warnings.append(f"transition changed on clip slide {t['slide']}: {t}")
    if unexplained_transitions:
        raise AssemblyRefusal(f"builds verify unexplained transition change(s): {unexplained_transitions}")

    if report["order"]:
        raise AssemblyRefusal(f"builds verify reveal-order mismatch(es): {report['order']}")

    return builds


_MAX_REFITS = 2


def _check_refit_batch_result(proc: Any, label: str) -> None:
    """Refuses on a nonzero refit/shrink pass or any ``MISS`` line -- a failed write
    must never let its (unwritten) measurement be accepted as the new state."""
    if proc.returncode != 0:
        raise AssemblyRefusal(f"{label} failed (exit {proc.returncode}):\n{(proc.stderr or '')[-2000:]}")
    for line in (proc.stderr or "").splitlines():
        m = _MISS_RE.match(line)
        if m:
            raise AssemblyRefusal(f"{label}: write failed for slide {m.group(1)} {m.group(2)}: {m.group(3)}")


def _box_with_runs(box: TextBox, item: Mapping) -> TextBox:
    """Attaches ``item['runs']`` (per-run font+size from ``attach_runs``) to a stacking
    ``TextBox`` so a refit round can use the run-aware estimator."""
    raw_runs = item.get("runs") or []
    runs = tuple(
        Run(r.get("text") or "", r.get("fontName") or box.font_name, r.get("size") or box.size)
        for r in raw_runs
    )
    return _dc_replace(box, runs=runs or None)


def _eligible_refit_items(plan: AssemblyPlan, slide_no: int) -> frozenset[ItemId]:
    """Text items a refit round may re-fit: the slide's stacked ids, excluding a split
    slide (its per-part rects live in ``plan.splits``, not ``plan.fits``; out of scope)
    and any ``GroupChildId`` -- the live refit's offline measure only maps top-level
    ``text`` items (D2b); a group's text is fit once, offline, with the run-aware
    estimator and its safety margin, never refit live (D1 step 6)."""
    if slide_no in plan.splits:
        return frozenset()
    return frozenset(
        iid for iid in plan.stacked_ids.get(slide_no, frozenset()) if iid[0] != "groupchild"
    )


def _refit_still_over_budget(
    plan: AssemblyPlan,
    measured: Mapping[tuple[int, str], float],
    keys: Iterable[tuple[int, str]],
    bands: Mapping[tuple[int, str], tuple[float, float]] | None = None,
    band: Band | None = None,
) -> set[tuple[int, str]]:
    """A key is over budget when its measured height exceeds its rect (+2pt), or --
    when ``bands`` carries its offline ``(y, bottom)`` -- it was placed outside its
    slide's stack band by more than 1pt even though its own rect fits."""
    bands = bands or {}
    over: set[tuple[int, str]] = set()
    for slide_no, item_key in keys:
        item_id: ItemId = ("text", int(item_key.split(":")[1]))
        rect = plan.fits.get(slide_no, {}).get(item_id)
        measured_h = measured.get((slide_no, item_key))
        if rect is None or measured_h is None or measured_h > rect.h + 2.0:
            over.add((slide_no, item_key))
            continue
        y_bottom = bands.get((slide_no, item_key))
        stack_band = plan.stack_bands.get(slide_no, band)
        if y_bottom is not None and stack_band is not None:
            y, bottom = y_bottom
            top = stack_band.bottom - stack_band.height
            if y < top - 1.0 or bottom > stack_band.bottom + 1.0:
                over.add((slide_no, item_key))
    return over


def _build_refit_round(
    plan: AssemblyPlan,
    slides_by_number: Mapping[int, dict],
    todo: set[tuple[int, str]],
    measured: Mapping[tuple[int, str], float],
    band: Band,
    min_text_pt: float,
    warnings: list[str],
    correction: dict[tuple[int, ItemId], float],
    *,
    text_fit: Literal["warn", "shrink"] = "warn",
    warned_gaps: set[tuple[int, ItemId]] | None = None,
    last_t: dict[int, float] | None = None,
    stop_reasons: dict[int, str] | None = None,
    log: Callable[[str], None] = print,
) -> dict[int, dict[ItemId, TextRefit]]:
    """One refit round's writes: per box still over budget, ``r = measured_h /
    last_written_h`` multiplied into ``correction`` (persisted across rounds, clamped to
    ``[1.0, 3.0]``), re-run through ``fit_text_stack`` for the whole stack. A slide in
    ``todo`` that this round cannot produce a write for (group-stacked text, a box-count
    mismatch, missing measurements, or ``fit_text_stack`` finding no valid ``t``) is
    recorded in ``stop_reasons`` rather than dropped silently."""
    warned_gaps = warned_gaps if warned_gaps is not None else set()
    stop_reasons = stop_reasons if stop_reasons is not None else {}
    refits: dict[int, dict[ItemId, TextRefit]] = {}
    for slide_no in sorted({s for s, _k in todo}):
        stacked = plan.stacked_ids.get(slide_no, frozenset())
        if any(iid[0] == "groupchild" for iid in stacked):
            # A group's text is fit once offline and never refit live (D1 step 6,
            # `_eligible_refit_items`) -- skip explicitly rather than relying on the
            # box-count mismatch below, which only skips this slide by accident.
            stop_reasons[slide_no] = "slide has group-stacked text, not eligible for live refit"
            continue
        items_by_id = {(it["kind"], it["kindIndex"]): it for it in slides_by_number[slide_no]["items"]}
        boxes, box_warnings = _text_boxes(list(stacked), items_by_id)
        warnings.extend(f"slide {slide_no}: {w}" for w in box_warnings)
        if len(boxes) != len(stacked):
            stop_reasons[slide_no] = f"text box read {len(boxes)} boxes for {len(stacked)} stacked ids"
            continue
        slide_correction: dict[ItemId, float] = {}
        any_new = False
        for box in boxes:
            corr_key = (slide_no, box.item_id)
            key = (slide_no, f"text:{box.item_id[1]}")
            if key in todo:
                predicted_h = plan.fits[slide_no][box.item_id].h
                measured_h = measured.get(key)
                if predicted_h > 0 and measured_h is not None:
                    ratio = measured_h / predicted_h
                    uncapped = correction.get(corr_key, 1.0) * ratio
                    capped = max(1.0, min(3.0, uncapped))
                    if capped != uncapped:
                        log(
                            f"slide {slide_no}: text {box.item_id[1]} correction clipped "
                            f"{uncapped:.2f} -> {capped:.2f}"
                        )
                    correction[corr_key] = capped
                    any_new = True
            if corr_key in correction:
                slide_correction[box.item_id] = correction[corr_key]
        if not any_new:
            stop_reasons[slide_no] = "no predicted height/measurement available for the over-budget box"
            continue
        stack_band = plan.stack_bands.get(slide_no, band)
        fit = fit_text_stack(boxes, stack_band, min_text_pt, height_correction=slide_correction)
        if fit is None:
            rounded_correction = {iid: round(v, 2) for iid, v in slide_correction.items()}
            stop_reasons[slide_no] = (
                f"fit_text_stack found no t >= floor ({min_text_pt}pt) fitting the stack "
                f"band at correction {rounded_correction}"
            )
            continue
        stop_reasons.pop(slide_no, None)
        t, sizes, heights = fit
        if last_t is not None:
            last_t[slide_no] = t
        rects = _stacked_text_rects(boxes, heights, stack_band)
        slide_refits: dict[ItemId, TextRefit] = {}
        for box in boxes:
            item = items_by_id[box.item_id]
            ranges, unresolved = _run_size_ranges(
                item, t, item_id=box.item_id, slide_number=slide_no, warnings=None,
            )
            if unresolved:
                if t < 1.0 and text_fit == "warn":
                    raise AssemblyRefusal(
                        f"slide {slide_no} box {_item_label(box.item_id)}: run ranges leave a gap and "
                        f"fit t={t:.2f} < 1.0, would overflow with un-shrunken text"
                    )
                gap_key = (slide_no, box.item_id)
                if gap_key not in warned_gaps:
                    warned_gaps.add(gap_key)
                    warnings.append(
                        f"slide {slide_no} box {_item_label(box.item_id)}: run ranges leave a gap, "
                        "preserving source sizing"
                    )
            run_sizes = ranges if isinstance(ranges, (tuple, float)) else sizes[box.item_id]
            slide_refits[box.item_id] = TextRefit(rects[box.item_id], run_sizes)
        short_fit = {
            iid: rect for iid, rect in (plan.short_fit.get(slide_no) or {}).items()
            if iid[0] != "groupchild"
        }
        if short_fit:
            stack_top = min(rect.y for rect in rects.values())
            short_row_h = plan.short_row_h.get(slide_no, 0.0)
            short_rects = _short_row_rects(short_fit, short_row_h, stack_top)
            for iid, short_rect in short_rects.items():
                slide_refits[iid] = TextRefit(short_rect, None)
            rects = {**rects, **short_rects}
        cluster = plan.two_column_cluster.get(slide_no)
        left_band = plan.two_column.get(slide_no)
        if cluster is not None and left_band is not None:
            heading_rect = plan.fits[slide_no][cluster.heading_id]
            block_h = NUMBER_BADGE_PT + _TEXT_STACK_GAP + heading_rect.h
            verse_block_top = min(rect.y for rect in rects.values())
            right_block_centre = (verse_block_top + left_band.bottom) / 2.0
            circle_y = right_block_centre - block_h / 2.0
            heading_y = circle_y + NUMBER_BADGE_PT + _TEXT_STACK_GAP
            circle_x = left_band.x_min + HEADING_COL_W / 2.0 - NUMBER_BADGE_PT / 2.0
            cluster_rects = {
                cluster.heading_id: _dc_replace(heading_rect, y=heading_y),
                cluster.circle_id: Rect(circle_x, circle_y, NUMBER_BADGE_PT, NUMBER_BADGE_PT),
                cluster.number_id: Rect(circle_x, circle_y, NUMBER_BADGE_PT, NUMBER_BADGE_PT),
            }
            for cid, cluster_rect in cluster_rects.items():
                slide_refits[cid] = TextRefit(cluster_rect, None)
            plan.fits[slide_no].update(cluster_rects)
        refits[slide_no] = slide_refits
        plan.fits[slide_no].update(rects)
    return refits


def _offline_measure(
    staging_path: Path,
    plan: AssemblyPlan,
    hidden: Mapping[int, frozenset[ItemId]],
    warnings: list[str],
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], tuple[float, float]], list[str]]:
    """``{(source slide number, 'text:<srcIdx>'): measured h}`` plus ``{key: (y, bottom)}``,
    read from the SAVED staging deck -- the archive's stored naturalSize, the Gate-outcome
    authority (soft_geometry membership is expected and is not a reason to skip). Heights
    are whole-point rounded by the offline reader (+/-0.5pt against the +2.0pt tolerance).
    Split slides are skipped -- ``_eligible_refit_items`` already excludes them. The third
    element carries this call's own measure-failure warnings (a full read failure, or an
    ordinal skipped by the staged/offline text-count cross-check) so a caller can refuse
    immediately on missing measures instead of treating them as merely over budget."""
    measured: dict[tuple[int, str], float] = {}
    bands: dict[tuple[int, str], tuple[float, float]] = {}
    measure_warnings: list[str] = []
    try:
        rects_by_ordinal, _soft = offline_text_rects(staging_path)
    except Exception as exc:  # noqa: BLE001 -- any offline-read failure just skips this round's measure
        msg = f"offline measure failed: {exc}"
        warnings.append(msg)
        measure_warnings.append(msg)
        return measured, bands, measure_warnings
    for number, ordinal in plan.ordinals.items():
        if number in plan.splits:
            continue
        rects = rects_by_ordinal.get(ordinal, {})
        offline_text_count = sum(1 for kind, _idx in rects if kind == "text")
        ranks = _staged_kind_ranks(number, plan, hidden=hidden.get(number, frozenset())).get("text", [])
        if offline_text_count != len(ranks):
            msg = (
                f"slide {number}: staged text count {len(ranks)} != offline text count "
                f"{offline_text_count} on ordinal {ordinal}, refit measurement skipped"
            )
            warnings.append(msg)
            measure_warnings.append(msg)
            continue
        for (kind, staged_idx), (_x, y, _w, h) in rects.items():
            if kind != "text" or staged_idx >= len(ranks):
                continue
            key = (number, f"text:{ranks[staged_idx]}")
            measured[key] = h
            bands[key] = (y, y + h)
    return measured, bands, measure_warnings


def _refuse_on_missing_measures(
    eligible_keys: set[tuple[int, str]],
    measured: Mapping[tuple[int, str], float],
    measure_warnings: list[str],
) -> None:
    """Refuses immediately when an eligible key has no offline measurement -- an offline
    read failure or an E cross-check skip must never cascade into live refit/shrink
    passes that cannot change the outcome."""
    missing = {k for k in eligible_keys if k not in measured}
    if not missing:
        return
    slide_no, item_key = sorted(missing)[0]
    detail = "; ".join(measure_warnings)
    msg = f"slide {slide_no}: text {item_key} offline measure missing"
    if detail:
        msg = f"{msg}: {detail}"
    raise AssemblyRefusal(msg)


def _log_offline_measures(
    plan: AssemblyPlan,
    measured: Mapping[tuple[int, str], float],
    eligible_keys: set[tuple[int, str]],
    log: Callable[[str], None],
    *,
    previous: Mapping[tuple[int, str], float] | None = None,
) -> None:
    """One line per eligible box that is over budget or whose measure changed since
    ``previous`` (``slide N: text K offline=H rect=R over=+D``), plus a one-line count of
    the rest -- the boxes that are fine and unchanged. A box with no rect or no measure is
    logged separately rather than skipped silently."""
    shown = 0
    quiet = 0
    missing = []
    for slide_no, item_key in sorted(eligible_keys):
        item_id: ItemId = ("text", int(item_key.split(":")[1]))
        rect = plan.fits.get(slide_no, {}).get(item_id)
        h = measured.get((slide_no, item_key))
        if rect is None or h is None:
            missing.append((slide_no, item_key))
            continue
        over = h - rect.h
        prev_h = previous.get((slide_no, item_key)) if previous is not None else None
        changed = prev_h is None or abs(prev_h - h) > 0.5
        if over > 0 or changed:
            log(f"slide {slide_no}: text {item_key} offline={h:.0f} rect={rect.h:.0f} over={over:+.0f}")
            shown += 1
        else:
            quiet += 1
    if quiet:
        log(f"{quiet} box(es) within budget and unchanged, not shown")
    for slide_no, item_key in missing:
        log(f"slide {slide_no}: text {item_key} offline measure missing a rect or height")


def _run_refit_and_finalize(
    plan: AssemblyPlan,
    batch: LiveBatch,
    slides_by_number: Mapping[int, dict],
    *,
    band: Band,
    min_text_pt: float,
    allow_split: bool,
    text_fit: Literal["warn", "shrink"],
    staging_path: Path,
    measured: dict[tuple[int, str], float],
    overflows: list[dict],
    warnings: list[str],
    log: Callable[[str], None],
    hidden: Mapping[int, frozenset[ItemId]] = {},
) -> None:
    """Refit loop, run after pass 1 has already saved and closed to ``staging_path``: at
    most ``_MAX_REFITS`` rounds, each reopening ``staging_path`` by POSIX path
    (`keynote.py`'s ``_build_superscript_fix_script`` precedent: a second osascript
    against a document a prior pass already saved), correcting every stacked box still
    over budget and re-saving in place (``retry_on_1712=False``); stops early once every
    box on a touched slide fits its rect within +2pt. The offline naturalSize read of
    ``staging_path`` (:func:`_offline_measure`) is the authority for every trigger and
    stop decision -- the live ``MEASURE``/``OVERFLOW`` lines are diagnostics only (logged
    when they diverge from the offline read by more than 2pt). Split is not re-run after
    a refit (C5, deferred): a still-overflowing split slide is left to the ``text_fit``
    fallback below, same as any other unresolved box."""
    # A group's text is fit once offline and never refit live (D1 step 6): a
    # ``groupchild:`` OVERFLOW line means the offline estimator got it wrong and there
    # is no live fallback for it (F5) -- escalate to a refusal under ``--text-fit warn``,
    # else leave the OVERFLOW warning already appended by the caller in place.
    for o in overflows:
        if str(o["item"]).startswith("groupchild:") and text_fit == "warn":
            raise AssemblyRefusal(
                f"slide {o['slide']}: text {o['item']} overflow, height {o['height']} "
                "-- grouped verse text cannot be refit live"
            )
    eligible_keys = {
        (n, f"text:{iid[1]}")
        for n in plan.ordinals
        for iid in _eligible_refit_items(plan, n)
    }
    if not eligible_keys:
        return
    live_measured = dict(measured)
    measured, bands, measure_warnings = _offline_measure(staging_path, plan, hidden, warnings)
    _refuse_on_missing_measures(eligible_keys, measured, measure_warnings)
    for key, live_h in live_measured.items():
        offline_h = measured.get(key)
        if offline_h is not None and abs(live_h - offline_h) > 2.0:
            log(f"slide {key[0]}: {key[1]} live={live_h} offline={offline_h} diverge")
    _log_offline_measures(plan, measured, eligible_keys, log, previous=live_measured)
    todo = _refit_still_over_budget(plan, measured, eligible_keys, bands=bands, band=band)
    reopen_path = staging_path
    correction: dict[tuple[int, ItemId], float] = {}
    warned_gaps: set[tuple[int, ItemId]] = set()
    last_t: dict[int, float] = dict(plan.stack_t)

    for round_no in range(1, _MAX_REFITS + 1):
        if not todo:
            break
        stop_reasons: dict[int, str] = {}
        refits = _build_refit_round(
            plan, slides_by_number, todo, measured, band, min_text_pt, warnings,
            correction, text_fit=text_fit, warned_gaps=warned_gaps, last_t=last_t,
            stop_reasons=stop_reasons, log=log,
        )
        if not refits:
            for slide_no in sorted({s for s, _k in todo}):
                reason = stop_reasons.get(slide_no, "no write produced for this slide's boxes")
                log(f"refit stopped after round {round_no}: slide {slide_no}: {reason}")
            break
        log(f"refit round {round_no}: slides {sorted(refits)}")
        script = build_refit_script(
            plan, refits, ordinals=plan.ordinals, scratch_path=reopen_path,
            staging_path=staging_path, hidden=hidden,
        )
        proc = batch.run(_osascript_path(script, batch.work), retry_on_1712=False)
        _check_refit_batch_result(proc, f"refit round {round_no}")
        prev_measured = measured
        measured, bands, measure_warnings = _offline_measure(staging_path, plan, hidden, warnings)
        _refuse_on_missing_measures(eligible_keys, measured, measure_warnings)
        _log_offline_measures(plan, measured, eligible_keys, log, previous=prev_measured)
        reopen_path = staging_path
        remaining = {s for s, _k in todo}
        todo = _refit_still_over_budget(plan, measured, eligible_keys, bands=bands, band=band)
        for slide_no in remaining - refits.keys():
            reason = stop_reasons.get(slide_no, "no write produced for this slide's boxes")
            log(f"no refit written in round {round_no}: slide {slide_no}: {reason}")

    if todo:
        if allow_split:
            warnings.append(
                "text still overflows after refit; a live refit round cannot re-run the "
                f"split fallback, applying --text-fit {text_fit}"
            )
        if text_fit == "warn":
            slide_no, item_key = sorted(todo)[0]
            raise AssemblyRefusal(f"slide {slide_no}: text {item_key} still overflows after refit")
        shrink_refits: dict[int, dict[ItemId, TextRefit]] = {}
        for slide_no, item_key in todo:
            item_id: ItemId = ("text", int(item_key.split(":")[1]))
            rect = plan.fits[slide_no][item_id]
            item = next(it for it in slides_by_number[slide_no]["items"]
                        if (it["kind"], it["kindIndex"]) == item_id)
            run_sizes_src = [float(r["size"]) for r in (item.get("runs") or []) if r.get("size") is not None]
            min_source_size = min(run_sizes_src) if run_sizes_src else float(item.get("size") or min_text_pt)
            lead_source_size = float(item.get("size") or min_source_size)
            shrink_box = _box_with_runs(TextBox(item_id, "", "", lead_source_size), item)
            t_floor = min(1.0, _box_min_t(shrink_box, min_text_pt))
            t_prev = last_t.get(slide_no, 1.0)
            measured_h = measured.get((slide_no, item_key))
            t_fit = t_prev * (rect.h / measured_h) if measured_h and measured_h > 0 else t_prev
            t = min(max(min(t_fit, t_prev), t_floor), t_prev)
            clamped = t == t_floor and t_floor > t_fit
            at_floor = t_floor >= t_prev
            ranges, unresolved = _run_size_ranges(
                item, t, item_id=item_id, slide_number=slide_no, warnings=None,
            )
            if unresolved:
                gap_key = (slide_no, item_id)
                if gap_key not in warned_gaps:
                    warned_gaps.add(gap_key)
                    warnings.append(
                        f"slide {slide_no} box {item_id[1]}: run ranges leave a gap, "
                        "flattening run sizes to the lead size under --text-fit shrink"
                    )
            run_sizes = ranges if isinstance(ranges, (tuple, float)) else t * lead_source_size
            if isinstance(ranges, tuple):
                lo = round(min(sz for _s, _e, sz in ranges), 1)
                hi = round(max(sz for _s, _e, sz in ranges), 1)
                size_desc = f"{lo}pt" if lo == hi else f"{lo}-{hi}pt"
            else:
                size_desc = f"{round(t * lead_source_size, 1)}pt"
            shrink_refits.setdefault(slide_no, {})[item_id] = TextRefit(rect, run_sizes)
            if at_floor:
                warnings.append(
                    f"slide {slide_no}: text {item_key} already at the floor, "
                    f"left at {size_desc}"
                )
            else:
                floor_note = f" (floor {min_text_pt}pt)" if clamped else ""
                warnings.append(
                    f"slide {slide_no}: text {item_key} shrunk to {size_desc} after refit{floor_note}"
                )
        script = build_refit_script(
            plan, shrink_refits, ordinals=plan.ordinals, scratch_path=reopen_path,
            staging_path=staging_path, hidden=hidden,
        )
        proc = batch.run(_osascript_path(script, batch.work), retry_on_1712=False)
        _check_refit_batch_result(proc, "shrink fallback")
        prev_measured = measured
        measured, bands, measure_warnings = _offline_measure(staging_path, plan, hidden, warnings)
        _refuse_on_missing_measures(eligible_keys, measured, measure_warnings)
        _log_offline_measures(plan, measured, eligible_keys, log, previous=prev_measured)
        todo = _refit_still_over_budget(plan, measured, eligible_keys, bands=bands, band=band)

    if todo:
        slide_no, item_key = sorted(todo)[0]
        raise AssemblyRefusal(
            f"slide {slide_no}: text {item_key} still overflows after refit and shrink"
        )

    resolved_keys = eligible_keys - todo
    if resolved_keys:
        stale_prefixes = tuple(f"slide {s}: text {i} overflow, height " for s, i in resolved_keys)
        warnings[:] = [w for w in warnings if not w.startswith(stale_prefixes)]
    overflows[:] = [o for o in overflows if (o["slide"], o["item"]) not in eligible_keys]


def assemble_dsk_deck(
    fw_deck: Path,
    out_path: Path,
    *,
    decisions: Mapping[int, SlideDecision],
    band: Band | None = None,
    reference_deck: Path | None = None,
    clips: Mapping[int, Path] = {},
    log: Callable[[str], None] = print,
    rss_limit_bytes: int = DEFAULT_RSS_LIMIT_BYTES,
    layout_policy: LayoutPolicy = "import",
    black_layout_names: Sequence[str] = DEFAULT_TRANSPARENT_LAYOUT_NAMES,
    import_layout_names: Sequence[str] = DEFAULT_DSK_LAYOUT_NAMES,
    layout_template: Path = DEFAULT_LAYOUT_TEMPLATE,
    stroke_min_refs: int = 1,
    text_fit: Literal["warn", "shrink"] = "warn",
    min_text_pt: float = DEFAULT_MIN_TEXT_PT,
    allow_split: bool = True,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    crop_dir: Path | None = None,
    no_image_crop: bool = False,
    no_auto_anchor: bool = False,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
    split_overrides: Mapping[int, int] | None = None,
) -> AssembleResult:
    """Runs the live AppleScript batch end to end (plan -> LiveBatch -> script),
    then two offline IWA post-passes: card-border stroke restore and build/transition
    verification. The batch script saves-as (Keynote's sdef does document a `save ... in`
    verb, per `maps_keynote.py`) to a staging path inside the batch's own disposable work
    dir, never in place and never straight to `out_path` -- both post-passes run against
    that staging copy, and only once they pass (`_verify_builds` raises on a surplus) is
    it copied to `out_path`. A refusal after a failed post-pass therefore never leaves a
    corrupt or unverified deck sitting at `out_path`.

    `layout_policy` -- see `build_assembly_script` -- defaults to "import". When "import",
    `check_layout_import_preconditions` refuses offline before Keynote launches, and
    `verify_staged_layouts_alpha_safe` refuses offline against the staged deck before it
    is published to `out_path`."""
    fw_deck = Path(fw_deck)
    out_path = Path(out_path)
    dsk_live.guard_out_dir(out_path.parent, fw_deck)

    if layout_policy == "import":
        check_layout_import_preconditions(
            fw_deck, layout_template=layout_template, layout_names=import_layout_names
        )

    if reference_deck is not None:
        resolved_band = read_band(reference_deck)
    elif band is not None:
        resolved_band = band
    else:
        resolved_band = DEFAULT_BAND

    include_side = frozenset(d.slide for d in decisions.values() if d.keep_side)
    deck = _load_deck(fw_deck)
    payload, classes, runs = load_assembly_inputs(
        fw_deck, include_side=include_side, text_slide_words=text_slide_words,
        no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )
    builds_by_number = deck_builds(fw_deck, deck=deck)
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=resolved_band, clips=clips, runs=runs, text_fit=text_fit,
        min_text_pt=min_text_pt, text_slide_words=text_slide_words, allow_split=allow_split,
        deck=deck, fw_deck=fw_deck, crop_dir=crop_dir, no_image_crop=no_image_crop,
        builds=builds_by_number, no_auto_anchor=no_auto_anchor,
        no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop, split_overrides=split_overrides,
        all_classes=classes,
    )
    for number in sorted(plan.anchors):
        log(f"slide {number}: anchor {plan.anchors[number]}")

    warnings: list[str] = list(plan.warnings)
    movie_props: dict[int, dict[str, str]] = {}
    overflows: list[dict] = []
    measured: dict[tuple[int, str], float] = {}
    elapsed_by_slide: dict[int, float] = {}
    t0 = time.monotonic()

    slide_layout_names = resolve_slide_layouts(payload, classes, plan) if layout_policy == "import" else None
    if slide_layout_names:
        plan = apply_layout_slot_rects(plan, classes, payload, slide_layout_names)

    with LiveBatch(fw_deck, out_path.parent, rss_limit_bytes=rss_limit_bytes, log=log) as batch:
        staging_path = batch.work / f"staged-{out_path.name}"
        script = build_assembly_script(
            plan,
            scratch_path=batch.scratch,
            staging_path=staging_path,
            layout_policy=layout_policy,
            black_layout_names=black_layout_names,
            import_layout_names=import_layout_names,
            layout_template=layout_template,
            text_fit=text_fit,
            slide_layout_names=slide_layout_names,
        )
        script_path = _osascript_path(script, batch.work)

        def on_progress(slide: int) -> None:
            elapsed_by_slide[slide] = time.monotonic() - t0

        proc = batch.run(script_path, on_progress=on_progress)

        last_error: tuple[int, int, str] | None = None
        hidden: list[dict] = []
        hidden_ids: dict[int, set[ItemId]] = {}
        for line in (proc.stderr or "").splitlines():
            error_m = _ERROR_RE.match(line)
            if error_m:
                last_error = (int(error_m.group(1)), int(error_m.group(2)), error_m.group(3))
                continue
            hidden_m = _HIDDEN_RE.match(line)
            if hidden_m:
                slide_no, addr, slot = int(hidden_m.group(1)), hidden_m.group(2), hidden_m.group(3)
                hidden.append({"slide": slide_no, "addr": addr, "slot": slot})
                warnings.append(f"slide {slide_no}: {addr} hidden ({slot} placeholder, delete refused)")
                item_id = _item_id_from_addr(addr)
                if item_id is not None:
                    hidden_ids.setdefault(slide_no, set()).add(item_id)
                continue
            prop_m = _OBED_PROP_RE.match(line)
            if prop_m:
                slide_no = int(prop_m.group(1))
                key = prop_m.group(2)
                if key == "OVERFLOW":
                    item_key, _sep, height_s = prop_m.group(3).partition("\t")
                    overflows.append({"slide": slide_no, "item": item_key, "height": float(height_s)})
                    warnings.append(f"slide {slide_no}: text {item_key} overflow, height {height_s}")
                elif key == "MEASURE":
                    item_key, _sep, height_s = prop_m.group(3).partition("\t")
                    measured[(slide_no, item_key)] = float(height_s)
                else:
                    movie_props.setdefault(slide_no, {})[key] = prop_m.group(3)
                continue
            miss_m = _MISS_RE.match(line)
            if miss_m:
                warnings.append(f"slide {miss_m.group(1)}: write failed for {miss_m.group(2)}: {miss_m.group(3)}")

        try:
            if proc.returncode != 0:
                if last_error is not None:
                    slide_no, errnum, errmsg = last_error
                    raise AssemblyRefusal(f"slide {slide_no}: Keynote assembly failed (errNum {errnum}): {errmsg}")
                raise AssemblyRefusal(f"Keynote assembly AppleScript failed:\n{proc.stderr}")

            log(f"movie_props: {movie_props}")

            hidden_map = {n: frozenset(ids) for n, ids in hidden_ids.items()}
            slides_by_number = {s["number"]: s for s in payload.get("slides") or []}
            _run_refit_and_finalize(
                plan, batch, slides_by_number,
                band=resolved_band, min_text_pt=min_text_pt, allow_split=allow_split, text_fit=text_fit,
                staging_path=staging_path, measured=measured, overflows=overflows, warnings=warnings, log=log,
                hidden=hidden_map,
            )

            if layout_policy == "import":
                verify_staged_layouts_alpha_safe(staging_path, plan)

            stroke = _restore_stroke(
                fw_deck, staging_path, plan, payload, stroke_min_refs, warnings, log, hidden=hidden_map,
            )
            zorder = _restore_crop_zorder(fw_deck, staging_path, plan, warnings, hidden=hidden_map)
            builds = _verify_builds(fw_deck, staging_path, plan, warnings, hidden=hidden_map)
        except AssemblyRefusal:
            # Pass 1 may already have saved to `staging_path` before failing (a
            # post-save script failure, or a refusal in the refit/verify steps below)
            # -- keep it next to `out_path` rather than letting the batch's disposable
            # work dir discard it, so a refusal after pass 1 still leaves the operator
            # something to inspect.
            if staging_path.exists():
                refused_path = out_path.parent / f"{out_path.stem}.refused.key"
                try:
                    copy_keynote(staging_path, refused_path)
                except Exception as exc:  # noqa: BLE001
                    log(f"could not keep the staged deck: {exc}")
                else:
                    log(f"staged deck kept at {refused_path}")
            raise

        copy_keynote(staging_path, out_path)

    wall_s = time.monotonic() - t0

    return AssembleResult(
        path=out_path,
        slides_kept=plan.kept,
        ordinals=plan.ordinals,
        fits=plan.fits,
        clips_inserted={number: clip_path for number, (clip_path, _iid) in plan.clips.items()},
        stroke=stroke,
        zorder=zorder,
        builds=builds,
        size_bytes=_package_size(out_path),
        source_size_bytes=_package_size(fw_deck),
        wall_s=wall_s,
        warnings=tuple(warnings),
        movie_props=movie_props,
        overflows=tuple(overflows),
        ordinal_to_number=plan.ordinal_to_number,
        hidden=tuple(hidden),
    )
