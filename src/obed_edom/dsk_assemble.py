"""DSK deck assembly: pure planning over the offline payload/classifier, plus the
AppleScript emitter that carries out the plan live -- copy-and-transform, not build-from-template.
Clip slides are force-set to `no transition effect` since the clip owns timing; the verify
report's transition note on clip slides is expected, not a defect.
"""
from __future__ import annotations

import copy
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
    LiveBatch,
    _applescript_string_list,
    _as_escape,
    _ERROR_RE,
    _keynote_tell,
    _keynote_terms,
    _osascript_path,
    layout_import_lines,
    ordinal_map,
)
from obed_edom.dsk_plan import (
    Band,
    CropRefusal,
    CropSpec,
    DEFAULT_TEXT_SLIDE_WORDS,
    ItemId,
    Run,
    SlideClass,
    TextBox,
    _delete_order,
    _item_object_ids,
    _TEXT_GAP_PT,
    classify_deck,
    fit_slide,
    fit_text_stack,
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
    attach_group_captions,
    attach_group_child_text,
    attach_group_content_signature,
    attach_runs,
    slide_order,
)
from obed_edom.iwa_write import OfflineWriteCorrupted, reorder_drawables
from obed_edom.map_remap import CENTRE_PANEL_RECT, LW_WALL_SIZE, Rect, item_rect
from obed_edom.offline_inspect import _build_data_index, _canvas_size, _data_identifier, offline_wall_payload
from obed_edom.remap_keynote import _AS_KIND_NAMES, _as_num, _delete_or_hide_placeholder_lines, copy_keynote

DEFAULT_BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)
DEFAULT_MIN_TEXT_PT = 24.0
_TEXT_STACK_GAP = _TEXT_GAP_PT

LayoutPolicy = Literal["preserve", "import"]

DEFAULT_TRANSPARENT_LAYOUT_NAMES: tuple[str, ...] = ("Blank Black",)

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
                f"slide {slide_number} text {item_id[1]}: run ranges leave a gap"
            )
        return None, gap
    covered = not gap and ranges[0][0] == 1 and ranges[-1][1] == full_len
    if covered:
        covered = all(b[0] == a[1] + 1 for a, b in zip(ranges, ranges[1:]))
    if not covered:
        if warnings is not None and item_id is not None:
            warnings.append(
                f"slide {slide_number} text {item_id[1]}: run ranges leave a gap"
            )
        return None, True
    if len({round(sz, 6) for _s, _e, sz in ranges}) <= 1:
        return ranges[0][2], False
    return tuple(ranges), False


def _text_boxes(
    long_ids: Sequence[ItemId], items_by_id: Mapping[ItemId, dict]
) -> tuple[list[TextBox], list[str]]:
    """``([TextBox, ...], [warning, ...])`` for ``long_ids`` in source order (y then x);
    a box whose font/size can't be resolved is omitted and warned about (D4 fallback)."""
    ordered = sorted(long_ids, key=lambda iid: (items_by_id[iid].get("y", 0.0), items_by_id[iid].get("x", 0.0)))
    boxes: list[TextBox] = []
    warnings: list[str] = []
    for iid in ordered:
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
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> float | None:
    """The one shared uniform scale ``fit_slide`` applies across a slide; ``None`` when
    the slide has no visible/fit content."""
    union = visible_union(
        items, include_side=include_side, wall=wall, group_child_text=group_child_text,
        text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )
    if union is None:
        return None
    fit = fit_slide(
        items, band, include_side=include_side, anchor=anchor, wall=wall, group_child_text=group_child_text,
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
    """True when `signature` has an ``image:``/``movie:`` leaf; unresolved/empty counts as content."""
    if not signature:
        return True
    return any(part.startswith(("image:", "movie:")) for part in signature.split("\n") if part)


def _content_item_count(cls: SlideClass, group_signature: Mapping[int, str | None] | None = None) -> int:
    """Count of kept image/movie/group items; text-only content never counts towards it."""
    group_signature = group_signature or {}
    count = 0
    for kind, kind_index in cls.kept:
        if kind not in ("image", "movie", "group"):
            continue
        if kind == "group" and not _group_has_media(group_signature.get(kind_index)):
            continue
        count += 1
    return count


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
) -> AssemblyPlan:
    """Pure planning over `payload`/`classes`, EXCEPT the cropped image files under
    `crop_dir` (unless `no_image_crop`), committed only once every slide validates."""
    classes_by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    wall = (payload["slideWidth"], payload["slideHeight"])

    kept_numbers = sorted(
        number
        for number, decision in decisions.items()
        if decision.action in ("in_deck", "both")
        and classes_by_number[number].category != "empty"
    )

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
            warnings.extend(f"slide {number}: {w}" for w in cls.mirror_warnings)

            if decision.anchor in (None, "auto"):
                anchor = "centre" if no_auto_anchor else (
                    "right" if _content_item_count(cls, slide.get("groupChildSignature")) == 1 else "centre"
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
                    children = children_payload.get(kind_index)
                    if has_text and children is None:
                        raise AssemblyRefusal(
                            f"slide {number}: group {kind_index} has text but no offline child "
                            "metadata (nested/rotated/masked group, or an autosize child whose "
                            "naturalSize disagrees with its frame) -- refusing to write blind"
                        )
                    if children is not None:
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

            stacked_ids: set[ItemId] = set()
            stacked_text_sizes: dict[ItemId, float] = {}
            stacked_shrink_only_sizes: dict[ItemId, float] = {}
            stacked_run_sizes: dict[ItemId, tuple[tuple[int, int, float], ...]] = {}
            if cls.is_text and cls.long_text_ids:
                long_ids = [iid for iid in cls.long_text_ids if iid in fit]
                boxes, box_warnings = _text_boxes(long_ids, items_by_id)
                warnings.extend(f"slide {number}: {w}" for w in box_warnings)
                if boxes and len(boxes) == len(long_ids):
                    long_id_set = set(long_ids)
                    short_fit = {iid: rect for iid, rect in fit.items() if iid not in long_id_set}
                    stack_band = band
                    short_row_h = 0.0
                    if short_fit:
                        short_row_h = max(rect.h for rect in short_fit.values())
                        budget = max(0.0, band.height - short_row_h - _TEXT_STACK_GAP)
                        stack_band = _dc_replace(band, height=budget)

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
                        if short_fit:
                            stack_top = min(rect.y for rect in long_rects.values())
                            fit.update(_short_row_rects(short_fit, short_row_h, stack_top))
                        stacked_ids = {box.item_id for box in boxes}
                        for box in boxes:
                            ranges, unresolved = _run_size_ranges(
                                items_by_id[box.item_id], t, item_id=box.item_id,
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
                                            f"slide {number} box {box.item_id[1]}: run ranges leave a gap and "
                                            f"fit t={t:.2f} < 1.0, would overflow with un-shrunken text"
                                        )
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap and "
                                        f"fit t={t:.2f} < 1.0, flattening run sizes to the lead size under "
                                        "--text-fit shrink"
                                    )
                                elif text_fit == "shrink":
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap, "
                                        "flattening run sizes to the lead size under --text-fit shrink"
                                    )
                                else:
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap, "
                                        "preserving source sizing"
                                    )
                                stacked_shrink_only_sizes[box.item_id] = sizes[box.item_id]
                            else:
                                stacked_text_sizes[box.item_id] = sizes[box.item_id]
                    elif not allow_split:
                        raise AssemblyRefusal(
                            f"slide {number}: text does not fit the band at --min-text-pt {min_text_pt}"
                        )
                    elif len(boxes) < 2:
                        raise AssemblyRefusal(
                            f"slide {number} box {boxes[0].item_id[1]} does not fit the band even alone at --min-text-pt {min_text_pt}"
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
                                    f"slide {number} box {box.item_id[1]} does not fit the band even alone at --min-text-pt {min_text_pt}"
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
                            part_item = items_by_id[box.item_id]
                            part_autosize = (
                                frozenset({box.item_id})
                                if part_item.get("w") == 0.0 or part_item.get("h") == 0.0
                                else frozenset()
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
                                            f"slide {number} box {box.item_id[1]}: run ranges leave a gap and "
                                            f"fit t={t1:.2f} < 1.0, would overflow with un-shrunken text"
                                        )
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap and "
                                        f"fit t={t1:.2f} < 1.0, flattening run sizes to the lead size under "
                                        "--text-fit shrink"
                                    )
                                elif text_fit == "shrink":
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap, "
                                        "flattening run sizes to the lead size under --text-fit shrink"
                                    )
                                else:
                                    warnings.append(
                                        f"slide {number} box {box.item_id[1]}: run ranges leave a gap, "
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
            slide_autosize: set[ItemId] = set()
            for iid in cls.kept:
                if iid[0] != "text" or iid in stacked_ids:
                    continue
                item = items_by_id.get(iid)
                if item is None:
                    continue
                if item.get("w") == 0.0 or item.get("h") == 0.0:
                    slide_autosize.add(iid)
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
                "x": abs_gx + cx, "cy": abs_gy + cy, "y": abs_gy + cy - nh / 2.0, "w": nw, "h": nh,
                "group_path": group_path,
            })
            continue
        kind = "shape" if "shape" in assigned else kinds[0]
        if rotated and not masked:
            fx, fy, fw, fh = _frame_rect(geom)
            out.append({
                "kind": kind, "kindIndex": assigned[kind], "autosize": False,
                "x": abs_gx + fx, "y": abs_gy + fy, "w": fw, "h": fh, "angle": ca,
                "group_path": group_path,
            })
            continue
        x0, y0, x1, y1 = _leaf_bbox(child, abs_gx, abs_gy, objects)
        out.append({
            "kind": kind, "kindIndex": assigned[kind], "autosize": False,
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "group_path": group_path,
        })
    return out


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


def _theme_layout_slides(objects: dict[str, dict]) -> list[tuple[str, dict, dict]]:
    """``[(name, layoutNode, layoutSlide)]`` for every ``KN.ThemeArchive.templates``
    entry -- Keynote's IWA graph has no separate layout type; a layout IS a
    ``KN.SlideArchive`` referenced from the theme's ``templates`` list (each a
    ``KN.SlideNodeArchive`` wrapping the slide, same shape as an ordinary slide)."""
    theme = next((o for o in objects.values() if o.get("_pbtype") == "KN.ThemeArchive"), None)
    if theme is None:
        return []
    out: list[tuple[str, dict, dict]] = []
    for ref in theme.get("templates") or []:
        node = objects.get(str(ref.get("identifier")))
        if not node:
            continue
        slide_id = (node.get("slide") or {}).get("identifier")
        slide = objects.get(str(slide_id)) if slide_id is not None else None
        if slide is None:
            continue
        out.append((slide.get("name") or "", node, slide))
    return out


def _find_layout_by_name(objects: dict[str, dict], name: str) -> dict | None:
    target = name.strip().lower()
    for layout_name, _node, slide in _theme_layout_slides(objects):
        if layout_name.strip().lower() == target:
            return slide
    return None


def _first_matching_layout(objects: dict[str, dict], names: Sequence[str]) -> tuple[str | None, dict | None]:
    """First theme layout (in ``templates`` order) whose name case-insensitively matches
    any of ``names`` -- mirrors the live search ``layout_import_lines`` runs against the
    layout template."""
    approved = {n.strip().lower() for n in names}
    for layout_name, _node, slide in _theme_layout_slides(objects):
        if layout_name.strip().lower() in approved:
            return layout_name, slide
    return None, None


def layout_alpha_safe(slide_archive: dict, objects: dict[str, dict], canvas: tuple[float, float]) -> bool:
    """A slide/layout PNG-exports opaque whenever it owns a drawable spanning the full
    ``canvas`` (``x<=0``, ``y<=0``, ``x+w>=W``, ``y+h>=H``); one with no such drawable
    -- including zero drawables -- exports transparent. Frames come from
    ``compose_geometry`` (masks, rotation and group unions composed, not raw
    ``geometry``)."""
    width, height = canvas
    for rec in compose_geometry(slide_archive, objects):
        x, y, w, h = rec["x"], rec["y"], rec["w"], rec["h"]
        if x <= 0 and y <= 0 and x + w >= width and y + h >= height:
            return False
    return True


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
    ``templateSlideId`` -- a 128-bit uuid every slide's ``KN.SlideNodeArchive`` carries,
    equal to the same field on exactly one ``KN.ThemeArchive.templates`` node. This is
    Keynote's only offline link from a slide to its layout; there is no direct object
    reference. ``None`` if the ordinal is out of range or the uuid doesn't resolve."""
    nodes = _slide_nodes(objects)
    if not (1 <= ordinal <= len(nodes)):
        return None
    target = nodes[ordinal - 1].get("templateSlideId")
    if target is None:
        return None
    for _name, node, slide in _theme_layout_slides(objects):
        if node.get("templateSlideId") == target:
            return slide
    return None


def check_layout_import_preconditions(
    fw_deck: Path,
    *,
    layout_template: Path,
    black_layout_names: Sequence[str],
) -> None:
    """Offline plan-time precondition for ``layout_policy="import"``, run before Keynote
    ever launches. Refuses (``AssemblyRefusal``) when:

    - `layout_template` has no layout matching `black_layout_names`, or its first match
      (in `templates` order -- the same one the live search finds) is not alpha-safe --
      importing a donor that isn't alpha-safe defeats the point.
    - `fw_deck` already owns a layout with that same name and it is NOT alpha-safe: the
      live import (`layout_import_lines`) makes a new slide with `base layout: donorLayout`
      then moves it into the FW-deck copy -- Keynote dedupes slide layouts by name
      (case-insensitive) on import, so it would silently keep the FW deck's own
      (unsafe) layout instead of the template's donor.
    """
    template_objects, _tf, _tfi = _load_deck(layout_template)
    donor_name, donor_slide = _first_matching_layout(template_objects, black_layout_names)
    if donor_slide is None:
        raise AssemblyRefusal(
            f"no layout named any of {list(black_layout_names)} found in layout template {layout_template}"
        )
    if not layout_alpha_safe(donor_slide, template_objects, _canvas_size(template_objects)):
        raise AssemblyRefusal(f"layout template donor {donor_name!r} in {layout_template} is not alpha-safe")

    fw_objects, _ff, _ffi = _load_deck(fw_deck)
    fw_owned = _find_layout_by_name(fw_objects, donor_name)
    if fw_owned is not None and not layout_alpha_safe(fw_owned, fw_objects, _canvas_size(fw_objects)):
        raise AssemblyRefusal(
            f"FW deck already owns a layout named {donor_name!r} that is not alpha-safe; "
            "Keynote's name-based import dedupe would reuse it instead of the template donor"
        )


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
        if not child.get("autosize"):
            body.append(f"            set height of theObj to {_as_num(child['h'] * scale)}")
        body.append(f"            set position of theObj to {{{_as_num(new_x)}, {_as_num(new_y)}}}")
        if child.get("angle"):
            body.append(f"            set rotation of theObj to {_as_num(child['angle'])}")
        if caption_child is not None and child is caption_child:
            body.append(f"            set size of object text of theObj to {_as_num(text_size)}")
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


_MEASURE_POLL_DELAY = 0.2
_MEASURE_MAX_POLLS = 5


def _text_measure_lines(
    number: int, kind_index: int, addr: str, target_h: float, *, ordinal: int | None = None
) -> list[str]:
    """Poll a text item's live height until two consecutive reads agree (`delay 0.2`, at
    most 5 polls), log `OBED\\t<n>\\tMEASURE\\ttext:<idx>\\t<h>`, then `OBED\\t<n>\\tOVERFLOW\\t...`
    when it still exceeds `target_h` by more than 2pt."""
    item_key = f"text:{kind_index}" if ordinal is None else f"text:{kind_index}:{ordinal}"
    return [
        "        try",
        "          set prevH to -1",
        f"          repeat with i from 1 to {_MEASURE_MAX_POLLS}",
        f"            set curH to (height of {addr})",
        "            if curH = prevH then",
        "              exit repeat",
        "            end if",
        "            set prevH to curH",
        f"            delay {_MEASURE_POLL_DELAY}",
        "          end repeat",
        f'          log ("OBED" & tab & "{number}" & tab & "MEASURE" & tab & '
        f'"{item_key}" & tab & (curH as string))',
        f"          if curH > {_as_num(target_h)} + 2.0 then",
        f'            log ("OBED" & tab & "{number}" & tab & "OVERFLOW" & tab & '
        f'"{item_key}" & tab & (curH as string))',
        "          end if",
        "        end try",
    ]


def _second_measure_lines(number: int, kind_index: int, addr: str, *, ordinal: int | None = None) -> list[str]:
    """End-of-slide-loop re-read of a stacked box's height, logged under a distinct
    ``MEASURE2`` key so a run can prove the first ``MEASURE`` had already settled rather
    than agreeing twice on a stale value."""
    item_key = f"text:{kind_index}" if ordinal is None else f"text:{kind_index}:{ordinal}"
    return [
        "        try",
        f'          log ("OBED" & tab & "{number}" & tab & "MEASURE2" & tab & '
        f'"{item_key}" & tab & ((height of {addr}) as string))',
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

    for item_id, rect in fit.items():
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
        body.append(f"          set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}")
        if kind == "text" and item_id in run_sizes_here:
            for start, end, size in run_sizes_here[item_id]:
                body.append(
                    f"          set size of characters {start} thru {end} "
                    f"of object text of theObj to {_as_num(size)}"
                )
        elif kind == "text" and item_id in text_sizes:
            body.append(f"          set size of object text of theObj to {_as_num(text_sizes[item_id])}")
        elif kind == "text" and text_fit == "shrink" and item_id in shrink_text_sizes:
            body.append(
                f"          set size of object text of theObj to {_as_num(shrink_text_sizes[item_id])}"
            )
        lines += _locked_write_block(number, addr, body)
        if kind == "text" and (item_id not in text_sizes or item_id in stacked_ids_here):
            overflow_ordinal = ordinal if split_parts is not None else None
            lines += _text_measure_lines(number, kind_index, addr, rect.h, ordinal=overflow_ordinal)

    for item_id in stacked_ids_here:
        kind, kind_index = item_id
        name = _AS_KIND_NAMES.get(kind)
        if not name:
            continue
        addr = f"{name} {kind_index + 1} of slide {ordinal}"
        overflow_ordinal = ordinal if split_parts is not None else None
        lines += _second_measure_lines(number, kind_index, addr, ordinal=overflow_ordinal)

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
    layout_template: Path = DEFAULT_LAYOUT_TEMPLATE,
    text_fit: Literal["warn", "shrink"] = "warn",
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
    - "import" (default): always imports the alpha-safe layout from `layout_template`
      (a full-canvas drawable exports opaque even from a Blank layout), never an
      FW-owned layout matched by name -- a same-named layout the FW deck happens to
      own is not guaranteed to be alpha-safe (see `check_layout_import_preconditions`,
      the plan-time dedupe-trap refusal).
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
        lines += [
            '      set blackLayoutName to ""',
            f"      set approvedBlackNames to {approved_names}",
            "      set donorSlide to missing value",
        ]
        lines += layout_import_lines("theDoc", "approvedBlackNames", layout_template)
        lines += [
            '      if blackLayoutName is "" then',
            '        error "layout import failed to resolve a black layout"',
            "      end if",
            "      set targetLayout to missing value",
            "      repeat with lay in slide layouts of theDoc",
            "        ignoring case",
            "          if (name of lay as text) is blackLayoutName then",
            "            set targetLayout to lay",
            "          end if",
            "        end ignoring",
            "        if targetLayout is not missing value then exit repeat",
            "      end repeat",
            '      if targetLayout is missing value then error "resolved layout name not found in theDoc"',
        ]
        for number in keep:
            ordinal = base_ordinals[number]
            lines.append(f"      set base layout of slide {ordinal} of theDoc to targetLayout")
        lines.append("      if donorSlide is not missing value then delete donorSlide")

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
            kind, kind_index = item_id
            staged_id = _staged_id_for(number, plan, item_id, hidden=(hidden or {}).get(number, frozenset()))
            if staged_id is None:
                continue
            name = _AS_KIND_NAMES.get(kind)
            if not name:
                continue
            addr = f"{name} {staged_id[1] + 1} of slide {ordinal}"
            rect = refit.rect
            body = [
                f"          set width of theObj to {_as_num(rect.w)}",
                f"          set position of theObj to {{{_as_num(rect.x)}, {_as_num(rect.y)}}}",
            ]
            if item_id not in autosize_ids:
                body.insert(1, f"          set height of theObj to {_as_num(rect.h)}")
            if isinstance(refit.run_sizes, tuple):
                for start, end, size in refit.run_sizes:
                    body.append(
                        f"          set size of characters {start} thru {end} "
                        f"of object text of theObj to {_as_num(size)}"
                    )
            elif isinstance(refit.run_sizes, (int, float)):
                body.append(f"          set size of object text of theObj to {_as_num(refit.run_sizes)}")
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
            retained_staged_ids = _staged_retained_ids(number, plan, part=part) if number is not None else set()
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
    fw_deck: Path, out_path: Path, plan: AssemblyPlan, warnings: list[str]
) -> dict[int, dict]:
    """Move each re-inserted cropped image back to its deleted source item's z-order
    index, per slide; a slide with nothing to move is absent from the result."""
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
        deleted_not_cropped = deleted - set(crop_specs)

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
    for kind, idx in retained_ids:
        by_kind.setdefault(kind, []).append(idx)
    for kind, idxs in by_kind.items():
        by_kind[kind] = sorted(idxs)
    return by_kind


def _staged_retained_ids(number: int, plan: AssemblyPlan, *, part: int = 0) -> set[tuple[str, int]]:
    """Staged (post-delete/insert) `(kind, kindIndex)` for the items this slide keeps;
    an inserted clip becomes the last staged movie."""
    by_kind = _staged_kind_ranks(number, plan, part=part)
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


def _merge_split_part_builds(ordinal_recs: list[tuple[int, dict]], plan: AssemblyPlan, number: int) -> list[dict]:
    """Sums each part's own long-box builds; merges short-item builds, treating a key as
    "repeated" only when genuinely shared across every part (see plan D5)."""
    split_parts = plan.splits.get(number, ())
    part_fits = [p.fits for p in split_parts]
    long_builds: list[dict] = []
    short_counts: list[Counter] = []
    short_reps: dict[tuple, dict] = {}
    repeated_keys: set[tuple] = set()
    for ordinal, rec in ordinal_recs:
        part = ordinal - plan.ordinals[number]
        source_long_id = next(iter(split_parts[part].stacked_ids), None) if part < len(split_parts) else None
        long_id = _staged_id_for(number, plan, source_long_id, part=part)
        staged_idxs = _staged_kind_ranks(number, plan, part=part)
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


def _verify_builds(fw_deck: Path, out_path: Path, plan: AssemblyPlan, warnings: list[str]) -> dict:
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
            merged_builds = _merge_split_part_builds(ordinal_recs, plan, number)
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
    slide (its per-part rects live in ``plan.splits``, not ``plan.fits``; out of scope)."""
    if slide_no in plan.splits:
        return frozenset()
    return plan.stacked_ids.get(slide_no, frozenset())


def _refit_still_over_budget(
    plan: AssemblyPlan, measured: Mapping[tuple[int, str], float], keys: Iterable[tuple[int, str]]
) -> set[tuple[int, str]]:
    over: set[tuple[int, str]] = set()
    for slide_no, item_key in keys:
        item_id: ItemId = ("text", int(item_key.split(":")[1]))
        rect = plan.fits.get(slide_no, {}).get(item_id)
        measured_h = measured.get((slide_no, item_key))
        if rect is None or measured_h is None or measured_h > rect.h + 2.0:
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
) -> dict[int, dict[ItemId, TextRefit]]:
    """One refit round's writes: per box still over budget, ``r = measured_h /
    last_written_h`` multiplied into ``correction`` (persisted across rounds, clamped to
    ``[1.0, 3.0]``), re-run through ``fit_text_stack`` for the whole stack."""
    warned_gaps = warned_gaps if warned_gaps is not None else set()
    refits: dict[int, dict[ItemId, TextRefit]] = {}
    for slide_no in sorted({s for s, _k in todo}):
        stacked = plan.stacked_ids.get(slide_no, frozenset())
        items_by_id = {(it["kind"], it["kindIndex"]): it for it in slides_by_number[slide_no]["items"]}
        boxes, box_warnings = _text_boxes(list(stacked), items_by_id)
        warnings.extend(f"slide {slide_no}: {w}" for w in box_warnings)
        if len(boxes) != len(stacked):
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
                    correction[corr_key] = max(1.0, min(3.0, correction.get(corr_key, 1.0) * ratio))
                    any_new = True
                elif measured_h is None:
                    warnings.append(
                        f"slide {slide_no}: text {key[1]} measure missing this round, "
                        "no correction change"
                    )
            if corr_key in correction:
                slide_correction[box.item_id] = correction[corr_key]
        if not any_new:
            continue
        stack_band = plan.stack_bands.get(slide_no, band)
        fit = fit_text_stack(boxes, stack_band, min_text_pt, height_correction=slide_correction)
        if fit is None:
            continue
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
                        f"slide {slide_no} box {box.item_id[1]}: run ranges leave a gap and "
                        f"fit t={t:.2f} < 1.0, would overflow with un-shrunken text"
                    )
                gap_key = (slide_no, box.item_id)
                if gap_key not in warned_gaps:
                    warned_gaps.add(gap_key)
                    warnings.append(
                        f"slide {slide_no} box {box.item_id[1]}: run ranges leave a gap, "
                        "preserving source sizing"
                    )
            run_sizes = ranges if isinstance(ranges, (tuple, float)) else sizes[box.item_id]
            slide_refits[box.item_id] = TextRefit(rects[box.item_id], run_sizes)
        short_fit = plan.short_fit.get(slide_no)
        if short_fit:
            stack_top = min(rect.y for rect in rects.values())
            short_row_h = plan.short_row_h.get(slide_no, 0.0)
            short_rects = _short_row_rects(short_fit, short_row_h, stack_top)
            for iid, short_rect in short_rects.items():
                slide_refits[iid] = TextRefit(short_rect, None)
            rects = {**rects, **short_rects}
        refits[slide_no] = slide_refits
        plan.fits[slide_no].update(rects)
    return refits


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
    box on a touched slide fits its rect within +2pt."""
    eligible_keys = {
        (o["slide"], o["item"])
        for o in overflows
        if o["item"].startswith("text:")
        and o["item"][5:].isdigit()
        and ("text", int(o["item"][5:])) in _eligible_refit_items(plan, o["slide"])
    }
    if not eligible_keys:
        return
    todo = _refit_still_over_budget(plan, measured, eligible_keys)
    reopen_path = staging_path
    correction: dict[tuple[int, ItemId], float] = {}
    warned_gaps: set[tuple[int, ItemId]] = set()
    last_t: dict[int, float] = dict(plan.stack_t)

    for round_no in range(1, _MAX_REFITS + 1):
        if not todo:
            break
        refits = _build_refit_round(
            plan, slides_by_number, todo, measured, band, min_text_pt, warnings,
            correction, text_fit=text_fit, warned_gaps=warned_gaps, last_t=last_t,
        )
        if not refits:
            break
        log(f"refit round {round_no}: slides {sorted(refits)}")
        script = build_refit_script(
            plan, refits, ordinals=plan.ordinals, scratch_path=reopen_path,
            staging_path=staging_path, hidden=hidden,
        )
        proc = batch.run(_osascript_path(script, batch.work), retry_on_1712=False)
        for key in todo:
            measured.pop(key, None)
        measured.update(_parse_measure_lines(proc.stderr or ""))
        reopen_path = staging_path
        todo = _refit_still_over_budget(plan, measured, eligible_keys)

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
            t_floor = min(1.0, min_text_pt / lead_source_size) if lead_source_size > 0 else 1.0
            t_prev = last_t.get(slide_no, 1.0)
            measured_h = measured.get((slide_no, item_key))
            t_fit = t_prev * (rect.h / measured_h) if measured_h and measured_h > 0 else t_prev
            t = min(max(min(t_fit, t_prev), t_floor), t_prev)
            clamped = t == t_floor and t_floor > t_fit
            at_floor = t_floor > t_prev
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
        measured.update(_parse_measure_lines(proc.stderr or ""))
        todo = _refit_still_over_budget(plan, measured, todo)

    resolved_keys = eligible_keys - todo
    if resolved_keys:
        stale_prefixes = tuple(f"slide {s}: text {i} overflow, height " for s, i in resolved_keys)
        warnings[:] = [w for w in warnings if not w.startswith(stale_prefixes)]
    overflows[:] = [o for o in overflows if (o["slide"], o["item"]) not in eligible_keys or (o["slide"], o["item"]) in todo]


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
            fw_deck, layout_template=layout_template, black_layout_names=black_layout_names
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
    )
    for number in sorted(plan.anchors):
        log(f"slide {number}: anchor {plan.anchors[number]}")

    warnings: list[str] = list(plan.warnings)
    movie_props: dict[int, dict[str, str]] = {}
    overflows: list[dict] = []
    measured: dict[tuple[int, str], float] = {}
    elapsed_by_slide: dict[int, float] = {}
    t0 = time.monotonic()

    with LiveBatch(fw_deck, out_path.parent, rss_limit_bytes=rss_limit_bytes, log=log) as batch:
        staging_path = batch.work / f"staged-{out_path.name}"
        script = build_assembly_script(
            plan,
            scratch_path=batch.scratch,
            staging_path=staging_path,
            layout_policy=layout_policy,
            black_layout_names=black_layout_names,
            layout_template=layout_template,
            text_fit=text_fit,
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
                elif key == "MEASURE2":
                    item_key, _sep, height_s = prop_m.group(3).partition("\t")
                    height2 = float(height_s)
                    measured_h = measured.get((slide_no, item_key))
                    if measured_h is not None and abs(height2 - measured_h) > 2.0:
                        msg = (
                            f"slide {slide_no}: text {item_key} measure settled at "
                            f"{measured_h} but re-read {height2} at end of slide"
                        )
                        warnings.append(msg)
                        log(msg)
                else:
                    movie_props.setdefault(slide_no, {})[key] = prop_m.group(3)
                continue
            miss_m = _MISS_RE.match(line)
            if miss_m:
                warnings.append(f"slide {miss_m.group(1)}: write failed for {miss_m.group(2)}: {miss_m.group(3)}")

        if proc.returncode != 0:
            if last_error is not None:
                slide_no, errnum, errmsg = last_error
                raise AssemblyRefusal(f"slide {slide_no}: Keynote assembly failed (errNum {errnum}): {errmsg}")
            raise AssemblyRefusal(f"Keynote assembly AppleScript failed:\n{proc.stderr}")

        log(f"movie_props: {movie_props}")

        slides_by_number = {s["number"]: s for s in payload.get("slides") or []}
        _run_refit_and_finalize(
            plan, batch, slides_by_number,
            band=resolved_band, min_text_pt=min_text_pt, allow_split=allow_split, text_fit=text_fit,
            staging_path=staging_path, measured=measured, overflows=overflows, warnings=warnings, log=log,
            hidden={n: frozenset(ids) for n, ids in hidden_ids.items()},
        )

        if layout_policy == "import":
            verify_staged_layouts_alpha_safe(staging_path, plan)

        stroke = _restore_stroke(fw_deck, staging_path, plan, payload, stroke_min_refs, warnings, log)
        zorder = _restore_crop_zorder(fw_deck, staging_path, plan, warnings)
        builds = _verify_builds(fw_deck, staging_path, plan, warnings)

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
