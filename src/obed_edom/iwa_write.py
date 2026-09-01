"""Offline surgical geometry-WRITE for one slide of a finalized ``.key``.

The companion of the offline READ stack (:mod:`obed_edom.iwa_kindindex`,
:mod:`obed_edom.iwa_geometry`, :mod:`obed_edom.offline_inspect`): it patches the
laid-out geometry of the drawables on ONE slide directly in the deck's decoded IWA
graph — no Keynote, no AppleScript — and rewrites just that slide's ``Index/*.iwa``
member back into the ``.key`` zip. Its intended use is the pass-1-only baseline
produced by ``OBED_SUPPRESS_GEOMETRY`` (see :func:`remap_keynote.suppress_geometry_slides`):
pass 1 writes attributes but leaves geometry untouched, and this patcher then writes
the geometry the batched AppleScript pass would have written.

WRITE MECHANICS (promoted verbatim from the proven w-spike1 prototype, which opened
clean in Keynote with every value surviving — see SKILL "Surgical geometry-write
semantics, per class"):

  * **shape** — position absolute; size to BOTH ``geometry.size`` AND
    ``bezierPathSource.naturalSize`` (Keynote lays a shape out from ``naturalSize``
    and ignores ``geometry.size`` when the two disagree).
  * **line** — placed by the INVERSE of :func:`offline_inspect._line_endpoints`
    (:func:`line_inverse`): ``geometry.position`` + ``geometry.angle`` + the length
    written to BOTH ``geometry.size.width`` (what the offline reader composes from)
    AND ``bezierPathSource.naturalSize.width`` (what Keynote renders the segment
    length from); the bezier ``moveTo``/``lineTo`` template is left untouched.
  * **text / autosize** — ``position.x`` exact absolute (left-aligned);
    ``position.y`` is the vertical CENTRE, moved by the delta ``target − reported``;
    w/h only as a ``reported`` delta (the real laid-out size is not offline-recoverable).
  * **group** — pure translation: ``stored += target − reported``; the group's own
    w/h is deliberately NOT written (a group frame is inert — the children carry the
    render).
  * **masked image** — TENTATIVE (see :func:`_masked_image_fields`); the definitive
    rule comes from the lead's live byte-reveal.

``com.apple.macl`` gotcha (SKILL): a patched deck written as a NEW file has no
``com.apple.macl`` xattr, so sandboxed Keynote refuses to open it ("Operation not
permitted"). The rewrite is therefore IN PLACE (``os.open(..., O_TRUNC)`` over the
existing file), preserving the inode and its macl.

ADDRESSING is swappable (``address=``): the live id-preservation probe (deferred to
the lead) selects ``"identity"`` (a spec's source drawable id survived the pass-1
save) vs the default ``"positional"`` ((kind, kindIndex) on the saved deck, bridged
across deleted hides). Positional is guarded by a per-kind :func:`reconcile_counts`
REFUSE gate: the saved deck's live per-kind counts must equal the plan-expected base
(source-derived minus role=hide specs); any mismatch REFUSES the slide (returns a
fallback marker) rather than risk a mis-addressed write.
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


# --------------------------------------------------------------------------
# Result.
# --------------------------------------------------------------------------
@dataclass
class PatchResult:
    """Outcome of one :func:`patch_slide_geometry` call.

    ``refused`` marks a slide the addressing gate would not touch (``reason`` says
    why); the caller falls back to the scoped AppleScript geometry write for it.
    ``value_clean`` is the in-member self-check: exactly the edited archives differ
    and no archive HEADER changed (``obj_diffs == edited archives`` and
    ``header_diffs == 0``) — a False here means the rewrite mutated more than intended
    and MUST NOT be trusted.
    """

    applied: int = 0
    missed: int = 0
    refused: bool = False
    reason: str | None = None
    target_member: str | None = None
    value_clean: bool = False
    obj_diffs: int = 0
    header_diffs: int = 0
    edited_ids: list[str] = field(default_factory=list)
    # Soft classes (group / text / masked image) whose delta fell back to the offline
    # COMPOSED frame because no ``reported`` frame was supplied for their (kind, saved
    # kindIndex). The gate asserts this is 0 — every soft frame must come from the bulk
    # pre-patch read, never from the offline compose (which is stale for those kinds).
    soft_fallbacks: int = 0


# --------------------------------------------------------------------------
# Archive-object geometry access (promoted from the spike).
# --------------------------------------------------------------------------
def _find_geom(objdict: dict) -> list[str] | None:
    """Path (list of keys) to the first ``geometry`` dict inside an archive object.

    Walks nested dicts, so it lands the geometry wherever the archive keeps it
    (``super.super.geometry`` for a shape, ``super.geometry`` for an image/mask).
    """
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
    """The ``bezierPathSource`` dict up the ``super`` chain, or ``None``.

    Mirrors :func:`iwa_kindindex._bezier` / :func:`offline_inspect._line_direction`'s
    walk: the first ``super.pathsource`` seen owns the ``bezierPathSource``.
    """
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
    """``(pos_x, pos_y, length, angle_deg)`` so ``_line_endpoints(obj')`` == ``(start, end)``.

    Uses the object's own natural direction ``(ux, uy)`` incl. horizontal/vertical
    flips (:func:`offline_inspect._line_direction`), the exact quantity the forward
    reader consumes, so the round trip is faithful for any flipped template line.
    A line's stored frame has height 0, so ``pos = centre − (length/2, 0)``.
    """
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


# --------------------------------------------------------------------------
# deleteHides bridge + reconcile base (positional addressing).
# --------------------------------------------------------------------------
def bridge_kind_index(kind: str, wall_kind_index: int, hide_specs: list[dict]) -> int:
    """Wall ``kindIndex`` → saved-deck ``kindIndex`` after ``deleteHides``.

    ``deleteHides`` (``remap_keynote.js``) removes every ``role="hide"`` object on a
    non-reuse slide before the deck is saved, so a surviving object's live index
    drops by the number of SAME-KIND hides with a lower index than it. Generalizes
    the group-only :func:`map_remap.adjust_child_resize_for_deleted_hides` to every
    kind. ``hide_specs`` is this slide's ``role="hide"`` specs.
    """
    lower = sum(
        1
        for h in hide_specs
        if str(h.get("kind")) == kind and int(h.get("kindIndex", 0)) < wall_kind_index
    )
    return wall_kind_index - lower


def expected_base_counts(source_counts: dict[str, int], specs: list[dict]) -> dict[str, int]:
    """Per-kind counts the SAVED deck must show = source-derived minus role=hide specs.

    ``source_counts`` is :func:`iwa_kindindex.derived_kind_counts` on the SOURCE wall
    slide; every ``role="hide"`` spec is a ``deleteHides`` target, so it is subtracted
    from its kind. The saved deck's live per-kind counts must equal this exactly (bar
    the text-placeholder slack :func:`reconcile_counts` already tolerates), else the
    offline addressing is untrusted and the slide is REFUSED.
    """
    hides: dict[str, int] = {}
    for s in specs:
        if s.get("role") == "hide":
            k = str(s.get("kind"))
            hides[k] = hides.get(k, 0) + 1
    return {k: v - hides.get(k, 0) for k, v in source_counts.items()}


# --------------------------------------------------------------------------
# Per-class field builders. Each returns [(archive_object_id, {field: value})].
# Field keys: pos_x, pos_y, size_w, size_h, angle, natural_w, natural_h.
# --------------------------------------------------------------------------
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
    # geometry.size.width feeds the offline reader (_line_rect); naturalSize.width is
    # what Keynote renders the segment length from — write both, leave the bezier.
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
                  stored: tuple[float, float, float, float, float]) -> list[tuple[str, dict]]:
    # Pure translation on the stored frame; the group's own w/h is never written.
    fields: dict[str, float] = {}
    if spec.get("x") is not None:
        fields["pos_x"] = stored[0] + (float(spec["x"]) - reported[0])
    if spec.get("y") is not None:
        fields["pos_y"] = stored[1] + (float(spec["y"]) - reported[1])
    return [(rec["id"], fields)] if fields else []


def _masked_image_fields(rec: dict, obj: dict, objects: dict[str, dict], spec: dict,
                         reported: list[float]) -> tuple[list[tuple[str, dict]], str | None]:
    """TENTATIVE masked-image write. Returns ``(ops, mask_id)``.

    **Deferred to the lead's live byte-reveal (Piece 4).** Best prior, mirroring
    :func:`iwa_geometry._masked_rect`: at a clean (0°) layout the composed crop is
    ``(image_pos + mask_pos, mask_size)``. To land that crop at the target we move
    and size the MASK (``super.geometry`` of the mask archive) so
    ``image_pos + mask_pos == target_pos`` and ``mask_size == target_size`` — this
    alone makes the offline reader (and JXA's mask-rect frame) read back the target,
    and is what the value-clean + read-back test pins. The image ``geometry.size`` is
    ALSO scaled by the crop ratio (the "scale image and mask together" prior), which
    is the ONE unverified bit; the byte-reveal confirms or replaces it, in this single
    function.

    Returns ``mask_id`` so the caller can confirm the mask lives in the target member
    (a cross-member mask cannot be reached by the single-member rewrite → the spec is
    skipped as a miss).
    """
    mask_ref = (obj.get("mask") or {}).get("identifier")
    if mask_ref is None:
        return ([], None)
    mask_id = str(mask_ref)
    mask_obj = objects.get(mask_id)
    if not mask_obj:
        return ([], None)
    fx, fy, fw, fh, fa = _xywha(_geom_dict(obj))
    _mx, _my, mw, mh, ma = _xywha(_geom_dict(mask_obj))
    # The composed-crop formula (image_pos + mask_pos, mask_size) is AXIS-ALIGNED only:
    # a rotated image or mask would be mis-placed by it. Refuse such a spec here (the
    # caller counts it a MISS) rather than silently corrupt the layout. SKILL: rotated-
    # masked is 0 on the gold decks, so this never fires there — it is a corruption net.
    if fa % 360.0 or ma % 360.0:
        return ([], mask_id)
    tx = float(spec["x"]) if spec.get("x") is not None else reported[0]
    ty = float(spec["y"]) if spec.get("y") is not None else reported[1]
    tw = float(spec["w"]) if spec.get("w") is not None else mw
    th = float(spec["h"]) if spec.get("h") is not None else mh
    ops: list[tuple[str, dict]] = [
        # mask: position so image_pos + mask_pos == target; size == target crop.
        (mask_id, {"pos_x": tx - fx, "pos_y": ty - fy, "size_w": tw, "size_h": th}),
    ]
    # image: scale by the crop ratio (TENTATIVE — see docstring). Guard /0.
    ratio_w = tw / mw if mw else 1.0
    ratio_h = th / mh if mh else 1.0
    ops.append((rec["id"], {"size_w": fw * ratio_w, "size_h": fh * ratio_h}))
    return (ops, mask_id)


# --------------------------------------------------------------------------
# Field application to a decoded archive object.
# --------------------------------------------------------------------------
def _apply_geom_fields(archive_obj: dict, fields: dict) -> None:
    """Mutate a decoded archive object's geometry / naturalSize per ``fields``."""
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


# --------------------------------------------------------------------------
# Addressing strategies (swappable). Each maps a spec to a saved-deck record.
# --------------------------------------------------------------------------
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
    # HOOK (lead resolves empirically in Piece 4): if the source drawable id survives
    # the pass-1 save, the spec carries it as ``source_id`` and we address by it —
    # immune to deleteHides shifts and same-kind swaps, no bridge needed.
    sid = spec.get("source_id") or spec.get("id")
    return comp_by_id.get(str(sid)) if sid is not None else None


# --------------------------------------------------------------------------
# Public entry.
# --------------------------------------------------------------------------
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
    """Surgically write the geometry of ``slide_number``'s drawables, in place.

    ``specs`` are the slide's transforms (each carrying ``kind``, ``kindIndex`` (wall),
    ``x``/``y``/``w``/``h``, ``start``/``end`` for lines, ``role``). ``reported`` is the
    pre-patch soft-class bulk frames as ``{(kind, kindIndex): [x, y, w, h]}`` keyed by
    SAVED (post-``deleteHides``) kindIndex, injectable so a unit test needs no Keynote;
    where a class needs a delta and no reported frame is supplied, the offline COMPOSED
    frame stands in. ``address`` selects the strategy (``"positional"`` default, or
    ``"identity"``); ``source_counts`` (source-wall per-kind counts) arms the positional
    reconcile REFUSE gate. ``require_reconcile`` makes that gate MANDATORY: with it True
    and ``source_counts`` unset the slide is REFUSED outright (the gate cannot be armed),
    so the harness can never write a positional slide with the reconcile check disarmed.

    Returns a :class:`PatchResult`; on a reconcile mismatch or a cross-member slide it
    REFUSES (writes nothing) and the caller falls back to the scoped AppleScript write.
    """
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

    # --- locality guard: every drawable on this slide in ONE member -------------
    members = {id_to_file.get(r["id"]) for r in comp if r["id"] in id_to_file}
    members.discard(None)
    if len(members) != 1:
        return PatchResult(refused=True, reason=f"slide drawables span {sorted(members)} (need exactly one member)")
    target_member = next(iter(members))

    # --- reconcile REFUSE gate (positional only) --------------------------------
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

    # --- resolve each spec to a saved-deck record + build its field ops ---------
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
            ops = _group_fields(rec, spec, rep, stored)
        elif kind == "text":
            ops = _text_fields(rec, spec, rep, stored)
        elif kind in ("image", "movie"):
            if masked:
                ops, mask_id = _masked_image_fields(rec, obj, objects, spec, rep)
                # An unresolved mask, a cross-member mask (a single-member rewrite can't
                # reach it), or a rotated masked image the axis-aligned crop formula
                # can't place: skip as a MISS rather than mis-write.
                if not ops or mask_id is None or id_to_file.get(mask_id) != target_member:
                    missed += 1
                    continue
            else:  # unmasked image/movie: plain frame, same as a shape (position + size)
                ops = _shape_fields(rec, spec)
        else:
            missed += 1
            continue

        # Soft classes (group / text / masked image) carry a delta off the pre-patch
        # frame; when the bulk read supplied none for this (kind, saved kindIndex) the
        # offline composed frame stood in — count it so the gate can insist on 0.
        if (kind in ("group", "text") or masked) and not have_reported and ops:
            soft_fallbacks += 1

        for obj_id, fields in ops:
            if not fields:
                continue
            edits.setdefault(obj_id, {}).update(fields)

    if not edits:
        return PatchResult(applied=0, missed=missed, target_member=target_member,
                           value_clean=True, soft_fallbacks=soft_fallbacks)

    # --- apply to the target member, self-check value-clean, rewrite in place ---
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
    value_clean = obj_diffs == len(edits) and header_diffs == 0

    # In-place rewrite (O_TRUNC over the existing file) preserves the inode and its
    # com.apple.macl xattr, without which sandboxed Keynote refuses to open the deck.
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
