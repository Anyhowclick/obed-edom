# Pass 2A analysis (offline, 2026-10-14)

Run: `live3/runs/placement-20261013-231739.json` (25 fps, code `ae1c0f63`), re-scored offline with
`managed_obs_qualify.placement_gates` on an APFS clone of `live3/raw-out` (evidence untouched). Decision record
`q0b-2026-10-11/runs/decision_record_q0b1.json`. Unpatched re-score reproduces the live verdict exactly (null control).

## Decision: the inherited INCONCLUSIVEs do NOT count as REPORTED for this PR

The `m-snap-cef[clip]`, `wrongrule-cef`, `perfect-shift` and tone arms are this PR's own §5 gate (CEF frac holder fidelity),
not Chrome regression scope. Scoring them REPORTED would ship the PR's central claim unqualified. The inherited cause is
an instrument bug that is cheap to fix here, and fixing it unmasks failures that are new to CEF placement.

## Root cause of the inherited INCONCLUSIVE ("null timing while paused")

`scripts/dissolve_probe.py:2551` (`anim_problem`, from `b2a8f2cd`, dissolve merge) requires a non-null `startTime` for a
`paused` animation unless `currentTime == 0`. Web Animations unresolves `startTime` on pause and holds `currentTime`, so
every correctly paused reference record (`ct 750, start null, state paused`) fails the shared schema check and the whole
arm is INCONCLUSIVE. The producer is right; the validator is wrong. Same cause fails `CEF placement tone observation`.

## Re-score with the validator accepting `paused` + resolved `ct` (scratch monkeypatch, not committed)

| Arm | Unpatched | Patched | Cause after patch |
|---|---|---|---|
| m-snap-cef-far-x / far-y / near-x | INCONCLUSIVE | **MATCH** | interior 2–4 LSB, edge 0 |
| perfect-shift | INCONCLUSIVE | **MATCH** | |
| CEF placement tone observation | FAIL | ok | |
| m-snap-cef | INCONCLUSIVE | INCONCLUSIVE | `holder_pixels`: "no kept interior or edge-band px" (interior 2.0, edge null) |
| wrongrule-cef | INCONCLUSIVE | INCONCLUSIVE | same (interior 183.0, edge null) — expected FAIL is visible in interior |
| m-snap-cef-near-y, nooffset-y | INCONCLUSIVE | INCONCLUSIVE | **0 holders, expected 1**; no bound decoder; paused reference None (twins too) |
| m-snap-cef-nooffset-x | INCONCLUSIVE | INCONCLUSIVE | holder strip does not decode at its device scale (twin too) |
| m-snap-cef-dsk | INCONCLUSIVE | INCONCLUSIVE | 4 mid frames < 5; holder strip does not decode → `frozen_frame`, `cost` INCONCLUSIVE |
| m-tone-cef | INCONCLUSIVE | **MISMATCH** | tone FAIL, worst 12 LSB (identity map applied) |
| m-tone-raw-cef | INCONCLUSIVE | INCONCLUSIVE | no twin to verify the production mask |
| cut-on / cut-off | INCONCLUSIVE | INCONCLUSIVE | no screencast frame inside [DOM insertion, cut completion] (inherited "cut") |

## Classification

- Inherited, instrument: paused-timing validator (fix here). Cut capture coverage (parent "cut", may stay REPORTED with owner ok).
- New, needs root cause before 2B: y-clip cells bind no holder; holder strip decode failures (nooffset-x, dsk); empty edge band on
  the no-clip cell; tone 12 LSB on CEF (W5 tone map is an open parent item); missing `m-tone-raw-cef` twin; dsk mid-frame coverage.
- 2B on `ae1c0f63` is pointless until these are resolved; 2B runs on the fixed head (two valid 30 fps launches needed).
- 30 fps take: Mac entered "Clamshell Sleep" on battery at 00:01 (lid closed). Next live pass: AC power, lid open.
