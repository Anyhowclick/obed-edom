"""Offline DSK-side slide classification and CG-band fitting from the IWA graph.

Classifies each slide (empty/static/built/movie/mixed) from the offline wall
payload and ``deck_builds``, and fits item rects into a reference deck's
image/movie band for CG-style placement. Never opens Keynote.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from obed_edom.iwa_builds import _ref_id, _transition_effect_duration, deck_builds
from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.map_remap import (
    CENTRE_PANEL_RECT,
    LW_WALL_SIZE,
    Affine,
    Rect,
    is_backdrop,
    is_side_panel_item,
    is_visible,
    item_rect,
)
from obed_edom.offline_inspect import _round_pt, offline_wall_payload

ItemId = tuple[str, int]


def _filter_kept_items(
    items: Sequence[dict], wall_w: float, wall_h: float, *, include_side: bool
) -> tuple[list[dict], list[ItemId]]:
    """Shared classify_slide/fit_slide filter: drop backdrops, off-canvas items, and
    (unless ``include_side``) side-panel-only items. Returns (kept items, dropped side ids)."""
    kept: list[dict] = []
    dropped_side: list[ItemId] = []
    for item in items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        if is_backdrop(item, wall_w, wall_h):
            continue
        if not is_visible(item, wall_w, wall_h):
            continue
        if not include_side and is_side_panel_item(item, wall_w, wall_h):
            dropped_side.append(item_id)
            continue
        kept.append(item)
    return kept, dropped_side


def _group_movie_descendants(group_obj: dict, objects: dict[str, dict], _depth: int = 0) -> int:
    """Count TSD.MovieArchive descendants of a group, recursing into nested groups."""
    if _depth > 8:
        return 0
    count = 0
    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        child = objects.get(str(cid)) if cid is not None else None
        if child is None:
            continue
        pbtype = child.get("_pbtype")
        if pbtype == "TSD.MovieArchive":
            count += 1
        elif pbtype == "TSD.GroupArchive":
            count += _group_movie_descendants(child, objects, _depth + 1)
    return count


def _slide_group_movie_counts(slide_archive: dict, objects: dict[str, dict]) -> dict[int, int]:
    """``{group kindIndex: movie descendant count}`` for this slide's top-level groups."""
    counts: dict[int, int] = {}
    for rec in derive_kind_index(slide_archive, objects):
        if rec.get("kind") != "group":
            continue
        group_obj = objects.get(str(rec["id"]))
        if not group_obj:
            continue
        n = _group_movie_descendants(group_obj, objects)
        if n:
            counts[int(rec["kindIndex"])] = n
    return counts


def _deck_group_movie_counts(deck_path: str | Path, *, deck: Any = None) -> dict[int, dict[int, int]]:
    """``{1-based slide number: {group kindIndex: movie descendant count}}`` for a whole deck."""
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(deck_path)
    out: dict[int, dict[int, int]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        counts = _slide_group_movie_counts(slide_archive, objects)
        if counts:
            out[idx + 1] = counts
    return out


def _group_descendant_ids(group_obj: dict, objects: dict[str, dict], _depth: int = 0) -> set[str]:
    """All descendant object ids of a group, recursing into nested groups (any kind)."""
    if _depth > 8:
        return set()
    ids: set[str] = set()
    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        if cid is None:
            continue
        cid = str(cid)
        ids.add(cid)
        child = objects.get(cid)
        if child is not None and child.get("_pbtype") == "TSD.GroupArchive":
            ids |= _group_descendant_ids(child, objects, _depth + 1)
    return ids


def _slide_group_build_counts(slide_archive: dict, objects: dict[str, dict]) -> dict[int, int]:
    """``{group kindIndex: build count}`` for builds whose target drawable is a descendant of
    a top-level group. ``deck_builds`` (iwa_builds.py) resolves a build's drawable against
    ``derive_kind_index``, which only enumerates top-level ``drawablesZOrder`` entries -- a
    build owned by a grouped child never addresses there and is silently dropped. This mirrors
    just the drawable-resolution step of ``iwa_builds.deck_builds`` (reusing its ``_ref_id``)
    against the group descendant census instead."""
    descendants_by_group: dict[int, set[str]] = {}
    for rec in derive_kind_index(slide_archive, objects):
        if rec.get("kind") != "group":
            continue
        group_obj = objects.get(str(rec["id"]))
        if not group_obj:
            continue
        ids = _group_descendant_ids(group_obj, objects)
        if ids:
            descendants_by_group[int(rec["kindIndex"])] = ids

    if not descendants_by_group:
        return {}

    counts: dict[int, int] = {}
    for ref in slide_archive.get("builds") or []:
        bid = _ref_id(ref)
        build = objects.get(bid) if bid else None
        if build is None:
            continue
        drawable_id = _ref_id(build.get("drawable"))
        if drawable_id is None:
            continue
        for kind_index, ids in descendants_by_group.items():
            if drawable_id in ids:
                counts[kind_index] = counts.get(kind_index, 0) + 1
                break
    return counts


def _deck_group_build_counts(deck_path: str | Path, *, deck: Any = None) -> dict[int, dict[int, int]]:
    """``{1-based slide number: {group kindIndex: descendant-owned build count}}`` for a deck."""
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(deck_path)
    out: dict[int, dict[int, int]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        counts = _slide_group_build_counts(slide_archive, objects)
        if counts:
            out[idx + 1] = counts
    return out


def _slide_connection_line_builds(slide_archive: dict, objects: dict[str, dict]) -> int:
    """Count of builds whose target is a top-level ``TSD.ConnectionLineArchive`` drawable.

    ``KIND_ORDER`` (iwa_kindindex.py) has no connection-line kind, so
    ``derive_kind_index`` never addresses these drawables and ``deck_builds`` drops
    their builds outright, even though they sit directly in ``drawablesZOrder``.
    Connection lines have no side-panel geometry test available, so every build
    found here is centre content, unconditionally kept.
    """
    line_ids = {
        str(ref.get("identifier"))
        for ref in slide_archive.get("drawablesZOrder") or []
        if (objects.get(str(ref.get("identifier"))) or {}).get("_pbtype")
        == "TSD.ConnectionLineArchive"
    }
    if not line_ids:
        return 0

    count = 0
    for ref in slide_archive.get("builds") or []:
        bid = _ref_id(ref)
        build = objects.get(bid) if bid else None
        if build is None:
            continue
        drawable_id = _ref_id(build.get("drawable"))
        if drawable_id in line_ids:
            count += 1
    return count


def _deck_connection_line_builds(deck_path: str | Path, *, deck: Any = None) -> dict[int, int]:
    """``{1-based slide number: connection-line build count}`` for a whole deck."""
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(deck_path)
    out: dict[int, int] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        count = _slide_connection_line_builds(slide_archive, objects)
        if count:
            out[idx + 1] = count
    return out


@dataclass(frozen=True)
class SlideClass:
    """``connection_line_builds`` counts builds on this slide targeting a top-level
    ``TSD.ConnectionLineArchive`` drawable -- a kind ``derive_kind_index`` cannot
    address, since ``KIND_ORDER`` (iwa_kindindex.py) has no connection-line kind.
    Always centre content, unconditionally counted here. Descendant-owned group
    builds are counted in ``build_count`` via the group census instead, not here."""

    number: int
    category: str
    build_count: int
    movie_count: int
    kept: tuple[ItemId, ...]
    dropped_side: tuple[ItemId, ...]
    transition: str | None
    connection_line_builds: int = 0


def classify_slide(
    slide: dict,
    builds: dict | None,
    wall: tuple[float, float],
    *,
    include_side: bool = False,
    group_movie_counts: dict[int, int] | None = None,
    group_build_counts: dict[int, int] | None = None,
    connection_line_builds: int = 0,
) -> SlideClass:
    number = slide["number"]
    wall_w, wall_h = wall
    if slide.get("skipped"):
        return SlideClass(number, "empty", 0, 0, (), (), None, 0)

    kept_kinds, dropped_side = _filter_kept_items(
        slide.get("items") or [], wall_w, wall_h, include_side=include_side
    )
    kept: list[ItemId] = [(item["kind"], item["kindIndex"]) for item in kept_kinds]
    kept_set = set(kept)

    build_records = [
        b for b in (builds or {}).get("builds") or [] if (b["kind"], b["kindIndex"]) in kept_set
    ]
    build_count = len(build_records)
    group_build_counts = group_build_counts or {}
    build_count += sum(
        group_build_counts.get(item["kindIndex"], 0) for item in kept_kinds if item["kind"] == "group"
    )
    build_count += connection_line_builds
    transition = None
    if builds is not None:
        effect_duration = _transition_effect_duration(builds.get("transition"))
        if effect_duration is not None:
            transition = effect_duration[0]

    group_movie_counts = group_movie_counts or {}
    movie_count = 0
    for item in kept_kinds:
        if item["kind"] == "movie":
            movie_count += 1
        elif item["kind"] == "group":
            movie_count += group_movie_counts.get(item["kindIndex"], 0)

    if not kept and build_count == 0:
        category = "empty"
    elif movie_count > 0 and build_count == 0:
        category = "movie"
    elif movie_count > 0 and build_count > 0:
        category = "mixed"
    elif build_count > 0:
        category = "built"
    else:
        category = "static"

    return SlideClass(
        number,
        category,
        build_count,
        movie_count,
        tuple(kept),
        tuple(dropped_side),
        transition,
        connection_line_builds,
    )


def classify_deck(
    deck_path: str | Path, *, include_side: frozenset[int] = frozenset(), deck: Any = None
) -> list[SlideClass]:
    graph = deck if deck is not None else _load_deck(deck_path)
    payload = offline_wall_payload(deck_path, deck=graph)
    builds_by_number = deck_builds(deck_path, deck=graph)
    group_movie_by_number = _deck_group_movie_counts(deck_path, deck=graph)
    group_build_by_number = _deck_group_build_counts(deck_path, deck=graph)
    connection_line_by_number = _deck_connection_line_builds(deck_path, deck=graph)
    wall = (payload["slideWidth"], payload["slideHeight"])
    out: list[SlideClass] = []
    for slide in payload["slides"]:
        number = slide["number"]
        out.append(
            classify_slide(
                slide,
                builds_by_number.get(number),
                wall,
                include_side=number in include_side,
                group_movie_counts=group_movie_by_number.get(number),
                group_build_counts=group_build_by_number.get(number),
                connection_line_builds=connection_line_by_number.get(number, 0),
            )
        )
    return out


@dataclass(frozen=True)
class Band:
    bottom: float
    height: float
    x_min: float
    x_max: float
    sample_count: int

    @property
    def width(self) -> float:
        return self.x_max - self.x_min


class BandRefusal(ValueError):
    pass


def read_band(reference_deck_path: str | Path, *, deck: Any = None, min_h: float = 150.0) -> Band:
    graph = deck if deck is not None else _load_deck(reference_deck_path)
    payload = offline_wall_payload(reference_deck_path, deck=graph)
    ref_w, ref_h = payload["slideWidth"], payload["slideHeight"]
    candidates: list[tuple[int, int, float, float]] = []
    for slide in payload["slides"]:
        if slide.get("skipped"):
            continue
        for item in slide.get("items") or []:
            if item["kind"] not in ("image", "movie"):
                continue
            if item["h"] <= min_h:
                continue
            if is_backdrop(item, ref_w, ref_h) or not is_visible(item, ref_w, ref_h):
                continue
            bottom = _round_pt(item["y"] + item["h"])
            height = _round_pt(item["h"])
            candidates.append((bottom, height, item["x"], item["x"] + item["w"]))

    if not candidates:
        raise BandRefusal("no candidate band items")

    pair_counts = Counter((bottom, height) for bottom, height, _x0, _x1 in candidates)
    ranked = pair_counts.most_common()
    modal_pair, sample_count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == sample_count:
        raise BandRefusal(f"ambiguous modal band: tie at {sample_count} samples")
    if sample_count < 3:
        raise BandRefusal(f"only {sample_count} qualifying band items")

    modal_bottom, modal_height = modal_pair
    members = [c for c in candidates if (c[0], c[1]) == modal_pair]
    x_min = min(x0 for _b, _h, x0, _x1 in members)
    x_max = max(x1 for _b, _h, _x0, x1 in members)
    return Band(float(modal_bottom), float(modal_height), float(x_min), float(x_max), sample_count)


def fit_item(
    item_rect: Rect, band: Band, *, anchor: str = "centre", wall_rect: Rect = CENTRE_PANEL_RECT
) -> Rect:
    visible = _intersect(item_rect, wall_rect)
    if visible is None:
        return Rect(0.0, 0.0, 0.0, 0.0)
    scale = _fit_scale(visible, band)
    return _place(visible, scale, band, anchor)


def _visibles_by_kept(
    items: Sequence[dict], kept: Iterable[ItemId], *, include_side: bool
) -> dict[ItemId, Rect]:
    wall_rect = Rect(0.0, 0.0, *LW_WALL_SIZE) if include_side else CENTRE_PANEL_RECT
    kept_set = set(kept)
    visibles: dict[ItemId, Rect] = {}
    for item in items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        if item_id not in kept_set:
            continue
        visible = _intersect(item_rect(item), wall_rect)
        if visible is not None:
            visibles[item_id] = visible
    return visibles


def _visibles_by_wall(
    items: Sequence[dict], wall_w: float, wall_h: float, *, include_side: bool
) -> dict[ItemId, Rect]:
    wall_rect = Rect(0.0, 0.0, *LW_WALL_SIZE) if include_side else CENTRE_PANEL_RECT
    filtered_items, _dropped_side = _filter_kept_items(items, wall_w, wall_h, include_side=include_side)
    visibles: dict[ItemId, Rect] = {}
    for item in filtered_items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        visible = _intersect(item_rect(item), wall_rect)
        if visible is not None:
            visibles[item_id] = visible
    return visibles


def visible_union(
    items: Sequence[dict], *, include_side: bool, wall: tuple[float, float]
) -> Rect | None:
    """Wall-space union of kept visible item rects -- backdrops, off-canvas items and
    (unless ``include_side``) side-panel-only items dropped via ``_filter_kept_items`` --
    or ``None`` if nothing is kept/visible. Used by the DSK movie export's include_side
    crop rect (``dsk_movie_export.py``)."""
    visibles = _visibles_by_wall(items, wall[0], wall[1], include_side=include_side)
    if not visibles:
        return None
    return _union_rect(visibles.values())


def fit_slide(
    items: Sequence[dict],
    band: Band,
    *,
    include_side: bool = False,
    anchor: str = "centre",
    kept: Iterable[ItemId] | None = None,
    wall: tuple[float, float] | None = None,
) -> dict[ItemId, Rect]:
    """``kept`` (explicit item ids) or ``wall`` (apply the classifier's own backdrop/
    visibility/side filter via ``_filter_kept_items``) restrict which items are fit --
    exactly one of the two must be given; omitting both would fit every raw item,
    backdrops included, which is never what a caller wants."""
    if (kept is None) == (wall is None):
        raise ValueError("fit_slide requires exactly one of `kept` or `wall`")
    if kept is not None:
        visibles = _visibles_by_kept(items, kept, include_side=include_side)
    else:
        visibles = _visibles_by_wall(items, wall[0], wall[1], include_side=include_side)

    if not visibles:
        return {}

    union = _union_rect(visibles.values())
    scale = _fit_scale(union, band)
    placed_union = _place(union, scale, band, anchor)
    affine = Affine(scale, placed_union.x - union.x * scale, placed_union.y - union.y * scale)

    return {item_id: affine.apply_rect(rect) for item_id, rect in visibles.items()}


def _fit_scale(rect: Rect, band: Band) -> float:
    """Uniform scale fitting ``rect`` into ``band``. A degenerate (zero-width or
    zero-height) rect -- a line's own extent, or a line-only union -- drops the
    zero dimension's ratio rather than dividing by it; the fitted rect keeps that
    dimension at zero."""
    ratios = []
    if rect.w > 0:
        ratios.append(band.width / rect.w)
    if rect.h > 0:
        ratios.append(band.height / rect.h)
    return min(ratios) if ratios else 1.0


def _intersect(a: Rect, b: Rect) -> Rect | None:
    """``None`` only on true separation (strict ``<``): a zero-width/height rect (a
    line) that merely touches or sits within the other rect's bound on that axis
    still has a real, on-frame extent."""
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.x + a.w, b.x + b.w)
    y1 = min(a.y + a.h, b.y + b.h)
    if x1 < x0 or y1 < y0:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _union_rect(rects: Sequence[Rect]) -> Rect:
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _place(rect: Rect, scale: float, band: Band, anchor: str) -> Rect:
    w, h = rect.w * scale, rect.h * scale
    y = band.bottom - h
    if anchor == "left":
        x = band.x_min
    elif anchor == "right":
        x = band.x_max - w
    else:
        x = band.x_min + (band.width - w) / 2.0
    return Rect(x, y, w, h)
