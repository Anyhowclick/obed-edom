# One-frame detach at the post-MM `Playing` onset: plan (instrument, A/B, fix options)

Planner, read-only. Nothing was run live. Code citations are against the S2 head `4e6df7b5`
(`git show origin/claude/continuity-generalisation-s2:<path>`). `main.js` citations are byte offsets in the pinned player
(sha `e9b2fad4…`, the same in every D deck and P2). The scan scripts for §0 are in this folder's `tools/`
(`scan2.py`, `scan3.py`, `scan4.py`; pure readers of the evidence JSON, run with `python3 -I`).

## 0. What the existing evidence already shows (new; read before §1)

I re-scanned every deck and host artifact under `output/evidence/s2-dev/*/*.json`: 281 post-MM jumps that carry a
remounted decoder across them.

1. **Where the blink is.** It is not at the MM's onset. It is at the first `Playing` frame of the destination slide's
   automatic `movie-start` scene, right after the MM has finished. Example, D4 arm C: scene 4, the 2→3 MM, plays for
   1.6 s. Then the player idles for about 100 ms in `IdleAtFinalState`, then `SettingUpScene`, then scene 5 `Playing`.
   The empty sample is the first scene-5 frame. Every failing verdict is a **pin** carry at that jump: D1 pin@6,
   D4 pin@5, D5 pins @2 and @4 (attach), D6 pin@6. There is also a D2 arm-C hit at 7→8.
2. **R8 changes which path the player takes at that jump** (main.js `jumpToScene` 2352124):
   - **Waited (stock).** The destination slide is not yet in `slideCache`, so the player goes
     `IdleAtFinalState → WaitingToJump (70–100 ms) → SettingUpScene`. The jump resumes from pdf.js's render completion
     (`handleSceneDidLoad` 2353034).
   - **Direct (R8).** R8 already loaded the destination during the ≥1.5 s idle before the click that started the MM.
     `isScenePreloaded` is therefore true, and the player goes straight to `SettingUpScene` with no `WaitingToJump`.

   | Head | Waited jumps | Direct jumps | Blinks |
   |---|---|---|---|
   | Pre-rebase | 212 | 4 | 0 |
   | Rebased | 2 | 67 | **7, all in direct jumps** |

   - Blink rate by path: 7/67 direct vs 0/214 waited (Fisher one-sided p ≈ 3e-5).
   - Path and head are almost perfectly confounded, so this alone does not prove causation. §2 adds the arm that
     separates them.
3. **The documented R8 risk is not this failure.** That risk is "the g+1 render overlaps the MM's first frames". In
   these runs the R8 render ran during the 1.5 s pre-click idle, long before the MM.
4. **Only decoders inside the player's subtree blink.** Blinks among direct jumps on the rebased head, by arm:

   | Arm | Where the decoder sits | Blinks / direct jumps |
   |---|---|---|
   | A | Held as a bridge overlay, outside the player's subtree | 0/27 |
   | C | Pool-remounted into the outgoing slide's authored layer, inside the player's subtree | 5/13 (38 %) |
   | attach | Pool-remounted (D5 pins) | 2/27 |

5. **The carry lands later on the direct path.** At the first destination `Playing` sample:

   | Path | Already carried | Old instance still in DOM, not yet carried | Absent (the blink) |
   |---|---|---|---|
   | Waited | 211/212 | 1/212 | 0/212 |
   | Direct | 37/67 | 23/67 | 7/67 |

   So on the direct path, the fresh destination element's `src` (the carry, core `setAttribute` hook
   `live_continuity_js.py:2037–2055`) often lands in a later task than the jump's `displayScene`/`renderEvent`
   (`jumpToScene_partFour`, main.js 2353707).
6. **Timing.** The destination's first `Playing` comes 1900–1934 ms after MM setup on the direct path, against
   1983–2067 ms on the waited path.
7. **Working hypothesis (H0, to verify).** The two paths reach `partFour` with different frame phase:
   - **Waited.** The jump resumes from a pdf.js render that finishes inside a rAF callback (`_scheduleNext` uses
     `requestAnimationFrame`, main.js 60596). One `s()` = `setTimeout(…,100)` follows (main.js 1977494; 100 ms is 6.0
     frames). So `partFour` lands just after a vsync, and its follow-up tasks finish before the next rAF.
   - **Direct.** The jump inherits the click's arbitrary phase through `setTimeout` chains, so `partFour` can land late
     in a frame. A rAF then falls between the teardown task and the task that re-homes or carries the decoder.
   - Consequence: R8 only **exposes** a core race. On the waited path the race is hidden by phase lock. Fixing the race
     belongs in the core, not in R8 (§3), unless §2 says otherwise.
8. **Main may be affected too.** Main's core has the same detach guard and observer (`main:src/obed_edom/live_continuity_js.py:722`
   `if (v.__obedRemounting) return;`, `:1249` `beginMove`, `:1721` detach MO). Main also ships R8, and P2 has a pin at
   atScene 2 right after the 1→2 MM. P2 on main is therefore a product-relevance arm (§2.3).
9. **Two corrections to the handover.**
   - The 2560 round had 6 blink events in **5** of 6 runs (D3 was clean). Rebased total: 7 events in 6 of 11 runs.
   - "Empty `querySelectorAll` in a rAF callback" alone does not prove a painted blink. A re-home inside a later rAF
     callback of the same frame reads empty but paints fine. I3 below closes this.
10. **Chrome 154 (b7f4ea50).** The S2 head lacks main's attach-viewport hold, so the attach arm fails stageFit
    (scale 0.9491) on today's Chrome. Either keep attach out of the A/B, or cherry-pick `b7f4ea50` into the scratch gate
    worktree (no commit).

## 1. Instrument

### Level 1: probe side only, served bytes unchanged in every arm

All of Level 1 lives in a scratch driver that imports the probe from the gate worktree (`scripts/live_continuity_probe.py`)
and calls `run_arm` (`:2923`), under `bridge_disabled()` (`:1347`) for the arm-C condition. The JS is added to the
sampler page, installed by `drive_and_sample` (`:1414`) through `SAMPLER_JS` (`:433`).

- **I1. Core event dump.** The core already timestamps every note with `performance.now()` (`live_continuity_js.py:733–735`).
  - After the drive, read `JSON.parse(JSON.stringify(window.__OBED_P2_PRESERVE__.events))` unfiltered. (The probe's
    `CORE_EVENTS_JS` at `:421` filters it and is only read for refusal evidence; deck arms save none today.)
  - Store it per run.
  - Kinds that time the re-home: `preserve-on-detach[-subtree]` (`stash`, `:826`, note at `:904`),
    `remount-scheduled` / sync `tryRemount` (`scheduleRemount` `:924`, sync call `:950`, retries `:951–955`),
    `remount-authored-parent|into-authored-layer|done` with `inDocument` (`tryRemount` `:1463`, placements `:1484/:1549/:1612`),
    `remount-footprint-rect` / stage-map-unavailable (`:1535`), `reuse-decoder` (`carry` `:1969`), `dom-swap`
    (`bindFacade` MO `:1692`), `createElement-video` (`:2037`).
- **I2. Video lifecycle observer.** A probe `MutationObserver` on `document.documentElement` (`{childList, subtree}`),
  created after the core's.
  - It is delivered after the core's detach MO (`:1897–1911`), in the same checkpoint, because MO delivery follows
    creation order.
  - For every added or removed node that is, or contains, a `<video>`, log:
    - `t`, add/remove, the probe id, `__obedElId`, `__obedInstance`;
    - `isConnected` at delivery, which answers "did the core re-home synchronously?";
    - `__obedRemounting`, `dataset.obedPreserved/obedRemounted`, `!!__obedHold`, `__obedRemountEpoch`;
    - the parent's/layer's id;
    - `__obedLive.snapshot()` `{playerState, sceneId, revision}`.
  - Caveat: `bindFacade` MOs are created later, at carry, so they are delivered after this one. Correlate with the
    `dom-swap` note `t` from I1.
- **I3. Pre-paint truth.**
  - A `ResizeObserver` callback runs after all rAF callbacks and layout, just before paint. Use it on a 1-px sentinel
    inside a **closed shadow root**, so the core's MOs (`:1897`, `:1692`, `:1769`) never see its mutations. The sampler
    `tick` toggles the sentinel's width every frame.
  - Each callback records `{t, nVideosConnected, decoder ids, document.elementsFromPoint(center of the pin dst rect)[0]}`.
    The last field shows what actually paints in the slot: poster canvas, GL canvas or decoder. That gives severity
    (poster flash vs hole).
- **I4. Frame phase.**
  - Change `tick` (`:477–509`) to `function tick(ts)` and store `rafTs`, the frame time.
  - Phase of the teardown task = `t(first I2 removal at the jump) − rafTs(previous frame)`.
  - Also store per-run rAF Δt stats: median, p95, and the count of Δt > 25 ms.
- **I5. R8 path flag, needs no bytes.** Per post-MM jump, `waited = WaitingToJump` appears between `IdleAtFinalState`
  and `SettingUpScene` (from the sampled `playerState` runs; `scan2.py` already computes it). A render takes several
  frames, so a real `WaitingToJump` is never sub-frame.
- **I6. Run metadata.**
  - Before each run: `sysctl -n vm.loadavg`, `uptime`, `pgrep -c -f 'Google Chrome'`, `pmset -g therm`, Chrome
    `--version`.
  - From the artifact: served shas, i.e. `output.mmOpacity.sha256` (`live_host.py:1064–1068`) and the continuity sha.
  - Viewport and wall clock.

### Level 2: mechanism session only; debug bytes, identical in every arm compared

- **L2a. Expose the controller.**
  - In the probe process, patch `obed_edom.live_runtime._INSTALL` (`live_runtime.py:85–161`; spliced at `:176–179`) to
    add `Object.defineProperty(window,'__obedDebugController',{value:controller})` inside the IIFE.
  - Record the new served sha per arm.
  - From page JS, wrap instance methods. The player calls them through `this.` property lookup, so instance shadowing
    works:
    - `textureManager.loadScene` (`preloadTextures` 2347682): log `(t, sceneIndex, caller=preloadTextures?, events[B]` is
      MM`)`. This answers "R8 issued?";
    - `textureManager.isScenePreloaded` (`jumpToScene` 2352124): log the result at the MM's jump and at the post-MM
      jump. This answers "`slideCache[g+1]` ready at MM setup?";
    - `textureManager.processTextureDidLoadCallback`: log render completion per slide, to compare against MM setup and
      first frames. This answers "overlap?";
    - `jumpToScene_partFour` (2353707): log task start and end;
    - `playbackController.renderEvent` / `animateEffects`: separates teardown from the fresh-element task.
- **L2b. Core trace variant (only if I1/I2 leave the early-return branch ambiguous).**
  - A probe-only variant via the `injected_core_variant` seam (`live_continuity_probe.py:1355`; anchors count-checked
    as in `scripts/continuity_core_variants.py:24–60`).
  - It adds `note()` at `stash`'s silent returns: `:831` `__obedRemounting`, `:866` not poolable, and the readyState
    gate.
  - The core sha changes for this variant; diagnosis only.

### Controls (run first; a failing control voids the session)

All four controls fire at a pin boundary in **arm A**, which never blinks naturally, so the background is clean.

| Control | Action | Expected | Pass condition |
|---|---|---|---|
| **Blink null** | On the first `dom-swap` note at the boundary, set `v.__obedRemounting=true`, then `p.removeChild(v); p.insertBefore(v,next)` synchronously. (The flag is the core's own self-move convention, so its MO stays out.) | I2 shows remove and add at the same `t` | 0 empty samples and 0 pre-paint empties |
| **Blink positive** | Same, but re-insert after `requestAnimationFrame(()=>requestAnimationFrame(…))` | Exactly ~2 frames empty in samples **and** pre-paint; the I2 gap spans 2 `rafTs` | All three agree |
| **One-task variant** | Re-insert in `setTimeout(0)` | Calibrates the real case: empty only when a rAF falls between the two tasks | Intermittent; record the rate |
| **R8 flag** | Run under four servings: `mm_opacity="off"` (`live_host.py:765–772`), sha `7cf00b56…`; R1–R5 (`21476f78…`); R1–R7 (`3730d38e…`); R1–R8 (`574274e8…`). With L2a, also confirm the `loadScene(B+1)` log matches. | `waited` true at every post-MM jump for off/R1–R5/R1–R7. Under R1–R8 every jump after a click MM is direct (`waited` false); evidence so far 67/69. | Flag matches expectation |

Precomputed served shas, from the S2 `live_runtime.py` on the pinned `main.js`:

| Serving | sha |
|---|---|
| R1–R8 | `574274e8…` |
| R1–R7 | `3730d38e…` |
| R1–R5 | `21476f78…` (**byte-identical to the pre-rebase served player**, as the pre-rebase artifacts record) |
| R1–R5+R8 | `ac8dcda0…` |
| off | `7cf00b56…` |

## 2. Experiment

### 2.1 Arms: same checkout, so only the player bytes vary

- **Checkout.** A detached gate worktree at the S2 head `4e6df7b5`. Core `9c4fc61f` in every arm. Same probe, host and
  Chrome.
- **How the arms vary.** Probe-process monkeypatch of `obed_edom.live_runtime._MM_OPACITY_REPLACEMENTS`
  (`live_runtime.py:42–83`). It is read at call time by `_apply_mm_opacity` (`:190–197`), which `live_host` reaches
  through `patch_player`.
  - Assert the identity of R8 before slicing: `t[7][0] == b"this.textureManager.loadScene(B)}unloadTextures(){"`
    (`:77–82`).
  - Assert the served sha per run.
- **The arms:**

  | Arm | Replacements | Role |
  |---|---|---|
  | V8 | R1–R8 | As shipped |
  | V7 | R1–R7 | The direct test: R8 dropped alone; R6/R7 stay |
  | V5 | R1–R5 | Byte-equal to the pre-rebase player |
  | (opt) V5+8 | R1–R5 + R8 | Sufficiency |

- **External control (optional).** Recreate `s2-gate-089a0393` detached and run 10 runs, only to tie back to the 0/29
  history. V5's byte identity makes it non-essential.

### 2.2 Decks, arms, viewport

- **Primary event.** A post-MM automatic jump that carries a **pool-remounted** pin decoder. That means the arm-C
  condition (`--strip bridge`, as in `bridge_disabled()`) at **2560×1440**.
- **Decks.**
  - D4 (pin@5): 1 event per run.
  - D1 (pin@6): 1.
  - D6 (pin@6, pin@8): 2.
  - Rotate the three per block.
- **Secondary decks.**
  - P2 host at 2560 (pin@2 after the R8-engaged 1→2 MM; product deck). One launch arm per run, 1 event.
  - D5 only if `b7f4ea50` is cherry-picked. D5 pins appear in A and attach; attach gave 2/4.
- **Excluded.** Arm A (held bridge overlay, 0/27) and B (continuity off). They are kept only as the controls' carrier.
- **Viewport factor.** After the decisive A/B, run one V8-only block of about 10 runs at 1920×1080. Prediction under H0:
  a lower rate, because shorter tasks at 1080 leave a narrower window.

### 2.3 Sample size and decision rule

- **Base rates on the rebased head.** Arm C 5/13 (38 %; 95 % CI ≈ 14–68 %). All arms 7/67 (10 %).
- **Target.** ≥ 30 eligible events per arm, about 23 runs per arm.
  - At 38 %, V8 expects about 11 blinks. P(≥ 5) ≈ 0.99.
  - 5/30 vs 0/30 gives Fisher one-sided p ≈ 0.026. 6/30 vs 0/30 gives about 0.012.
- **Early stop.** Stop after ≥ 15 blocks if V8 ≥ 6 and V7 = V5 = 0.
- **Futility.** If V8 < 3 by 30 events, the effect is not reproducing (it is condition-dependent; see the cluster). Go to
  the stress block (§2.4) before concluding anything.
- **Analysis.** Per event: blink = empty sample flanked by non-empty samples **and** a pre-paint empty (I3). Report
  both.
  - Primary: Fisher V8 vs V7 and V8 vs V5.
  - Sensitivity: stratified by block (Cochran–Mantel–Haenszel) and by I4 phase. H0 predicts that blinks only occur at
    late phase, and only on direct jumps.
- **Main relevance.** On **main's** head, run 10 P2 host runs at 2560, launch arm, R8 on as shipped.
  - Any blink means a live main bug, because main's core has the same guard. Escalate separately.

### 2.4 Load confound, interleaving, concurrency

- **Interleave.** Blocks of {V8, V7, V5} in a random order per block, with the deck rotated per block. Never run arms in
  separate time windows. The cluster (6 of 7 in one round) shows that conditions drift.
- **Load.** Record I6 per run, and stratify on it. Reject a run with any rAF Δt > 50 ms inside the jump window ±200 ms;
  call it INVALID and retake it.
- **Concurrency: run THIS experiment serially.**
  - The effect is a sub-frame task-vs-rAF race. CPU contention from other headless Chromes changes task latency and
    frame pacing, which is exactly the variable under test. It is the likeliest explanation of the cluster.
  - Running two streams in one checkout is also unsafe. `prepare_export` rmtree's the shared `cache_dir(PROBE_DIGEST)/html-{tag}`
    (`live_continuity_probe.py:771–782`). The probe's `check_no_leftover_chrome` (`:4667`) would also flag other
    streams' Chromes.
  - If the pool must be used: one worktree per stream, one block's three arms run **simultaneously** so they share
    contention, concurrency recorded as a covariate, and never pooled with serial blocks.
  - Recommended stress test, after the serial verdict: one V8 block with 3 concurrent streams, to test "load raises the
    rate".
- **Wall time.** About 30–35 s per scratch single-arm run (Chrome launch, export copy, then dwell 3 s plus per slide
  `CLICK_DELAY_S` 1.5 + `POST_ADVANCE_SETTLE_S` 1.8 + the MM).

  | Batch | Approximate wall time |
  |---|---|
  | Controls | 10 min |
  | 23 blocks × 3 arms | 40 min |
  | 1920 block | 6 min |
  | Main P2 ×10 | 6 min |
  | Total, session 2 | ≈ 60–70 min |

  - Using the probe CLI `--strip bridge` red arm instead (`run_red_arm`, `:5278`; adds census and plan derivation)
    takes about 45 s per run, about 85 min in total.
  - Full deck runs (A/B/C/attach/V/Voff) take about 2.2 min per run. Do not use them for the A/B.

### Sessions

| Session | Work |
|---|---|
| 1 | Scratch driver and Level 1; controls; 5 V8 runs to confirm the events are captured |
| 2 | The interleaved A/B (§2.3) plus the 1920 block plus main's P2 |
| 3 | Level 2 on V8 only (about 15 runs) to name the branch (§4). Then the fix candidate as a probe-only core variant: V8+fix vs V8, ≥ 30 events each, interleaved |

## 3. Fix options

Ownership: the core JS (`live_continuity_js.py`, v6) is S2-owned. `live_runtime.py` (R1–R8) is **main's** file
(#238), so changing it is a main PR. Owner rule: never modify `main.js` on disk; only sha-pinned, in-memory
`patch_player` replacements.

### (a) Same-task re-home, in the core. **Recommended direction**

Pick the variant from §4.

| Variant | When | Change |
|---|---|---|
| a1 | H1, guard swallow | In the detach MO (`:1897–1911`), skip a removed decoder only if it `isConnected` at delivery (a self-move). Always `stash` a disconnected one, bypassing the time-window guard at `:831`; that guard stays for other callers. Self-moves (`tryRemount` `:1487/:1553`, `bindFacade` `:1716–1722`, bridge `:1059/:1123/:1140/:1243`) leave the node connected at delivery. Deliberate removals stay safe by their own gates: retire (`retireDecoder` `:1395`, gen −1), facade stubs (`__obedFacadeFor`), `clear()` (stale gen). |
| a2 | H2, `tryRemount` bails | In `tryRemount` (`:1463`), never return with a pooled or held decoder disconnected. Fall back to the stage overlay at `restingRect` (`:1612` path) when the stage map or placement fails at `:1535`/`:1549`. |
| a3 | H3, re-homed into a container the next task removes | a1 alone covers it, because the second removal re-stashes. Otherwise (b). |

- **Cost.**
  - Core sha changes: re-pin `PINNED_CORE_SHA256` (`tests/test_live_continuity_js.py:32`).
  - `CONTINUITY_VERSION` 6 is a decision. It is a behaviour fix, not a contract change, so the recommendation is no
    bump; ask the owner.
  - Every variant re-derives: `variant_sha` follows the core automatically. Re-run `variant_core`'s count checks (the
    `stash-any` anchors sit near `stash`). `RED_ARM_EXPECTATIONS` are keyed by plan sha and label, not core sha, so
    nothing needs re-registering, unless a red set moves.
- **Gates.**
  - Full suites (pytest, `test:ui`, `test:maps`).
  - P2 harness, nine arms.
  - Host gates: P2 at 1600/1920/2560 plus the 16 host/deck red arms.
  - D1–D6 dev loop at 1920 and 2560, then the 1600×1000 round and Pass G.
  - All of this is already owed by §3.4 (Q1–Q3, …), so the fix lands **before** that one re-qualification. It is not
    an extra round.
- **Risks.**
  - Re-stash loops: the guard exists to stop exponential rescheduling, and the connectivity test keeps it for
    self-moves.
  - Double painters (stub vs real).
  - Restart and retire semantics.
  - The P2 note counts. The `glReplay@2` false red showed instrument checks keyed on note counts (`refusalEventsN`).
  - The **restart clock**: #238's lesson was +0.2 s on the slide-3 restart. Measure it in the P2 fast arm against the
    baseline 0.094 s (limit 0.35 s) and in the host restart verdict.

### (b) Keep the decoder outside the torn-down subtree, in the core

- **Change.** Hold a pool-remounted pin as a stage-level overlay from the MM end until its carry, then use the existing
  `pin-rehome` into the destination layer (`carry` `:1994–2010`, `bindFacade` `:1735–1741`).
- **Evidence.** Arm A (held bridge overlay) shows 0/27 on the direct path.
- **Trade-off: z-order.**
  - The authored-layer remount exists for P2 Finding 2: later-authored artwork must paint in front (comment at `:1546`).
  - An overlay paints over the artwork for that window, and over the MM's GL canvas during the move if it is applied
    earlier.
  - It is a larger behaviour change. It needs the V/Voff visible passes, the paint oracle and a Finding-2 check, on top
    of (a)'s gates.
  - Use it only if (a) cannot be made deterministic.

### (c) Adjust R8, in the player patch (a main PR)

| Option | Change | Effect |
|---|---|---|
| c1 | Preload B+1 only when R6 can engage: the MM has a scaled leaf with no `contents` whose end quad matches one destination leaf in the script JSON (texture-free precheck) | D decks go back to stock timing; P2 1→2 still preloads |
| c2 | Revert R8 | Breaks #238: owner decision 3b, `hbnopre` reads 2.788 px |
| c3 | Preload later | Reintroduces the render/MM overlap and the restart delay (#238 gates-r1) |

- **Why not recommended.** All three only **mask** the core race. Any direct, random-phase jump still exposes it:
  automatic MMs, go-to, slow machines, P2 itself under R8.
- **Cost.**
  - The `patch_player` sha changes: re-pin `tests/test_live_runtime.py:258–260` (`574274e8…`).
  - Re-run #238's gates: `mm_handback_probe`, `mm_opacity_probe` MO-1/4/5 with `mixFactor` ordinals, the P2 bridge-off
    restart clock, and managed-OBS M3/HB-OBS (an **owner OBS session**).
  - Then rebase S2 and redo its dev loop.
- **When to use.** Only as an owner-chosen stopgap, if main's P2 blinks (§2.3) and the core fix is far off.

## 4. Decision tree

1. **Controls.**
   - Blink positive not detected, or the null flags something: fix the instrument. Stop.
   - R8 flag wrong: fix I5 or L2a. Stop.
2. **A/B at 2560, serial.**
   - **V8 blinks, V7 = V5 = 0** (meets §2.3). R8 is necessary. H0 is confirmed if every blink is a direct jump at late
     I4 phase. Go to 3.
   - **V7 also blinks at a rate like V8.** R8 is not the cause.
     - If V5 also blinks: the cause is environmental (Chrome 154 or OS), but it is still a core race. Go to 3.
     - If V5 is clean: suspect R6/R7. Run V5+R6/R7 and bisect.
   - **V8 < 3 in 30.** The effect did not reproduce. Run the stress block (3 concurrent) and the 1920/2560 contrast.
     - If it reproduces only under load: the cause is still a race. Go to 3, and record load as a trigger.
     - If it never reproduces: park it, with the instrument kept in the dev loop.
   - **Main's P2 blinks.** Flag a live main bug to the owner now. Offer (c1) as a stopgap until the S2 core fix.
3. **Level 2 mechanism (session 3), on V8.** Classify each blink by its I1/I2 signature:

   | Hypothesis | Signature | Fix |
   |---|---|---|
   | H1, guard swallow | The removal shows `isConnected=false` and `__obedRemounting=true`, with no `preserve-on-detach*` note; the decoder comes back only at `dom-swap`/`reuse-decoder` in a later task | (a1) |
   | H2, `tryRemount` bails | `remount-scheduled` appears with no successful `remount-*` (or `remount-footprint-rect` / stage-map-unavailable), and the decoder stays disconnected | (a2) |
   | H3, re-homed then removed again | `remount-*` with `inDocument:true` at T1, then a second removal in T2 that matches H1 or H2 | (a1), else (b) |
   | H4, other remover | A `retire-boundary` note, or the decoder taken out of the stub swap path | Targeted fix in `retireDecoder` or `bindFacade` |

4. **Fix verification.** Run the candidate as a probe-only core variant: V8+fix vs V8, ≥ 30 events each, interleaved.
   - Pass: 0 blinks with fix, no new reds, the positive control still detected, and the P2 restart clock unchanged.
   - Then land it in the core, re-pin, and run the §3 gate list. If (c) was chosen, run #238's gate list too.
