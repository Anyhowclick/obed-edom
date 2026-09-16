#!/usr/bin/env python3
"""Whole-deck A/B gate for the offline geometry-WRITE opt-in (``w-offline-write-optin``)
and the W2 z-order write (``w-zorder-patch`` piece 4).

Runs :func:`obed_edom.remap_keynote.remap_and_inspect` TWICE against the same
source/template pair:

    A = ``OBED_ZORDER_WRITE=off`` — no z-order write at all: pass 2 raises nothing,
        every raise-bearing slide is reported un-raised (``zorderGui``). A measures
        the deck's PRE-RAISE order, never the ambient z-order default.
    B = ``OBED_ZORDER_WRITE=on``, **the same** ``OBED_OFFLINE_WRITE`` mode as A
        (offline z-order patch on every eligible slide; nothing left for a GUI
        raise to do).

Both arms share ``--mode`` so the A/B delta is the z-order writer, not a second
geometry-writer variable. W1's older split (A ``OBED_OFFLINE_WRITE=off``, B
``--mode``) is no longer this script's arm configuration.

Per-slide z-order verdicts reuse ``output/bank/2026-09-11/badge-retry/zorder_compare.py``'s
method (full ``drawablesZOrder`` id-list equality) in two forms:

    SAME_ORDER      — full id-list equality. The RAISE10 A-vs-A control uses this
                      metric via ``--control-a`` (a second same-code A deck) and
                      DOES gate there. A-vs-B SAME_ORDER is OBSERVATIONAL ONLY,
                      by design: A is unraised and B is patched, so the two orders
                      are expected to differ everywhere. A ``SAME_ORDER(A-vs-B)=no``
                      line is not a regression signal — do not read it as one.
    FRONT_BLOCK_OK  — target ids occupy the final ``|T|`` slots in the same order
                      in both arms. This is the real A-vs-B gate line.

RAISE10-vs-Gold control caveat (plan C8): on RAISE10 a same-code A-vs-A control
**is** valid (six banked runs ``SAME_ORDER=yes`` on 7/7 ordinals,
``output/bank/2026-09-11/badge-retry/results.md``) and must be run as a control.
On Gold it is not — Keynote scrambles ``drawablesZOrder`` on save — and only
same-run A-vs-B ``FRONT_BLOCK_OK`` is meaningful there. Do not generalise the
Gold caveat to RAISE10, and do not treat a Gold ``SAME_ORDER(A-vs-B)=no`` as a
W2 fail — on Gold it is expected on every slide, control or not.

Piece 3 emits ``OBED_ZORDER_WRITE`` and the ``Stat zorder detail:`` counters
(``zorderSlides``, ``zorderStatRaised``, ``zorderBadgeRaised``, ``zorderNoop``,
``zorderUnresolved(s=,k=,i=)``, ``zorderRefused(s=,reason=)``, ``zorderGui``,
``zorderLost(s=,id=)``; no token may contain the literal `` exported=``). This
gate surfaces those counters and REDs arm B when the piece-3
``zorderWrite`` schema is missing (absent counters are not read as 0), when
``zorderRefused`` / ``zorderUnresolved`` / ``zorderLost`` are non-zero, or when
``slides`` / ``zorderGui`` are not exactly the eligible vs reuse/ineligible
raise-bearing sets. Pass 2 (stat-finalize) never raises any more — there is no
GUI raise health to check on either arm.

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
shape/line, unmasked image/movie, and group (its composed union, measured at 0.46px
median / 1.92px max over 240 comparable specs on a Keynote-written reference deck).
Records the reader itself flags approximate (`needs_keynote` set, e.g.
`rotated-group`/`group-residual`) are NOT comparable and are counted in `skipped` and
listed in `approx`, which is reported but never gates. Text (autosize geometry) is NOT
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

Health gates run BEFORE any geometry compare: a Keynote-open-documents pre-flight
(:func:`keynote_open_documents` -- ABORTS if anything is already open; a stray document
left by a swallowed close is what made a real run inherit the previous run's B_flagged
and blow memory on the two-tier read), pass-2 (stat-finalize) health on run A --
aborting before B ever starts -- then a card-border damage check (:func:`card_border_refs`
+ :func:`card_border_damage_reasons`): an arm whose card-border media-style ref count falls
below ``CARD_REF_FLOOR`` of the SOURCE deck's has LOST card images and hard-fails. The ref
count is the OBSERVATION only and attributes no cause -- D1 read the 2026-09-07 shortfall as
a stolen GUI interaction and D6 disproved that (a second run on an untouched machine
reproduced the same 43 refs and character-identical stat-finalize integers; the real cause
was the load-sensitive ``applyReuse`` paste no-op fixed in ``f76e8d3``), so the RED line
names that mechanism as the known mechanism (D6) with where to check it, and points at
diagnosis, never at a re-run first. A's check ABORTS before B ever starts (exit 6); B's
check cannot abort B (already paid for) but folds into ``gate_ok`` so a
damaged B can no longer report GREEN. Then A/B pass-2 parity and plan parity. Each fresh
run (A and B) is followed by the SAME open-documents check, WARNing loudly and closing
only that run's own deck if Keynote left it open (never anyone else's). Plan parity
checks ``transforms``/``reuses`` for exact equality, but NOT ``suppressGeometry`` as an
A==B equality: W1 constructed A empty and B as the compared-slide set; W2 puts both
arms on the same offline-write mode, so A may also equal that set. B must still equal
the compared-slide set exactly. :func:`compare_units_multiset`
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
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple

# `python scripts/x.py` puts scripts/ (not the repo root) on sys.path[0].
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GATE_VERSION = 3
COMPATIBLE_GATE_VERSIONS = {2, GATE_VERSION}

TOL_HARD = 0.5
TOL_SOFT = 1.0
TOL_MASK = 2.0
TOL_TEXT = 2.0
TOL_CHILD = 2.0
TOL_ASPECT = 0.25

_HARD_KINDS = {"shape", "line"}
_ASPECT_LOCKED = {"group", "image", "movie"}
_TEXT_BUCKETS = {"text"}  # "child:text" is unreachable: `_child_kind` never yields "text"

# D4 pass-2 (stat-finalize) health, from `keynote._run_stat_finalize`'s result dict.
PASS2_ZERO_KEYS = ("unresolved", "dedupShortfall")
PASS2_PARITY_KEYS = (
    "jobs", "done", "skipped", "sized", "sizeSkips", "dedupDeleted",
    "dedupShortfall", "sigFallback", "unresolved",
)
PASS2_WARN_KEYS = ("sigFallback",)

# Piece 3 result-dict counters that must be 0 on arm B (lists or ints).
ZORDER_ZERO_KEYS = ("zorderRefused", "zorderUnresolved", "zorderLost")
# Required on arm B when OBED_ZORDER_WRITE=on — missing is not "zero".
ZORDER_SCHEMA_KEYS = (
    "slides", "zorderSlides",
    "zorderStatRaised", "zorderBadgeRaised", "zorderNoop",
    "zorderRefused", "zorderUnresolved", "zorderLost", "zorderGui",
)
ZORDER_SURFACE_KEYS = (
    "zorderSlides", "zorderStatRaised", "zorderBadgeRaised", "zorderNoop",
    "zorderRefused", "zorderUnresolved", "zorderLost", "zorderGui",
)
class Tolerances(NamedTuple):
    hard: float = TOL_HARD
    soft: float = TOL_SOFT
    mask: float = TOL_MASK
    text: float = TOL_TEXT
    child: float = TOL_CHILD


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================================================
# Pre-flight + pass-2 health (D5) — pure, unit-tested via monkeypatched subprocess.
# ==========================================================================
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


def pass2_health(result: dict[str, Any] | None, *, label: str,
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
    :func:`pass2_parity`). ``ok`` and ``done+skipped==jobs`` stay HARD in both modes.
    Pass 2 never raises any more (W2 piece 1) — there is no ``front``/``frontErr``
    to check here.
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
    jobs = int(result.get("jobs") or 0)
    done = int(result.get("done") or 0)
    skipped = int(result.get("skipped") or 0)
    if done + skipped != jobs:
        reasons.append(f"{label}: done({done})+skipped({skipped}) != jobs({jobs})")
    return reasons


def pass2_parity(a: dict[str, Any] | None, b: dict[str, Any] | None) -> list[str]:
    """A/B parity on ``PASS2_PARITY_KEYS`` — ``raw`` is deliberately ignored.

    Every key (``jobs``/``done``/``skipped``/``sized``/``sizeSkips``/``dedupDeleted``/
    ``dedupShortfall``/``sigFallback``/``unresolved``) stays HARD in every mode. Pass 2
    never raises any more (W2 piece 1) — there is no ``front``/``badgeFallback`` key to
    exempt from parity.
    """
    a = a or {}
    b = b or {}
    reasons: list[str] = []
    for key in PASS2_PARITY_KEYS:
        va = int(a.get(key) or 0)
        vb = int(b.get(key) or 0)
        if va != vb:
            reasons.append(f"pass-2 {key}: A={va} != B={vb}")
    return reasons


def pass2_bar_line(*, zero_keys_hard: bool, parity: list[str],
                   a: dict[str, Any] | None, b: dict[str, Any] | None) -> str:
    """The `pass-2 bar:` summary line. "tolerated because A==B" is claimed ONLY when
    `parity` (the actual A-vs-B diff) came back empty -- the banked 2026-09-07 run
    printed that tolerance directly under seven `A != B` lines."""
    if zero_keys_hard:
        return "pass-2 bar: strict"
    ua, ub = int((a or {}).get("unresolved") or 0), int((b or {}).get("unresolved") or 0)
    da, db = int((a or {}).get("dedupShortfall") or 0), int((b or {}).get("dedupShortfall") or 0)
    if parity:
        return (f"pass-2 bar: parity NOT MET — {len(parity)} key(s) differ between A and B "
                f"(unresolved A={ua} B={ub}, dedupShortfall A={da} B={db}); "
                "see the RED lines above.")
    return (f"pass-2 bar: parity (unresolved A={ua} B={ub}, dedupShortfall A={da} B={db} "
            "tolerated because A==B)")


def pass2_zero_warn(label: str, result: dict[str, Any] | None, *, tolerated: bool) -> str:
    """The per-arm PASS2_ZERO_KEYS WARN under `--pass2-bar parity`; "" when there is
    nothing non-zero to report."""
    zero_warns = [f"{key}={result.get(key)}" for key in PASS2_ZERO_KEYS
                 if int((result or {}).get(key) or 0)]
    if not zero_warns:
        return ""
    if tolerated:
        return (f"WARN {label}: {', '.join(zero_warns)} "
                "(pass2-bar=parity: tolerated because A==B, does not gate).")
    return (f"WARN {label}: {', '.join(zero_warns)} "
            "(pass2-bar=parity: A != B, NOT tolerated — see the RED lines above).")


def plan_parity(
    plan_a: dict[str, Any], plan_b: dict[str, Any], compared_slides: list[int]
) -> list[str]:
    """A and B must plan the SAME ``transforms``/``reuses`` (D5) — any drift makes the
    numbers meaningless (they are no longer comparing the same plan).

    ``suppressGeometry`` is NOT compared for equality across A and B: W1 constructed
    A as AppleScript-only (empty) and B as the compared-slide set, so an equality
    check could never go GREEN. W2 puts both arms on the same ``OBED_OFFLINE_WRITE``
    mode, so A may also equal the compared-slide set. Allowed:

    * W1: A empty, B == ``compared_slides``
    * W2: A == B == ``compared_slides``

    Any other nonempty A list still fails with the W1 ``not empty`` wording so the
    existing tests keep their assertion.
    """
    reasons: list[str] = []
    for key in ("transforms", "reuses"):
        if plan_a.get(key) != plan_b.get(key):
            reasons.append(f"plan {key} drift between A and B")
    a_suppress = sorted(plan_a.get("suppressGeometry") or [])
    b_suppress = sorted(plan_b.get("suppressGeometry") or [])
    expected = sorted(compared_slides)
    if b_suppress != expected:
        reasons.append(f"plan B suppressGeometry {b_suppress} != compared slides {expected}")
    if a_suppress and a_suppress != expected:
        reasons.append(f"plan A suppressGeometry not empty: {sorted(plan_a.get('suppressGeometry') or [])}")
    return reasons


# An output card-border ref count below this fraction of the SOURCE's is card-image LOSS:
# a healthy arm dedups back to the source count (83 == 83 on arm B, and again on the
# 2026-09-08 production run); the damaged 2026-09-07 arm A measured 43/83 = 0.518. The floor
# sits roughly midway, tolerating a legitimate reuse-chain deviation of up to a quarter of
# all card images -- nothing in the reuse plan comes close (D1 §2: population byte-identical
# outside the slide-125 void D6 root-caused).
CARD_REF_FLOOR = 0.75


def card_border_damage_reasons(
    label: str, out_refs: int | None, src_refs: int | None,
    child_resize: dict[str, Any] | None,
) -> list[str]:
    """RED reason(s) for one arm's card-border media style having lost refs against the
    SOURCE deck -- a MEASURED shortfall of card images, reported with no cause attached.
    The known mechanism is D6's: ``remap_keynote.js:applyReuse``'s Cmd-A/Cmd-C/Cmd-V burst
    silently no-ops under Keynote load and the following ``delete slide`` destroys the slide
    holding the cards. ``f76e8d3`` made that delete conditional on a measured per-kind paste
    delta and halts the run on a deficit, so a shortfall that still reaches this gate is
    either a pre-``f76e8d3`` deck, the documented open hole (a stale paste whose per-kind
    histogram DOMINATES the expectation -- equal counts cannot tell the right objects from
    the wrong ones), or a different mechanism; the message says so rather than picking one.
    Empty when not applicable (``src_refs`` falsy -- the source deck has no single
    unambiguous card-border style, same rule ``iwa_write.match_card_stroke_styles`` applies)
    or when ``out_refs`` is within ``CARD_REF_FLOOR`` of ``src_refs``. Only a SHORTFALL
    hard-fails -- a surplus (stranded donor copies) is a dedup shortfall, already covered by
    ``PASS2_ZERO_KEYS`` and by :func:`pass2_bar_line`'s honest parity line, not a second gate
    here.
    """
    if not src_refs:
        return []
    if out_refs is not None and out_refs >= CARD_REF_FLOOR * src_refs:
        return []
    corroboration = ""
    if child_resize:
        dedup = int(child_resize.get("dedupShortfall") or 0)
        unresolved = int(child_resize.get("unresolved") or 0)
        if dedup or unresolved:
            corroboration = f" (dedupShortfall={dedup} unresolved={unresolved})"
    if out_refs is None:
        return [
            f"{label}: the output deck no longer carries an unambiguous card-border "
            f"style (source has {src_refs}){corroboration} — this can be either a "
            "shortfall (lost card images) or a surplus of stranded donor copies "
            "creating a second selectable style; the two look identical here. "
            "REMEDY: inspect the deck's media styles; do not assume the machine is at fault."
        ]
    ratio = out_refs / src_refs
    return [
        f"{label}: card-border refs {out_refs} vs source {src_refs} (ratio {ratio:.3f}, "
        f"floor {CARD_REF_FLOOR}){corroboration} — the arm is MISSING card images and is not "
        "gradeable. This count is the observation; it does NOT establish a cause. Known "
        "mechanism (D6): a pass-1 reuse paste silently no-ops and the slide holding the cards "
        "is then deleted — f76e8d3 halts the run on that path, so a shortfall arriving here "
        "means the deck predates f76e8d3, or a stale paste's per-kind histogram dominated the "
        "expectation (the documented open hole: equal counts cannot tell the right objects "
        "from the wrong ones), or the loss has another cause. DIAGNOSE before re-running: "
        "search this run's log for 'FATAL reuse slide' and 'WARNING reuse slide', then census "
        "cards per slide in this deck against the source."
    ]


def card_border_refs(deck: Path | str) -> int | None:
    """Total refs of the deck's single card-border media style, or None when the deck
    has no unambiguous one -- same classifier ``restore_card_stroke_widths`` uses.

    Offline ``Index/*.iwa`` only, one deck's object map at a time. May raise on a
    genuinely unreadable deck; callers must not let that abort a healthy gate (see
    :func:`main`'s WARN-and-skip wrapper around every call site).
    """
    from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415 (optional iwa extra)
    from obed_edom.iwa_write import card_styles, select_card_styles  # noqa: PLC0415

    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = select_card_styles(
        [s for s in card_styles(objects, id_to_file) if not s["inherited"]], 10
    )
    return int(styles[0]["refs"]) if len(styles) == 1 else None


def _card_border_refs_or_none(label: str, deck: Path | str) -> tuple[int | None, bool]:
    """``card_border_refs``, but a read failure WARNs and returns ``(None, False)``
    instead of propagating -- an exception here must never abort an otherwise-healthy
    gate, nor silently masquerade as :func:`card_border_damage_reasons`'s "lost its
    unambiguous style" case. ``ok`` False means the caller must skip the check."""
    try:
        return card_border_refs(deck), True
    except Exception as exc:  # noqa: BLE001 — optional iwa extra; never abort on a read failure
        _log(f"WARN: {label}: could not read card-border refs ({type(exc).__name__}: {exc}); "
             "skipping the card-border damage check.")
        return None, False


def damage_check_line(
    label: str, *, src_ok: bool, refs_ok: bool, src_refs: int | None,
    out_refs: int | None, damage: list[str],
) -> str:
    """The ``<label> damage check: ...`` status line, mirroring :func:`pass2_health`'s
    positive line -- without it ``gate.log`` jumps straight from pass-2 health to the
    compare with no way to tell whether the card-border damage check ran and passed, was
    SKIPPED (a read failure, already WARNed by :func:`_card_border_refs_or_none`), or was
    NOT APPLICABLE (the source has no unambiguous card-border style). "" when ``damage``
    is non-empty -- the RED line(s) already say it."""
    if not src_ok or not refs_ok:
        return f"{label} damage check: SKIPPED (card-border read failed; see WARN above)."
    if not src_refs:
        return f"{label} damage check: NOT APPLICABLE (source has no unambiguous card-border style)."
    if damage:
        return ""
    return f"{label} damage check: OK ({out_refs} vs source {src_refs} card-border refs)."


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
# Positional pairing (each arm sorted independently by its own box, then zipped by
# index) is unprovable without object ids -- a mis-pairing can look exactly like a real
# displacement -- so compare_units_multiset's deltas are reported only as upper bounds.
# Its population count is the one order-independent, zip-truncation-immune signal in the
# report, but the report is informational at the call site: gate_ok never reads it.
# compare_units_identity (id-matched) is the primary gate.
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
    ``kind``) keeps a group CHILD out of its parent's top-level bucket (D8).

    Without object ids, positional pairing can never be proven correct — a mis-pairing
    is indistinguishable from a real displacement of the same size — so a per-unit delta
    is reported only as an upper bound and never fails the bucket or the overall report.
    Within this report the population count is the trustworthy signal — order-independent,
    checked before any delta work, immune to ``zip`` truncation — but the report itself is
    informational at the call site: ``gate_ok`` never reads ``report["pass"]``.
    :func:`compare_units_identity` (id-matched) is the primary gate.

    Returns ``{"pass": bool, "per_kind": {bucket: {n_a, n_b, pass, worstUpperBound,
    reasons, informational?}}}``.
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
            "worstUpperBound": 0.0,
            "reasons": [],
        }
        if len(a_list) != len(b_list):
            entry["pass"] = False
            entry["reasons"].append(f"count {len(a_list)} != {len(b_list)}")
            per_kind[bucket] = entry
            overall = False
            continue
        tol = tol_hard if bucket in _HARD_KINDS else tol_soft
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
        entry["worstUpperBound"] = worst
        entry["informational"] = True
        if worst > tol:
            entry["reasons"].append(
                f"upper bound from positional pairing (unproven), not a measured "
                f"displacement: worst Δ{worst:.2f}px > {tol}px"
            )
        per_kind[bucket] = entry
    return {"pass": overall, "per_kind": per_kind}


def _log_multiset_report(report: dict[str, Any]) -> None:
    for kind, entry in sorted(report["per_kind"].items()):
        if kind in _TEXT_BUCKETS:
            _log(
                f"    {kind:8} n_a={entry['n_a']:<4} n_b={entry['n_b']:<4} "
                f"worstUpperBound={entry['worstUpperBound']:.2f}px  "
                "text: informational only — UNVERIFIED by this gate"
            )
            continue
        tag = "info" if entry.get("informational") else ("PASS" if entry["pass"] else "FAIL")
        _log(
            f"    {kind:8} n_a={entry['n_a']:<4} n_b={entry['n_b']:<4} "
            f"worstUpperBound={entry['worstUpperBound']:.2f}px  {tag}"
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
    *,
    aspects: dict[str, float] | None = None,
    src_recs_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare every planned transform's target against the drawable it resolves to,
    id-addressed via the SOURCE deck's kind index (D3) -- raise-immune, hide-immune
    (stat-finalize needs no exclusion).

    Covers the SAME exact classes as ``offline_write.verify_offline_frames`` (shape at
    ``tols.hard``, unmasked image/movie -- the resolved record's ``geom_source == "iwa"``
    -- at ``tols.soft``) PLUS ``group`` (its union x/y/w/h vs the composed group-union
    record, also at ``tols.soft``). Measured on the banked A/B arms: the composed union
    tracks a Keynote-written plan at 0.46px median / 1.92px max over 240 comparable
    specs. A record the reader itself flags approximate (``needs_keynote`` set, e.g.
    ``rotated-group``/``group-residual``) is NOT comparable -- it is counted in
    ``skipped`` and listed in ``approx`` (magnitude included) rather than gated on or
    silently dropped. For ``group`` this is checked on EITHER side: the writer itself
    refuses a group spec to the AppleScript fallback when the SOURCE deck's own record
    is ``needs_keynote`` (``iwa_write._slide_edits``), and that flag does not survive
    the write -- so the oracle must honor it too, via ``src_recs_by_id`` (keyed the
    same as ``recs_by_id``, by id in the SOURCE deck's own kind-index space), not only
    the OUTPUT record's flag. Text (autosize ``y``/``w``/``h`` are not offline-recoverable)
    is NOT exactly recoverable from raw IWA and would spuriously RED a text-heavy deck, so
    it is skipped here and left entirely to the A-vs-B identity compare instead. A masked
    image/movie (``geom_source == "mask"``) is skipped too -- its crop is covered by the
    identity compare at ``tols.mask``. Line is skipped as well -- a line spec's x/y is an
    ordinary bbox, a composed line's is ``_line_rect``'s anchor, not a comparable pair
    (see ``offline_write._OFFLINE_EXACT_KINDS``). Every skip increments ``skipped``.

    ``role == "hide"`` specs are skipped (nothing to compare — the object is deleted).
    Any other non-hide, non-skipped spec whose id fails to resolve, or is missing from
    the deck being checked, is a RED ``missing_ids`` entry. Uses
    ``offline_write._spec_box`` for the (planned, actual) tuples — same comparator
    ``verify_offline_frames`` uses.

    A spec with no ``kindIndex`` at all (should never happen -- ``ItemTransform.as_dict``
    always emits one) is a RED ``missing_ids`` entry too, reason ``"spec carries no
    kindIndex"`` — never silently dropped.

    When the caller passes ``aspects`` (a genuinely AppleScript-written arm's
    aspect-locked childless image/movie/group specs), the predicted width is compared
    against both the float aspect-lock ``h * ar`` and its integer rounding (Keynote
    stores the integer when the frame aspect differs from the media aspect), at
    ``TOL_ASPECT``. Neither W2 arm is AppleScript-written (both write geometry offline
    at the same mode), so ``main`` no longer passes ``aspects`` to either oracle call —
    both gate at ``tols.hard``/``tols.soft`` like any other exact/media spec.

    Returns ``{"pass": bool, "per_kind": {kind: {n, worst, pass, fails}}, "missing_ids":
    [...], "skipped": int, "compared": int, "approx": [...]}`` where ``compared`` is the
    total number of specs actually compared (``sum`` of every ``per_kind[kind]["n"]``) —
    0 alongside a non-zero ``skipped`` is a VACUOUS pass (every spec on the slide was an
    inexact class) the caller should call out, not treat as a clean result.
    """
    from obed_edom.offline_write import (  # noqa: PLC0415 — lazy, see module docstring
        _OFFLINE_EXACT_KINDS,
        _OFFLINE_MEDIA_KINDS,
        _spec_box,
    )

    oracle_kinds = _OFFLINE_EXACT_KINDS | _OFFLINE_MEDIA_KINDS | {"group"}
    per_kind: dict[str, dict[str, Any]] = {}
    missing_ids: list[dict[str, Any]] = []
    approx: list[dict[str, Any]] = []
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
        if kind == "group":
            if src_recs_by_id is not None and obj_id not in src_recs_by_id:
                missing_ids.append({"addr": addr, "id": obj_id,
                                    "reason": f"source record missing for ({kind}, {kind_index})"})
                continue
            src_rec = (src_recs_by_id or {}).get(obj_id)
            src_needs = src_rec.get("needs_keynote") if src_rec else None
            out_needs = rec.get("needs_keynote")
            if src_needs or out_needs:
                needs = [f"source:{src_needs}"] if src_needs else []
                if out_needs:
                    needs.append(f"output:{out_needs}")
                skipped += 1
                approx.append({"addr": addr, "id": obj_id, "needs": needs,
                               "worst": max(abs(a - b) for a, b in zip(*_spec_box(spec, rec)))})
                continue
        entry = per_kind.setdefault(kind, {"n": 0, "worst": 0.0, "pass": True, "fails": []})
        tol = tols.hard if kind in _OFFLINE_EXACT_KINDS else tols.soft
        planned, actual = _spec_box(spec, rec)
        ar = (aspects or {}).get(obj_id) if (kind in _ASPECT_LOCKED and not spec.get("children")) else None
        if ar:
            h = round(planned[3])
            w_pred = h * ar
            planned = (round(planned[0]), round(planned[1]), w_pred, float(h))
            tol = TOL_ASPECT
            diffs = [abs(planned[0] - actual[0]), abs(planned[1] - actual[1]),
                     min(abs(planned[2] - actual[2]), abs(round(planned[2]) - actual[2])),
                     abs(planned[3] - actual[3])]
            worst = max(diffs)
        else:
            worst = max(abs(a - b) for a, b in zip(planned, actual))
        entry["n"] += 1
        entry["worst"] = max(entry["worst"], worst)
        if worst > tol:
            entry["pass"] = False
            entry["fails"].append({"addr": addr, "id": obj_id, "worst": worst})
    overall = not missing_ids and all(e["pass"] for e in per_kind.values())
    compared = sum(e["n"] for e in per_kind.values())
    return {"pass": overall, "per_kind": per_kind, "missing_ids": missing_ids,
            "skipped": skipped, "compared": compared, "approx": approx}


def _log_plan_oracle_report(label: str, report: dict[str, Any]) -> None:
    tag = "PASS" if report["pass"] else "FAIL"
    _log(f"    plan-oracle {label}: {tag} ({report['skipped']} non-exact-class spec(s) skipped)")
    for kind, entry in sorted(report["per_kind"].items()):
        status = "PASS" if entry["pass"] else "FAIL"
        _log(f"      {kind:8} n={entry['n']:<4} worst={entry['worst']:.2f}px  {status}")
    if report["missing_ids"]:
        _log(f"      missing_ids: {report['missing_ids']}")
    if report["approx"]:
        worst = max(a["worst"] for a in report["approx"])
        _log(f"      group-approx n={len(report['approx'])} worst={worst:.2f}px  "
             "NOT GATED (reader flagged the union approximate)")
        for a in sorted(report["approx"], key=lambda r: -r["worst"])[:5]:
            _log(f"        {a['addr']} worst={a['worst']:.2f} {a['needs']}")


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

    ``missedSpecs`` gates on fallback coverage (sum(fallbackSpecs.values()) >= missedSpecs
    and fallbackUnwritable == 0), not the raw count.
    """
    reasons: list[str] = []
    refused = ow.get("refused") or []
    missed_specs = int(ow.get("missedSpecs") or 0)
    soft_fallbacks = int(ow.get("softFallbacks") or 0)
    value_clean = bool(ow.get("valueClean", True))
    if refused:
        reasons.append(f"{len(refused)} slide(s) refused the offline patch: {refused}")
    if missed_specs:
        # Coverage floor, not an exact identity: a REFUSED slide falls back whole, so its
        # non-hide specs inflate `fallbackSpecs` past `missedSpecs`. Refusals gate above.
        fallback_total = sum(int(v) for v in (ow.get("fallbackSpecs") or {}).values())
        fallback_unwritable = int(ow.get("fallbackUnwritable") or 0)
        if fallback_total < missed_specs or fallback_unwritable:
            reasons.append(
                f"{missed_specs} spec(s) missed the offline patch and the AppleScript "
                f"fallback did not fully cover them (fallback_specs={fallback_total}, "
                f"unwritable={fallback_unwritable})."
            )
    if soft_fallbacks:
        reasons.append(
            f"{soft_fallbacks} soft (text/masked) frame(s) used a stale fallback, "
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
    zorder_write: dict[str, Any] | None = None,
    previews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything a later ``--reuse-a``/``--reuse-b`` needs, with no Keynote (D13).

    ``offline_write`` is stored MINUS its ``specs`` key (the full per-slide spec dicts
    are already in ``plan["transforms"]``; duplicating them bloats the record).

    ``statJobs`` / ``badgeRaises`` are persisted at the top level (the trimmed plan
    drops them) so a reused record can still resolve the W2 front-block targets.
    ``zorderWrite`` is the piece 3 result dict (counters + eligible ``slides``).
    ``previews`` is the planner's preview-cache provenance (``info["previews"]`` from
    ``remap_and_inspect``: ``{"source": <dir or None>, "placements": n}``) — a record
    written before this field existed has no ``"previews"`` key.

    Raises ``ValueError`` if ``plan`` has NEITHER key: that means ``plan`` is already a
    trimmed, PERSISTED plan (a loaded run record's ``plan``, not a fresh ``plan_out``) —
    silently reading it as "no jobs planned" would hide the caller's mistake. One key
    without the other is also a refuse — do not persist the missing side as ``[]``.
    """
    jobs = raise_job_pair(plan, label="run_record: plan")
    if jobs is None:
        raise ValueError(
            "run_record: plan carries neither 'statJobs' nor 'badgeRaises' — this looks "
            "like an already-trimmed persisted plan, not a fresh plan_out dict."
        )
    stat_jobs, badge_raises = jobs
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
        "statJobs": stat_jobs,
        "badgeRaises": badge_raises,
        "childResize": child_resize,
        "applied": applied,
        "missed": missed,
        "offlineWrite": ow,
        "zorderWrite": dict(zorder_write or {}),
        "specIdMap": spec_id_map,
        "previews": dict(previews) if previews is not None else None,
    }


def preview_provenance_warning(a_record: dict[str, Any], b_record: dict[str, Any]) -> str | None:
    """The roster-keep placer is preview-cache-dependent (root cause A, 2026-09-16 gate
    diagnosis): a reused arm planned against a different (or absent) preview source than
    its counterpart is not a valid A-vs-B baseline for list placement. Returns a WARN
    line (never a RED reason -- a stale reuse is an operator input problem, not a code
    regression) or None when both sides agree."""
    a_previews = a_record.get("previews")
    b_previews = b_record.get("previews")
    if "previews" not in a_record or "previews" not in b_record:
        return "provenance unknown (older run record predates preview-cache provenance)."
    a_source = (a_previews or {}).get("source")
    b_source = (b_previews or {}).get("source")
    if a_source != b_source:
        return (
            f"arm A planned with preview source {a_source!r}, arm B with {b_source!r} -- "
            "if either is None, that arm planned without the preview cache and is an "
            "invalid baseline for list placement; re-run the mismatched arm."
        )
    return None


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
                    compatible_versions: set[int] = COMPATIBLE_GATE_VERSIONS) -> dict[str, Any]:
    """Load + validate a run record against the compatible gate versions and both the
    deck's and the SOURCE wall's OWN digest — refuses (``ValueError``) a stale record
    rather than trusting it.

    A ``commit`` drift is only WARNED, never refused: the deck/source digests are the
    real staleness signal (a docs-only or comment-only commit changes HEAD without
    changing anything this gate reads).
    """
    record = json.loads(Path(path).read_text())
    if int(record.get("gateVersion", -1)) not in compatible_versions:
        raise ValueError(
            f"{path}: gateVersion {record.get('gateVersion')} not in {sorted(compatible_versions)} "
            "(stale run record)"
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


def source_aspects(source_deck: Path | str) -> dict[str, float]:
    from obed_edom.iwa_geometry import compose_geometry  # noqa: PLC0415
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415

    objects, _id_to_file, _file_ids = _load_deck(source_deck)
    out: dict[str, float] = {}
    for slide_id, _skipped in slide_order(objects):
        if slide_id not in objects:
            continue
        for r in compose_geometry(objects[slide_id], objects):
            if r["h"] and r["w"] and r.get("geom_source") != "mask":
                out[r["id"]] = r["w"] / r["h"]
    return out


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
# W2 z-order A/B verdicts — pure, Keynote-free (piece 4).
# ==========================================================================
def same_order(ids_a: list[str], ids_b: list[str]) -> bool:
    """Full ``drawablesZOrder`` id-list equality — ``zorder_compare.py`` / P17."""
    return list(ids_a) == list(ids_b)


def front_block_ok(ids_b: list[str], targets: list[str]) -> bool:
    """Target ids occupy the final ``|T|`` slots, in order, in arm B.

    Arm A only (checking A's order too) is unraised by definition since #136
    removed the GUI raise path — B is the bar. A-vs-B ``SAME_ORDER`` stays
    observational.
    """
    block = list(targets)
    if not block:
        return True
    n = len(block)
    return len(ids_b) >= n and list(ids_b[-n:]) == block


def zorder_slide_verdict(
    ids_a: list[str] | None, ids_b: list[str] | None, targets: list[str],
) -> dict[str, Any]:
    """Per-slide ``SAME_ORDER`` (A-vs-B, observational) / ``FRONT_BLOCK_OK`` (B-only)."""
    if ids_a is None or ids_b is None:
        return {"sameOrder": False, "frontBlockOk": False, "targets": list(targets)}
    return {
        "sameOrder": same_order(ids_a, ids_b),
        "frontBlockOk": front_block_ok(ids_b, targets),
        "targets": list(targets),
    }


def _counter_nonzero(value: Any) -> int:
    """How many failures a z-order counter represents. Missing / 0 / [] / "" = 0."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, str):
        return 0 if not value.strip() else 1
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 if value else 0


def zorder_schema_reasons(
    zorder_write: dict[str, Any] | None, *, label: str = "B",
) -> list[str]:
    """RED if arm B did not emit the piece-3 ``zorderWrite`` schema.

    Absent counters must not be read as 0 — that would GREEN a B that never ran
    the offline z-order writer (every raise stayed on GUI, suffixes still match).
    """
    if not zorder_write:
        return [
            f"{label}: zorderWrite missing — offline z-order writer unproven "
            "(piece 3 result dict was not emitted)"
        ]
    missing = [key for key in ZORDER_SCHEMA_KEYS if key not in zorder_write]
    if missing:
        return [
            f"{label}: zorderWrite missing {missing} — refuse to treat absent "
            "counters as 0"
        ]
    return []


def zorder_counter_reasons(
    zorder_write: dict[str, Any] | None, *, label: str = "B",
) -> list[str]:
    """RED reasons when arm B's ``zorderRefused`` / ``Unresolved`` / ``Lost`` are non-zero.

    Only inspects keys that are present; :func:`zorder_schema_reasons` is what
    refuses a missing schema.
    """
    ow = zorder_write or {}
    reasons: list[str] = []
    for key in ZORDER_ZERO_KEYS:
        if key not in ow:
            continue
        n = _counter_nonzero(ow.get(key))
        if n:
            reasons.append(f"{label}: {key}={ow.get(key)!r} (expected 0)")
    return reasons


def _as_slide_set(value: Any) -> set[int] | None:
    """Slide id set from a ``list``. ``None`` for a count, tuple, set, or string."""
    if not isinstance(value, list):
        return None
    try:
        return {int(s) for s in value}
    except (TypeError, ValueError):
        return None


def claimed_patched_slides(zorder_write: dict[str, Any] | None) -> set[int]:
    """Patched-slide set from ``zorderWrite.slides``. Empty if missing or not a list.

    A count must not be iterated (``{int(s) for s in 2}`` is ``TypeError``). The
    schema/GUI gate REDs that shape; callers just must not crash first.
    """
    parsed = _as_slide_set((zorder_write or {}).get("slides"))
    return parsed if parsed is not None else set()


def raise_slides_from_jobs(
    stat_jobs: list[dict[str, Any]] | None,
    badge_rows: list[dict[str, Any]] | None,
) -> set[int]:
    """Raise-bearing slides (stat rows with a ``childSig``, plus every badge row)."""
    slides: set[int] = set()
    for job in stat_jobs or []:
        if job.get("childSig"):
            slides.add(int(job["slide"]))
    for row in badge_rows or []:
        slides.add(int(row["slide"]))
    return slides


def expected_zorder_sets(
    raise_slides: set[int],
    compared_slides: list[int] | set[int],
    refused: list[int] | set[int] | None = None,
) -> tuple[set[int], set[int]]:
    """``(expected_patched, expected_gui)`` from plan/offline-write facts, not B's claim.

    Eligible = raise-bearing ∩ compared (non-reuse, non-donor) − pass-1 refused.
    Those must be in ``slides``. Every other raise-bearing slide is the reuse /
    ineligible GUI leftover (plan gate line 3).
    """
    compared = {int(s) for s in compared_slides}
    refused_set = {int(s) for s in (refused or [])}
    patched = {s for s in raise_slides if s in compared and s not in refused_set}
    return patched, set(raise_slides) - patched


def zorder_gui_reasons(
    zorder_write: dict[str, Any] | None,
    raise_slides: set[int],
    *,
    compared_slides: list[int] | set[int],
    refused: list[int] | set[int] | None = None,
    label: str = "B",
) -> list[str]:
    """RED unless ``slides`` / ``zorderGui`` match the independent eligible vs leftover sets.

    Trusting B's ``slides`` and only checking ``zorderGui == raise − slides`` would
    still GREEN a B that left an eligible slide unraised and listed it as ineligible.
    """
    ow = zorder_write or {}
    expected_patched, expected_gui = expected_zorder_sets(
        raise_slides, compared_slides, refused,
    )
    reasons: list[str] = []
    patched = _as_slide_set(ow.get("slides"))
    actual_gui = _as_slide_set(ow.get("zorderGui"))
    if patched is None:
        reasons.append(
            f"{label}: slides={ow.get('slides')!r} is not a slide list — "
            "refuse to treat a count as the patched set"
        )
    elif patched != expected_patched:
        reasons.append(
            f"{label}: slides={sorted(patched)} != eligible raise slides "
            f"{sorted(expected_patched)}"
        )
    if actual_gui is None:
        reasons.append(
            f"{label}: zorderGui={ow.get('zorderGui')!r} is not a slide list — "
            "refuse to treat a count as the ineligible set"
        )
    elif actual_gui != expected_gui:
        reasons.append(
            f"{label}: zorderGui={sorted(actual_gui)} != ineligible raise slides "
            f"{sorted(expected_gui)}"
        )
    return reasons


def zorder_slides_count_reasons(
    zorder_write: dict[str, Any] | None, *, label: str = "B",
) -> list[str]:
    """RED if ``zorderSlides`` disagrees with ``len(slides)`` — a self-inconsistent
    B record (e.g. ``slides=[56], zorderSlides=0``) must not read as clean."""
    ow = zorder_write or {}
    patched = _as_slide_set(ow.get("slides"))
    if patched is None:
        return []
    n = _counter_nonzero(ow.get("zorderSlides"))
    if n != len(patched):
        return [
            f"{label}: zorderSlides={ow.get('zorderSlides')!r} != len(slides)="
            f"{len(patched)}"
        ]
    return []


def zorder_write_reasons(
    zorder_write: dict[str, Any] | None,
    raise_slides: set[int],
    *,
    compared_slides: list[int] | set[int],
    refused: list[int] | set[int] | None = None,
    label: str = "B",
) -> list[str]:
    """Arm-B z-order result gate: schema + zero-keys + patched/GUI set identity."""
    reasons = zorder_schema_reasons(zorder_write, label=label)
    if reasons:
        return reasons
    return (
        zorder_counter_reasons(zorder_write, label=label)
        + zorder_slides_count_reasons(zorder_write, label=label)
        + zorder_gui_reasons(
            zorder_write, raise_slides,
            compared_slides=compared_slides, refused=refused, label=label,
        )
    )


def zorder_counter_summary(zorder_write: dict[str, Any] | None) -> str:
    """``Stat zorder detail:``-shaped one-liner from a result dict (missing keys as 0)."""
    ow = zorder_write or {}
    parts = [f"{key}={_counter_nonzero(ow.get(key))}" for key in ZORDER_SURFACE_KEYS]
    return "Stat zorder detail: " + " ".join(parts)


def slide_zorder_ids(objects: dict[str, Any], slide_number: int) -> list[str] | None:
    """``drawablesZOrder`` ids for a 1-based output ordinal (``zorder_compare.py`` method)."""
    from obed_edom.iwa_runs import slide_order  # noqa: PLC0415 — optional iwa extra

    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        return None
    slide = objects.get(order[slide_number - 1][0])
    if not slide:
        return None
    return [str(r["identifier"]) for r in slide.get("drawablesZOrder") or []]


def front_targets_for_slide(
    *,
    id_by_addr: dict[tuple[str, int], str],
    stat_jobs: list[dict[str, Any]],
    badge_rows: list[dict[str, Any]],
    hide_specs: list[dict[str, Any]],
) -> list[str]:
    """Front-block ids from the SOURCE/wall address space: stat (ascending
    ``groupIndex``) then badges (planner row order).

    ``id_by_addr`` is the SOURCE kind index (wall addressing). Stat ``groupIndex``
    is 1-based hide-bridged, so the matching source row is the one whose bridged
    wall index equals ``gi-1``. Badge ``index`` is 1-based WALL and is looked up
    directly — never against a post-raise dest kind index (a GUI raise reorders
    kindIndex and would pick the wrong id). Unresolved rows are omitted (the
    counter gate, not this list, is what REDs an unresolved target).
    """
    from obed_edom.iwa_write import bridge_kind_index  # noqa: PLC0415 — optional iwa extra

    def source_id_for_saved(kind: str, saved_ki: int) -> str | None:
        hidden = {
            (str(h.get("kind")), int(h.get("kindIndex", 0))) for h in hide_specs
        }
        for (k, wall_ki), oid in id_by_addr.items():
            if (k, wall_ki) in hidden:
                continue
            if k == kind and bridge_kind_index(kind, wall_ki, hide_specs) == saved_ki:
                return str(oid)
        return None

    stat_ids: list[str] = []
    jobs = sorted(
        (j for j in stat_jobs
         if j.get("childSig") and int(j.get("groupIndex") or 0) > 0),
        key=lambda j: int(j["groupIndex"]),
    )
    for job in jobs:
        kid = source_id_for_saved("group", int(job["groupIndex"]) - 1)
        if kid:
            stat_ids.append(kid)

    badge_ids: list[str] = []
    for row in badge_rows:
        kind = str(row.get("kind") or "")
        raw_index = row.get("index")
        if raw_index is None:
            continue
        kid = id_by_addr.get((kind, int(raw_index) - 1))
        if kid:
            badge_ids.append(str(kid))
    return stat_ids + badge_ids


def zorder_targets_from_plan(
    plan: dict[str, Any], id_map: dict[str, list[dict[str, Any]]],
) -> dict[int, list[str]]:
    """``{slide: front-block ids}`` from a ``plan_out`` (or persisted job lists)
    plus the SOURCE kind index. Never reads a dest deck's post-raise indexes."""
    hide_specs = [t for t in (plan.get("transforms") or []) if t.get("role") == "hide"]
    stat_by: dict[int, list[dict[str, Any]]] = {}
    for job in plan.get("statJobs") or []:
        stat_by.setdefault(int(job["slide"]), []).append(job)
    badge_by: dict[int, list[dict[str, Any]]] = {}
    for row in plan.get("badgeRaises") or []:
        badge_by.setdefault(int(row["slide"]), []).append(row)
    out: dict[int, list[str]] = {}
    for n in sorted(set(stat_by) | set(badge_by)):
        targets = front_targets_for_slide(
            id_by_addr=_id_by_addr_for_slide(id_map, n),
            stat_jobs=stat_by.get(n, []),
            badge_rows=badge_by.get(n, []),
            hide_specs=[h for h in hide_specs if int(h.get("slide", -1)) == n],
        )
        if targets:
            out[n] = targets
    return out


def raise_job_pair(
    src: dict[str, Any], *, label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Both job lists from one dict, or ``None`` if neither key is present.

    One key without the other is a refuse — do not infer ``[]`` for the missing
    side, or a badge-only source would silently drop every stat target.
    """
    has_stat = "statJobs" in src
    has_badge = "badgeRaises" in src
    if has_stat != has_badge:
        raise ValueError(
            f"{label} carries only one of statJobs/badgeRaises; refuse to "
            "treat the missing key as empty"
        )
    if not has_stat:
        return None
    return list(src.get("statJobs") or []), list(src.get("badgeRaises") or [])


def persisted_raise_jobs(
    plan: dict[str, Any], record: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Return ``(statJobs, badgeRaises)`` from a fresh plan or a persisted record.

    ``None`` means a legacy record with neither key (W1 run records). Both keys
    must come from the same source — do not fill a one-key plan from the record
    (or the reverse), or ``run_record`` synthesizing ``[]`` would hide the gap.
    """
    if "statJobs" in plan or "badgeRaises" in plan:
        return raise_job_pair(plan, label="plan")
    return raise_job_pair(record, label="record")


def w2_oracle_kwargs(
    src_recs_n: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keyword args for arm A's and arm B's ``plan_oracle_slide`` calls under the W2
    gate config: both arms write geometry offline at the same mode, so neither is
    AppleScript-written and neither passes ``aspects`` — both gate at the ordinary
    ``tols.hard``/``tols.soft`` budget rather than arm A narrowing to ``TOL_ASPECT``.
    """
    kwargs = {"src_recs_by_id": src_recs_n}
    return dict(kwargs), dict(kwargs)


# ==========================================================================
# main — the Keynote-touching orchestration.
# ==========================================================================
def slide_selection(raw: str | None) -> frozenset[int] | None:
    from obed_edom.map_remap import parse_slide_spec  # noqa: PLC0415

    return parse_slide_spec(raw)


def main(argv: list[str] | None = None) -> int:
    # Imported here so the pure comparators above import without Keynote/iwa deps present.
    from obed_edom import offline_write  # noqa: PLC0415
    from obed_edom.baseline import deck_digest  # noqa: PLC0415
    from obed_edom.map_remap import slides_for_plan  # noqa: PLC0415
    from obed_edom.remap_keynote import remap_and_inspect  # noqa: PLC0415
    from scripts.write_gate_ab import _remap_env, slide_units  # noqa: PLC0415

    def _write_arm_env(*, offline_write: str, zorder_write: str) -> None:
        _remap_env(suppress="", as_geometry="1", geom_props="1", offline_write=offline_write)
        os.environ["OBED_ZORDER_WRITE"] = zorder_write

    def _clear_write_env() -> None:
        os.environ.pop("OBED_OFFLINE_WRITE", None)
        os.environ.pop("OBED_ZORDER_WRITE", None)

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", type=Path, required=True, help="wall (source) .key")
    ap.add_argument("--template", type=Path, required=True, help="CG template .key")
    ap.add_argument(
        "--out", type=Path, required=True,
        help="scratch dir for the A/B decks (Keynote-writable, not /tmp)",
    )
    ap.add_argument("--slides", help="slides to remap, e.g. 47 or 47,82,110-113 (default: whole deck)")
    ap.add_argument(
        "--mode", choices=("verify", "on"), default="verify",
        help="both arms' OBED_OFFLINE_WRITE (default verify: patch + live verify); "
             "A/B then differ only on OBED_ZORDER_WRITE off vs on",
    )
    ap.add_argument("--reuse-a", type=Path,
                    help="banked A .key (with its <deck>.run.json) — SKIP running A")
    ap.add_argument("--reuse-b", type=Path,
                    help="banked B .key (with its <deck>.run.json) — SKIP running B")
    ap.add_argument(
        "--control-a", type=Path,
        help="second same-code A deck for the RAISE10 SAME_ORDER A-vs-A control "
             "(Keynote-free compare; required on RAISE10, meaningless on Gold)",
    )
    ap.add_argument("--validate", dest="validate", action="store_true", default=True,
                    help="live-verify readback after each run (default on)")
    ap.add_argument("--no-validate", dest="validate", action="store_false",
                    help="skip the live-verify readback (required for the Full deck)")
    ap.add_argument("--tol-hard", type=float, default=TOL_HARD,
                    help=f"shape px tolerance vs the PLAN (oracle, per side; line is "
                         f"skipped by the oracle); identity (A-vs-B) gates "
                         f"shape+line at 2x this (default {TOL_HARD})")
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
        help="strict (default): every PASS2_ZERO_KEYS/PASS2_PARITY_KEYS A-vs-B parity is "
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
    if args.control_a is not None and not args.control_a.exists():
        ap.error(f"--control-a not found: {args.control_a}")

    tols = Tolerances(args.tol_hard, args.tol_soft, args.tol_mask, args.tol_text, args.tol_child)

    try:
        slide_range = slide_selection(args.slides)
    except ValueError as exc:
        ap.error(str(exc))

    from obed_edom.baseline import cache_root, preview_cache_dir  # noqa: PLC0415

    resolved_cache_root = cache_root()
    source_preview_dir = preview_cache_dir(deck_digest(args.source))
    _log(
        f"Preview cache: root={resolved_cache_root} "
        f"source preview dir={source_preview_dir} "
        f"exists={source_preview_dir.is_dir()}"
    )

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    a_deck = args.reuse_a if args.reuse_a is not None else out / "A_unflagged.key"
    b_deck = args.reuse_b if args.reuse_b is not None else out / "B_flagged.key"

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
        id_map = a_record["specIdMap"]
        zorder_write_a = a_record.get("zorderWrite") or {}
        _log(f"REUSE A: {a_deck} (run record OK).")
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
    else:
        _log(f"A: {args.source.name} OBED_OFFLINE_WRITE={args.mode} "
             f"OBED_ZORDER_WRITE=off -> {a_deck}")
        _write_arm_env(offline_write=args.mode, zorder_write="off")
        plan_a: dict[str, Any] = {}
        try:
            info_a = remap_and_inspect(
                args.source, a_deck, template=args.template, slide_range=slide_range,
                export_dir=None, plan_out=plan_a, log=_log, validate=args.validate,
            )
        finally:
            _clear_write_env()
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
        child_resize_a = info_a.get("childResize")
        applied_a = int(info_a.get("applied") or 0)
        id_map = spec_id_map(args.source)
        zorder_write_a = info_a.get("zorderWrite") or {}
        a_record = run_record(
            commit=commit, deck_digest=deck_digest(a_deck), source_digest=deck_digest(args.source),
            plan=plan_a, child_resize=child_resize_a, applied=applied_a,
            missed=int(info_a.get("missed") or 0), offline_write=info_a.get("offlineWrite"),
            spec_id_map=id_map, zorder_write=zorder_write_a, previews=info_a.get("previews"),
        )
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
    reasons_a = pass2_health(child_resize_a, label="A", zero_keys_hard=zero_keys_hard)
    for r in reasons_a:
        _log(f"RED: {r}")
    if reasons_a:
        _log("ABORT: run A pass-2 (stat-finalize) is UNHEALTHY — see RED lines above. B never ran.")
        return 3
    _log("A pass-2 health: OK.")

    src_refs, src_ok = _card_border_refs_or_none("source", args.source)
    out_refs_a, a_refs_ok = _card_border_refs_or_none("A", a_deck)
    damage_a = (
        card_border_damage_reasons("A", out_refs_a, src_refs, child_resize_a)
        if src_ok and a_refs_ok else []
    )
    line_a = damage_check_line("A", src_ok=src_ok, refs_ok=a_refs_ok, src_refs=src_refs,
                               out_refs=out_refs_a, damage=damage_a)
    if line_a:
        _log(line_a)
    for r in damage_a:
        _log(f"RED: {r}")
    if damage_a:
        _log("ABORT: run A is DAMAGED — see RED lines above. B never ran; diagnose the loss "
             "before paying for another run.")
        return 6

    # `compared_slides` depends only on A's plan (transforms) — compute it once,
    # before B runs, so B's own suppressGeometry can be checked against it (D5/D1) and
    # the per-slide loop below does not recompute it.
    wanted = slides_for_plan(slide_range)
    compared_slides = sorted(
        offline_write._offline_write_slides(plan_a.get("transforms") or [], wanted)
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
        ow_b = b_record["offlineWrite"] or {}
        zorder_write_b = b_record.get("zorderWrite") or {}
        _log(f"REUSE B: {b_deck} (run record OK).")
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
    else:
        _log(f"B: same plan, OBED_OFFLINE_WRITE={args.mode} OBED_ZORDER_WRITE=on -> {b_deck}")
        _write_arm_env(offline_write=args.mode, zorder_write="on")
        plan_b: dict[str, Any] = {}
        try:
            info_b = remap_and_inspect(
                args.source, b_deck, template=args.template, slide_range=slide_range,
                export_dir=None, plan_out=plan_b, log=_log, validate=args.validate,
            )
        finally:
            _clear_write_env()
        if not args.validate:
            _log("live verify SKIPPED (--no-validate).")
        child_resize_b = info_b.get("childResize")
        applied_b = int(info_b.get("applied") or 0)
        ow_b = info_b.get("offlineWrite") or {}
        zorder_write_b = info_b.get("zorderWrite") or {}
        b_record = run_record(
            commit=commit, deck_digest=deck_digest(b_deck), source_digest=deck_digest(args.source),
            plan=plan_b, child_resize=child_resize_b, applied=applied_b,
            missed=int(info_b.get("missed") or 0), offline_write=ow_b, spec_id_map=id_map,
            zorder_write=zorder_write_b, previews=info_b.get("previews"),
        )
        write_run_record(_run_record_path(b_deck), b_record)
        _log(f"Run record written -> {_run_record_path(b_deck)}")
        _warn_and_close_stray_documents("B", b_deck)
        if args.quit_between_runs:
            quit_ok, elapsed = quit_keynote_and_wait()
            if quit_ok:
                _log(f"Keynote quit between runs ({elapsed:.0f} s)")
            else:
                _log(f"WARN: Keynote still running after {elapsed:.0f} s")

    if args.reuse_a is not None or args.reuse_b is not None:
        provenance_warning = preview_provenance_warning(a_record, b_record)
        if provenance_warning:
            _log(f"WARN: preview-cache provenance: {provenance_warning}")

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

    reasons_b = pass2_health(child_resize_b, label="B", zero_keys_hard=zero_keys_hard)
    for r in reasons_b:
        _log(f"RED: {r}")

    out_refs_b, b_refs_ok = _card_border_refs_or_none("B", b_deck)
    damage_b = (
        card_border_damage_reasons("B", out_refs_b, src_refs, child_resize_b)
        if src_ok and b_refs_ok else []
    )
    line_b = damage_check_line("B", src_ok=src_ok, refs_ok=b_refs_ok, src_refs=src_refs,
                               out_refs=out_refs_b, damage=damage_b)
    if line_b:
        _log(line_b)
    for r in damage_b:
        _log(f"RED: {r}")

    parity = pass2_parity(child_resize_a, child_resize_b)
    for r in parity:
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
            warn = pass2_zero_warn(label, result, tolerated=not parity)
            if warn:
                _log(warn)

    drift = plan_parity(plan_a, plan_b, compared_slides)
    for r in drift:
        _log(f"RED: {r}")

    ow_missed = int(ow_b.get("missedSpecs") or 0)
    ow_fallback = sum(int(v) for v in (ow_b.get("fallbackSpecs") or {}).values())
    ow_unwritable = int(ow_b.get("fallbackUnwritable") or 0)
    if ow_missed and ow_fallback >= ow_missed and not ow_unwritable:
        _log(f"WARN B: missedSpecs={ow_missed} fully covered by the AppleScript fallback "
             f"(fallbackSpecs={ow_fallback}, unwritable=0; does not gate).")

    summary_reasons = summary_gate_reasons(ow_b, applied_a, applied_b)
    for r in summary_reasons:
        _log(f"RED: {r}")

    try:
        raise_jobs = persisted_raise_jobs(plan_a, a_record)
    except ValueError as exc:
        _log(f"ABORT: {exc}")
        return 2
    if raise_jobs is None:
        stat_jobs_a, badge_rows_a = [], []
    else:
        stat_jobs_a, badge_rows_a = raise_jobs
    raise_slides = raise_slides_from_jobs(stat_jobs_a, badge_rows_a)

    zorder_reasons = zorder_write_reasons(
        zorder_write_b, raise_slides,
        compared_slides=compared_slides, refused=ow_b.get("refused"),
    )
    for r in zorder_reasons:
        _log(f"RED: {r}")
    _log(f"A {zorder_counter_summary(zorder_write_a)}")
    _log(f"B {zorder_counter_summary(zorder_write_b)}")

    gate_ok = not (
        reasons_b or drift or parity or summary_reasons or damage_b or zorder_reasons
    )

    # ============================ per-slide compare =================================
    # Decode A, extract every compared slide's units, then DROP A's raw archive map
    # before decoding B — two whole-deck decodes held live at once is the dominant
    # memory cost on the Full deck.
    src_objects, src_by_slide = decode_deck(args.source)
    del src_objects
    a_objects, a_by_slide = decode_deck(a_deck)
    a_units_by_slide = {n: slide_units(a_objects, n) for n in compared_slides}
    a_z_by_slide = {n: slide_zorder_ids(a_objects, n) for n in compared_slides}
    jobs_plan = {
        "transforms": plan_a.get("transforms") or [],
        "statJobs": stat_jobs_a, "badgeRaises": badge_rows_a,
    }
    targets_by_slide = zorder_targets_from_plan(jobs_plan, id_map)
    del a_objects

    control_z_by_slide: dict[int, list[str] | None] | None = None
    if args.control_a is not None:
        control_objects, _control_by_slide = decode_deck(args.control_a)
        control_z_by_slide = {n: slide_zorder_ids(control_objects, n) for n in compared_slides}
        del control_objects
        _log(f"CONTROL A: {args.control_a} (SAME_ORDER A-vs-A on RAISE10).")

    b_objects, b_by_slide = decode_deck(b_deck)
    zw_slide_set = claimed_patched_slides(zorder_write_b) or None

    _log(
        f"Comparing {len(compared_slides)} planned non-reuse, non-donor slide(s): "
        f"{compared_slides} (reuse-target and donor slides are NOT covered by this gate)."
    )

    vacuous_slides: list[int] = []
    zorder_front_n = 0
    zorder_front_ok = 0
    zorder_same_n = 0
    zorder_same_ok = 0
    zorder_ctrl_n = 0
    zorder_ctrl_ok = 0
    for n in compared_slides:
        specs_n = [t for t in (plan_a.get("transforms") or []) if int(t.get("slide", -1)) == n]
        id_by_addr = _id_by_addr_for_slide(id_map, n)

        src_recs_n = src_by_slide.get(n, {})
        kwargs_a, kwargs_b = w2_oracle_kwargs(src_recs_n)
        oracle_a = plan_oracle_slide(specs_n, id_by_addr, a_by_slide.get(n, {}), tols, **kwargs_a)
        oracle_b = plan_oracle_slide(specs_n, id_by_addr, b_by_slide.get(n, {}), tols, **kwargs_b)
        _log(f"  slide {n}:")
        _log_plan_oracle_report("A", oracle_a)
        _log_plan_oracle_report("B", oracle_b)
        if not (oracle_a["pass"] and oracle_b["pass"]):
            gate_ok = False
        if any(r["compared"] == 0 and r["skipped"] > 0 for r in (oracle_a, oracle_b)):
            vacuous_slides.append(n)
            _log(f"  slide {n}: WARN plan-oracle VACUOUS PASS — every planned spec on this "
                 "slide is a non-exact class (text/group/masked/line); 0 compared, PASS proves nothing.")

        a_units = a_units_by_slide[n]
        b_units = slide_units(b_objects, n)

        identity = None
        try:
            identity = compare_units_identity(a_units, b_units, tols)
        except ValueError as exc:
            _log(f"RED: slide {n}: {exc}")
            gate_ok = False
        if identity is not None:
            _log_identity_report(identity)
            if not identity["pass"]:
                gate_ok = False
                _log("    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                _log(f"    !! slide {n}: IDENTITY COMPARE FAILED (id_rate={identity['id_rate']:.1%}) —")
                _log("    !! the multiset/addr diagnostics below for this slide are UNTRUSTED.")
                _log("    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

            multiset = compare_units_multiset(a_units, b_units, args.tol_hard, args.tol_soft)
            _log_multiset_report(multiset)  # informational cross-check only (D2)
            # open: a count mismatch here isn't gated (e.g. a lost zero-width autosize shape
            # identity doesn't carve) -- not decided whether it should be, not fixed here.

            if not identity["pass"]:
                _log(f"  slide {n}: identity compare FAILED — running the addr-matched permutation "
                     "diagnostic:")
                addr_report = compare_units_by_addr(a_units, b_units, args.tol_hard, args.tol_soft)
                _log_addr_report(addr_report)

        a_z = a_z_by_slide.get(n)
        b_z = slide_zorder_ids(b_objects, n)
        targets_n = targets_by_slide.get(n) or []
        verdict = zorder_slide_verdict(a_z, b_z, targets_n)
        eligible = (n in zw_slide_set) if zw_slide_set is not None else bool(targets_n)
        zorder_same_n += 1
        if verdict["sameOrder"]:
            zorder_same_ok += 1
        front_tag = "n/a"
        if eligible:
            zorder_front_n += 1
            if targets_n and verdict["frontBlockOk"]:
                zorder_front_ok += 1
                front_tag = "yes"
            else:
                front_tag = "no"
                gate_ok = False
                _log(f"RED: slide {n}: FRONT_BLOCK_OK=no")
        ctrl_tag = "n/a"
        if control_z_by_slide is not None:
            zorder_ctrl_n += 1
            ctrl_same = same_order(a_z or [], control_z_by_slide.get(n) or [])
            if a_z is not None and control_z_by_slide.get(n) is not None and ctrl_same:
                zorder_ctrl_ok += 1
                ctrl_tag = "yes"
            else:
                ctrl_tag = "no"
                gate_ok = False
                _log(f"RED: slide {n}: SAME_ORDER(A-vs-A)=no — A-vs-B z-order verdict is void")
        _log(
            f"    z-order SAME_ORDER(A-vs-B)={'yes' if verdict['sameOrder'] else 'no'} (observational) "
            f"SAME_ORDER(A-vs-A)={ctrl_tag} FRONT_BLOCK_OK={front_tag}"
        )

    if vacuous_slides:
        _log(f"NOTE: plan-oracle VACUOUS PASS on slide(s) {vacuous_slides} — 0 specs compared "
             "(every planned spec was a non-exact class); those slides' oracle result rests "
             "entirely on the identity compare above, not this oracle.")
    _log(pass2_bar_line(zero_keys_hard=zero_keys_hard, parity=parity,
                        a=child_resize_a, b=child_resize_b))
    if control_z_by_slide is None:
        ctrl_bar = (
            "SAME_ORDER(A-vs-A) n/a (pass --control-a with a second A deck "
            "for the RAISE10 control)"
        )
    else:
        ctrl_bar = f"SAME_ORDER(A-vs-A) {zorder_ctrl_ok}/{zorder_ctrl_n}"
    _log(
        f"zorder bar: FRONT_BLOCK_OK {zorder_front_ok}/{zorder_front_n} "
        f"SAME_ORDER(A-vs-B) {zorder_same_ok}/{zorder_same_n} observational "
        f"{ctrl_bar}"
    )
    _log("OFFLINE-WRITE GATE: GREEN" if gate_ok else "OFFLINE-WRITE GATE: RED (see above)")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
