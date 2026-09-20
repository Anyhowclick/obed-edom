# Plan — re-bracket the P2 freeze negative control at the 3→4 boundary

Status: decisions answered, implementation NOT started — awaiting the owner's direct go (Opus planner, 2026-09-20). No code written. Line numbers are as of `main` `946a7648`.
Why: `freezeControlCaughtByCounter` is parked `inconclusive` (P2 `success` False on `main`) because the baseline REFUSES
the 1→2 carry (`retire`), so there is no carried movie to freeze there. 3→4 still carries.

## 0. Premise check
- **Dead:** the boundary. `_capture_1to2_snapshot` (`scripts/p2_recovery_html_adversarial.py:2471`) arms on the 1→2 hash,
  scores `liveContinuity1to2` + `score_composited_index_run` over the 1→2 flip; `_ISOLATION_KEYS` carries slide-1/2
  composition ROIs (`blackAboveOk`, `blackBehindShowsMovie`, `greenFrontGreenish`). `_run_freeze_bracket`'s 3× boot of
  the 1→2 capture dies with it.
- **Reusable verbatim:** `NULL_CONTROL_JS` structure (arm/trigger/hold/release, id-less `{alpha:false}` cover, paint-once,
  per-rAF owner re-resolve + re-measure, `elementFromPoint` attestation, readiness + `currentTime` guard); the two-tier
  integrity/verdict split in `_score_freeze_control` (`:2682`) and its integrity keys; the A-B-A fresh-boot harness
  `_run_freeze_bracket` (`:2912`); constants `FREEZE_MIN_RUN` / `FREEZE_MIN_AFTER` / `RVFC_MIN_ADVANCE_S` /
  `MAX_RAF_GAP_MS` / `STALE_INDEX_TOL` / `COVER_MATCH_TOL` / `MIN_STALE_TIME_S`; the freeze suite in
  `tests/test_p2_adversarial.py:842-1100` (fixtures need new key names only).
- **Must change:** trigger (no `hashchange`; the hash does not move during the move), footprint tracking
  (translate + scale), the isolation key set (slide-4 invariants), the cut the counter is scored at, the release point
  (must precede the `footprintFullyLive` burst).

## 1. Prerequisite — the counter patch must track the footprint
`footprint_at` / `index_patch_roi_for` exist (`src/obed_edom/html_alpha_probe.py:1355,1377`; tests
`tests/test_html_alpha_probe.py:1541-1600`) and `_advance_to_slide4_capture` (`:2383`) already feeds
`index_patch_roi_for(footprint_at(progress, SLIDE3_MOVIE_RECT, SLIDE4_MOVIE_RECT))`. But `progress` is the PROBE's clock
(offset since the hash reached 8) while the painted rect is driven by the runtime's `keepThroughBridge` clock
(`src/obed_edom/live_continuity_js.py:656-706`). Unrelated clocks — which is why mid-transition decodes are declared
garbage today and only `progress>=0.98` is gated.

**Design: measure, don't model.**
1. Probe helper `_measured_footprint(chrome, key)` — `getBoundingClientRect()` of the keyed owner `<video>` (the element
   `_footprint_owner_keyed` resolves) → `{x,y,w,h,source:"measured"}`. During 3→4 the bridged decoder IS the painted
   surface (DOM `<video>`, opacity 1), so its rect is the painted rect.
2. Per index sample: `roi = index_patch_roi_for(measured or footprint_at(...))`, recording `footprintSource` ∈
   `measured|modelled|none`. A `modelled` sample is decoded and recorded but never counted in an at-cut run.
3. `index_patch_roi_for` scales its insets with `w,h` (×1.32 on slide 4). Verify on real frames that the scaled ROI stays
   inside the flat patch; if it spills, add a `scale_guard` parameter in src with its own unit test — not a script constant.
4. **Scorer null control (unit test):** synthesise a translating counter patch on a grating. Assert (a) the static
   `INDEX_PATCH_ROI` fails closed (`insufficient decodable samples` / `stall run too long`) and (b) the tracked ROI
   decodes the true sequence. This proves the tracking is load-bearing.

## 2. The 3→4 hold — trigger, geometry, release
**Trigger.** The player never fires `hashchange`; during the move the hash is `SLIDE4_MIN_HASH−1 == 7`, flipping to `#8`
~2 s later. `NULL_CONTROL_JS`'s live trigger is the rAF `location.hash !== armedHash` poll; the `hashchange` listener is
dead code on this player and `within_hashchange` is vacuously true when `hashchangeEventAt` is null — record that.
- Arm at `#7` AFTER the last slide-3 build is consumed (arming at `#6` fires on the 6→7 build).
- Trigger on the runtime's own move signal: rAF-poll for the bridged owner's `__obedMotion` (set by `keepThroughBridge`)
  or a `bridge-motion-start` note for this generation; fall back to the hash poll `#7→#8`. Record `firedVia ∈ motion|hash`.
  Capture the stale frame at that instant, with the existing ≤150 ms owner-readiness retry.
- **Wrong-reason trap:** `firedVia == "hash"` means the move is over and the cover tracked nothing. `firedAtMoveStart`
  (`firedVia == "motion"`) is an INTEGRITY key: a hash-only fire is INCONCLUSIVE, never a pass.

**Cover geometry.** Keep the partial left-fraction cover, re-derived per rAF from the MEASURED owner rect (`footprintNow`
already prefers `getBoundingClientRect`). `LEFT_FRAC = 0.4` of the 1274-wide slide-4 rect = 510 px, x∈[324,834]. The cover
is `position:fixed` (viewport px), the video absolute on the stage — equal only while the stage origin is (0,0): assert
`stageOrigin == (0,0)` at arm, else INCONCLUSIVE.

**Release.** After the last at-cut index capture and BEFORE the settled-slide-4 visible-content burst (`:3641`);
`footprintFullyLive` scores the whole `SLIDE4_MOVIE_RECT`, so a cover left in place reds it for the wrong reason.
`releaseAfterLastCapture` becomes two-sided `releaseBetweenLastCaptureAndBurst`; `coverPatchEnd` is snapshotted there.

**Other 3→4 traps.**
- *bridge34 off:* no carry ⇒ nothing to freeze. Arm B detects `bridge-3to4` absent ⇒ INCONCLUSIVE `bridge disabled`; the
  bracket is SKIPPED in the `--disable-bridge34` arm.
- *footprint pin vs cover:* `keepThroughBridge` re-asserts the rect every rAF; the cover must re-measure after it. New
  integrity key `coverTracksFootprint` = 100 % of hold frames with cover rect within 2 px of the measured rect.
- *retiring WA0125 clip:* the grown slide-4 box overlaps it; owner resolution stays keyed to `MOVIE1_KEY`; any
  `ownerAmbiguous` frame in the hold is INCONCLUSIVE (`noOwnerAmbiguousInWindow`, existing).

## 3. The counter verdict at the 3→4 cut
`"freeze run at cut"` is produced only by `score_composited_index_run`; 3→4 uses `score_index_progression` over the
settled window today. Add in the capture (all three arms):
`moving_index_run_at_cut = score_composited_index_run(measured_index_samples, flip_index=<first sample with hash>=8>)`
over samples with `footprintSource == "measured"`. In B the freeze must give `ok False`, reason `"freeze run at cut"`,
`freezeRunAtCut >= 6`, `negativeAnomaly False`, `n − flip_index >= 6`, flip window decodable.

## 4. Pass / inconclusive / fail
- **Integrity (any failure ⇒ INCONCLUSIVE):** `firedAtMoveStart` (new), `firedAfterAdvance`, `stageOriginZero` (new),
  `noControlError`, `ownerReadyAtTrigger`, `staleFrameFromPlayback`, `paintedOnce`, `coverPatchStable`, `coverHitTest100`,
  `coverTracksFootprint` (new), `loopLive` (≥10 rAF frames), `everyInHoldStale`, `flipIndexPresent`,
  `flipWindowDecodable`, `enoughAfterFlip`, `releaseBetweenLastCaptureAndBurst`, `allInHoldMeasured` (new),
  `bridgeEngaged` (new), `maxRafGapMs <= 100` (on a MOVING footprint a rAF stall leaves the cover behind the movie, so the
  1→2 "diagnostic only" carve-out does not transfer).
- **Verdict (PASS iff all, else FAIL):** `indexRunRed`, `reasonFreezeRunAtCut`, `freezeRunMargin`, `noNegativeAnomaly`,
  `movingContinuityOk`, `boundDecoderIsSlide3Decoder`, `noOwnerAmbiguousInWindow`, `rvfcRanThroughHold` (≥0.5 s),
  `playerBuildErrorsEmpty`, `positivesGreen` (A1/A2 `continueThroughMovingMagicMove3to4` pass AND their
  `movingIndexRunAtCut.ok`), `isolationEqual`.
- **`_ISOLATION_KEYS` for 3→4:** `movingContinuityOk`, `movingContinuityFailedEmpty`, `rvfcMonotonicOk`,
  `crossingIdentityOk`, `stableSlide4OwnerOk`, `boundaryValidOk`, `footprintFullyLiveOk`, `settledIndexProgressionOk`,
  `playerBuildErrorsEmpty`, `bridgeEngaged`. Slide-1/2 composition keys dropped; `movingIndexRunAtCut` and the 3→4
  finding's pass are excluded on purpose (they are what B flips).

## 5. Gate impact
- Findings 1–13 unchanged. `continueThroughMovingMagicMove3to4` gains a REPORTED `movingIndexRunAtCut`; it must stay True
  in fast/slow and stay the only red under `--disable-bridge34`.
- `freezeControlCaughtByCounter`: `inconclusive` → `pass` on fast and slow ⇒ `success` True honestly (the
  `verdict != "inconclusive"` and `restart_inconclusive` guards stay). Under `--disable-bridge34` the verdict is
  `"skipped"`, non-blocking only in that arm — which is already red on 3→4, so it cannot manufacture a green.
- Expected: fast 14/14, slow 14/14, bridge-off 13/14 (red only `continueThroughMovingMagicMove3to4`, freeze `skipped`).

## 6. Work split + commands
- **Stream A** — `src/obed_edom/html_alpha_probe.py` + `tests/test_html_alpha_probe.py`: scale guard (only if measured
  necessary), moving-ROI null control, static-vs-tracked misread test.
- **Stream B** — `scripts/p2_recovery_html_adversarial.py`, JS + capture: motion trigger, measured-rect tracking,
  stage-origin assert, `_measured_footprint`, `_capture_3to4_snapshot`, release ordering, `_run_freeze_bracket` re-point.
- **Stream C** — same file, scorer half + `tests/test_p2_adversarial.py`: 3→4 isolation view/keys, `_score_freeze_control`
  key sets, finding text + `success` wiring, port of every freeze test, new tests (`firedAtMoveStart`,
  `coverTracksFootprint`, rAF gap disqualifying, release-before-burst, bridge-disabled skip). B then C (one file).
- Tests: `PYTHONPATH=<worktree>/src $PY -m pytest tests/test_p2_adversarial.py tests/test_html_alpha_probe.py -q`, then the
  handover's unit list. Gates from `gate-runner` via `run_gates.sh`; `pgrep -fl obed-live-chrome` empty afterwards.
- **Codex brief:** (i) is the 3→4 premise real (bridged `<video>` is the painted surface); (ii) can the bracket PASS
  without a genuine freeze (walk every integrity key); (iii) does the cover perturb a 3→4 invariant (release vs
  `footprintFullyLive`); (iv) `movingIndexRunAtCut` only strengthens finding 13; (v) `success` stays honest bridge-off.

## 7. Risks
- Unit-testable: every scorer key, the ROI mapping, the null control, the fixture ports.
- Needs a live gate round: does the measured ROI decode MID-MOVE (biggest unknown — if not, `allInHoldMeasured` /
  `flipWindowDecodable` force INCONCLUSIVE, the honest outcome); does the cover stay within 2 px under rAF contention
  while CDP screenshots run; does `freezeRunAtCut >= 6` accumulate in the post-settle window at `DENSE_FPS`.

## 8. Owner decisions — ANSWERED 2026-09-20 (relayed via the DSK session; owner to confirm "go implement" directly)
a. `movingIndexRunAtCut`: REPORT-only until one clean fast/slow/bridge-off round, then gate.
b. Bridge-off arm: freeze verdict `skipped`, non-blocking in that arm only.
c. Hash-only trigger: INCONCLUSIVE.
