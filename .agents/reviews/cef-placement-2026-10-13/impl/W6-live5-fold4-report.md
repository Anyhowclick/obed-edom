# W6 live5 fold 4 implementation report

## Result

Implemented the binding live5 r3 coordinator decision in W6's qualification harness. The DSK coverage retry now reruns the complete placement session inside the existing OBS launch, with a new host/page, calibration transaction, recording, hook state, record, and image set per attempt. It retries only when the attempt's sole problem is the mid-frame shortage, stops after three attempts, scores every saved attempt with coverage disabled and all other checks enabled, and requires every attempt plus every attempt's placement calibration gates to pass.

The authorized targeted suite is green: **510 passed, 1 skipped, 0 failed, 0 errors**. No OBS, Chrome, Keynote, full suite, gate runner, commit, stash, reset, checkout, or rebase was run.

## Files changed

- `scripts/managed_obs_qualify.py`: session-level DSK retry orchestration, per-attempt persistence/scoring/rescore discovery, opaque-arm calibration propagation, and retry-aware disk preflight.
- `scripts/dissolve_probe.py`: coverage scoring accepts the session calibration; fixed the reviewed continuation indentation. Existing W6 placement/freeze-draw work remains intact.
- `tests/test_managed_obs_qualify.py`: forward-only fresh-session retry regression, exact retry rules, three-attempt cap, per-attempt scoring/calibration-gate coverage, and updated disk preflight expectation.
- `tests/test_dissolve_probe.py`: unchanged by fold 4; retains the prior W6 offline fixture coverage in the uncommitted stream diff.

## Review findings

### Major — retry the whole DSK placement session

- `scripts/managed_obs_qualify.py:2066-2085`: bounds the retry to three attempts and continues only for the exact sole `N mid frames < required` problem.
- `scripts/managed_obs_qualify.py:2129-2311`: one attempt owns a fresh `QualificationCalibrationAdapter`, `LiveOutputHost`, hooked transport/page, program recording, calibration evidence, images, and record directory.
- `scripts/managed_obs_qualify.py:2314-2343`: the DSK wrapper writes `runs/m-snap-cef-dsk/attempt-N/record.json` and images for every attempt; the parent record is only the attempt index/summary. There is no in-session re-drive path.
- `scripts/managed_obs_qualify.py:2105-2126`: every attempt is rescored with `CEF_PLACEMENT.mid_frames=0`; every other scorer check stays enabled, and the aggregate passes only when every outcome is `MATCH`.
- `scripts/managed_obs_qualify.py:3229-3277`: placement evidence is loaded and rescored for every attempt, using the same live probe controls; every attempt must return placement-calibration `PASS`.
- `scripts/managed_obs_qualify.py:3969-3986`: offline placement rescore expands parent summaries into all attempt records, so each attempt runs through the same classifier and persistence APIs.
- `scripts/managed_obs_qualify.py:4109-4148`: quit persistence, backup capture, recording retention, and final calibration gates are completed independently for every attempt.
- `scripts/managed_obs_qualify.py:4151-4165`: disk preflight includes the two possible extra DSK attempts.
- `tests/test_managed_obs_qualify.py:119-214`: a fake host retains a forward-only scene position. The shortage retry creates a distinct host for attempt 2 and both reach scenes 15 then 17 without `scene not reached`; the table also proves no retry for an additional problem, a maximum of three attempts, no coverage call for non-DSK arms, use of the supplied calibration, persistence of every record/image, and all-attempt scoring.
- `tests/test_managed_obs_qualify.py:2230-2275`: the placement gate fixture contains two DSK attempt records and proves both calibration records are rescored.

### Low 1 — do not create a record during rescore unless it was loaded

- `scripts/managed_obs_qualify.py:3247-3276`: attempt records are written only after an existing path was loaded; the parent capture score is written only when the parent record exists.
- `tests/test_managed_obs_qualify.py:2263-2275`: the missing-run-directory case runs from an empty working directory and proves no stray `record.json` is created.

### Low 3 — continuation indentation

- `scripts/dissolve_probe.py:448-449`: aligned the `m-fg-cef` continuation with the surrounding call style.

### Low 4 — use the session calibration for coverage

- `scripts/dissolve_probe.py:3199-3208`: `capture_coverage` accepts and forwards a `Calibration` to the ordinary arm scorer.
- `scripts/managed_obs_qualify.py:3636-3645`: the validated `opaque-off` calibration is decoded once and retained in the placement context.
- `scripts/managed_obs_qualify.py:2318-2328`: DSK coverage uses that session calibration; the default calibration is only the fail-closed fallback when opaque calibration is unavailable.
- `tests/test_managed_obs_qualify.py:123-176`: verifies both coverage decisions receive the exact supplied session calibration.

Low 2 from the review was accepted by design and required no change.

## Frozen-contract mapping

- §11.1 classifier/capture API: each attempt retains the W2 `ClassifierInput` and is rescored through `placement_probe.classify_probe`; no classifier thresholds or asset pins changed.
- §11.2 calibration/persistence API: each attempt has its own W3 adapter transaction, `CalibrationResult`, program guard, collection references, cleanup result, quit snapshot, and backup references.
- §11.3 host/grant status: each attempt constructs a fresh probe-mode managed host and retains its placement events/status. The engine remains the same managed OBS launch.
- §11.4 recalibrate/UI: consumed status only; no W5 files or wire contracts changed.
- §11.5 player behavior: no `src/` file or Keynote `main.js` was edited; player changes remain sha-pinned in memory.
- §11.6 evidence schema: every `attempt-N/record.json` carries the complete frozen `placementCalibration` schema and relative FileRefs. The parent DSK record is an additive harness-only attempt index. Missing/unreadable attempt evidence remains INCONCLUSIVE. Online and offline rescoring both call the same classifier, persistence, and dissolve scorer APIs.

No deviation from §11 was required.

## Verification

Commands ran from `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`.

1. Focused fold-4 regressions:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs_qualify.py::test_placement_capture_retries_only_for_sole_coverage_shortage_and_scores_every_saved_attempt 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[cef-complete]' -q -p no:cacheprovider`

   Result: **2 passed, 0 skipped, 0 failed, 0 errors** in 7.96 s.

2. Required targeted suite:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

   Result: **510 passed, 1 skipped, 0 failed, 0 errors** in 102.69 s.

3. Syntax check:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py`

   Result: **PASS**, exit 0.

4. `git diff --check`

   Result: **PASS**, no output.

The single skip is the existing environment-dependent skip in the authorized targeted files. The three named external census reds were outside W6's permitted test files and were not run.

## Open items for the coordinator

- Run live OBS/Chrome placement qualification and the coordinator's cross-stream/full suites; the W6 brief prohibited those runs.
- Review the final cross-stream W3 implementation together with these per-attempt records; W6 did not edit `src/obed_edom/managed_obs.py` or its tests.
- The known external census reds remain unmodified and unassessed by W6.
