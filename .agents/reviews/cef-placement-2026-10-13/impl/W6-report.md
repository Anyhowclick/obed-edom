# W6 qualification report

## Files changed

- `scripts/dissolve_probe.py`
  - Added strict §11.6 `placementCalibration` serialization/deserialization, FileRef/CollectionRef hashing, ProbeCapture PNG persistence, transaction evidence `$ref` identity restoration, and schema validation without `default=str` fallback.
  - Added the shared paced probe-page measurement driver and the harness-only fresh Chrome probe runner.
  - Added all eight O1 production-path forgery rows (raw/preview × snap/frac × assignment/non-configurable getter), the leased `wrongrule-chrome` row, and scope controls that require every forgery to bind no holder.
  - Added the CEF frac profile: near/far x/y clip rows, no-offset reds, wrong-rule red, foreground/tone rows, paused/off/hold controls, and the two-holder DSK cost row.
  - Added CEF-specific launch tone-map extraction and strict placement record persistence in `save_run`.
- `scripts/managed_obs_qualify.py`
  - Added §5 fail-closed offline scoring through W2 `classify_probe` and W3 `persistence_allowlist`/`check_persistence`.
  - Added the `placement` qualification arm, with controls ordered before candidates, two output rates, and the existing two-fresh-take default.
  - Added a qualification-only adapter recorder that preserves the host-facing preview request while allowing an actual W3 offcanvas transaction, captures Unix-time placement events, and retains the actual transaction/result.
  - Added continuous lossless Program recording across install through restored cleanup, raw RGBA samples at every W3 guard phase plus the no-transaction null, a fixed transparent/half-transparent in-memory test overlay, moving-program null/candidate/Program-toggle telemetry, classifier replay/DPR/wrong-rule controls, and candidate recording/alpha analysis.
  - Added step-0-style baseline/null-before/null-after/cleanup/quit AK.json copies, backup copies, original mtime metadata, W3 persistence rescoring, post-quit finalization, and cross-launch freshness requirements.
  - Added harness-only Chrome GPU/software records, CEF tone-row reconciliation, strict `placementCalibration.gates`, recursive offline discovery, and aggregate two-fresh-launch checks.
- `tests/test_dissolve_probe.py`
  - Extended the existing scorer table for all O1 forgery rows, bound-holder rejection, CEF profile coverage, and CEF tone-map extraction.
- `tests/test_managed_obs_qualify.py`
  - Added one parameterized qualification-record test covering strict round-trip identity, CEF/Chrome scoring, missing evidence, preview/offcanvas adapter mapping, recursive two-launch offline rescore, sampled RGBA, lossless identical-frame analysis, and detected frame/audio injection.

## Frozen-contract mapping

- §11.1 W2 types/assets/classifier: consumed directly; capture PNG bytes become digest-bound files and are reconstructed for the same classifier API.
- §11.2 W3 adapter/result/persistence: the live arm calls `ManagedObs.calibration_adapter()`, preserves `CalibrationRequest`/`CalibrationResult`, and offline rescoring calls W3’s public normalization/allowlist/check APIs.
- §11.4 W4 channel/lifecycle: all CEF sessions use `placement_mode="probe"`; output state changes are retained as Unix-time events. `wrongrule-cef` uses the privileged leased channel. Offcanvas is qualification-only and maps back to the host’s preview-facing request, so runtime selection remains preview with no fallback.
- §11.6 record: all named fields are emitted. Dataclasses use snake_case and enums use values; raw bytes and Paths are rejected; transaction evidence is a JSON pointer to the single input object; every artifact is relative and SHA-256 bound; missing/malformed evidence yields INCONCLUSIVE.
- §5 geometry/fidelity/cost: `CEF_PLACEMENT` reuses the existing resolver, driver, scorer, controls, calibration, masks, references, foreground checks, and cost scorer for the new CEF rows.
- §5 O1: forged snap/frac assignment/getter rows remain in the existing production raw/preview arms, with no harness-installed channel.

## Deviations and evidence

- Exact `lastRemovalMtimeNs` is not exposed by frozen W3’s public `CalibrationResult`/`PersistenceCheck`. The nearest faithful record stores the wall-clock checkpoint taken at W3’s `before-cleanup` guard phase; cleanup authority still requires the copied AK.json mtime to be newer, and clean quit is authoritative. This is conservative but is not the exact WebSocket removal-call timestamp.
- The frozen W2 probe page exposes only its pattern/motion clips, not W5’s extended Chrome ramp/color-patch/skin-tone fixture. CEF W5 rows are populated from the existing `m-tone-cef`/twin launch measurement; Chrome records explicitly retain `complete:false` and an INCONCLUSIVE W5 problem instead of claiming unsupported coverage.
- The driver records and detects non-silent PCM and non-identical Program frames, and the offline positive-control test proves both defects are caught. It does not inject live audio into OBS: the managed Program browser source is seeded with audio rerouting disabled and the frozen W3 adapter has no qualification-only audio injection hook.
- Successful preview and offcanvas lifecycle transactions are run live. Cancellation, blocked-capture, delayed-delete, and stale-generation fault injection remain W3’s transaction-test responsibility because those fault controls are not exposed through the frozen public adapter.

## Validation

- Final required targeted run:
  - `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider`
  - **476 passed, 1 skipped, 0 failed** in 88.04 s.
- Syntax check:
  - `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py`
  - **PASS**.
- SHA-pinned splice check on committed exports:
  - Both supported stock players accepted all four `frac-nooffset-{x,y}` / omit combinations with exact count-checked anchors: **8/8 passed**.
- One focused intermediate run exposed raw ProbeCapture bytes in offline rescore gate detail: **3 passed, 1 failed**. The detail now uses the already-serialized transaction record; focused rerun: **4 passed, 0 failed**. The final required run above includes the fix.
- No OBS, Chrome, Keynote, live gate, full suite, dashboard test, or known external-red test was run, as required.

## Open items for the coordinator

- Run the live `--arm placement` qualification on the pinned OBS machine and inspect the owner visual check; this stream intentionally did not launch OBS/Chrome/Keynote.
- Decide whether W3 should expose the exact last removal timestamp in a future contract revision; until then the recorded checkpoint remains conservative.
- Supply/authorize an extended Chrome W5 tone fixture/API if Chrome ramp/patch/skin coverage must become complete rather than explicit INCONCLUSIVE.
- If a live audio-injection positive control is mandatory, add a frozen W3 qualification hook or a dedicated audible scratch input; do not infer it from the muted Program source.
- No known external reds were encountered in the permitted targeted files.
