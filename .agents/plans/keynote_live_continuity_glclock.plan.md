# Plan: put the S2 bridge overlay on Keynote's GL clock (core v6, hardened)

**Owner GO 2026-10-10** (night handover, decision 1). The base is `claude/s2-detach-fix` at `4a389a72`, whose core is `6c7a482e`. This plan was made read-only: no repo edits, no Chrome, no live runs.

The JS sketch in §3.7 was run in Node, from scratch copies, against the real fake-DOM harness:
- 423 of the 441 tests in `test_live_continuity_js.py` and `test_continuity_core_variants.py` pass unchanged.
- The 18 failures are all expected: the sha pin, 4 fragment-harness runs that need a `departure` stub, and 13 variant tests.
- Scratch scripts: `/private/tmp/claude-501/glclock-plan/` (`sketch.py`, `nothrow.py`, `frag.py`).

## 1. Goal and non-goals

**Goal.** The carried `<video>` overlay times its bridge on the same clock as Keynote's GL poster: Keynote's `Date`, counted from its GL loop start. That removes two exposures:
- the 5.5–8 ms start offset, which shows 6–9 px strips on D1;
- the wall-clock-step exposure explained in §2.

The owner's hardening applies:
- the hook never throws;
- the overlay falls back to today's clock after 50 ms;
- today's clock becomes a red variant;
- carry-cover joins `run_gates` on D1.

**Non-goals.**
- `main` stays untouched.
- No edit to the player's `main.js`, on disk or in memory, and no new player patch.
- `CONTINUITY_VERSION` stays 6, and the preserve object stays at `version: 9`.
- No change to the carry-cover thresholds, masks, dilation or rounding.
- No change to the freeze-bracket bounds or verdict code.
- No change to the `bridge-motion-start` note or to `__obedMotion.started`.

## 2. The 53 px outlier (green-2): a macOS wall-clock step (verified)

- **The step.** `log show --predicate 'process == "timed"'` has `settimeofday` at 20:17:16.196777, `cmd,apply,src,settimeofday … adjust,-0.089354038,success,1`.
  - It is the only step between 19:45 and 20:46. The other entries are slews: −3.7 ms at 20:00:36 and +26 ms at 20:34:40.
  - The page's `timeOrigin` is 20:17:10.976, so the step lands at page time ≈ 5309 ms, between t113 (5293.4) and t114 (5310.1).
- **The screencast clock.** `pts−domTs` jumps by −89.9 ms at t113. That is the only jump larger than 8 ms in the 10 `cc-D1-glclock` runs.
- **The poster's lag.** It is about 6.6 ms until t113, then a flat ≈ 94–97 ms from t114 to t124. Two independent fits give 93.7–96.3 and 94.5–97.4.
  - Only the left and bottom strips show, which is what pure lag along the path produces.
  - They shrink from 53 to 29 px as the ease slows.
  - The overlay is continuous, and the largest frame gap is 16.8 ms.
- **Why only the poster moved.** `fB.animate()` sums `new Date` deltas, and the Magic Move program adds `percentfinished += delta/duration`. That telescopes to `Date(now) − Date(first animate)`, so a step moves the poster permanently. The core uses `performance.now()`, which never steps.
- **Rejected readings.** Compositor lag of about 70 or 110 ms does not fit a lag that stays flat for 11 frames and matches the screencast clock jump.

**What this means for the design.**
1. Origin and progress both use `Date`. Mixing a `Date` origin with `performance.now()` progress would bring this failure back.
2. The fallback deadline runs on `performance.now()`.
3. The fallback clock is today's `performance.now()` clock.
4. No new integrity rule and no threshold change: the exposure was real. The live readout (§9) checks for screencast-clock jumps offline.
5. **This is a live-show hazard today.** Any step during a bridge exposes the poster for the rest of the move. The GL clock removes it by construction, but no live run has seen a step under the GL clock yet.

## 3. Core design (`src/obed_edom/live_continuity_js.py`)

### 3.1 Keynote's clock (both supported players)

Byte offsets are into D1 `main.js` (e9b2fad4); 17c0c938 has the same call sites.

**`requestAnimFrame` is used in exactly two places:**
- the assignment `window.requestAnimFrame=window.requestAnimationFrame` @2043205;
- the re-arm in `fB.animate()` @2265797.

`animate()` reads `new Date`, sets `this.time` on the first call, calls `requestAnimFrame`, then draws. Native `requestAnimationFrame` is used only by PDF.js and the ink editor, and nothing calls `cancelAnimationFrame`.

**How a transition starts.**
1. `displayScene` @2354628 writes the hash, then runs `renderEvent`, then writes the hash a third time.
2. `playCurrentScene` @2356266 runs `renderEffects`, then `setTimeout(animateEffects, 1e3*g)`. R10 forces `g = 0`.
3. `animateEffects` @2316107 calls `animateEffect` for each effect (`new fB`, then `setTimeout(animateEffectWillBegin, 0)`).
4. In the same block it calls `e.animate()` on every GL renderer. That call is the loop start.
5. The Magic Move program accumulates `percentfinished += A/g`.
6. Scene completion is timer-driven: `setTimeout(currentSceneDidComplete, 1e3*C+100)`.

**When the core's own trigger (`started`) runs.**
- **Pooled path** (D1 b1to2, P2 3→4): the teardown microtask runs `noteDeparture` → `stash` → `scheduleRemount`, which calls `tryRemount` synchronously (`:967`) → `keepThroughBridge`. This is the end of the setup task. Keynote's loop starts one task hop plus WebGL setup later: 5.5–8 ms on D1. P2's 6.6 ms is a model estimate.
- **Held path** (D1 b2to3, chained bridges): `markTransition` runs on the second hash write, before `renderEvent`. That lag is unmeasured (risk 1).

### 3.2 Hook: a setter trap that never throws

**Installation.**
- The hook is installed after the history wrapper (`:808`), only when the plan has a `bridge` entry. The whole block sits inside `try/catch`.
- Absent property: define a configurable, enumerable accessor.
- Configurable data property (`main.js` already ran): wrap its value.
- Foreign accessor or non-configurable property: no hook, and the bridge falls back after 50 ms.

**Behaviour.**
- The setter always stores the value. A getter-only accessor would make `main.js`'s plain assignment throw.
- The getter returns the raw value when `disabled` is set or when the raw value is not a function. Otherwise it returns a wrapper.
- The wrapper:
  - passes a non-function argument straight to the raw function;
  - runs its bookkeeping inside `try/catch`;
  - calls the raw function with `this = window`;
  - wraps the callback so it sets `inGlFrame` around a `try/finally`.
- The P2 alpha probe wraps native `requestAnimationFrame` before `main.js` runs (`html_alpha_probe.py:2777`). The setter receives that wrapper, so its counts are unchanged.

### 3.3 Origin detection: one departure occurrence, one stamp

**What counts as a loop start.** A `requestAnimFrame` call counts only if:
- it is made outside a wrapped callback;
- a `departure` of the current generation exists;
- the hash equals `departure.scene`;
- it is the first such call in this occurrence. It stamps `departure.gl = {date: Date.now(), perf: performance.now()}`.

**What this rules out.**
- Re-arms always run inside a wrapped callback.
- Every top-level GL effect of an event starts in one synchronous block, and later chained starts find the occurrence already stamped.
- The core, the probes, Pass G and GL replay all use the native `requestAnimationFrame`.

**The occurrence object.**
- `markTransition` reuses `departure` while the scene and generation are unchanged. It creates `{scene, gen, gl: null}` otherwise. Today it always creates a fresh object (`:779`).
- Because the object is now reused, the `replaceState` wrapper lapses it as soon as a write moves the hash off its scene. The 200 ms interval (`:1909`) stays as a backstop.
- `goTo` calls `clear()`, which bumps the generation.

### 3.4 Per-motion latch and fallback

- **Motion key.** `__obedMotion` gains `departure`, and the reuse key becomes generation, boundary and departure. `started` is never mutated, so P2's re-handoff key `generation:started` (`p2_recovery_html_adversarial.py:2273-2290`) and `motionStart` are unaffected.
- **`bridgeElapsedMs(v, motion)`** picks the clock once per motion, at the first ride frame where one of these holds:
  - **`gl`:** the occurrence has a stamp. Progress is `Date.now() − gl.date`.
  - **`fallback`:** `performance.now() − started ≥ GL_CLOCK_WAIT_MS (50)`. Progress is `performance.now() − started`, which is today's clock.
  - Until then it returns 0, so the overlay holds the source rect. Keynote's poster is also there until its loop starts.
- **The latch.** A stamp that arrives after the fallback engaged is ignored, so there is no clock-switch jump. Under `gl`, a negative delta clamps to 0. A backward `Date` step moves the overlay back together with Keynote, by design.
- **No mid-move snap-back.** Mid-move re-marks keep the same occurrence and motion, and `rideTransition` keeps its first `rectAt` closure (`:1097`).

**The exact fallback guarantee.** From the fallback frame on, it is today's clock.
- Before that frame, the overlay holds at the source for 50–66.7 ms, then jumps forward to today's position.
- The jump is ease(≤66.7/D)·span:

  | Bridge | Jump |
  |---|---|
  | D1 b1to2 | ≤ 3.7 px (right edge) |
  | P2 | ≤ 1.2 px |
  | Any bridge with D ≥ 0.67 s | lands before the scored 10 % mark |
  | D = 0.5 s over 1000 px | 20–36 px, inside the scored window (Q3) |

- **Freeze bracket on the fallback.** The 1 px departure frame equals today's iff W ≤ L (P2 L = 61.0 ms), so the bracket sees today's behaviour. §7 pins this.

### 3.5 What records the clock

- **Core:** one `bridge-clock` note per motion, `{elId, via: 'gl'|'fallback', lagMs}`; `note()` adds `sceneHash`.
  - For `gl`, `lagMs = gl.perf − started`. It is negative on a late ride.
  - For `fallback`, `lagMs` is the time waited.
  - `__obedMotion.clock` holds the same data.
- **Probe:** `bridges[i].clock = {via, lagMs}`, report-only (§5).
- **`check_cc`:** asserts `via` per arm (§5).
- **P2:** `bridge-clock` joins `PRESERVE_EVENT_KEEP_KINDS` (`p2_verdict.py:130`), first in the sorted tuple, report-only.

### 3.6 Unknown players

The host and the dashboard gate on `SUPPORTED_PLAYERS` (`live_runtime.py:185,199`; `web/live.py:115`). On any other player:
- no assignment or no loop: fallback (§3.4);
- a non-function value: the getter passes it through;
- a foreign accessor: no hook, fallback.

### 3.7 JS sketch

**`markTransition`** (`:777-779`):
```js
    if (hn == null) return;
    if (!departure || departure.scene !== hn || departure.gen !== preserveGeneration) {
      departure = {scene: hn, gen: preserveGeneration, gl: null};
    }
```

**`replaceState` wrapper** (`:802-803`):
```js
        const hn = currentHashNum();
        if (departure && hn !== departure.scene) departure = null;
        if (!disabled && hn != null && hn === lastHashWrite) markTransition(hn);
```

**After `:808`:**
```js
  /**
   * Keynote's GL player times a transition on `Date` from its loop's first `requestAnimFrame` call; main.js assigns
   * it after this core runs, so a setter keeps the value and the getter wraps it. A call outside a wrapped callback
   * starts a loop; the first in a live departure stamps `departure.gl`.
   */
  let inGlFrame = false;
  function stampGlStart() {
    if (disabled || inGlFrame || !departure || departure.gl || departure.gen !== preserveGeneration
        || currentHashNum() !== departure.scene) return;
    departure.gl = {date: Date.now(), perf: performance.now()};
  }
  try {
    const prior = Object.getOwnPropertyDescriptor(window, 'requestAnimFrame');
    if (ENTRIES.some(function(b) { return b.action === 'bridge'; })
        && (!prior || (prior.configurable && 'value' in prior))) {
      let raw = prior ? prior.value : undefined;
      Object.defineProperty(window, 'requestAnimFrame', {
        configurable: true, enumerable: true,
        get: function() {
          if (disabled || typeof raw !== 'function') return raw;
          const f = raw;
          return function(cb) {
            if (typeof cb !== 'function') return f.call(window, cb);
            try { stampGlStart(); } catch (e) {}
            return f.call(window, function(ts) {
              inGlFrame = true;
              try { return cb(ts); } finally { inGlFrame = false; }
            });
          };
        },
        set: function(value) { raw = value; }
      });
    }
  } catch (e) {}
```

**Inside the `dstRect…keepAtSlot` slice**, after `easeInEaseOut`:
```js
  const GL_CLOCK_WAIT_MS = 50;
  /**
   * Ms into a bridge's move, chosen once per motion and noted (`bridge-clock`): Keynote's `Date` since its GL loop
   * start in this departure, else, once GL_CLOCK_WAIT_MS have passed on `performance.now()`, today's clock from the
   * core's trigger; 0 (the source rect) until one holds.
   */
  function bridgeElapsedMs(v, motion) {
    if (!motion.clock) {
      const gl = motion.departure && motion.departure.gl;
      const waited = performance.now() - motion.started;
      if (!gl && waited < GL_CLOCK_WAIT_MS) return 0;
      motion.clock = gl ? {via: 'gl', date: gl.date, lagMs: gl.perf - motion.started} : {via: 'fallback', lagMs: waited};
      note('bridge-clock', {elId: v.__obedElId, via: motion.clock.via, lagMs: motion.clock.lagMs});
    }
    return motion.clock.via === 'gl' ? Date.now() - motion.clock.date : performance.now() - motion.started;
  }
```

**`keepThroughBridge`** (`:1136-1143`):
```js
        || v.__obedMotion.boundary !== boundary || v.__obedMotion.departure !== departure) {
      v.__obedMotion = {started: performance.now(), generation: generation, boundary: boundary, departure: departure};
    }
    const motion = v.__obedMotion;
    ...
      const progress = easeInEaseOut(bridgeElapsedMs(v, motion) / (1000 * boundary.durationSeconds));
```

Also:
- Update the `markTransition` docblock: there is now one object per occurrence.
- Add two lines on the bridge clock to the module docstring, which does not change the sha.
- No inline comments.

## 4. Red controls (`scripts/continuity_core_variants.py`)

Each anchor must occur exactly once.

| Variant | Anchor → replacement | Purpose |
|---|---|---|
| **`no-gl-clock`** (new; D1 red) | `"    departure.gl = {date: Date.now(), perf: performance.now()};\n"` → `""` | The hook stays installed but never stamps. Every bridge takes the real fallback path: today's clock after the hold. |
| **`linear-bridge`** (P2 red, re-anchored) | `_BRIDGE_PROGRESS` = the new progress line → `Math.min(1, Math.max(0, bridgeElapsedMs(v, motion) / (1000 * boundary.durationSeconds)))` | A linear overlay on the product clock. |
| `gl-clock-bridge` | removed | Moved into the product; its evidence keeps sha `332f6516`. |

`VARIANTS = ("stash-any", "wrong-instance", "fifo-reuse", "linear-bridge", "no-pin-hold", "no-gl-clock")`. Anchor uniqueness and distinct shas are already tested.

**Predictions.**
- **`no-gl-clock` on D1:** fail.
  - b1to2's left strip is 6–9 px. Today's clock measured 6–9 px in 9 of 10 runs, plus the 53 px clock-step run. The margin is 1 px (Q2).
  - b2to3 has a right strip of ≈ 0.28 px/ms × the held-path lag.
  - Both bridges report `via: fallback`, with `lagMs` ≥ 50 (normally under 67).
  - Not gated on P2.
- **`linear-bridge` on P2:** fail, as in main's final round. `via: gl`.

## 5. `run_gates` carry-cover arms: P2 and D1

**Arms** (full tier only, queued where they are today, after paint control and before P2):
```zsh
CARRY_COVER_ARMS=("P2 pass" "P2 fail --core-variant linear-bridge" "P2 fail --carry-cover-null"
                  "D1 pass" "D1 fail --core-variant no-gl-clock" "D1 fail --carry-cover-null")
```

**Fixture and names.**
- One helper gives the fixture for both `run_cc` and `check_cc`, following the `HOST_DECK` pattern (`:321-322`):
  - P2: `$F/html-player` with `$F/html-unmodified/index.html`;
  - D1: `$Q/D1/html-unmodified` as both fixture and `index.html`.
- Stem: `carry-cover${deck:#P2}<args>`, giving `carry-coverD1`, `carry-coverD1--core-variantno-gl-clock` and `carry-coverD1--carry-cover-null`.
- Label: `${${deck:#P2}:+$deck }${label:-green}`.
- P2 stems and labels are unchanged, so they compare directly with `final-dcd5b9e4`.

**`check_cc`** keeps every existing condition (`:575-601`) and adds:
1. `d["fixture"]` equals the arm's fixture string. The probe writes `str(args.fixture)` (`live_continuity_probe.py:8167`).
2. Except on the null arm: `bridges` is non-empty and every bridge has `clock.via == ("fallback" if variant == "no-gl-clock" else "gl")`. A missing clock is a mismatch. This is the only way the P2 green can tell the GL clock from the fallback, since P2 passes on either.
3. One printed line per bridge: boundary, verdict, `maxStripPx`, `cleanShare`, `undecidedFrames`, clock.

**Probe changes** (`scripts/live_continuity_probe.py`):
- `CARRY_COVER_READ_JS` (`:7588-7601`) also keeps `bridge-clock` notes. `score_carry_cover` already filters by kind (`:7875-7878`), so scoring is unchanged.
- New `carry_cover_clock(notes, bridge, el_id)`. Exactly one `bridge-clock` note with this `elId` and `sceneHash == atScene − 1` gives `{via, lagMs}`; anything else gives `None`. It matches on identity, not time.
- `run_carry_cover` (`:8142-8148`) sets `bridge["clock"] = carry_cover_clock(read.get("notes"), bridge, scored.get("elId"))`. This is report-only; the probe status stays pixel-only.

**Predicted verdicts.**

| Arm | Status | Detail |
|---|---|---|
| P2 green | pass | `gl` |
| P2 `linear-bridge` | fail | |
| P2 null | fail | |
| D1 green | pass | both bridges strip ≤ 1, `gl` |
| D1 `no-gl-clock` | fail | b1to2 6–9 px, `fallback` |
| D1 null | fail | both bridges |

**Runtime.** A D1 arm takes 22–29 s. The three D1 arms add about 70 s of job time, about 25–35 s of wall time at `GATE_JOBS=3`.

**What blocks D1 today, and the fix for each:**

| Blocker | Fix |
|---|---|
| b2to3 double note | Fixed by `2f87dd41`, an ancestor of HEAD (`_is_bridge_note` `:7836-7842`). Never verified live: all 10 `cc-D1-glclock` artifacts carry the old reason text. GL-1 checks it. |
| `run_cc` hard-codes the P2 fixture (`:572-573`) | Per-deck fixture helper. |
| Artifact and label collision | The `${deck:#P2}` prefix. |
| No D1 red | `no-gl-clock`. |
| `check_cc` cannot see the clock | `bridges[i].clock` plus the `via` rule. |

## 6. Interplay with other gates

| Gate | Effect | Prediction |
|---|---|---|
| **P2 freeze bracket** | GL path: the departure moves by Δ = `lagMs`. The lead bound is 6 frames (`:3897-3899`, `_freeze_trigger_bounds` `:3472-3481`). r3 shows no read lag (71.1 = L+10.1), so **Δ ≤ 39 ms passes at every phase**. 39–50 ms can read INCONCLUSIVE at some phases. The displacement cap is safe, since a later origin means less displacement. Fallback: identical to today because W(50) ≤ L(61.0). | pass. Marker→trigger ≈ L+Δ … L+Δ+16.7 ms (≈ 68–85 ms if Δ ≈ 6.6); trigger frame 10 or 11. `bridge-clock` is kept for forensics. |
| P2 slide-3 restart, R10 | No clock dependency. | unchanged (0.106–0.222 s) |
| Pass G, paint instrument | Bind via `bridge-motion-start` (`paint_instrument.py:302`), which is unchanged. No other repo code reads bridge duration or curve. | unchanged |
| Host and P2 arms | The overlay lands about Δ later, together with the poster. | unchanged |
| Red registrations (V3) | Keyed by plan sha, but the core sha changes, so the core lands **before** V1–V6. | n/a |

## 7. Tests (minimal: 1 new JS test function, 1 new probe test function, 1 deleted)

| File | Change |
|---|---|
| `tests/test_live_continuity_js.py` | **Re-pin** `PINNED_CORE_SHA256` (`:34`). **Minimal-sandbox harness:** `_run_core_in_node` gains `before_core=""` and `after_core=""`; it reports `animFrame` only when `after_core` is set, so existing rows' dicts are unchanged. **Install rows:** 2 rows in `test_install_outcome`, both with a bridge plan: (a) a late-attached data property with `call_disable_after`, which calls through and is the raw function after `disable()`; (b) a non-configurable property, which installs without throwing, sets `ready` and still calls through. **Fragment stub:** `let departure = null;` in the `_run_bridge_motion_in_node` stub (`:270-276`); the fallback path keeps today's values. **New test:** `test_bridge_clock_follows_keynotes_gl_loop_start`, parametrized over the 4 timelines below. |
| `tests/test_continuity_core_variants.py` | Update the `VARIANTS` tuple (`:27-28`) and the `linear-bridge` strings (`:80-85`). **Delete** the gl-clock test (`:102-157`); its red row moves into the JS test. |
| `tests/test_p2_adversarial.py` | In the existing tripwire (`:2905-2907`): re-pin the progress line, assert `const GL_CLOCK_WAIT_MS = 50;` occurs once, and assert `50 <= latency` (W ≤ L). No new row. |
| `scripts/detach_experiment.py` | Re-pin `CORE_SHA256` (`:76`; asserted at `test_detach_experiment.py:152`). |
| `tests/test_live_continuity_probe.py` | **New** `test_carry_cover_clock_names_this_bridges_clock`, 3 rows: `gl` picked among a foreign-scene note and a foreign-`elId` note; `fallback`; two matching notes give `None`. |
| `tests/test_run_gates.py` | Extend `CC_STEMS`, `CC_LABELS` and `CC_EXTRA` and add `CC_DECKS`. The order test (`:959`) takes each stem's fixture from `_probe_args(events)["passG-P2"/"passG-D1"]`. The stub (`:188-206`) writes `fixture` and `bridges:[{clock}]` (`fallback` for `no-gl-clock`), with new modes `cc-clock` (flip `via`) and `cc-fixture`. **3 rows** in `:990-1003`: `carry-coverD1` `cc-clock`, `carry-coverD1--core-variantno-gl-clock` `cc-clock`, `carry-coverD1` `cc-fixture`. Update the docstring and the comment at `:946-947`. |

**The 4 clock timelines.** They use the full harness. `after_core` simulates `main.js`'s assignment and gives `Date` its own fake wall clock.
1. **`gl`.**
   - A loop running before the departure doesn't stamp, and the overlay holds the source at +4 ms.
   - A loop start at +7 ms stamps, and the rects then follow the ease on `Date`.
   - Two same-index `replaceState` writes plus a teardown mid-move keep the same `started`, with no snap-back.
   - A −90 ms `Date` step moves the overlay with Keynote's arithmetic.
   - Exactly one `bridge-motion-start` and one `bridge-clock {gl, lagMs 7}`.
2. **`fallback`.**
   - With no loop start, the overlay holds the source up to +49 ms, then follows today's ease from the trigger.
   - A `Date` step inside the wait does not move the deadline.
   - A loop start at +60 ms changes nothing.
   - `bridge-clock {fallback}`.
3. **`re-departure`.**
   - Mid-move, the hash goes to #8, then back to #7 without `clear()`, followed by the second write.
   - The same pooled element is re-driven via `remountAll()`.
   - It gets a new `started` and holds the source until its own loop start.
   - A second `bridge-clock {gl}` note.
4. **`no-gl-clock` (red, core monkeypatched).** On timeline 1, the overlay holds until +50 ms although Keynote started at +7. It then follows today's ease from the trigger, reports `bridge-clock {fallback}`, and `requestAnimFrame` is still callable.

The existing eased-overlay, re-detach and stage-mapping tests pass unchanged through the fallback path, which is the unit-level proof of "today from the fallback frame on".

## 8. Work streams (disjoint files; Opus MEDIUM implementers)

Branch off the S2 head at spawn time (`4a389a72`, or the head after the Astra r10 folds). Each stream gets its own worktree per `worktree-env-setup`. **A lands before V1–V6.**

**Stream A: core, variants and their tests.**
- Files: `src/obed_edom/live_continuity_js.py`, `scripts/continuity_core_variants.py`, `scripts/detach_experiment.py`, `tests/test_live_continuity_js.py`, `tests/test_continuity_core_variants.py`, `tests/test_p2_adversarial.py`.
- Acceptance:
```
OBED_EDOM_CACHE_DIR=/Users/anyhowclick/Desktop/work/obed-edom/.cache uv run pytest -q -n auto tests/test_live_continuity_js.py tests/test_continuity_core_variants.py tests/test_detach_experiment.py tests/test_p2_adversarial.py tests/test_p2_adversarial_arms.py tests/test_p2_adversarial_driver.py tests/test_live_gl_replay_js.py tests/test_managed_obs_qualify.py tests/test_paint_instrument.py tests/test_live_host.py
PYTHONPATH=$PWD/src:$PWD/scripts /Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python -m pytest -q <same files>   # 3.10 floor
uv run python -c "import sys; sys.path.insert(0,'scripts'); from obed_edom.live_continuity_js import js_sha256, CONTINUITY_VERSION as V; from continuity_core_variants import VARIANTS, variant_sha; print(V, js_sha256()[:12], {v: variant_sha(v)[:12] for v in VARIANTS})"
```
  The last line must print 6 and the new shas.

**Stream B: gates.**
- Files: `scripts/run_gates.sh` (including the header at `:3` and `:93-95`), `scripts/live_continuity_probe.py`, `src/obed_edom/p2_verdict.py` (one keep kind), `tests/test_run_gates.py`, `tests/test_live_continuity_probe.py`.
- B codes in parallel but rebases onto A before acceptance, because the stub imports `variant_sha("no-gl-clock")`.
- Acceptance: `zsh -n scripts/run_gates.sh`, then `uv run pytest -q -n auto tests/test_run_gates.py tests/test_live_continuity_probe.py tests/test_p2_adversarial.py tests/test_p2_adversarial_gl_replay.py`, plus the 3.10 floor.

**Stream C: docs.**
- `SKILL.md`: one carry-cover gate bullet (the P2 and D1 arms and the `via` rule) and one line on the bridge clock.
- Instrument plan `:50` ("P2 and D1") and `:398` (a pointer to this plan).
- Acceptance: `git diff --stat` touches only `.agents/`.

**Coordinator, after A → B → C merge:**
- the full suites: `uv run pytest tests/ -n auto --dist worksteal` (with `PYTHONDONTWRITEBYTECODE` unset), the 3.10 floor on the touched files, `npm run test:ui` and `npm run test:maps`;
- an Astra (high) review of the diff, folded until APPROVE;
- then §9.

## 9. Live validation (coordinator only; serial; load under 3 at start; at most 3 Chromes)

Run from a clean gate worktree `G` at the merged head, writing evidence to `output/evidence/s2-dev/glclock-v6/`. Before each timed window, tell the "Resizer optimizations" peer to go idle, and don't overlap the owner's OBS session.

**GL-1: D1 carry-cover, 5× green and `no-gl-clock` interleaved, then 2 nulls.**
```
cd $G; for i in 1 2 3 4 5; do for arm in green no-gl-clock; do extra=(); [[ $arm == green ]] || extra=(--core-variant $arm); quiet3
  PYTHONPATH=$G/src $PY -u scripts/live_continuity_probe.py --fixture $FX --original-index $FX/index.html --viewport 1920x1080 --carry-cover $extra --artifact $OUT/GL1/$arm-$i.json > $OUT/GL1/$arm-$i.log 2>&1; done; done
then null-1, null-2 with --carry-cover-null
```

Read the results offline:
- per bridge: verdict, `maxStripPx` and strips, `clock`;
- the largest change in `pts−domTs` between consecutive frames. Anything over 17 ms gets a `log show --predicate 'process == "timed"'` around `timeOrigin + t`.

Predictions:
- **green 5/5:** pass.
  - b1to2: strip ≤ 1, `gl`, lag 5–9.
  - b2to3: scored, which proves the note-scoping fix; strip ≤ 1; `gl` with lag under 50 (unmeasured).
- **red 5/5:** fail. b1to2 6–9 px, `fallback` with lag ≥ 50.
- **null 2/2:** fail on both bridges.

**GL-2: P2.**
- Carry-cover green, `linear-bridge` and null, once each. Predicted: pass, fail, fail; green `gl`.
- `p2_recovery_html_adversarial.py --reuse-export --disposable --wait-profile fast`, twice, plus `--gl-replay auto` once. Predicted:
  - the same success line as the last S2 round;
  - the freeze bracket passes, with marker→trigger ≈ L+Δ … L+Δ+16.7 ms, using the run's own `bridge-clock` `lagMs`;
  - slide-3 restart 0.106–0.222 s;
  - a kept `bridge-clock` note showing `gl`.

**GL-3: one full round.** Only if GL-1 and GL-2 met their predictions.
- `GATE_JOBS=3 run_gates.sh $G $OUT/GL3 --tier full`.
- Expected: `failed=2 pending=0`, exit 1. The two FAILED lines are exactly the unregistered `HOST red D5 --core-variant no-pin-hold` and `PASSG-RED D1 --core-variant no-pin-hold` (`run_gates.sh:59-64`, `:448-452`).
- The six carry-cover lines should match §5, and the wall time should be the last S2 round plus about 30 s.

**Send it back to the owner if any of these happens:**
- a green strip over 1 px, or any green `fallback` (D1 or P2);
- a D1 red reading pass;
- a green trailing strip of about 10–15 px (risk 3);
- any playback break: player build or page errors, a missing Magic Move, or an error mentioning `requestAnimFrame` → revert;
- a P2 freeze-bracket INCONCLUSIVE, or any P2 or host verdict differing from the last S2 round;
- a null arm passing;
- any GL-3 FAILED line beyond the two named above.

A null INCONCLUSIVE under round load is the known watch item: re-run it at `GATE_JOBS=1` and never widen the gap. A run with a `timed` step is reported, re-run once, and both results are reported. Neither run is ever used to turn a FAILED into a pass.

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Held-path lag ≥ 50 ms** (`renderEvent` sits between the trigger and the GL start). Chained bridges would then fall back. | `lagMs` makes it visible, GL-1 measures it, and Q1 covers the fix. |
| 2 | **The D1 red's margin is 1 px.** A lag under about 5.4 ms reads as a pass. | GL-1 ×5 plus GL-3; Q2. |
| 3 | **Lost first delta.** A frame between `animate()` and the `setTimeout(0)` that creates the Magic Move program drops up to 16.7 ms, so the poster trails by up to about 15 px. Seen 0 times in 20 D1 b1to2 runs. | GL-1 catches it. A real fix needs `main.js` knowledge, which is an owner call. |
| 4 | A GL lag of 39–50 ms on P2 could make the freeze bracket INCONCLUSIVE. | P2 lag is about 7 ms (model); the kept note shows it. |
| 5 | The null arm's coverage gap, now with two bridges, under 3-wide load. | Lower the load; never widen the gap. |
| 6 | A step during a fallback or red run gives a bigger strip. | The red still fails; green on the GL clock is immune; the offline skew check explains it. |
| 7 | An unrelated loop or a replay setting the origin. | Low: only `fB` loops call `requestAnimFrame`, there is one stamp per occurrence, and the lapse is on the hash. A hash moved away and back within 200 ms by something other than `replaceState` is the only residual case; the player and the host don't do it. |
| 8 | Short bridges (D under 0.67 s) on the fallback path: a 20–36 px jump in the scored window. | Only on a missed hook, which `check_cc` turns red; Q3. |
| 9 | All D1 evidence is on older cores (`7cb6e0fe`, `332f6516`). | GL-1 re-measures on the new core. |

## 11. Critique log

- **GL-3:** expects `failed=2 pending=0`; unregistered arms FAIL.
- **Fallback guarantee:** stated exactly, with corrected jump sizes (D1 ≤ 3.7 px, P2 ≤ 1.2 px, short bridges in-window); Q3 added.
- **Bracket on the fallback:** safe because W ≤ L. The W pin asserts `50 ≤ L`, and the redundant bracket row is dropped.
- **`run_gates` rows:** cover both `via` branches (3 rows instead of 4).
- **The `via` rule:** requires non-empty `bridges` and a present `clock`.
- **Replay timeline:** re-specified as a cut-short ride of the same pooled element.
- **Tests:** the red folds into the product clock test and the old variants-file test is deleted; harness keys are added only on demand; the probe test drops to 3 rows.
- **P2 numbers:** the lag is a model estimate, and the marker→trigger range is corrected.
- **Red `lagMs`:** now "≥ 50".
- **Hook block:** `ENTRIES.some(...)` moved inside the `try`.
- **Wording:** "no clock-switch jump", and the lapse rationale clarified.
- **Ordering:** GL-1 and GL-2 gate GL-3.

## 12. Owner questions (design-changing only)

- **Q1 (conditional).** If any green bridge reports `fallback` with a held-path lag of 50 ms or more: should the 50 ms wait start at the departure's latest setup mark instead of the core's trigger? The change is that `markTransition` refreshes `departure.at` and the wait becomes `max(started, departure.at)`. That is 2 lines plus 1 assertion in the fallback row. On D1 b2to3 the last mark is the end of the setup task, so the lag drops back to about 7 ms; the pooled path is unchanged. **Recommend pre-approving:** the GL path is unchanged and the fallback is still today's clock.
- **Q2 (conditional).** If the D1 `no-gl-clock` red ever reads a pass: should the D1 red become `linear-bridge` on D1, a robust detector check? A regression to today's clock would still be caught by the `via == gl` rule on both greens. Thresholds are never tuned. **Recommend pre-approving.**
- **Q3.** Should the fallback hold the overlay at the source and then jump forward to today's clock, as planned? The alternative is to run today's clock from the trigger and switch to the GL clock when the stamp arrives.

  | | Hold, then today's clock (planned) | Today's clock from the trigger |
  |---|---|---|
  | GL path (every show) | No jumps at all | A small backward correction: ~0.2 px on D1, up to ~18 px on a 0.5 s bridge with a 40 ms lag |
  | Fallback (missed hook only) | A forward jump of ≤ 3.7 px on D1; 20–36 px inside the scored window for bridges under 0.67 s | Exactly today |

  **Recommend keeping the hold.** It is correct by construction on the path every supported show takes. The fallback runs only on a missed hook, which the gates now turn red, and its deviation is bounded and confined to the first ≤ 67 ms.