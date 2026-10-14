# W6 live5 fold implementation report

## Result

Implemented all four W6 changes in the four owned files. The targeted suite is green: 505 passed, 1 skipped. No OBS, Chrome, Keynote, full suite, run-gates, commit, stash, reset, checkout, rebase, or files outside the W6 stream were touched.

The A30 retained evidence proves the new frozen-region control wiring (`m-fg-cef` PASS with spreads 1.9103, 2.0021, 2.3440, 3.0028; `m-hold-cef` FAIL). A full aggregate A30 re-score cannot also PASS under item 1's mandatory missing-field rule: A30 predates both `expectedDisplayTime` and `freezeDrawAt`, so `m-snap-cef-dsk` is correctly INCONCLUSIVE and the aggregate fails closed. This is an explicit conflict between brief items 1 and 4, not a silent redesign; details are under Deviations.

## Files changed

- `scripts/dissolve_probe.py`
  - DSK rVFC/draw instrumentation, expected-display frame selection, schema compatibility, capture coverage helper, and frozen-region control wiring.
- `scripts/managed_obs_qualify.py`
  - Bounded DSK recapture, attempt records, and ownership-abort isolation labeling.
- `tests/test_dissolve_probe.py`
  - Late-callback A25/B25 shapes, stale-holder negative, missing-field negatives, and `m-fg-cef` control coverage.
- `tests/test_managed_obs_qualify.py`
  - Two-attempt success, three-attempt fail-closed bound, and ownership-abort offline scoring.

## Contract-item mapping

### 1. DSK frame identity

- `scripts/dissolve_probe.py:568-571` adds `expectedDisplayTime` to every rVFC row while preserving `rvAt`.
- `scripts/dissolve_probe.py:586-595` wraps `CanvasRenderingContext2D.drawImage` in the harness only and records the first per-video draw into the disconnected, id-less freeze canvas as `freezeDrawAt`. No product hook or `src/` edit was required.
- `scripts/dissolve_probe.py:3209-3223` validates the four-field rVFC rows, matching `rvAt`, monotone expected-display times, and selects the latest row whose `expectedDisplayTime <= freezeDrawAt`. `rvAt - freezeDrawAt` is retained as `callbackLatenessMs`; it is not used as the visibility clock.
- `scripts/dissolve_probe.py:3288-3294` records the selected media frame and timing diagnostic in `dskCounterTiming`.
- `scripts/dissolve_probe.py:3369-3388` uses the selected expected-display row for exact holder equality. Missing expected-display/draw evidence is INCONCLUSIVE. No frame tolerance was added.
- `tests/test_dissolve_probe.py:1185-1218` covers late callbacks after the draw (PASS), a genuine N holder versus N+1-at-draw stale holder (FAIL), and missing `expectedDisplayTime`/`freezeDrawAt` (INCONCLUSIVE).

### 1b. DSK coverage

- `scripts/dissolve_probe.py:3176-3186` derives strict mid-window coverage without changing the 0.05/0.95 boundaries or five-frame minimum.
- `scripts/managed_obs_qualify.py:2068-2083` runs only `counter_strip == "distinct"` (the DSK arm) up to three total attempts in the same host/OBS launch, stops on `midFrames >= 5`, and records every attempt's number, fitted rows, problems, and shot timing metadata in `captureAttempts`.
- `scripts/managed_obs_qualify.py:2163-2179` integrates the bounded loop into the existing placement session. If all three attempts have four frames, the final ordinary scorer still sees `< 5` and fails closed.
- `tests/test_managed_obs_qualify.py:118-133` covers 4→5 success on the first retry and persistent four-frame coverage stopping after exactly three attempts.

### 2b. Ownership-abort scorer label

- `scripts/managed_obs_qualify.py:481-518` recognizes only the exact ownership-verification abort when classifier input is absent and isolation, cleanup, restoration, and Program guard remain good. The selected `iso-obs-*` gate becomes INCONCLUSIVE; other errors or isolation/cleanup/restore/Program failures remain FAIL. The overall result therefore cannot PASS.
- `tests/test_managed_obs_qualify.py:1689-1694,1732-1735,1773-1782` covers the retained B25 shape and asserts `iso-obs-preview == INCONCLUSIVE` and aggregate INCONCLUSIVE.

### 3. `frozen_region` control

- `scripts/dissolve_probe.py:448-449` gives `m-fg-cef` an explicit `frozen_region: PASS` contract.
- `scripts/dissolve_probe.py:2732` replaces `m-snap-cef` with `m-fg-cef` as the positive control; `m-hold-cef` remains the FAIL control.
- `tests/test_dissolve_probe.py:1485-1486,1763-1769` verifies both the actual synthetic PASS and the profile wiring.
- Retained A30 direct scorer result: `m-fg-cef MATCH / frozen_region PASS`, spreads `[1.91033935546875, 2.00213623046875, 2.3439674377441406, 3.002777099609375]`; `m-hold-cef MATCH / frozen_region FAIL`.

## Frozen-contract compliance and deviations

- §11.6 `placementCalibration` was not changed. The new rVFC and freeze-draw values are additive fields in the existing dissolve `dump`/`dskCounterTiming`, as the brief permits.
- No player file was edited on disk. The timestamp observation is an in-memory harness wrapper around `drawImage`; production `live_runtime.py` is untouched.
- No five-frame threshold or mid-window boundary was relaxed.
- No ownership mismatch or `gone` observation is accepted or retried by this stream; W6 only corrects the offline label for the exact already-aborted ownership-verification shape.
- A30 conflict: item 1 says missing `expectedDisplayTime` or per-video draw time must be INCONCLUSIVE. The binding diagnosis states A30 omitted `expectedDisplayTime`, and the retained A30 record also has no `freezeDrawAt`. Item 4 simultaneously asks the same retained A30 aggregate to PASS. Both cannot be true. The nearest faithful implementation keeps item 1 fail-closed. On the APFS clone, the aggregate result is `FAIL`, with `m-snap-cef-dsk` INCONCLUSIVE and 28 other arms MATCH; the frozen-region control itself is proven PASS above. Synthesizing either timestamp from `presentationTime`, `detach`, or `rvAt` would recreate the diagnosed race and violate item 1.

## Verification

Commands were run from the requested worktree.

1. Initial targeted run after implementation:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

   Result: 503 passed, 1 skipped, 1 failed. The failure exposed `_dsk_first_rvfc_times` still accepting only legacy three-field rows; fixed to accept both legacy three-field and new four-field records.

2. Focused regression:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement DSK binds timing past prior-slide decoders and enforces directed #t=5 time/frame deltas]' -q -p no:cacheprovider`

   Result: 1 passed.

3. Focused ownership/coverage/control checks:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs_qualify.py::test_dissolve_sessions_are_the_p2_crossfade_cut_and_opaque_arms_plus_cef_skip 'tests/test_managed_obs_qualify.py::test_placement_record_round_trip_and_offline_gates[ownership-abort]' 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement CEF profile reports inherited cut and identity-tone rows]' -q -p no:cacheprovider`

   Result: 3 passed.

4. Final required targeted run:

   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`

   Result: 505 passed, 1 skipped, 0 failed in 100.12 s.

5. A30 clone and offline checks:

   - Clone: `cp -cR <live5/out> /private/tmp/w6-a30.uag7ZM/out`.
   - `--score` completed without OBS against the cloned A30 shot directory and wrote `placement-rescore-20261014-184221.json`.
   - Direct retained-evidence scorer: `m-fg-cef` frozen-region PASS; `m-hold-cef` frozen-region FAIL.
   - Full current aggregate: FAIL solely through the legacy DSK arm's newly mandatory missing timing evidence; 28 MATCH, 1 INCONCLUSIVE. This is the documented item-1/item-4 conflict above.

`git diff --check` passes. The three known external reds listed in the brief were not run and were not touched.

## Open items for coordinator

- Accept the documented A30 contract conflict or explicitly authorize a legacy-evidence exception. A legacy fallback is not implemented because it would violate “Missing fields → INCONCLUSIVE” and would reuse the racy clock this fold removes.
- Fresh live placement qualification is still required for item 1 and item 1b: retained A25/B25/A30 evidence cannot acquire the missing expected-display/draw timestamps or demonstrate the new bounded recapture loop.
- W3 owns the separate managed-OBS unknown-ownership retry. This stream only supplies the required scorer label once such a transaction abort is recorded.
