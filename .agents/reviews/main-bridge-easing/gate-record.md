# Bridge easing + player 17c0c938 — gate record (2026-10-10)

Branch `claude/main-bridge-easing` (off main `dd61e7c0`, origin/main #254 merged in at `104364ee`), final head `dcd5b9e4`.
Machine: M1 Pro (10 cores). Origin: the owner's real-OBS look (generalisation plan Q7) found two things.
(a) The 3→4 bridge "rubber band": our overlay moved the carried `<video>` linearly while Keynote's player eases the movie's
GL poster, so the poster showed past the overlay mid-move. (b) The current Keynote export's player `17c0c938` was refused.
Reviews (GPT-6 Astra, high): branch r1 REQUEST CHANGES (3 MAJOR) → r2 APPROVE (1 MINOR folded); fix A r1–r3 REQUEST
CHANGES (1 MAJOR, then 1 MAJOR + 1 MINOR, then 1 MINOR) → r4 APPROVE. Raw rounds beside this file; they go at merge.

**Verdict:** final round at `dcd5b9e4` DONE tier=full failed=0 pending=0; carry-cover green pass / red fail / null fail;
full suites green. r3 at `87f8c450` failed 3 checks; all three were triaged to the instruments, not the product (below).

## What changed
- **Eased bridge overlay (`8204b87a`).** `keepThroughBridge` progress goes through an exact cubic-bezier(.42,0,.58,1)
  evaluator (Newton with bisection fallback) on the same linear time base. Core `e9338aff…` → `06789fbd…`. New red core
  variant `linear-bridge` (`d98e75b7…`).
- **Bridge timing qualification (`6ee91fc5`).** A bridge qualifies only if every motion group and leaf of the carried
  movie on the single-child chain is EaseInEaseOut, offset 0, duration equal to the transition's; otherwise refused;
  branching chains fail closed. Trimmed P2 fixture gets slide 3's transition slots back (textures sanitised); every plan
  and runtime sha unchanged.
- **Player `17c0c938` (`981d6df7`, docs `34cc9bf3`).** It is `e9b2fad4` plus two `,isEvalSupported:!1` PDF.js options
  outside every anchor. `PLAYER_SHA256` → `SUPPORTED_PLAYERS` (stock sha → pinned `patch_player` on / off and
  `patch_rendering` output shas: `330ef72c` / `4f9fbffd` / `33fcdcd2` for `17c0c938`). Byte-level test on both real players.
- **Carry-cover gate (`41390ccd`, `5576f061`, `87f8c450`).** `--carry-cover`: headless screencast of the bridge carry
  with a rAF sampler; per mid-move frame, poster pixels outside the overlay (dilated 4 px) inside src∪dst + 120 px, other
  transition objects masked for their windows. PASS: ≥95% of frames expose ≤0.5% and no strip > 5 px. A probe-only
  96×4 px tick bar names each frame's rAF tick; each tick's overlay is read twice and disagreeing reads that decide the
  verdict make it INCONCLUSIVE. Coverage: no gap > 3 ticks (+half) across the whole window, ≤10% unplaceable, ≥20 fps.
  A path within strip tolerance of the bar is INCONCLUSIVE. `run_gates.sh` full tier: green must pass,
  `--core-variant linear-bridge` and `--carry-cover-null` must fail; inconclusive / error / stale = FAILED.
- **Fix A: freeze-trigger bounds follow the injected bridge (`d0b94981`, `abefdb2d`, `18bbc221`, `dcd5b9e4`).** The P2
  freeze bracket's `firedAtMoveStart` / `firedAtRuntimeMotionStart` bounds were calibrated on a linear bridge (1 px
  departure ≈ 4.8 ms after the marker); eased, it takes ≈ 61 ms on P2's 3→4. The bounds now shift by (L − 4.8 ms), L from
  the injected plan's geometry, the measured stage scale and the curve (linear for `linear-bridge`). The poll records each
  callback's page clock from keydown to trigger (`nullControl.pollTimes`, ≤ 256); the departure must be seen by the
  deadline frame (first recorded callback ≥ marker + L, plus one read-lag callback and the 2-callback slack), the
  displacement cap is the curve's at that deadline, a marker tied with the preceding poll's clock is admitted, a marker
  strictly before it fails closed; missing or malformed `pollTimes` is inconclusive. Stall ceilings, frame lead, hold
  evidence and every other check unchanged. Reports without `pollTimes` (all freeze-ab runs, both r3 runs) now read
  inconclusive on `firedAtRuntimeMotionStart`.
- Hall entry `98de4a80`.

## Gate commands
- Rounds: `GATE_JOBS=3 scripts/run_gates.sh <pinned gate worktree> <outdir>` (full tier; clean worktrees
  `gate-main-87f8c450`, `gate-main-dcd5b9e4`; fixture symlink to the main checkout's `output/p2-recovery`).
- Host probe on the owner's fresh export (`Minimal Alpha_DSK`, player `17c0c938`), 1920×1080, from `gate-main-87f8c450`:
  `scripts/live_host_probe.py --fixture $X --original-index $X/index.html --viewport 1920x1080`, once with Magic Move
  opacity on, once with `OBED_LIVE_MM_OPACITY=off` (`live_continuity_probe.py` needs a plan, and this deck derives none).
- Evidence (git-ignored), main checkout `output/evidence/main-bridge-easing/`: `r3/`, `triage-r3/`, `r3-rerun/`,
  `freeze-ab/`, `final-dcd5b9e4/` (`gates/`, `gates.log`, `ab-{E,L}-{fast,gl}/`, suite logs).

## r3 at `87f8c450`: failed=3 (load start 2.92 / end 7.98, wall 544 s)
| Check | Got | Cause | Disposition |
|---|---|---|---|
| CARRY-COVER `--carry-cover-null` | inconclusive (want fail) | a 67 ms mid-move stretch with no scored frame (bound 58 ms = 3 ticks at 16.7 ms) under round load | instrument working as designed (coverage hole ⇒ never a verdict); `r3-rerun/` 3/3 fail correctly on a quiet machine (54/54, 55/55, 52/52 frames exposed) |
| P2 fast | `freezeControlCaughtByCounter` inconclusive | `firedAtMoveStart` + `firedAtRuntimeMotionStart` only: trigger frame 10 (limit 9), Δ 4 (slack 2); identity checks and 39 other checks True | linear-calibrated bounds meeting the eased overlay (`triage-r3/freeze-bracket-easing.md`); fixed by fix A |
| P2 fast `--gl-replay auto` | same | same (trigger 10, Δ 4) | same |

Carry-cover green passed and linear red failed in r3 (63/72 frames, 54 px strip). Everything else matched.

**Freeze A/B (`freeze-ab/`, 12 interleaved runs, pre-fix-A scorer):** linear core 6/6 pass, Δ 1, marker→trigger
13.5–30.1 ms; eased core 5/6 inconclusive, Δ 4, marker→trigger 65–78 ms in all six. Same plan, player, source; only the
core differs. Offline under fix A: 92 linear-era reports pass unchanged; both r3 eased runs pass (before `pollTimes`
became required).

## Final at `dcd5b9e4`
| Gate | Expected | Result | Numbers |
|---|---|---|---|
| `run_gates.sh` full tier | all MATCH | **failed=0, pending=0** | 18 runs; wall 452 s (7m32s); load start 3.92 / end 11.88 |
| Host gates ×3 (2560, 1600, 1920 + attach, B, Voff) | PASS | PASS | scales 1.3333 / 0.8333 / 1.0; V 4/4 each |
| Host reds ×5 | registered sets | all MATCH | |
| P2 arms ×7 (fast, slow, gl-auto; 4 reds) | registered sets | all MATCH | 15/15 on positives |
| Carry-cover green | pass | **pass** | 72/72 frames placed, 0 undecided, clean share 1.0, max exposed 0.0, max strip 0 px, max gap 16.8 ms (allowed 58.45) |
| Carry-cover red `linear-bridge` | fail | **fail** | 63/72 frames > 0.5%, 55 px strip; core `d98e75b7…` |
| Carry-cover null | fail | **fail** | 51/51 frames > 0.5% |
| Freeze bracket (fast / gl-auto) | pass | pass | L 61.0 ms; marker frame 6, trigger frame 10, deadline frame 13; marker→trigger 68.4 / 73.6 ms |
| `pollTimes` live checks (`ab-{E,L}-{fast,gl}`) | pass | **4/4 pass** | eased `06789fbd` and linear `d98e75b7`, fast and gl; 7–10 recorded callbacks each |

**Restart clock and rAF vs the 2026-10-09 baseline** (`gates-speedup-2026-10-09/gate-record.md`; restart =
`deliberateRestart2to3.earliestSlide3Obs.t`, limit 0.35 s):

| | fast | gl-auto | slow | max rAF gap (fast / gl) |
|---|---|---|---|---|
| Baseline final `2bf11264` | 0.148 | 0.129 | 0.124 | — |
| Baseline qualification r1–r3 (all positive arms) | 0.106–0.222 | | | 33.8–35.1 ms |
| r3 `87f8c450` | 0.193 | 0.103 | 0.147 | 34.2 / 33.9 ms |
| **Final `dcd5b9e4`** | **0.168** | **0.119** | **0.150** | **34.3 / 33.3 ms** |

All inside the baseline qualification spread, at a higher end load (11.88). The sync bar exists only in the carry-cover
probe, so these P2 numbers clear the core change, not the bar. The bar's own cost shows in the carry-cover green run:
16.7 ms cadence, max gap 16.8 ms, nothing discarded. Astra r2's "zero timing perturbation" point is answered by that
cadence, not proven absent.

## Host probe, player `17c0c938` at 1920 (`r3/fresh-adapter-1920-{on,off}.json`)
- **Patching:** stock `17c0c938`; on → `330ef72c…`, off → `4f9fbffd…`, both the pinned shas (`_pinned` fails closed, so a
  pass proves the bytes served). Rendering pin `33fcdcd2` is byte-level only (the live host never serves `patch_rendering`);
  the export's `main.js` is byte-identical to the test fixture and the `test_live_runtime` player tests ran (none skipped).
- **Presenter:** both arms `status pass`, stage fitted, viewport 1920×1080, runtime v2 ready, navigation and `goTo 1` landed.
- **Continuity: declined** (`unsupported`): "ambiguous 'untitled.mov' ownership at player index 7 -> 8: 2 instance(s)
  before, 2 after, 4 geometry-equal pair(s)". The headless host runs without continuity.
- **Product gap (not this branch):** the dashboard refuses to start a deck that does not qualify, even with continuity
  off (`web/live.py` `_deck_qualification` → 409; pinned by `test_qualification_refusal_also_blocks_start_even_with_continuity_off`).
  So the owner's fresh deck still cannot go live from the dashboard; it is blocked only by the 7→8 ambiguity.

## Suites (final, `dcd5b9e4`)
- `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`: 9156 passed, 11 skipped, 2 xfailed
  (skips are local operator decks)
- Python 3.10 floor: <<pytest-310.log result>>
- `npm run test:ui`: 320 passed. `npm run test:maps`: 542 passed + 2 perf

## Reviews (GPT-6 Astra, high; findings classified)
- **Branch r1 — REQUEST CHANGES.** (1) *New class, MAJOR:* bridge qualification never checked the carried movie's
  timing → `6ee91fc5`. (2) *New class, MAJOR:* min-exposure alignment within ±17 ms hides a one-frame lag → `5576f061`
  (tick bar, two reads, delayed-overlay test). (3) *New class, MAJOR:* aggregate frame count hides coverage holes →
  `5576f061` (whole-window gap bound, discarded share, cadence floor).
- **Branch r2 — APPROVE.** r1 (1)–(3) *closed class*. (4) *Edge case, MINOR:* sync-bar blind spot → `87f8c450`.
- **Fix A r1 — REQUEST CHANGES.** (1) *New class, MAJOR:* slow early callbacks inflate the mean-cadence band and cap,
  passing an overlay 3 callbacks late → `abefdb2d`.
- **Fix A r2 — REQUEST CHANGES.** r1 (1) partially closed. (1) *Edge case, MAJOR:* slow post-trigger hold cadence
  re-widens the band → `18bbc221`. (2) *Edge case, MINOR:* cadence recovery makes a healthy loaded run inconclusive → `18bbc221`.
- **Fix A r3 — REQUEST CHANGES.** r2 (1), (2) *closed class*. (1) *Edge case, MINOR:* a marker tied with the preceding
  poll's coarsened clock is rejected → `dcd5b9e4`.
- **Fix A r4 — APPROVE.** r3 (1) *closed class*; equality adds no late-trigger allowance; no new defects.

### Review log
- Astra branch r1: REQUEST CHANGES, 3 MAJOR new classes (bridge timing unchecked; exposure-picked alignment; aggregate coverage) → `6ee91fc5`, `5576f061`.
- Astra branch r2: APPROVE; 3 classes closed; 1 MINOR edge case (sync-bar blind spot) → `87f8c450`.
- Astra fix A r1: REQUEST CHANGES, 1 MAJOR new class (startup callbacks widen the band) → `abefdb2d`.
- Astra fix A r2: REQUEST CHANGES, 1 MAJOR + 1 MINOR edge cases (hold cadence widens / narrows the band) → `18bbc221`.
- Astra fix A r3: REQUEST CHANGES, r2 closed; 1 MINOR edge case (timestamp tie) → `dcd5b9e4`.
- Astra fix A r4: APPROVE; no open findings.

## Open
- Carry-cover thresholds and masks are P2-calibrated (Astra branch r1); other decks need their own calibration.
- The carry-cover null control can read inconclusive under round load (r3: one 67 ms coverage hole). Correct by design,
  but it reddens a round; watch for a repeat before tuning anything.
- Composed ancestor/descendant motion is unsupported and fails closed; no export evidence yet (Astra branch r2).
- The D1 marker failure is out of scope (Astra branch r1).
- Dashboard start is refused for any unqualified deck even with continuity off (above); owner decision whether
  `continuity: off` should present it.
