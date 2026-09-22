Not ready to approve. I found 2 high-severity runtime defects, 4 medium edge cases, and 1 medium G1b derivation defect. Final-sha Q3 gate evidence is also still outstanding. I did not run pytest or Chrome; I relied on the supplied tallies and gate records.

## Standards

1. **New class — Low** — duplicate section banner  
   [tests/test_live_gl_replay_js.py:503](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/tests/test_live_gl_replay_js.py:503)

   The “2. Node sandbox” heading appears twice.

   **Exact fix:**  
   “Delete the first duplicate `# 2. Node sandbox` banner at lines 503–505.”

2. **New class — Low** — stale, misleading unused test constant  
   [tests/test_live_gl_replay_js.py:138](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/tests/test_live_gl_replay_js.py:138)

   `PRE_ARM_REASONS` is unused, and its comment says several reasons owe no release even though the actual tests correctly require release for them.

   **Exact fix:**  
   “Remove `PRE_ARM_REASONS` and its comment. Keep `NO_RELEASE_REASONS` as the single test declaration of the release exemption.”

3. **Closed class — Low** — stale one-site wording in the plan  
   [.agents/plans/keynote_live_gl_replay_g2.plan.md:100](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/.agents/plans/keynote_live_gl_replay_g2.plan.md:100)

   The completed S1 criterion still says every reason has exactly one site, contradicting the documented two-site `canvasRemoved` exception.

   **Exact fix:**  
   “Replace the criterion with: `Every reason string is defined once and emitted from exactly one site, except canvasRemoved, which is emitted from its two documented sites; js_sha256() is stable.`”

4. **Closed class — Low** — stale opacity terminology in the plan  
   [.agents/plans/keynote_live_gl_replay_g2.plan.md:54](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/.agents/plans/keynote_live_gl_replay_g2.plan.md:54)  
   [.agents/plans/keynote_live_gl_replay_g2.plan.md:60](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/.agents/plans/keynote_live_gl_replay_g2.plan.md:60)

   These lines still describe program-level `progOpacityBefore`, although the amendment and implementation now require per-draw `restOpacity`.

   **Exact fix:**  
   “At §2.3, say `Capture restOpacity[i] immediately before every draw during replayFrame({capture:true}).` At §2.5, say `uniform1f(loc, the restOpacity from that program’s last draw)`.”

Standards summary: **4 findings; worst severity Low.** The implementation otherwise satisfies the named conventions: no minified player identifiers, threshold literals are traceable, and the prior broad inline-comment/docstring concerns are closed.

## Spec

1. **New class — High** — caught GL failures can bypass `glError` and strand ARM-POST  
   [src/obed_edom/live_gl_replay_js.py:426](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:426)  
   [src/obed_edom/live_gl_replay_js.py:504](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:504)  
   [src/obed_edom/live_gl_replay_js.py:761](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:761)

   `replayFrame()` converts recorded-call exceptions into an `errs` count, but every production caller ignores it. `sampleOnce()` converts read failures into `bands=null`/`glErr=-1`; `markerSwap()` ignores that result and accesses `dark.length`. That exception escapes `armPost()` into the scheduled poll callback, leaving the runtime in ARM-POST with the seam unreleased rather than taking the sole `glError` stand-down path. A replay call that throws without setting a GL error is similarly invisible.

   **Exact fix:**  
   “Introduce one `requireGlClean(ok, detail)` helper containing the sole `assertOr('glError', …)` emission. Make `replayFrame` report every caught uniform or recorded-call failure through that helper, with `state.replaying--` in `finally`. Make `sampleOnce` report read exceptions and nonzero GL errors through the same helper. Abort `markerSwap`, `proveOpacity`, `armPost`, and `tickOnce` immediately when `state.down` becomes true. Add sandbox cases where a recorded draw throws without setting a GL error and where ARM-POST `readPixels` throws; both must finish RETIRED, remove the handle, and release exactly once.”

2. **New class — High** — canvas qualification silently ignores two required shape failures  
   [src/obed_edom/live_gl_replay_js.py:1078](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:1078)

   A context on an invalid canvas ID is silently ignored instead of producing `canvasShape`. The check also verifies `isConnected` but not that the canvas is under `#stage`. Either case can leave the module indefinitely in ARM-PRE with no stand-down or release.

   **Exact fix:**  
   “For the first WebGL context encountered while ARM-PRE, evaluate the complete canvas-shape predicate: ID matches `/^\\d+-canvas$/`, canvas is connected, `#stage` exists and contains it, and backing dimensions equal authored dimensions. Route any failure through the single `assertOr('canvasShape', false, detail)` site. Add natural tests for a bad ID and for a connected canvas outside `#stage`; both must retire and release once.”

3. **New class — Medium** — `movieSlot` may come from the wrong source event  
   [src/obed_edom/live_continuity.py:1319](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_continuity.py:1319)

   `_drawn_slot_index()` returns the first source event containing the movie. `slotSizes` and `slotRects`, however, come from the qualifying transition effect’s `baseLayer`. If an earlier event has a different draw order, `movieSlot` no longer indexes those arrays.

   **Exact fix:**  
   “Pass the qualifying transition event into `_drawn_slot_index` and compute the slot exactly once from `_draw_slots(transition, src_slide_name)`. Do not scan unrelated source events. Add a derivation test with an earlier event whose draw order differs from the transition effect and assert that `movieSlot` indexes the transition’s movie slot.”

4. **Edge case — Medium** — `contextLost` reason does not itself enforce the cleanup exemption  
   [src/obed_edom/live_gl_replay_js.py:794](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:794)

   `standDown(CONTEXT_LOST, …)` recomputes `lost` solely from `isContextLost()`. If the browser emits the event before that guard changes—or the forced path is used—it can attempt write-back and poster restoration on the context, contrary to the context-loss exemption. The current event test pre-sets `_lost`, so it cannot expose this case.

   **Exact fix:**  
   “Initialize `lost` as `reason === CONTEXT_LOST || !g || (…)`. Add an event-only test that dispatches `webglcontextlost` while fake `isContextLost()` remains false and assert zero GL calls, one release, and RETIRED.”

5. **Edge case — Medium** — write-back failure can leave the wrong current program  
   [src/obed_edom/live_gl_replay_js.py:810](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:810)

   If `uniform1f` throws, control skips `g.useProgram(prev)`. Release still happens, but the player inherits whichever replay program was selected immediately before the exception.

   **Exact fix:**  
   “Capture `prev` before the write-back loop and restore it in a nested `finally`, independently of individual `uniform1f` failures. Continue the remaining best-effort writes, record `writebackFailed` once, then complete poster restoration and release. Extend `writeback_fails` to assert the original `CURRENT_PROGRAM`, one release with the expected rect, and—in the unflagged-player-call variant—that the forwarded call remains last.”

6. **Edge case — Medium** — failed wrapper installation is not detected  
   [src/obed_edom/live_gl_replay_js.py:295](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:295)  
   [src/obed_edom/live_gl_replay_js.py:1139](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/src/obed_edom/live_gl_replay_js.py:1139)

   Prototype assignments are not verified. Because the IIFE is not strict, assignment to a non-writable method may fail silently, after which no frame is captured and `glReplayUnavailable` is never emitted.

   **Exact fix:**  
   “Make `wrapContexts()` return false if a required descriptor cannot be replaced or if reading it back does not return the wrapper. Verify the `getContext` replacement the same way and route either installation failure through `refuseInstall('glReplayUnavailable', false)`. Add a sandbox case with a non-writable prototype method.”

7. **New class — High qualification gap, not a code defect** — final-sha gates are incomplete  
   [.agents/plans/keynote_live_gl_replay_g2.plan.md:109](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-live-continuity-handover-11b551/.agents/plans/keynote_live_gl_replay_g2.plan.md:109)

   The recorded Q3 failure predates N1/N2 fixes, and the supplied 18/20 fail-closed result predates N3. The final bytes therefore do not yet have the required soak and 20/20 evidence.

   **Exact fix:**  
   “Do not close G2 until the final pinned SHA has a passing Q3 soak and a 20/20 fail-closed run recorded in the gate evidence. Record the exact SHA, runtime duration, viewport, seam, and result for both reruns.”

### Closed checks

- **Fail-closed:** Normal stand-down paths unpublish the handle and release once; N3 correctly excludes rest replay for `canvasRemoved`, `contextLost`, and `unflaggedPlayerCall`. Findings 1, 4, and 5 are the remaining gaps.
- **LIVE loop:** The one-loop design, `loopGen`, watchdog, end-of-media fallback, and repeated pause/resume behavior are sound. rVFC callbacks run before rAF callbacks in the rendering update, so `sawVfc` suppresses the same-frame watchdog tick rather than double-ticking. [requestVideoFrameCallback specification](https://wicg.github.io/video-rvfc/)
- **Sentinels and identity:** The D1 `null`/zero handling, `WeakMap` texture identity, explicit per-draw opacity writes, and shared-program per-draw rest capture are closed.
- **Write-back ordering:** The ordinary `unflaggedPlayerCall` ordering is correctly inside the wrapper and before `orig.apply`; the context-loss and exception edges are findings 4–5.
- **Product reachability:** `API.debug` and `debugForceFail` are absent on the normal product path. `gl_replay_script()` returns zero bytes without a usable entry and case-insensitively escapes `</script`.
- **G1b:** `instanceId`, exact `instanceRect`, ambiguity refusals, flag-off output, and the two-SHA allowlist are closed. `movieSlot` selection is finding 3.
- **Tests as an instrument:** Sticky uniforms, per-call ordering, release assertions, N1–N3, one-site checks, and mutation evidence are substantive. The missing failure injections are identified in findings 1, 2, 4, 5, and 6.

Spec summary: **7 findings; worst severity High.**