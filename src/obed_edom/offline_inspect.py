"""Offline JXA-shaped wall inspect from the IWA graph (write-path input).

Plan-equivalence, not "true" values: omit childCount/children (JXA reports 0/[]
on groups), emit buildCount 0, omit runs. JXA color is colour-managed and not
equal to IWA sRGB. Raises ImportError without the ``iwa`` extra.
"""
from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Any

from obed_edom.iwa_geometry import _geom_dict, _is_rotated, _mask_geom, _xywha, compose_geometry
from obed_edom.iwa_runs import resolve_style

# Only autosize-soft is vouched (Keynote re-autosizes on write). group-residual is a real write divergence.
VOUCHED_NEEDS_KEYNOTE = frozenset({"autosize-soft"})

# Offline geometry is inexact for these; bulk Keynote overwrites their frames.
BULK_KINDS = frozenset({"group", "image", "movie", "text"})

# Best-effort offline frames; unconfirmed items force a slide fallback.
SOFT_GEOM_SOURCES = frozenset({"group-union", "autosize"})

# Geometry-only; cleared after a bulk overwrite. autosize-soft is already vouched.
GEOMETRY_GUARD_REASONS = frozenset(
    {"rotated-masked", "masked-unresolved", "rotated-group", "group-residual"}
)

# Content the bulk geometry read does not touch; still forces per-slide fallback.
CONTENT_GUARD_REASONS = frozenset({"font-size-unresolved", "filename-dirty"})

# Zip member ``Data/name-<dataId>.ext``; ``-<dataId>`` is Keynote's, not the reported filename.
_DATA_MEMBER = re.compile(r"^Data/(?P<base>.+)-(?P<id>\d+)\.(?P<ext>[^.]+)$")


def _round_pt(value: float) -> int:
    """Whole-point JXA geometry (half away from 0). Sub-pixel drift amplifies through the affine."""
    return int(math.floor(value + 0.5)) if value >= 0 else int(math.ceil(value - 0.5))


def _build_data_index(zip_names: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name in zip_names:
        m = _DATA_MEMBER.match(name)
        if not m:
            continue
        index[m.group("id")] = f"{m.group('base')}.{m.group('ext')}"
    return index


def _data_identifier(obj: dict) -> str | None:
    for key in ("data", "movieData"):
        ref = (obj.get(key) or {}).get("identifier")
        if ref is not None:
            return str(ref)
    return None


def _entry_sid(entry: dict) -> str | None:
    ref = entry.get("object")
    if ref and "identifier" in ref:
        return str(ref["identifier"])
    return None


def _leading_sid(table: dict | None) -> str | None:
    entries = (table or {}).get("entries") or []
    best: tuple[int, str | None] | None = None
    for entry in entries:
        idx = int(entry.get("characterIndex", 0))
        if best is None or idx < best[0]:
            best = (idx, _entry_sid(entry))
    if best is None or best[0] != 0:
        return None
    return best[1]


def _storage_of(obj: dict, objects: dict[str, dict]) -> dict | None:
    ref = (obj.get("ownedStorage") or {}).get("identifier")
    if ref is None:
        return None
    storage = objects.get(str(ref))
    return storage if storage and storage.get("_pbtype") == "TSWP.StorageArchive" else None


def _item_text_style(
    obj: dict, objects: dict[str, dict], cache: dict
) -> tuple[str | None, float | None, list[int] | None]:
    """Leading-run (font, size, color65535). Char then paragraph; color is IWA×257, not JXA colour-managed."""
    storage = _storage_of(obj, objects)
    if storage is None:
        return (None, None, None)
    char_sid = _leading_sid(storage.get("tableCharStyle"))
    para_sid = _leading_sid(storage.get("tableParaStyle"))
    cstyle = resolve_style(char_sid, objects, cache) if char_sid else None
    pstyle = resolve_style(para_sid, objects, cache) if para_sid else None

    def pick(field: str) -> Any:
        if cstyle is not None and cstyle.get(field) is not None:
            return cstyle[field]
        if pstyle is not None and pstyle.get(field) is not None:
            return pstyle[field]
        return None

    font = pick("fontName")
    size = pick("size")
    color255 = pick("color")
    color = [max(0, min(65535, int(round(c * 257)))) for c in color255] if color255 else None
    return (font, size, color)


def _locked(obj: dict) -> bool:
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        if "locked" in cur:
            return bool(cur.get("locked"))
        cur = cur.get("super")
    return False


def _line_direction(obj: dict) -> tuple[float, float]:
    cur: Any = obj
    pathsource: dict = {}
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        ps = cur.get("pathsource")
        if isinstance(ps, dict):
            pathsource = ps
            break
        cur = cur.get("super")
    bez = pathsource.get("bezierPathSource") or {}
    path = bez.get("path") or {}
    elements = path.get("elements") or bez.get("elements") or []
    pts: list[tuple[float, float]] = []
    for el in elements:
        for p in el.get("points") or []:
            pts.append((p.get("x") or 0.0, p.get("y") or 0.0))
    if len(pts) >= 2:
        dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
    else:
        dx, dy = 1.0, 0.0
    norm = math.hypot(dx, dy)
    if norm == 0.0:
        dx, dy, norm = 1.0, 0.0, 1.0
    ux, uy = dx / norm, dy / norm
    if pathsource.get("horizontalFlip"):
        ux = -ux
    if pathsource.get("verticalFlip"):
        uy = -uy
    return ux, uy


def _line_endpoints(obj: dict) -> tuple[list[float], list[float]]:
    """JXA start/end: centre ± (L/2)·R(-angle)·direction. Naive (cos,sin) draws the opposite diagonal."""
    x, y, w, h, angle = _xywha(_geom_dict(obj))
    length = w  # a line's natural frame is horizontal; its height is 0
    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = x + w / 2.0, y + h / 2.0
    ux, uy = _line_direction(obj)
    ex, ey = length / 2.0 * ux, length / 2.0 * uy

    def rot(dx: float, dy: float) -> tuple[float, float]:  # R(-theta) . (dx, dy)
        return (dx * cos_t + dy * sin_t, -dx * sin_t + dy * cos_t)

    sx, sy = rot(-ex, -ey)
    tx, ty = rot(ex, ey)
    return ([cx + sx, cy + sy], [cx + tx, cy + ty])


_TEXTUAL = frozenset({"text", "shape"})
_ASSET = frozenset({"image", "movie"})


def _item_from_record(
    rec: dict,
    objects: dict[str, dict],
    data_index: dict[str, str],
    style_cache: dict,
) -> tuple[dict[str, Any], str | None]:
    """JXA-shaped item plus guard reason (None if vouched). Omits master/runs/childCount."""
    obj = objects.get(rec["id"]) or {}
    kind = rec["kind"]
    # Masked rotation is frame+mask net angle (JXA's visible rotation).
    angle = _xywha(_geom_dict(obj))[4]
    if kind in _ASSET:
        mask_geom = _mask_geom(obj, objects)
        if mask_geom:
            angle += _xywha(mask_geom)[4]
    # Round to whole points: sub-pixel affine fit amplifies into a deck-wide cascade.
    item: dict[str, Any] = {
        "kind": kind,
        "kindIndex": rec["kindIndex"],
        "x": _round_pt(rec["x"]),
        "y": _round_pt(rec["y"]),
        "w": _round_pt(rec["w"]),
        "h": _round_pt(rec["h"]),
        "text": rec.get("text") or "",
        "size": 0,
        "font": "",
        "color": None,
        "fileName": "",
        # Whole-degree [0,360); fractional rotation churns the reuse fingerprint.
        "rotation": _round_pt(angle) % 360,
        "locked": _locked(obj),
        "buildCount": 0,
    }
    if rec.get("duplicateOf") is not None:
        item["duplicateOf"] = rec["duplicateOf"]

    reason: str | None = None
    needs = rec.get("needs_keynote")
    if needs is not None and needs not in VOUCHED_NEEDS_KEYNOTE:
        reason = needs

    if kind in _TEXTUAL:
        font, size, color = _item_text_style(obj, objects, style_cache)
        item["font"] = font or ""
        item["size"] = size if size is not None else 0
        item["color"] = color
        if (item["text"] or "").strip() and (font is None or size is None):
            reason = reason or "font-size-unresolved"
    elif kind in _ASSET:
        data_id = _data_identifier(obj)
        if data_id is not None:
            name = data_index.get(data_id)
            if name is None:
                reason = reason or "filename-dirty"
            else:
                item["fileName"] = name
    if kind == "line":
        start, end = _line_endpoints(obj)
        item["start"] = [_round_pt(start[0]), _round_pt(start[1])]
        item["end"] = [_round_pt(end[0]), _round_pt(end[1])]
    return item, reason


def _canvas_size(objects: dict[str, dict]) -> tuple[float, float]:
    """ShowArchive.size, else 1920×1080 (JXA fallback)."""
    for obj in objects.values():
        if obj.get("_pbtype") == "KN.ShowArchive":
            size = obj.get("size") or {}
            w, h = size.get("width"), size.get("height")
            if w and h:
                return (float(w), float(h))
            break
    return (1920.0, 1080.0)


def offline_wall_payload(
    key_path: str | Path, slide_range: Any = None, *, deck: Any = None
) -> dict[str, Any]:
    """JXA inspect-shaped wall payload plus ``_offline`` guard sidecar. ``deck`` shares one IWA decode."""
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    with zipfile.ZipFile(key_path) as zf:
        data_index = _build_data_index(zf.namelist())
    width, height = _canvas_size(objects)
    order = slide_order(objects)

    style_cache: dict = {}
    slides_out: list[dict[str, Any]] = []
    guard: list[dict[str, Any]] = []
    soft_geometry: list[dict[str, Any]] = []
    for index, (slide_id, skipped) in enumerate(order):
        slide = objects.get(slide_id)
        if slide is None:
            continue
        records = compose_geometry(slide, objects)
        items: list[dict[str, Any]] = []
        for item_index, rec in enumerate(records):
            item, reason = _item_from_record(rec, objects, data_index, style_cache)
            item["index"] = item_index
            items.append(item)
            if reason is not None:
                guard.append(
                    {
                        "slide": index + 1,
                        "kind": item["kind"],
                        "kindIndex": item["kindIndex"],
                        "reason": reason,
                    }
                )
            if (
                item["kind"] in BULK_KINDS
                and (
                    rec.get("geom_source") in SOFT_GEOM_SOURCES
                    or rec.get("needs_keynote") in GEOMETRY_GUARD_REASONS
                )
            ):
                soft_geometry.append(
                    {"slide": index + 1, "kind": item["kind"], "kindIndex": item["kindIndex"]}
                )
        slides_out.append(
            {
                "index": index,
                "number": index + 1,
                "skipped": bool(skipped),
                "items": items,
            }
        )

    tripped = _guard_tripped(guard, slide_range)
    return {
        "path": str(key_path),
        "slideWidth": width,
        "slideHeight": height,
        "slideCount": len(slides_out),
        "slides": slides_out,
        "_offline": {
            "guard": guard,
            "tripped": tripped,
            "soft_geometry": soft_geometry,
        },
    }


def _guard_tripped(guard: list[dict[str, Any]], slide_range: Any) -> bool:
    if not guard:
        return False
    if slide_range is None:
        return True
    from obed_edom.map_remap import wants_slide  # noqa: PLC0415 (avoid import cycle at load)

    return any(wants_slide(int(flag["slide"]), slide_range) for flag in guard)


def unvouched_items(payload: dict[str, Any], slide_range: Any = None) -> list[dict[str, Any]]:
    """Range-scoped ``_offline.guard`` flags. Any flag means the offline read is untrusted."""
    guard = ((payload.get("_offline") or {}).get("guard")) or []
    if slide_range is None:
        return list(guard)
    from obed_edom.map_remap import wants_slide  # noqa: PLC0415

    return [flag for flag in guard if wants_slide(int(flag["slide"]), slide_range)]


def _is_placeholder_row(row: list | None, width: float, height: float) -> bool:
    """JXA empty placeholder: at origin AND degenerate size. Either alone is a real box."""
    if not row or len(row) < 4:
        return False
    x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
    at_origin = abs(x) < 1.0 and abs(y) < 1.0
    degenerate = w < 1.0 or h < 1.0
    return at_origin and degenerate


def _splice_bulk_geometry(
    payload: dict[str, Any], bulk: dict[int, dict[str, list]]
) -> tuple[set[tuple[int, str, int]], set[tuple[int, str]]]:
    """Overwrite BULK_KINDS x/y/w/h from bulk. Count mismatch leaves that kind unspliced (kindIndex desync)."""
    from obed_edom.iwa_kindindex import (  # noqa: PLC0415
        TEXT_PLACEHOLDER_SLACK,
        reconcile_counts,
    )

    width = float(payload.get("slideWidth") or 0.0)
    height = float(payload.get("slideHeight") or 0.0)
    spliced: set[tuple[int, str, int]] = set()
    count_mismatch: set[tuple[int, str]] = set()
    for slide in payload.get("slides") or []:
        index = int(slide.get("index") or 0)
        number = int(slide.get("number") or (index + 1))
        rows_by_kind = bulk.get(index)
        if not rows_by_kind:
            continue
        items = slide.get("items") or []
        derived: dict[str, int] = {}
        for item in items:
            kind = item.get("kind")
            if kind in BULK_KINDS:
                derived[kind] = derived.get(kind, 0) + 1
        keynote = {
            kind: len(rows)
            for kind, rows in rows_by_kind.items()
            if kind in BULK_KINDS and rows is not None
        }
        bad_kinds = set(reconcile_counts(derived, keynote))
        extra = keynote.get("text", 0) - derived.get("text", 0)
        if "text" not in bad_kinds and 1 <= extra <= TEXT_PLACEHOLDER_SLACK:
            tail = (rows_by_kind.get("text") or [])[-extra:]
            if not (tail and all(_is_placeholder_row(r, width, height) for r in tail)):
                bad_kinds.add("text")
        count_mismatch.update((number, kind) for kind in bad_kinds)
        for item in items:
            kind = item.get("kind")
            if kind not in BULK_KINDS or kind in bad_kinds:
                continue
            rows = rows_by_kind.get(kind)
            if rows is None:
                continue
            ki = int(item.get("kindIndex", -1))
            if ki < 0 or ki >= len(rows):
                continue
            row = rows[ki]
            if row is None or len(row) < 4:
                continue
            x, y, w, h = row[0], row[1], row[2], row[3]
            item["x"] = _round_pt(float(x))
            item["y"] = _round_pt(float(y))
            item["w"] = _round_pt(float(w))
            item["h"] = _round_pt(float(h))
            spliced.add((number, kind, ki))
    return spliced, count_mismatch


def _fn_accepts_log(fn: Any) -> bool:
    """True when ``fn`` declares a ``log`` parameter (by name, or via ``**kwargs``) --
    signature inspection, never a call-and-catch-TypeError probe (which could mask a
    genuine bug inside ``fn`` as "doesn't accept log")."""
    import inspect as _pyinspect  # noqa: PLC0415 — stdlib, distinct from obed_edom.inspect

    try:
        params = _pyinspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "log" in params or any(
        p.kind == _pyinspect.Parameter.VAR_KEYWORD for p in params.values()
    )


def two_tier_wall_payload(
    key_path: str | Path,
    bulk_geometry_fn: Any = None,
    slide_range: Any = None,
    *,
    deck: Any = None,
    log: Any = None,
) -> dict[str, Any]:
    """Offline payload with bulk overwrite of soft geometry. Fallback is per class/slide
    unless bulk fails. ``log`` (the caller's operator-facing ``say``) is forwarded to
    ``bulk_geometry_fn`` ONLY when that callable actually accepts a ``log`` kwarg
    (:func:`_fn_accepts_log`) -- a test double built with a bare ``(key_path, slides=None)``
    signature must keep working unmodified."""
    payload = offline_wall_payload(key_path, slide_range, deck=deck)
    sidecar = payload.setdefault("_offline", {})
    guard = sidecar.get("guard") or []
    soft = sidecar.get("soft_geometry") or []
    skipped_numbers = {
        int(s.get("number") or (int(s.get("index") or 0) + 1))
        for s in payload.get("slides") or []
        if s.get("skipped")
    }

    content_flags = [f for f in guard if f.get("reason") in CONTENT_GUARD_REASONS]

    if bulk_geometry_fn is None:
        fallback = content_flags + [{**s, "reason": "bulk-missing"} for s in soft]
        _finalize_two_tier(payload, sidecar, bulk_ok=False, spliced=0, fallback=fallback,
                           slide_range=slide_range, bulk_slides=0, skipped_numbers=skipped_numbers,
                           bulk_errors=[], bulk_notes=[])
        return payload

    live = [
        int(s.get("number") or (int(s.get("index") or 0) + 1))
        for s in payload.get("slides") or []
        if not s.get("skipped")
    ]
    wanted = live
    if slide_range is not None:
        from obed_edom.map_remap import slides_for_plan  # noqa: PLC0415

        wanted = sorted(set(live) & set(slides_for_plan(slide_range) or []))
    bulk_kwargs: dict[str, Any] = {"slides": wanted}
    if log is not None and _fn_accepts_log(bulk_geometry_fn):
        bulk_kwargs["log"] = log
    try:
        # bulk_geometry reads the WHOLE deck for an empty list; nothing wants a skipped
        # slide. Subset relies on bulk_geometry_fn honouring `slides`.
        bulk = bulk_geometry_fn(key_path, **bulk_kwargs) if wanted else {}
    except Exception:  # noqa: BLE001 — any bulk failure => tier 2 unavailable
        fallback = content_flags + [{**s, "reason": "bulk-missing"} for s in soft]
        _finalize_two_tier(payload, sidecar, bulk_ok=False, spliced=0, fallback=fallback,
                           slide_range=slide_range, bulk_slides=0, skipped_numbers=skipped_numbers,
                           bulk_errors=[], bulk_notes=[])
        return payload

    # `inspect.LAST_BULK_ERRORS`/`LAST_BULK_NOTES` are set by the LAST `bulk_geometry()`
    # call ANY caller in this process made -- stale/ambiguous if read later. Snapshot
    # HERE, immediately after THIS call, and thread through explicitly (never re-read
    # downstream). Each entry is stamped with the `path` it came from (inspect.py); drop
    # anything whose path isn't OURS -- extra insurance if the snapshot is ever somehow
    # delayed past another caller's own bulk_geometry() call.
    bulk_errors: list[dict[str, Any]] = []
    bulk_notes: list[dict[str, Any]] = []
    if wanted:
        try:
            from obed_edom import inspect as _inspect_mod  # noqa: PLC0415

            own_path = str(Path(key_path).expanduser().resolve())
            bulk_errors = [
                e for e in (getattr(_inspect_mod, "LAST_BULK_ERRORS", None) or [])
                if e.get("path") == own_path
            ]
            bulk_notes = [
                n for n in (getattr(_inspect_mod, "LAST_BULK_NOTES", None) or [])
                if n.get("path") == own_path
            ]
        except ImportError:
            bulk_errors = []
            bulk_notes = []

    spliced, count_mismatch = _splice_bulk_geometry(payload, bulk or {})
    unconfirmed = [
        {**s, "reason": "bulk-missing"}
        for s in soft
        if (int(s["slide"]), s["kind"], int(s["kindIndex"])) not in spliced
    ]
    # Count mismatch: kindIndex may be desynced; fall the slide back even with no soft item.
    count_flags = [
        {"slide": number, "kind": kind, "kindIndex": -1, "reason": "count-mismatch"}
        for number, kind in sorted(count_mismatch)
    ]
    fallback = content_flags + unconfirmed + count_flags
    _finalize_two_tier(payload, sidecar, bulk_ok=True, spliced=len(spliced),
                       fallback=fallback, slide_range=slide_range,
                       bulk_slides=len(wanted), skipped_numbers=skipped_numbers,
                       bulk_errors=bulk_errors, bulk_notes=bulk_notes)
    return payload


def _finalize_two_tier(
    payload: dict[str, Any],
    sidecar: dict[str, Any],
    *,
    bulk_ok: bool,
    spliced: int,
    fallback: list[dict[str, Any]],
    slide_range: Any,
    bulk_slides: int,
    skipped_numbers: set[int],
    bulk_errors: list[dict[str, Any]],
    bulk_notes: list[dict[str, Any]],
) -> None:
    if slide_range is not None:
        from obed_edom.map_remap import wants_slide  # noqa: PLC0415

        fallback = [f for f in fallback if wants_slide(int(f["slide"]), slide_range)]
    fallback = [
        f for f in fallback
        if int(f["slide"]) not in skipped_numbers or f.get("reason") == "filename-dirty"
    ]
    sidecar["bulk_ok"] = bulk_ok
    sidecar["spliced"] = spliced
    sidecar["bulk_slides"] = bulk_slides
    sidecar["skipped"] = len(skipped_numbers)
    sidecar["fallback"] = fallback
    sidecar["fallback_slides"] = sorted({int(f["slide"]) for f in fallback})
    # tripped = whole deck cannot be served two-tier (bulk unavailable and fallback nonempty).
    sidecar["tripped"] = bool(not bulk_ok and fallback)
    # bulk_geometry.js's own per-collection/bulk-property/item failures (otherwise
    # invisible -- a "bulk-missing" fallback carries no reason why), threaded in
    # EXPLICITLY by the caller (never re-read from module-global state here -- it can go
    # stale between calls). Sidecar copy PLUS a non-underscore top-level key: the
    # cache-write strips every "_"-prefixed key (inspect.py), so `bulkErrors` (like
    # `reader`) is what actually survives into a cached payload.
    sidecar["bulk_errors"] = list(bulk_errors)
    payload["bulkErrors"] = list(bulk_errors)
    # Notes are informational-only (never gate) and stay under the sidecar -- unlike
    # bulk_errors they are NOT promoted to a non-underscore key, so they do NOT survive
    # into the cached payload.
    sidecar["bulk_notes"] = list(bulk_notes)
