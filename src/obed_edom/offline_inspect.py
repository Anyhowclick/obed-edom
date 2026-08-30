"""Offline reconstruction of ``remap``'s JXA *source-wall* inspect payload.

``remap_keynote`` normally reads the source wall deck with the ~12-minute
``inspect_keynote(source)`` JXA pass (``inspect_keynote.js``) before it plans a
single move. Every field that pass reports is derivable from the deck's decoded
IWA graph in a few seconds: :mod:`obed_edom.iwa_kindindex` gives each drawable's
``(kind, kindIndex)`` address, :mod:`obed_edom.iwa_geometry` composes the
laid-out ``(x, y, w, h)`` JXA reports, and this module adds the remaining
planner-consumed fields — item-level ``size``/``font``/``color``, ``locked``,
line ``start``/``end``, image/movie ``fileName``, ``buildCount`` and
``duplicateOf`` — assembling a payload shaped exactly like the JXA one so it can
drop straight into the planner in place of the slow read.

This is a WRITE-path input, so it reproduces what ``inspect_keynote`` *actually*
reports today, limitations included — not the "true" value — because the safety
model is plan-equivalence, not correctness:
    * **childCount / children** — JXA's ``iWorkItems()`` raises on every group, so
      it reports ``0``/``[]`` for all of them and ``coincident_duplicate_ids``
      keys every group on ``0``. OMITTED here (never synthesized) so the dedup is
      unchanged.
    * **buildCount** — JXA reports ``0`` for every item on these decks; emit ``0``
      (no ``BuildArchive`` parsing).
    * **rotation** — emitted (``_item_from_record``) from the composed frame angle,
      plus the mask angle for a masked image/movie so it equals JXA's *net* visible
      rotation (a 2°-frame / -2°-mask pair reads as 0, matching JXA). The remap
      planner never reads it — its reads are zero — so it is plan-neutral there, but
      the checker needs it for the photo-tilt flag and the reuse fingerprint.
    * **master** — only consulted over template slides, never the wall payload, so
      OMITTED (the checker never reads it either).
    * **runs[]** — the per-run character style (:mod:`obed_edom.iwa_runs`) is a
      CHECKER input; the remap write path never reads it, so it is not attached.
    * **color** — JXA's ``objectText.color()`` returns a colour-managed value that
      does NOT equal the raw sRGB in the IWA graph (e.g. para ``(0.0, 0.99, 1.0)``
      surfaces as JXA ``[0.13, 1.0, 1.0]``); it cannot be reproduced offline.
      Item colour is emitted from the box's first run in JXA 0-65535 scale
      (``×257`` up from the 0-255 IWA value); both payloads route it through
      :func:`map_remap.norm_rgb`, and colour only breaks ties among template
      swatches that share a font family+weight, so the gate proves the residual
      plan-neutral on decks of this kind (it is NOT proven for arbitrary decks).

The safety model is two-part (see the gold-deck gate in
``scratchpad/validate_remap_plan.py``): the gate proves the field mappings +
the *tolerated* ``needs_keynote`` categories are plan-neutral on decks of this
kind, and the per-run STRUCTURAL GUARD (:func:`unvouched_items`) makes every
production run fall back to the legacy read whenever it meets anything the gate
did not vouch for. Full rule statement lives in the SKILL under "Reading a .key
offline (IWA)".

Public entry points:
    * :func:`offline_wall_payload` — ``(key_path[, slide_range]) -> payload`` in
      the JXA inspect shape, plus an ``_offline`` sidecar carrying the guard.
    * :func:`unvouched_items` — the structural guard, pure over a built payload.

Raises ``ImportError`` when the optional ``iwa`` extra is absent (same contract
as :mod:`obed_edom.iwa_runs`), which the caller catches to fall back to legacy.
"""
from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Any

from obed_edom.iwa_geometry import _geom_dict, _is_rotated, _mask_geom, _xywha, compose_geometry
from obed_edom.iwa_runs import resolve_style

# The one needs_keynote category the gold-deck gate proves plan-neutral on decks
# of this kind: an autosize box is hand-reflowed so its stale height never sticks —
# Keynote re-autosizes it on write, so the divergent laid-out box the gate sees is
# not the box that lands. Every OTHER reason trips the guard and forces the legacy
# read. In particular ``group-residual`` is UNVOUCHED (prong 3b): a group's w/h AND
# its size-derived role ARE written (remap_keynote.py:286-296,350-361 + as_dict
# emits w/h for role other/pin), so a residual group whose child-union/stored-frame
# geometry the gate cannot pin down is a real write divergence (the gate finds 41
# Map / 51 Full such groups, incl. pin<->other role flips) — it must fall back, not
# be trusted. See iwa_geometry.NEEDS_KEYNOTE_REASONS for the full set.
VOUCHED_NEEDS_KEYNOTE = frozenset({"autosize-soft"})

# --------------------------------------------------------------------------
# Two-tier read (offline + bulk-geometry) constants.
# --------------------------------------------------------------------------
# The three object classes whose laid-out geometry the offline read cannot
# reproduce exactly and which the bulk Keynote read (bulk_geometry.js) overwrites:
# groups (stored frame vs child-union), masked/rotated images+movies, and autosize
# text (stale naturalSize vs the reflowed box). Shapes and lines are EXACT offline,
# so they are never spliced. "text" here is the JXA ``textItems`` collection; a
# text-bearing shape stays under "shape" and is not touched.
BULK_KINDS = frozenset({"group", "image", "movie", "text"})

# geom_source values whose offline geometry is only best-effort, so the item MUST
# be confirmed by the bulk read to be trusted (group-union diverges on ~11% of
# groups; autosize on ~20% of boxes — see iwa_geometry). An item with either source
# that the bulk read did NOT return is a real, unconfirmed divergence -> its slide
# falls back to the legacy read. Plain "iwa"/"line" frames and axis-aligned masks
# are exact and need no bulk confirmation.
SOFT_GEOM_SOURCES = frozenset({"group-union", "autosize"})

# needs_keynote reasons that are pure GEOMETRY divergences (as opposed to content):
# once the bulk read overwrites the item's frame, these no longer describe a write
# divergence and are cleared. (autosize-soft is already vouched and never a flag.)
GEOMETRY_GUARD_REASONS = frozenset(
    {"rotated-masked", "masked-unresolved", "rotated-group", "group-residual"}
)

# Guard reasons that describe CONTENT the bulk geometry read does NOT touch (it
# reads no font/size/fileName), so they survive the splice and still force a
# per-slide fallback. Emitted by :func:`_item_from_record`, not by iwa_geometry.
CONTENT_GUARD_REASONS = frozenset({"font-size-unresolved", "filename-dirty"})

# A finalized asset's zip member is ``Data/<display-name>-<dataId>.<ext>``; the
# ``-<dataId>`` suffix is Keynote's, not part of the name the object reports. An id
# that does not resolve to exactly this shape (renamed / " copy" / path asset) is
# dirty and trips the guard. Confirmed 937/937 on Full_Report_Card_Wall.
_DATA_MEMBER = re.compile(r"^Data/(?P<base>.+)-(?P<id>\d+)\.(?P<ext>[^.]+)$")


def _round_pt(value: float) -> int:
    """Round a laid-out coordinate to the whole point JXA reports (half away from 0).

    Keynote's JXA geometry getters yield integers; matching that removes the
    sub-pixel affine drift (see :func:`_item_from_record`). Half-away-from-zero
    rather than Python's bankers' rounding so a ``.5`` never rounds toward an even
    neighbour JXA rounded the other way.
    """
    return int(math.floor(value + 0.5)) if value >= 0 else int(math.ceil(value - 0.5))


# --------------------------------------------------------------------------
# Deck-level asset (fileName) index.
# --------------------------------------------------------------------------
def _build_data_index(zip_names: list[str]) -> dict[str, str]:
    """``{dataId: '<display-name>.<ext>'}`` for every clean ``Data/*-<id>`` member.

    Strips the ``-<dataId>`` suffix Keynote appends, leaving the display filename
    JXA's ``fileName()`` reports. A data id absent from this map is dirty (the
    caller flags it) — its object was renamed or carries a path, so the offline
    filename would not equal JXA's.
    """
    index: dict[str, str] = {}
    for name in zip_names:
        m = _DATA_MEMBER.match(name)
        if not m:
            continue
        index[m.group("id")] = f"{m.group('base')}.{m.group('ext')}"
    return index


def _data_identifier(obj: dict) -> str | None:
    """The image/movie's asset data id (``data`` for images, ``movieData`` for movies)."""
    for key in ("data", "movieData"):
        ref = (obj.get(key) or {}).get("identifier")
        if ref is not None:
            return str(ref)
    return None


# --------------------------------------------------------------------------
# Item-level text style (size / font / colour), paragraph-inheritance aware.
# --------------------------------------------------------------------------
def _entry_sid(entry: dict) -> str | None:
    ref = entry.get("object")
    if ref and "identifier" in ref:
        return str(ref["identifier"])
    return None


def _leading_sid(table: dict | None) -> str | None:
    """The style id covering character offset 0 of a ``table*Style`` run table."""
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
    """``(font, size, color65535)`` for a text/shape box's dominant (first) run.

    JXA's ``objectText.font()/size()/color()`` report the leading run's effective
    style. A char-style override typically carries only colour/weight and leaves
    ``fontName``/``fontSize`` to the PARAGRAPH style, so each field is resolved
    char-first then filled from the paragraph style (:func:`iwa_runs.resolve_style`
    reads either archive's ``charProperties`` and walks its parent chain). ``font``
    or ``size`` still ``None`` after both means the paragraph inheritance did not
    resolve — the caller flags the item and falls back to Keynote. Colour is scaled
    ``×257`` from the 0-255 IWA value to JXA's 0-65535, or ``None`` (inherited).
    """
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
    color255 = pick("color")  # [r, g, b] 0-255 or None
    color = [max(0, min(65535, int(round(c * 257)))) for c in color255] if color255 else None
    return (font, size, color)


# --------------------------------------------------------------------------
# locked — up the drawable's super chain.
# --------------------------------------------------------------------------
def _locked(obj: dict) -> bool:
    """First ``locked`` up the ``super`` chain (DrawableArchive), else ``False``."""
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        if "locked" in cur:
            return bool(cur.get("locked"))
        cur = cur.get("super")
    return False


# --------------------------------------------------------------------------
# line start / end — signed endpoints from the raw frame centre + angle + length.
# --------------------------------------------------------------------------
def _line_direction(obj: dict) -> tuple[float, float]:
    """Unit natural (un-rotated) direction of a line, from ``moveTo``→``lineTo``.

    A line's ``bezierPathSource`` stores a canonical straight segment as two
    points; their difference gives the natural orientation (``(1, 0)`` for every
    line in the gold decks — a horizontal template scaled by the frame length).
    ``horizontalFlip``/``verticalFlip`` on the path source mirror it about the
    frame centre, so they negate the matching axis. Falls back to ``(1, 0)`` when
    the bezier is absent or degenerate.
    """
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
    """``(start, end)`` for a line, matching JXA's ``startPoint``/``endPoint``.

    The natural segment runs from ``moveTo`` (start) to ``lineTo`` (end) along the
    unit direction from :func:`_line_direction`, centred on the frame and scaled to
    the frame length (a line's natural width; its height is 0). The frame rotation
    places the endpoints: measured against JXA on every line of both gold decks,
    the applied rotation is ``R(-angle)`` — a rotated line's box is orientation-
    symmetric so images/shapes cannot reveal the sign, but the directed endpoints
    do. Hence, with ``L`` the length, ``θ`` the frame angle and ``(cx, cy)`` the
    frame centre::

        start = (cx - (L/2)(u_x cosθ - u_y sinθ),  cy + (L/2)(u_x sinθ + u_y cosθ))
        end   = (cx + (L/2)(u_x cosθ - u_y sinθ),  cy - (L/2)(u_x sinθ + u_y cosθ))

    ``item_rect`` then derives the write rect (``x``/``y``/``w``) from ``min``/
    ``max`` of the two, so a correct pair also fixes the line's box. The prior
    ``centre ± (L/2)(cosθ, sinθ)`` form drew the OPPOSITE DIAGONAL of the same box
    on every non-axis-aligned line (it matched only at θ=90°, where cosθ=0);
    this form matches all 391 gold-deck lines to <0.5px.
    """
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


# --------------------------------------------------------------------------
# Per-item assembly.
# --------------------------------------------------------------------------
_TEXTUAL = frozenset({"text", "shape"})
_ASSET = frozenset({"image", "movie"})


def _item_from_record(
    rec: dict,
    objects: dict[str, dict],
    data_index: dict[str, str],
    style_cache: dict,
) -> tuple[dict[str, Any], str | None]:
    """A JXA-shaped item dict plus its guard reason (``None`` when vouched).

    ``rec`` is a :func:`iwa_geometry.compose_geometry` record (id/kind/kindIndex/
    text/duplicateOf + composed x/y/w/h + geom_source/needs_keynote). The returned
    item carries the fields the remap planner reads plus ``rotation`` (the checker's
    photo-tilt flag and reuse fingerprint read it; the planner does not); ``master``/
    ``runs``/``childCount`` are intentionally absent (see the module docstring).
    """
    obj = objects.get(rec["id"]) or {}
    kind = rec["kind"]
    # rotation == JXA's `obj.rotation()`: the frame angle for most drawables, but a
    # masked image/movie's visible rotation is the frame angle plus the mask's own
    # (mask-local) angle — the mask window's ABSOLUTE rotation. A 2°-frame / 358°-mask
    # pair therefore reads as 0, exactly as JXA reports it.
    angle = _xywha(_geom_dict(obj))[4]
    if kind in _ASSET:
        mask_geom = _mask_geom(obj, objects)
        if mask_geom:
            angle += _xywha(mask_geom)[4]
    # Keynote returns laid-out geometry to JXA as whole points — every x/y/w/h and
    # line start/end in an ``inspect_keynote`` payload is an integer (``obj.position()``
    # etc. round in the app, not the JS). A faithful offline payload must round too:
    # left sub-pixel, an object's own value stays within tolerance but the per-slide
    # affine (fit from these values) drifts a fraction that the cover scale amplifies
    # into a deck-wide 2-4px cascade off the JXA plan. Rounding to match JXA's integers
    # removes that amplification at the source (and moves no object more than ½px).
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
        # JXA's rotation is ALWAYS a whole degree (Keynote rounds it like x/y/w/h);
        # round the same way and normalise into [0,360) so a net 360/-2 lands on 0/358
        # as JXA reports. A fractional value would churn the reuse fingerprint
        # (baseline.deck_slide_digests) and risk a spurious photo-tilt flag. NOTE: the
        # composed frame+mask angle still carries a sub-degree residual on masked images,
        # so exact JXA parity is not attainable offline — integer rounding minimises but
        # does not eliminate rotation-digest churn on masked-rotated decks.
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
        # A text/shape box that carries copy but whose font or size would not
        # resolve is unvouched: JXA reports the rendered value, the offline read
        # cannot, and both feed item_content_key / match_character_style.
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


# --------------------------------------------------------------------------
# Deck-level canvas + slide order.
# --------------------------------------------------------------------------
def _canvas_size(objects: dict[str, dict]) -> tuple[float, float]:
    """``(width, height)`` of the presentation canvas from ``KN.ShowArchive.size``.

    JXA reads ``doc.width()/height()`` (7680×1080 on the wall decks); the show
    archive's ``size`` is the same canvas. Falls back to 1920×1080 (JXA's own
    fallback) when absent.
    """
    for obj in objects.values():
        if obj.get("_pbtype") == "KN.ShowArchive":
            size = obj.get("size") or {}
            w, h = size.get("width"), size.get("height")
            if w and h:
                return (float(w), float(h))
            break
    return (1920.0, 1080.0)


# --------------------------------------------------------------------------
# Public entry points.
# --------------------------------------------------------------------------
def offline_wall_payload(
    key_path: str | Path, slide_range: Any = None, *, deck: Any = None
) -> dict[str, Any]:
    """A JXA-``inspect_keynote``-shaped payload for the wall deck, read offline.

    Emits EVERY slide with its DOCUMENT-position ``number`` (= ``index`` + 1) and
    ``skipped`` flag — the planner's ``plan["slides"]`` / ``wants_slide`` does the
    range filtering, so no inspect-style subset windowing is reproduced here (and
    ``slide_range`` only scopes which slides' guard flags mark the payload as
    tripped, never which slides are emitted).

    The returned dict is a drop-in for the planner (``slideWidth``/``slideHeight``/
    ``slideCount``/``slides[].items[]``) plus a private ``_offline`` sidecar:
    ``{"guard": [{slide, kind, kindIndex, reason}, …], "tripped": bool}``. A
    caller must fall back to the legacy read when ``tripped`` is true (see
    :func:`unvouched_items`). Raises ``ImportError`` without the ``iwa`` extra.

    ``deck`` is an already-decoded ``_load_deck`` 3-tuple; pass it to share ONE IWA
    decode with :func:`obed_edom.iwa_runs.attach_runs` (the checker reads both).
    """
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
            # An item whose offline geometry is only best-effort (a group frame or
            # an autosize box) — or which already carries a geometry guard reason —
            # is soft: the two-tier read must confirm it against the bulk Keynote
            # geometry, or its slide falls back. Recorded from the record's
            # geom_source (which the item dict does not carry).
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
    """Whether any guard flag falls on a slide the caller is planning."""
    if not guard:
        return False
    if slide_range is None:
        return True
    from obed_edom.map_remap import wants_slide  # noqa: PLC0415 (avoid import cycle at load)

    return any(wants_slide(int(flag["slide"]), slide_range) for flag in guard)


def unvouched_items(payload: dict[str, Any], slide_range: Any = None) -> list[dict[str, Any]]:
    """The guard flags on a payload from :func:`offline_wall_payload`, range-scoped.

    Pure re-read of the ``_offline`` sidecar so a caller can log exactly which
    items forced the legacy fallback. Fails toward flagging: any returned flag
    means the offline read is untrusted for the deck.
    """
    guard = ((payload.get("_offline") or {}).get("guard")) or []
    if slide_range is None:
        return list(guard)
    from obed_edom.map_remap import wants_slide  # noqa: PLC0415

    return [flag for flag in guard if wants_slide(int(flag["slide"]), slide_range)]


# --------------------------------------------------------------------------
# Two-tier read: offline payload + a bulk Keynote geometry overwrite.
# --------------------------------------------------------------------------
def _is_placeholder_row(row: list | None, width: float, height: float) -> bool:
    """Whether a bulk geometry row looks like a JXA empty text placeholder.

    JXA appends 0-2 empty title/body placeholders (``KN.PlaceholderArchive``) to the
    END of ``textItems`` on some slides; derive omits them (SKILL "Placeholders").
    A real placeholder is at the origin AND degenerate (observed ``(0,0,0,0)``).
    Requiring BOTH closes the false-accept a peer caught: an at-origin case must also
    be degenerate-size (a real title box at the origin has real size), and a box merely
    parked off-canvas is NOT a placeholder — otherwise a mid-list text drop whose real
    tail box happens to sit at the origin (or off-canvas) would slip the count slack.
    A missed sized/off-canvas placeholder only yields a safe-side spurious JXA
    fallback, never a mis-splice.
    """
    if not row or len(row) < 4:
        return False
    x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
    at_origin = abs(x) < 1.0 and abs(y) < 1.0
    degenerate = w < 1.0 or h < 1.0
    return at_origin and degenerate


def _splice_bulk_geometry(
    payload: dict[str, Any], bulk: dict[int, dict[str, list]]
) -> tuple[set[tuple[int, str, int]], set[tuple[int, str]]]:
    """Overwrite each group/image/movie/text item's x/y/w/h from ``bulk``, in place.

    ``bulk`` is ``{slideIndex: {kind: [[x, y, w, h], … by kindIndex]}}`` (the
    :func:`obed_edom.inspect.bulk_geometry` shape), keyed by the 0-based document
    index that equals ``slide["index"]``. Only the four :data:`BULK_KINDS` are
    touched, and ONLY x/y/w/h — addressing, style, fileName, locked, childCount,
    buildCount and text stay exactly as the offline read produced them. Values are
    rounded to whole points to match JXA's integer geometry (see
    :func:`_item_from_record`).

    COUNT GUARD (per (slide, kind), before splicing that kind): the bulk row count
    (Keynote's collection size) is reconciled against the offline item count for
    that kind (:func:`obed_edom.iwa_kindindex.reconcile_counts`) — image/movie/group
    must match EXACTLY, text tolerates ``keynote − derived ∈ [0,2]`` trailing empty
    placeholders. When that text slack is actually used the extra rows must sit at
    the TAIL as placeholder-shaped frames (:func:`_is_placeholder_row`), else a
    mid-list text drop masked by placeholders would pass. A mismatch means a
    dropped/added mid-list item has desynced ``kindIndex`` from the bulk rows, so the
    kind is left UNspliced (its offline geometry stands until the slide falls back).

    Returns ``(spliced, count_mismatch)``: ``spliced`` is the set of
    ``(number, kind, kindIndex)`` actually overwritten (so the caller knows which
    soft items the bulk read confirmed); ``count_mismatch`` is the set of
    ``(number, kind)`` whose counts disagreed (so the caller can force those slides
    to fall back even when they carry no soft item).
    """
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
        # Per-kind offline (derived) vs bulk (Keynote) counts for the 4 BULK_KINDS.
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
        # The text slack can hide a mid-list drop when placeholders are present: if
        # it was actually used, the extra rows must be placeholder-shaped and at the
        # tail, else treat the (slide, text) as a real count mismatch.
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


def two_tier_wall_payload(
    key_path: str | Path,
    bulk_geometry_fn: Any = None,
    slide_range: Any = None,
    *,
    deck: Any = None,
) -> dict[str, Any]:
    """The offline wall payload with the three soft classes' geometry read from Keynote.

    Tier 1 is :func:`offline_wall_payload` (exact for shapes/lines/plain frames).
    Tier 2 is ``bulk_geometry_fn(key_path, slides=…)`` — a callable returning
    ``{slideIndex: {kind: [[x, y, w, h], …]}}`` (see
    :func:`obed_edom.inspect.bulk_geometry`); its values OVERWRITE each
    group/image/movie/text item's frame, which is where the offline read diverges.
    With ``bulk_geometry_fn=None`` this is exactly the tier-1 payload (pure offline).

    GRANULAR FALLBACK (per Fable) — the fallback unit is the object CLASS or SLIDE,
    never the whole deck. The ``_offline`` sidecar gains:

        * ``bulk_ok`` — False if the whole bulk read raised (tier 2 unavailable);
          the caller then treats the deck the pure-offline way (whole-deck legacy
          on any trip). True when a bulk map was obtained, even a partial one.
        * ``spliced`` — count of items overwritten.
        * ``fallback`` — the items that still need the legacy read, each
          ``{slide, kind, kindIndex, reason}``. A slide appears here only for its
          OWN unresolved items; every other slide is served offline+bulk.
        * ``fallback_slides`` — the sorted document numbers in ``fallback`` (the
          set the caller re-reads with one scoped ``inspect_keynote`` and merges).

    The reworked guard (documented): because groups/images/text are now READ, the
    geometry reasons ``group-residual`` / ``rotated-masked`` / ``masked-unresolved``
    / ``rotated-group`` no longer force a fallback once the bulk read CONFIRMS the
    item — they are cleared for spliced items. What remains a fallback trigger is
    (a) a CONTENT guard reason the bulk read cannot touch (``font-size-unresolved``,
    ``filename-dirty``), and (b) a SOFT-geometry item (group frame / autosize box,
    or a geometry-flagged one) the bulk read did NOT return — an unconfirmed
    divergence. Both are scoped to their slide, never the deck.

    ``deck`` is an already-decoded ``_load_deck`` 3-tuple, forwarded to tier 1 so the
    checker can share ONE IWA decode across this read and ``attach_runs``.
    """
    payload = offline_wall_payload(key_path, slide_range, deck=deck)
    sidecar = payload.setdefault("_offline", {})
    guard = sidecar.get("guard") or []
    soft = sidecar.get("soft_geometry") or []

    # Content guard reasons are never fixed by a geometry read.
    content_flags = [f for f in guard if f.get("reason") in CONTENT_GUARD_REASONS]

    if bulk_geometry_fn is None:
        # Pure offline: every soft item is unconfirmed, so it is a fallback unit —
        # this degrades to the offline read's own whole-deck-trip semantics via the
        # union of content + soft flags, but expressed granularly.
        fallback = content_flags + [{**s, "reason": "bulk-missing"} for s in soft]
        _finalize_two_tier(payload, sidecar, bulk_ok=False, spliced=0, fallback=fallback,
                           slide_range=slide_range)
        return payload

    from obed_edom.map_remap import wants_slide  # noqa: PLC0415

    wanted = None
    if slide_range is not None:
        from obed_edom.map_remap import slides_for_plan  # noqa: PLC0415

        wanted = slides_for_plan(slide_range)
    try:
        bulk = bulk_geometry_fn(key_path, slides=wanted)
    except Exception:  # noqa: BLE001 — any bulk failure => tier 2 unavailable
        fallback = content_flags + [{**s, "reason": "bulk-missing"} for s in soft]
        _finalize_two_tier(payload, sidecar, bulk_ok=False, spliced=0, fallback=fallback,
                           slide_range=slide_range)
        return payload

    spliced, count_mismatch = _splice_bulk_geometry(payload, bulk or {})
    # A soft item the bulk read did not confirm is still an unconfirmed divergence.
    unconfirmed = [
        {**s, "reason": "bulk-missing"}
        for s in soft
        if (int(s["slide"]), s["kind"], int(s["kindIndex"])) not in spliced
    ]
    # A per-(slide, kind) count disagreement means a mid-list BULK_KIND item was
    # dropped/added, so kindIndex no longer lines the bulk rows up with the offline
    # items — the whole slide must fall back EVEN IF it carries no soft item (a
    # soft-free count mismatch would otherwise silently mis-splice every later frame,
    # the DSK17 bug class). Its kind stayed unspliced above.
    count_flags = [
        {"slide": number, "kind": kind, "kindIndex": -1, "reason": "count-mismatch"}
        for number, kind in sorted(count_mismatch)
    ]
    fallback = content_flags + unconfirmed + count_flags
    if slide_range is not None:
        fallback = [f for f in fallback if wants_slide(int(f["slide"]), slide_range)]
    _finalize_two_tier(payload, sidecar, bulk_ok=True, spliced=len(spliced),
                       fallback=fallback, slide_range=slide_range)
    return payload


def _finalize_two_tier(
    payload: dict[str, Any],
    sidecar: dict[str, Any],
    *,
    bulk_ok: bool,
    spliced: int,
    fallback: list[dict[str, Any]],
    slide_range: Any,
) -> None:
    """Attach the two-tier bookkeeping to the ``_offline`` sidecar (in place)."""
    if slide_range is not None:
        from obed_edom.map_remap import wants_slide  # noqa: PLC0415

        fallback = [f for f in fallback if wants_slide(int(f["slide"]), slide_range)]
    sidecar["bulk_ok"] = bulk_ok
    sidecar["spliced"] = spliced
    sidecar["fallback"] = fallback
    sidecar["fallback_slides"] = sorted({int(f["slide"]) for f in fallback})
    # ``tripped`` now means "the whole deck cannot be served two-tier": true only
    # when the bulk tier is unavailable AND there is anything to fall back on.
    sidecar["tripped"] = bool(not bulk_ok and fallback)
