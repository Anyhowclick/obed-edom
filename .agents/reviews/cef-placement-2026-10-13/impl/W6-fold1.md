# W6 review round 1 fold

## Files changed

- `scripts/dissolve_probe.py`
- `scripts/managed_obs_qualify.py`
- `tests/test_dissolve_probe.py`
- `tests/test_managed_obs_qualify.py`

No other stream's files were edited by W6. The worktree also contains concurrent changes in W1-W5-owned files.

## Finding disposition

### #2 — folded

The candidate recording now starts in `QualificationCalibrationAdapter.start()` after its settle callback has awaited the page and obtained two equal OBS samples, immediately before delegation to W3. It stops only after the W3 future completes. The record carries `startedAt`, `stoppedAt`, `transactionStartedS`, and `transactionFinishedS`; coverage is computed from those timestamps. The decoder enforces at least `ceil((stop-start)*fps)-1` frames. A truncated recording or an ffmpeg missing-audio-stream result is INCONCLUSIVE.

### #3 — folded

Offline persistence scoring now uses `managed_obs.STEP0_NULL_ALLOWLIST`, matching W3. The two running-file copies are explicitly recorded as a stability check, not an allowlist derivation. `collection_saved_by_obs()` distinguishes the harness seed shape from an OBS-written collection, and the baseline `savedByObs` flag uses that result.

### #4 — folded to the nearest faithful W6 implementation; remaining API limitation disclosed

Before each candidate, the live OBS preflight now records:

- equal-screen isolation and alpha nulls;
- Studio-mode toggle/restoration evidence;
- scratch `color_source_v3` visible-origin, behind-transparent-Program, and alpha-only injected defects, all required to produce FAIL;
- classifier wrong-rule, replayed-PNG, DPR, undecodable-PNG, frozen-motion, dormant-source, and wrong-context controls, with exact rejection reasons.

Missing or non-failing controls make the affected gate INCONCLUSIVE.

Deviation: the OBS leak/alpha positives are genuine live scratch-source edits, but `startup` and `failedOnAir` are preflight records rather than separate failed calibration transactions in both initial Studio states. The probe replay/frozen/dormant/context controls are transformations of the real live evidence evaluated through the production classifier, not separate W3 live source transactions. The frozen-video wording calls for pausing the W3-created source while retaining live rAF; §11.2 exposes no hook between W3 source creation and capture to do that from W6 without changing `src/obed_edom/managed_obs.py`. The harness therefore fail-closes on these named controls but does not claim they are independent live transactions.

### #5 — folded

The preflight makes a real lossless OBS recording, flashes a full-frame `color_source_v3` for one frame, adds a short sine `ffmpeg_source`, retains and decodes the recording, and requires the visible flash to be detected. If the live audio stream is present, the sine must be detected. If the fixture cannot be created or the seeded Program's `reroute_audio=false` path yields no audio stream, the audio control is REPORTED with that explicit reason rather than PASS. The candidate recording still treats a missing audio stream as INCONCLUSIVE.

### #6 — folded

`classifier_controls()` now swaps the snap/frac candidate pixel bands for the wrong-rule control, reuses the first PNG under the second nonce for replay, and checks exact reasons: `stale-capture`, `unsupported-dpr`, and `invalid-evidence`. It also checks an undecodable PNG. Candidate reason must be `classified` for the grant-eligible GPU path or `software-map` for the ineligible software path.

### #7 — folded

The privileged placement force now runs only when an arm's requested value differs from the classifier verdict, which limits it to the intended wrong-rule arm. Drive-time placement is captured before forcing. Lifecycle scoring requires an ordered probing-to-valid sequence, `method == "probe"`, grant equal to the classifier verdict, and observed tone equal to the classifier tone map.

### #8 — folded

`lastRemovalMtimeNs` now comes from `adapter.phase_times_ns["restored"]`, the checkpoint after removal/restoration, rather than `before-cleanup`.

### #9 — folded

Chrome telemetry records the requested GPU/software launch identity. The GPU gate requires SNAP plus `GPU_ANALYTIC` and grant eligibility; the software gate requires SNAP plus `IDENTITY` and ineligibility.

### #10 — folded

CEF and Chrome evidence now produces 16 grey-ramp rows and 8 colour-patch rows by comparing the video against the correct-rule candidate over eroded flat cells. CEF no longer claims completion from one LUT. Both backends list the missing fresh-launch, acceleration, hevc10, Keynote-HEVC, skin, and reset/invalidation evidence, so W5 remains INCONCLUSIVE until every required row exists.

### #11 — folded

Added `m-snap-cef-underlay-omit`, driven by a counted sha-pinned in-memory splice that drops only the snapped underlay draw and expects no holder as alpha refusal. Added `m-geo-frac-origin-cef`, which uses the fractional 60.5 px stage origin and expects geometry FAIL. Both are in the corresponding CEF profile/control negatives and have behavioral scorer rows.

### #12 — folded

Added live arm `m-raw-prod-forge-snap-getter-kb`, using the take-bearing live variant with the same snap-getter forgery and expecting a bound holder/scope PASS. It is the positive scope control; the production forged rows remain negatives.

### #13 — folded for W6-owned files

The qualification fixture now builds real PNG evidence, serializes it through `FileRef`, deserializes it, runs the real `classify_probe`, and asserts exact equality with the recorded result for CEF, Chrome GPU, and Chrome software rows. The fixture's `content_box` is the page's contain-fit box through the shared `tests/test_placement_probe.py::_input` helper.

Ownership deviation: moving `_input` into a new shared fixture would require editing `tests/test_placement_probe.py`, which is outside W6's allowed files. W6 imports that stream's helper instead. The current real-classifier round trip passes with it.

### #14 — folded

Persistence and lifecycle gate details now say `coverage: "live subset"` and include the verified unit-test IDs for cancellation/fencing, crash-before-record cleanup, reconnect/renew/suppress/expiry, and related fault coverage. They no longer imply that every fault row ran live in the qualification harness.

### #16 — folded for W6-owned items

Removed the unused `classifierControls` return from `run_chrome_placement_probe`, corrected the `measure_placement_probe` docstring to describe the Chrome harness, restored the `PREDEFINE_JS` attribute docstring position, and removed the implementation-mirroring CEF-profile membership test. Behavioral rows cover the new arms and counted splice.

### #17 — folded

The Program-toggle positive control now holds Program off for the step-0-measured 1.0 seconds.

### #18 — folded

Every guard sample records whether an RGBA screenshot ran and its cost. `m-snap-cef` is the per-launch product-timing candidate with before/after-capture RGBA sampling disabled; the sampled candidates retain the alpha-integrity coverage. The product-timing row reports alpha rather than claiming a sampled PASS.

## §11.6 / harness record mapping

- `placement_record()` and the existing serialize/deserialize path emit and consume the frozen `placementCalibration` record fields.
- CEF records hold request, real classifier evidence/result, W3 transaction/result, ordered placement events, persistence file refs and checks, program/RGBA/telemetry refs, stock digest, and harness backend identity.
- `telemetry.json` carries classifier controls, tone rows, live isolation/alpha controls, continuous recording analysis and positives, drive-time placement, settle evidence, screenshot costs, sampling mode, and the persistence-null label.
- Chrome records use the same classifier serialization and scoring APIs and add the harness-only GPU/software identity and tone rows; `placement_mode` remains script-only.
- Missing, undecodable, stale, incomplete, unproven, or unsupported evidence resolves to INCONCLUSIVE unless an observed product defect specifically requires FAIL.

## Verification

Mandated final command:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
480 passed, 1 skipped in 97.50s
```

Development runs retained for audit:

- Initial two-file run: 478 passed, 1 failed, 1 skipped in 92.87s. The failure showed the underlay-omission arm's reference capture needed the engage frame; the arm was corrected from perfect to engage.
- Focused underlay regression after correction: 1 passed in 0.70s.
- Earlier placement-focused subset: 14 passed in 2.63s.

Additional checks:

```text
env PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.10 -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py
PASS

git diff --check -- scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py
PASS
```

No OBS, Chrome, headless browser, or Keynote run was performed, as required. None of the known external reds was in the targeted files or encountered.

## Open items for the coordinator

- Run the live qualification gates. Offline tests cannot establish that the local OBS build accepts `color_source_v3`/`ffmpeg_source`, that the one-frame flash lands in the retained recording, or that the seeded audio path exposes a mix; the harness records failures/inconclusive evidence rather than masking them.
- If independent live paused/dormant/replay probe transactions and separate startup/failed-on-air calibrations in both initial Studio states are mandatory, W3 needs a scoped fault/control hook around its created browser source and capture phases. W6 did not alter W3-owned files.
- Retain the shared real-pixel fixture import or have the owning stream relocate it; W6 could not edit `tests/test_placement_probe.py`.
