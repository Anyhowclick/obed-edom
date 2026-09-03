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

from obed_edom.iwa_geometry import _geom_dict, _xywha, compose_geometry
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
                    missed_specs.append(spec)
                    continue
                ops = ops + child_ops
        elif kind == "text":
            ops = _text_fields(rec, spec, rep, stored)
        elif kind in ("image", "movie"):
            if masked:
                ops, mask_id = _masked_image_fields(rec, obj, objects, spec, rep)
                # Unresolved, cross-member, or rotated mask: miss rather than mis-write.
                if not ops or mask_id is None or id_to_file.get(mask_id) != target_member:
                    missed_specs.append(spec)
                    continue
            else:  # unmasked image/movie: plain frame, same as a shape
                ops = _shape_fields(rec, spec)
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
