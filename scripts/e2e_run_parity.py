"""End-to-end read-path parity gate for the Sermon Checker.

Runs the real checker on an LW + DSK pair via BOTH read paths and diffs the
whole-pipeline result — pairings, flags, and highlighted markup — so a change to
the offline/bulk read (slim-bulk, l5-bulk-cache, incremental-previews) can be
confirmed not to move any operator-visible finding.

    offline+bulk : inspect_keynote_checker  (the two-tier path)
    full JXA     : inspect_keynote           (the legacy per-object path)

Previews are exported once (offline path) and reused for both diffs, so the only
variable is the geometry read. ``use_cache=False`` forces fresh reads both times,
so Keynote must be free and this costs ~4 full inspects (minutes).

    .venv/bin/python scripts/e2e_run_parity.py
    .venv/bin/python scripts/e2e_run_parity.py --lw A.key --dsk B.key

KNOWN BASELINE (2026-08-31): pairings + markup identical, flags identical except
ONE benign divergence — LW slide 21's masked/flipped photo reads `photo.rotated`
(offline, composed 354°) vs `photo.differs` (JXA), same slide + severity. That is
the documented angle-composition edge (why rotation is out of the digest), not a
regression. A DIFFERENT or ADDITIONAL divergence is the thing to investigate.
See .agents/plans/checker_offline_geometry.plan.md → "Probe results".
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

from obed_edom.diff_keynotes import compare_inspects
from obed_edom.inspect import inspect_keynote, inspect_keynote_checker

CHECKER_DIR = Path("/Users/anyhowclick/Desktop/Diff-Checker")
DEFAULT_LW = CHECKER_DIR / "Sermon_PK (GW).key"
DEFAULT_DSK = CHECKER_DIR / "Sermon_PK (DSK)_with mistakes.key"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "e2e-parity"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _flag_key(f) -> tuple:
    return (
        getattr(f, "rule", None),
        getattr(f, "deck", None),
        getattr(f, "slide", None),
        getattr(f, "severity", None),
    )


def _flag_full(f) -> tuple:
    return _flag_key(f) + (getattr(f, "message", None),)


def _pairing(result) -> list[tuple]:
    return [(p.get("leftIndex"), tuple(p.get("rightIndexes") or [])) for p in result.get("pairs", [])]


def _markup(result) -> list[tuple]:
    return [(p.get("leftMarkup"), p.get("rightMarkup")) for p in result.get("pairs", [])]


def _diff(name: str, a: list, b: list, key=lambda x: x) -> bool:
    sa, sb = [key(x) for x in a], [key(x) for x in b]
    if sa == sb:
        _log(f"  {name}: IDENTICAL ({len(sa)} items)")
        return True
    ca, cb = Counter(sa), Counter(sb)
    only_off = list((ca - cb).elements())
    only_jxa = list((cb - ca).elements())
    _log(f"  {name}: DIFFER — offline-only {len(only_off)}, jxa-only {len(only_jxa)}, "
         f"order-changed {sa != sb and ca == cb}")
    for x in only_off[:8]:
        _log(f"      offline-only: {x}")
    for x in only_jxa[:8]:
        _log(f"      jxa-only:     {x}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lw", type=Path, default=DEFAULT_LW, help="LW (wall) deck; the diff's left side")
    ap.add_argument("--dsk", type=Path, default=DEFAULT_DSK, help="DSK (lower-third) deck; the right side")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="scratch dir for previews (Keynote-writable; not /tmp)")
    args = ap.parse_args()

    for label, deck in (("LW", args.lw), ("DSK", args.dsk)):
        if not deck.exists():
            ap.error(f"{label} deck not found: {deck}")

    lw_prev, dsk_prev, heat = args.out / "lw_prev", args.out / "dsk_prev", args.out / "heat"
    for d in (lw_prev, dsk_prev, heat):
        d.mkdir(parents=True, exist_ok=True)

    _log(f"OFFLINE (inspect_keynote_checker): LW={args.lw.name} DSK={args.dsk.name}")
    t = time.perf_counter()
    lw_off = inspect_keynote_checker(args.lw, export_dir=lw_prev, use_cache=False)
    _log(f"  LW offline {time.perf_counter()-t:.0f}s reader={lw_off.get('reader')} slides={len(lw_off.get('slides') or [])}")
    t = time.perf_counter()
    dsk_off = inspect_keynote_checker(args.dsk, export_dir=dsk_prev, use_cache=False)
    _log(f"  DSK offline {time.perf_counter()-t:.0f}s reader={dsk_off.get('reader')} slides={len(dsk_off.get('slides') or [])}")

    _log("FULL JXA (inspect_keynote): no export; reuse the offline previews")
    t = time.perf_counter()
    lw_jxa = inspect_keynote(args.lw, export_dir=None, use_cache=False)
    _log(f"  LW jxa {time.perf_counter()-t:.0f}s reader={lw_jxa.get('reader')} slides={len(lw_jxa.get('slides') or [])}")
    t = time.perf_counter()
    dsk_jxa = inspect_keynote(args.dsk, export_dir=None, use_cache=False)
    _log(f"  DSK jxa {time.perf_counter()-t:.0f}s reader={dsk_jxa.get('reader')} slides={len(dsk_jxa.get('slides') or [])}")

    _log("DIFF: compare_inspects on both pairs")
    r_off = compare_inspects(lw_off, dsk_off, lw_prev, dsk_prev, heat / "off", left_label="LW", right_label="DSK")
    r_jxa = compare_inspects(lw_jxa, dsk_jxa, lw_prev, dsk_prev, heat / "jxa", left_label="LW", right_label="DSK")
    _log(f"offline flags={len(r_off.get('flags') or [])} pairs={len(r_off.get('pairs') or [])} | "
         f"jxa flags={len(r_jxa.get('flags') or [])} pairs={len(r_jxa.get('pairs') or [])}")

    ok = True
    ok &= _diff("pairing", _pairing(r_off), _pairing(r_jxa))
    ok &= _diff("flags(rule,deck,slide,sev)", r_off.get("flags") or [], r_jxa.get("flags") or [], key=_flag_key)
    ok &= _diff("flags(+message)", r_off.get("flags") or [], r_jxa.get("flags") or [], key=_flag_full)
    ok &= _diff("markup", _markup(r_off), _markup(r_jxa))

    _log("PARITY: IDENTICAL" if ok else "PARITY: DIFFERENCES (see above — compare against the KNOWN BASELINE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
