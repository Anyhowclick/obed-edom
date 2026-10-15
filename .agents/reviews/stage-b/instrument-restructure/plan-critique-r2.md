# Plan critique r2 (Opus 5.5 high): READY

All 18 r1 findings are resolved and none was refuted. M1's offline `ab-summary` table was recomputed and is exact.
Withdrawing the per-visit p95 proposal and leaving the cadence statistic to the owner is sound. Clean headless runs
sit at about 30 Hz on multi-video slides, so any rule at 2× a 16.67 ms period sits on the boundary.

Six folds were made by the coordinator into plan r3. None changes a module boundary.

## Medium
- **m1. Cadence has no interim behaviour and no freeze point.**
  - V implements cost and environment validity, plus cadence *measurement* in `measured`.
  - The cadence gate lands as a separate V checkpoint after the owner freezes Q2.
  - New gate row **5a / owner** freezes the Q1 host rows and the Q2 cadence statistic, together with the historical list. Gates 7–14 do not start before 5a.
- **m2. The judge's role for `departureExposure` was unstated.**
  - It is a required applicable verdict wherever a ride start is attributed, and it enters `combine()`.
  - The registry lists its value for every existing control row.
  - `departure-early-hide` runs once as RECORDED discovery; its full outcome set is then registered by review before gate 7.

## Low
- **L1.** G updates the `gates` fixture (`tests/test_run_gates.py:322-331`) to symlink `gate_checks.py` and `live_run_validity.py`, and moves the stub pins out of `PROBE_STUB`. The sha-mismatch case keeps its independent literal.
- **L2.** At closure, the Coordinator updates obed-edom `SKILL.md` (`:828`) for the pin, judge and validity references.
- **L3.** "OBS feed judge requires every plan verdict" becomes an explicit Owner Q1 row (whole-deck CEF qualification).
- **L4.** `P` does not change without an owner decision. Raising `P` and a 30 Hz headless profile are presented as Q2 options with their fail-closed consequences.
