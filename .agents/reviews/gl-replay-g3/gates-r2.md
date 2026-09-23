# G3+G4 headless gates — round 2 (2026-09-23, branch `ce21e359`, core v5 sha 359c589a…, G2 module 3f089a1a…, product flag `gl_replay="auto"`)

Results: `output/live-visible-content/g3/r2/<arm>/result.json`, `r2/gates.json`, and `r2/r2-instrument-validation.json`. The analyser is
`g3/analyse_g3.py`: plan rev 2 §6, the coordinator rulings, and the A2/G2-fix checks from `a2-advice.md` (pruned; `git show a56474f3:.agents/reviews/gl-replay-g3/a2-advice.md`). G-P2 is in
`output/gates-g3/gp2-ce21e359/`. Pinned detached worktree: `gates-g3-ce21e359` (clean); `gates-g3-2884e116` has been removed.
Every armed arm asserts `inject == product`. Lanes: at most 3 Chromes; `run_gates`, the go-to arms and Q3 each ran alone (Q3 as one 1227 s
call). Load was 11–28, except during the fail-arm batch (up to 93 at its end, from a concurrent `pytest -n auto`) and the go-to batch (≈50).
All of those arms passed, so none needed a re-run.

| Gate | r2 verdict | r2 numbers | r1 → r2 delta |
|---|---|---|---|
| G-P2 (blocking) | PASS | host ×3 == G-0 (`glReplay` mode off on the default path); P2 fast 14 True / —, no-bridge success False with 13 True / `continueThroughMovingMagicMove3to4`, slow 14 / —; `refusedCarry1to2.ok` with `moduleAbsent` ×3; printed sha 359c589a… == `PINNED_CORE_SHA256` == served, consistent | sha 914464e4… → 359c589a…; verdicts unchanged |
| 1 install order | PASS | 245 wrapped, `getContext` wrapped, main.js unseen, served order correct; `glReplay {injected, v1, 3f089a1a…}` | G2 sha 985afeb1… → 3f089a1a… |
| 2 full 1→2 | PASS | arm then live; settleGapMs 100.0, settleToHashMs 104.4; frameLen 88, 0 GL errors, 20/128, `programsDistinct`, `opacityUnproven []`; oracle LIVE n=24, paused DEAD; carried elId 1, Δ 0.012 px; 2 pooled, 0 in the document. **posterSnapshotMs 3.8** (new, report-only) | settle 99.7/100.2 → 100.0/104.4 |
| 4 hand-back + Q0b (n=2) | PASS ×2 | hand-off `remount-into-authored-layer` at (109.35, 795.04, 951.54, 267.62) == toScreen(instanceRect). **T-geom** max edge Δ 0.012 px at P3/P4/T4/T5. **T-ring** 0/0 at P3/P4/T4/T5. **T-topz** 0. **T-transition**: memo and facade out of the document at +0.3 s and +1.2 s (hash #5), 0 painting movie. Parity outside movie ∪ slot 4 = 0; release retired [2]; one painting `<video>`; burst OK; tail OK | hand-off at the slot (105.12, 790.85, 960, 276) → at the instance. Ring 720–1240 px → 0. 26 remount-done/footprint notes → 0. The 2→3 top-z append is gone (`glreplay-hold {via: stage}`) |
| 4b letterboxed 1600×1000 | PASS | hand-off (91.13, 712.53, 792.95, 223.02) == toScreen; T-geom 0.010 px; ring 0 (4351 px mask); T-topz 0; T-transition OK | slot → instance, as at 1920 |
| 6 fail-closed | PASS 20/20 | 17 forced reasons `failure/<r>` on #1 with no live; `planUnreadable` and `glReplayUnavailable` `moduleRetired`; `canvasRemoved` `notLive`. **Inside-movie parity vs control = 0 at P2c/P3/P4 on all 19** (max ≤ 2 required); outside parity 0; counter None; 0 painting; movie1 pool empty; 0 `remount-*` through P4. `writebackFailed` hands off and == armed | **10 red arms → 0**: the six crop arms, `sceneMismatch` and `posterAmbiguous` read 248–249 inside the rect at 0.79 of pixels in r1; all read 0 now |
| 6 late-forced | PASS 3/3 | late `frameLengthChanged`/`glError` P2d inside parity 0 (r1: 249). Late `contextLost` is a REAL `WEBGL_lose_context.loseContext()`: `failure/contextLost` on #2 and == control at P3/P4; its P2d inside parity is 255/1.0 (report-only by ruling: the context is gone). Late `canvasRemoved` (report-only) ⇒ `released handoff`, retired [2] | late fLC/glError 249 → 0; late contextLost forced → real loss |
| 7 go-to | PASS | goTo 2 and goTo 3 ⇒ `armed→retired cleared` on #1 before any `glreplay-arm`, never released, no live, parity == flag-off twin. goTo 3 settles at #7; G2 arms on 3→4 and stands down with `release` ⇒ `notArmed`; `bridge-3to4` at #8 with the slide-3 elId; no `retire-boundary` names it. Full walk: `bridge-3to4` at #8 | unchanged |
| Q3 soak | PASS | 20 × 1 min continuous; `loseContext()` at minute 10 ⇒ `contextLost` (fromEvent), write-back skipped, `failure/contextLost`, retired [1, 2]; after build 1 == control, inside and outside; heap 9.61–10.84 MB; 0 GL errors; dropped 0/1381; rVFC→rAF | heap 9.54–10.92 → 9.61–10.84 MB |

**Instrument validation.** The new checks FAIL on r1 and read 0 on control vs control.
- Ring (6737 px mask): r1 armed/armed-2 read 250–252 max and 720–1240 px over 8 at P3/P4/T4/T5; control-2 vs control reads 0/0.
- Inside-movie parity: 248–249 at 0.79 on the 10 r1 arms; 0 on the other 12 and on control-2 and control-rep.
- T-geom 8.457 px, T-topz 26 and the hand-off rect all fail on r1.
- T-transition could not be validated on r1 (no samples). In r2 every gate-4/4b arm and its control sampled at hash #5.

**Build-1 move (report-only, burst B00–B09 saved as PNG).**
- While LIVE, the GL movie content reaches the slot edge (left x105 at row 930, top y791 at column 300), with 0 white frame pixels.
- From the first post-hand-off shot (B04 in armed, while the hash is still #2), the outer edge is at 106/792 and 2–4 white frame pixels show at the left and top. The control has 4.
- At P3 the ring equals the control (0). This matches the advisor's prediction: the video settles into its authored frame and the frame's outer band reappears.
- Three armed-2 pre-hand-off shots read x117 / no top edge because of dark video content at the sampled row and column. That is a limit of the edge probe; the ring check is the gating one.

**Ruling applied / notes.**
- **T-topz scope.** Gating counts `remount-done` for the carried elId and its facades, and `remount-footprint-rect` for the carried elId (coordinator wording).
- **Facade note (report-only).** Each armed run shows ONE `remount-footprint-rect` for facade elId 3 in the 2→3 transition window (#5). It is immediately followed (within 0.1 ms) by `glreplay-hold {via: stage}`, with no `remount-done` and no append. Guard G fired as designed. The footprint computation runs before G.
- **Not measured:** OBS/CEF; any export other than the fixture.
