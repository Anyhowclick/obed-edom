# W6 live6 Chrome classifier fix

Date: 2026-10-14  
Worktree: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Branch/base supplied by coordinator: `claude/cef-obs-placement` at `f8059380`

## Outcome

Fixed the fold-4 regression in `placement_gates`: Chrome harness classifier rows now load and rescore each Chrome session's own `runDir/record.json`. Missing, unreadable, malformed, or incomplete Chrome evidence remains `INCONCLUSIVE` and therefore fails closed.

Both saved live6 25 fps takes rescore `PASS` through `placement_gates` on APFS clones. Both Chrome GPU/software classifier rows are `PASS`, every one of the 29 CEF placement arms is `MATCH`, and there are no failing enforced checks in either take.

## Files changed

- `scripts/managed_obs_qualify.py`
  - Replaced the Chrome classifier lookup through the CEF-only `runs` map with a direct read from each Chrome probe session's own `runDir/record.json`.
  - Calls the existing `score_placement_calibration(record["placementCalibration"], run_dir)` path.
  - Defaults to `INCONCLUSIVE` and preserves that result for missing `runDir`, missing/unreadable JSON, malformed records, decode errors, or missing gate output.
- `tests/test_managed_obs_qualify.py`
  - Extended the existing placement gate fixture with real serialized Chrome GPU and software calibration records.
  - Proves both valid records reach the scorer and produce `PASS` through `placement_gates`.
  - Proves a Chrome session whose record is missing reports classifier value `INCONCLUSIVE`, with an enforced failed check.

No other repository file was edited. The pre-existing untracked `.agents/reviews/cef-placement-2026-10-13/impl/live6-chrome-fix.md` was present before work began and was not touched.

## Contract mapping

- Plan §5, Harness classifier control: the GPU and software Chrome harness rows are rescored from their retained evidence rather than treated as product arms.
- Plan §5 fail-closed rule: missing or malformed evidence yields `INCONCLUSIVE`; it cannot satisfy the required `PASS` classifier check.
- Plan §11.6 offline evidence contract: the code reads `runs/<Chrome session>/record.json.placementCalibration` and calls the same `score_placement_calibration` API used for live records and offline rescoring.
- Plan §11.6 isolation boundary: Chrome remains harness-only. This change does not add Chrome to `dissolve_probe.ARMS`, product calibration, grants, or OBS ownership.
- Existing fold-4 CEF behavior remains intact: `run_paths`/`runs` stays restricted to dissolve arms for LUT and `score_runs`; only the two Chrome classifier checks use their separate session records.

## Root cause and regression signal

Fold 4 restricted `run_paths` and `runs` to names in `dissolve_probe.ARMS`. `probe-chrome-gpu` and `probe-chrome-software` are deliberately not dissolve arms, but their classifier loop still used `runs.get(name)`. It consequently passed `{}` into `score_placement_calibration`, producing `INCONCLUSIVE` despite valid records in the sessions' own run directories.

The regression fixture was written before the implementation change. On the original code path, the valid Chrome records still produced an overall placement gate `FAIL`:

```text
tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[cef-complete]
1 failed
AssertionError: assert 'FAIL' == 'PASS'
```

After the fix, the same node passes and the missing-record variant remains explicitly `INCONCLUSIVE`.

## Tests

Red-capable regression run before the implementation change:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[cef-complete]' -q -n 2 -p no:cacheprovider
```

Result: **1 failed**. A diagnostic rerun of the same node without `-q` also reported **1 failed** and exposed the assertion above.

Targeted regression run after the fix:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[cef-complete]' -q -n 2 -p no:cacheprovider
```

Result: **1 passed, 0 failed** in 12.17 s.

Required W6 file run:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

Result: **192 passed, 1 skipped, 0 failed** in 26.15 s.

Static cleanup checks:

```text
git diff --check -- scripts/managed_obs_qualify.py tests/test_managed_obs_qualify.py
rg -n '\[DEBUG-' scripts/managed_obs_qualify.py tests/test_managed_obs_qualify.py
```

Result: no whitespace errors and no temporary debug instrumentation.

The coordinator-listed external reds were not encountered because no other test file or live gate was run.

## Offline live6 rescore

The source evidence was cloned without changing the originals:

```text
cp -cR /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live6/out /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live6-rescore-fixed
```

An offline Python driver equivalent to `scratchpad/tools/rescore.py` loaded each take, replaced the embedded prefix

```text
/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live6/out
```

with

```text
/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live6-rescore-fixed
```

for every session `runDir`, then called `placement_gates(run, decision)` using:

```text
/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json
```

Results:

| Take | `CEF-placement` | Chrome GPU | Chrome software | CEF arms | Failing enforced checks |
|---|---|---|---|---|---|
| `placement-20261014-203501.json` | PASS | PASS | PASS | 29/29 MATCH | None |
| `placement-20261014-205740.json` | PASS | PASS | PASS | 29/29 MATCH | None |

Every failing check per take: **none**. No placement sub-gate returned `FAIL` or `INCONCLUSIVE` in either take. A focused independent call to `score_placement_calibration` against all four cloned Chrome records also returned overall `PASS` and `probe-chrome-harness: PASS`.

## Deviations from §11

None. The record schema and scorer APIs are unchanged. The fix restores the intended §11.6 evidence route and keeps missing evidence fail-closed.

## Open items for the coordinator

- Commit the two W6 files; this worker did not commit, stash, reset, checkout, or rebase.
- The APFS rescore clone remains at `scratchpad/live6-rescore-fixed` for audit and may be removed by the coordinator when no longer needed.
- No live OBS, Chrome, headless browser, or Keynote qualification was run, per the stream rules.
