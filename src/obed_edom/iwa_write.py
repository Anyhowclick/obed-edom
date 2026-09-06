"""Surgical in-place geometry write across one or more slides of a finalized .key.

shape: write geometry.size AND naturalSize. line: length in both
geometry.size.width and naturalSize.width. group: pure translation when spec
lacks w/h; when both are given, a uniform scale (spec size / child-union size)
also writes the group's own w/h and recursively rescales every descendant's
local geometry (masked children rescale their mask too). A descendant that
can't be safely scaled (rotated mask, cross-member mask) misses the whole
group rather than partially scaling it. ``patch_deck_geometry`` resolves every
slide's edits (pure, no I/O), then does exactly ONE zip rewrite touching only
the edited members. In-place rewrite (O_TRUNC) preserves com.apple.macl and
never ``os.replace``s. Positional addressing refuses a slide on
reconcile_counts mismatch; refusal is always per slide.
"""
from __future__ import annotations

import copy
import math
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from keynote_parser.codec import IWAFile

from obed_edom.iwa_builds import _contains_identifier
from obed_edom.iwa_geometry import _geom_dict, _is_rotated, _path_source, _xywha, compose_geometry
from obed_edom.iwa_kindindex import (
    derive_kind_index,
    derived_kind_counts,
    reconcile_counts,
)
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.offline_inspect import _line_direction


class OfflineWriteRefused(Exception):
    """Raised by ``_rewrite_members`` before any write: low disk space, or an ``edits``
    key naming a member the deck doesn't have. The deck is untouched."""


class OfflineWriteCorrupted(Exception):
    """Raised by ``_rewrite_members`` when the deck's O_TRUNC copy-back itself failed.

    The deck IS truncated/invalid at this point — never map this to a refused
    ``PatchResult``; it must propagate uncaught so the caller knows to recover.
    """


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
    missed_specs: list[dict] = field(default_factory=list)  # specs the patcher could not place


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


# naturalSize is a plain size for these; the rounded-rect `scalar` scales WITH naturalSize
# under a UNIFORM resize (mask 20557359: scalar ratio 189.00002/47.236244 == the exact
# 278.97/69.72 naturalSize ratio; shape 20554351 likewise) but stays put under an
# anisotropic one (the 29 invariant cases sampled were all anisotropic; see
# `_write_natural_size`). editableBezier needs its nodes rescaled too;
# callout/connectionLine/absent cannot be written at all.
_NATURAL_PLAIN_KINDS = frozenset({"bezierPathSource", "scalarPathSource", "pointPathSource"})


def _natural_writable(obj: dict, *, both_axes: bool) -> bool:
    """Can this object's render-derived size be kept in sync with a geometry.size write?

    Image/movie carry ``originalSize`` (a size sibling of ``geometry``, always == the
    frame in production). Their own ``naturalSize`` is the MEDIA's pixel size (7680x1080,
    4032x3024, ...) -- identical in both decks and NEVER written. Shapes/masks carry it
    under the path source.
    """
    if "originalSize" in obj:
        return True
    found = _path_source(obj)
    if found is None:
        return False
    key, sub = found
    if key in _NATURAL_PLAIN_KINDS:
        return True
    if key != "editableBezierPathSource":
        return False
    ns = sub.get("naturalSize") or {}
    return (both_axes and float(ns.get("width") or 0.0) > 0.0 and float(ns.get("height") or 0.0) > 0.0)


def _natural_unwritable(obj: dict, spec: dict) -> bool:
    """A RESIZE whose derived size can't be written is a hard miss; position-only is fine."""
    if spec.get("w") is None and spec.get("h") is None:
        return False
    return not _natural_writable(obj, both_axes=spec.get("w") is not None and spec.get("h") is not None)


def _scale_path_nodes(sub: dict, rx: float, ry: float) -> None:
    """Nodes live in naturalSize space and scale about the ORIGIN -- measured on 20554069
    /20541783: prod nodes == offline nodes * (662/165.52277, 92/23), nodePoint and BOTH
    control points alike, with (0,0) staying at (0,0)."""
    for subpath in sub.get("subpaths") or []:
        for node in subpath.get("nodes") or []:
            for key in ("nodePoint", "inControlPoint", "outControlPoint"):
                pt = node.get(key)
                if isinstance(pt, dict):
                    pt["x"] = float(pt.get("x") or 0.0) * rx
                    pt["y"] = float(pt.get("y") or 0.0) * ry


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


def bridge_specs_kindindex(specs: list[dict]) -> list[dict]:
    """Rewrite non-hide specs' WALL kindIndex to saved (post-``deleteHides``) kindIndex.

    Same bridge ``_resolve_positional`` applies during a patch; useful to anyone (e.g. an
    A' AppleScript reference) addressing the saved deck by wall kindIndex directly. No-op
    when the slide has no hides, or when every deleted hide sits above all survivors.
    """
    hide_specs = [s for s in specs if s.get("role") == "hide"]
    if not hide_specs:
        return specs
    bridged: list[dict] = []
    for s in specs:
        if s.get("role") == "hide" or s.get("kindIndex") is None:
            bridged.append(s)
            continue
        b = dict(s)
        b["kindIndex"] = bridge_kind_index(str(s.get("kind") or ""), int(s["kindIndex"]), hide_specs)
        bridged.append(b)
    return bridged


def expected_base_counts(source_counts: dict[str, int], specs: list[dict]) -> dict[str, int]:
    """Saved-deck per-kind counts = source-derived minus role=hide. Mismatch refuses the slide."""
    hides: dict[str, int] = {}
    for s in specs:
        if s.get("role") == "hide":
            k = str(s.get("kind"))
            hides[k] = hides.get(k, 0) + 1
    return {k: v - hides.get(k, 0) for k, v in source_counts.items()}


def _rotated_anchor_delta(w: float, h: float, angle: float) -> tuple[float, float]:
    """Stored unrotated TL minus rotated-AABB TL: the inverse of `iwa_geometry._frame_rect`.

    Gated on the reader's own `_is_rotated`, not on a bare angle test: below `_ANGLE_EPS`
    the reader returns the stored position verbatim, so any correction there is pure error.
    """
    if not _is_rotated(angle):
        return (0.0, 0.0)
    theta = math.radians(angle)
    big_w = abs(w * math.cos(theta)) + abs(h * math.sin(theta))
    big_h = abs(w * math.sin(theta)) + abs(h * math.cos(theta))
    return ((big_w - w) / 2.0, (big_h - h) / 2.0)


def _shape_fields(rec: dict, spec: dict,
                  stored: tuple[float, float, float, float, float]) -> list[tuple[str, dict]]:
    """Spec x/y is the ROTATED AABB top-left the reader reports; stored position is the
    unrotated top-left it rotates from. Correct with the POST-write size (spec w/h where the
    spec resizes, stored otherwise) and the stored angle -- shape/image writes never set angle.
    """
    fields: dict[str, float] = {}
    w = float(spec["w"]) if spec.get("w") is not None else stored[2]
    h = float(spec["h"]) if spec.get("h") is not None else stored[3]
    dx, dy = _rotated_anchor_delta(w, h, stored[4])
    if spec.get("x") is not None:
        fields["pos_x"] = float(spec["x"]) + dx
    if spec.get("y") is not None:
        fields["pos_y"] = float(spec["y"]) + dy
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
    """A stored width or height of ``0.0`` never reaches this function (the caller hard-misses
    it to the AppleScript fallback -- ``naturalSize`` is Keynote's render cache and only a
    live write refreshes it). ``naturalSize`` tracks ``geometry.size`` on both axes.
    """
    fields: dict[str, float] = {}
    if spec.get("x") is not None:  # left-aligned autosize x is exact absolute
        fields["pos_x"] = float(spec["x"])
    if spec.get("y") is not None:  # stored y is the vertical centre: move it by the delta
        fields["pos_y"] = stored[1] + (float(spec["y"]) - reported[1])
    if spec.get("w") is not None and stored[2] != 0.0:  # autosize width has no writable frame
        fields["size_w"] = stored[2] + (float(spec["w"]) - reported[2])
        fields["natural_w"] = fields["size_w"]
    if spec.get("h") is not None and stored[3] != 0.0:
        fields["size_h"] = stored[3] + (float(spec["h"]) - reported[3])
        fields["natural_h"] = fields["size_h"]
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
            if not _natural_writable(mask_obj, both_axes=True):
                return ([], False)
            ops.append((mask_id, {
                "pos_x": mx * sx, "pos_y": my * sy,
                "size_w": mw * sx, "size_h": mh * sy,
                "natural_w": mw * sx, "natural_h": mh * sy,
            }))

        if pbtype == "TSWP.ShapeInfoArchive" and child.get("isTextBox") and (cw == 0.0 or ch == 0.0):
            return ([], False)  # autosize text child: Keynote must lay it out; whole group misses

        if not _natural_writable(child, both_axes=True):
            return ([], False)
        ops.append((child_id, {
            "pos_x": cx * sx, "pos_y": cy * sy,
            "size_w": cw * sx, "size_h": ch * sy,
            "natural_w": cw * sx, "natural_h": ch * sy,
        }))
    return (ops, True)


# Identity test: the stricter of 1 px and 0.5 % of the frame on each axis. Both bounds are
# needed -- 0.5 % alone lets a 1.2 %-of-23 px crop through, 1 px alone lets a 1 px crop on a
# 3840 px photo through. Production, offline slides: 70 top-level media pass, 70 real crops
# are refused.
_MASK_IDENTITY_PX = 1.0
_MASK_IDENTITY_REL = 0.005


def _is_identity_mask(fw: float, fh: float, fa: float, mx: float, my: float,
                      mw: float, mh: float, ma: float) -> bool:
    """Mask covers the whole image at the origin: there is no crop to redistribute."""
    if _is_rotated(fa) or _is_rotated(ma) or mw <= 0.0 or mh <= 0.0:
        return False
    tol_x = min(_MASK_IDENTITY_PX, _MASK_IDENTITY_REL * max(fw, 1.0))
    tol_y = min(_MASK_IDENTITY_PX, _MASK_IDENTITY_REL * max(fh, 1.0))
    return (abs(mx) <= tol_x and abs(my) <= tol_y and abs(mw - fw) <= tol_x and abs(mh - fh) <= tol_y)


def _masked_media_fields(rec: dict, obj: dict, objects: dict[str, dict], spec: dict,
                         reported: list[float]) -> tuple[list[tuple[str, dict]], str | None, bool]:
    """Place a masked image/movie whose mask is an IDENTITY window; REFUSE any real crop.

    Production never displaces a mask: the IMAGE frame moves and the mask stays put (325/325
    masks have naturalSize == their own size; the composed rect is image_pos + mask_pos).
    The transform below is exact for ANY mask -- image pos = target - mask_pos*s, both sizes
    scaled by s = target/mask -- but for a real crop we cannot prove offline that Keynote
    redistributes it this way, so only the identity case (no crop, 100 %/0 % split, verified
    against 70 production objects) is written. ok=False => hard miss.
    """
    mask_ref = (obj.get("mask") or {}).get("identifier")
    if mask_ref is None:
        return ([], None, False)
    mask_id = str(mask_ref)
    mask_obj = objects.get(mask_id)
    if not mask_obj:
        return ([], None, False)
    _fx, _fy, fw, fh, fa = _xywha(_geom_dict(obj))
    mx, my, mw, mh, ma = _xywha(_geom_dict(mask_obj))
    if not _is_identity_mask(fw, fh, fa, mx, my, mw, mh, ma):
        return ([], mask_id, False)
    if not _natural_writable(mask_obj, both_axes=True) or not _natural_writable(obj, both_axes=True):
        return ([], mask_id, False)
    tx = float(spec["x"]) if spec.get("x") is not None else reported[0]
    ty = float(spec["y"]) if spec.get("y") is not None else reported[1]
    tw = float(spec["w"]) if spec.get("w") is not None else mw
    th = float(spec["h"]) if spec.get("h") is not None else mh
    sx, sy = tw / mw, th / mh
    return ([
        (mask_id, {"pos_x": mx * sx, "pos_y": my * sy, "size_w": tw, "size_h": th,
                   "natural_w": tw, "natural_h": th}),
        (rec["id"], {"pos_x": tx - mx * sx, "pos_y": ty - my * sy, "size_w": fw * sx, "size_h": fh * sy,
                     "natural_w": fw * sx, "natural_h": fh * sy}),
    ], mask_id, True)


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
        _write_natural_size(archive_obj, fields)


def _scale_rect_scalar(sub: dict, fields: dict) -> None:
    """Rounded-rect `scalar` rides naturalSize under a UNIFORM resize, stays put otherwise
    (module-top comment on `_NATURAL_PLAIN_KINDS` has the measured evidence)."""
    old = sub.get("naturalSize") or {}
    ow = float(old.get("width") or 0.0)
    oh = float(old.get("height") or 0.0)
    if ow <= 0.0 or oh <= 0.0 or "natural_w" not in fields or "natural_h" not in fields:
        return
    if "scalar" not in sub:
        return
    rx = float(fields["natural_w"]) / ow
    ry = float(fields["natural_h"]) / oh
    if abs(rx - ry) <= 1e-3 * max(rx, ry):
        sub["scalar"] = float(sub["scalar"]) * rx


def _write_natural_size(archive_obj: dict, fields: dict) -> None:
    """Image/movie -> ``originalSize``; everything else -> the path source's naturalSize.

    editableBezier additionally rescales its nodes off the PRE-write naturalSize, read from
    the same on-disk dict ``_patch_member`` is mutating.
    """
    if "originalSize" in archive_obj:
        size = archive_obj.setdefault("originalSize", {})
    else:
        found = _path_source(archive_obj)
        if found is None:
            return
        key, sub = found
        if key == "editableBezierPathSource":
            old = sub.get("naturalSize") or {}
            ow = float(old.get("width") or 0.0)
            oh = float(old.get("height") or 0.0)
            if ow <= 0.0 or oh <= 0.0 or "natural_w" not in fields or "natural_h" not in fields:
                return
            _scale_path_nodes(sub, float(fields["natural_w"]) / ow, float(fields["natural_h"]) / oh)
        elif key == "scalarPathSource":
            _scale_rect_scalar(sub, fields)
        elif key not in _NATURAL_PLAIN_KINDS:
            return
        size = sub.setdefault("naturalSize", {})
    if "natural_w" in fields:
        size["width"] = float(fields["natural_w"])
    if "natural_h" in fields:
        size["height"] = float(fields["natural_h"])


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


def _slide_edits(
    slide_number: int,
    specs: list[dict],
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    order: list[tuple[str, bool]],
    *,
    reported: dict | None = None,
    address: str = "positional",
    source_counts: dict[str, int] | None = None,
    require_reconcile: bool = False,
) -> tuple[str | None, dict[str, dict], int, list[dict], str | None]:
    """Pure, no-I/O resolution of one slide's edits against an already-loaded deck.

    Returns (target_member, edits, soft_fallbacks, missed_specs, refuse_reason).
    ``refuse_reason`` set => edits is always {}. Positional + source_counts: refuse on
    reconcile_counts mismatch. (``len(edits)`` is the applied-object count; the caller's
    ``_patch_member`` recomputes it for real after the actual archive mutation.)
    """
    if require_reconcile and source_counts is None:
        return (None, {}, 0, [], "reconcile required but source_counts missing")
    reported = reported or {}

    if not (1 <= slide_number <= len(order)):
        return (None, {}, 0, [], f"slide {slide_number} out of range (deck has {len(order)})")
    slide_id = order[slide_number - 1][0]
    slide = objects.get(slide_id)
    if not slide:
        return (None, {}, 0, [], f"slide archive {slide_id} not decoded")

    records = derive_kind_index(slide, objects)
    comp = compose_geometry(slide, objects)
    comp_by_key = {(r["kind"], r["kindIndex"]): r for r in comp}
    comp_by_id = {r["id"]: r for r in comp}

    members = {id_to_file.get(r["id"]) for r in comp if r["id"] in id_to_file}
    members.discard(None)
    if len(members) != 1:
        return (None, {}, 0, [], f"slide drawables span {sorted(members)} (need exactly one member)")
    target_member = next(iter(members))

    if address == "positional" and source_counts is not None:
        base = expected_base_counts(source_counts, specs)
        derived_counts = derived_kind_counts(records)
        mismatched = reconcile_counts(derived_counts, base)
        if mismatched:
            return (target_member, {}, 0, [],
                    f"reconcile mismatch on kinds {mismatched} (derived {derived_counts} vs expected {base})")

    hide_specs = [s for s in specs if s.get("role") == "hide"]

    edits: dict[str, dict] = {}
    missed_specs: list[dict] = []
    soft_fallbacks = 0
    for spec in specs:
        if spec.get("role") == "hide" or not _spec_bears_geometry(spec):
            continue
        if address == "identity":
            rec = _resolve_identity(spec, comp_by_id)
        else:
            rec = _resolve_positional(spec, comp_by_key, hide_specs)
        if rec is None:
            missed_specs.append(spec)
            continue
        kind = rec["kind"]
        obj = objects.get(rec["id"]) or {}
        stored = _xywha(_geom_dict(obj))
        saved_ki = rec["kindIndex"]
        masked = kind in ("image", "movie") and (obj.get("mask") or {}).get("identifier") is not None
        have_reported = (kind, saved_ki) in reported
        rep = list(reported.get((kind, saved_ki)) or [rec["x"], rec["y"], rec["w"], rec["h"]])

        if kind == "line":
            if _natural_unwritable(obj, spec):
                missed_specs.append(spec)
                continue
            ops = _line_fields(rec, obj, spec)
        elif kind == "shape":
            if _natural_unwritable(obj, spec):
                missed_specs.append(spec)
                continue
            ops = _shape_fields(rec, spec, stored)
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
                    missed_specs.append(spec)
                    continue
                ops = ops + child_ops
        elif kind == "text":
            # An autosize width or height (the 0.0 sentinel on either axis) is a Keynote
            # render cache only the live app refreshes -- hard miss to the AppleScript fallback.
            if stored[2] == 0.0 or stored[3] == 0.0:
                missed_specs.append(spec)
                continue
            wants_h = spec.get("h") is not None
            if (spec.get("w") is not None or wants_h) and not _natural_writable(obj, both_axes=wants_h):
                missed_specs.append(spec)
                continue
            ops = _text_fields(rec, spec, rep, stored)
        elif kind in ("image", "movie"):
            if masked:
                ops, mask_id, ok = _masked_media_fields(rec, obj, objects, spec, rep)
                # Cropped, rotated, unresolved or cross-member mask: miss, never mis-write.
                if not ok or mask_id is None or id_to_file.get(mask_id) != target_member:
                    missed_specs.append(spec)
                    continue
            else:  # unmasked image/movie: plain frame, same as a shape
                if _natural_unwritable(obj, spec):
                    missed_specs.append(spec)
                    continue
                ops = _shape_fields(rec, spec, stored)
        else:
            missed_specs.append(spec)
            continue

        # Soft class used composed/reported frame: count for the 0-fallback gate. Masked
        # images only fall back to `reported` for x/y (never w/h — those read the mask).
        used_reported = kind in ("group", "text") or (
            masked and (spec.get("x") is None or spec.get("y") is None)
        )
        if used_reported and not have_reported and ops:
            soft_fallbacks += 1

        for obj_id, fields in ops:
            if not fields:
                continue
            edits.setdefault(obj_id, {}).update(fields)

    return (target_member, edits, soft_fallbacks, missed_specs, None)


def _patch_member(zf: zipfile.ZipFile, member: str, edits: dict[str, dict]) -> tuple[bytes, int, int, int]:
    """Decode -> apply -> re-encode -> reparse -> diff ONE member, off an already-open
    ``ZipFile`` (the caller hoists one handle across every member). (new_bytes, applied,
    obj_diffs, header_diffs)."""
    buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
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
    reparsed = IWAFile.from_buffer(new_member, member).to_dict()
    obj_diffs = 0
    header_diffs = 0
    for c0, c1 in zip(decoded["chunks"], reparsed["chunks"]):
        for a0, a1 in zip(c0["archives"], c1["archives"]):
            if (a0.get("objects") or []) != (a1.get("objects") or []):
                obj_diffs += 1
            if a0["header"] != a1["header"]:
                header_diffs += 1
    return new_member, applied, obj_diffs, header_diffs


class _RawNameZipInfo(zipfile.ZipInfo):
    """ZipInfo whose central-directory/local-header filename bytes are frozen to
    ``_raw_name`` instead of re-encoded from ``self.filename``. ``ZipFile._open_to_write``
    resets ``flag_bits`` to 0 before calling ``_encodeFilenameFlags``, so this must not
    try to read back an "original" flag from ``self.flag_bits`` at encode time — it just
    keeps the standard machinery from ALSO setting bit 11 for a name we're freezing.
    """

    __slots__ = ("_raw_name",)

    def _encodeFilenameFlags(self):
        raw = getattr(self, "_raw_name", None)
        return (raw, self.flag_bits) if raw is not None else super()._encodeFilenameFlags()


_ZIPINFO_COPY_ATTRS = (
    "compress_type", "comment", "extra", "create_system", "create_version",
    "extract_version", "reserved", "flag_bits", "volume", "internal_attr",
    "external_attr", "CRC", "compress_size", "file_size",
)


def _preserve_raw_name(zi: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """Copy of ``zi`` for writing. Keynote writes some ``Data/*`` member names as raw
    UTF-8 bytes with the UTF-8 flag (bit 11) CLEAR; Python decodes those as CP437
    (mojibake), and a naive rewrite re-encodes that mojibake as UTF-8 + sets bit 11 —
    different bytes, so Keynote drops the member as damaged. When the ORIGINAL flag
    bit 11 was clear and the decoded name is non-ASCII (the mis-decode signature),
    freeze the exact original bytes; ASCII names and genuinely UTF-8-flagged names
    round-trip correctly through the standard path already.
    """
    info = _RawNameZipInfo(zi.filename, zi.date_time)
    for attr in _ZIPINFO_COPY_ATTRS:
        setattr(info, attr, getattr(zi, attr))
    if zi.flag_bits & 0x800 == 0 and not zi.filename.isascii():
        info._raw_name = zi.filename.encode("cp437")
    return info


def _rewrite_members(deck: Path, edits: dict[str, bytes]) -> None:
    """Stream every zip member into a same-volume temp file (peak RAM = largest member,
    not the whole deck), then copy the bytes back INTO THE ORIGINAL INODE via ``open(deck,
    "wb")`` (O_TRUNC on the SAME inode; never ``os.replace``, which would lose the inode
    and ``com.apple.macl``). Unedited members stream through ``ZipFile.open`` (keeps
    date_time/extra/compress_type); CPython resets a zero ``external_attr`` to
    ``0o600 << 16`` on that path regardless — pre-existing, harmless.

    Escape hatch (measured, not built): Index/*.iwa are the last ~857 KB of the 1.16 GB
    Map output (first .iwa header at 99.93%), so an append+central-directory rewrite
    would be sub-second but leaves orphaned bytes Keynote has never been probed on.
    """
    deck = Path(deck)
    tmp_path = deck.parent / f".{deck.name}.obedwrite.tmp"
    # temp zip + full copy-back reallocation (worst case: deck is an APFS clone source).
    required = deck.stat().st_size * 2.1
    if shutil.disk_usage(deck.parent).free < required:
        raise OfflineWriteRefused(f"free space below deck size * 2.1 ({required:.0f} bytes) on {deck.parent}")

    with zipfile.ZipFile(deck) as zin:
        missing = set(edits) - set(zin.namelist())
        if missing:
            raise OfflineWriteRefused(f"edits name members not in {deck.name}: {sorted(missing)}")
        try:
            with zipfile.ZipFile(tmp_path, "w") as zout:
                for zi in zin.infolist():
                    out_info = _preserve_raw_name(zi)
                    data = edits.get(zi.filename)
                    if data is not None:
                        zout.writestr(out_info, data, compress_type=zi.compress_type)
                    else:
                        with zin.open(zi) as src, zout.open(out_info, "w") as dst:
                            shutil.copyfileobj(src, dst, 8 << 20)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise  # nothing useful in the temp; deck untouched

    try:
        with open(str(deck), "wb") as out_fp, open(tmp_path, "rb") as tmp_fp:
            shutil.copyfileobj(tmp_fp, out_fp, 8 << 20)
            out_fp.flush()
            os.fsync(out_fp.fileno())
    except Exception as exc:
        raise OfflineWriteCorrupted(f"{deck} truncated; recover from {tmp_path}") from exc
    tmp_path.unlink()


def patch_deck_geometry(
    saved_deck: Path | str,
    specs_by_slide: dict[int, list[dict]],
    *,
    reported_by_slide: dict[int, dict[tuple[str, int], list[float]]] | None = None,
    source_counts_by_slide: dict[int, dict[str, int]] | None = None,
    address: str = "positional",
    require_reconcile: bool = True,
    extra_member_edits: dict[str, bytes] | None = None,
) -> dict[int, PatchResult]:
    """Patch every slide in ``specs_by_slide`` with exactly ONE zip rewrite.

    Refusal is per slide (that slide's member left byte-identical). Two slides
    resolving to the same target member refuse the LATER slide number.
    ``extra_member_edits`` (member -> raw new bytes, e.g. W2 stylesheet/z-order) merge in
    AFTER slide edits; a member in both raises ``ValueError`` before anything is written.
    Returns one ``PatchResult`` per key of ``specs_by_slide``, plus key 0 for
    ``extra_member_edits`` when given.
    """
    if 0 in specs_by_slide:
        raise ValueError("slide numbers are 1-based")
    saved_deck = Path(saved_deck)
    reported_by_slide = reported_by_slide or {}
    source_counts_by_slide = source_counts_by_slide or {}
    objects, id_to_file, _file_ids = _load_deck(saved_deck)
    order = slide_order(objects)

    slide_state: dict[int, tuple] = {}
    member_owner: dict[str, int] = {}
    for n in sorted(specs_by_slide):
        target_member, edits, soft, missed_specs, refuse_reason = _slide_edits(
            n, specs_by_slide[n], objects, id_to_file, order,
            reported=reported_by_slide.get(n),
            address=address,
            source_counts=source_counts_by_slide.get(n),
            require_reconcile=require_reconcile,
        )
        if not refuse_reason and target_member is not None and edits:
            owner = member_owner.get(target_member)
            if owner is not None:
                refuse_reason, edits = f"member shared with slide {owner}", {}
            else:
                member_owner[target_member] = n
        slide_state[n] = (target_member, edits, soft, missed_specs, refuse_reason)

    if extra_member_edits:
        collision = set(extra_member_edits) & set(member_owner)
        if collision:
            raise ValueError(f"extra_member_edits collides with slide-edited members {sorted(collision)}")

    member_edits: dict[str, bytes] = {}
    member_diag: dict[str, tuple[int, int, int]] = {}  # applied, obj_diffs, header_diffs
    if member_owner:
        with zipfile.ZipFile(saved_deck) as zf:  # one handle shared across every member patch
            for member, n in member_owner.items():
                _tm, edits, _soft, _missed, _reason = slide_state[n]
                new_bytes, applied, obj_diffs, header_diffs = _patch_member(zf, member, edits)
                member_edits[member] = new_bytes
                member_diag[member] = (applied, obj_diffs, header_diffs)

    results: dict[int, PatchResult] = {}
    for n, (target_member, edits, soft, missed_specs, refuse_reason) in slide_state.items():
        if refuse_reason:
            results[n] = PatchResult(refused=True, reason=refuse_reason, target_member=target_member,
                                     missed=len(missed_specs), missed_specs=missed_specs)
        elif not edits:
            results[n] = PatchResult(applied=0, missed=len(missed_specs), missed_specs=missed_specs,
                                     target_member=target_member, value_clean=True, soft_fallbacks=soft)
        else:
            m_applied, obj_diffs, header_diffs = member_diag[target_member]
            # No-op edits can yield obj_diffs < len(edits); collateral (> len(edits)) is the fail.
            value_clean = obj_diffs <= len(edits) and header_diffs == 0
            results[n] = PatchResult(
                applied=m_applied, missed=len(missed_specs), missed_specs=missed_specs,
                target_member=target_member, value_clean=value_clean,
                obj_diffs=obj_diffs, header_diffs=header_diffs,
                edited_ids=sorted(edits), soft_fallbacks=soft,
            )

    if extra_member_edits:
        member_edits.update(extra_member_edits)
        results[0] = PatchResult(applied=len(extra_member_edits), value_clean=True,
                                 edited_ids=sorted(extra_member_edits))

    if member_edits:
        try:
            _rewrite_members(saved_deck, member_edits)
        except OfflineWriteCorrupted:
            raise  # deck IS truncated: must reach the caller, never a refused result
        except Exception as exc:  # noqa: BLE001 — every result refuses, deck left untouched
            for n, prev in results.items():
                results[n] = PatchResult(refused=True, reason=f"rewrite failed: {exc}",
                                         target_member=prev.target_member,
                                         missed=len(prev.missed_specs), missed_specs=prev.missed_specs)
            return results

    return results


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
    """Write slide_number geometry in place. Delegates to patch_deck_geometry for one slide."""
    results = patch_deck_geometry(
        saved_deck, {slide_number: specs},
        reported_by_slide={slide_number: reported} if reported is not None else None,
        source_counts_by_slide={slide_number: source_counts} if source_counts is not None else None,
        address=address,
        require_reconcile=require_reconcile,
    )
    return results[slide_number]


_STROKE_STYLESHEET_MEMBER = "Index/DocumentStylesheet.iwa"


def _resolve_stroke(style_id: str, objects: dict[str, dict]) -> tuple[dict | None, bool]:
    """First non-``None`` ``mediaProperties.stroke`` up the ``super.parent`` chain.

    (stroke, inherited) -- ``inherited`` is True once the walk had to leave the
    starting style. Capped + seen-set, same shape as ``iwa_geometry._geom_dict``.
    """
    cur: str | None = str(style_id)
    seen: set[str] = set()
    inherited = False
    for _ in range(6):
        if cur is None or cur in seen:
            break
        seen.add(cur)
        obj = objects.get(cur)
        if not obj:
            break
        stroke = (obj.get("mediaProperties") or {}).get("stroke")
        if stroke is not None:
            return stroke, inherited
        parent = ((obj.get("super") or {}).get("parent") or {}).get("identifier")
        if parent is None:
            break
        cur = str(parent)
        inherited = True
    return None, inherited


def _collect_stroke_images(obj_id: str, objects: dict[str, dict], seen: set[str], out: list[str]) -> None:
    """DFS ``TSD.GroupArchive.children``, appending image/movie leaf ids. Mirrors
    ``iwa_runs._collect_group_text``'s seen-set group DFS."""
    if obj_id in seen:
        return
    seen.add(obj_id)
    obj = objects.get(obj_id)
    if not obj:
        return
    ptype = obj.get("_pbtype")
    if ptype == "TSD.GroupArchive":
        for ref in obj.get("children") or []:
            cid = ref.get("identifier")
            if cid is not None:
                _collect_stroke_images(str(cid), objects, seen, out)
    elif ptype in ("TSD.ImageArchive", "TSD.MovieArchive"):
        out.append(obj_id)


def card_styles(objects: dict[str, dict], id_to_file: dict[str, str]) -> list[dict]:
    """One dict per ``MediaStyleArchive`` referenced by an image/movie, sorted by refs desc.

    ``slide_of`` walks every slide's ``drawablesZOrder`` recursively through groups
    (a card's image is nested; ``compose_geometry`` never reaches it). Each dict:
    ``{id, member, width, color:(r,g,b,a), pattern, refs, slides, inherited}``.
    """
    slide_of: dict[str, int] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide = objects.get(slide_id)
        if not slide:
            continue
        images: list[str] = []
        seen: set[str] = set()
        for ref in slide.get("drawablesZOrder") or []:
            rid = ref.get("identifier")
            if rid is not None:
                _collect_stroke_images(str(rid), objects, seen, images)
        number = idx + 1
        for img_id in images:
            slide_of.setdefault(img_id, number)

    refs: dict[str, int] = {}
    slides_by_style: dict[str, set[int]] = {}
    for obj_id, obj in objects.items():
        if obj.get("_pbtype") not in ("TSD.ImageArchive", "TSD.MovieArchive"):
            continue
        style_id = (obj.get("style") or {}).get("identifier")
        if style_id is None:
            continue
        style_id = str(style_id)
        refs[style_id] = refs.get(style_id, 0) + 1
        number = slide_of.get(obj_id)
        if number is not None:
            slides_by_style.setdefault(style_id, set()).add(number)

    styles: list[dict] = []
    for style_id, count in refs.items():
        stroke, inherited = _resolve_stroke(style_id, objects)
        if stroke is None:
            continue
        color = stroke.get("color") or {}
        pattern = (stroke.get("pattern") or {}).get("type")
        styles.append({
            "id": style_id,
            "member": id_to_file.get(style_id),
            "width": stroke.get("width"),
            "color": (color.get("r"), color.get("g"), color.get("b"), color.get("a")),
            "pattern": pattern,
            "refs": count,
            "slides": sorted(slides_by_style.get(style_id, set())),
            "inherited": inherited,
        })
    styles.sort(key=lambda s: -s["refs"])
    return styles


def select_card_styles(styles: list[dict], min_refs: int) -> list[dict]:
    """White + opaque (r,g,b,a each >= 0.95) AND solid AND refs >= ``min_refs``. Never by id."""
    out = []
    for s in styles:
        r, g, b, a = s["color"]
        if r is None or g is None or b is None or a is None:
            continue
        if r >= 0.95 and g >= 0.95 and b >= 0.95 and a >= 0.95 \
                and s["pattern"] == "TSDSolidPattern" and s["refs"] >= min_refs:
            out.append(s)
    return out


# The output deck is a copy of the wall, so an output card style's ref count is the
# source's plus the remap's stranded donor copies -- measured 83 -> 269 (3.24x) on the
# Gold run, whose patch runs BEFORE the stat-finalize dedup brings it back to 83. Divide
# the output count by 8 for the source floor: ~2.5x headroom over that inflation, while
# still dropping the Full wall's 3-ref 5pt stray (83-ref card style, floor 10-33).
_SOURCE_REF_DIVISOR = 8


def _card_style_pair_key(style: dict[str, Any]) -> tuple:
    r, g, b, a = style["color"]
    rnd = tuple(round(v, 3) if v is not None else None for v in (r, g, b, a))
    return (*rnd, style["pattern"])


def match_card_stroke_styles(
    out_styles: list[dict],
    src_styles: list[dict],
    *,
    canvas_scale: float,
    min_refs: int = 10,
) -> dict[str, Any]:
    """Pair each output card style with its source counterpart. Pure: ``card_styles()``
    rows in (inherited rows included -- filtered here), no deck IO, no logging.

    The output side is the card classifier verbatim (``select_card_styles``, ``min_refs``).
    A source candidate shares the pairing key, so its colour and pattern already match by
    construction -- only the classifier's REFS test has to be re-applied on that side, and
    it is scaled off the paired output style's own ref count rather than ``min_refs``: the
    wall legitimately holds fewer card images than the donor-copy-inflated output does, so
    a flat ``min_refs`` there would refuse small decks that pair correctly today.

    Returns ``{"widths": {output style id: source width}, "chosen": [{"id","old","new",
    "refs"}], "notes": [str], "out_selected": [style]}``. ``notes`` are refusal lines in
    emission order for the caller to log verbatim; ``chosen`` is the success log's rows.
    """
    out_selected = select_card_styles([s for s in out_styles if not s["inherited"]], min_refs)
    out_by_key: dict[tuple, list[dict]] = {}
    for s in out_selected:
        out_by_key.setdefault(_card_style_pair_key(s), []).append(s)
    src_by_key: dict[tuple, list[dict]] = {}
    for s in src_styles:
        if not s["inherited"]:
            src_by_key.setdefault(_card_style_pair_key(s), []).append(s)

    widths: dict[str, float] = {}
    chosen: list[dict[str, Any]] = []
    notes: list[str] = []
    for key, out_candidates in out_by_key.items():
        src_all = src_by_key.get(key) or []
        floor = max(2, max(o["refs"] for o in out_candidates) // _SOURCE_REF_DIVISOR)
        src_candidates = select_card_styles(src_all, floor)
        if len(out_candidates) != 1 or len(src_candidates) != 1:
            for oc in out_candidates:
                notes.append(
                    f"Card-border stroke: skipping style {oc['id']} ({len(out_candidates)} "
                    f"output / {len(src_candidates)} source candidate(s) for this colour+pattern "
                    "pairing, need exactly 1 on each side)."
                )
            notes.append(
                "Card-border stroke: candidates were output ["
                + ", ".join(f"{o['id']} {o['width']}pt/{o['refs']} refs" for o in out_candidates)
                + "], source ["
                + (", ".join(f"{s['id']} {s['width']}pt/{s['refs']} refs" for s in src_all) or "none")
                + f"] at a source floor of {floor} refs."
            )
            continue
        out_style, src_style = out_candidates[0], src_candidates[0]
        out_w, src_w = out_style["width"], src_style["width"]
        if out_w is None or src_w is None:
            continue
        if not (out_w < src_w and out_w <= src_w * canvas_scale * 1.1):
            notes.append(
                f"Card-border stroke: skipping style {out_style['id']} (out={out_w} vs "
                f"src={src_w}, canvas_scale={canvas_scale:.4f} guard failed)."
            )
            continue
        widths[out_style["id"]] = src_w
        chosen.append({"id": out_style["id"], "old": out_w, "new": src_w, "refs": out_style["refs"]})
        if len(src_all) != len(src_candidates):
            discarded = [s for s in src_all if s["id"] != src_style["id"]]
            notes.append(
                f"Card-border stroke: source floor {floor} refs set aside ["
                + ", ".join(f"{s['id']} {s['width']}pt/{s['refs']} refs" for s in discarded)
                + f"] for output {out_style['id']}."
            )

    return {"widths": widths, "chosen": chosen, "notes": notes, "out_selected": out_selected}


def patch_stroke_widths(deck: Path, widths: dict[str, float]) -> dict:
    """Patch ``mediaProperties.stroke.width`` for each id in ``widths``, single-member
    rewrite of ``Index/DocumentStylesheet.iwa`` via ``_rewrite_members``.

    Refuses (deck untouched) if an id is absent, has no OWN stroke (inherited-only),
    lives in a different member, or fewer ids matched an archive than requested (the
    silent-no-op guard -- every validation happens before any write).
    """
    deck = Path(deck)
    target_member = _STROKE_STYLESHEET_MEMBER
    widths = {str(k): float(v) for k, v in widths.items()}
    objects, id_to_file, _file_ids = _load_deck(deck)

    for sid in widths:
        obj = objects.get(sid)
        if obj is None:
            return {"refused": True, "reason": f"style {sid} not found in deck"}
        if (obj.get("mediaProperties") or {}).get("stroke") is None:
            return {"refused": True, "reason": f"style {sid} has no own stroke (inherited-only)"}
        if id_to_file.get(sid) != target_member:
            return {"refused": True,
                    "reason": f"style {sid} lives in {id_to_file.get(sid)!r}, not {target_member!r}"}

    with zipfile.ZipFile(deck) as zf:
        if target_member not in zf.namelist():
            return {"refused": True, "reason": f"member {target_member} missing from deck"}
        buf = zf.read(target_member)

    decoded = IWAFile.from_buffer(buf, target_member).to_dict()
    patched = copy.deepcopy(decoded)
    applied = 0
    for ch in patched["chunks"]:
        for arch in ch["archives"]:
            aid = str(arch["header"]["identifier"])
            if aid not in widths:
                continue
            for o in arch.get("objects") or []:
                o["mediaProperties"]["stroke"]["width"] = float(widths[aid])
                applied += 1
                break

    if applied != len(widths):
        return {"refused": True,
                "reason": f"only {applied}/{len(widths)} styles matched an archive in {target_member}"}

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
    value_clean = obj_diffs <= len(widths) and header_diffs == 0

    try:
        _rewrite_members(deck, {target_member: new_member})
    except OfflineWriteCorrupted:
        raise  # deck IS truncated: must reach the caller, never a refused result
    except Exception as exc:  # noqa: BLE001 — every result refuses, deck left untouched
        return {"refused": True, "reason": f"rewrite failed: {exc}"}

    return {
        "refused": False,
        "reason": None,
        "target_member": target_member,
        "applied": applied,
        "obj_diffs": obj_diffs,
        "header_diffs": header_diffs,
        "value_clean": value_clean,
        "edited_ids": sorted(widths, key=str),
    }


def _archives_by_id(decoded: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ch in decoded["chunks"]:
        for arch in ch["archives"]:
            out[str(arch["header"]["identifier"])] = arch
    return out


def _archive_diff(before: dict, after: dict) -> tuple[set[str], set[str], list[str]]:
    """(removed_ids, added_ids, changed_ids), by archive identifier (not position —
    correct even if the archive count ever changed, which this patch never does)."""
    b, a = _archives_by_id(before), _archives_by_id(after)
    removed, added = set(b) - set(a), set(a) - set(b)
    changed = [
        aid
        for aid in set(b) & set(a)
        if (b[aid].get("objects") or []) != (a[aid].get("objects") or []) or b[aid]["header"] != a[aid]["header"]
    ]
    return removed, added, changed


def patch_slide_builds(deck: Path, plans: dict[str, dict]) -> dict:
    """Patch each named ``KN.SlideArchive``'s ``builds``/``buildChunks``/``transition``
    in place — one ``_rewrite_members`` call for every member touched. ``plans`` is
    ``{slideId: {"builds": [ids], "buildChunks": [ids], "transition": dict|None}}``
    (``iwa_builds.plan_build_patch``'s ``"plans"``). Orphaned ``KN.BuildArchive``/
    ``KN.BuildChunkArchive`` entries are left in place (same precedent as
    ``patch_stroke_widths`` leaving other stylesheet entries alone).

    Refuses (deck untouched) unless every named slide resolves to a
    ``KN.SlideArchive``, every id in its plan resolves to a same-member
    ``KN.BuildArchive``/``KN.BuildChunkArchive``, and, per member, the re-encoded
    archive set changed EXACTLY the intended slide(s) — nothing added or removed
    (the proven ``build_patch.py`` self-check gate).
    """
    deck = Path(deck)
    plans = {str(k): v for k, v in plans.items()}
    if not plans:
        return {"refused": False, "touched": [], "applied": 0}
    for slide_id, plan in plans.items():
        transition = plan.get("transition")
        if transition is not None and _contains_identifier(transition):
            return {"refused": True, "reason": f"slide {slide_id}: transition holds a cross-member reference"}

    objects, id_to_file, _file_ids = _load_deck(deck)
    for slide_id in plans:
        obj = objects.get(slide_id)
        if obj is None:
            return {"refused": True, "reason": f"slide {slide_id} not found in deck"}
        if obj.get("_pbtype") != "KN.SlideArchive":
            return {"refused": True, "reason": f"{slide_id} is not a KN.SlideArchive"}

    by_member: dict[str, list[str]] = {}
    for slide_id in plans:
        member = id_to_file.get(slide_id)
        if member is None:
            return {"refused": True, "reason": f"slide {slide_id} has no owning member"}
        by_member.setdefault(member, []).append(slide_id)

    for slide_id, plan in plans.items():
        member = id_to_file[slide_id]
        for pbtype, field in (("KN.BuildArchive", "builds"), ("KN.BuildChunkArchive", "buildChunks")):
            for oid in plan.get(field) or []:
                obj = objects.get(oid)
                if obj is None or obj.get("_pbtype") != pbtype or id_to_file.get(oid) != member:
                    return {
                        "refused": True,
                        "reason": f"slide {slide_id}: {field} id {oid} does not resolve to a {pbtype} in {member}",
                    }

    edits: dict[str, bytes] = {}
    applied = 0
    with zipfile.ZipFile(deck) as zf:
        for member, slide_ids in by_member.items():
            buf = zf.read(member)
            decoded = IWAFile.from_buffer(buf, member).to_dict()
            patched = copy.deepcopy(decoded)
            touched = 0
            wanted = set(slide_ids)
            for ch in patched["chunks"]:
                for arch in ch["archives"]:
                    aid = str(arch["header"]["identifier"])
                    if aid not in wanted:
                        continue
                    plan = plans[aid]
                    for o in arch.get("objects") or []:
                        o["builds"] = [{"identifier": bid} for bid in plan["builds"]]
                        o["buildChunks"] = [{"identifier": cid} for cid in plan["buildChunks"]]
                        if plan.get("transition") is not None:
                            o["transition"] = plan["transition"]
                        touched += 1

            if touched != len(wanted):
                return {
                    "refused": True,
                    "reason": f"expected to touch {len(wanted)} slide(s) in {member}, touched {touched}",
                }

            new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
            reparsed = IWAFile.from_buffer(new_member, member).to_dict()
            removed, added, changed = _archive_diff(decoded, reparsed)
            # A byte-identical no-op write for one of the wanted slides is fine --
            # `changed` need only be a SUBSET of `wanted`, not equal to it.
            if removed or added or not set(changed) <= wanted:
                return {
                    "refused": True,
                    "reason": f"{member}: re-encode touched fewer/other than the intended slide(s) "
                    f"(removed={sorted(removed)}, added={sorted(added)}, changed={sorted(changed)})",
                }
            edits[member] = new_member
            applied += touched

    _rewrite_members(deck, edits)
    return {"refused": False, "touched": sorted(plans), "applied": applied}
