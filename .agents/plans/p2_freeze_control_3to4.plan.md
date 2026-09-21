# Plan — re-bracket the P2 freeze negative control at the 3→4 boundary

Status: IMPLEMENTED and under review — the freeze negative control is re-bracketed on the MOVING 3→4 Magic Move
and runs in both the A-B-A scratch bracket and the e2e. Codex review rounds 1–12 (r1–r9 recorded under
`.agents/reviews/freeze-3to4/`); round 12 closes r9's four majors (MAIN's cut boundary, the pre-trigger poll
gap, the release split + first settled instant, the null controller's keydown filter) and replaces the
hand-picked absence sweep with an EXHAUSTIVE leaf walk (§10.14), which found two further ungated
cached-verdict reads and a Chrome orphan path. NOT merged; no CI, so the
two suites are run locally. Current live results (round 12, this machine): 5/5 clean scratch brackets `pass`
with `integrityFailed []` at load 3.5–7.5, and e2e fast/disposable/bridge-on `success: True` with
`freezeControlCaughtByCounter` `pass` at load 6.7–7.1. Line numbers below are as of `main` `946a7648`.
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
  integrity key `coverTracksFootprint` = 100 % of hold frames with cover rect within `COVER_TRACK_TOL_PX` = 0.5 px of the measured rect.
- *retiring WA0125 clip:* the grown slide-4 box overlaps it; owner resolution stays keyed to `MOVIE1_KEY`; any
  `ownerAmbiguous` frame in the hold is INCONCLUSIVE (`noOwnerAmbiguousInWindow`, existing).

## 3. The counter verdict at the 3→4 cut
`"freeze run at cut"` is produced only by `score_composited_index_run`; 3→4 uses `score_index_progression` over the
settled window today. Add in the capture (all three arms):
`moving_index_run_at_cut = score_composited_index_run(measured_index_samples, flip_index=<first sample with hash>=8>)`
over samples with `footprintSource == "measured"`. In B the freeze must give `ok False`, reason `"freeze run at cut"`,
`freezeRunAtCut >= 6`, `negativeAnomaly False`, `n − flip_index >= 6`, flip window decodable.

## 4. Pass / inconclusive / fail
As IMPLEMENTED (`_score_freeze_control`; the original draft split below was revised in rounds 3–12 — a FAIL is a claim
about the COUNTER, so everything that instead says "the stimulus or the measurement was not sound" is INCONCLUSIVE, and
continuity / positives / isolation moved from the verdict tier to the integrity tier):
- **Integrity (any failure ⇒ INCONCLUSIVE):** `firedAtMoveStart`, `firedAtRuntimeMotionStart`, `firedAfterAdvance`,
  `advanceKeySameEventInControl`, `noPreAdvanceDeparture`, `drainPressesAllLanded`, `advanceSinglePressAllArms`,
  `coverPaintedAtPresent`, `stageGeometryStable`, `stageOriginZero`, `noControlError`, `ownerReadyAtTrigger`,
  `staleFrameFromPlayback`, `paintedOnce`, `coverPatchStable`, `coverHitTest100`, `coverTracksFootprint`,
  `loopLive` (≥10 rAF frames), `everyInHoldStale`, `flipIndexPresent`, `flipWindowDecodable`, `enoughAfterFlip`,
  `releaseStrictlyBeforeSettleAndBurst`, `allInHoldMeasured`, `rehandoffPairSound`, `ownerSettledAllArms`,
  `bridgeEngaged`, `collectorSeriesSound`, `atCutBoundaryValidAllArms`, `badgeSamplesSoundAllArms`,
  `maxRafGapOk` (`maxRafGapMs <= 100`, folding the PRE-trigger poll gap; on a MOVING footprint a rAF stall leaves the
  cover behind the movie, so the 1→2 "diagnostic only" carve-out does not transfer), `noNegativeAnomaly`,
  `movingContinuityOk`, `boundDecoderIsSlide3Decoder`, `noOwnerAmbiguousInWindow`, `rvfcRanThroughHold` (≥0.5 s),
  `playerBuildErrorsEmpty`, `positivesGreen`, `isolationEqual`.
- **Verdict (PASS iff all three, else FAIL, and only once every integrity key holds):** `indexRunRed`,
  `reasonFreezeRunAtCut`, `freezeRunMargin`.
- **Nothing is satisfiable by absence.** `positivesGreen` and `collectorSeriesSound` RE-DERIVE the positives' at-cut run
  and the collector's admissibility from the raw samples rather than trusting the capture side's cached `ok`; the
  bracket and MAIN inputs are walked leaf by leaf in `test_bracket_absence_sweep_is_exhaustive` /
  `test_main_absence_sweep_is_exhaustive`, whose allowlists carry a one-line reason per surviving field (§10.14).
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
  `flipWindowDecodable` force INCONCLUSIVE, the honest outcome); does the cover stay within 0.5 px under rAF contention
  while CDP screenshots run; does `freezeRunAtCut >= 6` accumulate in the post-settle window at `DENSE_FPS`.

## 8. Owner decisions — ANSWERED 2026-09-20 (relayed via the DSK session; owner to confirm "go implement" directly)
a. `movingIndexRunAtCut`: REPORT-only until one clean fast/slow/bridge-off round, then gate.
b. Bridge-off arm: freeze verdict `skipped`, non-blocking in that arm only.
c. Hash-only trigger: INCONCLUSIVE.

## 9. Correction 2026-09-21 — the "motion starts on arrival at #7" premise error was an instrument artifact
Measured headless (bridge-on, every press landing): `#6` is the 2→3 dissolve in flight and SELF-ADVANCES to `#7`; on
settled `#7` the carried movie is static (x=198, w=951.5, 4 s, no `__obedMotion`). The drain pressed AT `#6`; the player
queues a press it cannot honour and replays it at `#7`, starting the real 3→4 move "on arrival". Fixed in `a94c2c81`
(press only below `#6`, wait for the self-advance, `drainPressesAllLanded` integrity key). Owner-approved follow-ups
(2026-09-21): hold A1/A2 to the drain check; couple the rect read to the capture in ONE in-page rAF and keep the "every
in-hold sample" rule; re-measure `FREEZE_TRIGGER_MAX_RAFS` on ≥10 clean runs (worst + 1); apply the same one-press
discipline to `_advance_to_slide4_capture` on the main gate path, then a full gate round.

## 10. Measurements (rounds 4–10)
Every number that used to live in a code comment lands here; the code keeps only the behavioural
invariant and a pointer to this section. Re-measure whenever the capture loop's per-frame cost
changes — all of the trigger bounds track the HARNESS, not the player alone.

### 10.1 `FREEZE_TRIGGER_MAX_RAFS = 9` — delivered poll frames, advance keydown → rect departure
Re-measured 2026-09-21 on 10 CLEAN freeze-arm runs (drain 5/5 landed, hash `#7` exact,
`firedVia == "moved"`, one press sent and landed): the departure landed on delivered poll frame 8 in
10/10 runs, at 157.8–173.4 ms after the in-page keydown, with a 17.1–17.7 ms rAF period. Not bimodal,
no outlier. Worst observation 8 plus one frame of margin ⇒ **9**.
The previous value of 3 was calibrated on runs CONTAMINATED by queued presses (the capture re-pressed
ArrowRight every 0.9 s through the move, so the move began at a replayed press, not at the one the
listener timed). The count is not a property of the player: it is delivered POLL frames, so it
absorbs how much the harness does per frame — 3–4 contaminated, 6–7 with the press fixed, 8 with the
footprint badge running.
A wall-clock-only ceiling is not defensible on its own: `keepThroughBridge` interpolates LINEARLY
(`src/obed_edom/live_continuity_js.py` ~L687) over 952→1266 px in `TRANS_S`, so the rect departs by
>1 px within ~5 ms.

### 10.2 `FREEZE_TRIGGER_MAX_DELAY_MS = 190.0` — page-clock keydown → trigger ceiling
The secondary bound for the defect a frame count CANNOT see: nine delivered poll frames can hide
unbounded elapsed time, because a keydown→rAF stall advances the runtime's time-based interpolation
deep into the move before poll frame 1 is ever delivered, and `maxRafGapOk` only starts at the trigger.
Rule: worst CLEAN observation plus one rAF period. Re-measured 2026-09-21 on the round-8 capture loop
(13 clean freeze-arm brackets, all `pass`): delay 156.7–172.1 ms (median 159.7) on delivered poll
frame 8 in 13/13, rAF period 17.1–17.3 ms. Unimodal, no outlier. 172.1 + 17.3 = 189.4 ⇒ **190**
(was 195 on the pre-round-8 loop, from 175.5 + 17.4).

### 10.3 `FREEZE_TRIGGER_MOTION_SLACK_FRAMES = 2`
`keepThroughBridge` creates `__obedMotion` inside its first SYNCHRONOUS `frame()`, which runs in a
task, so the poll can see the marker on the same frame it first sees the rect move, or one frame
earlier. Two callbacks of slack covers both. Round 7 adds marker IDENTITY on top of proximity
(§10.7), because proximity alone accepts a marker for another boundary or generation.

### 10.4 `INDEX_PATCH_TOP_GUARD_PX = 2` (src)
The x mapping carries a +2 inset; the y mapping carries none, so the ROI's first row sits exactly on
the footprint's own top edge. Harmless for a static integral rect; not for a live
`getBoundingClientRect()` reading, whose y is fractional, is badge-quantised to a quarter pixel (`FOOTPRINT_BADGE_Q = 4`), and which
`round()` sends to the EVEN integer — i.e. down, onto the movie's antialiased top edge row, which is
not flat, so the patch decodes None. Measured on the round-5 3→4 brackets: 3 of 260 captured samples
decoded None for this reason alone (badge y 734.5 / 744.5 / 746.5), each recovered by dropping
exactly 1 top row and yielding the same value as its neighbours. 2 px = that 1 px plus one row of
margin, against a measured bottom slack of ≥ 9 px.

### 10.5 Badge constants
- Coupling by reading the owner rect before and after a CDP screenshot is not a coupling at all on
  the fast part of the 3→4 move: the round trip is ~230 ms and the rect travels ~0.12 px/ms, so the
  two reads disagree by ~28 px, every such sample is `unstable`, and
  `allInHoldMeasured`/`everyInHoldStale` are unsatisfiable (measured, round 3). Hence the badge.
- `FOOTPRINT_BADGE_CELL_PX = 6`: 6 px cells decoded 100 % of painted frames live
  (`deviceScaleFactor=1`, PNG capture, so a cell centre is an exact pixel).
- Badge log ring = 4000 entries: the capture loop runs `(TRANS_S + POST_SETTLE_S + 3)` s at ~60 Hz
  and the whole log is dumped ONCE after it; 600 entries covered only ~10 s and the earliest sampled
  frames fell out.
- `dump()` is per-capture, not per-sample: a per-sample lookup is one more CDP round trip inside the
  hold. See §10.10 for why round trips turned out not to be the cost.
- `COVER_TRACK_TOL_PX = 0.5`: with the control loop handed off BEHIND the runtime's footprint pin the
  per-frame residual is 0 px over every hold frame of the live runs. A ONE-FRAME lag would show
  ~2.8 px in x at the 30 Hz headless rAF rate (~1.4 px at 60 Hz), so the tolerance cannot absorb one.

### 10.6 Re-handoff exemption (round 7 r4 BLOCKER 1; tightened round 8, r5 MAJOR 1)
The badge's re-handoff onto a fresh pin paints a NULL rect for exactly two consecutive frames, which
it logs in `rehandoffSeqs`. Only a LEADING covered sample whose badge sequence belongs to that pair,
with a null rect and nothing decoded, is excused from `allInHoldMeasured`;
`FREEZE_REHANDOFF_MAX_EXEMPT = 2` is that frame count. Every other post-paint sample through
`releaseSplitIndex` must be `measured`.

Round 8 closes four ways the exemption could be bought without a real re-handoff
(`rehandoffPairSound`, an integrity key): `badge.stats.rehandoffs` must be exactly 1;
`rehandoffSeqs` must be exactly one contiguous pair `(p, p+1)`; the badge's `motionStartedAt` must be
the trigger marker's own `started` (a pair from another generation proves nothing about THIS hold);
the captured exempt sequences must be unique and increasing; and every non-exempt covered badge
sequence must be `> p+1`, which is what actually PROVES the first measured covered badge is after the
re-handoff rather than assuming it. A null-rect sample also keeps `footprintSource == "badge"` through
`_fill_badge_coupling` now, so it takes that function's monotonicity checks instead of bypassing them
— a duplicate or reversed exempt sequence used to slip past.

### 10.7 rAF/task ordering under a later runtime pin (round 7, r4 MINOR 2)
Node-executed ordering model (`test_footprint_badge_lands_behind_a_later_runtime_pin_callback`),
with the pin ordered exactly as `keepThroughBridge` is (starts from a post-frame task, applies the
rect synchronously, re-queues from its own rAF callback):
- WITHOUT the re-handoff, every frame after the pin starts is lagged by exactly one pin step.
- WITH it, exactly ONE lagged frame remains — the frame the pin STARTS on, where the badge has
  already read before the task that creates the marker runs. That frame is strictly before the
  trigger (the first poll frame that SEES the departure) and therefore before `coverPaintedAt`, so it
  can never enter the scored window. Every frame that reads at all from the re-handoff onward is
  residual-0 against the pin's own rect.

### 10.8 The at-cut boundary (round 7; page clock round 8 r5 MAJOR 3; fail-closed round 9 r6 MAJOR 2)
Samples captured before the advance press are pre-move: the movie is still on its slide-3 rect, whose
counter has its own mapping, so they decode None BY DESIGN. The exclusion is a stated rule, never a
hardcoded index, so the `nDecodable` fraction carries no silent free miss; the raw samples stay in
`indexSamples` for diagnostics.

The boundary is a PAGE CLOCK, not a sample count. `_at_cut_boundary` returns the first badge frame
whose own `perfNowMs` is at or after the ArrowRight keydown's own event `timeStamp`, recorded
page-side in every arm (§10.12). `advancePressIndex + 1` was wrong in both directions: the press sample's screenshot is taken
AFTER the dispatch, so it belongs inside the segment, and an anomaly confined to it was being
discarded. Live: `atCutFrom == 0` in 13/13 — the keydown precedes the first badge frame, so the whole
capture is at the cut.

That makes `0` a legitimate boundary, so validity travels separately: `_at_cut_boundary` returns
`{"from", "ok", "reason"}` and answers `{"from": None, "ok": False}` for a missing or non-finite
keydown clock and for a keydown later than every badge frame. `_moving_index_run_at_cut` treats
`covered_from=None` as "no valid boundary" and refuses to score (never index 0), and
`atCutBoundaryValidAllArms` is an integrity key requiring a finite `advanceKeyPerfMs` and an in-range
`from` in A1/B/A2; MAIN carries the same condition in `advance_c_ok`.

### 10.9 Owner-rect settle (round 7, r4 MAJOR 2)
The hash reaching `#7` is an instantaneous value, not a settled build: the `#7` build's own animation
is still running when the drain stops, so arming there records a pre-advance departure and the run is
INCONCLUSIVE by construction (measured live). `_settle_bound_owner_rect` requires
`OWNER_SETTLE_READINGS = 3` consecutive rect reads agreeing under the same `_couple_owner_rect`
"measured" test the at-cut samples use, within `OWNER_SETTLE_S = 5.0` s, and fails closed. Both the
bracket and the MAIN gate path now use it, in the order: exact `#7` → bind → rect settle → one press.

### 10.10 Capture-loop cost (round 8, r5 MAJOR 4)
The per-sample owner / media / preserve-pool round trips are gone: they are collected page-side per
rAF by `CAPTURE_COLLECTOR_JS` and dumped ONCE, so the loop is the screenshot plus the scene hash.
Measured on this machine, same bake, same driver, `Page.captureScreenshot` count unchanged:

| | CDP calls / sample | CDP ms / sample | loop wall / sample | maxRafGapMs (clean runs) |
|---|---|---|---|---|
| before (`de0cedfd`) | 7.24 | 82.6 | 95 ms | 55.6 / 56.7 / 58.0 (n=3) |
| after | 2.16 | 81.1 | 93 ms | 46.9–64.3, median 55.9 (n=13) |

**The round trips were never the cost.** Removing 5.1 CDP calls per sample moved CDP time per sample
by ~1.5 ms; `Runtime.evaluate` on a local socket is ~0.2 ms. `Page.captureScreenshot` is ~100 ms and
is frame-synchronised, not encode-bound — measured over 30 captures each at `deviceScaleFactor=1`:

| variant | median | badge decodes |
|---|---|---|
| `format=png` (current) | 99.9 ms | yes |
| `optimizeForSpeed=true` | 100.0 ms | yes |
| `clip` to 1601×1073 (every scored ROI + badge + hit-test point) | 101.6 ms | yes |
| `clip` + `optimizeForSpeed` | 101.4 ms | yes |
| `fromSurface=false` | 433.6 ms | NO |
| `format=jpeg` q95 | 100.0 ms | NO |

No parameter reduces it; the two that change the pixels (`jpeg`, `fromSurface=false`) break the badge
decode outright. So the screenshot stays exactly as it was. `MAX_RAF_GAP_MS` is NOT raised: on 13
clean round-8 brackets the largest gap was 64.3 ms, 36 ms inside the 100 ms bound. Round-8 ran three
batches; the logs record the 1-minute load at the start of only two of them (8.7 and 5.4), so the
third is unattested. Round 9 re-measured on the fail-closed build: 6 clean brackets in two batches
started at load 5.2 and 5.5 (max gap 53.8-57.8 ms, trigger delay 158.4-162.9 ms, 8 frames in all 6),
plus the e2e fast run at load 6.9. Round 10 re-measured on the raw-clock build: 6 clean brackets in
two batches started at load 5.1 and 8.5 (max gap 52.0-59.9 ms, trigger delay 158.0-163.9 ms, 8 frames
in all 6), every arm's collector whole (0 unbracketed / 0 dropped / 0 errors / 0 `neighbourFillable`,
521-527 rows) and every arm's badge clean (0 missing / 0 CRC-bad / 0 unlogged / 0 sequence
violations, 102/102 `measured`), plus the e2e fast run at load 6.0. Every load figure here is the
`uptime` 1-minute average printed at the head of that batch's own log.


### 10.11 Collector series integrity (round 9, r6 MAJOR 1)
The page-side series (§10.10) is evidence, so it is fail-closed as evidence. The dump carries its own
metadata — row count, first/last page clock, rows the ring dropped, page-side errors — and
`_collector_series_meta` additionally requires every row to carry `COLLECTOR_ROW_FIELDS` in
non-decreasing time order. `_collector_rows_for` no longer extrapolates: a sample is admissible only
when a real row lies at or before it AND a real row lies strictly after it, so a truncated dump
cannot hand a capture its neighbours' owner/media rows. `collectorSeriesSound` (rows present,
schema intact, monotonic, `dropped == 0`, `errors == 0`, every capture bracketed) is an integrity key
across A1/B/A2 and part of MAIN's `advance_c_ok`.

Strict bracketing and the drop counter catch **different** failures, and the gate needs both (r6
MINOR). Strict bracketing catches a TRUNCATED endpoint: a series that started after the first
capture, or ended before the last, leaves that capture with no row on one side. It does NOT catch an
interior gap — a sample falling inside a window the ring overwrote is still bracketed by the healthy
rows on either side — so the cumulative `dropped` counter is what catches OVERWRITTEN rows, and
`dropped == 0` is load-bearing, not belt-and-braces.


### 10.12 Each capture's own clock (round 10, r7)
Two substitutions were dating evidence from the wrong instant.

**Collector integrity takes RAW `perfNowMs`.** A capture whose badge went missing, tore its CRC or
named a frame the page never logged has no clock of its own. Filling it from a neighbour let a
post-cover/pre-flip frame borrow that neighbour's collector rows, keep `unbracketed == 0`, and then
drop out of `allInHoldMeasured`/`everyInHoldStale` entirely — a live counter or wrong ROI on that one
frame disappeared, and the later frozen frames carried a PASS. `_collector_sample_times` is now the
one seam the capture loop brackets against, a `None` counts as unbracketed, and `_nearest_sample_times`
survives only as the diagnostic `collector.neighbourFillable`, scored by nothing. The same
substitution let a collector that started late or ended early keep MAIN's `advanceOk` true when the
uncovered endpoint had no badge clock; on raw clocks both endpoints are unbracketed.
`badgeSamplesSoundAllArms` refuses the underlying gap in its own right: zero missing, CRC-bad,
unlogged and sequence-invalid captures in every arm. The re-handoff pair is not an exemption here —
its deliberate null rects still decode, still check their CRC and are still logged.

**The cut instant is the KEYDOWN's, measured page-side.** `advanceKeyPerfMs` was a
`performance.now()` read after the awaited `keyDown` and `keyUp` CDP round trips, so it ran LATE; a
badge painted inside that window was after the real cut but before the recorded one, and
`_at_cut_boundary` excluded it — discarding exactly the first-frame reset the control exists to see.
MEASURED (round 10, 18 arms over 6 brackets at load 5.1–8.5, plus 3 e2e arms): the post-dispatch read
lags the keydown by **0.7–1.1 ms, median 0.9 ms**. That is well inside one 17 ms capture period, so on
this machine the old clock almost never moved the boundary — the exposure was real but latent, and it
is a round trip, not a bounded quantity. `atCutFrom == 0` in all 21 arms either way.
`ADVANCE_KEY_WATCH_JS` now arms a capture-phase one-shot `keydown` listener BEFORE dispatch and
`_advance_key_clock` takes its event `timeStamp`, and only when the page saw EXACTLY ONE matching
event: zero (the dispatch never landed) or more than one (a replay, or a drain press still in flight)
yields `None`, which `_at_cut_boundary` fails closed.

**Badge TRANSPORT is not badge GEOMETRY (round 11, r8 MAJOR 1).** The `badgeSamplesSoundAllArms` gate
above proved only that each capture carried a badge: installed, decoded, CRC-valid, logged, in
sequence. It ignored what that badge *said*. A badge can satisfy every one of those and still name a
rect that disagrees with the page's own log for that frame — `_fill_badge_coupling` settles such a
sample `unstable`, which means its ROI was read at the wrong place, so its decoded counter value is
junk. The positive arms discarded those samples through their measured-only filter, but the gate
itself stayed green, and MAIN did not filter `slide4IndexSequence` by `footprintSource` at all, so a
wrong-ROI or `None` decode could sit in finding 13's scored sequence. `_badge_samples_sound` now
additionally requires `install.ok is True`, `decoded == len(indexSamples)`, and that EVERY sample is
`measured`. The single exception is the re-handoff pair's two deliberate null-rect frames, and it is
not a property of the sample: the scorer passes the pair in as `exempt_seqs` only once
`rehandoffPairSound` has validated it (§10.6), and a sample that actually decoded a rect is never
exempt. MAIN applies the same gate plus a measured-only filter on the settled slide-4 window, and
fails `advanceOk` closed if that filter removes anything — there is no re-handoff on MAIN's path, so
the admissible loss is zero. The MAIN gate is extracted as `_advance_c_ok` purely so it can be
unit-tested; it is the same conjunction that was inline.

### 10.13 The advance keydown is COUNTED, and only a trusted one counts (round 11, r8 MAJOR 2)
§10.12's predecessor recorded the keydown page-side but only *used* the exact-one rule while
producing `advanceKeyPerfMs`. The scorer never required the count itself, and no pass-capable fixture
carried it — so a snapshot with a finite (or stale) timestamp and a missing, zero or doubled event
count could reach PASS. The listener also accepted any `ArrowRight` keydown, including a synthetic
one dispatched by page script (`isTrusted === false`) and an auto-repeat burst held down by the OS.
Both can advance the player, so both change the stimulus while the count still reads 1.

The watch now filters on `e.type === 'keydown' && e.key === 'ArrowRight' && e.isTrusted && !e.repeat`
and COUNTS what it refuses (`rejected`) rather than dropping it silently — a refusal that is not
counted is indistinguishable from an event that never happened, which is the same absence bug one
level down. `_advance_key_clock` yields the timestamp only for `n == 1 && rejected == 0`, and
`_advance_key_observed_once` re-checks both counters in `_at_cut_boundary_valid` (all three arms) and
in MAIN's `advanceOk`, rejecting bools and missing keys explicitly. `advanceKeyEvents: 1` and
`advanceKeyRejected: 0` are now part of the shared clean fixture. MEASURED (round 11, 21 arms over 7
clean brackets at load 4.6–7.1, plus 3 e2e arms): `advanceKeyEvents == 1`, `advanceKeyRejected == 0`
and `atCutFrom == 0` in every arm; the keydown→post-dispatch lag re-measured at **0.7–1.2 ms, median
1.0** (consistent with round 10's 0.7–1.1).

**Absence sweep (round 11, pre-emptive).** Three consecutive rounds found the same defect class: a
new integrity key read a field the pass-capable fixture never carried, so the key was satisfied by
ABSENCE and the "positive" proved nothing. `test_no_integrity_key_can_be_satisfied_by_absence` now
takes the clean bracket and, for every integrity key the scorer scores, deletes the snapshot field(s)
that key is argued from and asserts the verdict falls to INCONCLUSIVE;
`test_absence_sweep_covers_every_integrity_key` asserts the case table names exactly the scorer's own
`integrityKeys`, so a key cannot be added without one. The same sweep runs over MAIN's `_advance_c_ok`
inputs. Two keys are negative assertions (`noPreAdvanceDeparture`, `noControlError`) whose green state
IS an absent value; deleting their whole `nullControl` block short-circuits to "hold never fired",
which is inconclusive, and they are never reached. The sweep immediately caught a real hole:
`maxRafGapOk` was `max(gaps) <= ceiling` over a possibly EMPTY series, i.e. green with no series to
measure at all; it now requires a non-empty rAF series as well.

**Live before/after control (round 11).** The first five brackets of the round came back
`inconclusive` on `firedAtMoveStart` (keydown→trigger 208–256 ms against the 190 ms ceiling) with rAF
gaps of 93–158 ms. That was NOT the change: run interleaved against the pre-change module on the same
machine, AFTER went 4/4 `pass` and BEFORE 4/4 `pass` with identical timings (delay 157–164 ms, gap
54–68 ms). The five bad brackets ran while the machine was still draining a just-finished gate round
(15-minute load average 7.18 decaying). Recorded because the trigger bounds track the HARNESS, not
the player: a loaded machine reads as a stimulus failure here, and the honest response is the
interleaved control, never a wider ceiling.

### 10.14 The absence sweep is EXHAUSTIVE, not hand-picked (round 12, r9 MAJOR 1–4 + owner instruction)

Round 11's sweep was written per integrity KEY: one deletion per key, chosen by the author from the
field that key is argued from. Round 9 of review then found four more holes of exactly the class the
sweep existed to close — `advanceKeyPerfMs` and `atCutBoundary.from` on MAIN, `nullControl.pollMaxGapMs`
(absent read as a `0.0` gap), `releaseSplitIndex` and `firstSettledPerfMs` (the latter explicitly
accepted when absent). A per-key sweep can only cover the fields its author already thought of, which
is the same blind spot that produced the holes.

It is now a WALK. `test_bracket_absence_sweep_is_exhaustive` enumerates every leaf of the clean,
pass-capable bracket — both arm classes, nested dicts, and the leaves of every dict inside every list —
deletes each in turn, and requires the verdict to fall to INCONCLUSIVE; `test_main_absence_sweep_is_exhaustive`
does the same for `_advance_c_ok`. A field counts as gated when deleting it from ANY list element
fails closed (a sample outside the scored window is not an absence hole). Anything that survives its
own deletion must be named in `_SWEEP_ALLOW` / `_MAIN_SWEEP_ALLOW` with a one-line reason, in one of
four classes — report-only, redundant (a view of a gated field), provenance (an input the PAGE used
for a sub-verdict the scorer re-derives or reads only as `ok`), and negative (the key asserts absence,
so its PRESENCE is what `_ABSENCE_CASES` tests). A companion test refuses a DEAD allowlist entry, so
a reason cannot outlive the hole it excused.

The walk found two ungated classes beyond the review's four, both the "trust a cached verdict" shape:
`collectorSeriesSound` read the page's `collector.ok` while every field that `ok` was computed from
could be deleted, and `positivesGreen` took A1/A2's at-cut run from the capture side's cached
`movingIndexRunAtCut` — so the positives' `index`, `perfNowMs`, `progress` and `sceneHash` were not
gated at all. Both now RE-DERIVE (`_collector_ok`, `_moving_index_run_at_cut`) from the raw snapshot
and require the derivation to agree with what the capture reported. A third, `stageGeometryStable`,
raised `KeyError` instead of failing closed on a rect missing a component; numeric reads go through
`_finite` now (absent, boolean and non-finite are all "no measurement", never a zero).

The null CONTROLLER's own `onAdvanceKey` was the last asymmetry: the capture watch filtered for a
trusted, non-repeat `keydown`/`ArrowRight` while the controller accepted any `ArrowRight` and stamped
`performance.now()`, so a synthetic or repeated press just before the real one could seed the
controller's clock while the watch timed the trusted event, and nothing proved the two clocks named the
same event. The controller now applies the identical filter, records `e.timeStamp`, and counts what it
rejected; `advanceKeySameEventInControl` requires `nullControl.advanceKeyAt == advanceKeyPerfMs` and a
zero rejection count, and `atCutBoundaryValidAllArms` continues to hold all three arms to the watch's
own counts.

### 10.15 The scorer RE-DERIVES, and the sweep walks the REAL bracket (round 13, r10 MAJOR 1–5 + MINOR 1)

Round 12 closed the cached-verdict class for `collectorSeriesSound` and `positivesGreen` only. Round 9
of review found the rest of it: the scorer still accepted the capture side's own sub-verdicts and
derived labels wherever the raw evidence was retained, and the harness's OR-aggregated sweep on a
hand-built fixture could not see it.

**The at-cut boundary is re-run, not range-checked.** `_at_cut_boundary_valid` verified only that the
cached `atCutBoundary.from` was an in-range integer, so a stale LATER index discarded the first
post-keydown reset the control exists to catch. It now re-runs `_at_cut_boundary(indexSamples,
advanceKeyPerfMs)` and requires exact agreement. The same shape sat on the release ordering:
`lastAtCutPerfMs` was taken from the capture, so a stale EARLIER value could claim the release
followed the final covered capture when `indexSamples[releaseSplitIndex].perfNowMs` said otherwise. It
is read off the validated split sample now, and the reported field must agree.

**Every re-derivable gate is re-derived and held to its cache.** `_advance_ok_derived` rebuilds the
press state from `pressesSent`/`pressesLanded`/`unlandedFromHash`/`outstandingAtEnd`/`pressingStopped`
and re-runs `_advance_gate`; `_drain_clean` rebuilds `allPressesLanded`/`hashAtArmExact` from the
recorded counts and `hashAtArm`, which must be the arm's own `armHash` AND the exact `#7`;
`_settled_progression_ok` re-scores the post-split settled window. `_owner_settle_ok` replays the
ordered rect readings the settle loop now RETAINS (`ownerSettle.readings`) through the same
`_couple_owner_rect` run — a stable count and a Boolean were two more derived values, not the readings
they came from. `movingContinuity3to4` is RE-RUN from `ownerSamples` and the newly retained
`mediaSamples`: without the media series a stale green could hide a handoff or an rVFC rewind, and
`rvfcRanThroughHold` now reads the derived advance. `bridgeEngaged` is DERIVED from `bridgeEvents`
validated for movie key, a scene at or beyond slide 4, the bound slide-3 decoder as `oldElId`, and a
preserve generation matching the one current when it fired (`oldGen`/`generation`, added to the
runtime's `bridge-3to4` note) — a snapshot claiming `bridgeEngaged` with no events is INCONCLUSIVE.
`_isolation_view` is built from the same derivations, so `isolationEqual` compares evidence rather
than cached booleans; `footprintFullyLive.ok` stays cached because the burst pixels it is scored from
are not retained.

**MAIN re-derives the collector too.** The bracket re-ran `_collector_ok`, but `_advance_c_ok` read
only `collector.ok`, so a truncated, dropped or unbracketed MAIN series with a stale `ok` stayed
green. It calls `_collector_ok` and requires agreement, and the nine MAIN allowlist entries that
excused the collector primitives are gone — as are the seven advance primitives.

**A badge sample is held to its OWN evidence.** `_badge_samples_sound` trusted each sample's derived
`footprintSource == "measured"` and the aggregate counters, so a covered sample could lose its clock
and drop out of `covered_positions`, or keep a stale "measured" label after its coupling evidence
disappeared. Every non-exempt sample must now carry a finite `perfNowMs`, a typed and STRICTLY
INCREASING `badgeSeq`, both `measuredRect` and `badgeRect`, and must re-satisfy
`_couple_owner_rect(measuredRect, badgeRect) == "measured"`. The re-handoff pair is validated
separately through `_is_rehandoff_sample`, as before.

**The pass fixture is a real live bracket, and the walk keeps its positions.** The hand-built bracket
could only model fields its author had thought of — it carried `bridgeEngaged=True` with
`bridgeEvents=[]` and no rect evidence at all. `tests/fixtures/p2_freeze_3to4/clean_bracket.json` is
the verbatim A1/B/A2 snapshot triple of one clean live run (round 13, run 1300), 515 KB, with nothing
dropped: the sweep walks the production shape. The walk also kept COLLAPSING list indices and ORing
the results, so one deletion that failed closed marked the whole field gated. Positions are now kept
apart and aggregated with AND; a field gated in some positions only must be classified in
`_SWEEP_PARTIAL_ALLOW`, and the headline case is asserted rather than excused — deleting a capture's
decoded `index` fails closed at EXACTLY the 23 in-hold positions the freeze is scored over.

MEASURED (round 13): the bracket walk covers **17 821 concrete indexed paths** (102-sample arms),
210 fully gated collapsed fields, 361 survivors on the allowlist and 5 partials; MAIN's covers 8 152
paths, 39 gated, 202 survivors, 0 partials. Deletion is done by mutate-and-restore rather than a deep
copy per case (the real fixture makes the copy the dominant cost); the two suites run in ~65 s.
Live: 5/5 brackets PASS at load 4.1–6.3 (trigger delay 159–164 ms, poll/rAF max gap 55–60 ms, 8
delivered frames, keydown→post-dispatch lag 0.7–1.2 ms median 1.0, 1 keydown per arm, zero badge
missing/CRC-bad/unlogged/sequence violations), plus one e2e fast bridge-ON run with
`freezeControlCaughtByCounter: True` and `success: True`.

### 10.16 Schema BEFORE windowing, and the footprint verdict re-scored from pixels (round 14, r11 MAJOR 1–5 + MINOR 1–2)

Round 13 re-derived the sub-verdicts but kept one structural hole underneath them: every derivation
picks its window with `sceneHash`/`progress` first and scores `index`/`decoderId`/`videos` inside it,
so DELETING one of those keys did not make the gate red — it moved the window off the sample that
carried the bad evidence. The sweep read that as "gated in the scored positions, diagnostic
elsewhere" and allowlisted it. A pre-flip reset at position 5 reddened the positive; deleting only
that `index` made it green again.

**One schema validator, before any window is selected.** `_samples_schema_ok` /
`_media_samples_schema_ok` / `_sample_schema_failures` run FIRST in `_score_freeze_control` (integrity
key `sampleSchemaSoundAllArms`, all three arms) and first in `_advance_c_ok`. Every sample must CARRY
every required key; an explicit `None` is admissible only where the model permits one, and exactly two
keys do: `indexSamples[*].index` (an undecodable badge patch is a real reading, and
`score_composited_index_run` scores it as one) and `ownerSamples[*].decoderId` (a transient unresolved
footprint owner, which `stableSlide4Owner` already tolerates up to 30% of the window). Required with
no null admitted: `indexSamples` `sceneHash`/`progress`/`perfNowMs`/`footprintSource`; `ownerSamples`
`sceneHash`/`ownerAmbiguous`; `mediaSamples` `sceneHash`/`videos`; and `decoderId` on EVERY entry
inside `videos` — an unattributable entry could be the bound decoder's. `badgeSeq`, `measuredRect` and
`badgeRect` are deliberately NOT in the schema: `_badge_samples_sound` already holds every sample to
them, with the argued re-handoff exemption that a blanket presence rule would break (measured: the one
re-handoff capture legitimately reads null rects — it fired in live run 1401).

**The bound decoder's rVFC clock must exist, once, per after-window sample.** Each `mediaSamples`
entry at or beyond `SLIDE4_MIN_HASH` must hold exactly ONE finite `presentedMediaTime` among the
entries whose `decoderId` is the bound decoder. No reading, a non-finite one, or two that disagree is
no reading at all. Measured on the fixture: every after-window sample carries exactly one.

Eighteen collapsed fields per positive/B class are GONE from the blanket allowlist as a result (36
bracket entries): `indexSamples` `index`/`sceneHash`/`progress`, `ownerSamples`
`sceneHash`/`decoderId`/`ownerAmbiguous`, `mediaSamples` `sceneHash`/`videos`,
`videos[*].decoderId`, `bridgeEvents[*].kind`, and the eight `footprintFullyLive` sub-verdicts; MAIN
loses its three `indexSamples` entries and its eight `ownerSettle` ones. All five
`_SWEEP_PARTIAL_ALLOW` entries go with them. ONE partial remains and is asserted, not
excused: `videos[*].presentedMediaTime` fails closed at exactly the bound decoder's entries in the
after-window samples and nowhere else.

**The bridge event must BE the bridge.** `_bridge_engaged` validated the detail but never the `kind`,
so a `reuse-decoder` event — same detail shape — carried the bracket. It requires
`kind == BRIDGE_EVENT_KIND` before looking at detail.

**MAIN's two settles are derived from their readings.** `_advance_c_ok` accepted
`{"settled": True, "readings": []}` and `{"exact": True}` — binding during the `#7` build's residual
motion can retain both. It now calls `_owner_settle_ok` on the real readings and
`_advance_settle_exact`, which requires `hashAtAdvance` to PARSE as the exact `#7` and `expected` to
say so. The MAIN sweep walks the real argument dicts (the owner settle IS `snap["ownerSettle"]`, so
the snapshot walk covers it; the advance settle is walked as its own class, keyed like the bracket's
by `(class, path)`).

**`footprintFullyLive` is re-scored from the pixels it was scored on.** `ok=True` over a summary
saying `verdict=False` still passed: a material fail-open, and a digest would only have authenticated
bytes nobody could re-score. `score_visible_slide` is split into `score_visible_slide_from_delta`, so
the whole verdict is a pure function of the burst's max-delta raster; the capture retains that raster
losslessly under `footprintFullyLive.evidence` together with the frame count, dimensions, rects and
the ten scoring parameters. `_footprint_fully_live_ok` decodes it, re-runs the SAME scorer with the
recorded parameters, and requires agreement on `n`, `verdict`, `status`, `noiseFloor.verdict`, every
`perRect[*].verdict` and label, and `stray.verdict`. MEASURED: PNG-grayscale beat raw zlib on every
arm of every run, so PNG is what is stored — 2 733–3 418 B per 1920×1080 raster (3 644–4 560 B base64;
4.1/4.8/4.1 kB of JSON for A1/B/A2), and the fixture grew 528 kB → 542 kB. The re-score is memoised on
the blob so the sweep's ~26 000 deletions do not each decode it.

**A1 and A2 are two different runs' worth of evidence.** The harness copied A1 into the A2 slot, so
value-dependent positions in the committed A2 were never scored. `_a2_snap_34()` loads the fixture's
own A2 and the sweep walks it as a third class.

MEASURED (round 14): the bracket walk covers **26 063 concrete indexed paths** across three arms
(was 17 821 across two) — 9 707 in B, 8 178 in each positive — 418 fully gated collapsed fields, 472
survivors on the allowlist and 1 partial field (3 entries, one per arm); MAIN's covers 8 181 paths
(8 178 snapshot + 3 advance settle), 53 gated, 217 survivors, 0 partials. The two suites run 620 tests in ~124 s (was 562
in ~65 s; the third arm and the raster re-scores account for it).
Live: 5/5 brackets PASS at load 3.8–7.5 (trigger delay 121–175 ms, poll/rAF max gap 40–64 ms, 7–8
delivered frames, 1 keydown per arm, zero badge missing/CRC-bad/unlogged/sequence violations), plus
one e2e fast bridge-ON run with `freezeControlCaughtByCounter: True` and `success: True`.

### 10.17 Evidence bound to its arm, and absence bounded (round 15, r12 MAJOR 1–3 + MINOR 1–5)

Round 14 retained the burst raster and re-scored it, but bound it to nothing: the re-score read the
raster's shape, its frame count, its rectangles and its ten thresholds out of the blob itself, and
compared only booleans. Four pure-scorer probes reached PASS — A1's raster in B's slot, the frame
count edited 12→2, the raster padded to 1921×1081, and an all-zero raster carrying parameters slack
enough to call itself live. The same round left two kinds of ABSENCE unbounded in the scored windows.

**The raster is bound to its arm and to a fixed capture contract.** `FOOTPRINT_BURST_SHAPE =
(1080, 1920)` (the deck's stage, which every ROI here is measured in) and `FOOTPRINT_BURST_FRAMES =
len(BURST_OFFSETS_MS) = 12` are constants, and `_footprint_evidence_bound` requires the evidence to
carry exactly them, plus rectangles, control rect and parameters EQUAL to the module's own — the
re-score then passes the CONSTANTS to the scorer, so a blob can no longer weaken the thresholds it is
judged by. `_decode_delta_raster` takes the contract's shape as an argument and checks it BEFORE any
pixel is decoded. Each arm mints a `captureId` before it captures anything and retains it TWICE — in
the snapshot header and inside `footprintFullyLive.evidence` — so a raster lifted from another arm
names a capture that is not the one being scored; a mismatch is INCONCLUSIVE. Per-frame sha256 of the
12 burst frames travels as provenance (the PNGs do not). Forgery is explicitly NOT in scope: this
binds the instrument against its own bugs, and self-described metadata could never authenticate
provenance anyway.

**The comparison is the COMPLETE result at tolerance 0.** `_footprint_fully_live_ok` requires
`cached[k] == derived[k]` for every key the re-score produces — `liveFrac`, `maxDelta`, the clipped
rects, the noise floor's p99, the strays, not just the booleans. MEASURED: the re-score reproduces the
committed numbers EXACTLY on all three arms, so there is no measured reason for any tolerance. The
sweep records it: 54 `footprintFullyLive` numeric fields left the allowlist as now-gated.

**`None` counter reads are a bounded acquisition miss.** Both index scorers drop null-adjacent
deltas, so a `None` deletes the step across it from the progress and freeze-run totals, and a run of
them deletes an interval a reset or a freeze can hide in. `_null_reads_admissible` bounds every scored
window: at most `SCORED_NULL_MAX_RUN = 1` consecutive; at most `AT_CUT_MAX_NULLS = 1` in an at-cut
segment and `SETTLED_MAX_NULLS = 0` in a settled one; and an INTERIOR null must be bridged by a
plausible forward step `1 <= d <= NULL_BRIDGE_MAX_STEP = 60` (twice `score_index_progression`'s own
30-per-step ceiling, one step being what the miss deletes) — a zero step across it is the freeze the
gate exists to catch. An EDGE null cannot earn a bracket and is admitted on the count alone.
MEASURED over 33 clean arms: EXACTLY one at-cut null per arm, always at position 0 (the badge patch
has not settled at the first read after the advance), never two consecutive, ZERO nulls in every
settled window, and a largest single forward step of 12. Applied in `_moving_index_run_at_cut` (so B
and both positives alike), `_settled_progression_ok` and `_advance_c_ok`.

**Null footprint owners are bounded per GAP, not by the aggregate.** `nonNullFrac >= 0.7` admitted a
single blind interval of nearly a third of the after-window; the probe nulled the first 24 of 80 and
still passed. `_owner_null_gaps` bounds each run inside the window at `OWNER_NULL_MAX_RUN = 5` and
requires the nearest RESOLVED readings on either side — searched in the FULL owner series — to exist
and name the SAME decoder. MEASURED over 27 clean arms: ONE gap per arm, always leading, 4 or 5 of
~80, never more; it straddles the boundary (the box is mid-flight and `elementFromPoint` resolves
nothing while it moves), and its left bracket therefore lies BEFORE the window — taking it from the
full series is what makes the check non-vacuous instead of skipped. A trailing gap has no right-hand
bracket and fails closed.

**NOT closed as worded.** r12 MAJOR 3 also asked to "attest no competing decoder overlaps the
footprint during the gap (the `mediaSamples`/`videos` rects are retained — use them)". Those rects are
not retained: `videos[*]` carries `w`/`h` as `videoWidth`/`videoHeight`, with no screen rect. Worse,
a clean run legitimately carries a SECOND decoder on the same `Untitled.mov` asset — the export's
suppressed restart element — so an asset-keyed "no competing decoder" attestation would red the clean
bracket. A geometric attestation needs a per-video screen rect and a visibility flag added to
`MEDIA_PROBE_JS` (a shared probe, and a third fixture-shape change), and it cannot be calibrated
without its own live round. Deferred, with the bounded-and-bracketed gap above standing in.

**MINORs.** `_decode_delta_raster` is fail-closed (`img.format == "PNG"`, contract dimensions
enforced before load, a context manager, and Pillow's decode/decompression errors caught → `None`).
The "exactly one" bound-decoder rVFC clock is a LIST with `len(matches) == 1`, so two duplicate
entries no longer collapse through a set. Each arm now takes the SAME `_settle_at_advance_hash`
reading MAIN does and persists it as `advanceSettle`, so `_main_inputs` loads a captured block
instead of rebuilding one from `drain.hashAtArm` — and since both settles are members of the
snapshot, MAIN's sweep is one walk. The two remaining review narratives are cut. The positive
allowlist is defined ONCE as `_POSITIVE_SWEEP_ALLOW` and keyed per class, so A1 and A2 cannot drift.

MEASURED (round 15): the bracket walk covers **26 122 concrete indexed paths**, **481 fully gated**
collapsed fields (was 418), **457 survivors** (was 472) and the same 1 partial field (3 entries);
MAIN's covers **8 194 paths**, 53 gated, 230 survivors, 0 partials. The two suites run **653 tests in
~126 s** (was 620 in ~124 s). The fixture is re-captured from live run 1504 and grows 541 kB → 599 kB
(the `captureId`, the `advanceSettle` block and 3 × 12 frame digests).
Live: **7/7 brackets PASS** on the new code at load 3.4–8.8, plus one INCONCLUSIVE on `maxRafGapOk`
(131 ms) during a load spike to 8.75 — an INTERLEAVED before/after control at load 6.5 put the old
and new modules at 3/3 PASS each with `maxRafGap` 53–60 ms on both, so that inconclusive is the
machine, not this round. One e2e fast bridge-ON run: `freezeControlCaughtByCounter: True`,
`success: True`. The three BEFORE captures re-scored under the new gate come back INCONCLUSIVE on
`isolationEqual` — old-shape evidence carries no `captureId`, which is the binding working.
