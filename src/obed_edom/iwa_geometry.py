"""Compose raw IWA frames into JXA-laid-out (x, y, w, h).

Raw vs JXA: masked=mask rect; rotated=AABB position + unrotated size;
groups=child union; autosize=stale naturalSize (flagged autosize-soft).
needs_keynote is always paired with best-effort geometry. Addressing is unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from obed_edom.iwa_kindindex import derive_kind_index

GEOM_SOURCES = ("iwa", "mask", "line", "group-union", "autosize")

# Complete set; flagged records still ship best-effort geometry.
NEEDS_KEYNOTE_REASONS = (
    "rotated-masked", "masked-unresolved", "rotated-group", "group-residual", "autosize-soft",
)

# Un-rotated: AABB collapses to the frame (no rotated-* flag).
_ANGLE_EPS = 0.01

# Displacement gate (not an angle threshold): snap-to-90° vs raw-angle top-left.
# Lever-arm residual can miss by tens of px at 1°. Do not raise; 1.5 sits in the measured gap.
_MASK_TRUST_PX = 1.5


def _geom_dict(obj: dict) -> dict:
    """First geometry dict up the super chain (≤6 hops)."""
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
    a = angle_deg % 360.0
    return min(a, 360.0 - a) > _ANGLE_EPS


def _frame_transform(x: float, y: float, w: float, h: float, angle_deg: float
                     ) -> Callable[[float, float], tuple[float, float]]:
    """Local (origin unrotated TL) → absolute, rotating about the frame centre."""
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = x + w / 2.0, y + h / 2.0

    def f(local_x: float, local_y: float) -> tuple[float, float]:
        dx, dy = local_x - w / 2.0, local_y - h / 2.0
        return (cos_t * dx - sin_t * dy + cx, sin_t * dx + cos_t * dy + cy)

    return f


def _corners_aabb(transform: Callable[[float, float], tuple[float, float]],
                  w: float, h: float) -> tuple[float, float, float, float]:
    pts = [transform(0.0, 0.0), transform(w, 0.0), transform(w, h), transform(0.0, h)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _frame_rect(geom: dict) -> tuple[float, float, float, float]:
    """JXA rotated frame: AABB top-left, unrotated size."""
    x, y, w, h, angle = _xywha(geom)
    if not _is_rotated(angle):
        return (x, y, w, h)
    x0, y0, _x1, _y1 = _corners_aabb(_frame_transform(x, y, w, h, angle), w, h)
    return (x0, y0, w, h)


def _mask_geom(obj: dict, objects: dict[str, dict]) -> dict:
    ref = (obj.get("mask") or {}).get("identifier")
    if ref is None:
        return {}
    return _geom_dict(objects.get(str(ref)) or {})


def _snap90(angle_deg: float) -> float:
    return round(angle_deg / 90.0) * 90.0


def _mask_corner_aabb(fx: float, fy: float, fw: float, fh: float, fa: float,
                      mx: float, my: float, mw: float, mh: float, ma: float
                      ) -> tuple[float, float, float, float]:
    """AABB of mask rect mapped mask-local → image-local → slide."""
    to_image = _frame_transform(mx, my, mw, mh, ma)
    to_slide = _frame_transform(fx, fy, fw, fh, fa)
    return _corners_aabb(lambda lx, ly: to_slide(*to_image(lx, ly)), mw, mh)


def _masked_rect(frame_geom: dict, mask_geom: dict
                 ) -> tuple[tuple[float, float, float, float], bool]:
    """Mask box at snapped 90°; rotated=True when snap displacement > _MASK_TRUST_PX."""
    if not mask_geom:
        return ((0.0, 0.0, 0.0, 0.0), True)
    fx, fy, fw, fh, fa = _xywha(frame_geom)
    mx, my, mw, mh, ma = _xywha(mask_geom)
    sx, sy, _sx1, _sy1 = _mask_corner_aabb(fx, fy, fw, fh, _snap90(fa), mx, my, mw, mh, _snap90(ma))
    rx, ry, _rx1, _ry1 = _mask_corner_aabb(fx, fy, fw, fh, fa, mx, my, mw, mh, ma)
    # Gate on top-left displacement (max-corner matches under residual rotation).
    displacement = max(abs(sx - rx), abs(sy - ry))
    return ((sx, sy, mw, mh), displacement > _MASK_TRUST_PX)


def _line_rect(geom: dict) -> tuple[float, float, float, float]:
    """(x, y, length, 0) from length + rotation about frame centre; |cos|/|sin| fold quadrants."""
    x, y, w, h, angle = _xywha(geom)
    length = w  # a line's natural frame is horizontal; its height is 0
    theta = math.radians(angle)
    cx, cy = x + w / 2.0, y + h / 2.0
    return (cx - length / 2.0 * abs(math.cos(theta)),
            cy - length / 2.0 * abs(math.sin(theta)),
            length, 0.0)


def _natural_size(obj: dict) -> tuple[float, float]:
    pathsource = (obj.get("super") or {}).get("pathsource") or {}
    natural = (pathsource.get("bezierPathSource") or {}).get("naturalSize") or {}
    return (natural.get("width") or 0.0, natural.get("height") or 0.0)


def _autosize_rect(obj: dict, geom: dict) -> tuple[float, float, float, float]:
    """Best-effort (x, top, w, h); position is left/vertical-centre so top = y − h/2. naturalSize is stale."""
    x, y, _w, _h, _angle = _xywha(geom)
    nw, nh = _natural_size(obj)
    return (x, y - nh / 2.0, nw, nh)


def _leaf_bbox(obj: dict, ox: float, oy: float, objects: dict[str, dict]
               ) -> tuple[float, float, float, float]:
    """Absolute AABB of a leaf at parent origin (ox, oy). Masked children use snapped _masked_rect."""
    geom = _geom_dict(obj)
    x, y, w, h, angle = _xywha(geom)
    x += ox
    y += oy
    if obj.get("_pbtype") in ("TSD.ImageArchive", "TSD.MovieArchive"):
        mask_geom = _mask_geom(obj, objects)
        if mask_geom:
            mx, my, mw, mh, ma = _xywha(mask_geom)
            return _mask_corner_aabb(x, y, w, h, _snap90(angle), mx, my, mw, mh, _snap90(ma))
    return _corners_aabb(_frame_transform(x, y, w, h, angle), w, h)


def _is_real_box(box: tuple[float, float, float, float]) -> bool:
    """Positive w and h. Zero-extent connectors must not bound the group union."""
    return (box[2] - box[0]) > 0.0 and (box[3] - box[1]) > 0.0


def _group_union(group_id: str, ox: float, oy: float, objects: dict[str, dict],
                 seen: set[str]) -> tuple[float, float, float, float] | None:
    """Union AABB of real children; nested groups add position. None if none remain."""
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
    """True if a descendant makes the child-union approximate (zero-size connector, off-axis mask, effect, rotated nested group)."""
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
            # Nested rotation breaks translation-only union (parent rotation is rotated-group).
            if _is_rotated(_xywha(_geom_dict(child))[4]):
                return True
            if _group_residual_reason(str(child_id), objects, seen):
                return True
            continue
        _cx, _cy, cw, ch, _cangle = _xywha(_geom_dict(child))
        if pbtype == "TSWP.ShapeInfoArchive" and (cw == 0.0 or ch == 0.0):
            return True
        if pbtype in ("TSD.ImageArchive", "TSD.MovieArchive"):
            mask_geom = _mask_geom(child, objects)
            if mask_geom:
                # Same displacement gate as top-level masked images (near-90 children compose).
                _rect, off_axis = _masked_rect(_geom_dict(child), mask_geom)
                if off_axis:
                    return True
        if _has_effect_style(child):
            return True
    return False


def _compose_record(rec: dict, objects: dict[str, dict]) -> None:
    """Mutate rec x/y/w/h + geom_source/needs_keynote. Never touches kind/kindIndex/id/order."""
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
        else:
            x, y, w, h = gx, gy, gw, gh
        source = "group-union"
        if _is_rotated(gangle):
            needs = "rotated-group"  # union is translation-only
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
            # Masked but mask geom missing: unmasked frame is wrong.
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

    else:  # shape: same AABB + unrotated-size rule as image
        x, y, w, h = _frame_rect(geom)

    rec["x"], rec["y"], rec["w"], rec["h"] = x, y, w, h
    rec["geom_source"] = source
    rec["needs_keynote"] = needs


def compose_geometry(slide: dict, objects: dict[str, dict]) -> list[dict]:
    """derive_kind_index records with composed JXA-frame geometry; addressing unchanged."""
    records = derive_kind_index(slide, objects)
    for rec in records:
        _compose_record(rec, objects)
    return records


def compose_deck_geometry(key_path: str | Path) -> dict[int, list[dict]]:
    """{slide_index: [records]} matching JXA payload index (skipped slides included)."""
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = _load_deck(key_path)
    return {
        idx: compose_geometry(objects[slide_id], objects)
        for idx, (slide_id, _skipped) in enumerate(slide_order(objects))
        if slide_id in objects
    }
