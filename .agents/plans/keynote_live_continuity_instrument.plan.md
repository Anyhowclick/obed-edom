# S2 instrument stream: final plan, per-frame "painted"

**Owner: LGTM 2026-10-10 — all 14 recommendations accepted. Test additions stay minimal (max coverage, fewest new tests). Stream D also carries the end-of-show hold (owner decision (a)).**

Head `63606556` (worktree `obs-mac-camera-swap-fbc63b`, branch `claude/s2-detach-fix`). Evidence lives in the main checkout under `output/evidence/`. I made this plan read-only: I ran no Chrome, gates or pytest.

## Can it start now, or must it be serial?

**The code can start now, in parallel. Anything that runs Chrome or a test suite is serial.**

**Now: write the code in A, B and C** (and D, once the owner confirms it). Each stream gets its own fresh worktree off `63606556`, so no two implementers share a git index. The streams own disjoint files and need no browser.

**Serial, one heavy job at a time machine-wide, at most 3 Chromes.** This covers every Chrome run (smoke, controls, null sweep, Pass G, `run_gates`) and every full-suite run.
- They all wait behind the main fix's live round, which is running now.
- Even a single-file pytest waits for the coordinator's go between rounds. A suite run once voided a timed round (`.agents/reviews/gates-speedup-2026-10-09/gate-record.md`).
- Node-only JS checks are fine.

**Manage these before spawning:**
1. **Another main fold is in flight.**
   - A worktree `scratchpad/main-fix-freeze` exists at `87f8c450`, for the freeze-bracket fix in triage-r3. Main r3 was also not clean: its carry-cover null came back INCONCLUSIVE, a 66.7 ms gap against 58.45 ms allowed (`triage-2026-10-10/carry-cover-D1-lag.md:43`).
   - That fold lands in `live_continuity_probe.py` and maybe `run_gates.sh`. B and C keep their additions in new functions and blocks, and merge the fold before V1.
2. **`s2-r10-tests` is active.** The coordinator must confirm which files it edits. If they include `tests/test_live_continuity_probe.py`, B branches from its commit.
3. **Stream D changes core bytes.** It must land before the live controls V2–V5, or those controls re-run.
4. **Spawn each implementer from a session rooted in that stream's worktree.** The session-isolation hook blocks writes across worktrees (evening handover, "Machine").

---

## 1. Goal and non-goals

### Goal
For every frame inside every scored carry window, prove from the DOM that the carried decoder is the only element painting its slot. This covers pins and bridges in sequential arms, red arms and Pass G advance legs. Count every violating frame with zero tolerance. Prove the sampler saw every frame, or return INCONCLUSIVE, which is a fail.

### The false green it closes (verified)
- `score_continuity` checks the owner only on move, move-complete and after rows (`live_continuity_probe.py:2013-2014`).
- Pins have `transitionScene=None` (`verdict_specs` `:1251`), so `move_rows` is empty. The whole Magic Move is in `before_rows`, which are checked only for `isConnected` and rect (`:2025-2027`).
- Rows come from `querySelectorAll('video')` (`:504`), so `isConnected` is always true.
- `phaseD-867e415c/deck-D5-1920x1080.json` (old core): b0to1 reads True, with every move row present, at rect, `readyState` 4 and owned. pingap shows 108 dark frames for the same move.
- The ancestor walk in `isCompositing` (`live_continuity_js.py:1287-1299`) does not help pins, because pin before-rows are never owner-checked. The blindness rescore (§4) proves this live.

### A finding that predates the instrument (from reading the code, not yet run)
`fbba575e` made `isCompositing` walk ancestors. Alpha/attach mode injects `#body{opacity:0}` inline and `!important` until `show()` (`live_host.py:425-428`). Neither `run_arm` (`:3097`) nor `run_attach_arm` (`:3233`) calls `show()`; only the V pass (`:3831`) and Pass G (`:4857`) do.

So on the next S2 host gate, the attach arm's `footprintOwnerDecoderId` should return `{elId:null, via:'none'}`. That is a readable dict, so `_carry_integrity_gap` (`:2582`) does not demote it, and every attach carry would read **False** through owner mismatches on after rows. No S2 host gate has run since `fbba575e`; `cc-D1-63606556` is carry-cover only.

This is why `show()` is commit B0, measured in V1 before anything else is attributed. Launch-mode arms are not affected: `#obed-output-black` is a sibling, not an ancestor.

### What the DOM cannot see (named, not hidden)
| Not visible | Why | Covered by |
|---|---|---|
| GL content: poster copies, rubber band, the ~7 ms poster lag | Drawn in the transition canvas | carry-cover (bridges; P2 only in `run_gates`) |
| Occlusion by a later canvas or layer | `elementsFromPoint` is blind (`pointer-events:none`) | Pixels only. Held decoders on `#body` are pixel-proven above the GL canvas **for bridges** (eased S2 D1: ≤95 exposed px, `rubber/s2D1-eased/expose.json`). Pins use the same container but were never measured (V3b) |
| Frozen or black decoder pixels | DOM sees the element, not pixels | Clock rules, V/G liveness |
| Compositor vs main-thread skew (≤1 frame at the edges of CSS animations) | `getComputedStyle` reports main-thread time | None. Keynote's GL hide is an inline step change set from a task, so it is exact |
| 3D backface, OBS alpha/premultiply, OBS rAF throttling | Outside headless DOM | Q6, Q7 |
| **Pin mid-move pixels** | No pixel gate covers pin holds | **Named gap.** One-off spot check V3b (owner decision 6) |

### Non-goals
- No product bytes in A–C: core `7cb6e0fe` and `CONTINUITY_VERSION` 6 stay.
- No change to carry-cover code or thresholds, to `PAINTING_VIDEOS_JS` (`:387`, also imported by `managed_obs_qualify.py`), or to the P2 harness.
- No threshold relaxation, and **no new excuse without a measured reason and the owner's word**.
- The D5 end-of-show policy and the carry-cover clock alignment are separate items.

## 2. Definition of painted(element, frame)

### 2.1 Frame and phase
**Frame.** f is one rendering update in which the sampler's rAF callback ran, identified by `(seq, ts)` (tick counter, rAF timestamp).

**Pre-paint read.** A `ResizeObserver` watches a 1 px sentinel inside a **closed shadow root**, the pattern in `detach_experiment.py:125-220`. The sampler toggles the sentinel's width in its rAF callback.
- RO delivery runs in "update the rendering": after every rAF callback (the core's `rideTransition`, `keepAtSlot` and `keepSuppressed` loops included) and after style and layout, before paint.
- Tasks between frames (the player's `setTimeout(0)` that sets the opacity-0 swap) are seen by the next frame's read, the same frame that paints them.
- Evidence that phase matters: `pingap/c6-g1-ctl-1/2` show 1 rAF-phase double and 0 pre-paint doubles.

**No observer side effects.** Toggles inside the closed shadow root produce no MutationObserver records in the document. The core watches:
- `documentElement` subtree childList (`live_continuity_js.py:1833`, `:1997`);
- attributes `style/bgcolor/class` on transparent decks (`:1854`).

The host overlay watches `#body` attributes `style/class` (`live_host.py:428`). So the sentinel host is inserted once, at install, before any facade stub exists. The probe writes no light-DOM attributes after that, and no childList.

**Ordering self-check** (not taken on trust):
- The RO callback attaches `pp` only to the row with `row.seq == currentSeq` that has no `pp` yet.
- Each row needs exactly one `pp`, with `pp.seq == row.seq`, `pp.ts == row.ts` and `pp.t ≥ row.t`. Anything else makes the row unobserved, and its window INCONCLUSIVE.
- Paint verdicts **never fall back** to rAF-phase data.
- A missing `ResizeObserver`, `WeakRef` or `checkVisibility` is an arm error.
- The node twin tests only logic. The live positive control's late-writer variant (§4) is what proves the phase.

**Frame coverage.**
- period = median rAF delta. A window fails coverage when any delta exceeds `(CARRY_COVER_MAX_GAP_FRAMES + 0.5) × period`, or the cadence is below `CARRY_COVER_MIN_FPS`. This is the exact expression carry-cover uses (`:6881`, `:6801-6803`); A takes both constants as parameters. Failing coverage gives INCONCLUSIVE.
- Missed vsyncs are reported (count, ms). They never count as painted.
- **Known risk:** main r3's carry-cover null already tripped this rule at 66.7 ms under load. V1/V5 measure the INCONCLUSIVE rate. If it trips, the remedy is lower load, never a wider gap.

**Sampler liveness.**
- `meta` tracks `rafTicks`, `prepaint`, `ppMismatch`, `ppDuplicate`, `overflow`, `errors` and `readCostMs{sum,max}`.
- At read time, `now − lastTs ≤ (CARRY_COVER_MAX_GAP_FRAMES+1)·period`, or the sampler stopped early.
- When rows exceed `MAX_SAMPLES`, nothing is pushed and `overflow` increments. This replaces the silent `samples.shift()` at `:530`.
- The frame body is try/catch and always re-registers.
- **Drain in chunks** (`drain(maxRows)` in a loop until empty), so the CDP evaluate payload stays bounded. Rows grow a lot with `pp`.

### 2.2 Raw readings (the page records, Python decides)
**Candidates** are `querySelectorAll('video')` plus every element ever seen, held by **WeakRef**. A strong reference would change decoder lifetime. A detached decoder therefore appears as `connected:false`; the D5 gap frames had `all == []`.

**Per element (`pv`):**
- identity: `id`, `elId`, `instance`, `src`
- state: `connected`, `facade`, `suppressed`, `readyState`, `seeking`, `videoWidth`, `videoHeight`, `currentTime`, `paused`
- visibility:
  - `checkVisibility` (all flags; null when unavailable)
  - `visibility` (own computed value)
  - `displayNone`: label of the first flat-tree ancestor-or-self with `display:none`
  - `opacity`: product over the element and flat-tree ancestors up to `documentElement`; null when any value is non-finite
  - `hiding`: `{node, prop, value}` for the first ancestor at opacity ≤0.02 or `display:none`
  - `effects`: label of the first ancestor whose computed `filter`, `clip-path` or `mask-image` is not `none`
- geometry: `rect` (screen); `visibleRect` = rect ∩ each overflow-clipping ancestor's box ∩ viewport; `clippedBy`
- placement: `parent`, `layer`

**Walk rules.** The walk follows `parentNode` and crosses a `ShadowRoot` through `.host`. That is the flat tree, not `parentElement`, which stops at shadow roots. An unknown node type gives `opacity:null`, which is unreadable.

**Each `pp` also carries** `stageMap` (`STAGE_MAP_FN_JS` `:330`), `stageBox` (the `#stageArea` screen rect) and `cover` (`#obed-output-black` displayed).

### 2.3 `painted_state(pv)` in Python: the first matching rule wins
| # | Condition | State: reason |
|---|---|---|
| 1 | Not in `pp` | unpainted: absent |
| 2 | `connected` false | unpainted: detached |
| 3 | `facade` | not a painter. `bindFacade` proxies `readyState` and `videoWidth` (`live_continuity_js.py:1767-1773`) |
| 4 | `suppressed` | unpainted: suppressed (cross-check of rule 8) |
| 5 | `readyState<2` or `videoWidth≤0` or `videoHeight≤0` | unpainted: not-decoded, or **unpainted: seeking** when `seeking`. A poster never counts. Seeking is a separate reason so V2b can measure it (§2.5) |
| 6 | `opacity` or `checkVisibility` null, `effects` set, or `cover` | **unreadable**, giving INCONCLUSIVE |
| 7 | `displayNone` | unpainted: display |
| 8 | `visibility ≠ 'visible'` | unpainted: visibility. Own value only: visibility inherits, `#stageArea` is `visibility:hidden`, and the prototype's ancestor walk could false-gap |
| 9 | `checkVisibility` false | unpainted: checkVisibility |
| 10 | `opacity ≤ 0.02` | unpainted: opacity (with `hiding`). Same floor as `isCompositing` `:1299` and `PAINTING_VIDEOS_JS` |
| 11 | `visibleRect` null, or w≤1 or h≤1 | unpainted: offscreen |
| 12 | `opacity < 0.99` | **partial**: opacity. R9 refuses non-opaque carries (`live_continuity.py:1717-1721`) |
| 13 | `visibleRect` differs from the expected visible slot (slot ∩ `stageBox`, both authored) by more than `RECT_TOLERANCE_PX` | **partial**: clipped |
| 14 | otherwise | painted |

**Diagnostic only:** `outsideStagePx`, the decoder's painted area outside `stageBox`. Held decoders on `#body` are not clipped by `#stageArea`'s overflow, so a movie that bleeds off the slide would show over the letterbox during a hold. This is reported, not gated (owner decision 13).

**Opacity values** are computed values, so they include in-flight CSS animations at the frame's main-thread time. `PAINTING_VIDEOS_JS` treats NaN as 1 (`:396`) and `isCompositing` skips NaN. Both fail open, so neither is reused for this.

### 2.4 Per-frame slot count
The slot for row f:
- `srcRect` before the move (pin hold included);
- `dstRect` on move-complete and after rows (`is_move_complete` `:1726`);
- on bridge move rows, the carried decoder's own rect when `path_progress` (`:1693`) accepts it. Otherwise there is no slot, and the frame already fails.

S(f) = the `pp` elements of the verdict's asset (the `track_by_id` substring rule `:1556`) in state painted or partial, with `rect_iou` (`:3510`) ≥ `INSTANCE_IOU_MIN` (0.75, `:169`).

| S(f) | Result |
|---|---|
| exactly the carried element | pass |
| empty | unpainted (the carried element's reason is kept) |
| non-empty, carried element absent | **substitute** |
| two or more elements | **double** |

There is never a page-wide count: pingap D3/D5 have 56–118 frames where other movies legitimately coexist.

### 2.5 Excuses: none at build time
- The draft's single-frame wrap excuse is **removed**.
- `seeking` is recorded instead. V2b measures what a loop wrap does to these readings on the L2 force-wrap takes.
- If a measured dip appears, an excuse is proposed with its evidence path, for owner sign-off. Until then a dip is a red, and force-wrap reds block V2b, not the gate.

### 2.6 Frame advance
Frame advance is not part of painted. The clock rules are unchanged (`MAX_STALL_S`, `MAX_DROP_S`, `MIN_ADVANCE_S`). `pp.currentTime` is kept for gap diagnostics.

## 3. Probe changes

### 3.1 New module `scripts/paint_instrument.py` (stream A)
The probe imports it the same way it imports `continuity_core_variants` (`:117`). It never imports the probe.

- **Constants:** `SAMPLER_SCHEMA = 2`, `PAINT_OPACITY_FLOOR = 0.02`, `PAINT_OPAQUE_MIN = 0.99`.
  - `PAINT_CONTROL_VARIANTS = ("ancestor-opacity", "ancestor-half", "ancestor-display", "element-visibility")`
  - `PAINT_CONTROL_PHASES = ("settled", "bridge", "pin")`
  - `PAINT_CONTROL_TIMINGS = ("early", "late")`
- **`PAINT_READ_FN_JS`:** `paintReadOf(v)`, `labelOf(n)`, `layerOf(n)`, `flatParent(n)`, `coverUp()`, `stageBox()`. Read-only.
- **`PREPAINT_FN_JS`:** `installPrepaint(probe)` → `{toggle(seq, ts), track(v)}`. It sets up the closed-shadow sentinel, the RO and the WeakRef set, and attaches `pp` and updates `probe.meta`.
- **`paint_control_js(n, variant, phase, at_scene, *, timing="early", depth=1, delay_ticks=10) -> str`** (§4).
- **Python functions:**
  - `painted_state(pv) -> tuple[str, str | None]`
  - `frame_coverage(rows, *, max_gap_frames, min_fps) -> dict`
  - `score_paint(rows, element_id, asset_substr, *, start, end, slot_of, stage_box_of, rect_tolerance, iou_min, max_gap_frames, min_fps) -> dict`. Status is `ok`, `fail` or `inconclusive`. Fields: `reasons`, `frames`, `window`, `unpaintedFrames`, `unpaintedMs`, `partialFrames`, `doubleFrames`, `substituteFrames`, `minOpacity`, `firstFailure`, `longestRun`, `runs` (first 10), `unpaintedSeqs` (≤600), `coverage`, `outsideStagePx`.
  - `sampler_self_check(rows, meta, *, read_now, max_gap_frames) -> dict`
  - `paint_census(rows, carried, asset_by_id, *, scene_count) -> dict`. Every painted→not→painted run of a carried element is listed with a class: `scored`, `unscored`, `endOfShow` (`hash ≥ sceneCount`) or `ended`. **No class removes an entry from the findings list.** The class is a label for triage.
  - `score_paint_control(record, target_verdict, n, timing) -> dict`
- Thresholds the probe owns are passed in, never duplicated.

### 3.2 `SAMPLER_JS` v2 (`:444`)
- **Composition:** today's body + `STAGE_MAP_FN_JS` + A's two fragments.
- **Literals contract with `detach_experiment.py:117-122` and `tests/test_detach_experiment.py:173-193`.** B does not edit either file. `SAMPLER_JS` must keep, byte for byte:
  - `"  function tick(){\n    var t = performance.now();\n"` exactly once;
  - `"samples.push({t: t, scene: state.sceneId,"` exactly once;
  - `"window.__obedContinuityProbe__ = {samples"`;
  - and it must never contain `rafTs`.
- **New rAF callback `frame(ts)`.** It runs the control hook, then calls `tick(ts)` **with `ts` as an argument**. The detach patch rewrites `tick(){` into `tick(ts){` and toggles its own sentinel with `ts` (`:117-120`), so an argument-less call would feed it `undefined`. Unpatched `tick()` reads `frameSeq`/`frameTs` from the closure.
- **New row fields:** `seq`, `ts`, `hash`, `sceneCount` (`live_runtime.py:157`), `pp`.
- **Methods:** `{samples, meta, start(), stop(), drain(maxRows)}`. `stop()` cancels the rAF loop.
- **New constants:** `SAMPLER_META_JS`, `SAMPLER_START_JS`, `SAMPLER_STOP_JS`, `SAMPLER_DRAIN_JS`.
- `drive_and_sample` keeps its return type, because the detach wrapper depends on it. It drains in chunks.

### 3.3 Arms: `show()` first (commit B0)
`run_arm` (`:3097`) and `run_attach_arm` (`:3233`) call `player.execute("show")` before `drive_and_sample`, then check that the output reads visible (`live_host.py:1223`).
- In attach mode this lifts the inline `#body` opacity 0 that the ancestor-aware owner and paint checks both see (§1).
- In launch mode it removes the black cover, which `pp.cover` would otherwise mark unreadable.

B0 is a separate commit with its own unit test (FakeHost order). It changes host-gate conditions; see owner decision 12.

The arms also set `result["sampler"] = {schema, meta, selfCheck}` and `result["paintCensus"]`. The force-wrap drive (`:6211`) gets the same meta, and its status requires `selfCheck.ok`.

### 3.4 `convert_samples_to_authored` (`:1601`)
It also converts `pp.videos[].rect`, `visibleRect` and `pp.stageBox` to authored px using `pp.stageMap`, keeping the screen values. An invalid map makes the row unreadable.

### 3.5 `score_continuity` (`:1894`)
- New keyword `paint: bool = True`, threaded through `score_carry` (`:2615`) and `score_verdicts` (`:2946`).
- **When rows carry `pp`:**
  - **`paintStart` = max(clip_start, min(window.start, t₀))**, where t₀ is the first settled (`busy` False) row of scene `atScene−1` in which the carried element has `readyState ≥ 2`. This covers the whole pin transition; today only the 2 s pad covers it (190 ms of margin on D5 b0to1). It never starts during initial load, before the first decode.
  - `slot_of` is a closure over `is_move_sample`, `is_move_complete`, `path_progress` and the spec rects.
  - `scored["paint"] = score_paint(...)` goes after `missing_samples` (`:1988`).
  - Verdict: `fail` → False (ANDed at `:2040`). `inconclusive` with everything else ok → None, with reason `"inconclusive: paint …"`.
- **When no row carries `pp` (legacy):** output is byte-identical, with no `paint` key. This keeps `TestCarryVerdict`'s `S1_BASE` equality, the committed real-sample fixtures and `rescore_generated` (`:6345`, which does not call a status function) unchanged.

### 3.6 `score_restart_strict` (`:2634`)
With `pp` present, it adds a report-only `slotGap {frames, ms, t0, t1}`. The verdict is unchanged. Expected on D2 restart@4: 1 frame (`f6` frame 303).

### 3.7 Schema and status
- `_sample_problem` (`:2516`) validates `seq`, `ts`, `pp` and `pv` types when present.
- `sample_schema_errors` (`:2558`) errors on mixed schemas.
- New `sampler_problem(entry)` requires `sampler.schema == 2` and `selfCheck.ok`. It is enforced in:
  - `generated_status` (`:5464`)
  - the P2 path of `overall_status` (`:5308`)
  - `red_arm_status` (`:5630`)
  - `overall_status_g` (`:4829`, per leg)
  - `paint_control_status`
- Legacy rescoring does not call these. A fresh run without schema 2 is an error.

### 3.8 Pass G per-frame advance legs (`:4711-4960`)
**`goto_matrix`.** `GOTO_MATRIX` filtered to the deck, plus `(f, src, dst)` for **every** expected-True carry, with `f = 1 if src != 1 else 2`, de-duplicated with `dict.fromkeys`. Today's rule (`:4718`) keeps only mid-chain sources.

| Deck | Added cases |
|---|---|
| P2 | (1,3,4) (decision 5) |
| D1, D6 | (2,1,2), (1,2,3), (1,3,4) |
| D2 | (2,1,2), (1,3,4), (1,4,5) |
| D3 | (2,1,2) (A pin + B bridge), (1,2,3), (1,3,4) |
| D4, D5 | (2,1,2), (1,2,3) |

B's tests derive these from the committed deck plans (`_deck_plan` `:7740`), not from this table.

**`_run_goto_arm` (`:4865`).** After warm-up (which already calls `show()`, `:4857`): evaluate `SAMPLER_JS`, then `SAMPLER_STOP_JS`. This happens once per session, before any goTo, while no stub exists.

**`run_goto_destination` (`:4723`), replacing the bare advance at `:4796`:**
1. drain and discard; start;
2. sleep `CLICK_DELAY_S`;
3. `advance_until_original_slide`;
4. `wait_until_settled`;
5. sleep `WINDOW_PAD_S`;
6. stop and drain;
7. `convert_samples_to_authored`;
8. `score_verdicts(rows, {}, {"verdicts": leg_specs}, installed, continuity)`, where `leg_specs` are the expected-True carries whose `(fromPlayer, toPlayer)` equals the leg;
9. `advanceCarry = {specs, verdicts, sampler{meta, selfCheck}, verdict}`, added to `combine_verdicts` (`:4323`);
10. the existing settled burst then runs with the sampler stopped.

**A leg with no matching spec is an error, never vacuous.** Legs run in the armed session only, as today.

**End of show.** Legs stop at `dst`, which is never past the last slide. The handover requires legs to treat `hash ≥ numScenes` as an exit. The leg also asserts that `dst` was reached without passing end of show.

### 3.9 Pass G red arm
- `parse_args` (`:823-828`) accepts `--pass G --core-variant NAME`. `--pass` with `--strip` is still refused.
- `run_cli` (`:7121`) checks `only_pass == "G"` before dispatching a red arm.
- `run_pass_g` wraps both sessions in `injected_core_variant` (`:1462`). The result records `redArm`, `expectedCoreSha256`, `expectedRedSet` (from new `PASSG_RED_EXPECTATIONS[(planSha, label)]`), `redSet` (`G{f}-{to}-{adv}:{specId}` for each leg verdict that differs from expectation, plus `G…:destination` for a non-leg failure) and `unknown`.
- `passg_red_status` follows `red_arm_status`. Both sessions' `continuity.sha256` must equal the variant's sha.

### 3.10 Positive control CLI
- **Flag:** `--paint-control N:VARIANT:PHASE@SCENE[:late][:depth=K]`.
- **Run:** `run_paint_control` runs one continuity-on `run_arm` with `SAMPLER_JS + paint_control_js(...)`.
- **Artifact:** kind `live-continuity-probe-paint-control`, with `control`, `controlRecord`, `targetVerdictId`, `arm`, `redSet`, `unknown`, `status`, `statusReasons`, `expectedCoreSha256`.
- **Refused:**
  - attach/alpha mode;
  - `ancestor-display` outside `settled`;
  - a phase/scene that matches no carry of that action;
  - `settled` on a non-bridge;
  - a `depth` that would reach `documentElement`.
- **Exit:** 1 unless the status is pass.

### 3.11 Registrations (pre-registered predictions; first registrations are owner-signed)
- `RED_ARM_EXPECTATIONS[(_D5, "core:no-pin-hold", "off")] = (b0to1:A carry, b1to2:A carry)`. Source: pingap r9, older core, trace wraps on.
- `PASSG_RED_EXPECTATIONS[(_D1, "core:no-pin-hold")] = ("G1-3-4:b2to3:…carry",)`. Source: r1/r3/r4/c1, plus r7 at 2560.
- Optional `RED_ARM_PAINT_FLOOR[key] = 60` frames for the longest run (decision 3).
- `TestRedArmRegistration` (`tests/…probe.py:7778`) validates the ids. Each entry carries a reason string and an evidence path.
- Nothing is registered before V3 measures it on the landed core.

## 4. Controls

### Null
- Every carry window reads `0/0/0/0` (unpainted/partial/double/substitute), with `selfCheck.ok` and coverage ok.
- Scope: D1–D6 and P2 × {2560×1440, 1600×1000, 1920×1080}, as host arms A, C and attach, and as Pass G legs.
- Reported, not gated: D2 restart@4 `slotGap`, and every census run, `endOfShow` and `unscored` included.
- Never measured before: D4, D6, P2, 1600×1000 and the landed pin-hold core. Expect findings. A red is a finding, never a tolerance.

### Positive (exact seq set)

**Mechanism.** A constructable stylesheet goes in `document.adoptedStyleSheets`: no node, no MutationObserver record. Its rules:
- `[data-obed-paint-control="ancestor-opacity"]{opacity:0!important}`
- `…="ancestor-half"]{opacity:.5!important}`
- `…="ancestor-display"]{display:none!important}`
- `…="element-visibility"]{visibility:hidden!important}`

The `data-*` attribute is outside every observer filter (`live_continuity_js.py:1833,1854,1997`; `live_host.py:428`).

**Target.** The ancestor at `depth` (1 = `parentElement`), or the element itself for `element-visibility`. During pin and bridge holds the parent is `#body`, so depth is 1. **At `settled`, depth 2 is required**: it exercises a multi-level walk, the layer104-above-layer113 shape of Q7.

**Trigger.** Polled read-only from the core's `events` in the sampler tick:
- `pin`: `pin-hold-start` with `detail.atScene == S` (`:1168`);
- `bridge`: the first `bridge-motion-start` while the hash equals S−1 (`:1151`);
- `settled`: the first settled tick on the bridge's source scene, with exactly one decoded element of the asset, otherwise abort.

**Timing.** After `delay_ticks`, at tick k:
- `early`: the attribute is set in the sampler's own rAF callback.
- `late`: the attribute is set in a **separate rAF callback registered after the sampler's**, which mimics a core loop that writes after the probe (the c6 shape). That callback runs after the sampler's rAF-phase read and before the RO read.

The pass condition is **seq-set equality**. Pre-paint must see exactly {k…k+N−1} in both timings. A rAF-phase instrument would see {k+1…k+N} under `late` and fail. That makes the phase load-bearing, not vacuous.

**Integrity.** INCONCLUSIVE if the target's parent or rect changes during the hide, or if the core logs a placement or retire event for that decoder inside [on, off]: stash, remount*, rehome, dom-swap, retire*, bridge*.

**Pass.**
- `unpaintedSeqs` equals the injected set exactly (for `ancestor-half`, `partialSeqs` does, with unpainted 0), and the other counts are 0;
- `fired`, and `hiddenTicks == N`;
- `redSet == [target]`, with every other verdict green.

N=0 is the injector's null: armed, nothing hidden, everything 0.

Owner mismatches are recorded, not asserted, because pin-hold rows are never owner-checked.

**Pure twin.** A's node tests run the same JS with a fake rAF/RO/DOM. They prove logic only; V2 proves the phase.

### Red (sources: pingap; older core, trace wraps on, so re-measure)
| Arm | Boundary | Expected (1920) | Evidence |
|---|---|---|---|
| D5 host red `--core-variant no-pin-hold` | b0to1 A (pin@2) | ≈108 | r9 108 frames / 1813 ms (layer16 at opacity 0) |
| | b1to2 A (pin@4) | ≈107 | r9 107 / 1834 ms (layer78) |
| D1 `--pass G --core-variant no-pin-hold` | (1,3,4) b2to3 | ≈108 | r1 108/1814, r3 108/1811, r4 108/1811, c1 108/1813; r7 (2560) 108/1817 |
| same | (2,1,2), (1,2,3) | 0 | r5 0, c6 0 |
| D1 sequential, same variant | all | 0 (the variant's null) | r2 0 (`keepThroughPin` refuses bridged decoders) |
| D2 / D3 / D4, same variant (measure first) | D2 b2to3, D3 b0to1 A, D4 none | ≈108 / ≈108 / 0 | r10 108/1807; c7 108/1849; D4 predicted only |

- **Blindness rescore.** Offline, `score_verdicts(..., paint=False)` on each red artifact must read **green**. This proves the new readings, and nothing else, close the false green.
- **Pre-pin-hold core** (`4ae33f99`, core sha `d71d1e76`), once, through a scratch driver outside the repo (decision 7). Expect the same paint red set; owner mismatches may differ.

### Silent-sampler guard
A sampler that is silent, stopped, out of order, overflowed, or under-sampled can never read green:
- no `pp` → error;
- a missing or mismatched `pp` → INCONCLUSIVE;
- a frame gap → INCONCLUSIVE;
- a stale `lastTs` → `selfCheck` fails;
- overflow → INCONCLUSIVE;
- a Pass G leg with no matching spec → error.

## 5. Gate integration (stream C, `scripts/run_gates.sh`)

**New arms, full tier only:**
- **`DECK_ARMS`** (`:51-58`) gains `"D5 --core-variant no-pin-hold"`, plus D2/D3 after V3 (decision 11).
- **`PASSG_RED_ARMS=("D1 --core-variant no-pin-hold")`**, with `run_passg_red`/`check_passg_red` modelled on `run_cc`/`check_cc` (`:373-401`). The check covers:
  - kind and `redArm`;
  - both shas = `variant_sha`;
  - `expectedRedSet == redSet` (Counter);
  - `unknown` empty and status pass.

  It prints each leg's paint counts.
- **`PAINT_CONTROL_ARMS=("D5 6:ancestor-opacity:pin@2" "D5 6:ancestor-opacity:pin@2:late" "D5 0:ancestor-opacity:pin@2")`**, with `run_paint_control`/`check_paint_control`. The check covers:
  - kind and control = args;
  - `fired` and `hiddenTicks == N`;
  - target seq set exact;
  - status pass and exit 0.

**Existing checks:**
- `check_host`, `check_host_red` (`:293-347`) and `check_passg` (`:356-367`) print each carry's unpainted/partial/double/longestRun and `selfCheck`. They count census entries into `FINDINGS`, by class.
- `check_host_red` also requires `arm.sampler.schema == 2` and `selfCheck.ok`.
- `DONE` (`:420`) gains `findings=N`; the exit code is unchanged.
- Check order: Pass G → Pass G red → paint control → carry-cover.
- **Docs (`.agents/skills/obed-edom/SKILL.md`):** Gate G scored per frame; add `pin-hold-start` and `bridge-motion-start` to the F5 note list (now read by the injector); one "Painted instrument" bullet.

**Never relaxed:**
- zero tolerance for unpainted, partial, double and substitute frames;
- `MAX_STALL_S`, `MAX_DROP_S`, `RECT_TOLERANCE_PX`, `INSTANCE_IOU_MIN`;
- the carry-cover thresholds, including 5 px strips and `MAX_GAP_FRAMES`;
- `RED_ARM_REQUIRED` (D4 b0to1 A_FAR carry; P2 WA0125 stray);
- "a red under the stricter scorer is a finding";
- INCONCLUSIVE stays fail-closed.

**Red sets that may move** (measure; nothing is predicted beyond "may move"):
- strip arms: `D1/D2 strip:pin@6`, `D3 strip:pin@2/@4`, `D4 strip:pin@5`, `D5 strip:pin@2/@4`;
- post-hoc arms: `D4 wrong-instance/fifo-reuse`, `D5 fifo-reuse/stash-any`.

Procedure for each:
1. Diff the run against the registration.
2. Attach per-frame evidence for each added or removed id.
3. Run the blindness rescore, which separates a scorer cause from a core cause.
4. Re-register only with a reason, an evidence path and owner sign-off.

**Carry-cover strip failure.** Untouched here; separate (triage: ~7 ms GL lag).

**D5 #5→#6.** This is end of show plus the stale-timer revival (`triage-2026-10-10/d5-end-of-show.md`). No gate drive reaches it. If a census ever sees it, it is listed as a finding with the label `endOfShow`, never dropped. Stream D and E1–E3 handle it.

## 6. Work streams (disjoint files; one worktree each, off `63606556`)
| Stream | Owns (exclusively) | Targeted test command (only when the coordinator gives a go) |
|---|---|---|
| A | `scripts/paint_instrument.py` (new), `tests/test_paint_instrument.py` (new; may import `tests/test_live_continuity_js.py` helpers read-only: `_node_stdout` `:63`, `_full_harness` `:813`) | `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/test_paint_instrument.py -q`, then the same with `uv run --python /opt/homebrew/bin/python3.11 pytest …` |
| B | `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py` | `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/test_live_continuity_probe.py tests/test_detach_experiment.py tests/test_paint_instrument.py tests/test_managed_obs_qualify.py -q`, plus the 3.11 run |
| C | `scripts/run_gates.sh`, `tests/test_run_gates.py` (uses `PROBE_STUB` `:101`), `.agents/skills/obed-edom/SKILL.md` | `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/test_run_gates.py -q`, plus the 3.11 run |
| D (separate brief) | `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py` (`PINNED_CORE_SHA256`), `scripts/detach_experiment.py` (`CORE_SHA256` only), `tests/test_continuity_core_variants.py` (only if an anchor moves) | `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/test_live_continuity_js.py tests/test_continuity_core_variants.py tests/test_detach_experiment.py -q`, plus the 3.11 run |

The shared `.venv` is Python 3.10.10, which is the floor. 3.11 is the second-interpreter check.

**Order.** A commits its API skeleton first (§3.1 constants and signatures). B merges A's branch and codes against it, starting with B0 (`show()`). C codes against the artifact contracts in §3.9, §3.10 and §5. D is independent. B and C merge the main fold before V1.

**Style.** Minimal natspec. No inline comments in product code or in the JS fragments; tests may be verbose. Reuse `rect_iou`, `track_by_id`, `path_progress`, `STAGE_MAP_FN_JS` and the carry-cover coverage constants.

### Stream A tests
**`painted_state` truth table, one row per rule.** It must include:
- an ancestor `visibility:hidden` with the element's own value visible → painted (the prototype's bug);
- NaN opacity → unreadable;
- a poster with `readyState` 1 → unpainted;
- `seeking` → unpainted: seeking;
- `cover` → unreadable;
- a shadow-root ancestor at opacity 0 → unpainted (flat-tree walk).

**`score_paint` on synthetic rows:**
- clean → ok;
- 108 frames with c1 geometry (parent layer113, hiding layer104) → 108, with layer104 named;
- 14 detached frames;
- partial 0.5 → fail; 0.995 → painted;
- a same-asset double → fail;
- D5 A′ elsewhere → ok; another asset at the slot → ok; a facade at the slot → ok;
- a substitute;
- clipped vs (slot ∩ stage) → partial; a slot legitimately clipped by the stage → ok;
- missing or mismatched `pp` → inconclusive;
- a delta of 4.5 periods → inconclusive; 1 missed frame → ok.

**Other functions:**
- `sampler_self_check`: overflow, stale, errors, duplicates.
- `paint_census`: all four classes, and no class drops an entry.

**Node JS:**
- one `pp` per tick with matching seq/ts, and none when the RO is suppressed;
- WeakRef reports detached elements;
- no attribute or childList writes outside the shadow root after install;
- the injector hides exactly {k…k+N−1} for N ∈ {0,1,6,30} × {early, late} × each trigger, and aborts on a parent change;
- under `late`, a rAF-phase reader would see the shifted set (a known-bad for the phase).

### Stream B tests
- B0: `run_arm`/`run_attach_arm` call `show()` before driving (FakeHost `:920`).
- `SAMPLER_JS` literals contract; `frame` calls `tick(ts)`.
- Chunked drain.
- Legacy rows: output unchanged, no `paint` key. Mixed rows → None.
- A v2 pin with 108 dark frames → False; the same rows with `paint=False` → True (blindness).
- A pin transition longer than `WINDOW_PAD_S` with dark early frames → caught.
- No false red during initial load (paintStart grounding).
- `slotGap` report.
- Status functions fail closed without `sampler`.
- `goto_matrix` from every committed deck plan (update `TestGotoMatrixFromThePlan` `:7625`); P2 = `GOTO_MATRIX` + (1,3,4).
- Leg call order. A leg without a matching spec → error.
- `parse_args`/`run_cli` dispatch for `--pass G --core-variant` (update `TestRedArmArgs` `:7730`).
- `passg_red_status` and `paint_control_status` truth tables.

### Stream C tests
- New arms queue in order, full tier only.
- `check_passg_red` known-bad cases: sha mismatch, an extra red, `unknown` not empty.
- `check_paint_control` known-bad cases: N±1, a shifted seq set, never fired, wrong control.
- `check_host_red` refuses a missing `selfCheck`.
- `findings=` is printed without changing the exit code.

### Stream D
1. A reproduce-first node test: a declined stash plus a pending `scheduleRemount` must not remount.
2. The fix: `tryRemount` bails for an unwanted decoder, or the stash cancels the pending retries.
3. Re-pin the shas.
4. E1–E3 confirm the mechanism live before D lands (coordinator, 1 Chrome).

## 7. Validation sequence (coordinator only; serial; load under 3 at start)
**Preconditions:** the main live round is finished; the main fold is merged into S2 and the instrument branches; D has landed, or the controls re-run after it.

- **V0:** A–D targeted tests green on 3.10 and 3.11.
- **V1 smoke (1 Chrome):**
  - First, the B0 effect. D1 host attach arm on the S2 head **without** B0, then with it. This confirms or refutes the `fbba575e` attach-owner prediction (§1) before anything is attributed.
  - Then D1 host at 1920 with `--skip-arms B,C,V,Voff,attach`: `selfCheck` ok, `pp` on every row, `0/0/0/0`, cadence ≈16.7 ms, max gap within the rule, `readCostMs` recorded.
  - Then a full P2 host run at 1920, attach carries included.
- **V2 positive (3-wide):**
  - D5 pin@2 ancestor-opacity, N ∈ {0,1,6,30} × {early, late};
  - D5 pin@2 ancestor-half N=6;
  - D1 bridge@2 ancestor-opacity and element-visibility N=6, late;
  - D1 settled@2 ancestor-display depth 2, N=6;
  - N=6 pin, late, at 1600×1000.
  - Expect exact seq sets everywhere.
- **V2b force-wrap:** L2 force-wrap takes with paint on. Measure `seeking` and `readyState` at wraps. Any dip is a finding for owner decision 14.
- **V3 red (3-wide):**
  - D5 host red; D1 Pass G red; D2/D3/D4 `no-pin-hold`;
  - the blindness rescore, offline;
  - the pre-pin-hold one-off.
- **V3b pin pixel spot check (one-off, decision 6):** reuse the carry-cover screencast plus sync bar on D1 (1,3,4) and D5 pin@2, landed core vs `no-pin-hold`. Inside the pin rect during the hold, the counter clip must change frame to frame (landed core) and must not (the variant). This is evidence, not a gate.
- **V4 moved sets (3-wide):** §5 list, triage, owner sign-off.
- **V5 null:** D1–D6 + P2 host full runs at 1600×1000, then 2560 and 1920. Pass G P2 + D1–D6 at 1920, every leg green. Record the INCONCLUSIVE rate per arm.
- **V6 overhead:** cadence and `readCostMs`; host `restart2to3.startTimeS` against the `phaseD-867e415c` artifacts and the 2026-10-09 baseline.
- **Full suites (serial):**
  - `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (3.10 `.venv`; worktree env per `worktree-env-setup`);
  - the 3.11 run of the touched test files;
  - `cd dashboard && npm run test:ui` and `npm run test:maps` (the owner's rule: every code PR).
- **Review:** Astra reviews the diff and this plan; fold the findings. If probe code changed, re-run V2 (N=6 pin, late) and V3 (D5 host red).
- **S2 full re-run on the final head:**
  - Phase A null sweep: all counts 0, findings cited.
  - B/D1: `run_gates` 3-wide ending `failed=0 pending=0`, plus one `GATE_JOBS=1` round. Required: identical verdicts, identical exact seq sets, red counts within ±3 frames per boundary (to agree), restart margins within baseline.
  - Then D2–D5, Q6, Q7. Q7 remains the only check on OBS alpha.

## 8. Risks
- **Main fold conflicts:** new code goes in new functions, and A's module is conflict-free. Merge early.
- **RO ordering differs in some Chrome/CEF:** the self-check gives INCONCLUSIVE, and the late-writer positive fails. It is never green.
- **Coverage INCONCLUSIVE under load** (r3 precedent): measured in V5. The remedy is load, not threshold.
- **The landed pin hold has never been measured pre-paint:** a 1–2 frame dark start would be a product finding, not a tolerance.
- **Initial-load false reds:** handled by paintStart grounding, tested in B.
- **CDP payload size:** chunked drain.
- **Positive control disturbing the core:** `data-*` plus `adoptedStyleSheets`; alpha mode refused; placement events inside the hide → INCONCLUSIVE.
- **Detach coupling:** literals plus `tick(ts)`; `tests/test_detach_experiment.py` is in B's command.
- **Cost:** artifacts roughly double; Pass G gets ~10 s per leg, about +3 min per round at 3-wide.
- **P2 harness scripts also read `footprintOwnerDecoderId`** (`p2_recovery_html_adversarial.py:893`). If any of them runs hidden in alpha mode, the `fbba575e` owner effect applies there too. The coordinator checks this; it is out of this stream's files.

## Critique log
1. **Correctness.** Python commands fixed. The shared `.venv` is 3.10.10, the second interpreter is 3.11, and the full suite command comes from SKILL/memory. The draft's `--python 3.10` flag placement and "3.12" were wrong. `test:ui`/`test:maps` are required again (owner rule for every code PR).
2. **Correctness / false-red.** `show()` is promoted from "instrument need" to prerequisite commit B0. From the code, `fbba575e`'s ancestor-walking `isCompositing` plus the alpha host's inline `#body` opacity 0 (`live_host.py:425-428`; no `show()` in `run_arm`/`run_attach_arm`) should already turn attach carries red through readable-dict owner mismatches. V1 measures this first.
3. **False-green risk.** The positive control was vacuous for phase: the injector and the counter shared the sampler tick, so a rAF-phase instrument would also count exactly N. Added the `late` timing plus seq-set equality, an `ancestor-half` variant (exercises the 0.99 partial rule), and depth 2 at `settled` (multi-level walk, the Q7 shape).
4. **Tolerance smuggling.** The pre-built wrap excuse is removed. `seeking` is recorded, V2b measures it, and any excuse needs evidence plus the owner.
5. **False-green risk.** The census `endOfShow` class no longer removes entries from findings. The handover asks legs to treat end of show as an exit, not to excuse gaps there.
6. **False-red.** paintStart is grounded at the first settled decoded source row, not the first row of scene `atScene−1`, which could include pre-decode load on first carries.
7. **Correctness.** Clipping is compared against slot ∩ stage box (letterbox-safe). Added the `outsideStagePx` diagnostic, because held decoders on `#body` escape `#stageArea`'s clip.
8. **Correctness / reuse.** The coverage rule is now the exact carry-cover expression (`(MAX_GAP_FRAMES+0.5)·cadence`, `:6881`), not a new "missed run" semantics. The r3 66.7 ms precedent is flagged as an INCONCLUSIVE risk.
9. **Correctness.** `frame(ts)` must call `tick(ts)` with an argument: the detach patch rewrites `tick(){` to `tick(ts){` and uses `ts` (`detach_experiment.py:117-120`).
10. **Correctness.** Chunked drain added for CDP payload size.
11. **False-green risk.** The ancestor walk follows the flat tree (`ShadowRoot.host`), and unknown nodes are unreadable.
12. **Clarity / unsupported claim.** The draft's mechanism for strip:pin red-set movement was unverified; it is now "may move; measure".
13. **Correctness.** Positive-control integrity is keyed on placement and retire events for the target, not "any core note", which could make every N=30 inconclusive.
14. **False-green risk / scope.** Pin z-order is pixel-evidenced only for bridges on the same `#body` container. Added the one-off V3b counter-clip spot check, with no gate.
15. **Scope.** Each stream gets its own worktree (no shared index). The coordinator gates even targeted pytest during live rounds (task rule). Named the in-flight main freeze fold worktree.
16. **False-green risk.** A Pass G leg with no matching spec is an error, never vacuous. Legs assert they did not pass end of show.
17. **Verified unchanged:**
    - owner-check scope and pin `before_rows` (`:2013-2027`);
    - `samples.shift()` (`:530`);
    - the `--pass` with `--core-variant` refusal (`:823-828`) and the `run_cli` order (`:7121-7126`);
    - `GOTO_MATRIX` and the mid-chain filter (`:303`, `:4711-4720`);
    - `INSTANCE_IOU_MIN` 0.75;
    - carry-cover constants (`:6447-6448`);
    - R9 opacity refusal (`live_continuity.py:1717-1721`);
    - `PAINTING_VIDEOS_JS` NaN→1 (`:396`);
    - observer filters (`live_continuity_js.py:1833,1854,1997`; `live_host.py:428`);
    - `rescore_generated` calls no status function.

## Owner decisions (recommendation first)
1. **Carried-decoder opacity threshold:** **≥0.99** (partial counts as a violation), rather than >0.02.
2. **D2 restart 1-frame blank:** **report only** (`slotGap`).
3. **Red registration:** **id sets plus a 60-frame floor** on the longest run, rather than exact counts.
4. **CLI surface:** **accept** `--pass G --core-variant` and `--paint-control`.
5. **Pass G:** **every** expected-True carry gets a leg. P2 gains (1,3,4); legs from slide 1 go to slide 2 first.
6. **Pin mid-move pixels:** **one-off V3b spot check now**; a pin carry-cover gate is deferred until after the D1 lag fix.
7. **Pre-pin-hold core red:** **once**, with a scratch driver, outside `run_gates`.
8. **Census findings (all classes, `endOfShow` included):** **report only**; each is cited and triaged before the full re-run.
9. **Consolidating the duplicate opacity logic** (`PAINTING_VIDEOS_JS`, carry-cover): **defer** until after the S2 gates.
10. **Stream D:** **parallel**; confirm with E1–E3 and land before V2–V5.
11. **D2/D3 `no-pin-hold` red arms in `run_gates`:** **add after V3 measures them**.
12. **B0 `show()` in host, red and attach arms:** **yes**, as its own commit. It changes host-gate conditions, and it is probably needed for the attach arm after `fbba575e` regardless (V1 confirms).
13. **`outsideStagePx`** (held decoder painting over the letterbox): **report only** for now. Gate it if V5 finds any.
14. **Loop-wrap `seeking` frames:** **no excuse until V2b measures them**. Then decide with the evidence.
