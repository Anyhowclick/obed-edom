"""Offline poster-frame patch for ``TSD.MovieArchive`` (reveal movies), separate from
``iwa_write.py`` which is geometry-scoped. Same surgical single-member-rewrite shape as
``iwa_write.patch_slide_builds``: locate the owning member via ``id_to_file``, patch only
that member, verify the re-encode touched exactly the intended archives, and refuse
(deck untouched) otherwise.
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
                    "hasPosterImageData": bool((obj.get("posterImageData") or {}).get("identifier")),
                    "naturalSize": (natural.get("width"), natural.get("height")),
                    "dataId": data_id,
                    "dataName": data_name,
                }
            )
    return out


def plan_movie_posters(deck: Path, targets: list[dict]) -> dict:
    """Match each ``target`` ({x,y,w,h,posterTime,name}) to exactly one composed movie
    archive frame within ``_FRAME_TOL`` px on all four of x/y/w/h. Refuses (nothing
    written -- this is planning only) on zero or ambiguous matches; this selection
    deliberately excludes full-width ``map:True`` background fly movies, whose first
    frame is already the correct poster.
    """
    archives = movie_archives(deck)
    posters: dict[str, float] = {}
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
            return {
                "refused": True,
                "reason": f"target {name!r} matched {len(matches)} movie archive(s)",
                "posters": {},
            }
        aid = matches[0]["id"]
        if aid in claimed_by:
            name = target.get("name", i)
            other = claimed_by[aid]
            return {
                "refused": True,
                "reason": f"movie archive {aid} matched both target {other!r} and target {name!r}",
                "posters": {},
            }
        claimed_by[aid] = target.get("name", i)
        posters[aid] = float(target["posterTime"])
    return {"refused": False, "reason": None, "posters": posters}


def patch_movie_posters(deck: Path, posters: dict[str, float]) -> dict:
    """Patch each named ``TSD.MovieArchive``'s ``posterTime`` in place. Modelled
    line-for-line on ``iwa_write.patch_slide_builds``: refuses (deck untouched) unless
    every id resolves to a same-member ``TSD.MovieArchive`` and the re-encode changed
    exactly the intended archive(s). Never touches ``posterImageData``/``endTime``.
    """
    deck = Path(deck)
    posters = {str(k): float(v) for k, v in posters.items()}
    if not posters:
        return {"refused": False, "reason": None, "touched": [], "applied": 0}

    objects, id_to_file, _file_ids = _load_deck(deck)
    for oid in posters:
        obj = objects.get(oid)
        if obj is None or obj.get("_pbtype") != "TSD.MovieArchive":
            return {
                "refused": True,
                "reason": f"{oid} does not resolve to a TSD.MovieArchive",
                "touched": [],
                "applied": 0,
            }

    by_member: dict[str, list[str]] = {}
    for oid in posters:
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
                        o["posterTime"] = float(posters[aid])
                        touched += 1

            if touched != len(wanted):
                return {
                    "refused": True,
                    "reason": f"expected to touch {len(wanted)} movie(s) in {member}, touched {touched}",
                    "touched": [],
                    "applied": 0,
                }

            new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
            reparsed = IWAFile.from_buffer(new_member, member).to_dict()
            removed, added, changed = _archive_diff(decoded, reparsed)
            if removed or added or not set(changed) <= wanted:
                return {
                    "refused": True,
                    "reason": f"{member}: re-encode touched fewer/other than the intended movie(s) "
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
