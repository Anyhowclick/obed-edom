"""Durable JXA-derived per-slide (kind, count) bank for the kindIndex guard's cross-check.

`test_iwa_kindindex.py`'s local-integration tests need a `reader='jxa'` payload to
compare `derive_kind_index` against; the shared inspect-cache slot is not that (it is
routinely re-stamped `reader='offline'`), so a JXA-derived kind-count bank is durable
where that cache slot is not. This is the ONLY thing in the repo allowed to open
Keynote for `tests/fixtures/jxa-kind-counts/`. `Full_Report_Card_Wall.key` is
deliberately not banked as part of routine use: a 155-slide, 6.7 GB deck is not read
on this machine by default; pass `--deck Full_Report_Card_Wall.key` explicitly if you
ever want it banked.

    .venv/bin/python scripts/bank_jxa_kind_counts.py --deck Gold_Wall_Input.key
    .venv/bin/python scripts/bank_jxa_kind_counts.py --deck Gold_Wall_Input.key \\
        --accept-input-drift
    .venv/bin/python scripts/bank_jxa_kind_counts.py --deck Gold_Wall_Input.key \\
        --payload /path/to/jxa-payload.json

`--payload` banks from an already-captured JXA payload JSON and opens no Keynote.
It refuses a non-`jxa` reader or a mismatched deck name, and it is incompatible
with `--accept-input-drift`: a payload load cannot itself refresh the bank's
basis, so drift can only be accepted from a live Keynote read.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obed_edom import baseline
from obed_edom.inspect import inspect_keynote

DECKS = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")

BANK_VERSION = 1

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "jxa-kind-counts"


def bank_path(deck_name: str) -> Path:
    return FIXTURES_DIR / f"{Path(deck_name).stem.lower()}.json"


def _build_bank(deck: Path, payload: dict[str, Any]) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    for slide in payload.get("slides") or []:
        counts: dict[str, int] = {}
        for item in slide.get("items") or []:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        slides.append({"slide": slide["index"], "counts": counts})
    return {
        "bankVersion": BANK_VERSION,
        "inspectVersion": baseline.INSPECT_VERSION,
        "deck": deck.name,
        "sourceDigest": baseline.deck_digest(deck),
        "reader": payload["reader"],
        "keynoteVersion": payload.get("keynoteVersion"),
        "keynoteBundleId": payload.get("keynoteBundleId"),
        "capturedUTC": datetime.now(timezone.utc).isoformat(),
        "slideCount": len(slides),
        "slides": slides,
    }


def _do_bank(args: argparse.Namespace) -> None:
    deck = DECKS / args.deck
    if args.payload and args.accept_input_drift:
        raise SystemExit(
            "--accept-input-drift is not compatible with --payload: a payload load cannot "
            "itself refresh the bank's basis, so drift can only be accepted from a live "
            "Keynote read"
        )
    path = bank_path(args.deck)
    old = json.loads(path.read_text()) if path.exists() else None
    source_digest = baseline.deck_digest(deck)
    if old is not None:
        print(f"source digest {old.get('sourceDigest')} -> {source_digest}")
        drifted = old.get("sourceDigest") != source_digest
        if drifted and not args.accept_input_drift:
            raise SystemExit(
                "input digest drift vs the committed bank; pass --accept-input-drift to "
                "re-bank against the new deck bytes (a live Keynote read, not --payload)"
            )

    if args.payload:
        payload = json.loads(args.payload.read_text())
    else:
        payload = inspect_keynote(deck, use_cache=False)

    if payload.get("reader") != "jxa":
        raise SystemExit(
            f"payload reader is {payload.get('reader')!r}, expected 'jxa': refusing to bank "
            "a non-JXA payload"
        )
    payload_deck_name = Path(payload.get("path") or "").name
    if payload_deck_name != args.deck:
        raise SystemExit(
            f"payload deck is {payload_deck_name!r}, expected {args.deck!r}: refusing to bank "
            "a mismatched deck"
        )

    bank = _build_bank(deck, payload)
    if old is not None:
        old_by_slide = {row.get("slide"): row.get("counts") for row in old.get("slides") or []}
        for row in bank["slides"]:
            old_counts = old_by_slide.get(row["slide"])
            if old_counts != row["counts"]:
                print(f"  slide {row['slide']} counts: {old_counts} -> {row['counts']}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bank, sort_keys=True, indent=1) + "\n")
    print(
        f"{deck.name} {bank['slideCount']} slides, reader={bank['reader']}\n"
        f"  source {bank['sourceDigest'][:16]}…\n"
        f"  wrote {path}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", required=True, help="deck file name under DECKS, e.g. Gold_Wall_Input.key")
    ap.add_argument(
        "--payload",
        type=Path,
        default=None,
        help="bank from an already-captured JXA payload JSON; opens no Keynote",
    )
    ap.add_argument(
        "--accept-input-drift",
        action="store_true",
        help="allow re-banking when the deck digest differs from the committed bank",
    )
    args = ap.parse_args(argv)
    _do_bank(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
