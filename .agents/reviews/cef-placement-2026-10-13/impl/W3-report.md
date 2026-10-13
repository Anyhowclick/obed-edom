# W3 OBS implementation report

## Files changed

- `src/obed_edom/managed_obs.py`
- `src/obed_edom/obs_websocket.py`
- `tests/test_managed_obs.py`
- `tests/test_obs_websocket.py`

No other stream-owned file was edited by W3. No commit, stash, reset, checkout, rebase, OBS, Chrome, Keynote, full-suite, or gate run was performed.

## Contract mapping

- §11.2 adapter and execution boundary: `ManagedObs.calibration_adapter()` returns a stable adapter. `start()` validates the ready owned `EngineIdentity`, program target/context binding, connection generation, loopback run URL, placement, geometry, DPR, and source FPS before starting a dedicated calibration thread. It rejects concurrent runs with the frozen error text. Calibration never enters the engine `_submit` queue. Measurement and cleanup use calibration-owned WebSocket connections with a 16 MiB message limit and per-request deadlines capped by the transaction budget.
- Generation/cancellation fencing: ready/forgotten-engine transitions advance `_ready_generation`; every mutation/capture checks cancellation, deadline, current run identity, ready generation, and process ownership before and after the request. Quit, restart, setup, reset-page, shutdown, close, and observed engine exit signal cancellation; engine replacement paths drain cleanup before changing or touching the replacement engine. `cancel()` is bounded to five seconds and is idempotent for completed/absent runs.
- Guard/result lifecycle: the worker calls `begin`, all six frozen `sample` phases, measurement, exhaustive cleanup/restore, and `finish`, and resolves `Future[CalibrationResult]` only afterward. Measurement exceptions, guard exceptions, and cleanup errors become failed result evidence instead of escaping the worker.
- Exact prechecks: pinned names/constants are used. Transition must be `Cut`/`cut_transition`; cursor must be exactly inactive (`1.0`). Preview output accepts only `outputActive:false` or the measured `GetOutputStatus` code-600 response with its exact comment. Preview-scene absence accepts only `GetCurrentPreviewScene` code 506 with null comment while Studio Mode is off; the same response while on fails. There is no generic code-600 handling.
- Preview placement: snapshots program UUID/name, Studio state, retained preview UUID/name, canvas/video settings, and the full ordered program scene-item records. When Studio Mode starts off, it is enabled and its retained preview is captured before selecting `AK-Calibrate`. The program identity and graph remain unchanged; the probe is verified as `videoActive:false` and `videoShowing:true`.
- Harness-only off-canvas placement: creates the nested `AK-Calibrate` reference disabled, positions it at canvas width + 128, reads back the complete identity transform/crop/bounds/source geometry and proves disjointness, then enables it. The enabled probe must read back active/showing and the original ordered program graph must remain unchanged.
- Probe isolation/binding: creates exactly one owned scene/input after collision checks; reads back scene/input UUIDs, browser URL/size/FPS/custom FPS, empty filters, muted audio, disabled tracks 1–6, and monitoring off. Exact-URL CDP discovery must produce one non-program target; returned evidence must retain the installed source UUID, discovered target ID, run ID, connection generation, DPR, and original request spec.
- Capture: rechecks program scene, transition/cursor, preview output, canvas, program target, exact probe target, source UUID/settings/audio, placement state, program graph, and off-canvas transform before and after each raw source PNG. Malformed base64 or a non-PNG result fails isolation.
- Cleanup/restoration: uses a fresh bounded connection, disables an off-canvas reference first, resolves an uncertain created reference when possible, restores the saved preview before disabling Studio Mode, removes the reference/input/scene, continues after errors, accepts only the two frozen measured already-absent responses, polls input/scene/item enumerations plus CDP target disappearance, directly restores program only while ownership/generation remains established, and reads back Studio/preview/program/items. Creation attempts are recorded before their requests so transport ambiguity still enters cleanup.
- O5 persistence: `read_collection()` parses and normalizes sources by stable names without dropping fields. `persistence_allowlist()` canonicalizes only cross-launch original source UUID references. `STEP0_NULL_ALLOWLIST` pins the exact 16 measured before→after transitions from the supplied null evidence. `check_persistence()` allows only those exact transitions plus monotonic `id_counter` growth on an original scene, preserves item membership/order/transforms, makes cleanup authoritative only when file mtime is later than the wall-clock final-removal acknowledgement, and makes quit authoritative unconditionally. Missing/malformed collection files raise a typed failure. Backups remain untouched.
- WebSocket capability: mutating calls use the existing request path. Existing callers retain the 4 MiB/default timeout behavior; calibration opts into 16 MiB. Optional request timeout is never permitted to exceed the connection default.
- Conditional Scene Duplication setting: `SceneDuplicationMode` remains unseeded, matching §2.2's conditional and the step-0 outcome; tests pin that omission. `write_tree()` also remains non-mutating toward `AK.json.bak`.

## Deviations from frozen contracts

None identified. The implementation retains the frozen §11.2 public records/protocol signatures and exact measured OBS error strings. The adapter implements the cleanup checkpoint; the authoritative post-quit snapshot remains the frozen W6 responsibility and is supported through `check_persistence(..., phase="quit")`.

## Tests

Contract-focused tests, using the existing fake launcher/OBS patterns and no local sockets:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider -k 'render_tree or write_tree or persistence_contract or calibration_transaction or request_before_connect'
28 passed in 0.76s
```

This table-driven coverage includes preview with Studio initially off/on, off-canvas mutation order and transform readback, inactive/absent preview output, exact and delayed removals, wrong removal errors, malformed screenshots, mismatched source and target evidence, program disturbance/restoration, transition-in-flight rejection, preview 506 rejection while Studio is on, stale engine identity, direct cancellation, quit/restart/setup fencing, own-WebSocket connection count, no engine queue use, idempotent cancel, exact persistence allowlist derivation/checking, leftover rejection, non-authoritative cleanup, and malformed collections.

Syntax and whitespace verification:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
git diff --check -- src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
Both passed with no output.
```

Required full targeted command:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider
113 failed, 43 passed in 4.43s
```

The 113 failures are environment reds, not contract assertions: 112 socket-backed fake-server cases cannot bind `127.0.0.1:0` in this sandbox and raise `PermissionError: [Errno 1] Operation not permitted`; the remaining pre-existing real-process AppKit check expects a reaped PID to return `False`, but this sandbox returns `None` from `env_marker` (`test_appkit_env_marker_on_real_processes`). Running that AppKit case alone produced `1 failed in 0.19s`. The user-listed main-checkout external reds were not run because they are outside the assigned targeted files.

## Open items for the coordinator

- Re-run the exact two-file command in an environment that permits loopback binds and normal process inspection.
- W6 should take and retain the authoritative clean-quit persistence snapshot, run the real configured-device preview-output field test, and execute the OBS/CEF qualification gates. Those were explicitly outside W3's permitted runs.
- Integrate W4's guard/measurement implementation with this adapter and discard any result that does not meet W4's full grant predicate.
