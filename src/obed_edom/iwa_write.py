"""Surgical in-place geometry write for one slide of a finalized .key.

shape: write geometry.size AND naturalSize. line: length in both
geometry.size.width and naturalSize.width. group: pure translation when spec
lacks w/h; when both are given, a uniform scale (spec size / child-union size)
also writes the group's own w/h and recursively rescales every descendant's
local geometry (masked children rescale their mask too). A descendant that
can't be safely scaled (rotated mask, cross-member mask) misses the whole
group rather than partially scaling it. In-place rewrite (O_TRUNC) preserves
com.apple.macl. Positional addressing refuses the slide on reconcile_counts
mismatch.
"""
from __future__ import annotations

import copy
import io
import math
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from keynote_parser.codec import IWAFile

from obed_edom.iwa_geometry import _geom_dict, _xywha, compose_geometry
from obed_edom.iwa_kindindex import (
    derive_kind_index,
    derived_kind_counts,
    reconcile_counts,
)
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.offline_inspect import _line_direction


@dataclass
class PatchResult:
    """refused → AppleScript fallback. value_clean: obj_diffs ≤ edited archives and header_diffs == 0."""

    applied: int = 0
    missed: int = 0
    refused: bool = False
    reason: str | None = None
    target_member: str | None = None
    value_clean: bool = False
    obj_diffs: int = 0
    header_diffs: int = 0
    edited_ids: list[str] = field(default_factory=list)
    soft_fallbacks: int = 0  # group/text/masked used composed frame because reported was missing


def _find_geom(objdict: dict) -> list[str] | None:
    def rec(d: Any, path: list[str]) -> list[str] | None:
        if not isinstance(d, dict):
            return None
        if "geometry" in d and isinstance(d["geometry"], dict):
            return path + ["geometry"]
        for k, v in d.items():
            if isinstance(v, dict):
                r = rec(v, path + [k])
                if r:
                    return r
        return None

    return rec(objdict, [])


def _getp(d: dict, path: list[str]) -> Any:
    for k in path:
        d = d[k]
    return d


def _find_bezier(objdict: dict) -> dict | None:
    cur: Any = objdict
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        ps = cur.get("pathsource")
        if isinstance(ps, dict):
            bez = ps.get("bezierPathSource")
            return bez if isinstance(bez, dict) else None
        cur = cur.get("super")
    return None


def line_inverse(obj: dict, start: Any, end: Any) -> tuple[float, float, float, float]:
    """(pos_x, pos_y, length, angle_deg) inverting _line_endpoints. pos = centre − (length/2, 0)."""
    sx, sy = start[0], start[1]
    ex, ey = end[0], end[1]
    length = math.hypot(ex - sx, ey - sy)
    cx, cy = (sx + ex) / 2.0, (sy + ey) / 2.0
    ux, uy = _line_direction(obj)
    # forward: (E−S)/L = R(−theta) . (ux, uy)  =>  theta = angle(u) − angle(d)
    d_ang = math.atan2(ey - sy, ex - sx)
    u_ang = math.atan2(uy, ux)
    angle_deg = math.degrees(u_ang - d_ang) % 360.0
    return (cx - length / 2.0, cy, length, angle_deg)


def bridge_kind_index(kind: str, wall_kind_index: int, hide_specs: list[dict]) -> int:
    """Wall kindIndex → saved kindIndex after deleteHides (same-kind hides with lower index)."""
    lower = sum(
        1
        for h in hide_specs
        if str(h.get("kind")) == kind and int(h.get("kindIndex", 0)) < wall_kind_index
    )
    return wall_kind_index - lower


def expected_base_counts(source_counts: dict[str, int], specs: list[dict]) -> dict[str, int]:
    """Saved-deck per-kind counts = source-derived minus role=hide. Mismatch refuses the slide."""
    hides: dict[str, int] = {}
    for s in specs:
        if s.get("role") == "hide":
            k = str(s.get("kind"))
            hides[k] = hides.get(k, 0) + 1
    return {k: v - hides.get(k, 0) for k, v in source_counts.items()}


def _shape_fields(rec: dict, spec: dict) -> list[tuple[str, dict]]:
    fields: dict[str, float] = {}
    if spec.get("x") is not None:
        fields["pos_x"] = float(spec["x"])
    if spec.get("y") is not None:
        fields["pos_y"] = float(spec["y"])
    if spec.get("w") is not None:  # size to BOTH geometry.size AND naturalSize
        fields["size_w"] = float(spec["w"])
        fields["natural_w"] = float(spec["w"])
    if spec.get("h") is not None:
        fields["size_h"] = float(spec["h"])
        fields["natural_h"] = float(spec["h"])
    return [(rec["id"], fields)] if fields else []


def _line_fields(rec: dict, obj: dict, spec: dict) -> list[tuple[str, dict]]:
    start, end = spec.get("start"), spec.get("end")
    if start is None or end is None:
        return []
    px, py, length, angle = line_inverse(obj, start, end)
    # geometry.size.width feeds the offline reader; naturalSize.width is what Keynote renders.
    return [(rec["id"], {
        "pos_x": px, "pos_y": py, "angle": angle,
        "size_w": length, "natural_w": length,
    })]


def _text_fields(rec: dict, spec: dict, reported: list[float],
                 stored: tuple[float, float, float, float, float]) -> list[tuple[str, dict]]:
    fields: dict[str, float] = {}
    if spec.get("x") is not None:  # left-aligned autosize x is exact absolute
        fields["pos_x"] = float(spec["x"])
    if spec.get("y") is not None:  # stored y is the vertical centre: move it by the delta
        fields["pos_y"] = stored[1] + (float(spec["y"]) - reported[1])
    if spec.get("w") is not None:  # soft: only a reported delta (real size not offline)
        fields["size_w"] = stored[2] + (float(spec["w"]) - reported[2])
    if spec.get("h") is not None:
        fields["size_h"] = stored[3] + (float(spec["h"]) - reported[3])
    return [(rec["id"], fields)] if fields else []


def _group_fields(rec: dict, spec: dict, reported: list[float],
                  stored: tuple[float, float, float, float, float],
                  sx: float, sy: float, write_size: bool) -> list[tuple[str, dict]]:
    """Own frame: origin moved so the (scaled) child union lands on spec; size = stored*s.

    sx=sy=1, write_size=False degenerates to the old pure-translation rule.
    """
    fields: dict[str, float] = {}
    if spec.get("x") is not None:
        fields["pos_x"] = float(spec["x"]) + (stored[0] - reported[0]) * sx
    if spec.get("y") is not None:
        fields["pos_y"] = float(spec["y"]) + (stored[1] - reported[1]) * sy
    if write_size:
        fields["size_w"] = stored[2] * sx
        fields["size_h"] = stored[3] * sy
    return [(rec["id"], fields)] if fields else []


def _group_child_scale_ops(
    group_obj: dict, objects: dict[str, dict], sx: float, sy: float,
    id_to_file: dict[str, str], target_member: str,
) -> tuple[list[tuple[str, dict]], bool]:
    """Recursively rescale a group's descendants (parent-relative local geometry) by (sx, sy).

    ok=False refuses the WHOLE group: an unresolved child, a rotated masked
    child/mask, a mask outside target_member, or ANY rotated child under an
    anisotropic scale (sx!=sy would shear it — angle is preserved, not settable).
    """
    anisotropic = abs(sx - sy) > 1e-3 * max(abs(sx), abs(sy), 1.0)
    ops: list[tuple[str, dict]] = []
    for cref in group_obj.get("children") or []:
        child_id = cref.get("identifier")
        if child_id is None:
            continue
        child_id = str(child_id)
        child = objects.get(child_id)
        if not child:
            return ([], False)
        cx, cy, cw, ch, ca = _xywha(_geom_dict(child))
        if ca % 360.0 and anisotropic:
            return ([], False)
        pbtype = child.get("_pbtype")

        if pbtype == "TSD.GroupArchive":
            ops.append((child_id, {
                "pos_x": cx * sx, "pos_y": cy * sy,
                "size_w": cw * sx, "size_h": ch * sy,
            }))
            sub_ops, ok = _group_child_scale_ops(child, objects, sx, sy, id_to_file, target_member)
            if not ok:
                return ([], False)
            ops.extend(sub_ops)
            continue

        mask_ref = (child.get("mask") or {}).get("identifier")
        if pbtype in ("TSD.ImageArchive", "TSD.MovieArchive") and mask_ref is not None:
            mask_id = str(mask_ref)
            mask_obj = objects.get(mask_id)
            if not mask_obj or id_to_file.get(mask_id) != target_member:
                return ([], False)
            mx, my, mw, mh, ma = _xywha(_geom_dict(mask_obj))
            if ca % 360.0 or ma % 360.0:
                return ([], False)
            ops.append((mask_id, {
                "pos_x": mx * sx, "pos_y": my * sy,
                "size_w": mw * sx, "size_h": mh * sy,
            }))

        ops.append((child_id, {
            "pos_x": cx * sx, "pos_y": cy * sy,
            "size_w": cw * sx, "size_h": ch * sy,
            "natural_w": cw * sx, "natural_h": ch * sy,
        }))
    return (ops, True)


def _masked_image_fields(rec: dict, obj: dict, objects: dict[str, dict], spec: dict,
                         reported: list[float]) -> tuple[list[tuple[str, dict]], str | None]:
    """TENTATIVE. Move/size the mask so image_pos+mask_pos==target; scale image by crop ratio (unverified)."""
    mask_ref = (obj.get("mask") or {}).get("identifier")
    if mask_ref is None:
        return ([], None)
    mask_id = str(mask_ref)
    mask_obj = objects.get(mask_id)
    if not mask_obj:
        return ([], None)
    fx, fy, fw, fh, fa = _xywha(_geom_dict(obj))
    _mx, _my, mw, mh, ma = _xywha(_geom_dict(mask_obj))
    # Axis-aligned crop only; refuse rotated image/mask rather than mis-place.
    if fa % 360.0 or ma % 360.0:
        return ([], mask_id)
    tx = float(spec["x"]) if spec.get("x") is not None else reported[0]
    ty = float(spec["y"]) if spec.get("y") is not None else reported[1]
    tw = float(spec["w"]) if spec.get("w") is not None else mw
    th = float(spec["h"]) if spec.get("h") is not None else mh
    ops: list[tuple[str, dict]] = [
        (mask_id, {"pos_x": tx - fx, "pos_y": ty - fy, "size_w": tw, "size_h": th}),
    ]
    # Scale image by crop ratio (tentative). Guard /0.
    ratio_w = tw / mw if mw else 1.0
    ratio_h = th / mh if mh else 1.0
    ops.append((rec["id"], {"size_w": fw * ratio_w, "size_h": fh * ratio_h}))
    return (ops, mask_id)


def _apply_geom_fields(archive_obj: dict, fields: dict) -> None:
    if any(k in fields for k in ("pos_x", "pos_y", "size_w", "size_h", "angle")):
        gp = _find_geom(archive_obj)
        if gp is not None:
            geom = _getp(archive_obj, gp)
            if "pos_x" in fields or "pos_y" in fields:
                pos = geom.setdefault("position", {})
                if "pos_x" in fields:
                    pos["x"] = float(fields["pos_x"])
                if "pos_y" in fields:
                    pos["y"] = float(fields["pos_y"])
            if "size_w" in fields or "size_h" in fields:
                size = geom.setdefault("size", {})
                if "size_w" in fields:
                    size["width"] = float(fields["size_w"])
                if "size_h" in fields:
                    size["height"] = float(fields["size_h"])
            if "angle" in fields:
                geom["angle"] = float(fields["angle"])
    if "natural_w" in fields or "natural_h" in fields:
        bez = _find_bezier(archive_obj)
        if bez is not None:
            ns = bez.setdefault("naturalSize", {})
            if "natural_w" in fields:
                ns["width"] = float(fields["natural_w"])
            if "natural_h" in fields:
                ns["height"] = float(fields["natural_h"])


def _spec_bears_geometry(spec: dict) -> bool:
    if spec.get("w") is not None or spec.get("h") is not None:
        return True
    if spec.get("x") is not None and spec.get("y") is not None:
        return True
    return spec.get("start") is not None and spec.get("end") is not None


def _resolve_positional(spec: dict, comp_by_key: dict, hide_specs: list[dict]) -> dict | None:
    kind = str(spec.get("kind"))
    wall_ki = int(spec.get("kindIndex", 0))
    saved_ki = bridge_kind_index(kind, wall_ki, hide_specs)
    return comp_by_key.get((kind, saved_ki))


def _resolve_identity(spec: dict, comp_by_id: dict) -> dict | None:
    # Address by surviving source drawable id (immune to deleteHides).
    sid = spec.get("source_id") or spec.get("id")
    return comp_by_id.get(str(sid)) if sid is not None else None


def patch_slide_geometry(
    saved_deck: Path | str,
    slide_number: int,
    specs: list[dict],
    *,
    reported: dict | None = None,
    address: str = "positional",
    source_counts: dict[str, int] | None = None,
    require_reconcile: bool = False,
) -> PatchResult:
    """Write slide_number geometry in place. Positional + source_counts: refuse on reconcile_counts mismatch."""
    if require_reconcile and source_counts is None:
        return PatchResult(refused=True, reason="reconcile required but source_counts missing")
    saved_deck = Path(saved_deck)
    reported = reported or {}
    objects, id_to_file, _file_ids = _load_deck(saved_deck)

    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        return PatchResult(refused=True, reason=f"slide {slide_number} out of range (deck has {len(order)})")
    slide_id = order[slide_number - 1][0]
    slide = objects.get(slide_id)
    if not slide:
        return PatchResult(refused=True, reason=f"slide archive {slide_id} not decoded")

    records = derive_kind_index(slide, objects)
    comp = compose_geometry(slide, objects)
    comp_by_key = {(r["kind"], r["kindIndex"]): r for r in comp}
    comp_by_id = {r["id"]: r for r in comp}

    members = {id_to_file.get(r["id"]) for r in comp if r["id"] in id_to_file}
    members.discard(None)
    if len(members) != 1:
        return PatchResult(refused=True, reason=f"slide drawables span {sorted(members)} (need exactly one member)")
    target_member = next(iter(members))

    if address == "positional" and source_counts is not None:
        base = expected_base_counts(source_counts, specs)
        mismatched = reconcile_counts(derived_kind_counts(records), base)
        if mismatched:
            return PatchResult(
                refused=True,
                reason=f"reconcile mismatch on kinds {mismatched}; refusing offline write",
                target_member=target_member,
            )

    hide_specs = [s for s in specs if s.get("role") == "hide"]

    edits: dict[str, dict] = {}
    missed = 0
    soft_fallbacks = 0
    for spec in specs:
        if spec.get("role") == "hide" or not _spec_bears_geometry(spec):
            continue
        if address == "identity":
            rec = _resolve_identity(spec, comp_by_id)
        else:
            rec = _resolve_positional(spec, comp_by_key, hide_specs)
        if rec is None:
            missed += 1
            continue
        kind = rec["kind"]
        obj = objects.get(rec["id"]) or {}
        stored = _xywha(_geom_dict(obj))
        saved_ki = rec["kindIndex"]
        masked = kind in ("image", "movie") and (obj.get("mask") or {}).get("identifier") is not None
        have_reported = (kind, saved_ki) in reported
        rep = list(reported.get((kind, saved_ki)) or [rec["x"], rec["y"], rec["w"], rec["h"]])

        if kind == "line":
            ops = _line_fields(rec, obj, spec)
        elif kind == "shape":
            ops = _shape_fields(rec, spec)
        elif kind == "group":
            spec_w, spec_h = spec.get("w"), spec.get("h")
            rep_w, rep_h = rep[2], rep[3]
            scaled = spec_w is not None and spec_h is not None and rep_w > 0 and rep_h > 0
            sx = float(spec_w) / rep_w if scaled else 1.0
            sy = float(spec_h) / rep_h if scaled else 1.0
            ops = _group_fields(rec, spec, rep, stored, sx, sy, scaled)
            if scaled:
                child_ops, ok = _group_child_scale_ops(obj, objects, sx, sy, id_to_file, target_member)
                if not ok:
                    missed += 1
                    continue
                ops = ops + child_ops
        elif kind == "text":
            ops = _text_fields(rec, spec, rep, stored)
        elif kind in ("image", "movie"):
            if masked:
                ops, mask_id = _masked_image_fields(rec, obj, objects, spec, rep)
                # Unresolved, cross-member, or rotated mask: miss rather than mis-write.
                if not ops or mask_id is None or id_to_file.get(mask_id) != target_member:
                    missed += 1
                    continue
            else:  # unmasked image/movie: plain frame, same as a shape
                ops = _shape_fields(rec, spec)
        else:
            missed += 1
            continue

        # Soft class used composed frame (no bulk reported): count for the 0-fallback gate.
        if (kind in ("group", "text") or masked) and not have_reported and ops:
            soft_fallbacks += 1

        for obj_id, fields in ops:
            if not fields:
                continue
            edits.setdefault(obj_id, {}).update(fields)

    if not edits:
        return PatchResult(applied=0, missed=missed, target_member=target_member,
                           value_clean=True, soft_fallbacks=soft_fallbacks)

    with zipfile.ZipFile(saved_deck) as zf:
        buf = zf.read(target_member)
    decoded = IWAFile.from_buffer(buf, target_member).to_dict()
    patched = copy.deepcopy(decoded)
    applied = 0
    for ch in patched["chunks"]:
        for arch in ch["archives"]:
            aid = str(arch["header"]["identifier"])
            if aid not in edits:
                continue
            for o in arch.get("objects") or []:
                _apply_geom_fields(o, edits[aid])
                applied += 1
                break

    new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
    reparsed = IWAFile.from_buffer(new_member, target_member).to_dict()
    obj_diffs = 0
    header_diffs = 0
    for c0, c1 in zip(decoded["chunks"], reparsed["chunks"]):
        for a0, a1 in zip(c0["archives"], c1["archives"]):
            if (a0.get("objects") or []) != (a1.get("objects") or []):
                obj_diffs += 1
            if a0["header"] != a1["header"]:
                header_diffs += 1
    # No-op edits can yield obj_diffs < len(edits); collateral (obj_diffs > len(edits)) is the fail.
    value_clean = obj_diffs <= len(edits) and header_diffs == 0

    # In-place O_TRUNC preserves inode + com.apple.macl; a new file is refused by Keynote.
    out = io.BytesIO()
    with zipfile.ZipFile(saved_deck) as zin, zipfile.ZipFile(out, "w") as zout:
        for zi in zin.infolist():
            data = new_member if zi.filename == target_member else zin.read(zi.filename)
            zout.writestr(zi, data, compress_type=zi.compress_type)
    payload = out.getvalue()
    fd = os.open(str(saved_deck), os.O_WRONLY | os.O_TRUNC)
    try:
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
    finally:
        os.close(fd)

    return PatchResult(
        applied=applied,
        missed=missed,
        target_member=target_member,
        value_clean=value_clean,
        obj_diffs=obj_diffs,
        header_diffs=header_diffs,
        edited_ids=sorted(edits),
        soft_fallbacks=soft_fallbacks,
    )
