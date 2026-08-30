"""Offline reconstruction of Keynote's per-slide ``(kind, kindIndex)`` addressing.

``remap`` resolves every object it moves as ``<kind> (kindIndex)`` — the position of
an object within its scripting collection (``slide.textItems()``, ``.images()``,
``.shapes()``, ``.movies()``, ``.groups()``, ``.lines()``). Reading that from Keynote
costs the ~12-minute per-object inspect. This module derives the *same* addressing
directly from the deck's decoded IWA graph in ~0.4 s, so a remap can address objects
without the slow read — GUARDED by a cheap per-kind ``count`` check (see
:func:`reconcile_counts`), because a wrong index would write a mis-placed object into
the user's deck.

Reverse-engineered and differential-tested (2026-08-29) against fresh exact-bytes JXA
payloads on ``Map_Extracted_Wall_1st`` (8 slides) and ``Full_Report_Card_Wall`` (155).
What is actually established, by kind:
    * **text** — order VERIFIED by content (0 mis-orders, ~1980 pairs); count exact
      bar 0-2 trailing empty placeholders (see :data:`TEXT_PLACEHOLDER_SLACK`).
    * **shape, line, movie** — order VERIFIED by geometry (small, non-degenerate
      deltas); counts exact.
    * **image, group** — counts exact, but per-kind ORDER is only *inferred* from the
      shared z-order walk (raw IWA geometry can't confirm it: masked-image bounds and
      stale group frames diverge from JXA). It becomes geometry-verifiable once the
      composed geometry is used (mask-rect for masked images -> 96.6% within 2px;
      union-of-transformed-children for groups -> ~89%), leaving only truly-coincident
      objects, which are harmless to swap. So a WRITE that addresses images/groups by
      this kindIndex must first confirm their order against composed (not raw-IWA)
      geometry — the cardinality-only :func:`reconcile_counts` is necessary but NOT
      sufficient for those two kinds. The lone hard count-miss is Full slide 73 (a
      filled/variation text box JXA lists in both textItems and shapes), which the
      count guard catches and falls back on.
Full rule statement, the geometry-composition formulas, and the write caveat live in
the SKILL under "``kindIndex`` IS reconstructible offline".

Public entry points:
    * :func:`derive_kind_index` — pure ``(slide, objects) -> [records]`` for one slide.
    * :func:`derive_deck_kind_index` — whole deck, ``{slide_index: [records]}``.
    * :func:`derived_kind_counts` / :func:`reconcile_counts` — the count guard.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# JXA collectItems (inspect_keynote.js:500-505) collects EXACTLY these six kinds in
# this order, and kindIndex is assigned per kind in it — load-bearing for both the
# payload item order and remap's addressing. Tables and charts are deliberately absent:
# collectItems never enumerates them, so neither does derive (a table object falls
# through _memberships to no kind, matching JXA, rather than becoming a phantom record
# that would force the count guard to fall back on every table slide).
KIND_ORDER = ("text", "image", "shape", "movie", "group", "line")

# The one-to-one archive kinds; the ambiguous TSWP.ShapeInfoArchive (text / shape /
# line) is resolved by :func:`_shape_memberships`.
_PBTYPE_KIND = {
    "TSD.ImageArchive": "image",
    "TSD.MovieArchive": "movie",
    "TSD.GroupArchive": "group",
}

# JXA text-collection count may exceed derive's by this many EMPTY title/body
# placeholders (KN.PlaceholderArchive, off-canvas, appended last, not in
# drawablesZOrder) — see module docstring. The guard tolerates the gap for text only.
TEXT_PLACEHOLDER_SLACK = 2


# --------------------------------------------------------------------------
# Per-drawable classification helpers (pure).
# --------------------------------------------------------------------------
def _geometry(obj: dict) -> tuple[float | None, float | None, float | None, float | None]:
    """``(x, y, w, h)`` from the first ``geometry`` up the ``super`` chain.

    For a ShapeInfoArchive this is ``super.super.geometry``; the walk keeps it robust
    across the image / group / line archives whose geometry sits at a different depth.
    Returns ``(None, None, None, None)`` when no geometry is present.

    NB: reliable only for fixed boxes and unmasked images. Masked images report the
    unmasked frame here (JXA reports masked bounds), autosize text is ~30 px off with
    height 0, and group / line positions differ — do not feed this to a write path.
    """
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
    """Concatenated storage text for a ShapeInfoArchive, via ``ownedStorage``."""
    ref = (obj.get("ownedStorage") or {}).get("identifier")
    if ref is None:
        return ""
    storage = objects.get(str(ref))
    return "".join(storage.get("text") or []) if storage else ""


def _bezier(obj: dict) -> dict:
    return ((obj.get("super") or {}).get("pathsource") or {}).get("bezierPathSource") or {}


def _is_line(obj: dict) -> bool:
    """A line is a shape whose bezier path is a single open segment.

    ``bezierPathSource.path.elements == [moveTo, lineTo]`` — equivalently a
    ``naturalSize`` with a zero dimension (a line has no thickness in its natural
    frame; matches "a line's height is always 0"). Verified 0-disagreement across both
    test decks. A multi-point *open* ``editableBezierPathSource`` freeform is a pen
    shape, not a line, and is deliberately NOT matched here.
    """
    bez = _bezier(obj)
    if not bez:
        return False
    natural = bez.get("naturalSize") or {}
    if natural.get("width") == 0.0 or natural.get("height") == 0.0:
        return True
    elements = (bez.get("path") or {}).get("elements") or []
    return [e.get("type") for e in elements] == ["moveTo", "lineTo"]


def _has_custom_shape_path(obj: dict) -> bool:
    """True when the shape carries an editable/custom path (``editableBezierPathSource``).

    Such an object is a real shape even when it is a text box with text, so it lands in
    BOTH ``textItems`` and ``shapes`` (a dual). A plain text box has the default
    ``bezierPathSource`` rectangle and is text-only.
    """
    pathsource = (obj.get("super") or {}).get("pathsource") or {}
    return bool(pathsource.get("editableBezierPathSource"))


def _shape_memberships(obj: dict) -> list[str]:
    """Which scripting collections a ``TSWP.ShapeInfoArchive`` belongs to.

    * line  -> ``["line"]``
    * ``textItems`` membership is driven by ``isTextBox`` ALONE, not by carrying text:
      a text-bearing shape with ``isTextBox=False`` (e.g. a "UPG"/"CHC" label) is in
      ``shapes`` only.
    * ``shapes`` membership is ``not isTextBox OR has a custom path``.
    So a plain text box is ``["text"]``, a bare shape is ``["shape"]``, and a
    custom-path text box is the dual ``["text", "shape"]``.
    """
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
    """Scripting kind(s) for any top-level drawable (0, 1, or 2 kinds)."""
    simple = _PBTYPE_KIND.get(obj.get("_pbtype"))
    if simple:
        return [simple]
    if obj.get("_pbtype") == "TSWP.ShapeInfoArchive":
        return _shape_memberships(obj)
    return []


# --------------------------------------------------------------------------
# The derivation.
# --------------------------------------------------------------------------
def derive_kind_index(slide: dict, objects: dict[str, dict]) -> list[dict]:
    """``(kind, kindIndex)`` records for one ``KN.SlideArchive``, in JXA payload order.

    Walk ``drawablesZOrder`` once assigning ``kindIndex`` per kind (z-order rank, which
    is what JXA's per-collection order follows), recording each drawable's memberships;
    then emit grouped by :data:`KIND_ORDER`. A dual (a shape that also carries text)
    yields two records; the ``shape`` one carries ``duplicateOf`` -> its text. Note this
    is a STRUCTURAL mark (same archive is both text and shape), which is related to but
    NOT identical to JXA's ``markDuplicateShapes`` (which matches by text + rounded
    geometry); do not treat the two as the same set. It does not affect kindIndex.

    Each record: ``{id, kind, kindIndex, x, y, w, h, text[, duplicateOf]}``. Geometry
    is included for matching/debugging but is IWA-frame (see :func:`_geometry` caveat).
    Empty title/body placeholders that JXA appends to ``textItems`` are intentionally
    omitted (see :data:`TEXT_PLACEHOLDER_SLACK`).
    """
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
    """``{slide_index: [records]}`` for every slide, in presentation order.

    ``slide_index`` matches the JXA payload's ``index`` (skipped slides included), so a
    caller can line records up with ``payload["slides"][i]["items"]`` directly. Raises
    ``ImportError`` when the optional ``iwa`` extra is absent (same contract as
    :mod:`obed_edom.iwa_runs`).
    """
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional extra)

    objects, _id_to_file, _file_ids = _load_deck(key_path)
    return {
        idx: derive_kind_index(objects[slide_id], objects)
        for idx, (slide_id, _skipped) in enumerate(slide_order(objects))
        if slide_id in objects
    }


# --------------------------------------------------------------------------
# The count guard — a wrong index must never reach a write, so before trusting the
# offline addressing for a slide, confirm its per-kind counts against a cheap Keynote
# `count of <kind> of slide N` read (one Apple Event per kind, negligible next to the
# full inspect). Any disagreement -> fall back to the JXA read for that slide.
#
# LIMIT (see module docstring): this is a CARDINALITY check only — it cannot see an
# intra-kind permutation (right count, wrong order). Order is already established for
# text/shape/line/movie; for IMAGE and GROUP the caller must additionally verify order
# against COMPOSED geometry (mask-rect / child-union) before backing a write, since raw
# counts alone would wave through a swapped pair of masked images.
# --------------------------------------------------------------------------
def derived_kind_counts(records: list[dict]) -> dict[str, int]:
    """Per-kind count from :func:`derive_kind_index` records."""
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["kind"]] = counts.get(rec["kind"], 0) + 1
    return counts


def reconcile_counts(
    derived: dict[str, int],
    keynote: dict[str, int],
    *,
    text_slack: int = TEXT_PLACEHOLDER_SLACK,
) -> list[str]:
    """Kinds whose derived count disagrees with Keynote's — empty == slide is safe offline.

    ``keynote`` may exceed ``derived`` for ``text`` by up to ``text_slack`` (the empty
    title/body placeholders derive omits, which never shift a real index). Every other
    kind must match exactly; any listed kind means the offline addressing for this slide
    is untrusted and the caller should fall back to the Keynote read for it.
    """
    mismatches: list[str] = []
    for kind in set(derived) | set(keynote):
        d, k = derived.get(kind, 0), keynote.get(kind, 0)
        if kind == "text" and 0 <= (k - d) <= text_slack:
            continue
        if d != k:
            mismatches.append(kind)
    return sorted(mismatches)
