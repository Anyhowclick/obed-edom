# W3 live pass 2: off-canvas activation

## Root cause

The failing live transactions exhaust the activation-settle deadline because the managed off-canvas sequence enters Studio Mode before creating and enabling the nested Program reference. That is the material sequence difference from the successful step-0 off-canvas measurement.

Evidence:

- `opaque-off/record.json` records placement `offcanvas`, `started_s=98516.439217083`, `finished_s=98531.613857083`, `isolation_ok=false`, `cleanup_verified=true`, and `restored=true`, with the sole error `Calibration source is not active in the selected isolated placement.` The 15.17464-second span shows that the new bounded activation poll ran to the transaction deadline; this was not an immediate-read race or a later capture recheck.
- `startup-offcanvas-on` and `failed-offcanvas-on` report the same isolation error in their host logs. Every preview transaction passed.
- Step 0 starts with `studioModeEnabled=false` and never calls `SetStudioModeEnabled` in its off-canvas branch. It creates `AK-Calibrate`, creates `AK-Probe` inside it, creates a disabled `AK-Calibrate` scene item in `AK`, sets and reads back `positionX=2048`, enables that item, and then gets `videoActive=true, videoShowing=true` from `GetSourceActive({"sourceName":"AK-Probe"})`.
- Before this fix, `ManagedObs._install_calibration` enabled Studio Mode for both placements before `CreateScene`. The live profile and step-0 profile have `SceneDuplicationMode=true`, so the observed consequence is that the managed nested mutation did not activate `AK-Probe` in the actual Program graph. Step 0's otherwise equivalent mutation with Studio Mode off did activate it.

The remaining sequence and readback contracts already match step 0 and were not the cause:

- Both paths query source name `AK-Probe`; `GetSourceActive` has no UUID form. Managed OBS additionally pins the returned `inputUuid` and `sceneUuid` through `GetInputList`/`GetSceneList` before activation.
- Both use scene `AK`, nested source `AK-Calibrate`, a disabled create, transform readback at x=2048, and then enable the returned scene-item id.
- Managed OBS expects `(videoActive, videoShowing) == (true, true)` for off-canvas, matching step 0. Preview expects `(false, true)` and passed live.
- Managed OBS verifies the current Program name and UUID before the activation poll. The live transaction reached that poll and its Program-wire result remained good, excluding a Program-scene switch.
- The browser input dimensions, fps, `fps_custom`, `shutdown`, and `reroute_audio` match. Managed OBS's extra `restart_when_active=false` and audio isolation are shared by passing preview transactions, so they do not discriminate the failures.

## Fix

### `src/obed_edom/managed_obs.py`

- `_install_calibration` now treats Studio Mode as placement-specific:
  - preview: enable it when initially off, unchanged from the passing path;
  - off-canvas: leave it off, matching step 0; if it was initially on, temporarily disable it before creating the calibration scene and Program reference.
- Cleanup now disables and removes the off-canvas Program reference before restoring an initially enabled Studio Mode. It then restores the captured preview scene and preserves the existing final Studio, preview, Program, scene-graph, absence, identity, audio, transform, target, and persistence readbacks.
- The source-active settle loop, expected tuples, Program verification, transform verification, audio isolation, identity checks, and cleanup checks are unchanged.

### `tests/test_managed_obs.py`

- The existing `CalibrationObs` fake now distinguishes an off-canvas reference enabled against the real Program graph from one enabled while Studio Mode is active. This makes the fake reproduce the live failure instead of reporting the source active merely because an enabled item appeared in a list.
- Added `offcanvas / initial Studio Mode on / success` to the existing calibration matrix.
- Existing off-canvas success rows now assert the exact sequencing that would have caught the bug:
  - initial Studio off: no Studio Mode mutation at all;
  - initial Studio on: Studio off before create, Program reference removed before Studio on, original preview restored.
- Existing late-activation and never-active rows continue to cover bounded source-active settling.

No changes were needed in `src/obed_edom/obs_websocket.py` or `tests/test_obs_websocket.py`.

## Verification

- `git diff --check -- src/obed_edom/managed_obs.py tests/test_managed_obs.py`: passed.
- Authorized command: `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider`
  - Result: **53 passed, 104 failed** in 5.32s.
  - All 31 parameterized calibration transaction cases passed, including the added off-canvas/Studio-on case and both late-activation cases; none appears in the failure summary.
  - The failures are environment-limited permission failures. The repeated cause is the unrelated `Rig` fixture trying to bind its fake CDP/WebSocket server to `127.0.0.1:0`: `PermissionError: [Errno 1] Operation not permitted`; the platform process-probe test is also listed by the restricted run. No calibration transaction case or product assertion appears in the failure summary.

## Coordinator open item

- Re-run `tests/test_managed_obs.py` in the coordinator environment where localhost test sockets are permitted, then run the off-canvas live qualification. The expected live discriminator is that off-canvas no longer sends `SetStudioModeEnabled(true)` before `CreateSceneItem`, and `GetSourceActive(AK-Probe)` settles at `true/true` as in step 0.
