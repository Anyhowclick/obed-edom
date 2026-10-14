# Review r2 (Opus 5.5 high): probe + qualification files, `git diff ecb1de98 ba3b9ff5`

Read-only review. Per the coordinator's hold, I ran no pytest and no generator in this round. I did re-run the blocker reproduction, which imports only the classifier.

**Verdict: NOT READY.** 0 blocker, 3 major, 4 medium, 7 low. Of the 14 findings, 7 are closed-class regressions introduced by the r1 fold, 2 are new class and 5 are edge cases.

## r1 findings: status

| r1 | Status | Evidence |
|---|---|---|
| 1 blocker content_box | **Closed** | `_expected_geometry` now uses contain-fit with a 1/256 px tolerance. I re-ran `scratchpad/geo_check.py` with the page's content box: it returns `FRAC classified` (it returned `invalid-evidence` at ecb1de98). Float32-rounded rect and content box are accepted. The Node row evaluates the page's own `geometry()`. Residual: if Chromium ever snapped the rect to LayoutUnit (1/64 px), the 1/256 px tolerance would reject it. Unverified live; the first live run will show it. |
| 2 recording order | **Closed, with regression R2** | Recording now starts in `QualificationCalibrationAdapter.start` after the settle step and stops in the done callback; coverage is computed. |
| 3 persistence null | **Closed, with regression R1 and low L3** | Uses `STEP0_NULL_ALLOWLIST`; `savedByObs` comes from `collection_saved_by_obs`. |
| 4 live positives | **Partly closed (M2, M3)** | The visible-origin, behind-Program and alpha-only injections are live and can genuinely FAIL. `startup`, `failedOnAir` and `priorStudioStates` are relabelled duplicates. The probe-* controls are offline transforms. |
| 5 flash/audio | **Closed in design, broken by R2** | The live flash and sine controls exist, but the flash lasts 1/50 s at a 25 fps canvas. |
| 6 classifier controls | **Closed (L2)** | Wrong-rule band swap, PNG replay and exact reasons are in place. The `dormant` control is mislabelled. |
| 7 host grant/forcing | **Closed, with regression M1** | Forcing happens only when `placement_value` differs from the classifier verdict, and drive-time grant/method/tone are checked. The ordered probing check can be satisfied by an event the harness writes itself. |
| 8 lastRemovalMtimeNs | **Closed, with regression R1** | The value now comes from `restored`. |
| 9 Chrome GPU/software | **Closed** | `chromeGpu` plus the per-launch map and eligibility requirements. |
| 10 W5 rows | **Closed (L1)** | Ramp/patch rows are present and `missingRows` keeps W5 INCONCLUSIVE. There is a rounding bug in the size. |
| 11 CEF controls | **Underlay closed (L4). Frac-origin is not runnable on CEF (R3)** | |
| 12 O1 known-bad | **Closed offline** | `m-raw-prod-forge-snap-getter-kb` is in mode `on` with the `scope` positive. Live behaviour is unverified. |
| 13 tests | **Closed** | Real round trip, no `classify_probe` monkeypatch, W2 rows added. The tests miss R1, R2 and R3 (see each finding). |
| 14–18 | **Closed** | Unit-test IDs and the "live subset" label, wording, dead code, the 1.0 s toggle, and the product-timing session. |

## Findings

### R1. MAJOR: closed-class regression (#8). `persistence-worker` can no longer PASS
- **Where:** `scripts/managed_obs_qualify.py`, `_persistence_gates` (verdict line after the checks loop), combined with `"lastRemovalMtimeNs": adapter.phase_times_ns.get("restored")` in `placement_session`.
- **How it happens:**
  - OBS writes `AK.json` on each removal, which happens before the `restored` sample. So the cleanup copy's `mtime < lastRemovalMtimeNs`.
  - `check_persistence(..., phase="cleanup")` then returns `authoritative=False, ok=None`.
  - The gate sets `unknown = True` and the verdict becomes INCONCLUSIVE, even after `finalize_placement_persistence` adds an authoritative, clean quit read.
- **Why it is wrong:** O5 says clean quit is authoritative and a non-authoritative cleanup read must not decide the gate.
- **Test gap:** the test fixture uses `lastRemovalMtimeNs=1` with mtimes 2–6, so it never exercises this case.
- **Fix:**
  - Compute the verdict only from authoritative rows: FAIL if any authoritative row has `ok is False`; PASS if the quit row is authoritative and `ok is True`; INCONCLUSIVE only if quit is missing or non-authoritative.
  - Keep non-authoritative cleanup rows in `detail` as "not authoritative".
  - Add a fixture row with cleanup `mtimeNs < lastRemovalMtimeNs` and a clean quit, and assert PASS.

### R2. MAJOR: closed-class regression (#2, #5). The recording uses the source fps, not the canvas fps
`placement_session` passes `fps=managed_obs.RATES[ctx["rate"]][1]` to `analyze_program_recording` and `recording_positive_controls`. That value is the browser-source rate: 50 for the 25 PAL canvas, 60 for 30 (`managed_obs.py:49`). The OBS recording runs at the canvas rate.
- **Frame count:** `minimumFrames = ceil(dur·50) − 1` is about twice the frames actually decoded. So `frameCountComplete` is False in every session, the recording leg is INCONCLUSIVE, and `program-wire-integrity` can never PASS.
- **Flash:** the flash is held for `1/fps` = 20 ms plus WebSocket round trips, against a 40 ms canvas frame. Whether it lands in any rendered frame is a matter of chance, so the flash control is often PASS (undetected), which makes the gate INCONCLUSIVE.
- **Fix:**
  - Pass the canvas rate (`ctx["rate"]`), or better, derive fps from the decoded recording's metadata and compare it with `ctx["rate"]`.
  - Hold the flash for `1.5/ctx["rate"]` s.
  - Require at least one decoded frame containing the flash colour (see L6).
  - Add an analyzer test row at 25 fps / 1.0 s with 25 frames that asserts `frameCountComplete`.

### R3. MAJOR: new class (missed in r1). Three CEF-profile arms need a viewport or DPR that the OBS source cannot produce
`m-geo-2560` (viewport 2560×1440), `m-geo-dpr125` (DSF 1.25, launch-flag provenance) and the new `m-geo-frac-origin-cef` (based on `m-snap-lbfrac`, viewport 1920×1201) are all in `CEF_PLACEMENT_ARMS` (`dissolve_probe.py:2459-2463`).
- The managed browser source is fixed at 1920×1080, DPR 1; the probe fingerprint even requires exactly that. The CEF drive path never emulates metrics.
- `capture_problems` (`dissolve_probe.py:2736-2744`) therefore marks these arms INCONCLUSIVE ("recorded viewport … is not the arm's", "devicePixelRatio … not from the Chrome launch flag"). `placement_gates` requires every arm to MATCH, so `CEF-placement` can never PASS.
- **Test gap:** the offline row "placement CEF fractional stage origin publishes no holder" uses `media_run`, which records the arm's own viewport, so it hides this.
- **Fix:**
  - Remove `m-geo-dpr125`, `m-geo-2560` and `m-geo-frac-origin-cef` from the CEF profile. Run the frac geometry negatives in the Chrome DX-1 profile through the script-only probe-mode channel, as `wrongrule-chrome` does. The take bytes are identical and DPR/viewport are controllable there: a frac-origin arm based on `m-snap-lbfrac`, plus frac DPR 1.5/2 arms based on `m-snap-dpr15`/`m-snap-dpr2` with `placement_value="frac", placement_mode="probe"`, each expecting geometry FAIL.
  - Alternatively, build a CEF frac-origin override that offsets the stage by 0.5 px inside 1920×1080, and stop requiring the arm's viewport for it.

### M1. MEDIUM: closed-class regression (#7). The harness writes a fake "probing" event that satisfies the life-cal order check
`QualificationCalibrationAdapter.start` appends `{"event":"calibration-start","placement":{"state":"probing"}}` before anything happens. The `life-cal-*` check looks for the first "probing" state in all events, so a host that never reports probing still passes the ordered probing→valid requirement.
- **Fix:** compute `states` only from `event == "placement"` rows, which are host-observed. Keep `calibration-start` as a separate marker.

### M2. MEDIUM: closed-class regression (#4). The startup, failedOnAir and priorStudioStates rows certify coverage that never ran
In `live_integrity_controls`:
- `startup` is the same equality test as `null`.
- `failedOnAir` aliases `visibleOrigin`, a FAIL-expected leak. The spec means a failed on-air recalibration whose isolation must PASS.
- `priorStudioStates` only toggles Studio Mode and reads it back; no calibration runs in the other initial state.

The iso gate treats all three as satisfied. W6 says this needs a W3 hook, but neither case does:
- (a) `SetStudioModeEnabled(true)` before `host.start()` for one candidate session per placement. W3 snapshots and restores that state, and `iso-obs-*` must PASS.
- (b) A failed on-air run: wrap `measure` in `QualificationCalibrationAdapter.start` so that `capture_png` raises after the first capture (or call `cancel`). W3 then aborts. Require isolation and restore to PASS and no grant.

**Fix:** implement (a) and (b) as real sessions. Until then, drop the aliases and leave those rows `"verdict":"NOT-RUN"`, which the gate treats as INCONCLUSIVE.

### M3. MEDIUM: W6 deviation disposition. Live probe controls are feasible without touching W3
The harness already sits between the host and W3, because `QualificationCalibrationAdapter.start` receives the host's `measure`. It can pass W3 a wrapping `measure` whose `CalibrationIO` proxy:
- returns the previous PNG on capture 2 (replay / warmed-dormant);
- returns a fully transparent 1920×1080 PNG (cold-dormant);
- pauses the probe video on the probe target via CDP before motion captures 2 and 3 (frozen video with live rAF).

Each control session must end with the host rejecting it (`placementProbeRejected`, no grant) and isolation/cleanup PASS. That exercises the product's own freshness path (`live_host._probe_nonce_matches`) and the classifier live, which the current offline transforms do not.
- **Fix:** add these three control sessions, ordered before the candidates. Keep the offline transforms as instrument checks.

### M4. MEDIUM: new class. Recording retention doubles disk use, and every hash reads the whole file into RAM
- **Disk:** `placement_session` and `recording_positive_controls` `shutil.copy2` each lossless 1080p recording into `run_dir`. The original stays in `record_dir`; `decode_session` deletion does not apply to placement sessions. With about 45 sessions × 2 rates × 2 takes and two recordings per session, this keeps two copies of each lossless recording. The README estimate of about 0.5 GB per 20–30 s session puts that in the tens of GB.
- **RAM:** `placement_file_ref` and `_placement_ref_bytes` hash with `path.read_bytes()`, loading each recording into memory on every serialise and rescore.
- **Fix:** `shutil.move` instead of copying. Hash in 1 MiB chunks, like the generator's `sha256`. Add a free-space preflight before `--arm placement` that states the expected size.

### L1. LOW: edge case. `probe_tone_rows` rounds the candidate size the Python way
`candidate_size = (round(cw), round(ch))`: Python `round(480.5)` is 480, but the page draws `Math.round(480.5)`, which is 481. Cell sampling on the candidate drifts up to 1 px across the width, so the right-hand patches lose their erosion margin.
- **Fix:** use `math.floor(v + 0.5)` (JS semantics) for `cw`, `ch` and the snap origin.

### L2. LOW: edge case. The `dormant` classifier control only flips `ready_state`
`ready_state=1` tests a metadata check. A dormant (cold) source yields an empty, transparent screenshot.
- **Fix:** replace `freshness[0].png` with a transparent 1920×1080 PNG and expect `stale-capture`. Keep the ready_state row named `notDecoded`.

### L3. LOW: edge case. The null "stability check" is not computed
`nullBefore` and `nullAfter` are copied and digest-checked, but never compared. The telemetry claims "running-file stability".
- **Fix:** require byte equality (or equal `_canonical_null_state`) and put the result in the gate detail, or drop the two copies.

### L4. LOW: edge case. The underlay-omission FAIL is credited to alpha refusal without proof the take ran
`_score_arm` returns `result(False, alphaRefusal=True)` for any zero-holder run.
- **Fix:** also require a published take record for the advance (`dump.takes` entry with `__obedTakeMs`) and `record["placement"] == "frac"`. A take that never ran is then INCONCLUSIVE, not "alpha refusal".

### L5. LOW: edge case. The settle evidence is taken before the Program toggle, and control removal is not confirmed
In `settle()`, the two equal OBS samples are taken before `program_guard_controls` toggles Program off and on for 1 s, so the recording's baseline follows an unsettled re-show. The `AK-Control-*` removals are also not polled for absence before W3 snapshots `AK`'s items; §1.2 records acknowledgements that precede actual removal.
- **Fix:** run the integrity, recording and guard controls first. Then poll `GetInputList` until no `AK-Control-*` remains. Then take the two equal samples.

### L6. LOW: edge case. The flash control counts any changed frame as detection
`flash.verdict = FAIL if decodedFrames > identicalFrames`, so motion unrelated to the flash would also "detect" it.
- **Fix:** require at least one frame whose centre pixel is the flash colour (white) and the frames before and after it equal to the first frame.

### L7. LOW: edge case. Test coupling to a case W2 never defined
`tests/test_managed_obs_qualify.py` imports `test_placement_probe._input` and calls `_input("software-snap")`. That case is not defined in `_regions`; it works only by falling through to the default branch.
- **Fix:** add an explicit `"software-snap"` branch (or a public helper) in `tests/test_placement_probe.py` so a later edit to the default cannot silently change this fixture.
