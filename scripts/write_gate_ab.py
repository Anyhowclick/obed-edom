#!/usr/bin/env python3
"""A/B validation gate for the offline geometry-WRITE (``w-offline-write-optin``).

Proves that an OFFLINE surgical patch of ONE non-reuse content slide reproduces the
PRODUCTION scripted-AppleScript geometry write, so the gate can flip ``OBED_OFFLINE_WRITE``.
Two output decks of the same wall/template are compared on slide N (default 9):

    A     = production remap (OBED_AS_GEOMETRY=1, OBED_GEOM_PROPS=1) — ground truth.
    B-pre = attrs-only pass 1 (OBED_SUPPRESS_GEOMETRY=N) — slide N carries NO geometry.
    B     = B-pre with slide N patched offline by ``iwa_write.patch_slide_geometry``.

The PRIMARY oracle is OFFLINE and value-level: the two decks' decoded slide-N geometry,
composed to the render-accurate frame JXA would report (mask crop, line endpoints, group
child-union), matched object-by-object and compared within ±2px (§Gate-compare). JXA
frame parity + a full-slide PNG pixel-diff (step 7) are the live CO-GATE.

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
import math
import os
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from obed_edom.iwa_geometry import (
    _geom_dict,
    _group_union,
    _leaf_bbox,
    _mask_geom,
    _snap90,
    _xywha,
    compose_geometry,
)
from obed_edom.iwa_kindindex import derive_kind_index, derived_kind_counts
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_write import PatchResult, patch_slide_geometry
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
    """Per-kind ``derive_kind_index`` counts of the SOURCE-wall slide (reconcile base).

    Fed to :func:`patch_slide_geometry` as ``source_counts`` so its reconcile REFUSE gate
    can confirm the saved deck's live per-kind counts equal source-minus-hides.
    """
    objects, _idf, _fi = _load_deck(source_deck)
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        raise ValueError(f"slide {slide_number} out of range (source has {len(order)} slides)")
    slide_id = order[slide_number - 1][0]
    return derived_kind_counts(derive_kind_index(objects[slide_id], objects))


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
                   slide_number: int, tol: float = TOL_PX) -> dict:
    """Full §Gate-compare of slide N between deck A and deck B (both decoded id→object).

    Returns a report ``{pass, per_class, unmatched_a, unmatched_b, crosscheck}`` where
    ``per_class[kind] = {pass, worst, n, fails}``.
    """
    a_units = slide_units(a_objects, slide_number)
    b_units = slide_units(b_objects, slide_number)
    pairs, unmatched_a, unmatched_b = match_units(a_units, b_units)
    crosscheck = positional_crosscheck(a_units, b_units)

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
    )
    return {"pass": overall, "per_class": per_class,
            "unmatched_a": unmatched_a, "unmatched_b": unmatched_b, "crosscheck": crosscheck}


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


def main(argv: list[str] | None = None) -> int:
    # Imported here so the pure comparator above imports without Keynote deps present.
    import shutil

    from obed_edom.inspect import export_slide_images, inspect_keynote
    from obed_edom.remap_keynote import remap_and_inspect

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True, help="wall (source) .key")
    ap.add_argument("--template", type=Path, required=True, help="CG template .key")
    ap.add_argument("--slide", type=int, default=DEFAULT_SLIDE, help="slide number to gate (default 9)")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "output" / "write-gate",
                    help="scratch dir for the A/B/B-pre decks + PNGs (Keynote-writable, not /tmp)")
    ap.add_argument("--tol", type=float, default=TOL_PX, help=f"px tolerance (default {TOL_PX})")
    ap.add_argument("--live", action="store_true",
                    help="also run the live CO-GATE (step 7) — needs the lead's bounded-open guard")
    args = ap.parse_args(argv)

    for label, deck in (("source", args.source), ("template", args.template)):
        if not deck.exists():
            ap.error(f"{label} deck not found: {deck}")
    N = args.slide
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    a_deck = out / "A_production.key"
    bpre_deck = out / "B_pre.key"
    b_deck = out / "B_offline.key"
    a_png, bpre_png, b_png = out / "A_png", out / "Bpre_png", out / "B_png"

    # --- step 2: B-pre (attrs-only for slide N) + capture the plan's transforms --------
    _log(f"B-pre: remap {args.source.name} with OBED_SUPPRESS_GEOMETRY={N}")
    _remap_env(suppress=str(N))
    plan_out: dict[str, Any] = {}
    bpre_info = remap_and_inspect(
        args.source, bpre_deck, template=args.template,
        slide_range=None, export_dir=bpre_png, plan_out=plan_out, log=_log,
    )
    specs_N = slide_specs(plan_out.get("transforms") or [], N)
    reuses = plan_out.get("reuses") or []

    # --- step 1: preconditions (offline) ----------------------------------------------
    errors = check_preconditions(specs_N, reuse_slide_numbers(reuses), N)
    if errors:
        for e in errors:
            _log(f"PRECONDITION FAILED: {e}")
        return 2
    _log(f"Preconditions OK: slide {N} is non-reuse and resizes a masked image "
         f"({len(specs_N)} transform(s)).")

    reported = build_reported(bpre_info.get("payload") or {}, N)
    _log(f"reported seed: {len(reported)} soft-class frame(s) from the B-pre bulk read.")

    # --- step 3: A (production geometry) ----------------------------------------------
    _log(f"A: remap {args.source.name} with OBED_AS_GEOMETRY=1 OBED_GEOM_PROPS=1")
    _remap_env(suppress="", as_geometry="1", geom_props="1")
    remap_and_inspect(args.source, a_deck, template=args.template,
                      slide_range=None, export_dir=a_png, log=_log)

    a_objects, _a_idf, _a_fi = _load_deck(a_deck)
    bpre_objects, _bp_idf, _bp_fi = _load_deck(bpre_deck)

    # --- step 4: byte-reveal (A vs B-pre) ---------------------------------------------
    a_units = slide_units(a_objects, N)
    bpre_units = slide_units(bpre_objects, N)
    reveal_pairs, _ua, _ub = match_units(a_units, bpre_units)
    reveal = byte_reveal(a_objects, bpre_objects, reveal_pairs)
    _log("BYTE-REVEAL (production AS mutations, A vs B-pre) — the masked-image rule input:")
    for kind, counter in sorted(reveal.items()):
        _log(f"  {kind}: {dict(counter)}")

    # --- step 5: B = copy B-pre, patch slide N offline --------------------------------
    shutil.copyfile(bpre_deck, b_deck)
    src_counts = source_kind_counts(args.source, N)
    res: PatchResult = patch_slide_geometry(
        b_deck, N, specs_N, reported=reported,
        source_counts=src_counts, require_reconcile=True,
    )
    _log(f"PATCH: applied={res.applied} missed={res.missed} refused={res.refused} "
         f"soft_fallbacks={res.soft_fallbacks} value_clean={res.value_clean} "
         f"target={res.target_member}")
    assert not res.refused, f"patch refused: {res.reason}"
    assert res.soft_fallbacks == 0, "soft frames must all come from the bulk read"
    assert res.value_clean, "member rewrite was not value-clean"
    assert res.missed == 0, f"{res.missed} spec(s) missed"

    # --- step 6: OFFLINE GATE (§Gate-compare) + cross-slide locality ------------------
    b_objects, _b_idf, _b_fi = _load_deck(b_deck)
    shapes_bad = text_autosize_shapes(slide_units(a_objects, N))
    if shapes_bad:
        _log(f"WARNING: {len(shapes_bad)} shape(s) on slide {N} are text-autosize; "
             "carve them out of the frame compare (SKILL:954).")
    report = compare_slides(a_objects, b_objects, N, tol=args.tol)
    _log("OFFLINE GATE (§Gate-compare A vs B):")
    for kind, cls in sorted(report["per_class"].items()):
        status = "PASS" if cls["pass"] else "FAIL"
        _log(f"  {kind}: {status}  n={cls['n']}  worst={cls['worst']:.2f}px")
        for f in cls["fails"][:8]:
            _log(f"      {f['addr']} worst={f['worst']:.2f} {f['reasons']}")
    if report["crosscheck"]:
        _log(f"  positional cross-check: {report['crosscheck']}")

    only_n = changed_members(bpre_deck, b_deck)
    tgt = target_member_for_slide(bpre_objects, _bp_idf, N)
    locality_ok = only_n == {tgt}
    _log(f"CROSS-SLIDE LOCALITY: changed members={sorted(only_n)} expected={{{tgt}}} "
         f"{'OK' if locality_ok else 'VIOLATED'}")

    gate_ok = report["pass"] and locality_ok
    _log("OFFLINE GATE: GREEN" if gate_ok else "OFFLINE GATE: RED (see per-class above)")

    # --- step 7: LIVE CO-GATE (wired; run only with --live under the lead's guard) ----
    if args.live:
        _log("LIVE CO-GATE: scoped inspect + PNG pixel-diff of slide N (A vs B)")
        a_scope = inspect_keynote(a_deck, slide_range={N}, use_cache=False)
        b_scope = inspect_keynote(b_deck, slide_range={N}, use_cache=False)
        _log(f"  A slide {N} items={_scoped_item_count(a_scope, N)} "
             f"B slide {N} items={_scoped_item_count(b_scope, N)}")
        export_slide_images(a_deck, a_png)
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
