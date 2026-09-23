# G5+G6 headless gates — PR-citable (2026-09-23, `d3fe55d9`)

Plan: `.agents/plans/keynote_live_gl_replay_g5g6.plan.md` rev 2 + amendments. Earlier rounds (r1 on `bfaeffae`, r2 probe-only on
`aa2fd851`) found the P2 `--disable-gpu`, early armed read, `loopMode`, unresolved-owner and P2 harness issues now fixed; their
evidence stays in the main checkout's git-ignored `output/gates-g5g6/{g0,r1,r2}/`.

## Provenance
- **Commits.** P2 (off and auto) and P5 on `d3fe55d9`; host ×3 on `fc5e79b0` (host and probe code identical at `d3fe55d9`). Clean
  detached worktree, `uv sync --all-extras --all-groups`, fixture symlink to main-checkout `output/p2-recovery/html-adversarial`.
  G-0′ baseline `a56474f3` (`output/gates-g5g6/g0/`).
- **Shas.** Core v5 `e9338aff…` start == end; G2 `4f8850e0…`; player `main.js` `e9b2fad4…` == `PLAYER_SHA256`, served patched
  `7cf00b56…`; fixture `index.html` `5908d479…`, `preserve-inject.json` `53cf8339…`, `continuity-plan-inject.json` `91a29d5e…`
  unchanged; product files (`live_continuity.py`, `live_runtime.py`, `live_continuity_js.py`, `live_gl_replay_js.py`,
  `live_host.py`) == G-0′.
- **Env.** `OBED_LIVE_GL_REPLAY` unset. Flag-off runner = `scripts/run_gates.sh` split into ≤10-min phases; a P2 `report.json` is
  copied only from a fresh successful run.
- **Known-bad splices (observation only).** A wrapper removes the `data-obed-p2-gl-replay` or `data-obed-p2-gl-info` tag after
  injection, or seeds `debugForceFail:'posterAmbiguous'`. Product code untouched.
- **Browser discipline.** One headless Chrome at a time, `pgrep` before each batch, uptime per batch (load 5–55 from other
  sessions); no CDP-timeout runs this round. No Keynote.

## Results

| Gate | Verdict | Numbers |
|---|---|---|
| G-OFF host ×3 (blocking) | PASS | Verdict summary byte-identical to G-0′; key sets equal at 2560×1440, 1600×1000, 1920×1080 |
| G-OFF P2 off (blocking; the harness fix changes the off path on purpose) | PASS | Fast and slow: success, 14 True. `--disable-bridge34`: False only on `continueThroughMovingMagicMove3to4` (== G-0′). Finding ids/verdicts and key sets == G-0′. Freeze control pass (fast, slow). `collector.flipVia` = `motion` (fast, slow), `hash` (no-bridge) |
| G6-0 A6 | PASS | Unpatched fixture `main.js` == `PLAYER_SHA256`; `patch_player` verifies one anchor; auto serves the recorded patched digest |
| G6-0 A7 | PASS | 16/16 `sampleFrame`/screenshot counter pairs \|Δ\| ≤ 2 (typically −1). Known-bad: pairing with the previous read gives \|Δ\| = 14 (12/12). ROI margin +4 px x / +3 px y still decodes; beyond that None, never a wrong index |
| P5-0 | Poke off | Unpoked Vgl screenshot oracle reads slide 2 LIVE (n=2; poked identical) |
| P5-A, 3 viewports + 2 reps at 2560×1440 | PASS | 5/5 pass. `armed1to2` True in A and C 10/10. Attach `unavailable` + `refused1to2`; B `refused1to2`; V/Voff all slides; Vgl armed slide 6/6 checks, mask 20/128 |
| P5-A known-bads / controls | RED / 0 | Vgl vs `facts_off` RED 5/5; V as armed slide RED 5/5; r3 forced shape RED; Vgl vs own facts 0 reasons; two Vgl runs identical |
| P5-H (3 viewports) | PASS | Parity maxOutside 0; carry 4/4. V as Vgl RED (carry 0/4); 1-px poke outside mask RED; undilated mask not RED on the real pair (no edge difference) — synthetic ring pixel RED undilated / GREEN dilated; V vs V and Vgl vs Vgl 0 px |
| P5-F (2560) | PASS | `planUnreadable`, `rvfcUnavailable`, `posterAmbiguous`, `occlusionTooHigh` `forced-ok`; unknown reason ⇒ `forced-fail` |
| P5-7 (r1, `bfaeffae`) | PASS | goTo 3 → goTo 1 → advance 2: no `glreplay-live`, zone `armed→retired cleared`, slide-2 shot == flag-off twin |
| P5-L | Recorded | `mutationScanMs` 0; hand-off `completedMs` 2.8–3.6 ms |
| G6-P2 auto fast ×2 / slow / no-bridge | PASS | `glReplayCarry1to2` True (a–h) on all four; no-bridge False only on 3→4. Carried elId 1, `#1→#2`, composite counter 13–14 decoded and progressing, `sampleFrame` +15 per read, clock rate 0.99996–1.00002. A8: natural reuse-skip/retire pair fires, `preserveDidNotBlockRestart` True |
| G6-P2 known-bads / controls | RED / agree | GL tag removed ⇒ boot-check exit; INFO tag removed ⇒ boot-check exit; `posterAmbiguous` seed ⇒ False (b,c,d,f,g,h); off report scored by `glReplayCarry1to2` ⇒ False (offline); fast vs fast-rep2 identical |
