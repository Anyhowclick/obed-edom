# W6 fold — review edge fix r1 (2026-10-14)

Read `.agents/reviews/cef-placement-2026-10-13/review-edgefix-r1.md`. Build on the uncommitted diff (W1 owns src/ and
tests/test_live_runtime.py — do not touch). Fold B1, L3, L4, L5, L6:
- B1: add a `nooffsetx` in-memory override for m-snap-cef-nooffset-x and its twin placing the content at x≈-80 (mirror the y
  override and its NOOFFSET constant), keeping the near-x clip, the strip outside the clip (or decodable per O-M1), no later-painted
  element overlapping the visible clip (check ALL events/effects), non-empty displaced overlap, and the W1 containment guard
  `fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5` passing with the splice applied (compute fx/fw/ww the way the patched player does).
  Prove on real p2bin geometry in the existing table row(s).
- L3: `score_displaced_holder`: |displacement| < 1 → INCONCLUSIVE.
- L4: pass demix progress values only for demixed candidates that exist (ev.B None → no new INCONCLUSIVE).
- L5: widen the nooffset-y overlap proof to all events/effects.
- L6: diagnostic offline rescore of today's four live4 takes with ONLY the player-pin equality relaxed (scratch monkeypatch,
  never in-tree) to confirm m-fg-cef and the other arms under the new scorer; report per take.
Fewest test additions. Run tests/test_dissolve_probe.py and tests/test_managed_obs_qualify.py at -n 2.
