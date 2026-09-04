#!/usr/bin/env python3
"""Whole-deck A/B gate for the offline geometry-WRITE opt-in (``w-offline-write-optin``).

Runs :func:`obed_edom.remap_keynote.remap_and_inspect` TWICE against the same
source/template pair:

    A = the scripted-AppleScript baseline, ``OBED_OFFLINE_WRITE=off`` set EXPLICITLY
        (never relies on the ambient default, whatever it currently is).
    B = the SAME plan with ``OBED_OFFLINE_WRITE={verify,on}`` (surgical offline IWA patch,
        AppleScript fallback only for refused slides / individually missed specs).

A and B are two INDEPENDENT Keynote runs, but the output deck's drawable ids are copied
straight from the SOURCE (not regenerated per run) — so every object that survives both
runs' pass 1 (reuse-pasted copies and stat-finalize dedup deletions excepted) shares the
SAME id in A and B. That makes drawable-IDENTITY matching the PRIMARY gate on every
planned non-reuse, non-donor slide (:func:`compare_units_identity`): the id SETS must be
equal (``id_rate == 1.0``, no unmatched on either side). Matching pairs by ``(id, kind)``
composite, not id alone — a text-bearing shape emits TWO units sharing one drawable id
(a ``duplicateOf`` twin: the text unit and the shape unit), so id-only matching can
cross-pair a text unit to its own twin's shape unit and silently orphan the other side.
Each matched pair's render geometry is then compared per D8 bucket (top-level kind, or
``"child:" + kind`` for a group's recursive children).

A SECOND, always-on oracle (:func:`plan_oracle_slide`, D3) resolves each planned transform
to a drawable id via the SOURCE deck's kind index and checks the id's composed geometry in
BOTH A and B against the spec's target — independent of Keynote's own z-order/kindIndex
bookkeeping (immune to Bring-to-Front re-indexing and to a deleted hide shifting the
surviving indices), so stat-finalize slides need no exclusion. This oracle covers
shape/line, unmasked image/movie, and group (its union). Text (autosize geometry) is NOT
offline-recoverable from raw IWA, so it is skipped by this oracle and left entirely to
the identity compare above.

EVERY bucket in the identity compare GATES — there is no informational demotion. The
oracle already holds A and B each individually to ``tols.hard``/``tols.soft`` against
the SAME plan, so their MUTUAL distance is budgeted at TWICE that (two independent runs
each within r of one centre can be up to 2r apart): shape/line at ``2 * tols.hard``,
group union and unmasked image/movie at ``2 * tols.soft`` (:func:`tol_for_bucket`).
``child:*`` (a group child's live layout, not oracle-covered at all) gates at
``tols.child``; masked image/movie at ``tols.mask``; text at ``tols.text``. A structural
mismatch a matched pair's render signature reports — TYPE (e.g. ``autosize`` vs
``frame``, Keynote silently freezing a grow-to-fit text box), ``flips``, or masked
``mask_angle`` — always fails its pair regardless of the tolerance used, since
``write_gate_ab.compare_signature`` reports those independently of the geometry delta.

Health gates run BEFORE any geometry compare: an Accessibility pre-flight (``front``
z-order raises silently no-op without it), a Keynote-open-documents pre-flight
(:func:`keynote_open_documents` -- ABORTS if anything is already open; a stray document
left by a swallowed close is what made a real run inherit the previous run's B_flagged
and blow memory on the two-tier read), pass-2 (stat-finalize) health on run A --
aborting before B ever starts -- then A/B pass-2 parity and plan parity. Each fresh run
(A and B) is followed by the SAME open-documents check, WARNing loudly and closing only
that run's own deck if Keynote left it open (never anyone else's). Plan parity
checks ``transforms``/``reuses`` for exact equality, but NOT ``suppressGeometry`` — that
key differs from A to B BY CONSTRUCTION (A, the production path, never suppresses
geometry; B suppresses exactly the compared-slide set) — instead A's must be empty and
B's must equal the compared-slide set exactly. :func:`compare_units_multiset`
(sorted-position, no id needed) and :func:`compare_units_by_addr` (kindIndex-matched) are
kept as INFORMATIONAL cross-checks only -- the latter runs only when identity matching
itself failed, as a permutation diagnostic (same population, different pairing).

Each fresh run persists a ``<deck>.run.json`` beside the deck (:func:`run_record`) so a
later invocation can ``--reuse-a``/``--reuse-b`` the SAME compare with no Keynote at all;
a reused record refuses on a gate-version or deck-digest mismatch.

Timing: the Map deck pair takes roughly 10-30 minutes end to end (two Keynote remaps +
one offline compare). The Full deck's bulk-geometry cache is often STALE (see the
umbrella plan's "Things to be aware of"), which turns a cold run into 1-2 hours — run it
as its own separate pass (``--no-validate``). Never run this concurrently with any other
Keynote automation (Session-14 cache corruption) — one deck warm at a time, and Keynote
must be completely free (no other open decks) before starting.

    .venv/bin/python scripts/offline_write_ab.py --source WALL.key --template CG.key \\
        --out output/offline-write-ab
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple

# `python scripts/x.py` puts scripts/ (not the repo root) on sys.path[0].
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GATE_VERSION = 2

TOL_HARD = 0.5
TOL_SOFT = 1.0
TOL_MASK = 2.0
TOL_TEXT = 2.0
TOL_CHILD = 2.0

_HARD_KINDS = {"shape", "line"}
_TEXT_BUCKETS = {"text"}  # "child:text" is unreachable: `_child_kind` never yields "text"

# D4 pass-2 (stat-finalize) health, from `keynote._run_stat_finalize`'s result dict.
PASS2_ZERO_KEYS = ("unresolved", "dedupShortfall", "badgeUnresolved")
PASS2_PARITY_KEYS = (
    "jobs", "done", "skipped", "sized", "sizeSkips", "front", "dedupDeleted",
    "dedupShortfall", "sigFallback", "unresolved", "badgeFallback", "badgeUnresolved",
)
PASS2_WARN_KEYS = ("sigFallback", "badgeFallback")

_ACCESSIBILITY_ERR_CODES = ("-1743", "-25211")
_FRONT_ERR_RE = re.compile(r"frontErr=(.*?) exported=")


class Tolerances(NamedTuple):
    hard: float = TOL_HARD
    soft: float = TOL_SOFT
    mask: float = TOL_MASK
    text: float = TOL_TEXT
    child: float = TOL_CHILD


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================================================
# Pre-flight + pass-2 health (D4/D5) — pure, unit-tested via monkeypatched subprocess.
# ==========================================================================
def accessibility_ok() -> tuple[bool, str]:
    """``(True, "true")`` when the Accessibility API is enabled for this process's host
    app, else ``(False, detail)``. z-order raises (``front``) silently no-op without it."""
    proc = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to UI elements enabled'],
        capture_output=True, text=True, check=False,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return False, (proc.stderr or out or "osascript failed").strip()
    if out.lower() != "true":
        return False, out or "Accessibility not enabled"
    return True, out


def keynote_open_documents() -> list[str]:
    """Every open Keynote document's name — empty when Keynote isn't running, or is
    running with no documents open. ``if it is running`` short-circuits so this never
    LAUNCHES Keynote itself; a stray document left open (a swallowed close from a prior
    run) is exactly what caused the Full-deck gate to inherit the previous run's
    B_flagged and blow memory on the two-tier read."""
    from obed_edom import keynote_app  # noqa: PLC0415

    proc = subprocess.run(
        ["osascript", "-e",
         f'tell application id "{keynote_app.bundle_id()}" to if it is running then '
         "get name of documents"],
        capture_output=True, text=True, check=False,
    )
    out = (proc.stdout or "").strip()
    if not out:
        return []
    return [name.strip() for name in out.split(",") if name.strip()]


def _close_keynote_document(name: str) -> None:
    """Close every open document named ``name`` (exact match), discarding changes."""
    from obed_edom import keynote_app  # noqa: PLC0415

    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e",
         f'tell application id "{keynote_app.bundle_id()}" to close (every document '
         f'whose name is "{escaped}") saving no'],
        capture_output=True, text=True, check=False,
    )


def _warn_and_close_stray_documents(label: str, deck: Path) -> None:
    """After a fresh run, log a loud WARN naming every Keynote document still open, then
    close ONLY the ones matching THIS run's own deck (``deck.stem``) -- never anything
    else -- so a swallowed close doesn't strand the next run's Keynote session holding
    stale documents (the Full-deck-gate memory blowup this guards against)."""
    open_docs = keynote_open_documents()
    if not open_docs:
        return
    _log(f"WARN: {label}: Keynote still has {len(open_docs)} document(s) open after "
         f"this run: {open_docs}.")
    own = [name for name in open_docs if Path(name).stem == deck.stem]
    for name in own:
        _close_keynote_document(name)
        _log(f"Closed stray document {name!r} (matches {label}'s own deck {deck.name}).")


def quit_keynote_and_wait(timeout: float = 90.0) -> tuple[bool, float]:
    """``quit saving no``, then poll BY BUNDLE ID (never by process name -- this
    machine's Keynote installs as "Keynote Creator Studio.app", and matching a bare
    "Keynote" process name would also be wrong on a stock install with a differently-
    named helper) via System Events' process count, until it reaches 0 (or ``timeout``
    seconds elapse). Returns ``(ok, elapsed)`` -- ``ok`` False means still running at
    timeout; the caller WARNs that. Never raises: a quit/osascript failure just means
    Keynote wasn't running, which is the goal state anyway.

    Only a LITERAL ``"0"`` stdout on a SUCCESSFUL (``returncode == 0``) poll counts as
    gone; a nonzero returncode or empty/garbled stdout (a flaky System Events call, NOT
    proof Keynote quit) keeps polling rather than declaring victory on ambiguous output.
    """
    from obed_edom import keynote_app  # noqa: PLC0415

    bundle = keynote_app.bundle_id()
    subprocess.run(
        ["osascript", "-e", f'tell application id "{bundle}" to quit saving no'],
        capture_output=True, text=True, check=False,
    )
    count_script = (
        'tell application "System Events" to count '
        f'(every process whose bundle identifier is "{bundle}")'
    )
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        proc = subprocess.run(["osascript", "-e", count_script],
                              capture_output=True, text=True, check=False)
        count = (proc.stdout or "").strip()
        if proc.returncode == 0 and count == "0":
            return True, time.monotonic() - start
        time.sleep(1.0)
    return False, time.monotonic() - start


def front_err_from_raw(raw: str) -> str:
    """The ``frontErr=`` field out of ``_run_stat_finalize``'s raw AppleScript return."""
    match = _FRONT_ERR_RE.search(raw or "")
    return match.group(1).strip() if match else ""


def pass2_health(result: dict[str, Any] | None, *, label: str, expect_raises: bool,
                 zero_keys_hard: bool = True) -> list[str]:
    """RED reasons for one run's pass-2 (stat-finalize) result — empty == healthy.

    ``result is None`` (no stat/badge jobs planned) is healthy (D4). The no-op script
    form (``_run_stat_finalize`` never built a script — all three job lists were empty)
    returns ``{"skipped": True, ...}`` — ``skipped`` there is a BOOL sentinel, not the
    per-job skip COUNT the rest of this function reads as an int; treat it as healthy
    before the count checks would otherwise misread ``True`` as ``1``. WARN-only keys
    (``PASS2_WARN_KEYS``) never appear here — a non-zero fallback count is logged
    separately, it does not gate.

    ``zero_keys_hard`` is the ``--pass2-bar`` switch (``strict`` -> ``True``, the
    default; ``parity`` -> ``False``): under ``parity`` a nonzero ``PASS2_ZERO_KEYS``
    value is tolerated here (the caller WARNs it separately, gated on A==B by
    :func:`pass2_parity`), and a ``frontErr`` WITHOUT an Accessibility code
    (``_ACCESSIBILITY_ERR_CODES`` — a stray GUI raise miss like ``"[-1719]"`` "invalid
    index", not a permissions problem) is tolerated too. An Accessibility-coded
    ``frontErr`` stays HARD in BOTH modes -- it means z-order raises are silently
    no-op'ing, never a benign miss. ``ok``, ``done+skipped==jobs``, and
    ``front >= 1`` when ``expect_raises`` stay HARD in both modes.
    """
    if result is None:
        return []
    if result.get("skipped") is True:
        return []
    reasons: list[str] = []
    if not result.get("ok", False):
        reasons.append(f"{label}: pass-2 ok=False")
    if zero_keys_hard:
        for key in PASS2_ZERO_KEYS:
            val = int(result.get(key) or 0)
            if val:
                reasons.append(f"{label}: {key}={val} (expected 0)")
    front_err = front_err_from_raw(result.get("raw") or "")
    if front_err:
        is_accessibility = any(code in front_err for code in _ACCESSIBILITY_ERR_CODES)
        if is_accessibility or zero_keys_hard:
            tag = " (Accessibility denied)" if is_accessibility else ""
            reasons.append(f"{label}: frontErr={front_err!r}{tag}")
    jobs = int(result.get("jobs") or 0)
    done = int(result.get("done") or 0)
    skipped = int(result.get("skipped") or 0)
    if done + skipped != jobs:
        reasons.append(f"{label}: done({done})+skipped({skipped}) != jobs({jobs})")
    front = int(result.get("front") or 0)
    if expect_raises and front < 1:
        reasons.append(f"{label}: front={front} but the plan carried stat jobs or badge raises")
    return reasons


def pass2_parity(a: dict[str, Any] | None, b: dict[str, Any] | None, *,
                 front_hard: bool = True) -> list[str]:
    """A/B parity on ``PASS2_PARITY_KEYS`` — ``raw`` is deliberately ignored.

    ``front_hard=False`` (``--pass2-bar parity``) excludes ``front`` from this HARD
    check -- GUI Bring-to-Front raises are flaky and don't move geometry, so the
    caller WARNs an A/B ``front`` mismatch separately instead of gating on it. Every
    other key (``jobs``/``done``/``skipped``/``sized``/``sizeSkips``/``dedupDeleted``/
    ``dedupShortfall``/``sigFallback``/``unresolved``/``badgeFallback``/
    ``badgeUnresolved``) stays HARD in both modes.
    """
    a = a or {}
    b = b or {}
    reasons: list[str] = []
    keys = PASS2_PARITY_KEYS if front_hard else tuple(k for k in PASS2_PARITY_KEYS if k != "front")
    for key in keys:
        va = int(a.get(key) or 0)
        vb = int(b.get(key) or 0)
        if va != vb:
            reasons.append(f"pass-2 {key}: A={va} != B={vb}")
    return reasons


def plan_parity(
    plan_a: dict[str, Any], plan_b: dict[str, Any], compared_slides: list[int]
) -> list[str]:
    """A and B must plan the SAME ``transforms``/``reuses`` (D5) — any drift makes the
    numbers meaningless (they are no longer comparing the same plan).

    ``suppressGeometry`` is NOT compared for equality: it differs from A to B BY
    CONSTRUCTION (A never suppresses geometry; B suppresses exactly the offline-write
    set), so an equality check here could never go GREEN. Instead: A's
    ``suppressGeometry`` must be empty (A is the production AppleScript-only path), and
    B's must equal ``compared_slides`` exactly (the same non-reuse, non-donor slide set
    the rest of this gate compares).
    """
    reasons: list[str] = []
    for key in ("transforms", "reuses"):
        if plan_a.get(key) != plan_b.get(key):
            reasons.append(f"plan {key} drift between A and B")
    a_suppress = plan_a.get("suppressGeometry") or []
    if a_suppress:
        reasons.append(f"plan A suppressGeometry not empty: {sorted(a_suppress)}")
    b_suppress = sorted(plan_b.get("suppressGeometry") or [])
    expected = sorted(compared_slides)
    if b_suppress != expected:
        reasons.append(f"plan B suppressGeometry {b_suppress} != compared slides {expected}")
    return reasons


# ==========================================================================
# Buckets + tolerances (D7/D8).
# ==========================================================================
def unit_bucket(unit: dict[str, Any]) -> str:
    """Top-level unit keeps its ``kind``; a group's recursive CHILD gets ``"child:" +
    kind`` — separates a child image/group from its top-level bucket (D8)."""
    addr = unit["addr"]
    kind = unit["kind"]
    return kind if addr[0] == "top" else f"child:{kind}"


def tol_for_bucket(bucket: str, sig_type: str | None, tols: Tolerances) -> float:
    """A-vs-B GATING tolerance, per UNIT (every bucket gates -- there is no
    informational demotion; the plan oracle, :func:`plan_oracle_slide`, is the PRIMARY
    per-side bar, held to ``tols.hard``/``tols.soft`` directly against the plan).

    A and B are two INDEPENDENT Keynote runs, each individually within the oracle's
    per-side tolerance of the SAME plan -- their MUTUAL distance budget is therefore
    twice the per-side budget (two points each within r of a centre can be up to 2r
    apart). Measured on the Map deck (2026-09-04): line 0.95px, group 1.43px,
    child:image 1.83px -- all comfortably under the doubled bars below, none of which
    would pass at the single-sided ``tols.hard``/``tols.soft``.

    Priority: any ``child:*`` bucket (a group child's live layout, not oracle-covered
    at all) -> ``tols.child``; masked sig -> ``tols.mask``; text (fixed-frame or
    autosize, x-only) -> ``tols.text``; shape/line -> ``2 * tols.hard``; everything else
    (group union, unmasked image/movie) -> ``2 * tols.soft``.
    """
    if bucket.startswith("child:"):  # child sigs are always "frame" (no masked child)
        return tols.child
    if sig_type == "masked":
        return tols.mask
    if bucket in _TEXT_BUCKETS or sig_type == "autosize":
        return tols.text
    return 2 * tols.hard if bucket in _HARD_KINDS else 2 * tols.soft


# ==========================================================================
# compare_units_multiset / compare_units_by_addr — kept as INFORMATIONAL cross-checks.
# ==========================================================================
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
    """INFORMATIONAL cross-check (D2): per-bucket (:func:`unit_bucket`) MULTISET of two
    runs' render units, no id needed — counts must agree per bucket, then each side is
    sorted by its own rounded box and zipped positionally, ``max`` per-index delta.

    ``write_gate_ab.slide_units`` already flattens a group's own union box AND every
    recursive child into the same flat list; bucketing by :func:`unit_bucket` (not raw
    ``kind``) keeps a group CHILD out of its parent's top-level bucket (D8). Shape/line
    gate at ``tol_hard``; everything else at ``tol_soft``; text is INFORMATIONAL
    (x-delta only, never gates the overall pass/fail) -- kept as a cross-check against
    the identity compare, never the primary gate itself (D1).

    Returns ``{"pass": bool, "per_kind": {bucket: {n_a, n_b, pass, worst, reasons,
    informational?}}}``.
    """
    a_by_kind: dict[str, list[dict[str, Any]]] = {}
    b_by_kind: dict[str, list[dict[str, Any]]] = {}
    for u in a_units:
        a_by_kind.setdefault(unit_bucket(u), []).append(u)
    for u in b_units:
        b_by_kind.setdefault(unit_bucket(u), []).append(u)

    per_kind: dict[str, dict[str, Any]] = {}
    overall = True
    for bucket in sorted(set(a_by_kind) | set(b_by_kind)):
        a_list = sorted(a_by_kind.get(bucket, []), key=_sort_key)
        b_list = sorted(b_by_kind.get(bucket, []), key=_sort_key)
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
            per_kind[bucket] = entry
            overall = False
            continue
        x_only = bucket in _TEXT_BUCKETS
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
        if bucket in _TEXT_BUCKETS:
            entry["informational"] = True
        else:
            tol = tol_hard if bucket in _HARD_KINDS else tol_soft
            if worst > tol:
                entry["pass"] = False
                entry["reasons"].append(f"worst Δ{worst:.2f}px > {tol}px")
                overall = False
        per_kind[bucket] = entry
    return {"pass": overall, "per_kind": per_kind}


def _log_multiset_report(report: dict[str, Any]) -> None:
    for kind, entry in sorted(report["per_kind"].items()):
        if kind in _TEXT_BUCKETS:
            _log(
                f"    {kind:8} n_a={entry['n_a']:<4} n_b={entry['n_b']:<4} "
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


def compare_units_by_addr(
    a_units: list[dict[str, Any]],
    b_units: list[dict[str, Any]],
    tol_hard: float = TOL_HARD,
    tol_soft: float = TOL_SOFT,
) -> dict[str, Any]:
    """PERMUTATION diagnostic (D2, demoted): match A/B units by identical ``addr``
    (``write_gate_ab.slide_units``'s ``("top", kind, kindIndex)``, or a nested
    group-child chain) rather than sorted position. Only addresses present on BOTH sides
    are compared (a count mismatch is already caught by :func:`compare_units_multiset`);
    this pass exists to catch a same-population PERMUTATION neither the multiset nor the
    identity compare need to see — same boxes, different (kind, kindIndex) assignment.

    INFORMATIONAL EVERYWHERE (D2): identity matching (:func:`compare_units_identity`) is
    the primary gate now, immune to kindIndex reordering; this pass never gates the
    overall result (``"pass"`` is always ``True``) — run it only as a diagnostic when
    identity matching itself failed. Per-bucket ``"pass"``/``"reasons"`` are still
    computed so a large per-address delta is still visible in the log.

    Returns ``{"pass": True, "per_kind": {kind: {n, worst, pass, reasons,
    informational: True}}}``.
    """
    a_by_addr = {tuple(u["addr"]): u for u in a_units}
    b_by_addr = {tuple(u["addr"]): u for u in b_units}
    per_kind: dict[str, dict[str, Any]] = {}
    for addr in sorted(set(a_by_addr) & set(b_by_addr), key=str):
        ua, ub = a_by_addr[addr], b_by_addr[addr]
        kind = ua["kind"]
        entry = per_kind.setdefault(
            kind, {"n": 0, "worst": 0.0, "pass": True, "reasons": [], "informational": True}
        )
        ax, ay, aw, ah = _unit_box(ua)
        bx, by, bw, bh = _unit_box(ub)
        delta = (
            abs(ax - bx)
            if unit_bucket(ua) in _TEXT_BUCKETS
            else max(abs(ax - bx), abs(ay - by), abs(aw - bw), abs(ah - bh))
        )
        entry["n"] += 1
        entry["worst"] = max(entry["worst"], delta)
        tol = tol_hard if kind in _HARD_KINDS else tol_soft
        if delta > tol:
            entry["pass"] = False
            entry["reasons"].append(f"addr {addr} Δ{delta:.2f}px > {tol}px")
    unmatched = (set(a_by_addr) | set(b_by_addr)) - (set(a_by_addr) & set(b_by_addr))
    return {"pass": True, "per_kind": per_kind, "unmatched_addrs": len(unmatched)}


def _log_addr_report(report: dict[str, Any]) -> None:
    _log(f"  addr-matched pass ({report['unmatched_addrs']} addr(s) unmatched, skipped):")
    for kind, entry in sorted(report["per_kind"].items()):
        tag = "info" if entry.get("informational") else ("PASS" if entry["pass"] else "FAIL")
        _log(
            f"    {kind:8} n={entry['n']:<4} worst={entry['worst']:.2f}px  {tag}"
            + (f"  {entry['reasons']}" if entry.get("reasons") else "")
        )


# ==========================================================================
# compare_units_identity — the PRIMARY gate (D1).
# ==========================================================================
def _composite_id(unit: dict[str, Any]) -> str:
    """``"<id>|<kind>"`` — a text-bearing shape's ``duplicateOf`` twin shares ONE
    drawable id across TWO units (its text unit and its shape unit); matching by this
    composite instead of the raw id stops one twin's unit from cross-pairing with the
    OTHER twin's unit on the far side."""
    return f"{unit['id']}|{unit['kind']}"


def _duplicate_composite_ids(units: list[dict[str, Any]]) -> list[str]:
    """Composite ids (:func:`_composite_id`) that occur more than once in ``units`` --
    empty means every ``(id, kind)`` pair on this side is unique, as expected."""
    seen: set[str] = set()
    dupes: list[str] = []
    for u in units:
        cid = _composite_id(u)
        if cid in seen and cid not in dupes:
            dupes.append(cid)
        seen.add(cid)
    return dupes


def compare_units_identity(
    a_units: list[dict[str, Any]], b_units: list[dict[str, Any]], tols: Tolerances
) -> dict[str, Any]:
    """PRIMARY A/B gate (D1): match every unit by drawable IDENTITY, composite
    ``(id, kind)`` (:func:`_composite_id` — see the ``duplicateOf`` twin note),
    ``write_gate_ab.match_units`` doing the actual pairing/addr-fallback against
    COPIES keyed by the composite (results remapped back to the original units before
    return, so every id in the report is the real drawable id). A composite id
    repeated within ONE side is a caller bug (``slide_units`` should never emit two
    units with the same ``(id, kind)``) -- raises ``ValueError`` naming the duplicate
    rather than silently losing one of them to the ``{composite: unit}`` remap.

    Bucket by :func:`unit_bucket` (D8), gate EVERY bucket at :func:`tol_for_bucket`
    (D7, revised: doubled tolerances for the classes the plan oracle also validates
    per-side — see that function's docstring for the rationale). There is no
    informational demotion: every unit that fails ``write_gate_ab.compare_signature``
    (geometry beyond tolerance, OR a structural mismatch -- render-signature TYPE,
    ``flips``, or masked ``mask_angle`` -- which that comparator reports regardless of
    the delta) gates the overall result. Text-autosize shapes are carved out of BOTH
    sides first (``write_gate_ab.text_autosize_shapes`` — ``naturalSize`` re-derives on
    Keynote OPEN, so A and B legitimately differ there yet render identically).

    ``pass`` requires: ``id_rate == 1.0`` (every unit matched by id, none by addr
    fallback), no unmatched unit on either side, and every bucket within tolerance.
    Group order is never compared (D9) -- matching is by id, so a reordered group is
    still found and compared as itself.

    Returns ``{"pass": bool, "id_rate": float, "per_bucket": {bucket: {n, worst, pass,
    fails}}, "unmatched_a": [...], "unmatched_b": [...], "carved": [id, ...]}``.
    """
    # lazy: keep write_gate_ab (and its Keynote/iwa deps) out of this module's import path.
    from scripts.write_gate_ab import (  # noqa: PLC0415
        compare_signature,
        id_match_rate,
        match_units,
        text_autosize_shapes,
    )

    carve = {u["id"] for u in text_autosize_shapes(a_units)}
    carve |= {u["id"] for u in text_autosize_shapes(b_units)}
    a_units = [u for u in a_units if u["id"] not in carve]
    b_units = [u for u in b_units if u["id"] not in carve]

    a_keyed = [{**u, "id": _composite_id(u)} for u in a_units]
    b_keyed = [{**u, "id": _composite_id(u)} for u in b_units]
    a_orig_by_key = {k["id"]: o for o, k in zip(a_units, a_keyed)}
    b_orig_by_key = {k["id"]: o for o, k in zip(b_units, b_keyed)}
    if len(a_orig_by_key) != len(a_units):
        raise ValueError(
            f"compare_units_identity: duplicate (id, kind) on the A side: "
            f"{_duplicate_composite_ids(a_units)}"
        )
    if len(b_orig_by_key) != len(b_units):
        raise ValueError(
            f"compare_units_identity: duplicate (id, kind) on the B side: "
            f"{_duplicate_composite_ids(b_units)}"
        )

    keyed_pairs, unmatched_a_k, unmatched_b_k = match_units(a_keyed, b_keyed)
    rate = id_match_rate(keyed_pairs)
    pairs = [(a_orig_by_key[ka["id"]], b_orig_by_key[kb["id"]], how) for ka, kb, how in keyed_pairs]
    unmatched_a = [a_orig_by_key[k["id"]] for k in unmatched_a_k]
    unmatched_b = [b_orig_by_key[k["id"]] for k in unmatched_b_k]

    per_bucket: dict[str, dict[str, Any]] = {}
    for ua, ub, _how in pairs:
        bucket = unit_bucket(ua)
        entry = per_bucket.setdefault(bucket, {"n": 0, "worst": 0.0, "pass": True, "fails": []})
        tol = tol_for_bucket(bucket, ua["sig"].get("type"), tols)
        ok, worst, reasons = compare_signature(ua["sig"], ub["sig"], tol)
        entry["n"] += 1
        entry["worst"] = max(entry["worst"], worst)
        if not ok:
            entry["pass"] = False
            entry["fails"].append({"id": ua["id"], "addr": ua["addr"], "worst": worst,
                                   "reasons": reasons})
    for u in (*unmatched_a, *unmatched_b):
        bucket = unit_bucket(u)
        entry = per_bucket.setdefault(bucket, {"n": 0, "worst": 0.0, "pass": True, "fails": []})
        entry["pass"] = False
        entry["fails"].append({"id": u["id"], "addr": u["addr"], "worst": float("inf"),
                               "reasons": ["unmatched"]})

    overall = (
        rate == 1.0 and not unmatched_a and not unmatched_b
        and all(e["pass"] for e in per_bucket.values())
    )
    return {"pass": overall, "id_rate": rate, "per_bucket": per_bucket,
            "unmatched_a": unmatched_a, "unmatched_b": unmatched_b, "carved": sorted(carve)}


def _log_identity_report(report: dict[str, Any]) -> None:
    _log(
        f"    identity id_rate={report['id_rate']:.1%} "
        f"unmatched_a={len(report['unmatched_a'])} unmatched_b={len(report['unmatched_b'])}"
    )
    for bucket, entry in sorted(report["per_bucket"].items()):
        tag = "PASS" if entry["pass"] else "FAIL"
        _log(f"      {bucket:14} n={entry['n']:<4} worst={entry['worst']:.2f}px  {tag}")
        for f in entry["fails"][:8]:
            _log(f"        {f['addr']} worst={f['worst']:.2f} {f['reasons']}")
        if len(entry["fails"]) > 8:
            _log(f"        (+{len(entry['fails']) - 8} more)")
    if report["carved"]:
        _log(f"      autosize carve-out: {len(report['carved'])} shape(s) excluded")


# ==========================================================================
# plan_oracle_slide — the plan-as-oracle compare (D3).
# ==========================================================================
def plan_oracle_slide(
    specs: list[dict[str, Any]],
    id_by_addr: dict[tuple[str, int], str],
    recs_by_id: dict[str, dict[str, Any]],
    tols: Tolerances,
) -> dict[str, Any]:
    """Compare every planned transform's target against the drawable it resolves to,
    id-addressed via the SOURCE deck's kind index (D3) -- raise-immune, hide-immune
    (stat-finalize needs no exclusion).

    Covers the SAME exact classes as ``offline_write.verify_offline_frames`` (shape/
    line at ``tols.hard``, unmasked image/movie -- the resolved record's ``geom_source
    == "iwa"`` -- at ``tols.soft``) PLUS ``group`` (its union x/y/w/h vs the composed
    group-union record, also at ``tols.soft`` -- a group's union IS offline-recoverable,
    unlike its children's live layout). Text (autosize ``y``/``w``/``h`` are not
    offline-recoverable) is NOT exactly recoverable from raw IWA and would spuriously
    RED a text-heavy deck, so it is skipped here and left entirely to the A-vs-B
    identity compare instead. A masked image/movie (``geom_source == "mask"``) is
    skipped too -- its crop is covered by the identity compare at ``tols.mask``. Every
    skip increments ``skipped``.

    ``role == "hide"`` specs are skipped (nothing to compare — the object is deleted).
    Any other non-hide, non-skipped spec whose id fails to resolve, or is missing from
    the deck being checked, is a RED ``missing_ids`` entry. Uses
    ``offline_write._spec_box`` for the (planned, actual) tuples — same comparator
    ``verify_offline_frames`` uses (lines compare POSITION only, never length/width).

    A spec with no ``kindIndex`` at all (should never happen -- ``ItemTransform.as_dict``
    always emits one) is a RED ``missing_ids`` entry too, reason ``"spec carries no
    kindIndex"`` — never silently dropped.

    Returns ``{"pass": bool, "per_kind": {kind: {n, worst, pass, fails}}, "missing_ids":
    [...], "skipped": int, "compared": int}`` where ``compared`` is the total number of
    specs actually compared (``sum`` of every ``per_kind[kind]["n"]``) — 0 alongside a
    non-zero ``skipped`` is a VACUOUS pass (every spec on the slide was an inexact class)
    the caller should call out, not treat as a clean result.
    """
    from obed_edom.offline_write import (  # noqa: PLC0415 — lazy, see module docstring
        _OFFLINE_EXACT_KINDS,
        _OFFLINE_MEDIA_KINDS,
        _spec_box,
    )

    oracle_kinds = _OFFLINE_EXACT_KINDS | _OFFLINE_MEDIA_KINDS | {"group"}
    per_kind: dict[str, dict[str, Any]] = {}
    missing_ids: list[dict[str, Any]] = []
    skipped = 0
    for spec in specs:
        if spec.get("role") == "hide":
            continue
        kind = str(spec.get("kind") or "")
        if kind not in oracle_kinds:
            skipped += 1
            continue
        kind_index = spec.get("kindIndex")
        if kind_index is None:
            missing_ids.append({"kind": kind, "reason": "spec carries no kindIndex"})
            continue
        addr = (kind, int(kind_index))
        obj_id = id_by_addr.get(addr)
        if obj_id is None:
            missing_ids.append({"addr": addr, "reason": "not in source kind index"})
            continue
        rec = recs_by_id.get(obj_id)
        if rec is None:
            missing_ids.append({"addr": addr, "id": obj_id, "reason": "missing from output deck"})
            continue
        if kind in _OFFLINE_MEDIA_KINDS and rec.get("geom_source") != "iwa":
            skipped += 1
            continue
        entry = per_kind.setdefault(kind, {"n": 0, "worst": 0.0, "pass": True, "fails": []})
        tol = tols.hard if kind in _OFFLINE_EXACT_KINDS else tols.soft
        planned, actual = _spec_box(spec, rec)
        worst = max(abs(a - b) for a, b in zip(planned, actual))
        entry["n"] += 1
        entry["worst"] = max(entry["worst"], worst)
        if worst > tol:
            entry["pass"] = False
            entry["fails"].append({"addr": addr, "id": obj_id, "worst": worst})
    overall = not missing_ids and all(e["pass"] for e in per_kind.values())
    compared = sum(e["n"] for e in per_kind.values())
    return {"pass": overall, "per_kind": per_kind, "missing_ids": missing_ids,
            "skipped": skipped, "compared": compared}


def _log_plan_oracle_report(label: str, report: dict[str, Any]) -> None:
    tag = "PASS" if report["pass"] else "FAIL"
    _log(f"    plan-oracle {label}: {tag} ({report['skipped']} non-exact-class spec(s) skipped)")
    for kind, entry in sorted(report["per_kind"].items()):
        status = "PASS" if entry["pass"] else "FAIL"
        _log(f"      {kind:8} n={entry['n']:<4} worst={entry['worst']:.2f}px  {status}")
    if report["missing_ids"]:
        _log(f"      missing_ids: {report['missing_ids']}")


# ==========================================================================
# summary_gate_reasons — run B's offlineWrite self-report.
# ==========================================================================
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


# ==========================================================================
# Run records (D13) — persist + reload a run Keynote-free.
# ==========================================================================
def _git_head(repo: Path | None = None) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True, check=False)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def run_record(
    *, commit: str, deck_digest: str, source_digest: str, plan: dict[str, Any],
    child_resize: Any, applied: int, missed: int, offline_write: dict[str, Any] | None,
    spec_id_map: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Everything a later ``--reuse-a``/``--reuse-b`` needs, with no Keynote (D13).

    ``offline_write`` is stored MINUS its ``specs`` key (the full per-slide spec dicts
    are already in ``plan["transforms"]``; duplicating them bloats the record).

    ``expectRaises`` (D4's ``front >= 1`` bar) is computed HERE, once, from the FULL
    ``plan`` a fresh run hands in (remap_keynote.py's ``plan_out`` block carries
    ``statJobs``/``badgeRaises`` job lists) and persisted alongside the trimmed plan, so
    a later ``--reuse-a``/``--reuse-b`` reads it back exactly rather than re-deriving it
    from a plan already trimmed down to D13's three keys.

    Raises ``ValueError`` if ``plan`` has NEITHER key: that means ``plan`` is already a
    trimmed, PERSISTED plan (a loaded run record's ``plan``, not a fresh ``plan_out``) —
    computing ``expectRaises`` from it would silently read as "no jobs" instead of
    failing loudly on the caller's mistake.
    """
    if "statJobs" not in plan and "badgeRaises" not in plan:
        raise ValueError(
            "run_record: plan carries neither 'statJobs' nor 'badgeRaises' — this looks "
            "like an already-trimmed persisted plan, not a fresh plan_out dict; "
            "expectRaises cannot be derived from it."
        )
    ow = dict(offline_write or {})
    ow.pop("specs", None)
    return {
        "gateVersion": GATE_VERSION,
        "commit": commit,
        "deckDigest": deck_digest,
        "sourceDigest": source_digest,
        "plan": {
            "transforms": plan.get("transforms") or [],
            "reuses": plan.get("reuses") or [],
            "suppressGeometry": plan.get("suppressGeometry"),
        },
        "expectRaises": bool(plan.get("statJobs")) or bool(plan.get("badgeRaises")),
        "childResize": child_resize,
        "applied": applied,
        "missed": missed,
        "offlineWrite": ow,
        "specIdMap": spec_id_map,
    }


def write_run_record(path: Path | str, record: dict[str, Any]) -> Path:
    """Write ``record`` as JSON, then reload it and assert byte-for-byte equality
    (D13's reload-and-diff self-check) before returning."""
    path = Path(path)
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    reloaded = json.loads(path.read_text())
    if reloaded != record:
        raise RuntimeError(f"run record round-trip mismatch: {path}")
    return path


def load_run_record(path: Path | str, *, deck: Path | str, source: Path | str,
                    gate_version: int = GATE_VERSION) -> dict[str, Any]:
    """Load + validate a run record against the CURRENT gate version and both the
    deck's and the SOURCE wall's OWN digest — refuses (``ValueError``) a stale record
    rather than trusting it.

    A ``commit`` drift is only WARNED, never refused: the deck/source digests are the
    real staleness signal (a docs-only or comment-only commit changes HEAD without
    changing anything this gate reads).
    """
    record = json.loads(Path(path).read_text())
    if int(record.get("gateVersion", -1)) != int(gate_version):
        raise ValueError(
            f"{path}: gateVersion {record.get('gateVersion')} != {gate_version} (stale run record)"
        )
    from obed_edom.baseline import deck_digest  # noqa: PLC0415

    digest = deck_digest(Path(deck))
    if record.get("deckDigest") != digest:
        raise ValueError(f"{path}: deck digest mismatch for {deck} (stale run record)")
    source_digest = deck_digest(Path(source))
    if record.get("sourceDigest") != source_digest:
        raise ValueError(f"{path}: source digest mismatch for {source} (stale run record)")
    head = _git_head()
    if head and record.get("commit") != head:
        _log(f"WARN: {path}: commit {record.get('commit')!r} != HEAD {head!r} "
             "(deck/source digests still match; proceeding).")
    return record


def _run_record_path(deck: Path | str) -> Path:
    return Path(deck).with_suffix(".run.json")


# ==========================================================================
# Deck decode (thin) — spec_id_map (D3) + decode_deck (once per deck).
# ==========================================================================
def spec_id_map(source_deck: Path | str) -> dict[str, list[dict[str, Any]]]:
    """``{"<slide 1-based>": [{"kind", "kindIndex", "id"}, ...]}`` resolved from the
    SOURCE deck's own kind index (D3) — the addressing every planned transform spec
    uses. Slide keys are STRINGS (not int) so the run record round-trips through JSON
    byte-for-byte (D13's reload-and-diff self-check)."""
    from obed_edom.iwa_kindindex import derive_deck_kind_index  # noqa: PLC0415

    idx = derive_deck_kind_index(source_deck)
    return {
        str(i + 1): [{"kind": r["kind"], "kindIndex": r["kindIndex"], "id": r["id"]}
                    for r in records]
        for i, records in idx.items()
    }


def _id_by_addr_for_slide(id_map: dict[str, list[dict[str, Any]]], slide: int
                          ) -> dict[tuple[str, int], str]:
    return {(e["kind"], int(e["kindIndex"])): e["id"] for e in id_map.get(str(slide), [])}


def decode_deck(deck: Path | str) -> tuple[dict[str, dict], dict[int, dict[str, dict]]]:
    """Decode a deck ONCE: ``(objects, {slide (1-based): {id: composed record}})``.
    ``objects`` feeds ``write_gate_ab.slide_units``; the per-slide id map feeds
    :func:`plan_oracle_slide`."""
    from obed_edom.iwa_geometry import compose_geometry  # noqa: PLC0415
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415

    objects, _id_to_file, _file_ids = _load_deck(deck)
    order = slide_order(objects)
    by_slide: dict[int, dict[str, dict]] = {}
    for i, (slide_id, _skipped) in enumerate(order):
        if slide_id not in objects:
            continue
        recs = compose_geometry(objects[slide_id], objects)
        by_slide[i + 1] = {r["id"]: r for r in recs}
    return objects, by_slide


# ==========================================================================
# main — the Keynote-touching orchestration.
# ==========================================================================
def main(argv: list[str] | None = None) -> int:
    # Imported here so the pure comparators above import without Keynote/iwa deps present.
    from obed_edom import offline_write  # noqa: PLC0415
    from obed_edom.baseline import deck_digest  # noqa: PLC0415
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
        "--mode", choices=("verify", "on"), default="verify",
        help="run B's OBED_OFFLINE_WRITE (default verify: patch + live verify)",
    )
    ap.add_argument("--reuse-a", type=Path,
                    help="banked A .key (with its <deck>.run.json) — SKIP running A")
    ap.add_argument("--reuse-b", type=Path,
                    help="banked B .key (with its <deck>.run.json) — SKIP running B")
    ap.add_argument("--validate", dest="validate", action="store_true", default=True,
                    help="live-verify readback after each run (default on)")
    ap.add_argument("--no-validate", dest="validate", action="store_false",
                    help="skip the live-verify readback (required for the Full deck)")
    ap.add_argument("--tol-hard", type=float, default=TOL_HARD,
                    help=f"shape/line px tolerance vs the PLAN (oracle, per side); "
                         f"identity (A-vs-B) gates at 2x this (default {TOL_HARD})")
    ap.add_argument("--tol-soft", type=float, default=TOL_SOFT,
                    help=f"group/unmasked-image/movie px tolerance vs the PLAN (oracle, "
                         f"per side); identity (A-vs-B) gates at 2x this (default {TOL_SOFT})")
    ap.add_argument("--tol-mask", type=float, default=TOL_MASK,
                    help=f"masked image/movie crop px tolerance, A-vs-B (default {TOL_MASK})")
    ap.add_argument("--tol-text", type=float, default=TOL_TEXT,
                    help=f"text px tolerance (autosize x-only), A-vs-B (default {TOL_TEXT})")
    ap.add_argument("--tol-child", type=float, default=TOL_CHILD,
                    help=f"group-child px tolerance, A-vs-B (default {TOL_CHILD})")
    ap.add_argument(
        "--pass2-bar", choices=("strict", "parity"), default="strict",
        help="strict (default): every PASS2_ZERO_KEYS/frontErr/front A-vs-B parity is "
             "HARD. parity: tolerate a pre-existing pass-2 problem that is IDENTICAL on "
             "A and B (WARN, never abort/RED) so an unrelated deck defect doesn't block "
             "the write-equivalence question.",
    )
    ap.add_argument(
        "--no-quit-between-runs", dest="quit_between_runs", action="store_false", default=True,
        help="skip quitting Keynote after each fresh run (default: quit + wait so the "
             "next run starts on a fresh process -- Keynote can go unresponsive shortly "
             "after closing a large deck)",
    )
    args = ap.parse_args(argv)

    for label, deck in (("source", args.source), ("template", args.template)):
        if not deck.exists():
            ap.error(f"{label} deck not found: {deck}")

    tols = Tolerances(args.tol_hard, args.tol_soft, args.tol_mask, args.tol_text, args.tol_child)

    slide_range = None
    if args.slides:
        lo, _, hi = args.slides.partition("-")
        slide_range = (int(lo), int(hi or lo))

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    a_deck = args.reuse_a if args.reuse_a is not None else out / "A_unflagged.key"
    b_deck = args.reuse_b if args.reuse_b is not None else out / "B_flagged.key"

    ok, detail = accessibility_ok()
    if not ok:
        _log(f"ABORT: Accessibility is not enabled for this host ({detail}). Enable it under "
             "System Settings › Privacy & Security › Accessibility (z-order raises silently "
             "no-op without it).")
        return 4

    open_docs = keynote_open_documents()
    if open_docs:
        _log(f"ABORT: Keynote already has {len(open_docs)} document(s) open: {open_docs}. "
             "A prior run's swallowed close (or an unrelated open deck) can wedge this run "
             "or force the two-tier read to fall back into the legacy per-object inspect "
             "(the Full-deck-gate memory blowup this guards against). Close them in Keynote "
             "and re-run.")
        return 5

    commit = _git_head()

    # ================================ run/reuse A =================================
    if args.reuse_a is not None:
        if not a_deck.exists():
            ap.error(f"--reuse-a not found: {a_deck}")
        try:
            a_record = load_run_record(_run_record_path(a_deck), deck=a_deck, source=args.source)
        except ValueError as exc:
            _log(f"ABORT: {exc}")
            return 2
        plan_a = a_record["plan"]
        child_resize_a = a_record["childResize"]
        applied_a = int(a_record["applied"] or 0)
        expect_raises_a = bool(a_record["expectRaises"])
        id_map = a_record["specIdMap"]
        _log(f"REUSE A: {a_deck} (run record OK).")
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
    else:
        _log(f"A: production remap {args.source.name} (OBED_OFFLINE_WRITE=off) -> {a_deck}")
        _remap_env(suppress="", as_geometry="1", geom_props="1")
        os.environ["OBED_OFFLINE_WRITE"] = "off"  # explicit: never rely on the ambient default
        plan_a: dict[str, Any] = {}
        info_a = remap_and_inspect(
            args.source, a_deck, template=args.template, slide_range=slide_range,
            export_dir=None, plan_out=plan_a, log=_log, validate=args.validate,
        )
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
        child_resize_a = info_a.get("childResize")
        applied_a = int(info_a.get("applied") or 0)
        id_map = spec_id_map(args.source)
        a_record = run_record(
            commit=commit, deck_digest=deck_digest(a_deck), source_digest=deck_digest(args.source),
            plan=plan_a, child_resize=child_resize_a, applied=applied_a,
            missed=int(info_a.get("missed") or 0), offline_write=info_a.get("offlineWrite"),
            spec_id_map=id_map,
        )
        expect_raises_a = bool(a_record["expectRaises"])
        write_run_record(_run_record_path(a_deck), a_record)
        _log(f"Run record written -> {_run_record_path(a_deck)}")
        _warn_and_close_stray_documents("A", a_deck)
        if args.quit_between_runs:
            quit_ok, elapsed = quit_keynote_and_wait()
            if quit_ok:
                _log(f"Keynote quit between runs ({elapsed:.0f} s)")
            else:
                _log(f"WARN: Keynote still running after {elapsed:.0f} s")

    zero_keys_hard = args.pass2_bar == "strict"
    reasons_a = pass2_health(child_resize_a, label="A", expect_raises=expect_raises_a,
                             zero_keys_hard=zero_keys_hard)
    for r in reasons_a:
        _log(f"RED: {r}")
    if reasons_a:
        _log("ABORT: run A pass-2 (stat-finalize) is UNHEALTHY — see RED lines above. B never ran.")
        return 3
    _log("A pass-2 health: OK.")

    # `compared_slides` depends only on A's plan (transforms/reuses) — compute it once,
    # before B runs, so B's own suppressGeometry can be checked against it (D5/D1) and
    # the per-slide loop below does not recompute it.
    reuses = plan_a.get("reuses") or []
    reuse_slides = {int(r["slide"]) for r in reuses}
    wanted = slides_for_plan(slide_range)
    compared_slides = sorted(
        offline_write._offline_write_slides(plan_a.get("transforms") or [], reuses, reuse_slides, wanted)
    )

    # ================================ run/reuse B =================================
    if args.reuse_b is not None:
        if not b_deck.exists():
            ap.error(f"--reuse-b not found: {b_deck}")
        try:
            b_record = load_run_record(_run_record_path(b_deck), deck=b_deck, source=args.source)
        except ValueError as exc:
            _log(f"ABORT: {exc}")
            return 2
        plan_b = b_record["plan"]
        child_resize_b = b_record["childResize"]
        applied_b = int(b_record["applied"] or 0)
        expect_raises_b = bool(b_record["expectRaises"])
        ow_b = b_record["offlineWrite"] or {}
        _log(f"REUSE B: {b_deck} (run record OK).")
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
    else:
        _log(f"B: same plan, OBED_OFFLINE_WRITE={args.mode} -> {b_deck}")
        _remap_env(suppress="", as_geometry="1", geom_props="1")
        os.environ["OBED_OFFLINE_WRITE"] = args.mode
        plan_b: dict[str, Any] = {}
        try:
            info_b = remap_and_inspect(
                args.source, b_deck, template=args.template, slide_range=slide_range,
                export_dir=None, plan_out=plan_b, log=_log, validate=args.validate,
            )
        finally:
            os.environ.pop("OBED_OFFLINE_WRITE", None)
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
        child_resize_b = info_b.get("childResize")
        applied_b = int(info_b.get("applied") or 0)
        ow_b = info_b.get("offlineWrite") or {}
        b_record = run_record(
            commit=commit, deck_digest=deck_digest(b_deck), source_digest=deck_digest(args.source),
            plan=plan_b, child_resize=child_resize_b, applied=applied_b,
            missed=int(info_b.get("missed") or 0), offline_write=ow_b, spec_id_map=id_map,
        )
        expect_raises_b = bool(b_record["expectRaises"])
        write_run_record(_run_record_path(b_deck), b_record)
        _log(f"Run record written -> {_run_record_path(b_deck)}")
        _warn_and_close_stray_documents("B", b_deck)
        if args.quit_between_runs:
            quit_ok, elapsed = quit_keynote_and_wait()
            if quit_ok:
                _log(f"Keynote quit between runs ({elapsed:.0f} s)")
            else:
                _log(f"WARN: Keynote still running after {elapsed:.0f} s")

    if not (ow_b.get("slides") or []):
        _log("ABORT: run B took no slide offline (OBED_AS_GEOMETRY off, or no slide "
             "qualified — check the log above).")
        return 2

    _log(
        f"B offline-write summary: {len(ow_b.get('slides') or [])} slide(s) offline, "
        f"refused={ow_b.get('refused') or []}, missedSpecs={ow_b.get('missedSpecs') or 0}, "
        f"softFallbacks={ow_b.get('softFallbacks') or 0}, valueClean={ow_b.get('valueClean', True)}, "
        f"offlineVerifyPass={ow_b.get('offlineVerifyPass')}, liveVerifyPass={ow_b.get('liveVerifyPass')}, "
        f"applied={ow_b.get('applied')}."
    )

    reasons_b = pass2_health(child_resize_b, label="B", expect_raises=expect_raises_b,
                             zero_keys_hard=zero_keys_hard)
    for r in reasons_b:
        _log(f"RED: {r}")

    for label, result in (("A", child_resize_a), ("B", child_resize_b)):
        if not result:
            continue
        warns = [f"{key}={result.get(key)}" for key in PASS2_WARN_KEYS if int(result.get(key) or 0)]
        if warns:
            _log(f"WARN {label}: {', '.join(warns)} (non-zero fallback; investigate, does not gate).")

    if not zero_keys_hard:
        for label, result in (("A", child_resize_a), ("B", child_resize_b)):
            if not result:
                continue
            zero_warns = [f"{key}={result.get(key)}" for key in PASS2_ZERO_KEYS if int(result.get(key) or 0)]
            if zero_warns:
                _log(f"WARN {label}: {', '.join(zero_warns)} "
                     "(pass2-bar=parity: tolerated because A==B, does not gate).")
            front_err = front_err_from_raw((result.get("raw") or ""))
            if front_err and not any(code in front_err for code in _ACCESSIBILITY_ERR_CODES):
                _log(f"WARN {label}: frontErr={front_err!r} "
                     "(pass2-bar=parity: no Accessibility code, does not gate).")

    drift = plan_parity(plan_a, plan_b, compared_slides)
    for r in drift:
        _log(f"RED: {r}")

    parity = pass2_parity(child_resize_a, child_resize_b, front_hard=zero_keys_hard)
    for r in parity:
        _log(f"RED: {r}")

    if not zero_keys_hard:
        front_a = int((child_resize_a or {}).get("front") or 0)
        front_b = int((child_resize_b or {}).get("front") or 0)
        if front_a != front_b:
            _log(f"WARN: pass-2 front A={front_a} B={front_b} "
                 "(pass2-bar=parity: GUI Bring-to-Front raises are flaky, does not gate).")

    summary_reasons = summary_gate_reasons(ow_b, applied_a, applied_b)
    for r in summary_reasons:
        _log(f"RED: {r}")

    gate_ok = not (reasons_b or drift or parity or summary_reasons)

    # ============================ per-slide compare =================================
    # Decode A, extract every compared slide's units, then DROP A's raw archive map
    # before decoding B — two whole-deck decodes held live at once is the dominant
    # memory cost on the Full deck.
    a_objects, a_by_slide = decode_deck(a_deck)
    a_units_by_slide = {n: slide_units(a_objects, n) for n in compared_slides}
    del a_objects

    b_objects, b_by_slide = decode_deck(b_deck)

    _log(
        f"Comparing {len(compared_slides)} planned non-reuse, non-donor slide(s): "
        f"{compared_slides} (reuse-target and donor slides are NOT covered by this gate)."
    )

    vacuous_slides: list[int] = []
    for n in compared_slides:
        specs_n = [t for t in (plan_a.get("transforms") or []) if int(t.get("slide", -1)) == n]
        id_by_addr = _id_by_addr_for_slide(id_map, n)

        oracle_a = plan_oracle_slide(specs_n, id_by_addr, a_by_slide.get(n, {}), tols)
        oracle_b = plan_oracle_slide(specs_n, id_by_addr, b_by_slide.get(n, {}), tols)
        _log(f"  slide {n}:")
        _log_plan_oracle_report("A", oracle_a)
        _log_plan_oracle_report("B", oracle_b)
        if not (oracle_a["pass"] and oracle_b["pass"]):
            gate_ok = False
        if any(r["compared"] == 0 and r["skipped"] > 0 for r in (oracle_a, oracle_b)):
            vacuous_slides.append(n)
            _log(f"  slide {n}: WARN plan-oracle VACUOUS PASS — every planned spec on this "
                 "slide is a non-exact class (text/group/masked); 0 compared, PASS proves nothing.")

        a_units = a_units_by_slide[n]
        b_units = slide_units(b_objects, n)

        try:
            identity = compare_units_identity(a_units, b_units, tols)
        except ValueError as exc:
            _log(f"RED: slide {n}: {exc}")
            gate_ok = False
            continue
        _log_identity_report(identity)
        if not identity["pass"]:
            gate_ok = False
            _log("    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            _log(f"    !! slide {n}: IDENTITY COMPARE FAILED (id_rate={identity['id_rate']:.1%}) —")
            _log("    !! the multiset/addr diagnostics below for this slide are UNTRUSTED.")
            _log("    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        multiset = compare_units_multiset(a_units, b_units, args.tol_hard, args.tol_soft)
        _log_multiset_report(multiset)  # informational cross-check only (D2)

        if not identity["pass"]:
            _log(f"  slide {n}: identity compare FAILED — running the addr-matched permutation "
                 "diagnostic:")
            addr_report = compare_units_by_addr(a_units, b_units, args.tol_hard, args.tol_soft)
            _log_addr_report(addr_report)

    if vacuous_slides:
        _log(f"NOTE: plan-oracle VACUOUS PASS on slide(s) {vacuous_slides} — 0 specs compared "
             "(every planned spec was a non-exact class); those slides' oracle result rests "
             "entirely on the identity compare above, not this oracle.")
    if zero_keys_hard:
        _log("pass-2 bar: strict")
    else:
        unresolved_n = int((child_resize_a or {}).get("unresolved") or 0)
        dedup_m = int((child_resize_a or {}).get("dedupShortfall") or 0)
        _log(f"pass-2 bar: parity (unresolved={unresolved_n}, dedupShortfall={dedup_m} "
             "tolerated because A==B)")
    _log("OFFLINE-WRITE GATE: GREEN" if gate_ok else "OFFLINE-WRITE GATE: RED (see above)")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
