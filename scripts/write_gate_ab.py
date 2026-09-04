#!/usr/bin/env python3
"""A/B validation gate for the offline geometry-WRITE (``w-offline-write-optin``).

Proves that an OFFLINE surgical patch of ONE non-reuse content slide reproduces the
PRODUCTION scripted-AppleScript geometry write, so the gate can flip ``OBED_OFFLINE_WRITE``.

    B-pre = attrs-only pass 1 (OBED_SUPPRESS_GEOMETRY=N) — slide N carries NO geometry.
    B     = B-pre with slide N patched offline by ``iwa_write.patch_slide_geometry``.
    A'    = an ID-STABLE reference: a COPY of B-pre with the PRODUCTION AppleScript
            geometry body (``remap_keynote._build_slide_geometry_script``) applied to it.
    A     = full production remap (OBED_AS_GEOMETRY=1) — OPTIONAL (``--full-a``), kept
            only as a cross-check; it is an INDEPENDENT Keynote run with different drawable
            ids and different group z-order, so it can only be positionally matched.

The PRIMARY oracle is the OFFLINE value-level comparison of A' vs B. Because A' is
produced by applying production AppleScript to a COPY of B-pre, A' and B share B-pre's
drawable ids EXACTLY, so every object (and every group CHILD) matches by id — the gate
is id-stable, never blindly positional. Each object's raw IWA is composed to the
render-accurate frame JXA would report (mask crop, line endpoints, group child-union)
and compared within ±2px (§Gate-compare). JXA frame parity + a full-slide PNG pixel-diff
(``--live``) are the live CO-GATE.

Banking: B-pre, its specs sidecar, and A' are all reusable (``--reuse-bpre`` /
``--reuse-specs`` / ``--reuse-aprime``) so patcher-fix iterations need NO Keynote.

The Keynote-touching orchestration lives in :func:`main` (the LEAD runs it, guarded —
see the plan's Piece 4). Everything the gate DECIDES on — the §Gate-compare comparator,
the byte-reveal, the cross-slide locality diff — is a pure, import-testable function with
NO Keynote (unit-proven in ``tests/test_write_gate.py``).

    .venv/bin/python scripts/write_gate_ab.py --source WALL.key --template CG.key --slide 9

DO NOT run this against the 1.2 GB gold deck without the lead's bounded-open guard: a
Keynote open can wedge.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from obed_edom import keynote_app

from obed_edom.iwa_geometry import (
    _geom_dict,
    _group_union,
    _leaf_bbox,
    _mask_geom,
    _snap90,
    _xywha,
    compose_geometry,
)
from obed_edom.iwa_kindindex import deck_kind_counts
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_write import PatchResult, patch_slide_geometry
from obed_edom.iwa_write import bridge_specs_kindindex  # noqa: F401 — re-exported for callers of this module
from obed_edom.offline_inspect import _line_endpoints

DEFAULT_SLIDE = 9
TOL_PX = 2.0  # SKILL write budget (iwa_geometry:93) — mask/rotated composites need ±2, not ±1.
# Soft classes: their laid-out frame is not recoverable from raw IWA, so the patcher takes
# their delta off the pre-patch BULK read (``reported``), never the offline compose.
SOFT_KINDS = ("group", "text", "image", "movie")
# geometry fields the byte-reveal watches for an AppleScript mutation.
GEOM_FIELDS = ("pos_x", "pos_y", "size_w", "size_h", "angle", "natural_w", "natural_h")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================================================
# Preconditions (offline) — step 1.
# ==========================================================================
def slide_specs(plan_transforms: list[dict], slide_number: int) -> list[dict]:
    """The planned transform dicts for one slide (``plan_out['transforms']`` filtered)."""
    return [t for t in plan_transforms if int(t.get("slide", -1)) == slide_number]


def slide_has_resized_image(specs: list[dict]) -> bool:
    """True when the slide carries an image/movie spec that resizes (w or h present)."""
    return any(
        str(s.get("kind")) in ("image", "movie")
        and (s.get("w") is not None or s.get("h") is not None)
        for s in specs
    )


def check_preconditions(specs: list[dict], reuse_slides: set[int], slide_number: int) -> list[str]:
    """Reasons slide N cannot be gated — empty list == good to go.

    The gate needs a NON-reuse slide (a reuse slide is duplicated post-transform, so it
    has no fresh geometry write to reproduce) that actually resizes a masked image (the
    unproven SIZE class the gate exists to prove).
    """
    errors: list[str] = []
    if slide_number in reuse_slides:
        errors.append(f"slide {slide_number} is a REUSE slide; the gate needs a non-reuse slide")
    if not specs:
        errors.append(f"slide {slide_number} has no planned transforms")
    elif not slide_has_resized_image(specs):
        errors.append(
            f"slide {slide_number} carries no resized image spec (w/h); "
            "pick a slide that resizes a masked image"
        )
    return errors


def reuse_slide_numbers(reuses: list[dict]) -> set[int]:
    """Slide numbers a reuse job duplicates (from ``plan_out['reuses']``)."""
    return {int(r["slide"]) for r in (reuses or []) if r.get("slide") is not None}


def source_kind_counts(source_deck: Path | str, slide_number: int) -> dict[str, int]:
    """Per-kind counts of the SOURCE-wall slide (reconcile base); delegates to iwa_kindindex."""
    counts = deck_kind_counts(source_deck)
    if slide_number not in counts:
        raise ValueError(f"slide {slide_number} out of range (source has {len(counts)} slides)")
    return counts[slide_number]


# ==========================================================================
# Specs sidecar — bank ``specs_N`` + source counts so a re-run needs no Keynote.
# ==========================================================================
def write_specs_sidecar(path: Path | str, *, slide_number: int, source: Path | str,
                        template: Path | str, specs: list[dict],
                        source_counts: dict[str, int]) -> Path:
    """Persist everything the patcher + A' need for slide N, so a later run can SKIP
    the B-pre remap entirely (``--reuse-bpre`` / ``--reuse-specs``).

    Holds the slide number, the source/template paths, the planned transform dicts
    (``specs``) and the source-wall per-kind counts (the reconcile base). Written next
    to the banked B-pre deck as ``specs_slide<N>.json``.
    """
    path = Path(path)
    payload = {
        "slide": int(slide_number),
        "source": str(source),
        "template": str(template),
        "specs": specs,
        "source_counts": source_counts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def load_specs_sidecar(path: Path | str) -> dict:
    """Round-trips :func:`write_specs_sidecar`. Returns the decoded dict."""
    return json.loads(Path(path).read_text())


def specs_hide_count(specs: list[dict]) -> int:
    """Number of ``role="hide"`` specs on the slide — drives the A' index bridge.

    ``_build_slide_geometry_script`` addresses objects by WALL kindIndex, but B-pre has
    already run ``deleteHides``; a non-zero count means the surviving same-kind indices
    above a deleted hide are shifted down, so the A' body must be bridged (below) to hit
    the same saved objects the patcher (B) addresses.
    """
    return sum(1 for s in specs if s.get("role") == "hide")


# ==========================================================================
# A' — the ID-STABLE reference: production AppleScript geometry on a COPY of B-pre.
# ==========================================================================
def build_aprime_applescript(deck_path: Path | str, body: str) -> str:
    """The scoped AppleScript that opens ``deck_path``, applies the production geometry
    ``body`` (``remap_keynote._build_slide_geometry_script`` output — a ``with timeout
    ... tell slide N ... end tell ... end timeout`` block), SAVES, and closes.

    Mirrors ``remap_keynote.js``'s ``runAppleScript``: the body's ``tell slide N``
    resolves inside a ``tell <document>`` context, exactly as production applies it —
    so A' gets the byte-for-byte same geometry write, only against a COPY of B-pre
    (which is what makes the ids stable). Written as a pure function so a pytest can
    lock the scaffold with no Keynote.
    """
    key = str(Path(deck_path).resolve()).replace("\\", "\\\\").replace('"', '\\"')
    app = keynote_app.bundle_id()
    return "\n".join([
        f'tell application id "{app}"',
        f'  set theDoc to open POSIX file "{key}"',
        "  tell theDoc",
        body,
        "  end tell",
        "  save theDoc",
        "  try",
        "    close theDoc saving yes",
        "  end try",
        "end tell",
    ])


def run_aprime(deck_path: Path | str, body: str, log=_log) -> None:
    """Run :func:`build_aprime_applescript` under ``osascript`` (Keynote-touching).

    The LEAD runs this (under the bounded-open guard). Raises ``RuntimeError`` on any
    osascript failure so the harness never treats a wedged/failed A' write as valid.
    """
    script = build_aprime_applescript(deck_path, body)
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(["osascript", str(script_path)],
                              capture_output=True, text=True, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("A' geometry write failed:\n"
                           + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    log(f"A': production geometry applied to {Path(deck_path).name} (saved).")


# ==========================================================================
# Soft-class ``reported`` seed from the B-pre inspect payload — step 2.
# ==========================================================================
def build_reported(payload: dict, slide_number: int, soft_kinds=SOFT_KINDS
                   ) -> dict[tuple[str, int], list[float]]:
    """``{(kind, kindIndex): [x, y, w, h]}`` for the soft classes on slide N.

    The B-pre payload is Keynote's own post-``deleteHides`` read, so its per-kind item
    order is the SAVED kindIndex the patcher addresses by (empty trailing text
    placeholders sort last and never shift a real index). This is the accurate soft-class
    frame the patcher deltas off — the offline compose is stale for exactly these kinds.
    """
    reported: dict[tuple[str, int], list[float]] = {}
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if number != slide_number:
            continue
        counters: dict[str, int] = {}
        for item in slide.get("items") or []:
            kind = str(item.get("kind") or "")
            kind_index = counters.get(kind, 0)
            counters[kind] = kind_index + 1
            if kind in soft_kinds:
                reported[(kind, kind_index)] = [
                    float(item.get("x") or 0.0), float(item.get("y") or 0.0),
                    float(item.get("w") or 0.0), float(item.get("h") or 0.0),
                ]
    return reported


def build_reported_offline(objects: dict[str, dict], slide_number: int,
                           soft_kinds=SOFT_KINDS) -> dict[tuple[str, int], list[float]]:
    """``{(kind, kindIndex): [x, y, w, h]}`` for the soft classes, composed OFFLINE
    from the B-pre deck itself (no Keynote payload needed — the ``--reuse-bpre`` path).

    A' is produced by applying production AppleScript to a COPY of this very B-pre, so
    B-pre's own composed frames are the exact pre-patch reference the delta is taken
    off. For a masked image the composed crop (image_pos + mask_pos) and a group's
    child-union ARE offline-recoverable, so this matches the payload read on slide 9.
    CAVEAT: a text-autosize box's laid-out w/h is NOT offline-recoverable (Keynote
    derives it on OPEN); slide 9 has text=0, so this is exact there — on a text-bearing
    slide prefer the Keynote-payload :func:`build_reported`.
    """
    reported: dict[tuple[str, int], list[float]] = {}
    for rec in compose_geometry(_slide_archive(objects, slide_number), objects):
        if rec["kind"] in soft_kinds:
            reported[(rec["kind"], rec["kindIndex"])] = [
                float(rec["x"]), float(rec["y"]), float(rec["w"]), float(rec["h"])]
    return reported


def _slide_archive(objects: dict[str, dict], slide_number: int) -> dict:
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        raise ValueError(f"slide {slide_number} out of range (deck has {len(order)} slides)")
    return objects[order[slide_number - 1][0]]


# ==========================================================================
# §Gate-compare — pure render-geometry comparator (the CORE, unit-proven).
# ==========================================================================
def _pathsource(obj: dict) -> dict:
    """The first ``pathsource`` dict up the ``super`` chain, or ``{}``."""
    cur: Any = obj
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        ps = cur.get("pathsource")
        if isinstance(ps, dict):
            return ps
        cur = cur.get("super")
    return {}


def _flips(obj: dict) -> tuple[bool, bool]:
    """``(horizontalFlip, verticalFlip)`` — a flip renders a mirrored diagonal (a real
    write bug the composed box alone cannot see). Read from the geometry archive, or the
    path source for a line."""
    geom = _geom_dict(obj)
    ps = _pathsource(obj)
    return (
        bool(geom.get("horizontalFlip") or ps.get("horizontalFlip")),
        bool(geom.get("verticalFlip") or ps.get("verticalFlip")),
    )


def _box_to_frame(box: tuple[float, float, float, float] | None
                  ) -> tuple[float, float, float, float]:
    if not box:
        return (0.0, 0.0, 0.0, 0.0)
    x0, y0, x1, y1 = box
    return (x0, y0, x1 - x0, y1 - y0)


def render_signature(rec: dict, obj: dict, objects: dict[str, dict]) -> dict:
    """Render-geometry signature for one top-level drawable (composes raw IWA → JXA box).

    Per §Gate-compare, compare the COMPOSED render box, never the raw stored fields:
      * line   → directed ``_line_endpoints`` (folds position+length+angle+flips+bezier);
      * masked → ``_masked_rect`` crop (from the record) + snapped mask angle, PLUS the
                 raw image ``geometry.size`` as a SEPARATE crop-visibility diff;
      * group  → child-union box (children compared as their own units too);
      * autosize text → x only (naturalSize/derived-top are re-derived on OPEN — A and B
                 legitimately differ there yet render identically);
      * shape / fixed text / unmasked image → composed frame.
    """
    kind = rec["kind"]
    flips = _flips(obj)
    if kind == "line":
        start, end = _line_endpoints(obj)
        return {"type": "line", "endpoints": (tuple(start), tuple(end)), "flips": flips}
    if kind in ("image", "movie") and rec.get("geom_source") == "mask":
        _mx, _my, _mw, _mh, mask_angle = _xywha(_mask_geom(obj, objects))
        _ix, _iy, img_w, img_h, _ia = _xywha(_geom_dict(obj))
        return {
            "type": "masked",
            "crop": (rec["x"], rec["y"], rec["w"], rec["h"]),
            "mask_angle": _snap90(mask_angle),
            "raw_size": (img_w, img_h),
            "flips": flips,
        }
    if kind == "group":
        return {"type": "group", "union": (rec["x"], rec["y"], rec["w"], rec["h"]), "flips": flips}
    if kind == "text" and rec.get("geom_source") == "autosize":
        return {"type": "autosize", "x": rec["x"], "flips": flips}
    return {"type": "frame", "frame": (rec["x"], rec["y"], rec["w"], rec["h"]), "flips": flips}


def _child_kind(child: dict) -> str:
    pbtype = child.get("_pbtype")
    return {"TSD.ImageArchive": "image", "TSD.MovieArchive": "movie",
            "TSD.GroupArchive": "group"}.get(pbtype, "child")


def _expand_group(group_id: str, ox: float, oy: float, objects: dict[str, dict],
                  parent_addr: tuple, units: list[dict], seen: set[str]) -> None:
    """Emit a frame unit per child of a group (recursing nested groups), addressed by
    (parent, child position). The group-w/h-inert proof runs THROUGH these children: a
    child moved while the union box is unchanged is caught here, not by the union compare.
    """
    if group_id in seen:
        return
    seen.add(group_id)
    group = objects.get(group_id) or {}
    for i, ref in enumerate(group.get("children") or []):
        child_id = ref.get("identifier")
        if child_id is None:
            continue
        child = objects.get(str(child_id))
        if not child:
            continue
        addr = (parent_addr, "child", i)
        if child.get("_pbtype") == "TSD.GroupArchive":
            cx, cy, _cw, _ch, _ca = _xywha(_geom_dict(child))
            union = _group_union(str(child_id), ox + cx, oy + cy, objects, set())
            units.append({"id": str(child_id), "kind": "group", "addr": addr,
                          "sig": {"type": "group", "union": _box_to_frame(union),
                                  "flips": _flips(child)}})
            _expand_group(str(child_id), ox + cx, oy + cy, objects, addr, units, seen)
        else:
            box = _leaf_bbox(child, ox, oy, objects)
            units.append({"id": str(child_id), "kind": _child_kind(child), "addr": addr,
                          "sig": {"type": "frame", "frame": _box_to_frame(box),
                                  "flips": _flips(child)}})


def slide_units(objects: dict[str, dict], slide_number: int) -> list[dict]:
    """Every comparable render unit on slide N: each top-level drawable, plus every group
    expanded into its recursive children. A unit is ``{id, kind, addr, sig}``.
    """
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        raise ValueError(f"slide {slide_number} out of range (deck has {len(order)} slides)")
    slide = objects[order[slide_number - 1][0]]
    units: list[dict] = []
    for rec in compose_geometry(slide, objects):
        obj = objects.get(rec["id"]) or {}
        addr = ("top", rec["kind"], rec["kindIndex"])
        units.append({"id": rec["id"], "kind": rec["kind"], "addr": addr,
                      "sig": render_signature(rec, obj, objects)})
        if rec["kind"] == "group":
            gx, gy, _gw, _gh, _ga = _xywha(_geom_dict(obj))
            _expand_group(rec["id"], gx, gy, objects, addr, units, set())
    return units


def text_autosize_shapes(units: list[dict]) -> list[dict]:
    """Shape units with a DEGENERATE (zero-extent) composed frame — the tell of a grow-
    with-text autosize shape whose ``bezierPathSource.naturalSize`` recomputes on OPEN
    (SKILL:954), so A (Keynote-saved) and B (pre-open) legitimately differ yet render
    identically. Slide 9 has text=0, so this must be empty there; a non-empty result
    means carve those shapes out of the frame compare (per §Gate-compare)."""
    bad: list[dict] = []
    for u in units:
        if u["kind"] == "shape" and u["sig"].get("type") == "frame":
            _x, _y, w, h = u["sig"]["frame"]
            if w == 0.0 or h == 0.0:
                bad.append(u)
    return bad


def match_units(a_units: list[dict], b_units: list[dict]
                ) -> tuple[list[tuple[dict, dict, str]], list[dict], list[dict]]:
    """Pair A↔B units by drawable IDENTITY, positional (kind, kindIndex) address as the
    guarded fallback. Returns ``(pairs, unmatched_a, unmatched_b)`` where each pair is
    ``(a_unit, b_unit, how)`` and ``how`` is ``"id"`` or ``"addr"``.
    """
    b_by_id = {u["id"]: u for u in b_units}
    b_by_addr = {u["addr"]: u for u in b_units}
    used: set[str] = set()
    pairs: list[tuple[dict, dict, str]] = []
    unmatched_a: list[dict] = []
    for ua in a_units:
        ub = None
        how = ""
        cand = b_by_id.get(ua["id"])
        if cand is not None and cand["id"] not in used:
            ub, how = cand, "id"
        else:
            cand = b_by_addr.get(ua["addr"])
            if cand is not None and cand["id"] not in used:
                ub, how = cand, "addr"
        if ub is None:
            unmatched_a.append(ua)
            continue
        used.add(ub["id"])
        pairs.append((ua, ub, how))
    unmatched_b = [u for u in b_units if u["id"] not in used]
    return pairs, unmatched_a, unmatched_b


def id_match_rate(pairs: list[tuple[dict, dict, str]]) -> float:
    """Fraction of matched pairs paired by drawable IDENTITY (``how == "id"``).

    A' and B share B-pre's ids, so this must be ~1.0; a rate below the gate's threshold
    means the comparison silently FELL BACK to positional (kind, kindIndex) matching —
    which, on slide 9's 110 masked images + 67 reordered groups, mis-pairs objects and
    makes the whole result UNTRUSTED. The gate logs that loudly and fails.
    """
    if not pairs:
        return 1.0
    return sum(1 for _a, _b, how in pairs if how == "id") / len(pairs)


def _sig_center(sig: dict) -> tuple[float, float]:
    box = sig.get("frame") or sig.get("crop") or sig.get("union")
    if box:
        return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
    if "endpoints" in sig:
        (sx, sy), (ex, ey) = sig["endpoints"]
        return ((sx + ex) / 2.0, (sy + ey) / 2.0)
    if "x" in sig:
        return (float(sig["x"]), 0.0)
    return (0.0, 0.0)


def positional_crosscheck(a_units: list[dict], b_units: list[dict],
                          kinds=("image", "group")) -> dict[str, str]:
    """Guard the positional fallback for the z-order-inferred kinds (image/group).

    Returns ``{kind: reason}`` for any kind whose (kind, kindIndex) pairing is NOT
    geometry-consistent — a per-kind count delta, or an index whose nearest twin by
    composed centre is a DIFFERENT index (a silent coincident-swap mis-pair, slide 9's
    worst case with 110 masked images + 67 groups). Empty == the fallback is safe.
    """
    notes: dict[str, str] = {}
    for kind in kinds:
        a_k = sorted((u for u in a_units if u["addr"][0] == "top" and u["kind"] == kind),
                     key=lambda u: u["addr"][2])
        b_k = sorted((u for u in b_units if u["addr"][0] == "top" and u["kind"] == kind),
                     key=lambda u: u["addr"][2])
        if len(a_k) != len(b_k):
            notes[kind] = f"per-kind count {len(a_k)} != {len(b_k)}"
            continue
        b_centers = [_sig_center(u["sig"]) for u in b_k]
        for i, ua in enumerate(a_k):
            ca = _sig_center(ua["sig"])
            nearest = min(range(len(b_centers)),
                          key=lambda j: math.dist(ca, b_centers[j])) if b_centers else i
            if nearest != i:
                notes[kind] = f"index {i} nearest B index {nearest}: possible coincident swap"
                break
    return notes


def _sig_size(sig: dict) -> tuple[float, float]:
    """``(w, h)`` of a render signature's box (frame / crop / union / line span)."""
    box = sig.get("frame") or sig.get("crop") or sig.get("union")
    if box:
        return (float(box[2]), float(box[3]))
    if "endpoints" in sig:
        (sx, sy), (ex, ey) = sig["endpoints"]
        return (abs(ex - sx), abs(ey - sy))
    return (0.0, 0.0)


def _root_addr(addr: tuple) -> tuple:
    """Unwrap a nested ``(parent_addr, "child", i)`` chain to the owning ``("top", ...)``."""
    cur: Any = addr
    while isinstance(cur, tuple) and len(cur) == 3 and cur[1] == "child":
        cur = cur[0]
    return cur


def group_child_scale_report(pairs: list[tuple[dict, dict, str]],
                             ratio_tol: float = 0.02) -> dict[tuple, dict]:
    """Per-group child-transform diagnostic (the lead needs this to decide whether the
    patcher can be extended to scale group CHILDREN with a clean uniform scale).

    For every group-child pair matched A'↔B by id, records the size ratio
    ``A'_child_size / B_child_size`` per axis, then summarizes per owning top-level
    group: ``sx``/``sy`` min–max across children and whether it is a UNIFORM scale
    (every child's sx≈sy AND the sx band and sy band are each tight within
    ``ratio_tol``). Uniform ⇒ extending the patcher is a scale-about-the-group-origin;
    non-uniform ⇒ something messier the lead must inspect. Keyed by the group's root
    address ``("top", "group", kindIndex)``.
    """
    by_group: dict[tuple, list[dict]] = {}
    for ua, ub, how in pairs:
        addr = ua["addr"]
        root = _root_addr(addr)
        if not (isinstance(root, tuple) and len(root) == 3
                and root[0] == "top" and root[1] == "group"):
            continue
        if addr == root:  # the group's own union unit, not a child
            continue
        aw, ah = _sig_size(ua["sig"])
        bw, bh = _sig_size(ub["sig"])
        by_group.setdefault(root, []).append({
            "id": ua["id"], "kind": ua["kind"], "how": how,
            "sx": (aw / bw) if bw else None,
            "sy": (ah / bh) if bh else None,
        })

    def _tight(vals: list[float]) -> bool:
        vals = [v for v in vals if v is not None]
        return bool(vals) and (max(vals) - min(vals)) <= ratio_tol

    summary: dict[tuple, dict] = {}
    for root, children in by_group.items():
        sxs = [c["sx"] for c in children if c["sx"] is not None]
        sys_ = [c["sy"] for c in children if c["sy"] is not None]
        per_child_iso = all(
            c["sx"] is not None and c["sy"] is not None and abs(c["sx"] - c["sy"]) <= ratio_tol
            for c in children
        )
        summary[root] = {
            "n": len(children),
            "sx_range": (min(sxs), max(sxs)) if sxs else None,
            "sy_range": (min(sys_), max(sys_)) if sys_ else None,
            "uniform": bool(children) and per_child_iso and _tight(sxs) and _tight(sys_),
            "children": children,
        }
    return summary


def compare_signature(a_sig: dict, b_sig: dict, tol: float = TOL_PX
                      ) -> tuple[bool, float, list[str]]:
    """``(ok, worst_delta_px, fail_reasons)`` for one matched pair's render signatures.

    Positional geometry is compared within ``tol``; flips and snapped mask angle must
    match exactly; a masked image's raw ``geometry.size`` is a SEPARATE crop-visibility
    check (its own reason line), not folded into the position delta.
    """
    fails: list[str] = []
    if a_sig.get("type") != b_sig.get("type"):
        return (False, float("inf"), [f"type {a_sig.get('type')} != {b_sig.get('type')}"])
    if a_sig.get("flips") != b_sig.get("flips"):
        fails.append(f"flips {a_sig.get('flips')} != {b_sig.get('flips')}")
    kind = a_sig["type"]
    worst = 0.0

    def delta(a: tuple, b: tuple) -> float:
        return max(abs(x - y) for x, y in zip(a, b))

    if kind == "line":
        worst = max(delta(a_sig["endpoints"][0], b_sig["endpoints"][0]),
                    delta(a_sig["endpoints"][1], b_sig["endpoints"][1]))
    elif kind == "masked":
        worst = delta(a_sig["crop"], b_sig["crop"])
        raw_delta = delta(a_sig["raw_size"], b_sig["raw_size"])
        if raw_delta > tol:
            fails.append(f"raw image size Δ{raw_delta:.2f}px (crop visibility)")
        if a_sig["mask_angle"] != b_sig["mask_angle"]:
            fails.append(f"mask angle {a_sig['mask_angle']} != {b_sig['mask_angle']}")
    elif kind == "group":
        worst = delta(a_sig["union"], b_sig["union"])
    elif kind == "autosize":
        worst = abs(a_sig["x"] - b_sig["x"])
    else:  # frame
        worst = delta(a_sig["frame"], b_sig["frame"])

    if worst > tol:
        fails.append(f"Δ{worst:.2f}px > {tol}px")
    return (not fails, worst, fails)


def compare_slides(a_objects: dict[str, dict], b_objects: dict[str, dict],
                   slide_number: int, tol: float = TOL_PX,
                   id_rate_floor: float = 0.95) -> dict:
    """Full §Gate-compare of slide N between deck A' and deck B (both decoded id→object).

    Returns a report ``{pass, per_class, unmatched_a, unmatched_b, crosscheck,
    id_match_rate, id_stable, carved, group_child_scale}`` where
    ``per_class[kind] = {pass, worst, n, fails}``.

    ENFORCES two §Gate-compare rules:
      * text-autosize shapes are EXCLUDED from the frame compare (their
        ``naturalSize`` re-derives on OPEN, so A' and B legitimately differ) — listed
        under ``carved``, never silently compared;
      * the id-match RATE is computed; below ``id_rate_floor`` the comparison fell back
        to positional matching (``id_stable`` False) and the whole result is UNTRUSTED
        — the overall ``pass`` is forced False.
    """
    a_units = slide_units(a_objects, slide_number)
    b_units = slide_units(b_objects, slide_number)

    # ENFORCE the autosize carve-out: drop text-autosize shapes from BOTH sides before
    # matching so they never enter the frame compare (per §Gate-compare, SKILL:954).
    carve = {u["id"] for u in text_autosize_shapes(a_units)}
    carve |= {u["id"] for u in text_autosize_shapes(b_units)}
    a_units = [u for u in a_units if u["id"] not in carve]
    b_units = [u for u in b_units if u["id"] not in carve]

    pairs, unmatched_a, unmatched_b = match_units(a_units, b_units)
    crosscheck = positional_crosscheck(a_units, b_units)
    rate = id_match_rate(pairs)
    id_stable = rate >= id_rate_floor
    group_child_scale = group_child_scale_report(pairs)

    per_class: dict[str, dict] = {}
    for ua, ub, _how in pairs:
        cls = per_class.setdefault(ua["kind"], {"pass": True, "worst": 0.0, "n": 0, "fails": []})
        ok, worst, reasons = compare_signature(ua["sig"], ub["sig"], tol)
        cls["n"] += 1
        cls["worst"] = max(cls["worst"], worst)
        if not ok:
            cls["pass"] = False
            cls["fails"].append({"addr": ua["addr"], "worst": worst, "reasons": reasons})
    for ua in unmatched_a:
        cls = per_class.setdefault(ua["kind"], {"pass": True, "worst": 0.0, "n": 0, "fails": []})
        cls["pass"] = False
        cls["fails"].append({"addr": ua["addr"], "worst": float("inf"), "reasons": ["unmatched in B"]})

    overall = (
        all(c["pass"] for c in per_class.values())
        and not unmatched_a and not unmatched_b and not crosscheck
        and id_stable
    )
    return {"pass": overall, "per_class": per_class,
            "unmatched_a": unmatched_a, "unmatched_b": unmatched_b, "crosscheck": crosscheck,
            "id_match_rate": rate, "id_stable": id_stable,
            "carved": sorted(carve), "group_child_scale": group_child_scale}


# ==========================================================================
# byte-reveal (offline) — step 4: which geometry fields did AS mutate, per class.
# ==========================================================================
def object_geometry_fields(obj: dict) -> dict[str, float | None]:
    """Flat geometry field map for one archive object (the raw stored values)."""
    x, y, w, h, angle = _xywha(_geom_dict(obj))
    natural = (_pathsource(obj).get("bezierPathSource") or {}).get("naturalSize") or {}
    return {"pos_x": x, "pos_y": y, "size_w": w, "size_h": h, "angle": angle,
            "natural_w": natural.get("width"), "natural_h": natural.get("height")}


def _num_diff(a: float | None, b: float | None) -> float:
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return float("inf")
    return abs(float(a) - float(b))


def byte_reveal(a_objects: dict[str, dict], b_objects: dict[str, dict],
                pairs: list[tuple[dict, dict, str]], tol: float = 0.01
                ) -> dict[str, Counter]:
    """Per class, which geometry fields differ between the two decks' matched objects.

    Run on A vs B-pre it reveals exactly what the production AppleScript write mutated
    (image ``size``? mask ``super.geometry``? both?), which is what the lead reads to
    finalize the masked-image write rule. Returns ``{kind: Counter(field -> hits)}``.
    """
    out: dict[str, Counter] = {}
    for ua, ub, _how in pairs:
        fa = object_geometry_fields(a_objects.get(ua["id"]) or {})
        fb = object_geometry_fields(b_objects.get(ub["id"]) or {})
        mutated = [k for k in GEOM_FIELDS if _num_diff(fa[k], fb[k]) > tol]
        if mutated:
            out.setdefault(ua["kind"], Counter()).update(mutated)
    return out


# ==========================================================================
# Cross-slide locality (offline) — step 6: only slide N's member changed.
# ==========================================================================
def changed_members(deck_a: Path | str, deck_b: Path | str) -> set[str]:
    """Zip members whose bytes differ between two decks (missing on one side counts)."""
    with zipfile.ZipFile(deck_a) as za, zipfile.ZipFile(deck_b) as zb:
        names = set(za.namelist()) | set(zb.namelist())
        changed: set[str] = set()
        for name in names:
            try:
                da = za.read(name)
            except KeyError:
                changed.add(name)
                continue
            try:
                db = zb.read(name)
            except KeyError:
                changed.add(name)
                continue
            if da != db:
                changed.add(name)
    return changed


def target_member_for_slide(objects: dict[str, dict], id_to_file: dict[str, str],
                            slide_number: int) -> str | None:
    """The single ``Index/*.iwa`` member holding slide N's drawables (None if it spans)."""
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        return None
    slide = objects[order[slide_number - 1][0]]
    members = {id_to_file.get(r["id"]) for r in compose_geometry(slide, objects)}
    members.discard(None)
    return next(iter(members)) if len(members) == 1 else None


# ==========================================================================
# Keynote-touching orchestration — the LEAD runs this (guarded), NOT the sub-agent.
# ==========================================================================
def _remap_env(*, suppress: str = "", as_geometry: str = "1", geom_props: str = "1") -> None:
    """Set the env knobs remap reads at call time (module funcs read os.environ live)."""
    os.environ["OBED_SUPPRESS_GEOMETRY"] = suppress
    os.environ["OBED_AS_GEOMETRY"] = as_geometry
    os.environ["OBED_GEOM_PROPS"] = geom_props


def _log_group_child_scale(scale: dict[tuple, dict]) -> None:
    """Compact per-group table of the A'↔B group-CHILD size ratios (the lead's
    diagnostic for whether the patcher can scale group children with a uniform scale)."""
    if not scale:
        _log("GROUP-CHILD SCALE: no group children on this slide.")
        return
    _log(f"GROUP-CHILD SCALE (A'/B child size ratios, {len(scale)} group(s)):")
    _log(f"    {'group':22} {'n':>3}  {'sx range':>18}  {'sy range':>18}  uniform")
    for root, s in sorted(scale.items(), key=lambda kv: str(kv[0])):
        sx = s["sx_range"]
        sy = s["sy_range"]
        sx_s = f"{sx[0]:.4f}..{sx[1]:.4f}" if sx else "—"
        sy_s = f"{sy[0]:.4f}..{sy[1]:.4f}" if sy else "—"
        _log(f"    {str(root):22} {s['n']:>3}  {sx_s:>18}  {sy_s:>18}  "
             f"{'YES' if s['uniform'] else 'no'}")


def main(argv: list[str] | None = None) -> int:
    # Imported here so the pure comparator above imports without Keynote deps present.
    import shutil

    from obed_edom.inspect import export_slide_images, inspect_keynote
    from obed_edom.remap_keynote import _build_slide_geometry_script, remap_and_inspect

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="wall (source) .key (required for a fresh B-pre)")
    ap.add_argument("--template", type=Path, help="CG template .key (required for a fresh B-pre)")
    ap.add_argument("--slide", type=int, default=DEFAULT_SLIDE, help="slide number to gate (default 9)")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "output" / "write-gate",
                    help="scratch dir for the A'/B/B-pre decks + PNGs (Keynote-writable, not /tmp)")
    ap.add_argument("--tol", type=float, default=TOL_PX, help=f"px tolerance (default {TOL_PX})")
    ap.add_argument("--reuse-bpre", type=Path,
                    help="banked B-pre .key — SKIP the B-pre remap (needs --reuse-specs)")
    ap.add_argument("--reuse-specs", type=Path,
                    help="specs sidecar json from a prior run — SKIP the B-pre remap")
    ap.add_argument("--reuse-aprime", type=Path,
                    help="banked A' .key (built from the SAME B-pre) — SKIP regenerating A'")
    ap.add_argument("--full-a", action="store_true",
                    help="also run the full INDEPENDENT production remap A (positional-only "
                         "cross-check; different ids, so NOT id-stable — never gates)")
    ap.add_argument("--live", action="store_true",
                    help="also run the live CO-GATE — needs the lead's bounded-open guard")
    args = ap.parse_args(argv)

    N = args.slide
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    bpre_deck = out / "B_pre.key"
    b_deck = out / "B_offline.key"
    aprime_deck = out / "A_prime.key"
    a_deck = out / "A_production.key"
    specs_path = out / f"specs_slide{N}.json"
    aprime_png, b_png, a_png = out / "Aprime_png", out / "B_png", out / "A_png"

    if (args.reuse_bpre is None) != (args.reuse_specs is None):
        ap.error("--reuse-bpre and --reuse-specs go together (a banked B-pre needs its "
                 "specs sidecar). Run ONE fresh pass (no reuse flags) to bank both, then "
                 "reuse them. A banked B-pre alone cannot yield specs — the target geometry "
                 "lives in the plan's transforms, not in the attrs-only deck.")
    reuse = args.reuse_bpre is not None and args.reuse_specs is not None

    # ============================ B-pre + specs =================================
    if reuse:
        # SKIP the B-pre remap entirely: load the banked deck + specs sidecar. This is
        # the cheap patcher-iteration path (no Keynote for B-pre).
        for label, p in (("reuse-bpre", args.reuse_bpre), ("reuse-specs", args.reuse_specs)):
            if not Path(p).exists():
                ap.error(f"--{label} not found: {p}")
        sidecar = load_specs_sidecar(args.reuse_specs)
        specs_N = slide_specs(sidecar.get("specs") or [], N)
        src_counts = sidecar.get("source_counts") or {}
        shutil.copyfile(args.reuse_bpre, bpre_deck)  # never mutate the bank
        _log(f"REUSE: banked B-pre {args.reuse_bpre} + specs {args.reuse_specs} "
             f"({len(specs_N)} spec(s) for slide {N}).")
        errors = check_preconditions(specs_N, set(), N)  # reuse already validated at bank time
    else:
        if args.source is None or args.template is None:
            ap.error("--source and --template are required for a fresh B-pre "
                     "(or pass --reuse-bpre + --reuse-specs)")
        for label, deck in (("source", args.source), ("template", args.template)):
            if not deck.exists():
                ap.error(f"{label} deck not found: {deck}")
        _log(f"B-pre: remap {args.source.name} with OBED_SUPPRESS_GEOMETRY={N}")
        _remap_env(suppress=str(N))
        plan_out: dict[str, Any] = {}
        bpre_info = remap_and_inspect(
            args.source, bpre_deck, template=args.template,
            slide_range=None, export_dir=None, plan_out=plan_out, log=_log,
        )
        specs_N = slide_specs(plan_out.get("transforms") or [], N)
        reuses = plan_out.get("reuses") or []
        errors = check_preconditions(specs_N, reuse_slide_numbers(reuses), N)
        src_counts = source_kind_counts(args.source, N)
        # Bank the sidecar so later runs can --reuse-bpre + --reuse-specs (no Keynote).
        if not errors:
            write_specs_sidecar(specs_path, slide_number=N, source=args.source,
                                template=args.template, specs=specs_N, source_counts=src_counts)
            _log(f"Banked specs sidecar → {specs_path}")

    if errors:
        for e in errors:
            _log(f"PRECONDITION FAILED: {e}")
        return 2
    _log(f"Preconditions OK: slide {N} resizes a masked image ({len(specs_N)} transform(s)).")

    # Hide-addressing bridge: the production geometry body (A') addresses by WALL
    # kindIndex, but B-pre already ran deleteHides. Bridge the surviving indices so A'
    # and the patcher (B) hit the same saved objects (bridge is a no-op when the deleted
    # hides sit above every survivor, as on slide 9's top-two image hides).
    n_hides = specs_hide_count(specs_N)
    if n_hides:
        _log(f"BRIDGE: slide {N} has {n_hides} role=hide spec(s); A' kindIndex bridged to "
             "the post-deleteHides B-pre (iwa_write.bridge_kind_index), matching the patcher.")

    bpre_objects, _bp_idf, _bp_fi = _load_deck(bpre_deck)
    if reuse:
        reported = build_reported_offline(bpre_objects, N)
        _log(f"reported seed: {len(reported)} soft-class frame(s) composed OFFLINE from B-pre.")
    else:
        reported = build_reported(bpre_info.get("payload") or {}, N)
        _log(f"reported seed: {len(reported)} soft-class frame(s) from the B-pre bulk read.")

    # ==================== A' — ID-STABLE production reference ====================
    if args.reuse_aprime is not None:
        if not Path(args.reuse_aprime).exists():
            ap.error(f"--reuse-aprime not found: {args.reuse_aprime}")
        shutil.copyfile(args.reuse_aprime, aprime_deck)
        _log(f"REUSE: banked A' {args.reuse_aprime}.")
    else:
        shutil.copyfile(bpre_deck, aprime_deck)  # A' shares B-pre's drawable ids
        body = _build_slide_geometry_script(bridge_specs_kindindex(specs_N), N)
        if not body:
            _log(f"ABORT: no AppleScript geometry body built for slide {N}.")
            return 2
        _log(f"A': applying production geometry (osascript) to a copy of B-pre …")
        run_aprime(aprime_deck, body, _log)
    aprime_objects, _ap_idf, _ap_fi = _load_deck(aprime_deck)

    # ---- byte-reveal: which fields the production AS mutated (A' vs B-pre, id-matched) --
    reveal_pairs, _rua, _rub = match_units(slide_units(aprime_objects, N),
                                           slide_units(bpre_objects, N))
    reveal = byte_reveal(aprime_objects, bpre_objects, reveal_pairs)
    _log("BYTE-REVEAL (production AS mutations, A' vs B-pre) — the masked-image rule input:")
    for kind, counter in sorted(reveal.items()):
        _log(f"  {kind}: {dict(counter)}")

    # ==================== B — copy B-pre, patch slide N offline ==================
    shutil.copyfile(bpre_deck, b_deck)
    res: PatchResult = patch_slide_geometry(
        b_deck, N, specs_N, reported=reported,
        source_counts=src_counts, require_reconcile=True,
    )
    _log(f"PATCH: applied={res.applied} missed={res.missed} refused={res.refused} "
         f"soft_fallbacks={res.soft_fallbacks} value_clean={res.value_clean} "
         f"target={res.target_member}")
    assert not res.refused, f"patch refused: {res.reason}"
    assert res.soft_fallbacks == 0, "soft frames must all come from the reported seed"
    assert res.value_clean, "member rewrite was not value-clean"
    assert res.missed == 0, f"{res.missed} spec(s) missed"

    # ================ OFFLINE GATE (§Gate-compare A' vs B) + locality ============
    b_objects, _b_idf, _b_fi = _load_deck(b_deck)
    report = compare_slides(aprime_objects, b_objects, N, tol=args.tol)

    rate = report["id_match_rate"]
    if not report["id_stable"]:
        _log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        _log(f"!! ID-MATCH RATE {rate:.1%} < floor — the compare FELL BACK to positional")
        _log("!! (kind, kindIndex) matching. A' and B are supposed to share B-pre's ids,")
        _log("!! so this means A' was NOT built from this B-pre. RESULT IS UNTRUSTED.")
        _log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        _log(f"ID-MATCH RATE: {rate:.1%} of {len(reveal_pairs)} pairs by drawable id (id-stable).")
    if report["carved"]:
        _log(f"AUTOSIZE CARVE-OUT: excluded {len(report['carved'])} text-autosize shape(s) "
             f"from the frame compare: {report['carved']}")

    _log("OFFLINE GATE (§Gate-compare A' vs B):")
    for kind, cls in sorted(report["per_class"].items()):
        status = "PASS" if cls["pass"] else "FAIL"
        _log(f"  {kind}: {status}  n={cls['n']}  worst={cls['worst']:.2f}px")
        for f in cls["fails"][:8]:
            _log(f"      {f['addr']} worst={f['worst']:.2f} {f['reasons']}")
    if report["crosscheck"]:
        _log(f"  positional cross-check: {report['crosscheck']}")
    _log_group_child_scale(report["group_child_scale"])

    only_n = changed_members(bpre_deck, b_deck)
    tgt = target_member_for_slide(bpre_objects, _bp_idf, N)
    locality_ok = only_n == {tgt}
    _log(f"CROSS-SLIDE LOCALITY: changed members={sorted(only_n)} expected={{{tgt}}} "
         f"{'OK' if locality_ok else 'VIOLATED'}")

    gate_ok = report["pass"] and locality_ok
    _log("OFFLINE GATE: GREEN" if gate_ok else "OFFLINE GATE: RED (see per-class above)")

    # ============ FULL-A cross-check (optional; positional, never gates) =========
    if args.full_a:
        if args.source is None or args.template is None:
            _log("FULL-A skipped: --source/--template not supplied.")
        else:
            _log(f"FULL-A: independent production remap {args.source.name} "
                 "(OBED_AS_GEOMETRY=1 OBED_GEOM_PROPS=1) — positional cross-check only.")
            _remap_env(suppress="", as_geometry="1", geom_props="1")
            remap_and_inspect(args.source, a_deck, template=args.template,
                              slide_range=None, export_dir=a_png, log=_log)
            a_objects, _a_idf, _a_fi = _load_deck(a_deck)
            a_report = compare_slides(a_objects, b_objects, N, tol=args.tol)
            _log(f"  FULL-A id-match rate {a_report['id_match_rate']:.1%} "
                 "(low is EXPECTED — A is an independent run; positional, untrusted). "
                 "Top-level classes are validated against A' above.")
            for kind, cls in sorted(a_report["per_class"].items()):
                _log(f"    {kind}: n={cls['n']} worst={cls['worst']:.2f}px "
                     f"{'PASS' if cls['pass'] else 'FAIL'}")

    # ==================== LIVE CO-GATE (run only with --live) ====================
    if args.live:
        _log("LIVE CO-GATE: scoped inspect + PNG pixel-diff of slide N (A' vs B)")
        a_scope = inspect_keynote(aprime_deck, slide_range={N}, use_cache=False)
        b_scope = inspect_keynote(b_deck, slide_range={N}, use_cache=False)
        _log(f"  A' slide {N} items={_scoped_item_count(a_scope, N)} "
             f"B slide {N} items={_scoped_item_count(b_scope, N)}")
        export_slide_images(aprime_deck, aprime_png)
        export_slide_images(b_deck, b_png)
        _log("  PNG export done — pixel-diff slide-N frames at near-zero threshold (lead compares).")

    return 0 if gate_ok else 1


def _scoped_item_count(payload: dict, slide_number: int) -> int:
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        if number == slide_number:
            return len(slide.get("items") or [])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
