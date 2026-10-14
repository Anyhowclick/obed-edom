# W6 live5 fold 3 implementation report

## Result

Folded review live5 r2 M1, Medium 1 using the required lenient repair-draw rule, Medium 2, and all four lows in W6's four owned files. The required targeted suite is green: **510 passed, 1 skipped, 0 failed, 0 errors**. No OBS, Chrome, Keynote, full suite, gate runner, commit, stash, reset, checkout, rebase, or non-W6 source file was touched.

## Files changed

- `scripts/dissolve_probe.py`: records and scores full-size versus repair draws, time-filters DSK evidence, and keeps legacy non-DSK records readable.
- `scripts/managed_obs_qualify.py`: scores complete capture records, bounds retries to multi-attempt arms, tightens ownership labeling, and guards missing-run-directory writes.
- `tests/test_dissolve_probe.py`: extends the DSK scorer table and legacy evidence coverage.
- `tests/test_managed_obs_qualify.py`: covers real complete-record coverage, retry rules, ownership negatives, and the missing-run-directory guard.

## Per-finding fixes

### M1 — retry coverage used an incomplete record

- `scripts/managed_obs_qualify.py:2079-2088`: merges base and driven records before the real coverage scorer, persists that merged record, and retries only on the exact sole shortage.
- `tests/test_managed_obs_qualify.py:119-134`: splits a complete synthetic record into base/driven halves, calls the real `capture_coverage` without monkeypatching that call, and proves the capture path returns the complete-record problems.
- `tests/test_managed_obs_qualify.py:136-177`: retains bounded retry and additional-problem refusal coverage.

### Medium 1 — decoder frame changed across freeze draws

- `scripts/dissolve_probe.py:587-608`: records each harness-observed draw's argument count, before/after `VideoFrame.timestamp`, and duration.
- `scripts/dissolve_probe.py:3232-3279`: derives the reference only from full-size five-argument draws, requires those draws and their before/after samples to agree, allows repair draws on the same frame, records exactly-one-frame-later repairs as diagnostics, and rejects every other repair-frame relation.
- `scripts/dissolve_probe.py:3344-3356` and `:3431-3452`: use the same selector in recorded DSK diagnostics and enforcing media scoring.
- `tests/test_dissolve_probe.py:1213-1254`: covers within-draw change, disagreement between full-size draws, the diagnostic one-frame repair, a two-frame repair failure, and filtering a bad draw outside the capture window.

### Medium 2 — ownership label masked isolation/Program failures

- `scripts/managed_obs_qualify.py:492-515`: ownership-specific INCONCLUSIVE now additionally requires `transaction.isolation_ok` and `program_ok is not False`; known isolation or Program failures score FAIL.
- `tests/test_managed_obs_qualify.py:1749-1758` and `:1848-1851`: exact ownership-error rows with isolation false and Program false both expect FAIL.

### Low 1 — draw rows were not time-filtered

- `scripts/dissolve_probe.py:3235-3244`: considers only draws whose `startedAt` lies in `[advanceAt, first effective rAF]`.
- `tests/test_dissolve_probe.py:1245-1254`: proves a deliberately bad pre-advance draw is excluded.

### Low 2 — coverage ran for one-attempt arms

- `scripts/managed_obs_qualify.py:2071-2091`: coverage and attempt metadata run only when the capture limit exceeds one.
- `tests/test_managed_obs_qualify.py:179-182`: any coverage call fails the test for a single-attempt arm.

### Low 3 — old non-DSK records required `freezeDraws`

- `scripts/dissolve_probe.py:2840-2858`: absent `freezeDraws` defaults to `[]`; rows are still validated when present.
- `tests/test_dissolve_probe.py:1294-1298`: a non-DSK record without the field avoids `decoder/rVFC records malformed` and still MATCHes.
- Retained evidence audit: all **322** non-DSK `record.json` files under the supplied live4/live5 trees had zero `decoder/rVFC records malformed` schema results. Full read-only rescoring of representative live4 and live5 `m-snap-cef` records also reported `decoderMalformed=false` in both cases.

### Low 4 — missing session wrote a root record

- `scripts/managed_obs_qualify.py:3203-3224`: keeps a missing `runDir` as `None`, returns an INCONCLUSIVE attempt gate, and guards every write.
- `tests/test_managed_obs_qualify.py:2218-2228`: removes one session's `runDir`, runs `placement_gates` from an empty working directory, and verifies no `record.json` appears there.

## Frozen-contract mapping and deviations

- §11.6's `placementCalibration` schema, dataclass serialization, classifier/persistence API reuse, gate names, missing-evidence behavior, and relative file references are unchanged.
- `argumentCount` and repair diagnostics are additive fields in the existing dissolve harness's `dump.vids[].freezeDraws` / `dskCounterTiming` evidence; they do not alter the frozen `placementCalibration` record.
- Offline placement rescoring continues through the product classifier and persistence APIs.
- Player behavior remains untouched: no `src/` file and no Keynote `main.js` was edited.
- **No deviation from §11 was required.**

## Verification

Commands were run from the requested worktree.

1. Focused review rows:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement DSK binds timing past prior-slide decoders and enforces directed #t=5 time/frame deltas]' 'tests/test_dissolve_probe.py::test_dissolve_scorer[legacy non-DSK evidence may omit freeze draws]' tests/test_managed_obs_qualify.py::test_placement_capture_retries_only_for_sole_coverage_shortage_and_scores_every_saved_attempt 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[ownership-error-does-not-mask-isolation-failure]' 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[ownership-error-does-not-mask-program-failure]' -q -p no:cacheprovider`

   Result: **5 passed, 0 skipped, 0 failed, 0 errors** in 6.68 s.

2. First required targeted run:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

   Result: **510 passed, 1 skipped, 0 failed, 0 errors** in 102.19 s.

3. Focused full-size-draw disagreement regression:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement DSK binds timing past prior-slide decoders and enforces directed #t=5 time/frame deltas]' -q -p no:cacheprovider`

   Result: **1 passed, 0 skipped, 0 failed, 0 errors** in 2.91 s.

4. Final required targeted run:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

   Result: **510 passed, 1 skipped, 0 failed, 0 errors** in 104.20 s.

5. `git diff --check`: **PASS**, no output.

The single skip is the existing environment-dependent skip in the authorized targeted files. The three named external census reds were not run because they are outside W6's permitted test files.

## Open items for the coordinator

- Run live OBS/Chrome placement qualification and the coordinator's cross-stream/full suites; this W6 brief prohibited live runs and the full suite.
- Review W3's final `managed_obs.py` and owned tests with these scorer labels; W6 did not touch either file.
- The known external census reds remain unmodified and unassessed by W6.
