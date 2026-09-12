"""Offline DSK-side slide classification and CG-band fitting from the IWA graph.

Classifies each slide (empty/static/built/movie/mixed) from the offline wall
payload and ``deck_builds``, and fits item rects into a reference deck's
image/movie band for CG-style placement. Never opens Keynote.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from obed_edom.iwa_builds import _ref_id, _transition_effect_duration, build_identity, deck_builds
from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.map_remap import (
    CENTRE_PANEL_RECT,
    LW_WALL_SIZE,
    Affine,
    Rect,
    is_backdrop,
    is_lw_wall,
    is_side_panel_item,
    is_visible,
    item_rect,
)
from obed_edom.offline_inspect import _round_pt, offline_wall_payload

ItemId = tuple[str, int]


def _delete_order(ids: Sequence[ItemId]) -> tuple[ItemId, ...]:
    return tuple(sorted(ids, key=lambda iid: (iid[0], -iid[1])))


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


def _is_text_slide_kept(kept: Sequence[dict], text_slide_words: int) -> tuple[bool, tuple[ItemId, ...]]:
    """``(is_text, long_text_ids)`` -- a slide is text when some kept ``text`` item's
    content has more than ``text_slide_words`` whitespace-separated words (F2/D1)."""
    long_ids = [
        (item["kind"], item["kindIndex"])
        for item in kept
        if item.get("kind") == "text" and len([w for w in (item.get("text") or "").split() if w]) > text_slide_words
    ]
    return (bool(long_ids), tuple(long_ids))


def _filter_kept_items(
    items: Sequence[dict],
    wall_w: float,
    wall_h: float,
    *,
    include_side: bool,
    group_child_text: Mapping[int, str | None] | None = None,
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
) -> tuple[
    list[dict], list[ItemId], tuple[ItemId, ...], tuple[ItemId, ...], tuple[str, ...],
    bool, tuple[ItemId, ...], tuple[ItemId, ...],
]:
    """Shared filter dropping backdrops/off-canvas/side-panel/scrim/text-slide-media/mirror
    duplicates. Returns ``(kept, dropped_side, dropped_backdrop, dropped_duplicate, ...)``."""
    kept: list[dict] = []
    dropped_side: list[ItemId] = []
    panel_backdrops: list[dict] = []
    for item in items:
        item_id: ItemId = (item["kind"], item["kindIndex"])
        if is_backdrop(item, wall_w, wall_h):
            continue
        if not is_visible(item, wall_w, wall_h):
            continue
        if not include_side and is_side_panel_item(item, wall_w, wall_h):
            dropped_side.append(item_id)
            continue
        if is_panel_backdrop(item, (wall_w, wall_h), include_side=include_side):
            panel_backdrops.append(item)
            continue
        kept.append(item)
    if kept:
        dropped_backdrop = tuple((i["kind"], i["kindIndex"]) for i in panel_backdrops)
    else:
        kept.extend(panel_backdrops)
        dropped_backdrop = ()

    is_text, long_text_ids = _is_text_slide_kept(kept, text_slide_words)
    dropped_media_text: tuple[ItemId, ...] = ()
    if is_text:
        media_ids = {
            (i["kind"], i["kindIndex"]) for i in kept if i.get("kind") in ("image", "movie")
        }
        if media_ids:
            dropped_media_text = tuple(sorted(media_ids, key=lambda iid: (iid[0], iid[1])))
            kept = [item for item in kept if (item["kind"], item["kindIndex"]) not in media_ids]

    duplicate_map, mirror_warnings = mirror_duplicates(
        kept, (wall_w, wall_h), group_child_text=group_child_text
    )
    dropped_duplicate = tuple(duplicate_map)
    if dropped_duplicate:
        dup_set = set(dropped_duplicate)
        kept = [item for item in kept if (item["kind"], item["kindIndex"]) not in dup_set]
        long_text_ids = tuple(iid for iid in long_text_ids if iid not in dup_set)

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
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
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
        group_child_text=group_child_text, text_slide_words=text_slide_words,
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
) -> list[SlideClass]:
    """Classify every slide in ``payload`` (built from ``deck_path``/``deck`` if omitted)."""
    from obed_edom.iwa_runs import attach_group_content_signature  # noqa: PLC0415

    graph = deck if deck is not None else _load_deck(deck_path)
    if payload is None:
        payload = offline_wall_payload(deck_path, deck=graph)
        attach_group_content_signature(deck_path, payload, deck=graph)
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
                text_slide_words=text_slide_words,
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
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
) -> dict[ItemId, Rect]:
    wall_rect = Rect(0.0, 0.0, *LW_WALL_SIZE) if include_side else CENTRE_PANEL_RECT
    filtered_items = _filter_kept_items(
        items, wall_w, wall_h, include_side=include_side, group_child_text=group_child_text,
        text_slide_words=text_slide_words,
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
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
) -> Rect | None:
    """Wall-space union of kept visible item rects (per ``_filter_kept_items``), or ``None``
    if nothing is kept/visible. Used by the DSK movie export's include_side crop rect."""
    visibles = _visibles_by_wall(
        items, wall[0], wall[1], include_side=include_side, group_child_text=group_child_text,
        text_slide_words=text_slide_words,
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
    text_slide_words: int = DEFAULT_TEXT_SLIDE_WORDS,
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
            text_slide_words=text_slide_words,
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
    lines: list[str] = []
    for paragraph in _re.split(para_pattern, text or ""):
        if paragraph == "":
            lines.append("")
            continue
        words = _re.split(pattern, paragraph)
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if not current or font.getlength(trial) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def wrapped_height(text: str, font_name: str, size: float, width: float) -> float | None:
    """Estimated laid-out height (pt) of ``text`` at ``size`` wrapped to ``width`` (F9).
    ``None`` when the font cannot be resolved -- callers must warn and fall back."""
    path = resolve_font_path(font_name)
    if path is None or size <= 0:
        return None
    from PIL import ImageFont  # noqa: PLC0415

    font = ImageFont.truetype(str(path), int(round(size * _WRAP_OVERSAMPLE)))
    lines = _wrap_lines(text, font, width * _WRAP_OVERSAMPLE)
    return len(lines) * _LINE_HEIGHT_FACTOR * size + _BOX_PADDING_PT


@dataclass(frozen=True)
class TextBox:
    item_id: ItemId
    text: str
    font_name: str
    size: float


def fit_text_stack(
    boxes: Sequence[TextBox], band: Band, min_text_pt: float, *, gap: float = _TEXT_GAP_PT
) -> tuple[float, dict[ItemId, float], dict[ItemId, float]] | None:
    """Largest ``t`` in ``(0, 1]`` fitting ``boxes`` stacked with ``gap`` into ``band``, or
    ``None``. A fixed safety term against the estimator's own measured under-prediction
    is charged for every box count; the live ``OVERFLOW`` read-back is the final authority
    on wrap."""
    if not boxes:
        return None
    t = 1.00
    while t > 0.0:
        sizes = {box.item_id: box.size * t for box in boxes}
        if any(sizes[box.item_id] < min(min_text_pt, box.size) for box in boxes):
            return None
        heights: dict[ItemId, float] = {}
        for box in boxes:
            h = wrapped_height(box.text, box.font_name, sizes[box.item_id], band.width)
            if h is None:
                return None
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
