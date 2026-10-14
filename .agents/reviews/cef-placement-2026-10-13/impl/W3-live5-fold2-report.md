# W3 live5 fold 2 implementation report

## Outcome

D1 product-side ownership handling is fixed. If calibration ownership remains `unknown` until the calibration deadline, the transaction now fails closed with the exact shared error `ManagedObsError("Calibration engine ownership could not be verified.")` instead of `_CalibrationTimeout`. A transient `unknown` followed by `ours` still proceeds, and a deadline reached before any ownership observation remains a timeout.

## Finding fix and files

- D1 — `src/obed_edom/managed_obs.py:851-868`: `_calibration_verify_ownership` retains the last ownership observation. When `_calibration_check_current` reports the deadline and the last observation was `unknown`, it raises the exact ownership-verification `ManagedObsError`. Cancellation and generation fencing still run through `_calibration_check_current`; known non-owned states still fail immediately. The existing bounded 100 ms retry is at `src/obed_edom/managed_obs.py:362` and `:867`.
- D1 regression — `tests/test_managed_obs.py:2246-2247,2379-2392`: the existing parameterized matrix covers transient unknown, persistent unknown, and gone ownership. The persistent-unknown row now requires the exact `refused: ManagedObsError: Calibration engine ownership could not be verified.` result while continuing to prove repeated unknown observations, no scene/input mutation, and failed cleanup/restoration.

## Frozen-contract mapping

- §11.2 `check_current`/ownership/deadline fail-closed contract maps to `_calibration_verify_ownership` at `src/obed_edom/managed_obs.py:851-868`.
- The exact cross-stream ownership message required by live5 D1 is emitted at `src/obed_edom/managed_obs.py:859` and `:866`; W6 can classify both persistent-unknown and known-not-ours failures identically.
- The existing transaction matrix remains the §6 single parameterized OBS transaction/fault table; no new test function was added.

No deviation from §11 was required.

## Tests

- Red-capable regression before the product patch:
  `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider -k 'ownership and unknown'`
  — **1 passed, 1 failed**. Persistent unknown still returned `_CalibrationTimeout`, matching D1.
- Same regression after the product patch:
  `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider -k 'ownership and unknown'`
  — **2 passed, 0 failed**.
- Socket-free calibration/persistence subset:
  `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider -k 'persistence_contract or calibration_transaction'`
  — **35 passed, 0 failed**.
- Required full target file:
  `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_managed_obs.py -q -n 2 -p no:cacheprovider`
  — **56 passed, 104 failed**. Of the 104 sandbox-only failures, 103 are `PermissionError: [Errno 1] Operation not permitted` while binding the fake CDP server to `127.0.0.1:0`; the remaining failure is the macOS process-environment test receiving `None` from sandbox-restricted `ps -E`. The socket-free calibration subset above is fully green.
- `git diff --check -- src/obed_edom/managed_obs.py tests/test_managed_obs.py` — **passed**.

## Coordinator open items

- Re-run the full `tests/test_managed_obs.py` command in an environment that permits loopback binding and process-environment inspection.
- W6 should consume the exact message `Calibration engine ownership could not be verified.` for its D1 evidence label, as assigned in the live5 brief.
- No known external census failures were exercised by this W3-only test scope.
