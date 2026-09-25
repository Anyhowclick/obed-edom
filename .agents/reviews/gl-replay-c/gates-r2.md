# GL-replay option (c) headless gates r2 (2026-09-23/24; phase 1 `9989e8bf`, phase 2 `bef57a23`)

Plan: `git show ed7ff63c:.agents/plans/keynote_live_gl_replay_c.plan.md` rev 1, §8. This round supersedes r1 (pruned after merge; git history of #218), which stopped at
gate 2 because the core refused G2 v2 (`moduleVersion`). The owner chose v1 (`9989e8bf`). Phase 1 ran on 2026-09-23 up to
the 23:25 cut-off and was finished on 2026-09-24. Phase 2 ran on `bef57a23` (Codex r1 P2 hardening; P2 files and tests only).

**Verdict:** every gate and new check PASSes. A7 (re-run) PASSes at the **owner-widened limit |Δ| ≤ 3** (2026-09-24): 16/16 within ±3 (12/16 within ±2), because the probe read sits between `sampleFrame` and the screenshot (details below). Q3 PASS. All `analyse_g3` gates for the r2 root (1, 2, 4, 4b, 6, 7, Q3) read PASS on one commit.


## Provenance
- **Phase 1.** Clean detached worktree `.claude/worktrees/gates-glc-r2` at `9989e8bf`.
- **Phase 2.** Fresh clean detached worktree `.claude/worktrees/gates-glc-p2` at `bef57a23`.
- **Setup (both).** `uv sync --all-extras --all-groups` and a fixture symlink to main-checkout `output/p2-recovery/html-adversarial`.
  Neither worktree was dirty at start or end.
- **Shas (start == end in both).** G2 `10a5b36a…` v1 (host reports `injected` v1 `10a5b36a…`). Core `e9338aff…`, unchanged.
  Fixture: `index.html` `5908d479…`, `preserve-inject.json` `53cf8339…` and `continuity-plan-inject.json` `91a29d5e…`.
  Evidence: `output/evidence/gates-glc/r2/shas-*.txt` and `output/evidence/gates-glc/r2/p2/shas-*.txt`.
- **KB splices** (harness only, `output/evidence/gl-replay-c-harness/splices/splice.py`, one asserted substitution each):
  - `oldbytes` = the `d56fb0dd` text, sha `4f8850e0…`;
  - `frozen` = the LIVE `perLiveUpload()` call removed. It re-applies on `bef57a23` with 1 substitution, sha `413a00ba…`;
  - the r1 `-v1diag` arm is obsolete, since the new G2 sha equals it.
- **Discipline.** ≤ 3 Chromes per batch. Go-to arms, host/G-OFF runs, each probe run, each P2 run and Q3 each ran alone.
  `uptime` is recorded in each `batches.txt` (load 3–80). `pgrep -f headless=new` was empty before every batch except
  r2 gate 6, where it showed one PID (37424) that had exited by the next check, almost certainly the preceding G-OFF
  Chrome shutting down. Gate 6 passed, so it was not re-run. No Keynote, no OBS.

## Phase 1 (`9989e8bf`)

| Gate | Verdict | Numbers |
|---|---|---|
| N1 KB (`armed-oldbytes`, 1920) | RED, right reason | Ring max 251/251/252 at P2/P2b/P2c, fracOver8 0.767 (== r3). Only other red: N2 (sibling). Every existing hand-off check green |
| N1 CvC (control-2 vs control) | 0 | max 0 at P2/P2b/P2c (n 6737 ring px) |
| N1 pass | PASS | armed, armed-2 (vs control) and armed-lb (vs control-lb): max 0 at all three points |
| N2 CvC | PASS ⇒ **gating** (OQ-5) | control, control-2 and control-lb: B00–B03 == own P2c (0), B04–B09 == own P3 (0) |
| N2 KB (`armed-oldbytes`) | RED, right reason | B00–B02 match neither (vs P2c ≈ 252, vs P3 255, fracOver8 0.77) |
| N2 pass | PASS | Every armed/armed-2/armed-lb B-shot ≤ 2 vs control P2c or P3 |
| Gate 1 install order | PASS | 245 wrapped at install, order plan < core < gl-replay < fit < #stage < main.js, host `injected` v1 |
| Gate 2 | PASS | frameLen 88, occluded 20/128, oracle LIVE n=24, paused DEAD, carried/pool, innerRect {4,4,952,268}. **Uploads 29.90 / 29.89 / 29.90 /s** vs old bytes 29.97/s (same batch) and r3 ≈ 30/s: no drop |
| G-OFF host ×3 (blocking) | PASS | Summary == G-0′ at all three viewports. Key sets == G-0′ at 2560 and 1920 (first run) and at 1600 (re-run, below) |
| G-OFF 1600 caveat | **Settled** | First run (load 45): arm C `continue3to4` took the "decoder sampled, all samples missing" path, still False. The quiet re-run (2026-09-24, load 25 → 59) reproduces G-0′'s "no decoder id spans the boundary" path, with summary and key sets byte-equal to G-0′. The first run was timing, not an off-path change |
| Gate 4 / 4b | PASS | All existing hand-off checks plus N1/N2, at 1920 (armed, armed-2) and 1600 letterbox |
| Gate 6 fail-closed | PASS | 20 forced + late `contextLost`/`frameLengthChanged`/`glError`, all PASS. Late `canvasRemoved` is report-only |
| Gate 7 go-to | PASS | goto2, goto3walk and fullDeckWalk |
| P5-7 | PASS | goTo 3 → goTo 1 → advance 2: zone `armed → retired (cleared)`, 0 `glreplay-live`, P7/P7b slide-2 shots byte-identical to the flag-off twin |
| P5-A ×3 viewports + 2 reps at 2560 (+ 1 rep each at 1600/1920) | PASS 7/7 | `armed1to2` A and C True, Vgl armed slide True, hand-back parity maxOutside 0 |
| **N3** | PASS | liveRing max 0 in all 7 runs (ring px: 2560 10251, 1600 2690, 1920 4740). Dilation 2 |
| N3 KB (Vgl-oldbytes, 2560) | RED, right reason | liveRing max 245, 10251/10251 px. Status `fail` with the single reason "live ring failed". Hand-back, `armed1to2` and armed slide all still green |
| N3 CvC | 0 at every viewport | V vs V and Vgl vs Vgl: 2560 (base/rep2/rep3 pairs), 1600 (base/rep2), 1920 (base/rep2), all max 0 |
| P5-A/H KBs and controls (offline `rescore_p5.py`) | RED / 0 | Vgl vs facts_off RED 7/7. V as armed slide RED 7/7. V-as-Vgl hand-back RED, 1-px poke RED, synthetic ring px RED undilated / GREEN dilated (7/7). Own facts 0. V/V and Vgl/Vgl hand-back 0 at each viewport. Two Vgl runs identical |
| P5-F (2560) | PASS | `planUnreadable`, `rvfcUnavailable`, `posterAmbiguous`, `occlusionTooHigh`: `forced-ok` (all 10 checks). KB `bogusReason` ⇒ `forced-fail` (slides, matchesV, refused, zone, noLive, knownReason False) |
| P5-L | Recorded | mutationScanMs 0–0.1. Hand-off completedMs 3.0–3.7 |

## Phase 2 (`bef57a23`)

| Gate | Verdict | Numbers |
|---|---|---|
| G-OFF P2 off fast / slow / no-bridge (blocking) | PASS | Fast and slow: success, 14 True. No-bridge: False only on `continueThroughMovingMagicMove3to4`. Finding (id, pass, status) == g5g6 r3 **and** G-0′ in all three. Report key sets (depth 4) == r3. Against G-0′ they differ only by the keys the g5g6 harness fix added on purpose (`freezeControl/collectors/*/flipVia`, `…/visibleCompetitors/pageHidden`). Freeze control `freezeControlCaughtByCounter` True in all three |
| G6-P2 auto fast ×2 / slow / no-bridge + **N5** | PASS | `glReplayCarry1to2` True (a–h) in all four; no-bridge `success` False only on 3→4. Carried elId 1, `#1→#2`, clock rate 0.99993–1.00008. **GL probe series 4/4 decoded and progressing** (fast [13,29,45,62], rep2 [15,30,47,62], slow [227,242,3,19], no-bridge [58,75,91,107]), `glForward` 47–49 vs `sourceForward` 48–49. Composite 13–15 decoded |
| N5 KB frozen-upload (`413a00ba…`, fast) | RED, named series | `glReplayCarry1to2` False. (f) names **`glProbe` 'insufficient decoded reads'** (0/4; the frozen GL shows the restored poster, which has no counter). Also red: `composite` in (f) (0/13) and (b) "uploads not strictly increasing [91, 91]". `sourceSampleFrame` stays green (4/4, decoder running). Only `glReplayCarry1to2` is False among findings |
| KB off report scored (offline, `kb_off_scored.py`) | RED | Fast/slow/no-bridge off reports ⇒ False (b,c,d,f,g,h). (f) names composite, sampleFrame and glProbe. The same rebuild applied to the four auto reports ⇒ True (a–h), so the rebuild is sound. For off reports, (g) gets `[]` pre-flip owners (off reports do not record them) |
| CvC fast vs fast-rep2 | Identical | Every finding (id, pass, status) equal |
| **A7′** (`glProbeSampleFramePairing`, 4 runs × 4 reads) | PASS | lag 0: **16/16** \|Δ\| ≤ 2 (Δ −1…2, mostly +1). KB lag 1: 0/16 (Δ 15–18). `instrumentEscalation` False, no `alphaMin` < 255 read (every probe `ok`, alphaMin 255) |
| **A7 re-run** (sampleFrame vs same-read screenshot) | **PASS at \|Δ\| ≤ 3** (owner 2026-09-24: widened from 2) | lag 0: **16/16** within ±3 (12/16 within ±2), Δ −1…−3 (typically −2; r1 was −1, max 2). KB lag 1: 0/12 (Δ 16–19). Reason for the widening: the screenshot now comes about 1 counter step (~33 ms) later because the awaited probe read sits between `sampleFrame` and it; the instrument still separates same-read from previous-read (≤ 3 vs ≥ 16) and never mis-decodes, and the (f) series gate on progress, not pairing. Rescored from the saved deltas in `output/evidence/gates-glc/r2/p2/a7.txt`, no re-run. |
| **Q3** 20-min soak (`9989e8bf`, same G2 bytes; alone, load 8–30) | PASS | 0 GL errors in all 20 samples; heap 9.65–10.97 MB (flat, max ≤ 1.25× min); dropped 0/1381 frames; rVFC → rAF at end of media (the movie ends at 46 s, so all 1369 uploads happen before minute 1 and the rest of the soak is rAF replay, as in r3); `loseContext` at minute 10 ⇒ `contextLost` stand-down, write-back skipped, zone `retired failure/contextLost`; P3/P4 == control (parity 0, inside 0) |

## Harness changes since r1
- `splices/splice.py` and `g3/analyse_g3.py`: the expected G2 sha is now `10a5b36a…`.
- `output/evidence/gates-glc/run_gates_glc.sh`: `VIEWPORTS` env selects host viewports.
- New `output/evidence/gates-glc/run_auto_glc.sh`: a copy of `gates-g5g6/r3/g6p2/run_auto.sh`. Its only change is that `RUNNER` is
  word-split (`${=RUNNER}`), so it can hold `splices/run_spliced.py frozen <gate> <script>`.
- New `output/evidence/gates-glc/r2/p2/kb_off_scored.py`: rebuilds `glReplayCarry1to2` arguments from a report (plan, preserve
  events, census, reads, lingering, index sequence plus flipIndex, pre-flip owners from the carry detail) and scores it.
- The A7/A7′ scoring is inline in `output/evidence/gates-glc/r2/p2/a7.txt` (it calls `p2_verdict.glProbeSampleFramePairing`, and for A7
  `frameIndex` vs `screenIndexNonGating`, modulo 256).
- The raw r1 run (`g3/`, `g3-diag/`, `shas-*.txt`) was not retained.
- Everything else is as listed in r1: the `-oldbytes` arm, the 3 s uploads/s window, the N1/N2 rows and the integrity checks.

## Evidence (main checkout `output/evidence/gates-glc/r2/`)
- `g3/`: all g3h arms incl. go-to, gate 6, P5-7 and Q3, plus `gates.json`.
- `goff/`, `goff-1600-rerun/`.
- `p5a/`: 7 runs plus the oldbytes KB, `n3-cvc*.txt`, `rescore*.json`.
- `p5f/`.
- `p2/goff/`.
- `p2/g6/{auto-fast,auto-fast-rep2,auto-slow,auto-nobridge,kb-frozen}/` (report, inject and runs).
- `p2/kb-off-scored.txt`, `p2/a7.txt`.
