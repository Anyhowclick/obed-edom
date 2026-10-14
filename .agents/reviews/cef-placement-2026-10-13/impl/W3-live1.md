# W3 live-run product-fix report

## Root cause

The live `startup-offcanvas-on`, `failed-offcanvas-on`, and `opaque-off` transactions reached a valid isolated placement but performed one `GetSourceActive` read before OBS had finished activating the browser source. Each transaction therefore returned the existing `_CalibrationIsolationViolation` with clean Program, cleanup, and restoration evidence and no captures. The cited `opaque-off` artifact used `placementCalibration.placement: "offcanvas"`; it hit the same race as the two named off-canvas lifecycle controls.

Preview had the same one-read implementation. Its required settled state differs from off-canvas (`videoActive=false`, `videoShowing=true` rather than both true), but it had the same activation-settle exposure.

## Fix

- Added `ManagedObs._await_calibration_active()` in `src/obed_edom/managed_obs.py`.
- The common isolation verifier now polls `GetSourceActive` at the engine's existing poll interval and within the existing calibration transaction deadline.
- Off-canvas still requires `videoActive=true` and `videoShowing=true`; preview still requires `videoActive=false` and `videoShowing=true`.
- A source that never reaches its placement-specific state produces the unchanged isolation failure text, including when the transaction deadline is reached. It is not reported as a generic calibration timeout.
- Transition/cursor, DeckLink output, Program identity, canvas, CDP target, source identity/geometry, audio, preview scene, Program scene graph, off-canvas transform, cleanup, persistence, and restoration checks are unchanged and remain around the bounded settle.

## Tests added

Extended the existing `test_calibration_transaction_preview_offcanvas_faults_and_fencing` parameter matrix in `tests/test_managed_obs.py` without adding another test function:

- Late activation succeeds after three `GetSourceActive` reads for preview.
- Late activation succeeds after three reads for off-canvas.
- A never-showing preview source polls more than once, returns the exact existing isolation error rather than `timeout:`, and still cleans up/restores.
- A never-active off-canvas source has the same bounded failure and cleanup/restore behavior.

The calibration fake now supports delayed and permanently absent activation. Its matrix engine uses the existing `FakeClock`, so the 15-second deadline path is deterministic and does not wait in wall-clock time.

## Verification

- `git diff --check -- src/obed_edom/managed_obs.py tests/test_managed_obs.py`: PASS.
- Pytest was not run, as explicitly directed because another session holds the machine.
- OBS, Chrome, and Keynote were not started.

Coordinator test command when the machine is available:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider
```

## Files changed

- `src/obed_edom/managed_obs.py`
- `tests/test_managed_obs.py`

No `obs_websocket.py` change was required.

## Coordinator-test follow-up

### Root cause

The failing `obs.active_reads == 3` assertion counted all transaction-wide `GetSourceActive` requests as activation polling. The actual successful late-activation sequence is:

1. Three reads from the installation-time settle loop: two inactive/not-showing responses followed by the first placement-correct active/showing response.
2. One independent pre-screenshot isolation recheck in `_CalibrationIO.capture_png()`.
3. One independent post-screenshot isolation recheck in `_CalibrationIO.capture_png()`.

`CalibrationIO.check_current()` only checks cancellation, deadline, engine generation, and readiness; it does not send `GetSourceActive`.

The two capture-time reads are intentional isolation guards, so the fragile total-read assertion was wrong. The initial implementation also routed those later guards through the polling helper; that was broader tolerance than the requested startup settle.

### Fix

- `_verify_calibration_isolation(..., settle_active=True)` is now used only by the installation verification. It performs the bounded activation poll.
- Capture-time calls retain the default `settle_active=False` and perform one immediate fail-fast active/showing read each, preserving the original guard semantics.
- The fake records every returned active/showing state.
- The late-activation assertions now prove that the first placement-correct result is read 3, that four reads occur before the screenshot (three settle reads plus the pre-capture guard), that one occurs after it (the post-capture guard), and that every result from the first settled response onward remains placement-correct.

### Verification

Authorized command before the follow-up fix:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider
```

- 50 passed, 106 failed.
- The two new late-activation rows failed on the fragile total-read assertion; the other 104 failures were the existing restricted-environment failures.

The same authorized command after the follow-up fix:

- 52 passed, 104 failed.
- Both late-activation rows now pass.
- The remaining failures are unchanged: 103 loopback-bind `PermissionError` failures in this sandbox and the pre-existing `test_appkit_env_marker_on_real_processes` host-process assertion.
- `git diff --check -- src/obed_edom/managed_obs.py tests/test_managed_obs.py`: PASS.
