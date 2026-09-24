# GL replay under managed OBS (OD-2) — gate record r1 (DRAFT, in progress)

Plan: `.agents/plans/keynote_live_gl_replay_managed_obs.plan.md` rev 2. Branch `claude/od-2-gl-replay-managed-obs-5bd03f`.
Harness: `scripts/managed_obs_qualify.py` (+ `scripts/obs_cadence_decode.py`). OBS 32.2.2, CEF 127, M1 Pro, P2 fixture,
G2 `10a5b36a…` v1 (JS bytes unchanged vs origin/main). Evidence (git-ignored): worktree `output/gl-replay-managed/{runs,shots,*.log}`.
Codec: `utvideo/yuv420p` lossless on every decoded take.

## Status 2026-09-24 23:10 (paused; resume 2026-09-25)

Final product code `b255c6b6`: managed default `auto` at output 25 only; external attach refused; env `off` wins; stage-gate
failure reports `unavailable`. Full suite at `b255c6b6`'s product diff: 7369 passed / 88 skipped / 1 xfailed.

| Gate | Result | Evidence (runs/, logs) |
|---|---|---|
| M0 alpha instrument | PASS every take (H α 0 outside marker; marker 255; H≠S; 1-px poke caught 255) | all g2 takes |
| M1 slide-2 LIVE cadence + in-page | 25 fps final code, n=4 (2 hidden, 2 shown), post-reboot: G2 0.8/2.1/1.3/0.9 % vs native 9.7/13.3/11.3/11.2 %; uploads 30/s, glErrors 0, pool true, frameLen 88, occluded 20/128, innerRect {4,4,952,268}. KB frozen caught (static 0, uploads 0). Null: paused 1.0, g2-off movie rect static 0 | `fin2-25-*`, `fin3-25-*`, `kb-frozen2.log` |
| M2 build-1 hand-back | PASS every good take: live ring 0, hand-back ring px>20 = 35 (vs DOM-path g2-off 2596), backward 0, handoff note, 1 painting video. KB oldbytes caught (live ring 244, hand-back 3637 px). Residual 35 px = player-texture vs DOM edge sharpening on the movie slot's black-box edge (visually seamless, crops `shots/g2-20260924-181954/g2-crops`) | `t3.log`, `kb-old.log` |
| M3 key/alpha | PASS: plateau α 75/75, G2 vs DOM 0; edge = round(native × 0.2947) ± 1 (KB unscaled 180); g2-off T α 255 (KB). Report: player-vs-DOM edge softness max 73 over 2640 px — pre-existing, G2 reproduces the player's own draw | all g2 takes |
| M4 hide/show while LIVE | PASS 25 fps final (reshow judged vs same-take native, owner 2026-09-24: 3.3/2.2/1.1/3.3 % vs 9.7–13.3 %); counter continuity 0–1; hidden-arm LIVE in 0 s. KB latelost caught (RETIRED contextLost) | `fin*`, `kb-latelost.log` |
| M5 fail-closed smoke | PASS (module, zone, goto2 → retired, 0 live, P3 == off exactly, no remounts; bogus KB caught). Weak clause: painting count 0 == 0 | `failsafe.log` |
| M6 soak (P2 fixture, owner option A) | PASS rescored after the fixture-path fix: engine ready 20 min, loseContext → contextLost stand-down, retired failure/contextLost, P3/P4 == off. Per-minute uploads 0 after the movie ends at 46 s (report-only on a non-looping fixture) | `soak.log`, `runs/soak-20260924-184639.json` |
| M7 owner eyeball | TODO | |
| M8 regression | pytest full DONE (7369/88/1); TODO `test:ui`, `test:maps`, `live_continuity_probe.py --gl-replay auto --viewport 1920x1080` (external attach must read `unavailable`) | |

## Findings

1. **Loop.** Keynote Loop exports `movie.loopMode: "looping"`; continuity refuses the deck (unknown encoding), so no carry and
   no G2 on any deck with a looping movie. Owner: option A (soak on the P2 fixture) + separate follow-up session (loop support).
2. **rAF latch (managed OBS / CEF).** Page rAF = the seeded 2× (50 / 60) on a blank page and on the player until a movie plays in
   the shown output; then it drops to 30 and stays there across sessions, navigation and pause until OBS relaunches (not sleep/wake,
   load or recording — probed after a reboot). The 2× oversampling from #226 is therefore lost in real use. At 25 fps G2 still
   passes; at 30 fps cadence is bimodal (the first 30 take after a 25 run: G2 17–25 % vs native 14–17 %; otherwise ~1 %).
   Owner 2026-09-24: OQ-2 contingency applied — managed default on at 25 only (`b255c6b6`); 30 revisits once the latch is fixed
   (managed-OBS follow-up; also proposed: a dashboard warning when page rAF < 2× output rate).
3. Load matters: a take under load (another session's Electron renderers, load 5–15) read noisier; record `uptime` per batch.

## Remaining (resume)

- Baseline `--arm both --rate 25`: take 1 DONE 23:10 (load ~9) PASS — native `2x` 10.8 %, `positive` (source = canvas) 27.1 %,
  positive > 2x; one more take for n=2 (`baseline.log`).
- Rate 30 diagnostic takes (explicit `auto`), report-only.
- Re-run failsafe + soak on the final code (harness changed after they ran; product default at 25 unchanged).
- M7 owner eyeball (shown, `--keep-recordings`), M8 rest, docs (plan §6), Codex (plan §7 brief + the rate/reshow changes), PR.
