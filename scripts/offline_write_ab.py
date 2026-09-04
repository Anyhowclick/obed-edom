#!/usr/bin/env python3
"""Whole-deck A/B gate for the offline geometry-WRITE opt-in (``w-offline-write-optin``).

Runs :func:`obed_edom.remap_keynote.remap_and_inspect` TWICE against the same
source/template pair:

    A = production run, ``OBED_OFFLINE_WRITE`` unset (today's AppleScript-only path).
    B = the SAME plan with ``OBED_OFFLINE_WRITE=verify`` (surgical offline IWA patch,
        AppleScript fallback only for refused slides / individually missed specs).

A and B are two INDEPENDENT Keynote runs (different drawable ids, different group
z-order), so they can only be compared POSITIONALLY — this gate does NOT use
``write_gate_ab.compare_slides`` (its id-match gate assumes A' shares B-pre's drawable
ids, which is false here; two fresh remaps never share ids). Instead every planned
non-reuse, non-donor slide's render units (``write_gate_ab.slide_units``) are compared
as a per-kind MULTISET (:func:`compare_units_multiset`): counts must agree per kind,
then each side is sorted by its own rounded box and zipped positionally.

Bars: shape/line <= ``--tol-hard``, image/group/child <= ``--tol-soft``, text is
INFORMATIONAL only — reported, never gates ("text: informational only — UNVERIFIED by
this gate" prints explicitly in the summary; text geometry sits outside the offline
patch's exact-class guarantee, and autosize ``naturalSize`` legitimately differs between
two independent Keynote opens). Plus: ``applied_A == applied_B`` (attrs mode credits the
same objects on both runs), and on run B every offline slide's patch has
``refused == []``, ``missedSpecs == 0``, ``softFallbacks == 0``, ``valueClean``, and
run B's own ``offlineVerifyPass``/``liveVerifyPass`` (from ``offline_write._say_verify_report``)
are not ``False`` (:func:`summary_gate_reasons`).

A SECOND pass (:func:`compare_units_by_addr`) matches A/B units by identical ``addr``
(``("top", kind, kindIndex)``, or a group-child chain) instead of sorted position, and
logs the worst delta per kind alongside the multiset pass. A permutation that swaps two
same-box objects fools the multiset (same population, same sorted order) but shows up
here as a large per-address delta — GATING for shape/line/image/movie, informational
for group (z-order/dedup legitimately reorders group addressing between two independent runs).

Timing: the Map deck pair takes roughly 10-30 minutes end to end (two Keynote remaps +
one offline compare). The Full deck's bulk-geometry cache is often STALE (see the
umbrella plan's "Things to be aware of"), which turns a cold run into 1-2 hours — run it
as its own separate pass. Never run this concurrently with any other Keynote automation
(Session-14 cache corruption) — one deck warm at a time, and Keynote must be completely
free (no other open decks) before starting.

    .venv/bin/python scripts/offline_write_ab.py --source WALL.key --template CG.key \\
        --out output/offline-write-ab
"""
from __future__ import annotations

import argparse
import os
import time
import sys
from pathlib import Path
from typing import Any

# `python scripts/x.py` puts scripts/ (not the repo root) on sys.path[0].
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOL_HARD = 0.5
TOL_SOFT = 1.0

_HARD_KINDS = {"shape", "line"}


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _unit_box(u: dict[str, Any]) -> tuple[float, float, float, float]:
    """``(x, y, w, h)`` box for one ``write_gate_ab.slide_units`` render unit, any sig type."""
    sig = u.get("sig") or {}
    box = sig.get("frame") or sig.get("crop") or sig.get("union")
    if box:
        return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    if "endpoints" in sig:
        (sx, sy), (ex, ey) = sig["endpoints"]
        return (min(sx, ex), min(sy, ey), abs(ex - sx), abs(ey - sy))
    if "x" in sig:
        return (float(sig["x"]), 0.0, 0.0, 0.0)
    return (0.0, 0.0, 0.0, 0.0)


def _sort_key(u: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y, w, h = _unit_box(u)
    return (round(x, 1), round(y, 1), round(w, 1), round(h, 1))


def compare_units_multiset(
    a_units: list[dict[str, Any]],
    b_units: list[dict[str, Any]],
    tol_hard: float = TOL_HARD,
    tol_soft: float = TOL_SOFT,
) -> dict[str, Any]:
    """Per-kind MULTISET comparison of two INDEPENDENT runs' render units (no shared
    drawable ids to match by): counts must agree per kind, then each side is sorted by
    its own rounded box and zipped positionally, ``max`` per-index delta per kind.

    ``write_gate_ab.slide_units`` already flattens a group's own union box AND every
    recursive child into the same flat list, so bucketing by ``kind`` alone gives
    "groups as a set of union boxes" and "children as their own per-kind set" for free —
    no extra group-expansion logic needed here. Shape/line gate at ``tol_hard``;
    image/movie/group/child gate at ``tol_soft``; text is INFORMATIONAL (x-delta only,
    never gates the overall pass/fail).

    Returns ``{"pass": bool, "per_kind": {kind: {n_a, n_b, pass, worst, reasons,
    informational?}}}``.
    """
    a_by_kind: dict[str, list[dict[str, Any]]] = {}
    b_by_kind: dict[str, list[dict[str, Any]]] = {}
    for u in a_units:
        a_by_kind.setdefault(u["kind"], []).append(u)
    for u in b_units:
        b_by_kind.setdefault(u["kind"], []).append(u)

    per_kind: dict[str, dict[str, Any]] = {}
    overall = True
    for kind in sorted(set(a_by_kind) | set(b_by_kind)):
        a_list = sorted(a_by_kind.get(kind, []), key=_sort_key)
        b_list = sorted(b_by_kind.get(kind, []), key=_sort_key)
        entry: dict[str, Any] = {
            "n_a": len(a_list),
            "n_b": len(b_list),
            "pass": True,
            "worst": 0.0,
            "reasons": [],
        }
        if len(a_list) != len(b_list):
            entry["pass"] = False
            entry["reasons"].append(f"count {len(a_list)} != {len(b_list)}")
            per_kind[kind] = entry
            overall = False
            continue
        x_only = kind == "text"
        worst = 0.0
        for ua, ub in zip(a_list, b_list):
            ax, ay, aw, ah = _unit_box(ua)
            bx, by, bw, bh = _unit_box(ub)
            delta = (
                abs(ax - bx)
                if x_only
                else max(abs(ax - bx), abs(ay - by), abs(aw - bw), abs(ah - bh))
            )
            worst = max(worst, delta)
        entry["worst"] = worst
        if kind == "text":
            entry["informational"] = True
        else:
            tol = tol_hard if kind in _HARD_KINDS else tol_soft
            if worst > tol:
                entry["pass"] = False
                entry["reasons"].append(f"worst Δ{worst:.2f}px > {tol}px")
                overall = False
        per_kind[kind] = entry
    return {"pass": overall, "per_kind": per_kind}


def _log_multiset_report(report: dict[str, Any]) -> None:
    for kind, entry in sorted(report["per_kind"].items()):
        if kind == "text":
            _log(
                f"    text     n_a={entry['n_a']:<4} n_b={entry['n_b']:<4} "
                f"worst={entry['worst']:.2f}px  "
                "text: informational only — UNVERIFIED by this gate"
            )
            continue
        tag = "info" if entry.get("informational") else ("PASS" if entry["pass"] else "FAIL")
        _log(
            f"    {kind:8} n_a={entry['n_a']:<4} n_b={entry['n_b']:<4} "
            f"worst={entry['worst']:.2f}px  {tag}"
            + (f"  {entry['reasons']}" if entry.get("reasons") else "")
        )


_ADDR_GATING_KINDS = {"shape", "line", "image", "movie"}


def compare_units_by_addr(
    a_units: list[dict[str, Any]],
    b_units: list[dict[str, Any]],
    tol_hard: float = TOL_HARD,
    tol_soft: float = TOL_SOFT,
) -> dict[str, Any]:
    """SECOND pass: match A/B units by identical ``addr`` (``write_gate_ab.slide_units``'s
    ``("top", kind, kindIndex)``, or a nested group-child chain) rather than the multiset's
    sorted position. Only addresses present on BOTH sides are compared (a count mismatch
    is already caught by :func:`compare_units_multiset`); this pass exists to catch a
    same-population PERMUTATION the multiset can't see — same boxes, different (kind,
    kindIndex) assignment — which shows up here as a large per-address delta.

    GATES shape/line/image/movie at ``tol_hard``/``tol_soft``; every other kind (group,
    child, text) is informational only — logged, never gates.

    Returns ``{"pass": bool, "per_kind": {kind: {n, worst, pass, reasons}}}``.
    """
    a_by_addr = {tuple(u["addr"]): u for u in a_units}
    b_by_addr = {tuple(u["addr"]): u for u in b_units}
    per_kind: dict[str, dict[str, Any]] = {}
    overall = True
    for addr in sorted(set(a_by_addr) & set(b_by_addr), key=str):
        ua, ub = a_by_addr[addr], b_by_addr[addr]
        kind = ua["kind"]
        entry = per_kind.setdefault(
            kind, {"n": 0, "worst": 0.0, "pass": True, "reasons": [],
                   "informational": kind not in _ADDR_GATING_KINDS}
        )
        ax, ay, aw, ah = _unit_box(ua)
        bx, by, bw, bh = _unit_box(ub)
        delta = (
            abs(ax - bx)
            if kind == "text"
            else max(abs(ax - bx), abs(ay - by), abs(aw - bw), abs(ah - bh))
        )
        entry["n"] += 1
        entry["worst"] = max(entry["worst"], delta)
        if kind in _ADDR_GATING_KINDS:
            tol = tol_hard if kind in _HARD_KINDS else tol_soft
            if delta > tol:
                entry["pass"] = False
                entry["reasons"].append(f"addr {addr} Δ{delta:.2f}px > {tol}px")
                overall = False
    unmatched = (set(a_by_addr) | set(b_by_addr)) - (set(a_by_addr) & set(b_by_addr))
    return {"pass": overall, "per_kind": per_kind, "unmatched_addrs": len(unmatched)}


def summary_gate_reasons(ow: dict[str, Any], applied_a: int, applied_b: int) -> list[str]:
    """Reasons run B's ``info["offlineWrite"]`` summary should turn OFFLINE-WRITE GATE
    red — empty list == green on this part of the gate. Pure, no Keynote: unit-tested
    directly against a synthetic ``ow`` dict.

    ``offlineVerifyPass``/``liveVerifyPass`` are the bools ``offline_write._say_verify_report``
    returned for run B's own verify passes (offline compose vs planned, and Keynote-
    reported vs planned); checked for an explicit ``False`` (not merely absent) so a run
    that never verified — ``mode`` wasn't ``"verify"`` — doesn't spuriously fail here.
    """
    reasons: list[str] = []
    refused = ow.get("refused") or []
    missed_specs = int(ow.get("missedSpecs") or 0)
    soft_fallbacks = int(ow.get("softFallbacks") or 0)
    value_clean = bool(ow.get("valueClean", True))
    if refused:
        reasons.append(f"{len(refused)} slide(s) refused the offline patch: {refused}")
    if missed_specs:
        reasons.append(
            f"{missed_specs} spec(s) missed the offline patch (fallback should cover every miss)."
        )
    if soft_fallbacks:
        reasons.append(
            f"{soft_fallbacks} soft (group/text/masked) frame(s) used a stale fallback, "
            "not the live seed."
        )
    if not value_clean:
        reasons.append("at least one patched slide's zip member rewrite was not value-clean.")
    if applied_a != applied_b:
        reasons.append(
            f"applied_A={applied_a} != applied_B={applied_b} "
            "(attrs mode should credit the same objects on both runs)."
        )
    if ow.get("offlineVerifyPass") is False:
        reasons.append(
            "offline-write verify (offline compose vs planned) reported FAIL — see the "
            "per-kind lines above."
        )
    if ow.get("liveVerifyPass") is False:
        reasons.append(
            "offline-write live verify (Keynote-reported vs planned) reported FAIL — see "
            "the per-kind lines above."
        )
    return reasons


def _log_addr_report(report: dict[str, Any]) -> None:
    _log(f"  addr-matched pass ({report['unmatched_addrs']} addr(s) unmatched, skipped):")
    for kind, entry in sorted(report["per_kind"].items()):
        if kind == "text":
            tag = "text: informational only — UNVERIFIED by this gate"
        else:
            tag = "info" if entry.get("informational") else ("PASS" if entry["pass"] else "FAIL")
        _log(
            f"    {kind:8} n={entry['n']:<4} worst={entry['worst']:.2f}px  {tag}"
            + (f"  {entry['reasons']}" if entry.get("reasons") else "")
        )


def main(argv: list[str] | None = None) -> int:
    # Imported here so the pure comparator above imports without Keynote/iwa deps present.
    from obed_edom import offline_write  # noqa: PLC0415
    from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415
    from obed_edom.map_remap import slides_for_plan  # noqa: PLC0415
    from obed_edom.remap_keynote import remap_and_inspect  # noqa: PLC0415
    from scripts.write_gate_ab import _remap_env, slide_units  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", type=Path, required=True, help="wall (source) .key")
    ap.add_argument("--template", type=Path, required=True, help="CG template .key")
    ap.add_argument(
        "--out", type=Path, required=True,
        help="scratch dir for the A/B decks (Keynote-writable, not /tmp)",
    )
    ap.add_argument("--slides", help="slide range A-B to remap (default: whole deck)")
    ap.add_argument(
        "--tol-hard", type=float, default=TOL_HARD,
        help=f"shape/line px tolerance (default {TOL_HARD})",
    )
    ap.add_argument(
        "--tol-soft", type=float, default=TOL_SOFT,
        help=f"image/group/child px tolerance (default {TOL_SOFT})",
    )
    args = ap.parse_args(argv)

    for label, deck in (("source", args.source), ("template", args.template)):
        if not deck.exists():
            ap.error(f"{label} deck not found: {deck}")

    slide_range = None
    if args.slides:
        lo, _, hi = args.slides.partition("-")
        slide_range = (int(lo), int(hi or lo))

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    a_deck = out / "A_unflagged.key"
    b_deck = out / "B_flagged.key"

    _log(f"A: production remap {args.source.name} (OBED_OFFLINE_WRITE unset) -> {a_deck}")
    _remap_env(suppress="", as_geometry="1", geom_props="1")
    os.environ.pop("OBED_OFFLINE_WRITE", None)
    plan_a: dict[str, Any] = {}
    info_a = remap_and_inspect(
        args.source, a_deck, template=args.template, slide_range=slide_range,
        export_dir=None, plan_out=plan_a, log=_log,
    )

    _log(f"B: same plan, OBED_OFFLINE_WRITE=verify -> {b_deck}")
    _remap_env(suppress="", as_geometry="1", geom_props="1")
    os.environ["OBED_OFFLINE_WRITE"] = "verify"
    plan_b: dict[str, Any] = {}
    try:
        info_b = remap_and_inspect(
            args.source, b_deck, template=args.template, slide_range=slide_range,
            export_dir=None, plan_out=plan_b, log=_log,
        )
    finally:
        os.environ.pop("OBED_OFFLINE_WRITE", None)

    ow = info_b.get("offlineWrite") or {}
    offline_slides = set(ow.get("slides") or [])
    if not offline_slides:
        _log(
            "ABORT: run B took no slide offline (OBED_AS_GEOMETRY off, or no slide "
            "qualified — check the log above)."
        )
        return 2

    applied_a = int(info_a.get("applied") or 0)
    applied_b = int(info_b.get("applied") or 0)
    _log(
        f"B offline-write summary: {len(offline_slides)} slide(s) offline, "
        f"refused={ow.get('refused') or []}, missedSpecs={ow.get('missedSpecs') or 0}, "
        f"softFallbacks={ow.get('softFallbacks') or 0}, valueClean={ow.get('valueClean', True)}, "
        f"offlineVerifyPass={ow.get('offlineVerifyPass')}, liveVerifyPass={ow.get('liveVerifyPass')}, "
        f"applied={ow.get('applied')}."
    )

    reasons = summary_gate_reasons(ow, applied_a, applied_b)
    for reason in reasons:
        _log(f"RED: {reason}")
    gate_ok = not reasons

    a_objects, _a_idf, _a_fi = _load_deck(a_deck)
    b_objects, _b_idf, _b_fi = _load_deck(b_deck)

    reuses = plan_a.get("reuses") or []
    reuse_slides = {int(r["slide"]) for r in reuses}
    wanted = slides_for_plan(slide_range)
    # Real `reuses` (not []) so donors are excluded by the same logic run B's own pass-1
    # used — compared_slides then equals B's offline set exactly, no separate recomputation.
    compared_slides = sorted(
        offline_write._offline_write_slides(plan_a.get("transforms") or [], reuses, reuse_slides, wanted)
    )
    _log(f"Comparing {len(compared_slides)} planned non-reuse, non-donor slide(s): {compared_slides}")

    for n in compared_slides:
        a_units = slide_units(a_objects, n)
        b_units = slide_units(b_objects, n)
        report = compare_units_multiset(a_units, b_units, args.tol_hard, args.tol_soft)
        _log(f"  slide {n}:" + (" PASS" if report["pass"] else " FAIL"))
        _log_multiset_report(report)
        if not report["pass"]:
            gate_ok = False

        addr_report = compare_units_by_addr(a_units, b_units, args.tol_hard, args.tol_soft)
        _log_addr_report(addr_report)
        if not addr_report["pass"]:
            _log(f"  slide {n}: addr-matched pass FAIL (see above) — a permutation may be fooling the multiset pass.")
            gate_ok = False

    _log("OFFLINE-WRITE GATE: GREEN" if gate_ok else "OFFLINE-WRITE GATE: RED (see above)")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
