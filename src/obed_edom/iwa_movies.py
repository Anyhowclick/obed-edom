"""Offline poster-frame/autoplay patches for ``TSD.MovieArchive`` (reveal movies),
separate from ``iwa_write.py`` which is geometry-scoped. Same surgical
single-member-rewrite shape as ``iwa_write.patch_slide_builds``: locate the owning
member via ``id_to_file``, patch only that member, verify the re-encode touched
exactly the intended archives, and refuse (deck untouched) otherwise.
"""
from __future__ import annotations

import copy
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from keynote_parser.codec import IWAFile

from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_write import OfflineWriteCorrupted, _archive_diff, _rewrite_members, patch_slide_builds

_FRAME_TOL = 1.0


def movie_archives(deck: Path) -> list[dict]:
    """One dict per ``TSD.MovieArchive`` in the deck, composed geometry included."""
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    out: list[dict] = []
    for slide_id, _skipped in slide_order(objects):
        slide = objects.get(slide_id)
        if not slide:
            continue
        for rec in compose_geometry(slide, objects):
            if rec["kind"] != "movie":
                continue
            obj = objects.get(rec["id"]) or {}
            data_ref = obj.get("movieData") or {}
            data_id = data_ref.get("identifier")
            data_id = str(data_id) if data_id is not None else None
            data_name = None
            if data_id is not None:
                data_obj = objects.get(data_id) or {}
                data_name = data_obj.get("path") or data_obj.get("name")
            natural = obj.get("naturalSize") or {}
            out.append(
                {
                    "id": rec["id"],
                    "member": id_to_file.get(rec["id"]),
                    "x": rec["x"],
                    "y": rec["y"],
                    "w": rec["w"],
                    "h": rec["h"],
                    "posterTime": float(obj.get("posterTime") or 0.0),
                    "startTime": float(obj.get("startTime") or 0.0),
                    "endTime": float(obj.get("endTime") or 0.0),
                    "autoPlay": bool(obj.get("autoPlay") or False),
                    "playsAcrossSlides": bool(obj.get("playsAcrossSlides") or False),
                    "hasPosterImageData": bool((obj.get("posterImageData") or {}).get("identifier")),
                    "naturalSize": (natural.get("width"), natural.get("height")),
                    "dataId": data_id,
                    "dataName": data_name,
                }
            )
    return out


def _match_one_to_one(deck: Path, targets: list[dict]) -> dict:
    """Match each ``target`` ({x,y,w,h,name}) to exactly one composed movie archive
    frame within ``_FRAME_TOL`` px on all four of x/y/w/h. Refuses (nothing planned)
    on zero or ambiguous matches. Returns ``{"refused", "reason", "ids"}`` with ``ids``
    in target order; this selection deliberately excludes full-width ``map:True``
    background fly movies, whose geometry never matches a landmark target.
    """
    archives = movie_archives(deck)
    ids: list[str] = []
    claimed_by: dict[str, Any] = {}
    for i, target in enumerate(targets):
        matches = [
            a
            for a in archives
            if abs(a["x"] - target["x"]) <= _FRAME_TOL
            and abs(a["y"] - target["y"]) <= _FRAME_TOL
            and abs(a["w"] - target["w"]) <= _FRAME_TOL
            and abs(a["h"] - target["h"]) <= _FRAME_TOL
        ]
        if len(matches) != 1:
            name = target.get("name", i)
            return {"refused": True, "reason": f"target {name!r} matched {len(matches)} movie archive(s)", "ids": []}
        aid = matches[0]["id"]
        if aid in claimed_by:
            name = target.get("name", i)
            other = claimed_by[aid]
            return {
                "refused": True,
                "reason": f"movie archive {aid} matched both target {other!r} and target {name!r}",
                "ids": [],
            }
        claimed_by[aid] = target.get("name", i)
        ids.append(aid)
    return {"refused": False, "reason": None, "ids": ids}


def plan_movie_posters(deck: Path, targets: list[dict]) -> dict:
    """Match each ``target`` ({x,y,w,h,posterTime,name}) to exactly one composed movie
    archive frame. See `_match_one_to_one`.
    """
    match = _match_one_to_one(deck, targets)
    if match["refused"]:
        return {"refused": True, "reason": match["reason"], "posters": {}}
    posters = {aid: float(target["posterTime"]) for aid, target in zip(match["ids"], targets)}
    return {"refused": False, "reason": None, "posters": posters}


def plan_movie_autoplay(deck: Path, targets: list[dict]) -> dict:
    """Same one-to-one geometry match as `plan_movie_posters`, for landmark reveal
    movies that should start playing right after the slide's build-in transition.
    `target` needs only x/y/w/h/name.
    """
    match = _match_one_to_one(deck, targets)
    if match["refused"]:
        return {"refused": True, "reason": match["reason"], "ids": []}
    return {"refused": False, "reason": None, "ids": match["ids"]}


def _patch_archive_fields(deck: Path, patches: list[tuple[str, str, dict[str, Any]]]) -> dict:
    """Patch ``field: value`` pairs onto each named archive in place. ``patches`` is a
    list of ``(archive_id, pbtype, {field: value})``; the same archive id may not
    appear twice. Refuses (deck untouched) unless every id resolves to a same-member
    archive of the stated ``pbtype`` and, per member, the re-encode changed exactly
    the intended archive(s) -- the same self-check gate as `iwa_write.patch_slide_builds`.
    """
    deck = Path(deck)
    if not patches:
        return {"refused": False, "reason": None, "touched": [], "applied": 0}

    objects, id_to_file, _file_ids = _load_deck(deck)
    fields_by_id: dict[str, dict[str, Any]] = {}
    for oid, pbtype, fields in patches:
        obj = objects.get(oid)
        if obj is None or obj.get("_pbtype") != pbtype:
            return {"refused": True, "reason": f"{oid} does not resolve to a {pbtype}", "touched": [], "applied": 0}
        fields_by_id[oid] = fields

    by_member: dict[str, list[str]] = {}
    for oid, _pbtype, _fields in patches:
        member = id_to_file.get(oid)
        if member is None:
            return {"refused": True, "reason": f"{oid} has no owning member", "touched": [], "applied": 0}
        by_member.setdefault(member, []).append(oid)

    edits: dict[str, bytes] = {}
    applied = 0
    touched_ids: list[str] = []
    with zipfile.ZipFile(deck) as zf:
        for member, ids in by_member.items():
            buf = zf.read(member)
            decoded = IWAFile.from_buffer(buf, member).to_dict()
            patched = copy.deepcopy(decoded)
            wanted = set(ids)
            touched = 0
            for ch in patched["chunks"]:
                for arch in ch["archives"]:
                    aid = str(arch["header"]["identifier"])
                    if aid not in wanted:
                        continue
                    for o in arch.get("objects") or []:
                        for field, value in fields_by_id[aid].items():
                            o[field] = value
                        touched += 1

            if touched != len(wanted):
                return {
                    "refused": True,
                    "reason": f"expected to touch {len(wanted)} archive(s) in {member}, touched {touched}",
                    "touched": [],
                    "applied": 0,
                }

            new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
            reparsed = IWAFile.from_buffer(new_member, member).to_dict()
            removed, added, changed = _archive_diff(decoded, reparsed)
            if removed or added or not set(changed) <= wanted:
                return {
                    "refused": True,
                    "reason": f"{member}: re-encode touched fewer/other than the intended archive(s) "
                    f"(removed={sorted(removed)}, added={sorted(added)}, changed={sorted(changed)})",
                    "touched": [],
                    "applied": 0,
                }
            edits[member] = new_member
            applied += touched
            touched_ids.extend(ids)

    try:
        _rewrite_members(deck, edits)
    except OfflineWriteCorrupted:
        raise  # deck IS truncated: must reach the caller, never a refused result
    except Exception as exc:  # noqa: BLE001 — every result refuses, deck left untouched
        return {"refused": True, "reason": f"rewrite failed: {exc}", "touched": [], "applied": 0}

    return {"refused": False, "reason": None, "touched": sorted(touched_ids), "applied": applied}


def patch_movie_posters(deck: Path, posters: dict[str, float]) -> dict:
    """Patch each named ``TSD.MovieArchive``'s ``posterTime`` in place. Never touches
    ``posterImageData``/``endTime``.
    """
    posters = {str(k): float(v) for k, v in posters.items()}
    patches = [(oid, "TSD.MovieArchive", {"posterTime": value}) for oid, value in posters.items()]
    return _patch_archive_fields(deck, patches)


def _movie_slide(objects: dict, movie_id: str) -> str | None:
    """The one ``KN.SlideArchive`` whose ``drawablesZOrder`` holds ``movie_id``
    (``None`` on zero or several -- reveal movies are always top-level drawables,
    the same assumption ``iwa_builds.deck_builds`` makes of a build's target)."""
    owners = [
        slide_id
        for slide_id, _skipped in slide_order(objects)
        if any(
            str((ref or {}).get("identifier")) == movie_id
            for ref in (objects.get(slide_id) or {}).get("drawablesZOrder") or []
        )
    ]
    return owners[0] if len(owners) == 1 else None


def _movie_build_chunk(objects: dict, id_to_file: dict, movie_id: str) -> tuple[str | None, str | None]:
    """Resolve the single ``KN.BuildChunkArchive`` for ``movie_id``'s
    ``apple:movie-start`` build, THROUGH the owning slide's own ``builds``/
    ``buildChunks`` timeline -- this repo deliberately leaves orphaned build/chunk
    archives in place (``iwa_write.patch_slide_builds``), so a global search could
    patch an archive Keynote never plays. Returns ``(chunk_id, error)``; refuses
    (``chunk_id`` ``None``) rather than guess.
    """
    slide_id = _movie_slide(objects, movie_id)
    if slide_id is None:
        return None, f"movie {movie_id} does not resolve to exactly one owning slide"
    slide = objects.get(slide_id) or {}
    listed_builds = {str((ref or {}).get("identifier")) for ref in slide.get("builds") or []}

    chunks: list[str] = []
    for ref in slide.get("buildChunks") or []:
        chunk_id = str((ref or {}).get("identifier"))
        chunk = objects.get(chunk_id)
        if not chunk or chunk.get("_pbtype") != "KN.BuildChunkArchive":
            continue
        build_id = str((chunk.get("build") or {}).get("identifier"))
        if build_id not in listed_builds:
            continue
        build = objects.get(build_id) or {}
        if build.get("_pbtype") != "KN.BuildArchive":
            continue
        if str((build.get("drawable") or {}).get("identifier")) != movie_id:
            continue
        if ((build.get("attributes") or {}).get("animationAttributes") or {}).get("effect") != "apple:movie-start":
            continue
        if id_to_file.get(build_id) != id_to_file.get(movie_id):
            return None, f"movie {movie_id} build {build_id} lives in another member"
        chunks.append(chunk_id)

    if len(chunks) != 1:
        return None, f"movie {movie_id} has {len(chunks)} listed apple:movie-start build chunk(s) on slide {slide_id}"
    chunk_id = chunks[0]
    if id_to_file.get(chunk_id) != id_to_file.get(movie_id):
        return None, f"movie {movie_id} chunk {chunk_id} lives in another member"
    return chunk_id, None


def movie_autoplay_state(deck: Path, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Read back each movie's ``playsAcrossSlides`` and its ``apple:movie-start`` build
    chunk's ``automatic``/``referent``/``delay``/``chunkPos`` (0-based index into the
    owning slide's ``buildChunks``), for verify-mode logging after `patch_movie_autoplay`
    and `patch_clip_start_timing`."""
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    out: dict[str, dict[str, Any]] = {}
    for oid in ids:
        obj = objects.get(oid) or {}
        chunk_id, _error = _movie_build_chunk(objects, id_to_file, oid)
        chunk = objects.get(chunk_id) if chunk_id else None
        chunk_pos = None
        if chunk_id is not None:
            slide_id = _movie_slide(objects, oid)
            slide = objects.get(slide_id) or {}
            chunk_refs = [str((ref or {}).get("identifier")) for ref in slide.get("buildChunks") or []]
            if chunk_id in chunk_refs:
                chunk_pos = chunk_refs.index(chunk_id)
        out[oid] = {
            "playsAcrossSlides": bool(obj.get("playsAcrossSlides") or False),
            "automatic": bool(chunk.get("automatic")) if chunk is not None else None,
            "referent": bool(chunk.get("referent")) if chunk is not None else None,
            "delay": float(chunk.get("delay")) if chunk is not None and chunk.get("delay") is not None else None,
            "chunkPos": chunk_pos,
        }
    return out


def patch_movie_autoplay(deck: Path, ids: list[str]) -> dict:
    """Start each named landmark reveal movie right after its slide's build-in
    transition: set the movie's ``apple:movie-start`` build chunk's ``automatic`` to
    ``True`` and the movie's own ``playsAcrossSlides`` to ``False`` (probe-confirmed
    against Keynote's own "Start = After Transition" save). Refuses (deck untouched)
    unless every id resolves to a ``TSD.MovieArchive`` with exactly one such build
    and chunk.
    """
    deck = Path(deck)
    ids = sorted({str(i) for i in ids})
    if not ids:
        return {"refused": False, "reason": None, "touched": [], "applied": 0}

    objects, id_to_file, _file_ids = _load_deck(deck)
    for oid in ids:
        obj = objects.get(oid)
        if obj is None or obj.get("_pbtype") != "TSD.MovieArchive":
            return {"refused": True, "reason": f"{oid} does not resolve to a TSD.MovieArchive", "touched": [], "applied": 0}

    patches: list[tuple[str, str, dict[str, Any]]] = []
    for movie_id in ids:
        chunk_id, error = _movie_build_chunk(objects, id_to_file, movie_id)
        if error:
            return {"refused": True, "reason": error, "touched": [], "applied": 0}
        patches.append((chunk_id, "KN.BuildChunkArchive", {"automatic": True}))
        patches.append((movie_id, "TSD.MovieArchive", {"playsAcrossSlides": False}))

    result = _patch_archive_fields(deck, patches)
    if result["refused"]:
        return {"refused": True, "reason": result["reason"], "touched": [], "applied": 0}
    return {"refused": False, "reason": None, "touched": ids, "applied": len(ids)}


@dataclass(frozen=True)
class ClipTiming:
    """One inserted DSK clip's start timing, per owner rule
    (see ``.agents/briefs/dsk-clip-timing.md`` rule 2)."""

    movie_id: str
    mode: Literal["after_transition", "with_build_1", "after_previous"]


_CLIP_TIMING_FLAGS: dict[str, dict[str, Any]] = {
    "after_transition": {"automatic": True, "referent": True, "delay": 0.0},
    "with_build_1": {"automatic": True, "referent": False, "delay": 0.0},
    "after_previous": {"automatic": True, "referent": True, "delay": 0.0},
}

# Category rank within a slide's build-chunk order: every ``after_transition`` entry
# (chunk position 0) first, then every ``with_build_1`` entry (right after chunk 0),
# then every ``after_previous`` entry (cascade), each group keeping its given order.
_CLIP_TIMING_RANK = {"after_transition": 0, "with_build_1": 1, "after_previous": 2}


def patch_clip_start_timing(deck: Path, plans: Mapping[str, Sequence[ClipTiming]]) -> dict:
    """Set the start timing of inserted DSK clip movies (see rule 2 of the brief) and
    clear ``playsAcrossSlides`` on every one of them. ``plans`` maps slideId to its
    clips in VISUAL ORDER. Resolves each movie's single ``apple:movie-start`` chunk
    via `_movie_build_chunk`; any resolution failure raises ``ValueError`` before any
    write. Build-chunk ORDER is patched via ``iwa_write.patch_slide_builds`` only when
    it differs from the deck's current order -- the slide's own ``builds`` list and
    ``transition`` pass through verbatim, and any build chunk not named in the plan
    keeps its current slot. Never touches chunk ``duration``, delivery, or ids.
    Re-reads and verifies ``(automatic, referent, delay, chunkPos)`` per movie and
    ``playsAcrossSlides is False``, raising ``ValueError`` on any mismatch. Returns the
    verified state per slide: ``{slideId: {movieId: {...}}}``.
    """
    deck = Path(deck)
    plans = {str(k): list(v) for k, v in plans.items()}
    if not plans:
        return {}

    objects, id_to_file, _file_ids = _load_deck(deck)

    field_patches: list[tuple[str, str, dict[str, Any]]] = []
    build_plans: dict[str, dict[str, Any]] = {}
    expected_pos: dict[str, dict[str, int]] = {}

    for slide_id, entries in plans.items():
        if not entries:
            continue
        movie_ids = [str(e.movie_id) for e in entries]
        if len(set(movie_ids)) != len(movie_ids):
            raise ValueError(f"slide {slide_id}: duplicate movie id in plan")

        chunk_by_movie: dict[str, str] = {}
        for movie_id in movie_ids:
            obj = objects.get(movie_id)
            if obj is None or obj.get("_pbtype") != "TSD.MovieArchive":
                raise ValueError(f"{movie_id} does not resolve to a TSD.MovieArchive")
            chunk_id, error = _movie_build_chunk(objects, id_to_file, movie_id)
            if error:
                raise ValueError(error)
            chunk_by_movie[movie_id] = chunk_id

        owning_slides = {_movie_slide(objects, movie_id) for movie_id in movie_ids}
        if len(owning_slides) != 1 or slide_id not in owning_slides:
            raise ValueError(f"slide {slide_id}: plan movies do not all resolve to that slide")

        slide = objects.get(slide_id) or {}
        current_chunk_ids = [str((ref or {}).get("identifier")) for ref in slide.get("buildChunks") or []]

        ordered = sorted(
            range(len(entries)), key=lambda i: (_CLIP_TIMING_RANK[entries[i].mode], i)
        )
        target_order = [chunk_by_movie[movie_ids[i]] for i in ordered]

        target_set = set(target_order)
        slots = [i for i, cid in enumerate(current_chunk_ids) if cid in target_set]
        if len(slots) != len(target_order):
            raise ValueError(f"slide {slide_id}: plan chunk(s) not all listed in buildChunks")

        new_chunk_ids = list(current_chunk_ids)
        for slot, cid in zip(slots, target_order):
            new_chunk_ids[slot] = cid

        if new_chunk_ids != current_chunk_ids:
            build_plans[slide_id] = {
                "builds": [str((r or {}).get("identifier")) for r in slide.get("builds") or []],
                "buildChunks": new_chunk_ids,
                "transition": copy.deepcopy(slide.get("transition")),
            }

        expected_pos[slide_id] = {movie_id: new_chunk_ids.index(chunk_by_movie[movie_id]) for movie_id in movie_ids}

        for entry in entries:
            movie_id = str(entry.movie_id)
            chunk_id = chunk_by_movie[movie_id]
            flags = _CLIP_TIMING_FLAGS[entry.mode]
            field_patches.append((chunk_id, "KN.BuildChunkArchive", dict(flags)))
            field_patches.append((movie_id, "TSD.MovieArchive", {"playsAcrossSlides": False}))

    if build_plans:
        result = patch_slide_builds(deck, build_plans)
        if result["refused"]:
            raise ValueError(result["reason"])

    if field_patches:
        result = _patch_archive_fields(deck, field_patches)
        if result["refused"]:
            raise ValueError(result["reason"])

    all_movie_ids = sorted({str(e.movie_id) for entries in plans.values() for e in entries})
    state = movie_autoplay_state(deck, all_movie_ids)

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for slide_id, entries in plans.items():
        if not entries:
            continue
        slide_state: dict[str, dict[str, Any]] = {}
        for entry in entries:
            movie_id = str(entry.movie_id)
            got = state[movie_id]
            want_flags = _CLIP_TIMING_FLAGS[entry.mode]
            want_pos = expected_pos[slide_id][movie_id]
            if (
                got["automatic"] != want_flags["automatic"]
                or got["referent"] != want_flags["referent"]
                or got["delay"] != want_flags["delay"]
                or got["chunkPos"] != want_pos
                or got["playsAcrossSlides"] is not False
            ):
                raise ValueError(f"slide {slide_id} movie {movie_id}: verify mismatch, got {got}, want {want_flags} at chunkPos {want_pos}")
            slide_state[movie_id] = got
        out[slide_id] = slide_state
    return out
