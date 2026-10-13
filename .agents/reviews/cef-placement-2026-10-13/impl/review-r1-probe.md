# Review r1 (Opus 5.5 high): probe + qualification files, `git diff 99d53542 ecb1de98`

Scope: `src/obed_edom/placement_probe.py`, `src/obed_edom/data/placement_*`, `scripts/generate_placement_probe.py`,
`pyproject.toml`, `scripts/dissolve_probe.py`, `scripts/managed_obs_qualify.py`, `tests/test_placement_probe.py`,
`tests/test_dissolve_probe.py`, `tests/test_managed_obs_qualify.py`. Read-only; no OBS/Chrome/Keynote run.

**Verdict: NOT READY.** 1 blocker, 4 major, 8 medium, 5 low.

## Verified OK (with evidence)
- GPU table is the same as `probeana.py` `LT` (`round(255·sRGB((i/255)^1.961))`). Thresholds are `>4` LSB, `≤.02`/`≥.20`. The inner mask is 3 px, the max is over R/G/B, the two poses must agree, a single intermediate share disqualifies only that map, and two consistent maps give `ambiguous`. All of this matches §2.4/§11.1.
- Nonce decode matches §11.1: central 2×2, ≤32/≥223, alpha 255, exact. The classifier enforces ≥300 ms paint→capture, ≥200 ms pacing, ≤2 s per capture and a 15 s budget. It also requires distinct motion hashes/counters and a stable RGBA pair per pose.
- Asset pins: the manifest digest is pinned, both asset digests and byte counts are checked, and `repeatSha256` is checked.
- **Generator reproducibility:** I re-ran `scripts/generate_placement_probe.py --output-dir <scratch>`. Pattern `7b7d66b5…9870`, motion `e4640a66…bfe` and the manifest (`cmp`) are all byte-identical to the committed files. The generator sha `2dd0ad8a…` matches the committed script.
- **Wheel:** I built from a `git archive` copy in scratch (`uv build --wheel`). All three assets are in the wheel and their hashes match the pins.
- Python 3.10: every changed file parses under `/usr/local/bin/python3.10`.
- `pytest tests/test_placement_probe.py tests/test_managed_obs_qualify.py -k placement`: 27 passed.

## Findings

### 1. BLOCKER: new class. The classifier rejects every real capture because its expected `content_box` equals the CSS rect
`src/obed_edom/placement_probe.py:251-260` (`_expected_geometry` sets `content_box=rect`) and `:273` (tolerance 1e-6).
- **What the page reports.** The page's `geometry()` (`placement_probe.py:463`) publishes the object-fit contain box of a 1920×540 video inside 480.53125×135.140625 CSS px: `f=135.140625/540`, `cw=480.5`, `cx=r.left+0.015625`. Chromium's rect is exact here; 480.53125 and 135.140625 are 1/64 multiples. So `content_box` differs from `rect` by 0.015625 in x and 0.03125 in width. `_same_geometry` therefore raises "probe geometry mismatch", which becomes `invalid-evidence` → UNKNOWN on every live CEF and Chrome-harness run. The probe can never grant, and W6's `probe-cef`/`probe-chrome-harness` can never PASS.
- **Reproduced.** In scratch, `geo_check.py` takes `tests/test_placement_probe._input("gpu-frac")`, which is classified, and replaces each pose's `content_box` with the page's contain-fit `(10.367625, 10.036, 480.5, 135.140625)`. The result is `UNKNOWN invalid-evidence`.
- **The tests mirror the bug:** `tests/test_placement_probe.py:40`, `tests/test_live_host.py:3457` (`"contentBox": list(rect)`) and `tests/test_managed_obs_qualify.py:1659`.
- **Fix:**
  - In `_expected_geometry`, compute `f=min(w/_VIDEO_SIZE[0], h/_VIDEO_SIZE[1])`, `cw,ch=_VIDEO_SIZE[0]*f,_VIDEO_SIZE[1]*f` and `content_box=(x+(w-cw)/2, y+(h-ch)/2, cw, ch)`.
  - Loosen the rect/content_box tolerance to 1/256 px. `box` already drives every ROI exactly, and in a float32 emulation the pose-1 `left` already errs by 4.6e-7, near the 1e-6 limit.
  - Make the test helpers derive `content_box` the same way.
  - Add one Node row that evaluates the page's `geometry()` arithmetic for both poses (videoWidth 1920, videoHeight 540) and asserts `_same_geometry` against `_expected_geometry`. That ties the page to the classifier.

### 2. MAJOR: new class. The program recording starts before `host.start()` navigates the Program page, so `program-wire-integrity` always FAILs
`scripts/managed_obs_qualify.py:1278` (`start_record`) runs before `:1288` (`host.start()`). `LiveOutputHost.start` calls `self._transport.goto(url)` (`live_host.py`, in `start`), and `PLACEMENT_ALPHA_JS` adds its overlay on DOMContentLoaded.
- The recording therefore contains the blank→deck navigation and the overlay appearing. `analyze_program_recording` (`:585`) compares every frame with the first, so `identicalFrames < decodedFrames` and the result is FAIL in every placement session. This is a false FAIL on a correct product. The "static baseline" is not the program the transaction must leave untouched.
- **Fix:** start the recording inside `QualificationCalibrationAdapter.start`, before delegating to the W3 adapter. Do this only after the page is settled: take two equal `obs_screenshot` samples, after `await_input`. Stop it after `done`. Record `startedAt`/`stoppedAt` and the transaction `started_s`/`finished_s` so coverage is computed, not hard-coded (`covered=True`, `:1339`).
- Also make a missing audio stream (ffmpeg "does not contain any stream") or a frame count short of `(stop−start)×fps−1` INCONCLUSIVE instead of FAIL or unchecked. §5: a missing or truncated recording is INCONCLUSIVE.

### 3. MAJOR: new class. The persistence null is vacuous, and the offline rescore diverges from W3's live check
- **The null.** `scripts/managed_obs_qualify.py:1274-1277` copies the same `AK.json` twice, 0.1 s apart, in a running OBS. The derived `persistence_allowlist(null_before, null_after)` (`:357`) is therefore empty. Step 0 recorded that OBS does not rewrite `AK.json` at launch (seed→quit diff).
- **False FAIL.** The first CEF placement session's `baseline` is the unsaved seed, mislabelled `savedByObs=True`. Quit and cleanup are OBS-saved, so they differ at the step-0 fields (`/modules/*`, `/virtual-camera`, `/scaling_level`, `hotkeys/*`, `*_rel`). With an empty allowlist, `persistence-worker` FAILs.
- **Divergence.** W3's live check (`managed_obs.py:1261`) uses `STEP0_NULL_ALLOWLIST` and passes the same files, so live and offline disagree.
- **Fix:**
  - In `_persistence_gates`, use `managed_obs.STEP0_NULL_ALLOWLIST`, the field-justified list in §2.2. Alternatively, derive the allowlist from a real no-transaction launch→quit null, stored per take.
  - Drop the 0.1 s pseudo-null or label it a stability check.
  - Set `savedByObs` truthfully: false when the baseline bytes equal the seed `_seed` wrote.

### 4. MAJOR: new class. §5 live positive controls are absent and undisclosed, yet their gates return PASS
§5: "Each gate has a null and an injected positive defect … failed control … INCONCLUSIVE". None of the following exists in `managed_obs_qualify.py` or `dissolve_probe.py`:
- **`iso-obs-*`:** `iso-leak` visible-origin/on-program and behind-transparent-`Program` → FAIL. Also absent are the startup and failed on-air recalibration runs in both prior Studio states.
- **`alpha-integrity`:** a behind-Program leak, and an alpha-only change held across a sample → FAIL.
- **`probe-*` live:** cold/warmed dormant or disabled source, frozen video with live rAF, and prior-run PNG replay → invalid.

`score_placement_calibration` nevertheless returns PASS for `iso-obs-*` (`:434-441`) and `alpha-integrity` (`:485-490`) from the candidate alone. W6's report does not list these as deviations.

**Fix:**
- Add these as control sessions ordered before candidates. Use scratch-only OBS edits for the leak and alpha rows.
- For frozen video, use `video.pause()` on the motion phase with rAF still running.
- Make each gate INCONCLUSIVE when its control record is missing or did not produce the required FAIL.

### 5. MAJOR: W6 deviation 3, plus the flash it did not mention. The recording leg has no live positive control and still PASSes
- **Offline-only controls.** The one-frame flash and the audio injection are proven only on synthetic arrays (`tests/test_managed_obs_qualify.py`, end of the new test). No live session injects either one, so a recorder pointed at the wrong output, or an empty mix, passes.
- **Audio is vacuous.** The seeded Program source has audio rerouting disabled, so "all PCM silent" cannot see page audio at all.
- **Judgement:** the deviation is not acceptable as PASS.
- **Fix:** add one scratch-only control session in a recorded transaction window:
  - flash a `color_source_v3` item in `AK` for one frame;
  - add a short `ffmpeg_source`/sine input routed to the mix;
  - require both to be detected.

  Until that exists, set the recording leg to INCONCLUSIVE. In §9/handover, state that page audio bypasses the OBS mix by design.

### 6. MEDIUM: new class. `classifier_controls` checks nothing beyond the candidate verdict
`scripts/managed_obs_qualify.py:565-583`.
- **Wrong rule.** `if result.verdict == wrong` is implied by `result.verdict != expected`, so no wrong-rule control exists.
- **Replay.** It only re-uses a nonce string. `_validate_input` rejects that by uniqueness before any pixel is read, so it never tests a replayed screenshot.
- **Reasons.** Both controls accept any UNKNOWN, including `invalid-evidence`. §5 says "an invalid capture cannot count as an expected classifier rejection".
- **Fix:**
  - Build the wrong-rule control by swapping the snap/frac candidate pixel bands in each pattern PNG (same nonce cells). It must classify as the opposite verdict.
  - Build the replay by setting `freshness[1].png = freshness[0].png` while keeping `freshness[1].nonce`. It must give `reason == "stale-capture"`.
  - The DPR control must give `reason == "unsupported-dpr"`.
  - Add an undecodable PNG control that must give `invalid-evidence`.
  - Require the candidate to be `reason == "classified"`.

### 7. MEDIUM: new class. The product host's grant is never gated, and the positive arms silently force `frac`
- **Forcing.** `scripts/managed_obs_qualify.py:1311-1313` force `arm.placement_value` through the privileged channel whenever the host's grant differs. That applies to every positive (`m-snap-cef*`, `m-fg-cef`, …), not only `wrongrule-cef`. The `forcedPlacement` record is never checked.
- **Recompute.** `:1340` re-runs `classify_probe` in the harness, so "recorded vs offline classification" compares the function with itself.
- **Life-cal.** `life-cal-*` (`:499`) only checks that "probing" and "valid" are in the set of states.
- **Result:** a host that grants `snap`, or nothing, after a FRAC/GPU classification passes every gate.
- **Fix:**
  - Force only for arms whose `placement_value` differs from the expected calibrated value (`wrongrule-*`).
  - For the others, add a problem when `host.output.placement` is not `{state:"valid", grant:"frac", method: probe}` at drive time.
  - `life-cal-*` must require an ordered probing→valid sequence with the final `grant == classification.verdict` and `tone.observed == classification.tone_map`.

### 8. MEDIUM: W6 deviation 1. `lastRemovalMtimeNs` from `before-cleanup` is a lower bound, not conservative
`before-cleanup` is sampled (`managed_obs.py:1315`) before the first `RemoveSceneItem`/`RemoveInput`/`RemoveScene` (`:1175-1191`).
- An `AK.json` that OBS saved after an intermediate removal therefore counts as authoritative offline, while W3 live (`last_removal_mtime_ns` after the removals) treats it as non-authoritative. This is the opposite of "conservative", and another live/offline divergence.
- **Fix:** record `adapter.phase_times_ns["restored"]`, taken after all removals and the absence poll, as `lastRemovalMtimeNs`. It is a true upper bound: cleanup reads become non-authoritative unless saved later, and quit remains authoritative. Optionally ask the coordinator for a contract amendment exposing W3's value.

### 9. MEDIUM: edge case. The Chrome harness gate cannot tell a GPU launch from a software launch
`scripts/managed_obs_qualify.py:418` and `placement_gates` (`:2280-2284`) PASS any `SNAP`, under either map, for both `probe-chrome-gpu` and `probe-chrome-software`. A GPU launch that silently fell back to software (identity) passes; §2.7 asks for GPU/software discrimination.
- **Fix:** `probe-chrome-gpu` requires `tone_map == gpu_analytic and grant_eligible`. `probe-chrome-software` requires `tone_map == identity and not grant_eligible`. The session name carries `gpu`.

### 10. MEDIUM: W6 deviation 2, plus a CEF overclaim. W5 tone rows
- **CEF overclaims.** `scripts/managed_obs_qualify.py:2264` sets `complete = lut is not None`, so the CEF W5 gate reports REPORTED (done) from one launch LUT. §2.7 still requires two fresh launches each with OBS acceleration on and off, hevc10, Keynote-HEVC, and invalidation rows.
- **Chrome INCONCLUSIVE is honest but partly unjustified.** The pinned pattern contains a 16-step grey ramp and eight colour patches (`generate_placement_probe.py:56-71`). Every pattern capture holds the composited video and a candidate canvas of the same frame, so ramp and patch tone rows can be computed from captures already taken. Only skin tones are genuinely missing.
- **Fix:**
  - Set `complete` only when every §2.7 row is present, and list the missing rows otherwise.
  - Derive the ramp/patch rows for both engines from the existing pattern captures: per-cell video against the correct-rule candidate, over the eroded flat cells.
  - Keep skin tones INCONCLUSIVE.

### 11. MEDIUM: new class. The CEF profile lacks two §5 controls
`scripts/dissolve_probe.py:2439-2466` (`CEF_PLACEMENT_ARMS`) has no "fractional-only underlay-omission → alpha refusal" arm and no frac fractional-stage-origin negative. These are required by the `m-snap-cef` and Geometry rows.
- **Fix:** add a counted splice that drops the snapped underlay draw, with `expect` no holder (alpha refusal). Add a fractional `R.left` origin override arm with `geometry` FAIL. Place both in the profile's `holder_pixels`/`geometry` negatives.

### 12. MEDIUM: edge case. The O1 forged rows lack the live known-bad control §5 names
§5 Raw/preview: "Current rendering variant is the known-bad forgery control." The eight `m-*-prod-forge-*` rows expect `scope` FAIL (no holder). The only "binds a holder" evidence is a synthetic scorer row (`tests/test_dissolve_probe.py`, `forge-frac-getter`, holder=True). If holder detection on the raw/preview page were broken, every forged row would MATCH vacuously.
- **Fix:** add one live arm, `m-raw-prod-forge-snap-getter-kb`, that serves the take-bearing live variant (`patch_player` bytes) on the raw page with the same forgery. Expect `scope` PASS, a holder bound. Put it in the `scope` controls as a positive.

### 13. MEDIUM: edge case. Test gaps: the tables miss named rows, and the offline rescore never runs the real classifier
- **Missing rows.** `tests/test_placement_probe.py` lacks rows that §5/§6 name: motion frame/counter repeated (frozen video), settle <300 ms, pacing <200 ms, wrong PNG size, capture identity/context mismatch, and two maps consistent with different rules. For the last one: video=111, snap=111, frac=100 makes identity give SNAP and GPU give FRAC → `ambiguous`.
- **Mocked classifier.** `tests/test_managed_obs_qualify.py:1717` monkeypatches `classify_probe`, and its captures are `b"png"`. The serialize→PNG FileRef→deserialize→classify round trip is never exercised with real data.
- **Fix:** add those cases as rows to the existing parametrized table. In the qualify test, build `evidence` from a shared real-pixel helper (move `_input` into a small fixture both tests import), drop the monkeypatch, and assert that the offline result equals the recorded one. No new test functions are needed.

### 14. LOW: W6 deviation 4, fault injection left to W3 unit tests
This is acceptable, because §6 assigns cancellation, blocked capture, delayed delete and generation to the managed transaction test. However, `life-cal-*` and `persistence-worker` still report PASS as if their fault rows ran live. Crash/relaunch `_seed` and the reload/reconnect/expiry rows are also not live.
- **Fix:** put the covering unit-test ids in each gate's `detail` and label the gate a "live subset". Alternatively, report those rows as REPORTED rather than folding them into PASS.

### 15. LOW: W2 report wording on the pattern digest
W2 says the regeneration "is the retained artifact" and that the full digest was "recovered". §2.4/O3 forbid that claim, since prefix plus size is corroboration only. My re-run confirms the generator is byte-reproducible, but identity with the pruned file is not proven. The current manifest also records the declared `colorTuple`, not one read back by ffprobe ("decoded-frame/color metadata").
- **Fix:** in the report, handover and commit text, say "regenerated; byte-reproducible; matches the retained 144,100 B / `7b7d66b5` prefix (corroboration)". State that requalification is not inherited. Optionally record ffprobe stream metadata in the manifest.

### 16. LOW: dead code, duplication and style
- `placement_probe.py:210`: `inner_pixels != other_pixels` is unreachable, because `_share` already enforces equal shapes. Remove it.
- `dissolve_probe.py:3731`: `run_chrome_placement_probe` returns `classifierControls`, which nothing reads. Remove it.
- `dissolve_probe.py:3627`: the docstring says the OBS path uses `measure_placement_probe`, but OBS uses `live_host._measure_probe`. Fix the docstring to "Chrome harness driver".
- `dissolve_probe.py:732-744`: `FORGERY_JS` was inserted between `PREDEFINE_JS` and its attribute docstring, so the docstring now documents the wrong constant. Move `FORGERY_JS` below it.
- `tests/test_placement_probe.py:137`: `math_ceil` re-implements `math.ceil`. Use `math.ceil`.
- `tests/test_dissolve_probe.py`: the row "placement CEF profile carries clips…" is a set-membership mirror of the implementation. Drop it; the profile is exercised by the scorer rows.

### 17. LOW: edge case. The Program-toggle positive uses an unmeasured 0.1 s off-time
`program_guard_controls` (`managed_obs_qualify.py`, `run(True)`) disables `Program` for 0.1 s. Step 0 measured the guard tripping at 1 s off. If 0.1 s does not trip it, `program-wire-integrity` false-FAILs with "Program-toggle positive control did not fail".
- **Fix:** use the measured 1.0 s.

### 18. LOW: edge case. Qualification adds an OBS full-frame screenshot inside every probe capture
`QualificationCalibrationAdapter`'s guard `sample` runs `obs_screenshot` at `before-capture`/`after-capture`, which execute inside `_CalibrationIO.capture_png` (`managed_obs.py:620`, `:644`). The step-0 cost is 90–107 ms per capture. The qualified paint→screenshot gap and the 2 s capture budget therefore differ from the product's, so qualification does not demonstrate the product's 300 ms settle margin or its latency.
- **Fix:** record the sample cost per capture in telemetry. Run one candidate per launch without per-capture RGBA sampling to log the product timing; keep the sampled run for alpha integrity.

## W6 deviation judgements
1. `lastRemovalMtimeNs` approximated by before-cleanup: **reject the "conservative" claim** (#8). Use the `restored` checkpoint.
2. Chrome W5 tone rows INCONCLUSIVE: **honest but partly avoidable**; ramp and patches are in the pinned clip (#10). The CEF counterpart overclaims "complete".
3. No live audio-injection positive: **not acceptable as PASS** (#5). The visible-flash positive is also offline-only, and that was not disclosed.
4. Fault injection left to W3 unit tests: **acceptable per §6**, but the gates must say so (#14). The live iso-leak, alpha and probe-* positives are a separate, undisclosed gap (#4).
