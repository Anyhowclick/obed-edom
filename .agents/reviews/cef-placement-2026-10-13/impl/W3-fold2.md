# W3 review round 2 fold

## Files changed

- `src/obed_edom/managed_obs.py`
- `tests/test_managed_obs.py`

No W3 change was required in `src/obed_edom/obs_websocket.py` or `tests/test_obs_websocket.py`. No other stream-owned file was edited.

## Finding dispositions

### Product R2-2 — folded

Cleanup now separates resource-cleanup failure from an observed isolation mismatch exactly as requested:

- An absence-poll request exception or timeout records an `absence-poll` cleanup error, leaves `cleanup_verified=False`, and leaves `isolation_ok=True`.
- A probe target that does not disappear within cleanup records a `target-cleanup` error, leaves `cleanup_verified=False`, and leaves `isolation_ok=True`.
- `isolation_ok=False` during cleanup is limited to an ambiguous reference proven to use this run's scene UUID, an observed program-scene change after this run mutated OBS, or restored-state readback differing after this run mutated OBS.
- Runs that installed no scene, input, or reference skip the input/scene/item absence loop and probe-target disappearance wait. This covers both a collision found in the pre-install snapshot and a `CreateScene` collision that occurs after the snapshot. The latter still restores the Studio/preview mutation but does not inspect or remove the newly occupied unowned scene name.
- `_CalibrationInstall` now retains the created scene UUID and whether this run changed Studio Mode. Cleanup resolves UUIDs after transport-ambiguous create requests, removes only identities attributable to this run, and polls source UUID, scene UUID, and scene-item ID. Same-name rows with different UUIDs are ignored rather than classified as this run's leftovers.

The existing parameterized transaction test gained five rows and no new test function:

- cleanup `GetInputList` timeout → cleanup failed, isolation remains valid;
- slow target disappearance → cleanup failed, isolation remains valid;
- precheck collision → no cleanup enumeration/target wait, refusal without isolation failure;
- collision arising at `CreateScene` after the precheck → Studio restored, no absence poll/target wait, refusal without isolation failure;
- unrelated same-name input/scene with different UUIDs after removal → cleanup succeeds.

### Probe review R2 recording-FPS finding — confirmed, no W3 edit

The review cites `managed_obs.py:49`, but its requested correction is entirely in W6-owned qualification callers. The verified W3 anchor is `RATES = {25: ("25 PAL", 50), 30: ("30", 60)}`: tuple element 1 is intentionally the managed browser-source FPS, and W3 validates and seeds the browser source with it. Changing that mapping would violate the frozen source-FPS contract. The recording analyzer and flash-control callers must pass the canvas rate (`ctx["rate"]`) or decoded recording metadata as the reviewer specifies; W3 did not edit those files.

No other r2 finding cites `managed_obs.py`, `obs_websocket.py`, `tests/test_managed_obs.py`, or `tests/test_obs_websocket.py` as a change site. Mentions of W3 in probe M2/M3/L5 explicitly prescribe W6 harness ordering/proxies rather than a W3 API change.

## Verification

New cleanup/collision rows:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py::test_calibration_transaction_preview_offcanvas_faults_and_fencing -q -n 2 -p no:cacheprovider -k 'collision or cleanup or target or unowned'
7 passed in 0.57s
```

Complete transaction table:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py::test_calibration_transaction_preview_offcanvas_faults_and_fencing -q -n 2 -p no:cacheprovider
26 passed in 0.41s
```

Focused W3 contract selection:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider -k 'persistence_contract or calibration_transaction or request_before_connect'
28 passed in 0.43s
```

Syntax, whitespace, and Ruff checks passed with no output:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
git diff --check -- src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
.venv/bin/ruff check src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
```

Required full targeted command:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider
113 failed, 50 passed in 5.05s
```

The 113 failures are the same environment limitations documented in both earlier W3 rounds: 112 socket-backed cases cannot bind `127.0.0.1:0` in this sandbox and fail with `PermissionError: [Errno 1] Operation not permitted`; the existing macOS real-process test receives `None` instead of `False` when inspecting a reaped PID. All changed no-socket W3 rows pass.

## Coordinator open items

- W6 must fold probe R2's recording/flash FPS fix at the qualification call sites; `managed_obs.RATES` must remain the source-FPS mapping.
- Re-run the exact two-file suite in an environment that permits loopback binds and normal macOS process inspection.
