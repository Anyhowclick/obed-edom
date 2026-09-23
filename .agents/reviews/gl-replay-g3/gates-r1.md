# G3+G4 headless gates — round 1 (2026-09-23, branch `2884e116`, core v5 sha 914464e4…, G2 module 985afeb1…, product flag `gl_replay="auto"`)

Results: `output/live-visible-content/g3/r1/<arm>/result.json` and `r1/gates.json` (analyser `g3/analyse_g3.py`, plan rev 2 §6 with
the coordinator rulings of 2026-09-23 recorded as `specNote`s). G-0 and G-P2 are in `output/gates-g3/{g0,gp2-2884e116}/`. Pinned
detached worktrees: `gates-g0-9ad4fc69` and `gates-g3-2884e116` (clean). Every armed arm asserts `inject == product`, and
`output.continuity.glReplay` is `{mode: injected, version: 1, sha256: 985afeb1…}`. Lanes: at most 3 Chromes; `run_gates` and the go-to
arms ran alone, and Q3 ran alone as a single 1224 s call. Load 4–17 (the first G-0 fast attempt hit a CDP timeout at load 76 and was discarded).

| Gate | Verdict | Numbers |
|---|---|---|
| G-0 (`9ad4fc69`) | recorded | host ×3 `pass`; P2 fast True 14/False —, fast+no-bridge success False, 13 True/False `continueThroughMovingMagicMove3to4`, slow 14/—; sha 68262ab8…; 1019 s |
| G-P2 (blocking) | PASS | host ×3 verdicts == G-0 (default path is `glReplay.mode off`). P2 ×3 success/True counts/False lists == G-0, `refusedCarry1to2.ok` with `glReplayFallback: moduleAbsent` in all 3, injected boundaries `glReplay, restart, bridge`. Printed sha 914464e4… == `PINNED_CORE_SHA256` == served sha, consistent start/end |
| 1 install order | PASS | 245 wrapped at install, `getContext` wrapped, main.js unseen; served order plan < core < `obed-gl-replay` < fit < `#stage` < main.js; control has no tag |
| 2 full 1→2 | PASS | arm, live; settleGapMs 99.7, settleToHashMs 100.2; frameLen 88, 0 GL errors, occluded 20/128, `programsDistinct`; oracle LIVE n=24, paused control DEAD; zone `pending→armed moduleReady`; `glreplay-carried` binds elId 1 (big instance) with Δ 0.012 px; 0 `preserve-refused`; `glreplay-hold` present; 2 pooled, 0 in document at settle |
| 4 hand-back + Q0b (n=2) | PASS ×2 | max\|Δ\| outside movie ∪ slot 4 = 0 at settled 2 / P2c / P3 / P4; `release {mode: handoff, retired: [2]}`; only `remount-into-authored-layer`, at (105.12, 790.85, 960, 276) == toScreen(slotRects[3]); one painting `<video>` (elId 1) at P3/P4, t 9.31→10.57; counter burst deltas 3–10 (sums 61 and 64); tail: elId 1 the only painting movie at #3/#4/#5, gone at #7 |
| 4b letterboxed 1600×1000 | PASS | stage s 0.8333, oy 50; hand-off at (87.60, 709.04, 800, 230) == toScreen; parity 0 at all 4 points; burst deltas 2–10 |
| 6 fail-closed | **FAIL 2/20** | 18 PASS. All 17 other forced reasons go `armed→retired failure/<r>` on #1 with no `glreplay-live`; `planUnreadable`/`glReplayUnavailable` go `pending→retired moduleRetired`. `canvasRemoved` goes `notLive`. Each equals the control at P2c/P3/P4 (counter None, 0 painting, movie1 pool empty, parity 0, 0 `remount-*` through P4). `writebackFailed` hands off and equals armed. **Red: `sceneMismatch`, `posterAmbiguous`** (below) |
| 6 late-forced | PASS 3/3 | `contextLost`/`frameLengthChanged`/`glError` set at #2 while LIVE ⇒ `failure/<r>` on #2 and == control at P3/P4. Late `canvasRemoved` (report-only) ⇒ `released handoff`, retired [2] |
| 7 go-to | PASS | goTo 2 and goTo 3: `armed→retired cleared` on #1 before any `glreplay-arm`, never released, no `glreplay-live`; parity == flag-off twin. goTo 3 settles at #7; G2 arms on 3→4 and stands down `assetUnbound` with `release` ⇒ `notArmed`; `bridge-3to4` at #8 with the slide-3 elId 3; no `retire-boundary` names it. Full-deck walk: `bridge-3to4` at #8 |
| Q3 soak | PASS | one continuous session, 20 × 1 min, `loseContext()` at minute 10 ⇒ `contextLost` (fromEvent), write-back skipped, `failure/contextLost` on #2, release retired [1, 2]; after build 1 == control (parity 0); heap 9.54–10.92 MB; 0 GL errors; dropped 0/1381; rVFC→rAF at end of media |

**Red (reproduced, interleaved with the control).** Forced `sceneMismatch` and `posterAmbiguous` stand down at ≈3.76 s, after the move and
before LIVE. They leave a FROZEN movie frame in the WebGL layer: counter 109/106 and 107/109 in r1 and the repeat, constant from P2 to P2c and
across the burst (0 px change inside the movie rect). The control shows the player's poster: counter None, and control vs control is
byte-equal. Max\|Δ\| inside the movie rect is 249 vs the control; outside it is 0; P3/P4 == control. This is not live, but it is not "equals the
control at P2c" either. It is G2 behaviour: the last per-clear upload stays in the texture. That behaviour is unchanged from r5 (108/112, K8).
Fixing it needs a module or ruling decision, not a G3 change.

**Observed, not gating (R3/A3).** At build 3 (#4) the player creates elId 3. Pin binds it as a facade for elId 1 (`reuse-decoder`); the
facade is excluded from "painting" because it has no media of its own. The footprint fallback then runs 6× after the hand-off, with 20
`remount-done` before scene 6. The carried `<video>` ends slide 2 at (105.1, 790.8, 951.5, 267.6), ≈4.2 px up-left of the authored instance.
This is the R3 pop, and it is present at both viewports.

**Instrument notes.** Superseded runs are kept in `r1/_superseded/`. `summarise_gates.py` first mixed `continuity.glReplay.sha256` into
the core-sha set, which gave a false G-P2 red; that is fixed. The window for "0 `remount-*` after stand-down" is bounded at P4: the slide-3
decoder's `remount-scheduled` at #7 occurs in the control too. Not measured: OBS/CEF, real-deck G2 on other exports.
