# W4 live-run product fixes

## Scope and files

- Changed `src/obed_edom/live_host.py`.
- Changed `tests/test_live_host.py`.
- Did not modify or commit the concurrently dirty W6 files `src/obed_edom/managed_obs.py` and `tests/test_managed_obs.py`.

## Root cause and evidence

### Program baseline instability

The failed-preview-off live artifact began recalibration before the visible Program cadence had settled:

- `failed-preview-off/placement/host-log.json` records `show` at `1791897434.623908` and `recalibrate` at `1791897434.73503`, only 111 ms later.
- `failed-preview-off/record.json` records a 20.0 ms pre-transaction baseline followed by a 33.400000000000546 ms maximum rAF gap. Its two playing videos also report approximately 20.91 ms maximum stall against approximately 12.49 ms observed frame intervals, so the old guard returned `program.ok=false` and the host rejected the run as `program-disturbed` with launch-scoped suppression.
- The prior guard accepted the first four-frame sample and used its median as the baseline. It did not require a stable cadence window, did not wait after a show/navigation, and mixed baseline telemetry into transaction telemetry. A normal CEF 50 Hz to 30 Hz settling transition could therefore be interpreted as transaction disturbance.

### Missing rejection detail

- The same record contains `errors: ["calibration: RuntimeError: injected capture failure after first capture"]`, while its `placementProbeRejected` host-log row contains only the generic `reason: "program-disturbed"` and no `errors` field.
- `_complete_probe` reduced completed results with null evidence or errors to `probe-failed`, and `_finish_probe_state` did not accept or log `CalibrationResult.errors`. This also hid the live replay's exact `Probe capture freshness could not be verified.` cause.

## Fix

### Stable pre-transaction guard baseline

- The Program guard now exposes raw rAF gaps during baseline acquisition and requires the latest six positive gaps to remain within 10% of their median.
- Acquisition re-samples for up to one second. If a show, slide navigation, initial browser navigation, document-context change, or managed-CDP reconnect just occurred, baseline acceptance is deferred until one second after that event, with an additional 350 ms acquisition allowance.
- Once a stable baseline is accepted, a new guard `arm` operation clears cadence, visibility, and media telemetry. The ensuing `finish` result therefore measures only the calibration transaction against the frozen stable baseline.
- A baseline that remains unstable returns `ProgramCheck.ok=None` with `program cadence baseline unstable`; missing cadence remains `ok=None` with `program cadence baseline unavailable`. `_complete_probe` maps either to unsuppressed `probe-failed`, so it grants nothing and does not disable automatic probes.
- A transaction max-rAF gap above two stable baseline periods, a visibility event, or a known media disturbance still returns `ok=False`; the existing `program-disturbed` rejection and launch suppression remain intact.

### Rejection observability

- `_finish_probe_state` now writes an `errors` array on every `placementProbeRejected` row.
- `_complete_probe` passes the completed result's exact `errors` tuple through that finishing path, including null-evidence and freshness failures.

## Tests added or extended

No new test function was added.

- Extended `test_program_guard_applies_program_liveness_thresholds` to cover mixed 20/33.4 ms cadence re-sampling, a recent-navigation/show not-before boundary, stable 33.4 ms acceptance, telemetry arming/reset, an indefinitely unstable baseline returning inconclusive, and a genuine 70 ms transaction gap returning failure after a stable baseline. The existing 40.1 ms row now expects failure because baseline collection and transaction measurement are no longer conflated.
- Extended `test_managed_probe_state_machine_renews_suppresses_and_stops` to verify the host passes its settle deadline into the guard; a completed null-evidence/inconclusive-program result remains `probe-failed` without automatic-probe suppression; and its `placementProbeRejected` row contains the exact `Probe capture freshness could not be verified.` error.

## Validation

- Pytest/OBS/Chrome/Keynote were not run, per the explicit live-machine restriction. Pytest count: 0 run, 0 passed, 0 failed.
- Parsed both changed Python files with `ast.parse`: passed.
- `git diff --check -- src/obed_edom/live_host.py tests/test_live_host.py`: passed.

## Coordinator open item

- Run the required targeted command when the live-machine lock is released: `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_host.py -q -n 2 -p no:cacheprovider`.

No contract deviation or cross-stream change is required.
