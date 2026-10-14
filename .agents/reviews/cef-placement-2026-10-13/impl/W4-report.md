# W4 host implementation report

## Files changed

- `src/obed_edom/live_host.py`
  - Added the frozen knowledge/probe placement channel modes, bounded probe leases, managed calibration state machine, Program CDP guard, separate probe CDP measurement, classifier commit checks, renewal/reconnect handling, expanded placement JSON, recalibrate execution, and bounded stop teardown.
  - Extended `_AssetServer` with one active run-scoped probe page/asset namespace and byte-range MP4 serving.
  - Made `ChromeCdp.call` include lock acquisition in its deadline and added non-navigating transport detach for managed reconnect.
- `tests/test_live_host.py`
  - Extended existing placement, server, CDP, and Node tamper tests.
  - Added three concentrated tests covering ProgramGuard thresholds, the managed state/renewal/reconnect/suppression/stop lifecycle, and construction of bound serial `ClassifierInput` evidence.

No other stream-owned file was edited by W4.

## Frozen-contract mapping

### §11.1 W2 assets/page/classifier

- `_AssetServer.set_probe_run(ProbeSpec | None)` admits only a 32-hex run ID, serves only `index.html`, `placement_probe.mp4`, and `placement_motion.mp4` below that run URL, uses W2's pinned loader/page renderer, supports MP4 byte ranges, and returns 404 semantics after clearing.
- `_measure_probe` opens a separate exact-URL probe CDP transport, records the exact target/default context/source UUID/connection generation, issues a fresh 128-bit nonce for every capture, validates the 16×8 nonce grid, waits at least 300 ms after painted-sequence observation, serializes and paces seven captures, validates DPR/decode/color/geometry stability, and constructs W2's immutable `ClassifierInput`.
- W2's `classify_probe` is the sole snap/frac/tone decision. Only a GPU-analytic, grant-eligible `snap` or `frac` result can commit.

### §11.2 W3 adapter

- `CalibrationRequest` binds the allocated run to the current engine identity, Program target/context, and host connection generation; selected placement remains W3's default `preview`.
- W4 passes a ProgramGuard on the existing Program transport and `measure` on a separate probe transport to `CalibrationAdapter.start`, then waits on a host-owned thread. It does not reach into W3 internals.
- Completion requires matching request/generation/context/engine, `program.ok is True`, isolation, cleanup and restoration, no errors, and no authoritative persistence failure. Cancellation and late/stale results never grant.
- Stop calls the adapter's bounded cancel, joins within the shared five-second placement teardown budget, then releases transport/server resources.

### §11.3 channel, lifecycle, renewal, and status

- Constructor accepts `calibration` and script/test-only `placement_mode`; `None` resolves to probe only for managed OBS with an adapter.
- Knowledge mode still permits only indefinite `snap`; product-launched Chrome retains its existing version/SystemInfo eligibility path.
- Probe mode fixes its mode in the pre-page closure, captures a bound monotonic clock, accepts only integer leases `1..15000` ms for `snap|frac`, expires in the getter, and cannot be changed or forged by page assignment/property replacement.
- Probe round trip is context-bound and leased; final commit rechecks engine, connection generation, original unique context, UA, DPR, and 1920×1080 viewport. Renewal refuses to resurrect a page-side expired grant.
- Managed lifecycle covers first eligible context, busy-transition deferral, reload/source refresh, managed transport reconnect, engine-generation changes, manual recalibration, failure/cancellation/stale completion, and stop.
- Runtime Program motion/isolation failures set launch-scoped automatic suppression. Manual retry remains available and does not clear suppression; a new engine identity clears it.
- ProgramGuard establishes a pre-install rAF baseline and reports visibility events, maximum rAF gap, and playing-media monotonicity/excess stall using §2.3 thresholds.
- O4 renewal runs on a host-owned three-second timer and immediately before go-to/advance (including repaired go-to autoplay). UA/DPR/viewport, context, connection, and engine identity are rechecked. CDP lock wait is included in the remaining-lease budget; expiry/timeout reports `leaseLapsed`.
- Managed CDP reconnect detaches without navigating the output, increments connection generation, reinstalls the future-document channel, and requires a successful revoke in the recovered current context before automatic reprobe/navigation.
- `output.placement` publishes all frozen additive fields: state/grant/reason/time, product/GPU, method/probe ID, lease metadata, observed/applied tone, and automatic suppression. No token, nonce, or source UUID is exposed. CEF `gpuCompositing` remains null because §2.3 forbids inventing unavailable browser-target SystemInfo; GPU evidence is represented by `tone.observed="gpu_analytic"`.

### §2.5 / O2 / O4

- `execute("recalibrate", None)` is managed-only, schedules without waiting for capture or navigation revision, preserves the existing observation, rejects a duplicate active run, and reports transition deferral through placement state.
- O2 is preserved: launched Chrome product behavior has no probe, timer, or lease and continues granting only qualified indefinite `snap`.
- O4 is implemented by the independent renewal thread, bounded CDP lock acquisition, page-side non-resurrection renewal expression, pre-navigation renewal, `leaseLapsed`, and stop cancellation/join.

## Deviations from §11

None in W4's owned scope. The implementation intentionally leaves CEF `gpuCompositing` null rather than claiming a SystemInfo value; this follows §2.3/O4 and uses the classifier's GPU-analytic tone result as the compositor evidence.

## Verification

- Required targeted command:
  - `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_host.py -q -n 2 -p no:cacheprovider`
  - Final result: **345 passed, 0 failed** in 1.98 s.
- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile src/obed_edom/live_host.py tests/test_live_host.py`
  - Result: **2 files compiled, 0 failures**.
- Generated ProgramGuard JavaScript checked with Node `--check`.
  - Result: **1 script checked, 0 failures**.
- `git diff --check -- src/obed_edom/live_host.py tests/test_live_host.py`
  - Result: **0 whitespace errors**.
- Ruff was not available in the project venv (`No module named ruff`); it was not a required W4 gate.

Known external reds were not exercised by the W4-only command: the named opacity-census and handback-census fixture failures remain coordinator-owned and untouched.

## Open items for the coordinator

- Run the cross-stream API/session/dashboard tests and full integration/qualification gates after W1–W6 settle; W4 did not run OBS, Chrome, Keynote, the full suite, or dashboard commands by instruction.
- Confirm the final W2/W3/W5/W6 combined diff still uses the frozen field names and that the managed router continues passing the exact OBS target ID plus `calibration_adapter()` (present in the concurrent W5 changes inspected by W4).
- No W4 code blocker or known contract deviation remains.
