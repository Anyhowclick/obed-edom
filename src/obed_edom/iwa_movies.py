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
    """One dict per ``TSD.MovieArchive`` in the deck, composed geometry included.

    ``slideIndex`` is 1-based ``slideTree`` order (skipped slides included, same
    numbering Keynote uses). ``slideId`` is the owning ``KN.SlideArchive`` id.
    """
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    out: list[dict] = []
    for slide_index, (slide_id, _skipped) in enumerate(slide_order(objects), start=1):
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
                    "slideId": slide_id,
                    "slideIndex": slide_index,
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


def _target_slide(target: dict) -> tuple[str, Any] | None:
    """Prefer ``slideId`` (archive identity) over 1-based ``slideIndex``."""
    slide_id = target.get("slideId")
    if slide_id is not None and str(slide_id) != "":
        return ("slideId", str(slide_id))
    if target.get("slideIndex") is not None:
        return ("slideIndex", int(target["slideIndex"]))
    return None


def _archives_on_slide(archives: list[dict], target: dict) -> list[dict] | None:
    key = _target_slide(target)
    if key is None:
        return None
    kind, value = key
    return [archive for archive in archives if archive.get(kind) == value]


def _frame_matches(archive: dict, target: dict) -> bool:
    return (
        abs(archive["x"] - target["x"]) <= _FRAME_TOL
        and abs(archive["y"] - target["y"]) <= _FRAME_TOL
        and abs(archive["w"] - target["w"]) <= _FRAME_TOL
        and abs(archive["h"] - target["h"]) <= _FRAME_TOL
    )


def _match_one_to_one(deck: Path, targets: list[dict]) -> dict:
    """Match each ``target`` to exactly one composed movie archive.

    Restricts candidates to the target's slide (``slideId`` or 1-based
    ``slideIndex``) before checking x/y/w/h within ``_FRAME_TOL``. Two full-frame
    fly movies on different slides therefore do not collide. Refuses (nothing
    planned) when the target has no slide identity, or on zero/ambiguous
    geometry matches. Returns ``{"refused", "reason", "ids"}`` in target order.
    """
    archives = movie_archives(deck)
    ids: list[str] = []
    claimed_by: dict[str, Any] = {}
    for i, target in enumerate(targets):
        name = target.get("name", i)
        pool = _archives_on_slide(archives, target)
        if pool is None:
            return {"refused": True, "reason": f"target {name!r} has no slide identity", "ids": []}
        matches = [archive for archive in pool if _frame_matches(archive, target)]
        if len(matches) != 1:
            return {"refused": True, "reason": f"target {name!r} matched {len(matches)} movie archive(s)", "ids": []}
        aid = matches[0]["id"]
        if aid in claimed_by:
            other = claimed_by[aid]
            return {
                "refused": True,
                "reason": f"movie archive {aid} matched both target {other!r} and target {name!r}",
                "ids": [],
            }
        claimed_by[aid] = name
        ids.append(aid)
    return {"refused": False, "reason": None, "ids": ids}


def plan_movie_posters(deck: Path, targets: list[dict]) -> dict:
    """Match each ``target`` ({x,y,w,h,posterTime,name,slideIndex|slideId}) to
    exactly one composed movie archive frame. See `_match_one_to_one`.
    """
    match = _match_one_to_one(deck, targets)
    if match["refused"]:
        return {"refused": True, "reason": match["reason"], "posters": {}}
    posters = {aid: float(target["posterTime"]) for aid, target in zip(match["ids"], targets)}
    return {"refused": False, "reason": None, "posters": posters}


def plan_movie_autoplay(deck: Path, targets: list[dict]) -> dict:
    """Same one-to-one slide-then-geometry match as `plan_movie_posters`, for
    movies that should start playing right after the slide's build-in transition
    (fly backdrops, pin-drop waves, and landmark reveals). `target` needs
    x/y/w/h/name and ``slideIndex`` or ``slideId``.
    """
    match = _match_one_to_one(deck, targets)
    if match["refused"]:
        return {"refused": True, "reason": match["reason"], "ids": []}
    return {"refused": False, "reason": None, "ids": match["ids"]}


def _set_field(obj: dict, field: str, value: Any) -> str | None:
    """Set a plain or dotted ``field`` on an archive object dict. Returns the dotted
    prefix of the first parent that is not an existing message, or ``None`` on success."""
    *parents, leaf = field.split(".")
    target = obj
    for i, part in enumerate(parents):
        child = target.get(part)
        if not isinstance(child, dict):
            return ".".join(parents[: i + 1])
        target = child
    target[leaf] = value
    return None


def _patch_archive_fields(deck: Path, patches: list[tuple[str, str, dict[str, Any]]]) -> dict:
    """Patch ``field: value`` pairs onto each named archive in place. ``patches`` is a
    list of ``(archive_id, pbtype, {field: value})``; the same archive id may not
    appear twice. A dotted ``field`` walks into the archive's EXISTING nested messages
    (``attributes.animationAttributes.effect``); a missing or non-dict parent refuses
    rather than minting one. Refuses (deck untouched) unless every id resolves to a
    same-member archive of the stated ``pbtype`` and, per member, the re-encode changed
    exactly the intended archive(s) -- the same self-check gate as
    `iwa_write.patch_slide_builds`.
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
                            missing = _set_field(o, field, value)
                            if missing is not None:
                                return {
                                    "refused": True,
                                    "reason": f"{aid} has no {missing} message to patch {field} into",
                                    "touched": [],
                                    "applied": 0,
                                }
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


_MOVIE_START = ("apple:movie-start",)


def _movie_build_chunk(
    objects: dict, id_to_file: dict, movie_id: str, effects: Sequence[str] = _MOVIE_START
) -> tuple[str | None, str | None]:
    """Resolve the single ``KN.BuildChunkArchive`` for ``movie_id``'s
    ``apple:movie-start`` build, THROUGH the owning slide's own ``builds``/
    ``buildChunks`` timeline -- this repo deliberately leaves orphaned build/chunk
    archives in place (``iwa_write.patch_slide_builds``), so a global search could
    patch an archive Keynote never plays. ``effects`` widens the accepted build
    effect, so a clip whose movie-start build has already had a build-in effect
    written onto it still resolves. Returns ``(chunk_id, error)``; refuses
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
        if ((build.get("attributes") or {}).get("animationAttributes") or {}).get("effect") not in effects:
            continue
        if id_to_file.get(build_id) != id_to_file.get(movie_id):
            return None, f"movie {movie_id} build {build_id} lives in another member"
        chunks.append(chunk_id)

    if len(chunks) != 1:
        return None, (
            f"movie {movie_id} has {len(chunks)} listed {'/'.join(effects)} build chunk(s) on slide {slide_id}"
        )
    chunk_id = chunks[0]
    if id_to_file.get(chunk_id) != id_to_file.get(movie_id):
        return None, f"movie {movie_id} chunk {chunk_id} lives in another member"
    return chunk_id, None


def movie_autoplay_state(
    deck: Path, ids: list[str], effects: Mapping[str, Sequence[str]] | None = None
) -> dict[str, dict[str, Any]]:
    """Read back each movie's ``playsAcrossSlides`` and its ``apple:movie-start`` build
    chunk's ``automatic``/``referent``/``delay``/``chunkPos`` (0-based index into the
    owning slide's ``buildChunks``), for verify-mode logging after `patch_movie_autoplay`
    and `patch_clip_start_timing`. ``effects`` widens the accepted build effect per movie
    (a clip that now carries a written build-in)."""
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    out: dict[str, dict[str, Any]] = {}
    for oid in ids:
        obj = objects.get(oid) or {}
        chunk_id, _error = _movie_build_chunk(objects, id_to_file, oid, (effects or {}).get(oid, _MOVIE_START))
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
    """Start each named movie right after its slide's build-in transition: set
    the movie's ``apple:movie-start`` build chunk's ``automatic`` to ``True`` and
    the movie's own ``playsAcrossSlides`` to ``False`` (probe-confirmed against
    Keynote's own "Start = After Transition" save). Refuses (deck untouched)
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
    (see ``.agents/briefs/dsk-clip-timing.md`` rule 2). ``build_in`` (with
    ``build_in_duration``) additionally rewrites the clip's own auto-created
    ``apple:movie-start`` build to the SOURCE build-in effect -- a stacked upper clip
    that must dissolve in over the clip below (plan §4 item 28)."""

    movie_id: str
    mode: Literal["after_transition", "with_build_1", "with_previous", "after_previous", "on_click"]
    delay: float = 0.0
    build_in: str | None = None
    build_in_duration: float | None = None


_CLIP_TIMING_FLAGS: dict[str, dict[str, Any]] = {
    "after_transition": {"automatic": True, "referent": True},
    "with_build_1": {"automatic": True, "referent": False},
    "with_previous": {"automatic": True, "referent": False},
    "after_previous": {"automatic": True, "referent": True},
    "on_click": {"automatic": False, "referent": True},
}

# Category rank within a slide's build-chunk order: every ``after_transition`` entry
# (chunk position 0) first, then every "with" entry (right after chunk 0), then every
# chain entry (cascade), each group keeping its given order. A slide carrying a
# ``build_in`` entry ignores this and keeps the plan's own (source build) order.
_CLIP_TIMING_RANK = {
    "after_transition": 0, "with_build_1": 1, "with_previous": 1, "after_previous": 2, "on_click": 2,
}

_CLIP_MODE_BY_FLAGS = {(True, False): "with_previous", (True, True): "after_previous", (False, True): "on_click"}

# A source build-in this writer may rewrite onto a clip's movie-start build. Measured on
# FRC Wall slide 50 (plan §3): the two KN.BuildArchives differ in `effect` alone.
_BUILD_IN_EFFECTS = frozenset({"apple:dissolve"})


def clip_timing_mode(automatic: Any, referent: Any) -> str | None:
    """The `ClipTiming.mode` reproducing a SOURCE build chunk's start flags, or ``None``
    when the pair is not one this writer expresses (plan §3 "Build-chunk flag encoding";
    After Transition is a position-0 After Previous, so it is never returned here)."""
    return _CLIP_MODE_BY_FLAGS.get((bool(automatic), bool(referent)))


def _clip_build(objects: dict, slide_id: str, movie_id: str) -> tuple[str | None, str | None]:
    """The single build LISTED on ``slide_id`` whose drawable is ``movie_id``. Returns
    ``(build_id, error)``; a clip carrying a second build is refused, not guessed."""
    owned = [
        bid
        for bid in (str((ref or {}).get("identifier")) for ref in (objects.get(slide_id) or {}).get("builds") or [])
        if (objects.get(bid) or {}).get("_pbtype") == "KN.BuildArchive"
        and str(((objects.get(bid) or {}).get("drawable") or {}).get("identifier")) == movie_id
    ]
    if len(owned) != 1:
        return None, f"movie {movie_id} has {len(owned)} listed build(s) on slide {slide_id}, expected exactly one"
    return owned[0], None


def _anim(objects: dict, build_id: str) -> dict:
    return ((objects.get(build_id) or {}).get("attributes") or {}).get("animationAttributes") or {}


def patch_clip_start_timing(deck: Path, plans: Mapping[str, Sequence[ClipTiming]]) -> dict:
    """Set the start timing of inserted DSK clip movies (see rule 2 of the brief) and
    clear ``playsAcrossSlides`` on every one of them. ``plans`` maps slideId to its
    clips in VISUAL ORDER. Resolves each movie's single ``apple:movie-start`` chunk
    via `_movie_build_chunk`; any resolution failure raises ``ValueError`` before any
    write. Build-chunk ORDER is patched via ``iwa_write.patch_slide_builds`` only when
    it differs from the deck's current order -- the slide's own ``builds`` list and
    ``transition`` pass through verbatim. The planned movie chunks are ordered at the
    FRONT of ``buildChunks`` (after_transition at position 0). A clip slide is expected
    to carry only movie-start chunks (the gold decks' overlays are static); a build
    chunk not named in the plan means the retiming is undefined, so the write is refused
    (``ValueError``) rather than silently moving it. Requires exactly one after_transition
    entry and only known modes. Never touches chunk ``duration``, delivery, or ids --
    the single exception is a ``build_in`` entry whose ``build_in_duration`` differs from
    the clip's current build duration, where both the build's and the chunk's ``duration``
    are written so the rewritten effect plays for the source's time.

    A ``build_in`` entry additionally rewrites the clip's own auto-created build effect to
    the source build-in (plan §4 item 28) and keeps the slide's chunk order EXACTLY as
    planned (the source build order), instead of the mode ranking. It is refused unless the
    effect is in ``_BUILD_IN_EFFECTS``, the clip owns exactly one listed build, and that
    build is an ``In`` whose effect is ``apple:movie-start`` (or already the planned
    build-in, so a second run is a no-op rather than a refusal).

    Re-reads and verifies ``(automatic, referent, delay, chunkPos)`` per movie,
    ``playsAcrossSlides is False`` and, for a ``build_in`` entry, the build's
    ``effect``/``animationType``/``duration`` and the chunk's ``duration``, raising
    ``ValueError`` on any mismatch. Returns the verified state per slide:
    ``{slideId: {movieId: {...}}}``.
    """
    deck = Path(deck)
    plans = {str(k): list(v) for k, v in plans.items()}
    if not plans:
        return {}

    objects, id_to_file, _file_ids = _load_deck(deck)

    field_patches: list[tuple[str, str, dict[str, Any]]] = []
    build_plans: dict[str, dict[str, Any]] = {}
    expected_pos: dict[str, dict[str, int]] = {}
    accepted_effects: dict[str, tuple[str, ...]] = {}
    build_checks: dict[str, dict[str, dict[str, Any]]] = {}

    for slide_id, entries in plans.items():
        if not entries:
            continue
        movie_ids = [str(e.movie_id) for e in entries]
        if len(set(movie_ids)) != len(movie_ids):
            raise ValueError(f"slide {slide_id}: duplicate movie id in plan")

        modes = [e.mode for e in entries]
        unknown = sorted({m for m in modes if m not in _CLIP_TIMING_RANK})
        if unknown:
            raise ValueError(f"slide {slide_id}: unknown clip timing mode(s) {unknown}")
        if modes.count("after_transition") != 1:
            raise ValueError(
                f"slide {slide_id}: expected exactly one after_transition clip, got {modes.count('after_transition')}"
            )

        chunk_by_movie: dict[str, str] = {}
        for entry in entries:
            movie_id = str(entry.movie_id)
            obj = objects.get(movie_id)
            if obj is None or obj.get("_pbtype") != "TSD.MovieArchive":
                raise ValueError(f"{movie_id} does not resolve to a TSD.MovieArchive")
            if entry.build_in is not None:
                if entry.build_in not in _BUILD_IN_EFFECTS:
                    raise ValueError(
                        f"slide {slide_id} movie {movie_id}: build-in effect {entry.build_in!r} is not supported"
                    )
                accepted_effects[movie_id] = (*_MOVIE_START, entry.build_in)
            chunk_id, error = _movie_build_chunk(
                objects, id_to_file, movie_id, accepted_effects.get(movie_id, _MOVIE_START)
            )
            if error:
                raise ValueError(error)
            chunk_by_movie[movie_id] = chunk_id

        owning_slides = {_movie_slide(objects, movie_id) for movie_id in movie_ids}
        if len(owning_slides) != 1 or slide_id not in owning_slides:
            raise ValueError(f"slide {slide_id}: plan movies do not all resolve to that slide")

        for entry in entries:
            if entry.build_in is None:
                continue
            movie_id = str(entry.movie_id)
            build_id, error = _clip_build(objects, slide_id, movie_id)
            if error:
                raise ValueError(error)
            anim = _anim(objects, build_id)
            if anim.get("effect") not in (*_MOVIE_START, entry.build_in):
                raise ValueError(
                    f"slide {slide_id} movie {movie_id}: build {build_id} carries effect "
                    f"{anim.get('effect')!r}, expected an apple:movie-start build to rewrite"
                )
            if anim.get("animationType") != "In":
                raise ValueError(
                    f"slide {slide_id} movie {movie_id}: build {build_id} animationType "
                    f"{anim.get('animationType')!r}, expected In"
                )
            chunk = objects.get(chunk_by_movie[movie_id]) or {}
            want_duration = float(anim.get("duration") or 0.0)
            want_chunk_duration = float(chunk.get("duration") or 0.0)
            write_duration = entry.build_in_duration is not None and float(entry.build_in_duration) != want_duration
            if write_duration:
                want_duration = want_chunk_duration = float(entry.build_in_duration)
            build_checks.setdefault(slide_id, {})[movie_id] = {
                "buildId": build_id,
                "effect": entry.build_in,
                "duration": want_duration,
                "chunkDuration": want_chunk_duration,
                "writeDuration": write_duration,
            }

        slide = objects.get(slide_id) or {}
        current_chunk_ids = [str((ref or {}).get("identifier")) for ref in slide.get("buildChunks") or []]

        if slide_id in build_checks:
            ordered = list(range(len(entries)))
        else:
            ordered = sorted(range(len(entries)), key=lambda i: (_CLIP_TIMING_RANK[entries[i].mode], i))
        target_order = [chunk_by_movie[movie_ids[i]] for i in ordered]

        target_set = set(target_order)
        slots = [i for i, cid in enumerate(current_chunk_ids) if cid in target_set]
        if len(slots) != len(target_order):
            raise ValueError(f"slide {slide_id}: plan chunk(s) not all listed in buildChunks")

        non_target = [cid for cid in current_chunk_ids if cid not in target_set]
        if non_target:
            raise ValueError(
                f"slide {slide_id}: {len(non_target)} non-clip build chunk(s) present; clip-slide "
                "retiming is only defined when every build chunk is a movie-start, refusing"
            )
        new_chunk_ids = target_order

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
            chunk_fields = dict(_CLIP_TIMING_FLAGS[entry.mode], delay=float(entry.delay))
            check = (build_checks.get(slide_id) or {}).get(movie_id)
            if check is not None:
                build_fields: dict[str, Any] = {"attributes.animationAttributes.effect": check["effect"]}
                if check["writeDuration"]:
                    build_fields["attributes.animationAttributes.duration"] = check["duration"]
                    chunk_fields["duration"] = check["chunkDuration"]
                field_patches.append((check["buildId"], "KN.BuildArchive", build_fields))
            field_patches.append((chunk_id, "KN.BuildChunkArchive", chunk_fields))
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
    state = movie_autoplay_state(deck, all_movie_ids, accepted_effects)
    after_objects, after_i2f, _after_fi = _load_deck(deck) if build_checks else ({}, {}, {})

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
                or got["delay"] != float(entry.delay)
                or got["chunkPos"] != want_pos
                or got["playsAcrossSlides"] is not False
            ):
                raise ValueError(
                    f"slide {slide_id} movie {movie_id}: verify mismatch, got {got}, want {want_flags} "
                    f"delay {float(entry.delay)} at chunkPos {want_pos}"
                )
            check = (build_checks.get(slide_id) or {}).get(movie_id)
            if check is not None:
                anim = _anim(after_objects, check["buildId"])
                chunk_id, error = _movie_build_chunk(
                    after_objects, after_i2f, movie_id, accepted_effects[movie_id]
                )
                chunk = after_objects.get(chunk_id) or {}
                got_build = {
                    "effect": anim.get("effect"),
                    "animationType": anim.get("animationType"),
                    "duration": float(anim.get("duration") or 0.0),
                    "chunkDuration": float(chunk.get("duration") or 0.0),
                }
                if error or got_build != {
                    "effect": check["effect"],
                    "animationType": "In",
                    "duration": check["duration"],
                    "chunkDuration": check["chunkDuration"],
                }:
                    raise ValueError(
                        f"slide {slide_id} movie {movie_id}: build-in verify mismatch, got {error or got_build}, "
                        f"want effect {check['effect']!r} In duration {check['duration']} "
                        f"chunk duration {check['chunkDuration']}"
                    )
            slide_state[movie_id] = got
        out[slide_id] = slide_state
    return out
