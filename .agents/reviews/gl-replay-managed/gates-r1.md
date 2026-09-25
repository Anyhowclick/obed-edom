# GL replay under managed OBS (OD-2) — gate record r1

Plan: `.agents/plans/keynote_live_gl_replay_managed_obs.plan.md` rev 2 (+ owner decisions below). Branch
`claude/od-2-gl-replay-managed-obs-5bd03f`. Harness `scripts/managed_obs_qualify.py`, decoder `scripts/obs_cadence_decode.py`,
fixture generator `scripts/binary_counter_movie.py`. OBS 32.2.2 (CEF 127), M1 Pro. G2 `10a5b36a…` v1 and core JS unchanged vs
origin/main. Recordings `utvideo/yuv420p` (lossless codec, 4:2:0). Evidence (git-ignored): worktree `output/gl-replay-managed/`
(`runs/`, `shots/`, `Q-*.log`, `Qkb-*.log`).

**Fixture of record: binary counter** — main checkout `output/p2-binary/` (P2 fixture copy, `Untitled.mov` replaced by a black/white
12-bit frame-index strip + parity + markers, printed digits, P2 grating; movie sha `947f8944…`, `fixture.json` `3a50059f…`; armed
facts identical to P2, no allowlist splice). Every frame of the movie decodes to its index offline (1381/1381).

## Owner decisions this round

- 2026-09-24: managed-OBS only; default on in Keyer; env `off` opts out; HDMI opt-in; OQ-1 ship even without screenshot alpha;
  OQ-2 rate 30 judged relative to native (absolute bound report-only); OQ-3 soak option A (P2 fixture; loop support = follow-up);
  OQ-4 stage-gate report fixed; reshow judged vs native; reviewer = Opus (Codex limit).
- 2026-09-25: binary counter fixture; managed default back to `auto` at every output rate (the 30-fps contingency rested on grey
  artefacts); limits recalibrated for binary; rAF keep-alive fix parked.

## Results on the final code (binary fixture, 2026-09-25)

| Gate | Result | Evidence |
|---|---|---|
| M0 alpha instrument | PASS every take; CvC H vs H 0 across takes | all `Q-*` |
| M1 cadence + in-page LIVE | 25 hidden ×2, 25 shown ×2: G2 slide-2 repeat 0/0/0/0.4 %, native 0 %, 24.9 distinct/s; 30 ×2: G2 1.8 % / 0 % vs native 0.9 % / 0 % (relative PASS; the absolute 1 % is report-only at 30 per OQ-2), 29.4–29.9/s. In page: uploads 30/s, glErrors 0, pool, frameLen 88, occluded 20/128, innerRect {4,4,952,268}. KB frozen caught (static 0, uploads 0). Null: paused 1.0, g2-off movie static 0 | `Q-25h`, `Q-25s`, `Q-30`, `Qkb-frozen` |
| M2 hand-back | every take: max forward step 2 (= live and native); re-scored after Opus r2 (steps bridge undecodable frames): max step per elapsed frame 1–2, every hand-back frame decodable, build 1 0.505–0.514 s after the marker; backward 0, live ring 0, hand-back ring px>20 = 35 (DOM path 2596), handoff note, 1 painting video. KB oldbytes caught (live ring 238, hand-back ring 4132 px) | `Q-*`, `Qkb-oldbytes` |
| M3 key/alpha | PASS: plateau α 75, G2 vs DOM 0; edge = native × 0.2947 ± 1 (KB 180); M0 poke vs g2-off-S caught; τ_O CvC 0 | all |
| M4 hide/show | PASS: reshow repeat 0 % at 25 (2.7 % at 30 take 1, native-relative PASS); drift 1; hidden-arm LIVE 0 s. KB latelost caught | `Q-*`, `Qkb-latelost` |
| M5 fail-closed smoke | PASS (module, zone, goto2; bogus KB caught on the zone-reason check) | `Q-failsafe` |
| M6 soak (binary P2, non-looping) | 5 min (new default) PASS: engine ready, wrap windows [1, 2] recorded (report-only: the P2 movie does not loop, so this soak proves engine health, context-loss stand-down and P3/P4 parity; per-minute LIVE and wrap checks are gated only on a looping fixture), loseContext → contextLost stand-down, retired failure/contextLost, P3/P4 == off. The earlier 20-min run failed only "engine ready": the managed engine raised a FALSE `obsExited` in minute 1 (OBS alive to 10:32, page answered CDP throughout) under load — managed-OBS (#226) liveness bug, separate follow-up; all G2 clauses passed | `Q-soak5.log`, `Q-soak.log` |
| M7 owner eyeball | Owner 2026-09-25 (recording `g2-20260925-104512`, movie area, on vs off): slide-2 movie keeps playing under the square (off: poster + solid square), hide/show clean, build-1 hand-back seamless. **Known limit found:** the square should be translucent throughout (as in Keynote); GL replay ON draws it solid during the move and ~1 s after settle until G2 goes LIVE (off: solid until build 1) — player opacity defect, follow-up. Windowed projector / Show OBS did not show a window (tray-minimised OBS) — recordings used instead | `M7-25p.log`, `od2_eyeball_25fps_movie_area.mp4` (session scratch) |
| M8 regression | full pytest 7410/88/1 at `812fd9d5`'s code; dashboard build OK, `test:ui` 305, `test:maps` 542 + 2; `live_continuity_probe.py --gl-replay auto --viewport 1920x1080 --attach` PASS (external attach → `unavailable` "attach output not qualified") | |

Native baseline (`--arm both`, binary): 2× source native 0 % repeats; positive control (source = canvas 25) 12.7 % / 6.3 % ⇒ the #226
2× setting is real and needed; binary limits: 2× ≤ 1 %, positive ≥ 5 %.

## Findings

1. **Grey counters misread across paths.** Chromium draws a native `<video>` through a tone curve that `drawImage`/`texImage2D`
   (so the G2 canvas) do not get: up to +11/255 in the midtones, 0 at pure black/white; OBS and headless Chrome identical
   (peer B seek sweep). Grey-coded counters therefore misread by ~9 frames between the two paths and inflated repeats. Earlier
   grey-counter figures in this round (native 10–13 %, "30 bimodal", a 9–13-frame "hand-back skip") are artefacts; the binary
   fixture replaces them. Real residual: a small midtone brightness step at G2 takeover and hand-back (owner eyeball; a G2 LUT is
   a possible follow-up).
2. **Page rAF latch.** Showing the output while a movie plays and nothing else changes per frame drops page rAF to the movie's
   30 fps until OBS relaunches (Chromium throttling, inferred; real show path; a 2×2 px per-rAF repaint prevents it). With the
   binary counter the latch does not hurt cadence at 25; at 30 one of four takes showed 1–3 % repeats for native and G2 alike.
   Keep-alive fix parked (owner).
3. **Loop.** Keynote Loop exports `movie.loopMode: "looping"`; continuity refuses such decks (no carry, no G2). Follow-up session
   in progress.
4. **Managed-engine false exit.** One sample of the engine's process check read "gone" while OBS ran; `_on_exit` forgets the process for good and raises the BLOCK `obsExited`. Intermittent (1 in ~40 launches, under load). Show risk (operator told to restart a healthy output) ⇒ follow-up session.
5. Load matters (another session's renderers, full-suite runs); `uptime` recorded per batch in the logs.

## Review

Opus r1 (`opus-r1.md`): items 1 (hand-back jump — resolved as a grey artefact, now gated by `maxForwardStep ≤ 3` on the binary
counter), 2 (hand-back 0.5 s after its marker), 3, 7, 8, 9, 10 folded; 4 (oldbytes re-run on HEAD: caught; no hand-back-only KB —
the binary forward-step gate has only the synthetic decoder KB), 5 (reshow bound now absolute 2 % at 25 + native-relative),
6 (frozen KB targets the static check), 11 (cross-take controls via `--takes 2`), 12 (nits) noted.
Opus r2: hand-back steps now bridge undecodable frames (`maxStepPerFrame` ≤ 3, every hand-back frame decodable on binary,
build-1 lead ≥ 0.3 s); fail-zone requires retired failure/posterAmbiguous (no fallback); M0 poke must exceed the unpoked O
delta; 2× vs positive enforced at both rates on binary; fixture movie sha256s verified at startup; fixture builder refuses a
foreign non-empty dest; `--soak-minutes` ≥ 4. The nine binary g2 takes of 2026-09-25 09:21–09:56 re-scored offline (one
re-decoded from its kept recording, the rest from stored hand-back counters): M0–M4 PASS on every take.
