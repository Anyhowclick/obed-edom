"""Keynote-free replay of the live-verify-zorder-bridge coverage arithmetic (W2
zorder-bridge Piece 2, opt-in/slow) against a banked A/B gate round.

The banked run records under ``output/bank/<date>/fresh-gate/{gold,raise10}/`` carry
``zorderWrite`` (with ``kindIndexMap``) and ``offlineWrite``'s ``statSlides``/``slides``,
but ``offlineWrite["specs"]`` is popped before persisting (``run_record`` in
``scripts/offline_write_ab.py``) and neither run touched ``.cache/inspect`` (``use_cache=
False`` on a verify-mode readback) -- so there is no banked "planned specs" or "Keynote
payload" to load directly. This script REGENERATES both, Keynote-free:

    planned specs  -- re-run the planner through `golden_plan.capture_plan` against the
                       banked run's ORIGINAL source+template deck (not `B_flagged.key`
                       itself), the same route `scripts/golden_plan.py` uses to prove a
                       plan is reproducible from deck bytes alone.
    "live" payload -- `derive_kind_index` (the pure-Python IWA kind-index reader) against
                       `B_flagged.key` directly, standing in for what a real Keynote
                       inspect would report.

THIS SUBSTITUTES THE OFFLINE READER FOR KEYNOTE. It proves the live-verify-zorder-bridge
ADDRESSING and COVERAGE ARITHMETIC hold on two real, large, previously-gated decks -- NOT
that Keynote agrees with any of it. Only a real Keynote-backed A/B gate run (the owner-run
live gate the plan's "Sequencing" section calls for after both pieces) proves that.

    PYTHONPATH=src uv run --no-sync python scripts/replay_live_verify.py
    PYTHONPATH=src uv run --no-sync python scripts/replay_live_verify.py --round gold

Each named round degrades gracefully (prints what is missing and moves on) when its
source/template deck cannot be found or its digest does not match the banked
``sourceDigest`` -- it never fabricates or hardcodes the expected numbers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obed_edom import baseline, offline_write  # noqa: E402
from scripts import golden_plan  # noqa: E402


def _git_head() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""

BANK_DIR = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/bank/2026-09-16/fresh-gate")
DECK_DIR = golden_plan.DECKS
TEMPLATE = golden_plan.TEMPLATE

# name -> candidate ORIGINAL source wall deck (never `B_flagged.key`, which is the
# Keynote-WRITTEN output the plan is verifying against, not the planner's input).
SOURCE_CANDIDATES: dict[str, str] = {
    "gold": "Gold_Wall_Input.key",
    "raise10": "RAISE10_Wall.key",
}


def _payload_from_deck(key_path: Path) -> dict[str, Any]:
    """`{"slides": [{"number": n, "items": records}, ...]}`, synthesizing what a live
    Keynote inspect would report from `derive_deck_kind_index`'s pure-Python read of the
    already-written deck -- the Piece-2-honest stand-in this script's docstring names."""
    from obed_edom.iwa_kindindex import derive_deck_kind_index  # noqa: PLC0415 (optional iwa extra)

    by_index = derive_deck_kind_index(key_path)
    return {
        "slides": [
            {"number": idx + 1, "items": records} for idx, records in sorted(by_index.items())
        ]
    }


def replay_round(name: str, bank_dir: Path) -> None:
    print(f"\n=== {name} ===")
    b_deck = bank_dir / "B_flagged.key"
    b_record_path = bank_dir / "B_flagged.run.json"
    if not b_deck.exists() or not b_record_path.exists():
        print(f"SKIP {name}: {b_deck} / {b_record_path} not found under {bank_dir}.")
        return

    record = json.loads(b_record_path.read_text())
    source_digest = record.get("sourceDigest")
    candidate_name = SOURCE_CANDIDATES.get(name)
    source = DECK_DIR / candidate_name if candidate_name else None
    if source is None or not source.exists():
        print(f"SKIP {name}: no candidate source deck for {name!r} found "
              f"(looked for {source}). Cannot re-derive planned specs without it.")
        return
    if not TEMPLATE.exists():
        print(f"SKIP {name}: template deck {TEMPLATE} not found.")
        return
    actual_source_digest = baseline.deck_digest(source)
    if actual_source_digest != source_digest:
        print(f"SKIP {name}: {source} digest {actual_source_digest} != banked "
              f"sourceDigest {source_digest} -- not the deck this run planned against.")
        return

    actual_deck_digest = baseline.deck_digest(b_deck)
    if actual_deck_digest != record.get("deckDigest"):
        print(f"WARN {name}: {b_deck} digest {actual_deck_digest} != banked "
              f"deckDigest {record.get('deckDigest')} -- deck moved since the gate ran; "
              "proceeding anyway (informational only).")

    head = _git_head()
    if head and record.get("commit") != head:
        print(f"WARN {name}: record commit {record.get('commit')!r} != HEAD {head!r} -- "
              "the planner (and any geometry fix landed since) may have moved since this "
              "round was banked, so a re-derived plan can legitimately disagree with what "
              "was actually baked into this deck for reasons that have nothing to do with "
              "the live-verify-zorder-bridge feature itself. A mismatch below is only "
              "trustworthy as a Piece 2 signal when this commit matches HEAD.")

    print(f"Re-deriving the plan from {source.name} + {TEMPLATE.name} (Keynote-free)…")
    with golden_plan._pinned_env():
        _wall, _tmpl, plan_out, _env = golden_plan.capture_plan(source, TEMPLATE)
    transforms = plan_out.get("transforms") or []

    ow = record.get("offlineWrite") or {}
    offline_slides = set(ow.get("slides") or [])
    if not offline_slides:
        print(f"SKIP {name}: banked offlineWrite carries no 'slides' -- nothing to verify.")
        return
    planned = {
        n: [t for t in transforms if int(t.get("slide", -1)) == n] for n in offline_slides
    }

    zorder_write = record.get("zorderWrite") or {}
    zorder_patched_slides = set(zorder_write.get("slides") or [])
    kind_index_map_raw = zorder_write.get("kindIndexMap")
    stat_slides = frozenset(int(n) for n in (ow.get("statSlides") or []))
    multiset_kinds_by_slide = {n: {"group"} for n in stat_slides}
    missing_kind_index_map = bool(zorder_patched_slides) and not kind_index_map_raw
    if missing_kind_index_map:
        print(f"WARN {name}: banked zorderWrite has {len(zorder_patched_slides)} patched "
              "slide(s) but no 'kindIndexMap' -- this run record predates W2 zorder-bridge "
              "Piece 1 (which first captured it), so the positional remap for those slides "
              "cannot be reconstructed from the bank. SKIPPING the positional bar entirely "
              "(running it without a remap would silently compare the WRONG objects on "
              "every patched slide, worse than not running it) -- not fabricating numbers "
              "here. The multiset bar below needs no kindIndex, so it still replays for "
              "real; a fresh gate run banked AFTER Piece 1 is required for the positional "
              "and coverage numbers the plan documents.")
        print(f"{name}: Reading back {b_deck.name} via derive_deck_kind_index (Keynote-free)…")
        payload = _payload_from_deck(b_deck)
        planned = {
            n: [t for t in transforms if int(t.get("slide", -1)) == n] for n in stat_slides
        }
        set_report = offline_write.verify_live_frames_multiset(planned, payload, multiset_kinds_by_slide)
        offline_write._say_verify_report(
            f"{name}: offline-write live verify (set) (REPLAY, partial)", set_report,
            offline_write.LIVE_VERIFY_TOL, print,
        )
        return
    kindindex_remap = offline_write.coerce_kind_index_map(kind_index_map_raw or {})

    print(f"Reading back {b_deck.name} via derive_deck_kind_index (Keynote-free)…")
    payload = _payload_from_deck(b_deck)

    live_report = offline_write.verify_live_frames(
        planned, payload, kindindex_remap=kindindex_remap,
        multiset_kinds_by_slide=multiset_kinds_by_slide,
    )
    set_report = offline_write.verify_live_frames_multiset(planned, payload, multiset_kinds_by_slide)
    coverage = offline_write.live_verify_coverage(planned, kindindex_remap, multiset_kinds_by_slide)

    offline_write._say_verify_report(
        f"{name}: offline-write live verify (REPLAY)", live_report, offline_write.LIVE_VERIFY_TOL,
        print,
    )
    offline_write._say_verify_report(
        f"{name}: offline-write live verify (set) (REPLAY)", set_report, offline_write.LIVE_VERIFY_TOL,
        print,
    )
    print(f"{name}: {offline_write.format_live_verify_coverage(coverage)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", choices=sorted(SOURCE_CANDIDATES), default=None,
                    help="replay only this round (default: all rounds under BANK_DIR)")
    ap.add_argument("--bank-dir", type=Path, default=BANK_DIR,
                    help=f"bank directory holding <round>/B_flagged.key (default: {BANK_DIR})")
    args = ap.parse_args(argv)

    rounds = [args.round] if args.round else sorted(SOURCE_CANDIDATES)
    for name in rounds:
        replay_round(name, args.bank_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
