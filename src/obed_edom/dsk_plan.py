"""Offline DSK-side slide classification and CG-band fitting from the IWA graph.

Classifies each slide (empty/static/built/movie/mixed) from the offline wall
payload and ``deck_builds``, and fits item rects into a reference deck's
image/movie band for CG-style placement. Never opens Keynote.
"""
from __future__ import annotations

import math
import os
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from obed_edom.iwa_builds import _ref_id, _transition_effect_duration, build_identity, deck_builds
from obed_edom.iwa_geometry import _frame_aabb, _frame_rect, _geom_dict, _mask_aabb, _mask_geom, _masked_rect, _xywha
from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.map_remap import (
    CENTRE_PANEL_RECT,
    LW_WALL_SIZE,
    Affine,
    Rect,
    is_backdrop,
    is_lw_wall,
    is_visible,
    item_rect,
)
from obed_edom.offline_inspect import _round_pt, offline_wall_payload

ItemId = tuple[str, int]


def _delete_order(ids: Sequence[ItemId], id_by_item: Mapping[ItemId, str] | None = None) -> tuple[ItemId, ...]:
    """Deletion order: reverse ``kindIndex`` within each ``kind`` (deleting high-to-low so
    a not-yet-deleted index never shifts). ``id_by_item`` dedupes duals -- the same
    underlying object addressed under two kinds, e.g. a text box also enumerated as its
    owning shape -- to a single address: the kind that sorts last among the kinds present,
    since deleting one kind's address also removes the object from every other kind's
    collection and would shift the indices of that other kind's still-pending addresses."""
    ordered = sorted(ids, key=lambda iid: (iid[0], -iid[1]))
    if not id_by_item:
        return tuple(ordered)
    by_obj: dict[str, list[ItemId]] = {}
    for iid in ordered:
        obj_id = id_by_item.get(iid)
        if obj_id is not None:
            by_obj.setdefault(obj_id, []).append(iid)
    drop: set[ItemId] = set()
    for dupes in by_obj.values():
        if len(dupes) < 2:
            continue
        survivor = max(dupes, key=lambda iid: iid[0])
        drop.update(iid for iid in dupes if iid != survivor)
    return tuple(iid for iid in ordered if iid not in drop)


def _content_item_aabb(item: dict) -> Rect:
    """Exact AABB of a content item's own frame. Payload ``x``/``y``/``w``/``h`` already
    follow the offline-payload contract (``iwa_geometry``: "rotated=AABB position +
    unrotated size") -- ``x``/``y`` is the rotated frame's AABB top-left and ``w``/``h``
    is its unrotated size, for both plain frames (``_frame_rect``) and masked media
    (``_masked_rect``, whose ``w``/``h`` is already the mask's own D2 rect). So a rotated
    item needs only its rotated EXTENTS derived from ``w``/``h``/``rotation``; ``x``/``y``
    stay as given -- they must never be re-rotated about the frame centre. An exact
    multiple of 90 degrees swaps/no-ops the extents rather than going through sin/cos,
    which leaves float residue (e.g. 400x1000 rotated 90 -> 1000x400.00000000000006)."""
    angle = item.get("rotation") or 0.0
    x, y, w, h = item.get("x", 0.0), item.get("y", 0.0), item.get("w", 0.0), item.get("h", 0.0)
    norm = angle % 360.0
    if norm == 0.0:
        return item_rect(item)
    if norm % 90.0 == 0.0:
        if norm % 180.0 != 0.0:
            w, h = h, w
        return Rect(x, y, w, h)
    theta = math.radians(norm)
    w, h = (
        abs(w * math.cos(theta)) + abs(h * math.sin(theta)),
        abs(w * math.sin(theta)) + abs(h * math.cos(theta)),
    )
    return Rect(x, y, w, h)


def _is_content_visible(item: dict, wall_w: float, wall_h: float) -> bool:
    """Like ``map_remap.is_visible`` but for image/movie items measures the transformed
    AABB (``_content_item_aabb``) rather than the unrotated frame, so a rotated frame
    that is wholly off-canvas but whose true extent crosses onto the wall is not dropped
    before the AABB-aware side-panel classification ever sees it."""
    if item.get("kind") not in ("image", "movie"):
        return is_visible(item, wall_w, wall_h)
    if wall_w <= 0 or wall_h <= 0:
        return True
    rect = _content_item_aabb(item)
    if rect.w <= 0 and rect.h <= 0:
        return False
    w = rect.w if rect.w > 0 else 1.0
    h = rect.h if rect.h > 0 else 1.0
    return rect.x < wall_w and rect.y < wall_h and rect.x + w > 0 and rect.y + h > 0


def _is_side_panel_item(item: dict, wall_w: float, wall_h: float) -> bool:
    """Like ``map_remap.is_side_panel_item`` but measured against the item's transformed
    AABB (``_content_item_aabb``) rather than its unrotated frame, so a rotated item that
    visually crosses into the centre panel is not dropped as side-only."""
    if not is_lw_wall(wall_w, wall_h) or not _is_content_visible(item, wall_w, wall_h):
        return False
    r = _content_item_aabb(item)
    c = CENTRE_PANEL_RECT
    overlaps_centre = r.x < c.x + c.w and r.x + r.w > c.x and r.y < c.y + c.h and r.y + r.h > c.y
    return not overlaps_centre


def is_panel_backdrop(item: dict, wall: tuple[float, float], *, include_side: bool = False) -> bool:
    """True for a textless ``shape`` filling the reference frame -- the verse-slide scrim
    (F3). See ``content-rules-plan.md`` D1 for the ``include_side`` frame rationale."""
    if (item.get("kind") or "") != "shape":
        return False
    if (item.get("text") or "").strip():
        return False
    if not is_lw_wall(*wall):
        return False
    rect = item_rect(item)
    frame = Rect(0.0, 0.0, *wall) if include_side else CENTRE_PANEL_RECT
    return rect.w >= 0.98 * frame.w and rect.h >= 0.98 * frame.h


DEFAULT_TEXT_SLIDE_WORDS = 10

# ("groupchild", group kindIndex, child kind, child kindIndex) -- a group's TEXT child,
# carried alongside plain ItemId everywhere a long/stacked/text-size/run-size id is keyed
# (Design A step 2); every ``iid[0] in ("text", "image", ...)`` filter must ignore it.
# The child kind is carried in the id (not just its per-kind kindIndex) because
# kindIndex is assigned PER KIND -- a badge ``shape`` and a verse ``text`` in the same
# group can share one kindIndex, and a 3-tuple id collided the two (D1 Codex fix round).
GroupChildId = tuple[str, int, str, int]


def _word_count(text: str | None) -> int:
    return len([w for w in (text or "").split() if w])


def _is_text_slide_kept(
    kept: Sequence[dict],
    text_slide_words: int,
    *,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
) -> tuple[bool, tuple[ItemId, ...]]:
    """``(is_text, long_text_ids)`` -- a slide is text when some kept ``text`` item's
    content has more than ``text_slide_words`` whitespace-separated words (F2/D1), OR a
    kept ``group``'s child text (``group_child_words``, the DFS join of every child's
    text) does (Design A step 1, F1) -- such a group contributes its AUTOSIZE text
    children (looked up in ``group_children``) as ``GroupChildId`` long ids (D1 Codex
    fix round 2: a fixed-frame text-bearing child never qualifies, even when its
    ``kind`` reads ``"text"``); its other children (a badge shape, or a fixed-frame
    text child) are left for the caller's short-row placement or refusal."""
    long_ids: list[ItemId] = [
        (item["kind"], item["kindIndex"])
        for item in kept
        if item.get("kind") == "text" and _word_count(item.get("text")) > text_slide_words
    ]
    group_child_words = group_child_words or {}
    group_children = group_children or {}
    for item in kept:
        if item.get("kind") != "group":
            continue
        group_ki = item["kindIndex"]
        if _word_count(group_child_words.get(group_ki)) <= text_slide_words:
            continue
        for child in group_children.get(group_ki, ()):
            if child.get("kind") == "text" and child.get("autosize"):
                long_ids.append(("groupchild", group_ki, "text", child["kindIndex"]))
    return (bool(long_ids), tuple(long_ids))


def _filter_kept_items(
    items: Sequence[dict],
    wall_w: float,
    wall_h: float,
    *,
    include_side: bool,
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> tuple[
    list[dict], list[ItemId], tuple[ItemId, ...], tuple[ItemId, ...], tuple[str, ...],
    bool, tuple[ItemId, ...], tuple[ItemId, ...],
]:
    """Shared filter dropping backdrops/off-canvas/side-panel/scrim/text-slide-media/mirror
    duplicates; ``no_dedupe``/``no_drop_panel_backdrop`` keep the mirror pair, resp. the scrim."""
    kept: list[dict] = []
    dropped_side: list[ItemId] = []
    panel_backdrops: list[dict] = []
    for item in items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        if is_backdrop(item, wall_w, wall_h):
            continue
        if not _is_content_visible(item, wall_w, wall_h):
            continue
        if not include_side and _is_side_panel_item(item, wall_w, wall_h):
            dropped_side.append(item_id)
            continue
        if not no_drop_panel_backdrop and is_panel_backdrop(item, (wall_w, wall_h), include_side=include_side):
            panel_backdrops.append(item)
            continue
        kept.append(item)
    if kept:
        dropped_backdrop = tuple((i["kind"], i["kindIndex"]) for i in panel_backdrops)
    else:
        kept.extend(panel_backdrops)
        dropped_backdrop = ()

    is_text, long_text_ids = _is_text_slide_kept(
        kept, text_slide_words, group_child_words=group_child_words, group_children=group_children
    )
    dropped_media_text: tuple[ItemId, ...] = ()
    if is_text:
        media_ids = {
            (i["kind"], i["kindIndex"]) for i in kept if i.get("kind") in ("image", "movie")
        }
        if media_ids:
            dropped_media_text = tuple(sorted(media_ids, key=lambda iid: (iid[0], iid[1])))
            kept = [item for item in kept if (item["kind"], item["kindIndex"]) not in media_ids]

    dropped_duplicate: tuple[ItemId, ...] = ()
    mirror_warnings: tuple[str, ...] = ()
    if not no_dedupe:
        duplicate_map, mirror_warnings = mirror_duplicates(
            kept, (wall_w, wall_h), group_child_text=group_child_text
        )
        dropped_duplicate = tuple(duplicate_map)
        if dropped_duplicate:
            dup_set = set(dropped_duplicate)
            dup_group_kis = {iid[1] for iid in dup_set if iid[0] == "group"}
            kept = [item for item in kept if (item["kind"], item["kindIndex"]) not in dup_set]
            long_text_ids = tuple(
                iid for iid in long_text_ids
                if iid not in dup_set
                and not (iid[0] == "groupchild" and iid[1] in dup_group_kis)
            )

    return (
        kept, dropped_side, dropped_backdrop, dropped_duplicate, mirror_warnings,
        is_text, long_text_ids, dropped_media_text,
    )


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
    dropped_backdrop: tuple[ItemId, ...]
    transition: str | None
    connection_line_builds: int = 0
    dropped_duplicate: tuple[ItemId, ...] = ()
    mirror_warnings: tuple[str, ...] = ()
    is_text: bool = False
    long_text_ids: tuple[ItemId, ...] = ()
    dropped_media_text: tuple[ItemId, ...] = ()


def classify_slide(
    slide: dict,
    builds: dict | None,
    wall: tuple[float, float],
    *,
    include_side: bool = False,
    group_movie_counts: dict[int, int] | None = None,
    group_build_counts: dict[int, int] | None = None,
    connection_line_builds: int = 0,
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> SlideClass:
    number = slide["number"]
    wall_w, wall_h = wall
    if slide.get("skipped"):
        return SlideClass(number, "empty", 0, 0, (), (), (), None, 0, (), ())

    (
        kept_kinds, dropped_side, dropped_backdrop, dropped_duplicate, mirror_warnings,
        is_text, long_text_ids, dropped_media_text,
    ) = _filter_kept_items(
        slide.get("items") or [], wall_w, wall_h, include_side=include_side,
        group_child_text=group_child_text, group_child_words=group_child_words,
        group_children=group_children, text_slide_words=text_slide_words,
        no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
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
        dropped_backdrop,
        transition,
        connection_line_builds,
        dropped_duplicate,
        mirror_warnings,
        is_text=is_text,
        long_text_ids=long_text_ids,
        dropped_media_text=dropped_media_text,
    )


def classify_deck(
    deck_path: str | Path,
    *,
    include_side: frozenset[int] = frozenset(),
    deck: Any = None,
    payload: dict | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> list[SlideClass]:
    """Classify every slide in ``payload`` (built from ``deck_path``/``deck`` if omitted)."""
    from obed_edom.iwa_runs import (  # noqa: PLC0415
        attach_group_children,
        attach_group_child_text,
        attach_group_content_signature,
    )

    graph = deck if deck is not None else _load_deck(deck_path)
    if payload is None:
        payload = offline_wall_payload(deck_path, deck=graph)
        attach_group_content_signature(deck_path, payload, deck=graph)
        attach_group_child_text(deck_path, payload, deck=graph)
        attach_group_children(deck_path, payload, deck=graph)
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
                group_child_text=slide.get("groupChildSignature"),
                group_child_words=slide.get("groupChildText"),
                group_children=slide.get("groupChildren"),
                text_slide_words=text_slide_words,
                no_dedupe=no_dedupe,
                no_drop_panel_backdrop=no_drop_panel_backdrop,
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


_MIRROR_SIZE_TOLERANCE_PT = 1.0
_MIRROR_GEOM_X_TOLERANCE_PT = 6.0
_MIRROR_GEOM_Y_TOLERANCE_PT = 2.0
_MIRROR_GEOM_SIZE_TOLERANCE_PT = 2.0


def mirror_duplicates(
    items: Sequence[dict],
    wall: tuple[float, float],
    *,
    group_child_text: Mapping[int, str | None] | None = None,
) -> tuple[dict[ItemId, ItemId], tuple[str, ...]]:
    """``({dropped ItemId: kept ItemId}, warnings)`` for L/R mirror duplicates (F2), keyed
    by content then, for keyless items, by the slide's own L/R translation (D1)."""
    wall_w = wall[0]
    mid = wall_w / 2.0
    no_map = group_child_text is None
    group_child_text = group_child_text or {}
    groups: dict[tuple[Any, ...], list[dict]] = {}
    keyless: list[dict] = []
    warnings: list[str] = []
    for item in items:
        kind = item.get("kind") or ""
        if kind in ("text", "shape"):
            if not (item.get("text") or "").strip():
                keyless.append(item)
                continue
            key = build_identity(kind, item.get("text"), None, None)
        elif kind in ("image", "movie"):
            file_name = item.get("fileName") or ""
            if not file_name:
                continue
            key = build_identity(kind, None, file_name, None)
        elif kind == "group":
            kind_index = item.get("kindIndex")
            if kind_index not in group_child_text:
                if not no_map:
                    warnings.append(f"group {kind_index} missing content signature; keeping")
                continue
            child_sig = group_child_text[kind_index]
            if child_sig is None:
                warnings.append(f"group {kind_index} content signature unresolved; keeping")
                continue
            if not child_sig:
                continue
            key = build_identity(kind, None, None, child_sig)
        else:
            continue
        groups.setdefault(key, []).append(item)

    valid_pairs: list[tuple[ItemId, ItemId, float, float]] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        ids = [(m["kind"], m["kindIndex"]) for m in members]
        if len(members) != 2:
            warnings.append(f"{len(members)} items share content key {key!r}: {ids}; keeping all")
            continue
        a, b = members
        rect_a, rect_b = item_rect(a), item_rect(b)
        cx_a = rect_a.x + rect_a.w / 2.0 - mid
        cx_b = rect_b.x + rect_b.w / 2.0 - mid
        opposite_sides = cx_a * cx_b < 0
        sizes_agree = True
        if a["kind"] in ("image", "movie"):
            sizes_agree = (
                abs(rect_a.w - rect_b.w) <= _MIRROR_SIZE_TOLERANCE_PT
                and abs(rect_a.h - rect_b.h) <= _MIRROR_SIZE_TOLERANCE_PT
            )
        if not opposite_sides or not sizes_agree:
            warnings.append(f"identical-content pair {ids} is not a L/R mirror; keeping all")
            continue
        id_a, id_b = ids
        valid_pairs.append((id_a, id_b, cx_a, cx_b))

    if not valid_pairs:
        return {}, tuple(warnings)

    def _pair_low_kind_index_side(id_a: ItemId, id_b: ItemId, cx_a: float, cx_b: float) -> str:
        low_cx = cx_a if id_a[1] < id_b[1] else cx_b
        return "right" if low_cx > 0 else "left"

    side_votes = Counter(_pair_low_kind_index_side(*p) for p in valid_pairs)
    global_side: str | None
    if len(side_votes) == 1:
        global_side = next(iter(side_votes))
        if len(valid_pairs) == 1:
            warnings.append(f"mirror-pair survivor side chosen by a single vote: {global_side!r}")
    else:
        ranked = side_votes.most_common()
        if ranked[0][1] > ranked[1][1]:
            global_side = ranked[0][0]
            if ranked[0][1] - ranked[1][1] == 1:
                warnings.append(
                    f"mirror-pair survivor side chosen by a margin of 1 ({dict(side_votes)}): {global_side!r}"
                )
        else:
            global_side = None
            warnings.append(
                f"mirror-pair survivor sides disagree with no majority ({dict(side_votes)}); "
                "falling back to per-pair lowest kindIndex"
            )

    dropped: dict[ItemId, ItemId] = {}
    offsets: list[float] = []
    for id_a, id_b, cx_a, cx_b in valid_pairs:
        if global_side is not None:
            side_a = "right" if cx_a > 0 else "left"
            survivor, dupe = (id_a, id_b) if side_a == global_side else (id_b, id_a)
            survivor_cx, dupe_cx = (cx_a, cx_b) if survivor == id_a else (cx_b, cx_a)
        else:
            survivor, dupe = (id_a, id_b) if id_a[1] < id_b[1] else (id_b, id_a)
            survivor_cx, dupe_cx = (cx_a, cx_b) if survivor == id_a else (cx_b, cx_a)
        dropped[dupe] = survivor
        offsets.append(dupe_cx - survivor_cx)

    if keyless and offsets:
        off = Counter(round(o) for o in offsets).most_common(1)[0][0]
        used: set[int] = set()
        for i, a in enumerate(keyless):
            if i in used:
                continue
            id_a = (a["kind"], a["kindIndex"])
            rect_a = item_rect(a)
            for j in range(i + 1, len(keyless)):
                if j in used:
                    continue
                b = keyless[j]
                if b.get("kind") != a.get("kind"):
                    continue
                rect_b = item_rect(b)
                cx_a = rect_a.x + rect_a.w / 2.0 - mid
                cx_b = rect_b.x + rect_b.w / 2.0 - mid
                if cx_a * cx_b >= 0:
                    continue
                if abs(abs(cx_b - cx_a) - abs(off)) > _MIRROR_GEOM_X_TOLERANCE_PT:
                    continue
                if abs(rect_b.y - rect_a.y) > _MIRROR_GEOM_Y_TOLERANCE_PT:
                    continue
                if abs(rect_b.w - rect_a.w) > _MIRROR_GEOM_SIZE_TOLERANCE_PT:
                    continue
                if abs(rect_b.h - rect_a.h) > _MIRROR_GEOM_SIZE_TOLERANCE_PT:
                    continue
                id_b = (b["kind"], b["kindIndex"])
                if global_side is not None:
                    side_a = "right" if cx_a > 0 else "left"
                    survivor, dupe = (id_a, id_b) if side_a == global_side else (id_b, id_a)
                else:
                    survivor, dupe = (id_a, id_b) if id_a[1] < id_b[1] else (id_b, id_a)
                dropped[dupe] = survivor
                used.add(i)
                used.add(j)
                break

    return dropped, tuple(warnings)


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
    items: Sequence[dict],
    wall_w: float,
    wall_h: float,
    *,
    include_side: bool,
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> dict[ItemId, Rect]:
    wall_rect = Rect(0.0, 0.0, *LW_WALL_SIZE) if include_side else CENTRE_PANEL_RECT
    filtered_items = _filter_kept_items(
        items, wall_w, wall_h, include_side=include_side, group_child_text=group_child_text,
        group_child_words=group_child_words, group_children=group_children,
        text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )[0]
    visibles: dict[ItemId, Rect] = {}
    for item in filtered_items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        visible = _intersect(item_rect(item), wall_rect)
        if visible is not None:
            visibles[item_id] = visible
    return visibles


def visible_union(
    items: Sequence[dict],
    *,
    include_side: bool,
    wall: tuple[float, float],
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> Rect | None:
    """Wall-space union of kept visible item rects (per ``_filter_kept_items``), or ``None``
    if nothing is kept/visible. Used by the DSK movie export's include_side crop rect."""
    visibles = _visibles_by_wall(
        items, wall[0], wall[1], include_side=include_side, group_child_text=group_child_text,
        group_child_words=group_child_words, group_children=group_children,
        text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
    )
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
    group_child_text: Mapping[int, str | None] | None = None,
    group_child_words: Mapping[int, str | None] | None = None,
    group_children: Mapping[int, Sequence[dict]] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
    no_dedupe: bool = False,
    no_drop_panel_backdrop: bool = False,
) -> dict[ItemId, Rect]:
    """``kept`` (explicit item ids) or ``wall`` (apply ``_filter_kept_items``) restrict which
    items are fit -- exactly one of the two must be given."""
    if (kept is None) == (wall is None):
        raise ValueError("fit_slide requires exactly one of `kept` or `wall`")
    if kept is not None:
        visibles = _visibles_by_kept(items, kept, include_side=include_side)
    else:
        visibles = _visibles_by_wall(
            items, wall[0], wall[1], include_side=include_side, group_child_text=group_child_text,
            group_child_words=group_child_words, group_children=group_children,
            text_slide_words=text_slide_words, no_dedupe=no_dedupe, no_drop_panel_backdrop=no_drop_panel_backdrop,
        )

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


_FONT_DIRS: tuple[Path, ...] = (
    Path.home() / "Library" / "Fonts",
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
)
_FONT_INDEX_CACHE: dict[str, Path] | None = None
_TEXT_GAP_PT = 10.0
_WRAP_OVERSAMPLE = 8
_LINE_HEIGHT_FACTOR = 1.157
_BOX_PADDING_PT = 21.0
_TEXT_SAFETY_PT = 15.0
_WRAP_MARGIN = 0.02


def _norm_font_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _build_font_index() -> dict[str, Path]:
    from PIL import ImageFont  # noqa: PLC0415

    index: dict[str, Path] = {}
    stem_index: dict[str, Path] = {}
    for directory in _FONT_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in (".otf", ".ttf", ".ttc"):
                continue
            stem = path.stem
            stem_candidates = {stem}
            if " - " in stem:
                stem_candidates.add(stem.split(" - ")[-1])
            for candidate in stem_candidates:
                stem_index.setdefault(_norm_font_key(candidate), path)
            try:
                family, style = ImageFont.truetype(str(path)).getname()
            except Exception:  # noqa: BLE001
                continue
            name_candidates = {family, f"{family} {style}".strip()}
            for candidate in name_candidates:
                index.setdefault(_norm_font_key(candidate), path)
    for key, path in stem_index.items():
        index.setdefault(key, path)
    return index


def resolve_font_path(font_name: str) -> Path | None:
    """Resolve a PostScript font name to a file under ``_FONT_DIRS``, matched by each file's
    own ``ImageFont.getname()`` first, filename stem second. Cached across calls."""
    global _FONT_INDEX_CACHE
    if _FONT_INDEX_CACHE is None:
        _FONT_INDEX_CACHE = _build_font_index()
    if not font_name:
        return None
    return _FONT_INDEX_CACHE.get(_norm_font_key(font_name))


_WRAP_BREAK_CHARS = (" ", " ")  # ASCII space and thin space (F9/D4)


_PARA_BREAK_CHARS = ("\n", "\r", " ", " ")


def _wrap_lines(text: str, font: Any, max_width: float) -> list[str]:
    """Greedy word wrap honouring ``\\n``/``\\r``/``\\u2028``/``\\u2029`` as hard breaks; ``\\xa0``
    is non-breaking (F9/D4)."""
    import re as _re  # noqa: PLC0415

    pattern = "[" + "".join(_WRAP_BREAK_CHARS) + "]"
    para_pattern = "\r\n|[" + "".join(_PARA_BREAK_CHARS) + "]"
    tok_re = _re.compile(f"({pattern})")
    lines: list[str] = []
    for paragraph in _re.split(para_pattern, text or ""):
        if paragraph == "":
            lines.append("")
            continue
        parts = tok_re.split(paragraph)
        words = parts[0::2]
        seps = parts[1::2]
        current = ""
        for i, word in enumerate(words):
            sep = seps[i - 1] if i > 0 else ""
            trial = word if not current else f"{current}{sep}{word}"
            if not current or font.getlength(trial) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def line_count(text: str, font_name: str, size: float, width: float) -> int | None:
    """Wrapped line count of ``text`` at ``size`` wrapped to ``width`` (F9), same wrap
    pass as ``wrapped_height``. ``None`` when the font cannot be resolved."""
    path = resolve_font_path(font_name)
    if path is None or size <= 0:
        return None
    from PIL import ImageFont  # noqa: PLC0415

    font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
    lines = _wrap_lines(text, font, width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE)
    return len(lines)


def wrap_line_spans(text: str, font_name: str, size: float, width: float) -> list[tuple[int, int]] | None:
    """``[start, end)`` character span of each wrapped line at ``size`` wrapped to
    ``width`` (F9/owner Q2), same wrap pass as ``line_count``/``wrapped_height`` -- a
    span excludes the wrap-point separator trailing its line, so a caller splitting
    ``text`` at line boundaries can join consecutive spans back into one contiguous
    slice. ``None`` when the font cannot be resolved."""
    path = resolve_font_path(font_name)
    if path is None or size <= 0:
        return None
    from PIL import ImageFont  # noqa: PLC0415

    font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
    lines = _wrap_lines(text, font, width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE)
    spans: list[tuple[int, int]] = []
    cursor = 0
    for line in lines:
        if line == "":
            spans.append((cursor, cursor))
            continue
        idx = text.index(line, cursor)
        spans.append((idx, idx + len(line)))
        cursor = idx + len(line)
    return spans


def wrapped_height(text: str, font_name: str, size: float, width: float) -> float | None:
    """Estimated laid-out height (pt) of ``text`` at ``size`` wrapped to ``width`` (F9).
    ``None`` when the font cannot be resolved -- callers must warn and fall back."""
    path = resolve_font_path(font_name)
    if path is None or size <= 0:
        return None
    from PIL import ImageFont  # noqa: PLC0415

    font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
    lines = _wrap_lines(text, font, width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE)
    return len(lines) * _LINE_HEIGHT_FACTOR * size + _BOX_PADDING_PT


def longest_line_width(text: str, font_name: str, size: float, width: float) -> float | None:
    """Rendered width (pt) of the longest line of ``text`` at ``size`` after wrapping to ``width``
    (F9), mirroring ``wrapped_height``'s wrap pass. ``None`` when the font cannot be resolved."""
    path = resolve_font_path(font_name)
    if path is None or size <= 0:
        return None
    from PIL import ImageFont  # noqa: PLC0415

    font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
    lines = _wrap_lines(text, font, width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE)
    if not lines:
        return 0.0
    return max(font.getlength(line) for line in lines) / _WRAP_OVERSAMPLE


def fit_heading_pt(
    text: str,
    font_name: str,
    col_width: float,
    budget: float,
    *,
    max_pt: float,
    max_block_pt: float,
    min_pt: float,
) -> float | None:
    """Largest integer point size in ``[min_pt, max_pt]`` fitting ``text`` inside ``col_width`` with
    its per-block line-height sum within ``max_block_pt`` and its wrapped height within ``budget``.
    ``None`` when no size fits or the font is unresolved."""
    for s in range(math.floor(max_pt), math.ceil(min_pt) - 1, -1):
        width = longest_line_width(text, font_name, s, col_width)
        height = wrapped_height(text, font_name, s, col_width)
        if width is None or height is None:
            return None
        if width > col_width:
            continue
        if height - _BOX_PADDING_PT > max_block_pt:
            continue
        if height > budget:
            continue
        return float(s)
    return None


@dataclass(frozen=True)
class Run:
    text: str
    font_name: str
    size: float


def wrapped_height_runs(runs: Sequence[Run], width: float) -> float | None:
    """Run-aware sibling of ``wrapped_height``: wraps across each run's own
    resolved font at its own size, charging every wrapped line's height by the
    tallest run on that line. Preserves each run's actual separator characters --
    a run boundary with no break char between it and its neighbour is one word,
    never a synthetic space. ``None`` when a run's font cannot be resolved."""
    import re as _re  # noqa: PLC0415
    from PIL import ImageFont  # noqa: PLC0415

    fonts: dict[tuple[str, float], Any] = {}

    def _font_for(name: str, size: float) -> Any | None:
        key = (name, size)
        font = fonts.get(key)
        if font is None:
            path = resolve_font_path(name)
            if path is None:
                return None
            font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
            fonts[key] = font
        return font

    break_pattern = "[" + "".join(_WRAP_BREAK_CHARS) + "]"
    para_pattern = "\r\n|[" + "".join(_PARA_BREAK_CHARS) + "]"
    tok_re = _re.compile(f"({break_pattern})")

    # Each paragraph is a list of ("word", [(text, font, size), ...]) or ("sep", text, font, size)
    # tokens, in source order; a "word" token spans run boundaries when no separator falls between.
    paragraphs: list[list[tuple]] = [[]]
    last_size = 0.0
    for run in runs:
        font = _font_for(run.font_name, run.size)
        if font is None:
            return None
        last_size = run.size
        pieces = _re.split(para_pattern, run.text or "")
        for i, piece in enumerate(pieces):
            if i > 0:
                paragraphs.append([])
            if piece == "":
                continue
            para = paragraphs[-1]
            for part in tok_re.split(piece):
                if part == "":
                    continue
                if tok_re.fullmatch(part):
                    para.append(("sep", part, font, run.size))
                elif para and para[-1][0] == "word":
                    para[-1][1].append((part, font, run.size))
                else:
                    para.append(("word", [(part, font, run.size)]))

    scaled_width = width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE
    lines: list[list[list[tuple[str, Any, float]]]] = []
    for paragraph in paragraphs:
        if not paragraph:
            lines.append([])
            continue
        current: list[list[tuple[str, Any, float]]] = []
        current_width = 0.0
        pending_seps: list[tuple[str, Any, float]] = []
        for tok in paragraph:
            if tok[0] == "sep":
                pending_seps.append((tok[1], tok[2], tok[3]))
                continue
            subparts = tok[1]
            word_width = sum(f.getlength(t) for t, f, _s in subparts)
            space_width = 0.0
            if current and pending_seps:
                space_width = sum(sep_font.getlength(sep_text) for sep_text, sep_font, _sep_size in pending_seps)
            trial_width = current_width + space_width + word_width
            if not current or trial_width <= scaled_width:
                current.append(subparts)
                current_width = trial_width
            else:
                lines.append(current)
                current = [subparts]
                current_width = word_width
            pending_seps = []
        lines.append(current)

    total = 0.0
    for line in lines:
        sizes_in_line = [s for subparts in line for _t, _f, s in subparts]
        max_size = max(sizes_in_line, default=last_size)
        total += _LINE_HEIGHT_FACTOR * max_size
    return total + _BOX_PADDING_PT


def wrap_line_spans_runs(
    text: str, runs: Sequence[Run], lead_font: str, lead_pt: float, width: float
) -> list[tuple[int, int]] | None:
    """Run-aware sibling of ``wrap_line_spans``: ``[start, end)`` character spans over
    ``text`` (== the concatenation of ``runs``' own text), wrapped at each run's own
    resolved font/size -- the EXACT sizes the emitter writes (S1/owner Q2), sharing
    ``wrapped_height_runs``'s tokeniser and run-boundary word handling verbatim (a run
    boundary with no break char between it and its neighbour is one word, never a
    synthetic space). A run with no ``font_name`` inherits ``lead_font``. ``None`` when a
    run's font cannot be resolved. Empty ``runs`` wraps ``text`` at ``lead_font``/
    ``lead_pt`` via ``wrap_line_spans``."""
    if not runs:
        return wrap_line_spans(text, lead_font, lead_pt, width)
    import re as _re  # noqa: PLC0415
    from PIL import ImageFont  # noqa: PLC0415

    fonts: dict[tuple[str, float], Any] = {}

    def _font_for(name: str, size: float) -> Any | None:
        key = (name, size)
        font = fonts.get(key)
        if font is None:
            path = resolve_font_path(name)
            if path is None:
                return None
            font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
            fonts[key] = font
        return font

    break_pattern = "[" + "".join(_WRAP_BREAK_CHARS) + "]"
    para_pattern = "\r\n|[" + "".join(_PARA_BREAK_CHARS) + "]"
    tok_re = _re.compile(f"({break_pattern})")

    # Each paragraph is a list of ("word", [(text, offset, font, size), ...]) or
    # ("sep", text, font, size, offset) tokens in source order, offsets against ``text``.
    paragraphs: list[list[tuple]] = [[]]
    pos = 0
    for run in runs:
        name = run.font_name or lead_font
        font = _font_for(name, run.size)
        if font is None:
            return None
        run_text = run.text or ""
        last = 0
        for m in _re.finditer(para_pattern, run_text):
            _wrap_span_emit(paragraphs[-1], run_text[last:m.start()], pos + last, font, run.size, tok_re)
            paragraphs.append([])
            last = m.end()
        _wrap_span_emit(paragraphs[-1], run_text[last:], pos + last, font, run.size, tok_re)
        pos += len(run_text)

    scaled_width = width * (1.0 - _WRAP_MARGIN) * _WRAP_OVERSAMPLE
    out: list[tuple[int, int]] = []
    for paragraph in paragraphs:
        current: list[list[tuple[str, int, Any, float]]] = []
        current_width = 0.0
        pending_seps: list[tuple[str, int, Any, float]] = []
        for tok in paragraph:
            if tok[0] == "sep":
                pending_seps.append((tok[1], tok[2], tok[3], tok[4]))
                continue
            subparts = tok[1]
            word_width = sum(f.getlength(t) for t, _o, f, _s in subparts)
            space_width = 0.0
            if current and pending_seps:
                space_width = sum(f.getlength(t) for t, _o, f, _s in pending_seps)
            trial_width = current_width + space_width + word_width
            if not current or trial_width <= scaled_width:
                current.append(subparts)
                current_width = trial_width
            else:
                out.append(_wrap_span_of(current))
                current = [subparts]
                current_width = word_width
            pending_seps = []
        # A trailing separator at the very end of the paragraph (no following word --
        # end of text, or immediately before a hard paragraph break) has nowhere to
        # attach as a mid-line space, so it stays glued to this last line rather than
        # being silently dropped (parity with `wrap_line_spans`, whose `_wrap_lines`
        # keeps it via the paragraph split's trailing empty token).
        if pending_seps and current:
            current.append(list(pending_seps))
        out.append(_wrap_span_of(current))
    return out


def _wrap_span_emit(para: list, piece: str, base: int, font: Any, size: float, tok_re: Any) -> None:
    if piece == "":
        return
    off = base
    for part in tok_re.split(piece):
        if part == "":
            continue
        if tok_re.fullmatch(part):
            para.append(("sep", part, off, font, size))
        elif para and para[-1][0] == "word":
            para[-1][1].append((part, off, font, size))
        else:
            para.append(("word", [(part, off, font, size)]))
        off += len(part)


def _wrap_span_of(current: list[list[tuple[str, int, Any, float]]]) -> tuple[int, int]:
    subs = [s for subparts in current for s in subparts]
    if not subs:
        return (0, 0)
    start = subs[0][1]
    end = subs[-1][1] + len(subs[-1][0])
    return (start, end)


@dataclass(frozen=True)
class TextBox:
    item_id: ItemId
    text: str
    font_name: str
    size: float
    runs: tuple[Run, ...] | None = None


def _box_min_t(box: TextBox, min_text_pt: float) -> float:
    """Minimum ``t`` keeping every run at or above ``min_text_pt``; a run already below
    the floor at its source size imposes no constraint (never enlarged, floored at
    source) rather than blocking the whole box from shrinking further."""
    run_sizes = [r.size for r in box.runs] if box.runs else [box.size]
    if min_text_pt <= 0:
        return 0.0
    candidates = [min_text_pt / s if s >= min_text_pt else 1.0 for s in run_sizes]
    return max(candidates) if candidates else 0.0


def fit_text_stack(
    boxes: Sequence[TextBox],
    band: Band,
    min_text_pt: float,
    *,
    gap: float = _TEXT_GAP_PT,
    height_correction: Mapping[ItemId, float] | None = None,
) -> tuple[float, dict[ItemId, float], dict[ItemId, float]] | None:
    """Largest ``t`` in ``(0, 1]`` fitting ``boxes`` stacked with ``gap`` into ``band``, or
    ``None``. Uses ``wrapped_height_runs`` when a box carries ``runs``, else the single-font
    ``wrapped_height``; either way ``height_correction`` (a per-box multiplier from a live
    ``MEASURE`` round) scales the estimate before the fit check. A fixed safety
    term against the estimator's own measured under-prediction is charged for every box
    count; the live ``OVERFLOW`` read-back is the final authority on wrap."""
    if not boxes:
        return None
    height_correction = height_correction or {}
    floor_t = {box.item_id: _box_min_t(box, min_text_pt) for box in boxes}
    t = 1.00
    while t > 0.0:
        if any(t < floor_t[box.item_id] for box in boxes):
            return None
        sizes = {box.item_id: box.size * t for box in boxes}
        heights: dict[ItemId, float] = {}
        for box in boxes:
            if box.runs:
                scaled_runs = tuple(Run(r.text, r.font_name, r.size * t) for r in box.runs)
                h = wrapped_height_runs(scaled_runs, band.width)
            else:
                h = wrapped_height(box.text, box.font_name, sizes[box.item_id], band.width)
            if h is None:
                return None
            h *= height_correction.get(box.item_id, 1.0)
            heights[box.item_id] = h
        total = sum(heights.values()) + gap * (len(boxes) - 1) + _TEXT_SAFETY_PT
        if total <= band.height:
            return t, sizes, heights
        t = round(t - 0.01, 2)
    return None


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


MIN_CROP_PX = 8.0


class CropRefusal(ValueError):
    """Hard refusal (min window, duplicate name) that aborts the whole slide."""


class CropFallback(CropRefusal):
    """Per-item fallback signal, caught by ``plan_crops`` and turned into an LWCROP warning."""


@dataclass(frozen=True)
class CropSpec:
    """One image replaced by a cropped file (D2, Q1). ``path``'s basename is
    ``source_file_name`` verbatim, matching Keynote's own re-import."""

    path: Path
    source_file_name: str
    px_box: tuple[int, int, int, int]
    visible: Rect


def _rects_close(a: Rect, b: Rect, tol: float = 0.5) -> bool:
    return (
        abs(a.x - b.x) <= tol and abs(a.y - b.y) <= tol
        and abs(a.w - b.w) <= tol and abs(a.h - b.h) <= tol
    )


def _asset_natural_size(obj: dict) -> tuple[float, float]:
    """``naturalSize`` (media pixel size) lives directly on an image/movie archive,
    not under ``super.pathsource`` like ``iwa_geometry._natural_size`` expects for shapes."""
    natural = obj.get("naturalSize") or {}
    return (natural.get("width") or 0.0, natural.get("height") or 0.0)


def crop_geometry(
    obj: dict, objects: dict[str, dict], window: Rect
) -> tuple[Rect, Rect, tuple[int, int, int, int]] | None:
    """``(content_abs, visible, px_box)`` for an image/movie ``obj`` clipped to
    ``window``, or ``None`` when nothing is visible; raises ``CropFallback`` otherwise."""
    mask_ref = (obj.get("mask") or {}).get("identifier")
    if mask_ref is not None and objects.get(str(mask_ref)) is None:
        raise CropFallback("referenced mask not found")
    geom = _geom_dict(obj)
    mask_geom = _mask_geom(obj, objects)
    frame_angle = _xywha(geom)[4]
    frame_rotated = abs((frame_angle % 360.0 + 180.0) % 360.0 - 180.0) > 0.01
    frame_abs = Rect(*_frame_aabb(geom))
    if mask_geom:
        masked_rect, mask_rotated = _masked_rect(geom, mask_geom)
        rotated = frame_rotated or mask_rotated
        mask_abs = Rect(*_mask_aabb(geom, mask_geom)) if rotated else Rect(*masked_rect)
    else:
        mask_abs = frame_abs
        rotated = frame_rotated
    content_abs = _intersect(mask_abs, frame_abs)
    if content_abs is None:
        return None
    visible = _intersect(content_abs, window)
    if visible is None:
        return None
    if rotated:
        if _rects_close(visible, content_abs):
            return None
        raise CropFallback("rotated-masked geometry" if mask_geom else "rotated frame")
    frame = Rect(*_frame_rect(geom))
    natural = _asset_natural_size(obj)
    if frame.w <= 0 or frame.h <= 0 or natural[0] <= 0 or natural[1] <= 0:
        if _rects_close(visible, content_abs):
            return None
        raise CropFallback("invalid frame or naturalSize geometry")
    sx, sy = natural[0] / frame.w, natural[1] / frame.h
    x0, y0 = (visible.x - frame.x) * sx, (visible.y - frame.y) * sy
    x1, y1 = x0 + visible.w * sx, y0 + visible.h * sy
    px_box = (
        max(0, int(math.floor(x0))),
        max(0, int(math.floor(y0))),
        min(int(round(natural[0])), int(math.ceil(x1))),
        min(int(round(natural[1])), int(math.ceil(y1))),
    )
    return content_abs, visible, px_box


def _item_object_ids(slide_archive: dict, objects: dict[str, dict]) -> dict[ItemId, str]:
    """``(kind, kindIndex) -> object id`` for one slide, addressed the same way
    ``offline_wall_payload`` addresses its items."""
    from obed_edom.iwa_geometry import compose_geometry  # noqa: PLC0415

    return {(rec["kind"], rec["kindIndex"]): rec["id"] for rec in compose_geometry(slide_archive, objects)}


def plan_crops(
    key_path: str | Path,
    slide_archive: dict,
    objects: dict[str, dict],
    items: Sequence[dict],
    kept: Iterable[ItemId],
    *,
    include_side: bool = False,
    crop_dir: str | Path,
    number: int,
    build_targets: Iterable[ItemId] = (),
    dry_run: bool = False,
) -> tuple[dict[ItemId, CropSpec], list[str], tuple[tuple[Path, Path], ...]]:
    """Offline per-slide crop planning; returns pending ``(temp_path, final_path)``
    writes under ``crop_dir`` for the caller to commit once every slide validates."""
    from obed_edom.offline_inspect import _data_identifier, data_member_index  # noqa: PLC0415

    crops: dict[ItemId, CropSpec] = {}
    warnings: list[str] = []
    window = Rect(0.0, 0.0, *LW_WALL_SIZE) if include_side else CENTRE_PANEL_RECT
    items_by_id = {(it["kind"], it["kindIndex"]): it for it in items}
    build_target_set = set(build_targets)
    id_by_item = _item_object_ids(slide_archive, objects)

    image_ids = sorted(iid for iid in kept if iid[0] == "image")
    if not image_ids:
        return crops, warnings, ()

    used_names: set[str] = set()
    kept_uncropped_names: set[str] = set()
    pending_writes: list[tuple[Path, Path]] = []

    def _mark_kept(it: dict) -> None:
        name = it.get("fileName")
        if name:
            kept_uncropped_names.add(name)

    def _cleanup() -> None:
        for temp_path, _out_path in pending_writes:
            temp_path.unlink(missing_ok=True)
        for temp_path, _out_path in pending_writes:
            try:
                temp_path.parent.rmdir()
            except OSError:
                pass

    with zipfile.ZipFile(key_path) as zf:
        data_index = data_member_index(zf.namelist())
        for item_id in image_ids:
            item = items_by_id.get(item_id)
            obj_id = id_by_item.get(item_id)
            if item is None or obj_id is None:
                continue
            obj = objects.get(obj_id)
            if obj is None:
                continue
            if item_id in build_target_set:
                warnings.append(f"image {item_id[1]}: a build targets this image, keeping source (LWCROP)")
                _mark_kept(item)
                continue
            try:
                result = crop_geometry(obj, objects, window)
            except CropFallback as exc:
                warnings.append(f"image {item_id[1]}: {exc}, keeping source (LWCROP)")
                _mark_kept(item)
                continue
            if result is None:
                _mark_kept(item)
                continue
            content_abs, visible, px_box = result
            if _rects_close(visible, content_abs):
                _mark_kept(item)
                continue
            if (item.get("rotation") or 0) % 360 != 0:
                warnings.append(f"image {item_id[1]}: rotated, keeping source (LWCROP)")
                _mark_kept(item)
                continue

            if dry_run:
                warnings.append(f"image {item_id[1]}: --no-image-crop, keeping source (LWCROP)")
                _mark_kept(item)
                continue

            data_id = _data_identifier(obj)
            member = data_index.get(str(data_id)) if data_id is not None else None
            if member is None:
                warnings.append(f"image {item_id[1]}: unresolved data member, keeping source (LWCROP)")
                _mark_kept(item)
                continue

            from PIL import Image  # noqa: PLC0415

            try:
                with zf.open(member) as fh:
                    src_img = Image.open(fh)
                    src_img.load()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"image {item_id[1]}: could not open {member} ({exc}), keeping source (LWCROP)")
                _mark_kept(item)
                continue

            orientation = None
            try:
                orientation = (src_img.getexif() or {}).get(274)
            except Exception:  # noqa: BLE001
                orientation = None
            natural = _asset_natural_size(obj)
            if orientation not in (None, 1) or src_img.size != (round(natural[0]), round(natural[1])):
                warnings.append(f"image {item_id[1]}: EXIF/pixel-size mismatch, keeping source (LWCROP)")
                _mark_kept(item)
                continue

            if (px_box[2] - px_box[0]) < MIN_CROP_PX or (px_box[3] - px_box[1]) < MIN_CROP_PX:
                _cleanup()
                raise CropRefusal(f"slide {number} image {item_id[1]}: crop window under {MIN_CROP_PX:.0f}px")

            source_name = item.get("fileName") or Path(member).name
            if source_name in used_names:
                _cleanup()
                raise CropRefusal(
                    f"slide {number} image {item_id[1]}: fileName {source_name!r} collides with another "
                    "kept image already cropped this slide"
                )
            out_dir = Path(crop_dir) / str(number)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / source_name
            ext = Path(source_name).suffix.lower()
            save_kwargs = {"quality": 95} if ext in (".jpg", ".jpeg") else {}
            temp_fd, temp_name = tempfile.mkstemp(dir=out_dir, prefix=f".{source_name}.", suffix=ext)
            os.close(temp_fd)
            temp_path = Path(temp_name)
            try:
                src_img.crop(px_box).save(temp_path, **save_kwargs)
            except Exception as exc:  # noqa: BLE001
                temp_path.unlink(missing_ok=True)
                warnings.append(f"image {item_id[1]}: could not save crop as {source_name!r} ({exc}), keeping source (LWCROP)")
                _mark_kept(item)
                continue

            used_names.add(source_name)
            pending_writes.append((temp_path, out_path))
            crops[item_id] = CropSpec(
                path=out_path, source_file_name=source_name, px_box=px_box, visible=visible,
            )

    for name in used_names:
        if name in kept_uncropped_names:
            _cleanup()
            conflicting = next(iid for iid, spec in crops.items() if spec.source_file_name == name)
            raise CropRefusal(
                f"slide {number} image {conflicting[1]}: fileName {name!r} collides with another "
                "kept image left uncropped this slide"
            )

    return crops, warnings, tuple(pending_writes)
