# W3 review round 1 fold

## Files changed

- `src/obed_edom/managed_obs.py`
- `tests/test_managed_obs.py`

No W3 change was required in `src/obed_edom/obs_websocket.py` or `tests/test_obs_websocket.py`. No other stream-owned file was edited.

## Finding dispositions

### Product review #1, W3 side — folded

`CalibrationResult.isolation_ok` now starts true and becomes false only for a typed post-mutation isolation or identity mismatch. The blanket `capture_png()` exception handler that converted screenshot errors, request timeouts, and cancellation into isolation failures was removed.

The transaction now records distinct error prefixes:

- `refused:` for pre-install state refusals, including a bad preview-output response, transition in flight, and unreadable preview state;
- `cancelled:` for cancellation;
- `timeout:` for transaction and WebSocket request timeouts;
- `isolation:` only for observed post-mutation state/identity mismatches;
- `calibration:` for other post-install failures.

Source/scene UUID, settings/audio/filter, target, canvas, program, preview, program-graph, active/showing, off-canvas transform, and evidence-binding comparison failures use the typed isolation path. Cleanup separately records program/restoration/resource readback mismatches as isolation violations while still distinguishing a successfully restored transient program change from failed cleanup. Pre-install refusal, malformed screenshot, timeout, wrong removal response, and cancellation retain `isolation_ok=True`.

The existing parametrized transaction test gained timeout and cleanup-only program-disturbance rows without adding a test function. It now pins the requested refusal/cancellation/timeout/isolation categories and verifies that only evidence/source/target, program, or cleanup-state mismatches set `isolation_ok=False`.

The review's `_complete_probe` ordering and host suppression rows are in W4-owned `live_host.py`/`test_live_host.py`; W3 did not edit them. W4 must evaluate `program.ok is False` and `isolation_ok is False` before the missing-evidence branch.

### Product review #11 — folded

`CalibrationAdapter.identity()` now returns the ready engine's lock-protected pid/launch-date/generation tuple without launching a process probe; ordinary engine liveness remains responsible for process re-verification.

Every OBS request still checks cancellation, deadline, current run, ready state, pid, launch date, and ready generation before and after the request, but no longer executes `_identity()`/`ps` there. Process ownership is verified exactly at the requested phase boundaries:

- once after the read-only snapshot and immediately before the first mutation;
- once before every `capture_png()` batch;
- once before cleanup mutations, with cancellation ignored only for cleanup.

The transaction table wraps `_identity()` and proves `identity()` performs zero process probes and a successful one-capture transaction performs exactly three phase-boundary ownership probes instead of two probes per WebSocket request.

### Product review #14 — W3 side not applicable

The cited fail-open target URL, FPS duplication, and image conversion order are all in W4-owned `live_host.py`. The requested FPS source is `managed_obs.RATES`, but no change to `managed_obs.py` is needed. W3 made no cross-stream edit.

### Product review #15 — W3 side not applicable

Both dead fields are in W4-owned `live_host.py`; neither is defined or consumed by the W3 files.

### Product review #16 — W3 side not applicable

All cited weak rows are in W4-owned `tests/test_live_host.py`; no `test_managed_obs.py` or `test_obs_websocket.py` row is cited. W3 made no cross-stream edit.

### Probe review #14 — W3 coverage verified; W6 reporting remains external

The reviewer explicitly accepts fault injection in W3 unit tests. The single W3 transaction table covers cancellation, blocked/timeout capture, delayed deletion, stale generation, idempotent cancellation, and quit/restart/setup fencing; this fold adds explicit timeout and cleanup-readback isolation rows. The requested gate-detail/live-subset labelling is in W6-owned qualification scripts and cannot be changed in W3 files.

### Probe review #15 — not applicable to W3

This is W2 report/handover/manifest wording and metadata; it cites no W3 source or test.

### Probe review #16 — not applicable to W3

Every item cites W2/W6 placement-probe or dissolve-probe files and tests. It cites neither `managed_obs.py`, `obs_websocket.py`, nor their tests.

## Verification

The focused contract command passed:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider -k 'persistence_contract or calibration_transaction or request_before_connect'
23 passed in 0.57s
```

The expanded transaction table alone passed:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py::test_calibration_transaction_preview_offcanvas_faults_and_fencing -q -n 2 -p no:cacheprovider
21 passed in 0.61s
```

Syntax, diff whitespace, and Ruff checks passed with no output:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
git diff --check -- src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
.venv/bin/ruff check src/obed_edom/managed_obs.py src/obed_edom/obs_websocket.py tests/test_managed_obs.py tests/test_obs_websocket.py
```

The required full targeted command completed with:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py tests/test_obs_websocket.py -q -n 2 -p no:cacheprovider
113 failed, 45 passed in 5.22s
```

As in the initial W3 run, 112 failures occur before behavior assertions because this sandbox denies fake-server binds to `127.0.0.1:0` with `PermissionError: [Errno 1] Operation not permitted`. The remaining existing macOS process test sees `AppKitLauncher.env_marker()` return `None` rather than `False` for a reaped PID. All new/changed no-socket W3 rows pass.

## Coordinator open items

- W4 must fold the product #1 host ordering/suppression rows and product #14–#16 host-only work.
- W6 must label probe-review #14 gates as live subsets or REPORTED and include the W3 unit-test IDs in gate detail.
- Re-run the exact two-file suite where loopback binds and normal macOS process inspection are permitted.
