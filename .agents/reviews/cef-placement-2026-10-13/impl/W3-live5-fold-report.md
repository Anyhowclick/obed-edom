# W3 live5 fold report

## Result

Implemented item 2a ownership-observation hardening in the managed OBS calibration path. Calibration now retries only the tri-state `unknown` observation with a 100 ms backoff bounded by the already-existing transaction or cleanup deadline. `ours` proceeds; `gone` and every other non-`unknown` observation fail immediately and are never accepted.

## Files changed and contract mapping

- `src/obed_edom/managed_obs.py:362`: added the private 100 ms calibration ownership retry interval.
- `src/obed_edom/managed_obs.py:851-861`: changed `_calibration_verify_ownership` to re-run the existing identity observer only for `unknown`, checking cancellation, generation, readiness, and the supplied existing deadline before every observation and after success. The sleep is clamped to the remaining deadline. This maps to frozen contract §11.2 `check_current` ownership/deadline behavior without changing any frozen record, protocol, error, adapter, or owner decision.
- `tests/test_managed_obs.py:2246-2247,2267-2285,2379-2391,2459-2463`: extended the existing parameterized calibration transaction matrix, adding no new test function. Coverage proves `unknown -> ours` succeeds after one short backoff, persistent `unknown` fails closed with `_CalibrationTimeout` at the existing deadline and performs no install mutation, and `gone` fails immediately without a retry inside either ownership-verification call or any install mutation.

Only the two W3-owned files were edited. No player file, Keynote `main.js`, plan, review, README, skill, commit, stash, reset, checkout, or rebase was touched.

## Frozen-contract deviations

None. The implementation preserves §11.2's existing transaction and cleanup deadlines and its fail-closed ownership requirement. Cleanup invokes its own separately contracted ownership verification, so a failed main-path observation is followed by one independent cleanup-path ownership check; neither invocation retries `gone`.

## Tests

Focused final calibration matrix:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider -k calibration_transaction_preview_offcanvas_faults_and_fencing
34 passed in 3.46s
```

Required complete targeted file:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider
56 passed, 104 failed in 17.93s
```

All 104 full-file failures are environment failures outside this change: the restricted runner rejects loopback socket binds used by the existing `FakeCdp`/websocket fixtures with `PermissionError: [Errno 1] Operation not permitted`; the existing real-process `AppKitLauncher.env_marker` test also cannot inspect `ps -E` in this sandbox and returns `None`. The socket-free calibration matrix, including all three new ownership rows, passes. `git diff --check -- src/obed_edom/managed_obs.py tests/test_managed_obs.py` passes.

The brief's listed external main-checkout reds were not exercised because only `tests/test_managed_obs.py` was permitted.

## W6 A30 re-score result

Not re-run by W3 because W6 owns the scorer files and this stream was restricted to `tests/test_managed_obs.py`. The binding W6 diagnosis reports its scratch-only in-memory A30 re-score as overall `PASS`, all 29 arms `MATCH`, `frozen_region PASS`, and no enforced non-PASS gate after assigning the positive control to `m-fg-cef`.

## Open items for the coordinator

- Re-run `tests/test_managed_obs.py` in an environment that permits the existing loopback fixtures and `ps -E`; the W3-specific socket-free matrix is green.
- Obtain fresh live B25/placement evidence to confirm the transient LaunchServices/`ps -E` `unknown -> ours` recovery in the real process environment. The retained failed run has no classifier input and cannot establish this offline.
- W6 should independently land and report the A30 scorer-control change; W3 made no W6-file changes.
