"""Offline composition of Keynote's laid-out (JXA-frame) per-object geometry.

:mod:`obed_edom.iwa_kindindex` reconstructs each drawable's *address*
``(kind, kindIndex)`` offline, but the geometry it carries is the RAW IWA frame,
which diverges from what Keynote's JXA inspect reports: masked images report the
unmasked frame, rotated frames report the un-rotated box, group frames are stale,
lines carry their bounding box rather than their endpoints, and autosize text
reports a zero-height frame. This module *composes* those raw values into the
write-accurate ``(x, y, w, h)`` JXA reports, so ``remap`` can read object geometry
without the ~12-minute per-object Keynote inspect.

Every divergence between raw IWA geometry and JXA is a composition the raw reader
had not performed. All formulas here were reverse-engineered and differential-tested
against fresh exact-bytes JXA payloads on ``Map_Extracted_Wall_1st`` (8 slides) and
``Full_Report_Card_Wall`` (155). What is established, by kind:

    * **image / movie** — unmasked axis-aligned frames match to <0.5px. A rotated
      frame's JXA box is the axis-aligned bounding box (AABB) of the four rotated
      corners, position only; SIZE stays the un-rotated ``(w, h)``. A *masked* image
      reports the MASK rectangle: at a 90°-multiple rotation (incl. 0°, where it
      collapses to ``(img+mask, mask_size)``) the mask-corner AABB is integer-exact
      and VOUCHED; only a real OFF-axis residual — where snapping to the nearest 90°
      moves the box more than ``_MASK_TRUST_PX`` — is best-effort and flagged
      ``rotated-masked`` (residual up to ~95px — the DSK17 flip). See
      :func:`_masked_rect`.
    * **line** — the endpoints, from the length + rotation closed form; <0.5px.
    * **shape** — same rotation rule as image (AABB position, un-rotated size);
      100% <2px both decks. (Raw geometry alone leaves rotated shapes ~2-12px inset,
      so this composes the rotation even though shapes are never masked.)
    * **group** — union of the children's transformed bounds; ~89% of distinct
      groups <2px. The residual cases carry a detectable signal (zero-size connector
      child, rotated-masked child, or an effect style) and are flagged
      ``group-residual``; a rotated group itself is flagged ``rotated-group``.
    * **text** — a fixed box is its frame; an autosize box (zero-height frame)
      recovers ``x`` exactly (left-aligned) but ``y``/``h``/``w`` from a
      ``naturalSize`` that is stale on ~20% of boxes, so every autosize box is
      flagged ``autosize-soft`` while still emitting best-effort values.

``needs_keynote`` marks the records a write path must treat with care; it is ALWAYS
accompanied by best-effort geometry (never a ``None`` position). The complete reason
set is ``rotated-masked``, ``masked-unresolved`` (a mask ref that does not resolve, so
the unmasked frame shipped instead of the mask rect), ``rotated-group`` (incl. a rotated
NESTED group, which the translation-only union cannot place), ``group-residual``, and
``autosize-soft``. All are conservative: a record that *might* be wrong is flagged, so a
write path can fall back to a Keynote read for it. Zero of the mask-unresolved / nested-
rotated cases occur in the two test decks; they are defensive nets for other decks.

This module is strictly geometry: it reuses :func:`iwa_kindindex.derive_kind_index`
for the addressing and NEVER changes an object's ``kind``/``kindIndex``/order.
The rotation math lives here because :class:`map_remap.Affine` is scale+translate
only. Full rule statement lives in the SKILL under "Reading a .key offline (IWA)".

Public entry points:
    * :func:`compose_geometry` — pure ``(slide, objects) -> [records]`` for one slide.
    * :func:`compose_deck_geometry` — whole deck, ``{slide_index: [records]}``.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from obed_edom.iwa_kindindex import derive_kind_index

# geom_source values, one per composition rule.
GEOM_SOURCES = ("iwa", "mask", "line", "group-union", "autosize")

# needs_keynote reasons (complete set); see module docstring.
NEEDS_KEYNOTE_REASONS = (
    "rotated-masked", "masked-unresolved", "rotated-group", "group-residual", "autosize-soft",
)

# An angle within this many degrees of 0 (mod 360) is treated as un-rotated: the
# corner-AABB collapses to the frame and no rotated-* flag is raised.
_ANGLE_EPS = 0.01

# Masked-image accuracy guard (L1). Keynote lays a masked image out at a CLEAN
# rotation: at an exact 90° multiple (0/90/180/270) the composed mask-corner AABB is
# integer-exact vs JXA (measured ≤0.5px on the DSK/GW/FULL/MAP decks), because sin/cos
# of a 90-multiple are exact 0/±1. Error appears only with a small OFF-axis residual
# (1-3°), where the corner-AABB applies a rotation Keynote did not and the miss scales
# with the mask offset's LEVER ARM (measured to 95px — the DSK17 flip is frame357+
# mask357). So the guard composes the mask box at the angles SNAPPED to their nearest
# 90° multiple (the clean layout JXA reports) and vouches it only when that snap moved
# the box no further than this many points from the RAW-angle composition. That
# displacement bounds the composition error up to integer rounding: JXA lays the image
# out at either the snapped rotation (error≈0) or the raw one (our shipped snapped
# value is `displacement` from it), and both sides are rounded to whole points, so
# error_vs_JXA ≤ displacement + ~0.5px — an angle threshold gives no such bound at all,
# because a 1° residual on a long lever arm still misses by px. 1.5 sits in a wide
# measured gap (accurate cases ≤1.48px, wrong ones ≥2.45px); with the rounding term the
# worst vouched case measured 1.56px, ~0.44px under the 2px write tolerance, so do NOT
# raise this. A displacement above it keeps the flag → Keynote fallback.
_MASK_TRUST_PX = 1.5


# --------------------------------------------------------------------------
# Level-agnostic geometry access (mirrors iwa_kindindex._geometry: walk the
# ``super`` chain to the first dict carrying a ``geometry``, ≤6 hops — robust
# across shapes at super.super, and images/groups/lines/masks one level up).
# --------------------------------------------------------------------------
def _geom_dict(obj: dict) -> dict:
    """The first ``geometry`` dict up the ``super`` chain, or ``{}``."""
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        geom = cur.get("geometry")
        if isinstance(geom, dict):
            return geom
        cur = cur.get("super")
    return {}


def _xywha(geom: dict) -> tuple[float, float, float, float, float]:
    """``(x, y, w, h, angle_deg)`` from a geometry dict, null-safe."""
    pos = geom.get("position") or {}
    size = geom.get("size") or {}
    return (
        pos.get("x") or 0.0,
        pos.get("y") or 0.0,
        size.get("width") or 0.0,
        size.get("height") or 0.0,
        geom.get("angle") or 0.0,
    )


def _is_rotated(angle_deg: float) -> bool:
    """True when ``angle_deg`` is not a multiple of 360 (within :data:`_ANGLE_EPS`)."""
    a = angle_deg % 360.0
    return min(a, 360.0 - a) > _ANGLE_EPS


# --------------------------------------------------------------------------
# The rotation primitive: a point transform mapping a frame's LOCAL coordinate
# (origin at the un-rotated top-left, ranging over ``[0,w]x[0,h]``) to its
# absolute placement, rotating about the frame's own centre.
#
#     transform(p) = R(theta) . (p - (w/2, h/2)) + (x + w/2, y + h/2)
# --------------------------------------------------------------------------
def _frame_transform(x: float, y: float, w: float, h: float, angle_deg: float
                     ) -> Callable[[float, float], tuple[float, float]]:
    """A ``f(local_x, local_y) -> (abs_x, abs_y)`` for the given frame."""
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = x + w / 2.0, y + h / 2.0

    def f(local_x: float, local_y: float) -> tuple[float, float]:
        dx, dy = local_x - w / 2.0, local_y - h / 2.0
        return (cos_t * dx - sin_t * dy + cx, sin_t * dx + cos_t * dy + cy)

    return f


def _corners_aabb(transform: Callable[[float, float], tuple[float, float]],
                  w: float, h: float) -> tuple[float, float, float, float]:
    """AABB ``(x0, y0, x1, y1)`` of a ``w x h`` rect's corners through ``transform``."""
    pts = [transform(0.0, 0.0), transform(w, 0.0), transform(w, h), transform(0.0, h)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _frame_rect(geom: dict) -> tuple[float, float, float, float]:
    """Composed ``(x, y, w, h)`` for a plain (possibly rotated) frame.

    JXA reports a rotated frame as the AABB top-left of the four rotated corners,
    but keeps the size UN-rotated. Un-rotated frames pass straight through. Used
    for unmasked images/movies, shapes, and fixed text boxes — all share this rule.
    """
    x, y, w, h, angle = _xywha(geom)
    if not _is_rotated(angle):
        return (x, y, w, h)
    x0, y0, _x1, _y1 = _corners_aabb(_frame_transform(x, y, w, h, angle), w, h)
    return (x0, y0, w, h)


# --------------------------------------------------------------------------
# Masked image (and any masked movie): the visible box is the mask rectangle
# mapped mask-local -> image-local -> slide, AABB top-left = position, mask's own
# un-rotated (w, h) = size. Axis-aligned this collapses to (img+mask, mask_size).
# --------------------------------------------------------------------------
def _mask_geom(obj: dict, objects: dict[str, dict]) -> dict:
    """The mask's geometry dict for a masked image/movie, via ``mask.identifier``."""
    ref = (obj.get("mask") or {}).get("identifier")
    if ref is None:
        return {}
    return _geom_dict(objects.get(str(ref)) or {})


def _mask_corner_topleft(fx: float, fy: float, fw: float, fh: float, fa: float,
                         mx: float, my: float, mw: float, mh: float, ma: float
                         ) -> tuple[float, float]:
    """AABB top-left of the mask rect mapped mask-local -> image-local -> slide."""
    to_image = _frame_transform(mx, my, mw, mh, ma)   # mask-local -> image-local
    to_slide = _frame_transform(fx, fy, fw, fh, fa)   # image-local -> slide
    x0, y0, _x1, _y1 = _corners_aabb(lambda lx, ly: to_slide(*to_image(lx, ly)), mw, mh)
    return (x0, y0)


def _masked_rect(frame_geom: dict, mask_geom: dict
                 ) -> tuple[tuple[float, float, float, float], bool]:
    """``((x, y, w, h), rotated)`` for a masked frame.

    The mask box is composed at the frame/mask angles SNAPPED to their nearest 90°
    multiple — the clean rotation JXA lays a masked image out at (integer-exact). It is
    VOUCHED (``rotated`` False) only when that snap moved the top-left no more than
    :data:`_MASK_TRUST_PX` from the RAW-angle composition; that displacement bounds the
    error to within ~0.5px integer rounding whatever the offset (see the constant's
    note). A larger displacement means
    a real off-axis residual whose laid-out position the closed form cannot pin down, so
    ``rotated`` is True and the caller flags ``rotated-masked`` → Keynote fallback. At
    snapped 0°/0° the corner AABB collapses to ``(fx+mx, fy+my)`` — the axis-aligned
    frame+mask position JXA reports for an un-rotated masked image.
    """
    fx, fy, fw, fh, fa = _xywha(frame_geom)
    mx, my, mw, mh, ma = _xywha(mask_geom)
    fa_s, ma_s = round(fa / 90.0) * 90.0, round(ma / 90.0) * 90.0
    sx, sy = _mask_corner_topleft(fx, fy, fw, fh, fa_s, mx, my, mw, mh, ma_s)
    rx, ry = _mask_corner_topleft(fx, fy, fw, fh, fa, mx, my, mw, mh, ma)
    displacement = max(abs(sx - rx), abs(sy - ry))
    return ((sx, sy, mw, mh), displacement > _MASK_TRUST_PX)


# --------------------------------------------------------------------------
# Line: the visible segment from its length (natural width) and rotation, about
# the frame centre. Direction/flip-independent because JXA reports the segment's
# bounding-box top-left, and |cos|/|sin| fold every quadrant onto the same box.
# --------------------------------------------------------------------------
def _line_rect(geom: dict) -> tuple[float, float, float, float]:
    """Composed ``(x, y, length, 0)`` for a line frame."""
    x, y, w, h, angle = _xywha(geom)
    length = w  # a line's natural frame is horizontal; its height is 0
    theta = math.radians(angle)
    cx, cy = x + w / 2.0, y + h / 2.0
    return (cx - length / 2.0 * abs(math.cos(theta)),
            cy - length / 2.0 * abs(math.sin(theta)),
            length, 0.0)


# --------------------------------------------------------------------------
# Autosize text: recover x/y(top)/w/h from geometry.position + naturalSize.
# --------------------------------------------------------------------------
def _natural_size(obj: dict) -> tuple[float, float]:
    """``(width, height)`` of a text box's ``bezierPathSource.naturalSize``."""
    pathsource = (obj.get("super") or {}).get("pathsource") or {}
    natural = (pathsource.get("bezierPathSource") or {}).get("naturalSize") or {}
    return (natural.get("width") or 0.0, natural.get("height") or 0.0)


def _autosize_rect(obj: dict, geom: dict) -> tuple[float, float, float, float]:
    """Best-effort ``(x, top, w, h)`` for an autosize (zero-height frame) text box.

    ``geometry.position`` is the box's horizontal-left / vertical-CENTRE anchor, so
    ``top = position.y - h/2``. ``x`` is exact for a left-aligned box; ``w``/``h``
    come from ``naturalSize`` which is stale on ~20% of boxes — hence the caller's
    unconditional ``autosize-soft`` flag.
    """
    x, y, _w, _h, _angle = _xywha(geom)
    nw, nh = _natural_size(obj)
    return (x, y - nh / 2.0, nw, nh)


# --------------------------------------------------------------------------
# Group: union of children's transformed bounds, recursing nested groups under a
# translation-only parent (verified). A ``seen`` set guards a group reached twice.
# --------------------------------------------------------------------------
def _leaf_bbox(obj: dict, ox: float, oy: float, objects: dict[str, dict]
               ) -> tuple[float, float, float, float]:
    """Absolute AABB ``(x0, y0, x1, y1)`` of a leaf child at parent origin ``(ox, oy)``.

    A masked-image child contributes its mask rectangle; every leaf's own rotation
    is folded into its AABB about its own centre. (Rotated masked/zero-size children
    make the union approximate — those groups are flagged ``group-residual``.)
    """
    geom = _geom_dict(obj)
    x, y, w, h, angle = _xywha(geom)
    x += ox
    y += oy
    if obj.get("_pbtype") in ("TSD.ImageArchive", "TSD.MovieArchive"):
        mask_geom = _mask_geom(obj, objects)
        if mask_geom:
            mx, my, mw, mh, _ma = _xywha(mask_geom)
            return _corners_aabb(_frame_transform(x + mx, y + my, mw, mh, angle), mw, mh)
    return _corners_aabb(_frame_transform(x, y, w, h, angle), w, h)


def _is_real_box(box: tuple[float, float, float, float]) -> bool:
    """True when an AABB has BOTH positive width and positive height.

    A zero-extent child — a connector/line whose stored frame is ``w==0`` or
    ``h==0`` and whose local origin can sit hundreds of px off the group's real
    corner (e.g. ``(0, 220, 0, 0)``) — does not bound the group JXA reports, so it
    is held out of the union. (Measured: including such children dragged a group's
    min-corner off by up to ~547px on the gold decks.)
    """
    return (box[2] - box[0]) > 0.0 and (box[3] - box[1]) > 0.0


def _group_union(group_id: str, ox: float, oy: float, objects: dict[str, dict],
                 seen: set[str]) -> tuple[float, float, float, float] | None:
    """Union AABB of a group subtree's REAL children (nested groups add their position).

    Only children with positive width AND height (:func:`_is_real_box`) join the
    union; zero-extent connectors are excluded. Returns ``None`` when no real child
    remains, so the caller falls back to the group's own stored-frame geometry.
    """
    if group_id in seen:
        return None
    seen.add(group_id)
    group = objects.get(group_id)
    if not group:
        return None
    boxes: list[tuple[float, float, float, float]] = []
    for ref in group.get("children") or []:
        child_id = ref.get("identifier")
        if child_id is None:
            continue
        child = objects.get(str(child_id))
        if not child:
            continue
        if child.get("_pbtype") == "TSD.GroupArchive":
            cx, cy, _cw, _ch, _ca = _xywha(_geom_dict(child))
            sub = _group_union(str(child_id), ox + cx, oy + cy, objects, seen)
            if sub is not None and _is_real_box(sub):
                boxes.append(sub)
        else:
            box = _leaf_bbox(child, ox, oy, objects)
            if _is_real_box(box):
                boxes.append(box)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _has_effect_style(obj: dict) -> bool:
    """True when a shadow/reflection effect is present up the ``super`` chain.

    Kept as a defensive residual signal per the plan; NOTE the 7 no-zero-size
    residual groups in the test decks carry no effect style (they are caught by
    :func:`_group_residual_reason`'s rotated-masked-child branch instead).
    """
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        props = cur.get("shapeProperties")
        if isinstance(props, dict) and any(k in props for k in ("shadow", "reflection")):
            return True
        cur = cur.get("super")
    return False


def _group_residual_reason(group_id: str, objects: dict[str, dict], seen: set[str]
                           ) -> bool:
    """True when any leaf descendant makes the child-union approximate.

    Signals (each ships the group with a residual JXA cannot match offline):
      * a zero-size ``ShapeInfoArchive`` (a connector — its drawn box is not its frame);
      * a rotated masked image/movie (mask corners get extra Keynote layout — this is
        the same uncertainty as a top-level ``rotated-masked`` image, inherited by the
        group; it is what actually catches the 7 no-effect-style residual groups);
      * a detectable shadow/reflection effect style.
    """
    if group_id in seen:
        return False
    seen.add(group_id)
    group = objects.get(group_id)
    if not group:
        return False
    for ref in group.get("children") or []:
        child_id = ref.get("identifier")
        if child_id is None:
            continue
        child = objects.get(str(child_id))
        if not child:
            continue
        pbtype = child.get("_pbtype")
        if pbtype == "TSD.GroupArchive":
            # A rotated NESTED group breaks the translation-only union (the parent
            # rotation is handled at the top by rotated-group; a nested one is not),
            # so treat it as a residual.
            if _is_rotated(_xywha(_geom_dict(child))[4]):
                return True
            if _group_residual_reason(str(child_id), objects, seen):
                return True
            continue
        _cx, _cy, cw, ch, cangle = _xywha(_geom_dict(child))
        if pbtype == "TSWP.ShapeInfoArchive" and (cw == 0.0 or ch == 0.0):
            return True
        if pbtype in ("TSD.ImageArchive", "TSD.MovieArchive"):
            mask_geom = _mask_geom(child, objects)
            if mask_geom:
                _mx, _my, _mw, _mh, mangle = _xywha(mask_geom)
                if _is_rotated(cangle) or _is_rotated(mangle):
                    return True
        if _has_effect_style(child):
            return True
    return False


# --------------------------------------------------------------------------
# Per-record composition.
# --------------------------------------------------------------------------
def _compose_record(rec: dict, objects: dict[str, dict]) -> None:
    """Replace ``rec``'s x/y/w/h with composed geometry and add geom_source/needs_keynote.

    Mutates ``rec`` in place (it is a fresh dict from :func:`derive_kind_index`).
    ``kind``/``kindIndex``/``id``/order are never touched.
    """
    obj = objects.get(rec["id"]) or {}
    kind = rec["kind"]
    geom = _geom_dict(obj)
    source = "iwa"
    needs: str | None = None

    if kind == "line":
        x, y, w, h = _line_rect(geom)
        source = "line"

    elif kind == "group":
        gx, gy, gw, gh, gangle = _xywha(geom)
        union = _group_union(rec["id"], gx, gy, objects, set())
        if union:
            x, y, w, h = union[0], union[1], union[2] - union[0], union[3] - union[1]
        else:  # childless / unresolved: fall back to the raw frame
            x, y, w, h = gx, gy, gw, gh
        source = "group-union"
        if _is_rotated(gangle):
            needs = "rotated-group"  # recursion is verified translation-only
        elif _group_residual_reason(rec["id"], objects, set()):
            needs = "group-residual"

    elif kind in ("image", "movie"):
        mask_geom = _mask_geom(obj, objects)
        if mask_geom:
            (x, y, w, h), rotated = _masked_rect(geom, mask_geom)
            source = "mask"
            if rotated:
                needs = "rotated-masked"
        else:
            x, y, w, h = _frame_rect(geom)
            # A mask ref that does not resolve to a geometry: the object IS masked, so
            # the unmasked frame is wrong (JXA reports the mask rect). Flag it rather
            # than ship the frame silently.
            if (obj.get("mask") or {}).get("identifier") is not None:
                needs = "masked-unresolved"

    elif kind == "text":
        _tx, _ty, _tw, th, _ta = _xywha(geom)
        if th == 0.0:  # autosize box: zero-height frame
            x, y, w, h = _autosize_rect(obj, geom)
            source = "autosize"
            needs = "autosize-soft"  # x is good (left-aligned); y/h/w are stale-soft
        else:
            x, y, w, h = _frame_rect(geom)

    else:  # shape (and any other frame-shaped drawable): same rotation rule as image
        x, y, w, h = _frame_rect(geom)

    rec["x"], rec["y"], rec["w"], rec["h"] = x, y, w, h
    rec["geom_source"] = source
    rec["needs_keynote"] = needs


def compose_geometry(slide: dict, objects: dict[str, dict]) -> list[dict]:
    """:func:`derive_kind_index` records with composed JXA-frame geometry.

    Each record keeps its ``id``/``kind``/``kindIndex``/``text``/``duplicateOf`` from
    :func:`derive_kind_index`; ``x``/``y``/``w``/``h`` are REPLACED by the composed
    geometry, and two fields are added:

        * ``geom_source`` — one of :data:`GEOM_SOURCES`.
        * ``needs_keynote`` — ``None`` or a :data:`NEEDS_KEYNOTE_REASONS` reason. A
          flagged record still carries best-effort geometry (never a ``None`` value);
          it marks the object a write path must confirm against Keynote.

    Pure and geometry-only: the addressing (kind, kindIndex, order) is unchanged.
    """
    records = derive_kind_index(slide, objects)
    for rec in records:
        _compose_record(rec, objects)
    return records


def compose_deck_geometry(key_path: str | Path) -> dict[int, list[dict]]:
    """``{slide_index: [records]}`` of composed geometry for every slide.

    ``slide_index`` matches the JXA payload's ``index`` (skipped slides included), so
    a caller can line records up with ``payload["slides"][i]["items"]`` directly.
    Raises ``ImportError`` when the optional ``iwa`` extra is absent (same contract
    as :mod:`obed_edom.iwa_runs` / :func:`iwa_kindindex.derive_deck_kind_index`).
    """
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = _load_deck(key_path)
    return {
        idx: compose_geometry(objects[slide_id], objects)
        for idx, (slide_id, _skipped) in enumerate(slide_order(objects))
        if slide_id in objects
    }
