"""Offline poster-frame/autoplay patches for ``TSD.MovieArchive`` (reveal movies),
separate from ``iwa_write.py`` which is geometry-scoped. Same surgical
single-member-rewrite shape as ``iwa_write.patch_slide_builds``: locate the owning
member via ``id_to_file``, patch only that member, verify the re-encode touched
exactly the intended archives, and refuse (deck untouched) otherwise.
"""
from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from typing import Any

from keynote_parser.codec import IWAFile

from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_write import OfflineWriteCorrupted, _archive_diff, _rewrite_members

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
    result = _patch_archive_fields(deck, patches)
    if result["refused"] or not posters:
        return result
    return {"refused": False, "reason": None, "touched": sorted(posters), "applied": len(posters)}


def _movie_build_chunk(objects: dict, movie_id: str) -> tuple[str | None, str | None]:
    """Resolve the single ``KN.BuildChunkArchive`` for ``movie_id``'s
    ``apple:movie-start`` build. Returns ``(chunk_id, error)``; refuses (``chunk_id``
    ``None``) rather than guess when the movie has zero or multiple builds/chunks.
    """
    builds = [
        oid
        for oid, obj in objects.items()
        if obj.get("_pbtype") == "KN.BuildArchive"
        and str((obj.get("drawable") or {}).get("identifier")) == movie_id
        and ((obj.get("attributes") or {}).get("animationAttributes") or {}).get("effect") == "apple:movie-start"
    ]
    if len(builds) != 1:
        return None, f"movie {movie_id} has {len(builds)} apple:movie-start build(s)"
    build_id = builds[0]
    chunks = [
        oid
        for oid, obj in objects.items()
        if obj.get("_pbtype") == "KN.BuildChunkArchive" and str((obj.get("build") or {}).get("identifier")) == build_id
    ]
    if len(chunks) != 1:
        return None, f"movie {movie_id} build {build_id} has {len(chunks)} chunk(s)"
    return chunks[0], None


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

    objects, _id_to_file, _file_ids = _load_deck(deck)
    for oid in ids:
        obj = objects.get(oid)
        if obj is None or obj.get("_pbtype") != "TSD.MovieArchive":
            return {"refused": True, "reason": f"{oid} does not resolve to a TSD.MovieArchive", "touched": [], "applied": 0}

    patches: list[tuple[str, str, dict[str, Any]]] = []
    for movie_id in ids:
        chunk_id, error = _movie_build_chunk(objects, movie_id)
        if error:
            return {"refused": True, "reason": error, "touched": [], "applied": 0}
        patches.append((chunk_id, "KN.BuildChunkArchive", {"automatic": True}))
        patches.append((movie_id, "TSD.MovieArchive", {"playsAcrossSlides": False}))

    result = _patch_archive_fields(deck, patches)
    if result["refused"]:
        return {"refused": True, "reason": result["reason"], "touched": [], "applied": 0}
    return {"refused": False, "reason": None, "touched": ids, "applied": len(ids)}
