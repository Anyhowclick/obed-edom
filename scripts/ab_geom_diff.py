#!/usr/bin/env python3
"""A/B geometry diff between two CG output decks (e.g. OBED_AS_GEOMETRY OFF vs ON).

Reads the cached inspect payloads the remap already wrote for each output deck
(no Keynote needed), matches objects per slide by a CONTENT signature — not by
index, so a silent index-swap can't hide — and reports every object whose
position/size differs beyond tolerance, plus anything present in one deck but not
the other. A clean run (0 diffs) means the AppleScript geometry path placed every
object exactly where the JXA path did.

Usage:
    python scripts/ab_geom_diff.py output/cg_OFF.key output/cg_ON.key [--tol 2.5]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path


def _newest_cache_for(deck_path: str) -> dict | None:
    """The most recently written inspect cache whose payload path is this deck."""
    target = str(Path(deck_path).expanduser().resolve())
    best: tuple[float, dict] | None = None
    for f in glob.glob(".cache/inspect/*.json"):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        p = d.get("path") or ""
        if str(Path(p).resolve()) == target if p else False:
            mtime = Path(f).stat().st_mtime
            if best is None or mtime > best[0]:
                best = (mtime, d)
    return best[1] if best else None


def _sig(item: dict) -> str:
    """Position-independent identity for an object.

    Prefers text/file (unique-ish); falls back to kind+size for bare shapes/lines
    so those still pair. Deliberately excludes x/y so a moved object still matches
    its twin (we WANT to compare positions, not pair on them)."""
    kind = str(item.get("kind") or "")
    text = (item.get("text") or "").strip()
    if text:
        return f"{kind}|t:{text[:40]}"
    fn = (item.get("fileName") or "").strip()
    if fn:
        return f"{kind}|f:{fn}"
    return f"{kind}|wh:{round(float(item.get('w') or 0))}x{round(float(item.get('h') or 0))}"


def _by_slide(payload: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for s in payload.get("slides") or []:
        n = int(s.get("number") or (int(s.get("index") or 0) + 1))
        out[n] = list(s.get("items") or [])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck_a", help="baseline deck (e.g. cg_OFF.key)")
    ap.add_argument("deck_b", help="comparison deck (e.g. cg_ON.key)")
    ap.add_argument("--tol", type=float, default=2.5, help="px tolerance (default 2.5)")
    args = ap.parse_args(argv)

    a = _newest_cache_for(args.deck_a)
    b = _newest_cache_for(args.deck_b)
    if a is None:
        print(f"No inspect cache found for {args.deck_a} — run the remap first (it inspects the output).")
        return 2
    if b is None:
        print(f"No inspect cache found for {args.deck_b} — run the remap first.")
        return 2

    a_slides, b_slides = _by_slide(a), _by_slide(b)
    tol = args.tol
    total = moved = unmatched = 0
    worst: list[tuple[float, str]] = []

    for n in sorted(set(a_slides) | set(b_slides)):
        a_items = a_slides.get(n, [])
        b_items = b_slides.get(n, [])
        b_by_sig: dict[str, list[dict]] = defaultdict(list)
        for it in b_items:
            b_by_sig[_sig(it)].append(it)
        for it in a_items:
            total += 1
            sig = _sig(it)
            pool = b_by_sig.get(sig)
            if not pool:
                unmatched += 1
                worst.append((9e9, f"slide {n}: UNMATCHED in B — {sig}"))
                continue
            # nearest twin by position (handles duplicate sigs sanely)
            ax, ay = float(it.get("x") or 0), float(it.get("y") or 0)
            twin = min(pool, key=lambda t: abs(float(t.get("x") or 0) - ax) + abs(float(t.get("y") or 0) - ay))
            pool.remove(twin)
            dx = float(twin.get("x") or 0) - ax
            dy = float(twin.get("y") or 0) - ay
            dw = float(twin.get("w") or 0) - float(it.get("w") or 0)
            dh = float(twin.get("h") or 0) - float(it.get("h") or 0)
            d = max(abs(dx), abs(dy), abs(dw), abs(dh))
            if d > tol:
                moved += 1
                worst.append((d, f"slide {n}: {sig}  Δpos=({dx:+.0f},{dy:+.0f}) Δsize=({dw:+.0f},{dh:+.0f})"))
        # objects in B with no A twin
        for sig, leftovers in b_by_sig.items():
            for _ in leftovers:
                unmatched += 1
                worst.append((9e9, f"slide {n}: UNMATCHED in A — {sig}"))

    print(f"A={args.deck_a}  B={args.deck_b}  tol={tol}px")
    print(f"objects compared: {total} | beyond tol: {moved} | unmatched: {unmatched}")
    if not moved and not unmatched:
        print("\n✅ CLEAN — every object lands within tolerance; B matches A.")
        return 0
    print("\nTop divergences (a big Δpos like +3000 = object left at wall coords = a silent AS miss):")
    for d, line in sorted(worst, key=lambda x: -x[0])[:40]:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
