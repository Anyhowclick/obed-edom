# live5 fold — DSK frame check, DSK coverage, ownership flake, frozen_region control (2026-10-14)

Diagnosis (binding): `.agents/reviews/cef-placement-2026-10-13/impl/W6-live5-diag-report.md`. No §5/§11 contract or owner
decision changes. Two parallel streams on disjoint files; build on HEAD 2d64a25e.

## W6 (scripts/dissolve_probe.py, scripts/managed_obs_qualify.py, tests/test_dissolve_probe.py, tests/test_managed_obs_qualify.py)
1. DSK frame identity (item 1): record rVFC `expectedDisplayTime` alongside the existing fields, and a per-video freeze-draw
   timestamp (from the harness's existing dump instrumentation of the freeze take; if that requires a product hook, STOP and report
   instead of editing src/). Select, per decoder, the frame whose expectedDisplayTime is the latest ≤ that video's draw time; holder
   must equal it. Keep `rvAt` as a lateness diagnostic. No ±1-frame tolerance. Missing fields → INCONCLUSIVE. Table rows: A25/B25
   shapes (late callback after take) now pass; a genuine stale holder (frame visible at draw is N+1, holder N) still fails.
2. DSK coverage (item 1b): if m-snap-cef-dsk has < 5 mid frames, recapture that arm a bounded number of times (≤2 extra) within the
   same launch and fail closed if still < 5; record every attempt. Never lower 5 or admit boundary frames.
3. Scorer labelling (item 2b): a transaction that aborted on ownership verification with isolation_ok true and no isolation
   violation scores iso-obs-* INCONCLUSIVE (missing evidence), not FAIL; overall still fails closed.
4. frozen_region control (item 3): `m-fg-cef` expects frozen_region PASS and replaces m-snap-cef as the CEF_PLACEMENT positive
   control; m-hold-cef stays the FAIL control. Verify by offline re-score of A30 (`SCR/live5/out/runs/placement-20261014-172217.json`;
   clone with `cp -cR` into a directory you can write, e.g. under the worktree's ignored `output/` or your sandbox tmp) → overall PASS.

## W3 (src/obed_edom/managed_obs.py, tests/test_managed_obs.py)
5. Ownership observation (item 2a): in the calibration path's ownership verification (`managed_obs.py` ~:850 and the identity
   observer ~:1754), boundedly retry ONLY an "unknown" observation within the existing calibration deadline (short backoff); never
   retry or accept "gone"/mismatch. Extend the existing calibration matrix tests (fewest additions): unknown→ours passes; persistent
   unknown fails closed at the deadline; gone fails immediately.
