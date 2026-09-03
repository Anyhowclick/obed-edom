"""Offline reconstruction of Keynote's per-slide ``(kind, kindIndex)`` addressing.

Matches JXA ``collectItems`` order so remap can address without a full inspect.
``reconcile_counts`` is cardinality-only: image/group order still needs composed
geometry before a write. Tables/charts are omitted because JXA never enumerates them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Same six kinds, same order as inspect_keynote.js collectItems. No tables/charts.
KIND_ORDER = ("text", "image", "shape", "movie", "group", "line")

_PBTYPE_KIND = {
    "TSD.ImageArchive": "image",
    "TSD.MovieArchive": "movie",
    "TSD.GroupArchive": "group",
}

# Empty title/body placeholders JXA appends last; not in drawablesZOrder.
TEXT_PLACEHOLDER_SLACK = 2


def _geometry(obj: dict) -> tuple[float | None, float | None, float | None, float | None]:
    """First ``geometry`` up ``super``. Unmasked/autosize/group frames diverge from JXA — not for writes."""
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        geom = cur.get("geometry")
        if isinstance(geom, dict):
            pos = geom.get("position") or {}
            size = geom.get("size") or {}
            return (pos.get("x"), pos.get("y"), size.get("width"), size.get("height"))
        cur = cur.get("super")
    return (None, None, None, None)


def _owned_text(obj: dict, objects: dict[str, dict]) -> str:
    ref = (obj.get("ownedStorage") or {}).get("identifier")
    if ref is None:
        return ""
    storage = objects.get(str(ref))
    return "".join(storage.get("text") or []) if storage else ""


def _bezier(obj: dict) -> dict:
    return ((obj.get("super") or {}).get("pathsource") or {}).get("bezierPathSource") or {}


def _is_line(obj: dict) -> bool:
    """Open two-point bezier or a zero natural dimension. Multi-point freeforms are shapes."""
    bez = _bezier(obj)
    if not bez:
        return False
    natural = bez.get("naturalSize") or {}
    if natural.get("width") == 0.0 or natural.get("height") == 0.0:
        return True
    elements = (bez.get("path") or {}).get("elements") or []
    return [e.get("type") for e in elements] == ["moveTo", "lineTo"]


def _has_custom_shape_path(obj: dict) -> bool:
    """Custom-path text boxes are duals (textItems AND shapes)."""
    pathsource = (obj.get("super") or {}).get("pathsource") or {}
    return bool(pathsource.get("editableBezierPathSource"))


def _shape_memberships(obj: dict) -> list[str]:
    """``isTextBox`` drives textItems; shapes = not textbox or custom path. Lines first."""
    if _is_line(obj):
        return ["line"]
    is_textbox = bool(obj.get("isTextBox"))
    kinds: list[str] = []
    if is_textbox:
        kinds.append("text")
    if (not is_textbox) or _has_custom_shape_path(obj):
        kinds.append("shape")
    return kinds


def _memberships(obj: dict) -> list[str]:
    simple = _PBTYPE_KIND.get(obj.get("_pbtype"))
    if simple:
        return [simple]
    if obj.get("_pbtype") == "TSWP.ShapeInfoArchive":
        return _shape_memberships(obj)
    return []


def derive_kind_index(slide: dict, objects: dict[str, dict]) -> list[dict]:
    """``(kind, kindIndex)`` in JXA payload order. Duals emit two records; placeholders omitted."""
    counters: dict[str, int] = {}
    buckets: dict[str, list[dict]] = {kind: [] for kind in KIND_ORDER}
    for ref in slide.get("drawablesZOrder", []):
        ident = str(ref.get("identifier"))
        obj = objects.get(ident)
        if not obj:
            continue
        kinds = _memberships(obj)
        if not kinds:
            continue
        x, y, w, h = _geometry(obj)
        text = _owned_text(obj, objects)
        assigned: dict[str, int] = {}
        for kind in kinds:
            assigned[kind] = counters.get(kind, 0)
            counters[kind] = assigned[kind] + 1
        for kind in kinds:
            rec = {
                "id": ident,
                "kind": kind,
                "kindIndex": assigned[kind],
                "x": x, "y": y, "w": w, "h": h,
                "text": text,
            }
            if kind == "shape" and "text" in assigned:
                rec["duplicateOf"] = {"kind": "text", "kindIndex": assigned["text"]}
            buckets[kind].append(rec)
    out: list[dict] = []
    for kind in KIND_ORDER:
        out.extend(buckets[kind])
    return out


def derive_deck_kind_index(key_path: str | Path) -> dict[int, list[dict]]:
    """``{slide_index: records}`` including skipped slides. Raises if the ``iwa`` extra is missing."""
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = _load_deck(key_path)
    return {
        idx: derive_kind_index(objects[slide_id], objects)
        for idx, (slide_id, _skipped) in enumerate(slide_order(objects))
        if slide_id in objects
    }


def derived_kind_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["kind"]] = counts.get(rec["kind"], 0) + 1
    return counts


def deck_kind_counts(deck: str | Path) -> dict[int, dict[str, int]]:
    """``{1-based slide number: derived_kind_counts}`` for every slide, one ``_load_deck``.

    ``derive_deck_kind_index`` keys 0-based; this is the reconcile-base call site's
    convention (``patch_deck_geometry``'s ``specs_by_slide``), so it re-derives rather
    than reindex the 0-based dict.
    """
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = _load_deck(deck)
    return {
        idx + 1: derived_kind_counts(derive_kind_index(objects[slide_id], objects))
        for idx, (slide_id, _skipped) in enumerate(slide_order(objects))
        if slide_id in objects
    }


def kind_counts_from_records(records_by_slide: dict[int, list[dict]]) -> dict[int, dict[str, int]]:
    """Per-slide ``derived_kind_counts`` from already-derived records (no I/O)."""
    return {n: derived_kind_counts(recs) for n, recs in records_by_slide.items()}


def reconcile_counts(
    derived: dict[str, int],
    keynote: dict[str, int],
    *,
    text_slack: int = TEXT_PLACEHOLDER_SLACK,
) -> list[str]:
    """Mismatched kinds (empty = safe). Text may exceed derived by ``text_slack`` placeholders."""
    mismatches: list[str] = []
    for kind in set(derived) | set(keynote):
        d, k = derived.get(kind, 0), keynote.get(kind, 0)
        if kind == "text" and 0 <= (k - d) <= text_slack:
            continue
        if d != k:
            mismatches.append(kind)
    return sorted(mismatches)
