# W6 live5 fold 2 implementation report

## Result

Implemented B1, M1, D1's W6 labeling, L1, L2, and L3 in W6's four owned files. The final targeted suite passes. No §11 frozen-contract deviation was required.

## Files changed

- `scripts/dissolve_probe.py`
  - B1: the harness-only `drawImage(video, ...)` wrapper now samples and closes a `VideoFrame` immediately before and after each native draw, recording microsecond timestamps and draw duration (`:587-607`).
  - B1: DSK holder identity is derived from `round(timestamp_us / 1_000_000 * counter_fps)`; unequal before/after timestamps, missing timestamps, or disagreement between multiple frac draws make the arm INCONCLUSIVE (`:3230-3252`, `:3402-3426`). rVFC rows and callback times remain recorded diagnostics and are not used to choose the holder frame (`:3232-3233`, `:3307-3328`, `:3406-3413`). The DSK timing record also carries the exercised take's `__obedTakeMs` value (`:3322-3328`).
  - M1/L1: capture coverage now reports the full arm's problems using the profile's requested frame threshold rather than a partial fade-only view (`:3197-3206`).
  - L2: removed the misleading `callbackLatenessMs` derivative; diagnostics use the neutral `rvfcCallbackAt` name (`:3232-3233`).
  - D2 rationale embodied in the existing fold: `m-fg-cef` is the independent frozen-region PASS arm and `m-hold-cef` remains the FAIL control (`:448-449`, `:2745`). This does not double-count the paused holder candidate.
- `scripts/managed_obs_qualify.py`
  - D1: recognizes the exact W3 ownership failure suffix `Calibration engine ownership could not be verified.` for both the cleaned synthetic shape and W3's refused/pre-install shape, labeling isolation INCONCLUSIVE instead of FAIL (`:481-515`).
  - M1/L1: retries only when the full attempt has the sole problem `n mid frames < CEF_PLACEMENT.mid_frames`; every DSK recapture is persisted at `runs/<arm>/attempt-N/record.json` with its PNGs (`:2066-2089`, call site `:2208-2216`).
  - M1: every persisted attempt is rescored with coverage disabled but all other arm checks active; the placement gate passes only when every attempt is MATCH, and the aggregate is retained as `captureAttemptScore` (`:2092-2120`, `:3210-3218`).
- `tests/test_dissolve_probe.py`
  - B1/L2: Chromium-shaped rVFC fixtures include `expectedDisplayTime >= presentationTime` and a skipped `presentedFrames`; tests prove rVFC timing changes/absence are diagnostic, VideoFrame before/after disagreement is INCONCLUSIVE, holder comparison follows VideoFrame timestamps, take cost is retained, and the old callback-lateness field is absent (`:548-578`, `:1119-1247`).
  - D2: pins `m-fg-cef` as the frozen-region PASS control (`:1513-1514`).
- `tests/test_managed_obs_qualify.py`
  - L3/M1/L1: recapture assertions live in their own placement test, covering exact sole-problem retry, attempt record/PNG persistence, all-attempt scoring, and refusal to retry when another problem is present (`:119-164`).
  - D1: adds the W3 ownership-abort result shape and asserts `iso-obs-preview` is INCONCLUSIVE (`:1724-1729`, `:1815-1816`).

## Frozen contracts

- §11.6 evidence remains under each arm's run directory; the new recapture evidence is additive under `attempt-N` and the root record retains relative record paths plus the aggregate score.
- W3 types and the exact ownership error string are consumed without changing W3-owned files.
- Player behavior remains untouched; no Keynote `main.js` was edited and no player replacement was added here.
- No contract was found wrong or unimplementable, so there are no deviations to report.

## Verification

- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`
  - **507 passed, 1 skipped, 0 failed, 0 errors** in 177.18 s.
- `git diff --check`
  - **PASS**, no output.

The single skip is pre-existing/environment-dependent within the targeted files. None of the three named external-red tests were run because they are outside W6's permitted targeted files.

## Open items for the coordinator

- Run W3's owned `tests/test_managed_obs.py` validation and the cross-stream integration suite after collecting the parallel W3 change.
- Run OBS/Chrome/Keynote qualification and full gates; these were explicitly out of scope for W6.
- The known external reds listed in the brief remain unmodified and unassessed by this stream.
