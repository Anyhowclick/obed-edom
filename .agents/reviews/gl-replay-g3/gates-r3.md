# G3+G4 headless gates — round 3, PR-citable (2026-09-23, branch `a9637d62`)

## Provenance

- **Commit.** `a9637d62` (`feat/gl-replay-g3g4`). It includes the core Codex round-1 fixes `a4039ba8` and the G2 fixes `fb6fa2bf`/`a9637d62`. Gates ran from a clean detached worktree `.claude/worktrees/gates-g3-a9637d62` (dirty = 0). That worktree had `uv sync --all-extras --all-groups` and a symlink to the fixture `output/p2-recovery/html-adversarial` (main checkout).
- **Shas.**
  - Continuity core v5 `e9338aff1cbe0aee74e8e1ac94412a0ffb19f787962961d9ff8ed550ebd01fa4` (== `PINNED_CORE_SHA256`).
  - G2 module `4f8850e05177d12051eadd37f84e091938b46e8fd0e2b7ecf03e7637bed6351e` (== `PINNED_JS_SHA256`).
  - G-0 baseline: `9ad4fc69`, core `68262ab8…` (`output/gates-g3/g0/`).
- **Injection.** Armed arms use the product path `LiveOutputHost(..., gl_replay="auto")`, asserted per arm (`injection.inject == product`). `output.continuity.glReplay = {mode: injected, version: 1, sha256: 4f8850e0…}`. The control uses the host default.
- **Observation-only splices.** An order probe goes after `<script id="obed-gl-replay">`. For `fail:<r>` arms, a `debugForceFail` seed goes immediately before that tag. Late arms are set by CDP at P2c on `#2`. Late `contextLost` is a real `WEBGL_lose_context.loseContext()`.
- **Harness and results.** Harness `output/live-visible-content/g3/{common,g3_flow,analyse_g3,validate_r2_instruments}.py`, `run_arms.sh`, and `output/gates-g3/{run_gates_g3.sh,summarise_gates.py}`. Results in `output/live-visible-content/g3/r3/<arm>/result.json`, `r3/gates.json`, `r3/r2-instrument-validation.json` and `output/gates-g3/gp2-a9637d62/` (`summary.json`, `gp2-verdict.json`).
- **Pass conditions.** Plan rev 2 §6, the coordinator rulings (recorded as `specNote`s), and the A2 / G2-fix checks of `a2-advice.md` (pruned; `git show a56474f3:.agents/reviews/gl-replay-g3/a2-advice.md`).
- **Browser discipline.** At most 3 headless Chromes. `run_gates`, the go-to arms and Q3 each ran alone. `pgrep -f headless=new` was empty before every batch. No Keynote, no OBS, no port 9222.

| Batch (1920×1080 unless noted) | Start | Duration | Load before → after |
|---|---|---|---|
| G-P2 host ×3 (2560×1440, 1600×1000, 1920×1080) | 12:19:30 | 404 s | 2.37 → 3.92 |
| G-P2 P2 fast / no-bridge / slow | 12:26:19 / 12:29:38 / 12:31:41 | 199 / 116 / 205 s | 3.69 → 8.39 / 8.39 → 13.55 / 11.99 → 10.80 |
| control, armed, control-lb, armed-lb, 4 late arms (3 lanes) | 12:35:12 | 75 s | 10.58 → 9.50 |
| control-2, armed-2 (1 lane) | 12:36:27 | 48 s | 9.50 → 7.32 |
| 20 `fail:` arms (3 lanes) | 12:37:29 | 173 s | 6.55 → 4.61 |
| go-to ×4 (alone) | 12:40:29 | 41 s | 4.24 → 3.99 |
| Q3 (alone, one continuous call) | 12:41:38 | 1224 s | 3.12 → 4.26 |

## Results

| Gate | r3 verdict | r3 numbers | r2 → r3 delta |
|---|---|---|---|
| G-P2 (blocking) | PASS | Host ×3 verdicts == G-0 (default path `glReplay.mode off`). P2 fast: success True, 14 True, no False. Fast + `--disable-bridge34`: success False (== G-0 by design), 13 True, False `continueThroughMovingMagicMove3to4`. Slow: True, 14, no False. `refusedCarry1to2.ok` with `glReplayFallback: moduleAbsent` in all 3. Printed sha e9338aff… == pinned == served at start and end | core 359c589a… → e9338aff…, G2 3f089a1a… → 4f8850e0…; verdicts unchanged |
| 1 install order | PASS | 245 wrapped at install, `getContext` wrapped, main.js unseen; served order plan < core < `obed-gl-replay` < fit < `#stage` < main.js; control has no tag | unchanged |
| 2 full 1→2 | PASS | arm then live; settleGapMs 100.2, settleToHashMs 97.8; frameLen 88, 0 GL errors, occluded 20/128, `programsDistinct`, `opacityUnproven []`; oracle LIVE n=24, paused control DEAD; zone `pending→armed moduleReady`; carried elId 1 (big instance) with Δ 0.012 px; 0 `preserve-refused`; hold present; 2 pooled, 0 in the document. posterSnapshotMs 3.5 (report-only) | settle 100.0/104.4 → 100.2/97.8; posterSnapshotMs 3.8 → 3.5 |
| 4 hand-back + Q0b (n=2) | PASS ×2 | Hand-off `remount-into-authored-layer` at (109.35, 795.04, 951.54, 267.62) == toScreen(instanceRect). T-geom max edge Δ 0.012 px at P3/P4/T4/T5. T-ring 0/0 at P3/P4/T4/T5 (6737 px). **T-topz (facade now gated): 0 `remount-done` and 0 `remount-footprint-rect` for elId 1 and its facade elId 3.** T-transition: both out of the document at +0.3/+1.2 s on #5, 0 painting movie. Parity outside movie ∪ slot 4 = 0 at settled 2/P2c/P3/P4; release retired [2]; one painting `<video>`; counter burst OK; tail OK | **the r2 facade `remount-footprint-rect` in the 2→3 window is gone** (1 → 0); guard G still holds once (`glreplay-hold {via: stage}` at #5) |
| 4b letterboxed 1600×1000 | PASS | hand-off (91.13, 712.53, 792.95, 223.02) == toScreen at s 0.8333, oy 50; T-geom 0.010 px; ring 0; T-topz 0 (facade gated); T-transition OK | facade note 1 → 0 |
| 6 fail-closed | PASS 20/20 | 17 forced reasons `armed→retired failure/<r>` on #1 with no live. `planUnreadable`/`glReplayUnavailable` `moduleRetired`; `canvasRemoved` `notLive`. The 19 retire arms each equal the control at P2c/P3/P4: inside-movie parity 0, outside parity 0, counter None, 0 painting, movie1 pool empty, 0 `remount-*` through P4. `writebackFailed` hands off and == armed | unchanged (all 0 inside the rect) |
| 6 late-forced | PASS 3/3 | late `frameLengthChanged`/`glError` P2d inside parity 0; late `contextLost` (real loss) `failure/contextLost` on #2 and == control at P3/P4, P2d 255/1.0 report-only by ruling. Late `canvasRemoved` (report-only): `released handoff`, retired [2] | unchanged |
| 7 go-to | PASS | goTo 2 and goTo 3 ⇒ `armed→retired cleared` on #1 before any `glreplay-arm`, never released, no live, parity == flag-off twin. goTo 3 settles at #7; G2 arms on 3→4 and stands down with `release` ⇒ `notArmed`; `bridge-3to4` at #8 with the slide-3 elId; no `retire-boundary` names it. Full walk: `bridge-3to4` at #8 | unchanged |
| Q3 soak | PASS | one continuous 20 × 1 min session; `loseContext()` at minute 10 ⇒ `contextLost` (fromEvent), write-back skipped, `failure/contextLost`, retired [1, 2]; after build 1 == control, inside and outside; heap 9.55–10.87 MB; 0 GL errors; dropped 0/1381; rVFC→rAF at end of media | heap 9.61–10.84 → 9.55–10.87 MB |

## `posterRestored` per stand-down (report-only)

- **True (the arm uploaded):** `canvasRemoved`, `frameLengthChanged`, `glError`, `occlusionTooHigh`, `posterAmbiguous`, `sceneMismatch` (90 uploads each), `writebackFailed` (201), late `frameLengthChanged`/`glError` (181–182), late `canvasRemoved` (180).
- **Null (no upload):** `planUnreadable`, `glReplayUnavailable`, `runtimeSeamAbsent`, `settleSignalAbsent`, `observerNotArmed`, `canvasShape`, `frameNotDelimited`, `rvfcUnavailable`, `videoNotReady`, `assetUnbound`, `unflaggedPlayerCall`.
- **Deviations from "true iff uploaded"**, none of them gating:
  - Forced `contextLost` (91 uploads) and late real `contextLost` (182) report **null**. This follows "restore needs a live context". The forced arm still reads inside-movie parity 0 vs the control at P2c.
  - `posterUnreadable` (0 uploads; it stands down at the first clear) reports **true**, because the snapshot is taken (posterSnapshotMs 2.9) and written back.

## Instrument validation and report-only measurements

- **Instrument validation** (`validate_r2_instruments.py`; r1 = negative control, r3 = this run):
  - Ring on r1 armed/armed-2: 250–252 max, 720–1240 px over 8. On r3: 0.
  - Inside-movie parity: 248–249 at 0.79 on the 10 r1 red arms; 0 on every r3 retire arm. `writebackFailed` differs (249) because it hands off, by design.
  - Control-2 vs control: 0 for both instruments.
  - T-transition sampled at #5 in every gate-4/4b arm and its control.
- **Build-1 move** (burst B00–B09 PNGs, row 930 / column 300):
  - While LIVE, the edge is at 105/791 with no white frame. From the first post-hand-off shot (hash still #2) it is at 106/792, with 3–4 frame pixels visible (control 4).
  - The ring at P3 == control.
  - One pre-hand-off armed shot reads x117 because of dark video content at the sampled row; this is a limit of the edge probe.

## Not measured

- OBS/CEF (OD-2 keeps `auto` unavailable in attach mode).
- Any export other than the adversarial fixture.
- The build-1 move at frame resolution.
