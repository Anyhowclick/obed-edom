# GL-replay option (c) headless gates r2: PARTIAL, all run gates PASS (2026-09-23, `9989e8bf`)

Plan: `.agents/plans/keynote_live_gl_replay_c.plan.md` rev 1, §8. This round supersedes r1 (`gates-r1.md`, stopped
at gate 2 on the core `moduleVersion` refusal of G2 v2). The owner chose v1, and the fix is `9989e8bf`. The round ended at
the owner's 23:25 cut-off for starting batches, and the last batch finished at 23:23. The not-run list below gives the
exact commands to resume.

## Provenance
- **Commit.** Clean detached worktree `.claude/worktrees/gates-glc-r2` at `9989e8bf`, not dirty at start or end.
  Set up with `uv sync --all-extras --all-groups` and a fixture symlink to main-checkout `output/p2-recovery/html-adversarial`.
- **Shas (start == end).** G2 `10a5b36a…` v1 (host reports `injected` v1 `10a5b36a…`). Core `e9338aff…`, unchanged. Fixture:
  `index.html` `5908d479…`, `preserve-inject.json` `53cf8339…` and `continuity-plan-inject.json` `91a29d5e…`.
  Evidence: `output/gates-glc/r2/shas-{start,end}.txt`.
- **KB splices** (harness only, `output/gl-replay-c-harness/splices/splice.py`, one asserted substitution each).
  - `oldbytes` = the `d56fb0dd` text, sha `4f8850e0…`.
  - `frozen` was rebuilt on the new bytes: sha `413a00ba…`. It is not used yet (P2).
  - `-v1diag` is obsolete, since the new G2 sha equals the r1 v1diag sha `10a5b36a…`.
- **Discipline.** There were ≤ 3 Chromes per batch. Go-to arms, G-OFF and each probe ran alone, with `uptime` in each
  `batches.txt` (load 3–45). `pgrep -f headless=new` was empty before every batch except gate 6. There it showed one PID
  (37424) that had exited by the next check, almost certainly the G-OFF host's Chrome shutting down. So gate 6 may have
  overlapped one exiting Chrome. It passed, so this is noted, not re-run. No Keynote, no OBS.

## Results

| Gate | Verdict | Numbers |
|---|---|---|
| N1 KB (`armed-oldbytes`, 1920) | RED, right reason | Ring max 251/251/252 at P2/P2b/P2c, fracOver8 0.767 (== r3). Only other red: N2 (sibling). Every existing hand-off check green |
| N1 CvC (control-2 vs control) | 0 | max 0 at P2/P2b/P2c (n 6737 ring px) |
| N1 pass | PASS | armed, armed-2 (vs control) and armed-lb (vs control-lb): max 0 at all three points |
| N2 CvC | PASS ⇒ **gating** (OQ-5) | control, control-2 and control-lb: B00–B03 == own P2c (0), B04–B09 == own P3 (0) |
| N2 KB (`armed-oldbytes`) | RED, right reason | B00–B02 match neither (vs P2c ≈ 252, vs P3 255, fracOver8 0.77) |
| N2 pass | PASS | Every armed/armed-2/armed-lb B-shot ≤ 2 vs control P2c or P3 |
| Gate 1 install order | PASS | 245 wrapped at install, order plan < core < gl-replay < fit < #stage < main.js, host `injected` v1 |
| Gate 2 | PASS | frameLen 88, occluded 20/128, oracle LIVE n=24, paused DEAD, carried/pool, innerRect {4,4,952,268}. **Uploads 29.90 / 29.89 / 29.90 /s** (armed/-2/-lb) vs old bytes 29.97/s (same batch) and r3 ≈ 30/s: no drop |
| G-OFF host ×3 (blocking) | PASS on verdicts; 1600 key set differs | Summary (status, arm modes, all boundary verdicts, visible slides) == G-0′ at 2560, 1600 and 1920. Key sets == G-0′ at 2560 and 1920. **At 1600, arm C `continue3to4`** (bridge disabled, False in both) took the "sampled, failed" path instead of G-0′'s "no decoder id spans the boundary" path. The verdict is the same. The off path's code is unchanged, so this is likely timing under load (45 at the start), but it is **not proven**. A 1600 re-run is listed below |
| Gate 4 / 4b | PASS | All existing hand-off checks plus N1/N2, at 1920 (armed, armed-2) and 1600 letterbox |
| Gate 6 fail-closed | PASS | 20 forced + late `contextLost`/`frameLengthChanged`/`glError`, all PASS. Late `canvasRemoved` is report-only |
| Gate 7 go-to | PASS | goto2, goto3walk and fullDeckWalk |
| P5-7 | PASS | goTo 3 → goTo 1 → advance 2: zone `armed → retired (cleared)`, 0 `glreplay-live`, P7/P7b slide-2 shots byte-identical to the flag-off twin (same sha, parity 0) |
| P5-A (3 viewports + 1 rep at 2560) | PASS 4/4 | `armed1to2` A and C True. Vgl armed slide True. Hand-back parity maxOutside 0 |
| **N3** | PASS | liveRing max 0 at 2560 (10251 px), 2560-rep2 (10251), 1600 (2690) and 1920 (4740). Dilation 2 |
| N3 KB (Vgl-oldbytes, 2560) | RED, right reason | liveRing max 245, 10251/10251 px. Status `fail` with the single reason "live ring failed". Hand-back, `armed1to2` and armed slide all still green |
| N3 CvC | 0 at 2560 only | V vs V 0 and Vgl vs Vgl 0 (2560 vs 2560-rep2). **Not run at 1600/1920** (needs a second run per viewport) |
| P5-A/H KBs and controls (offline `rescore_p5.py`) | RED / 0 | Vgl vs facts_off RED 4/4. V as armed slide RED 4/4. V-as-Vgl hand-back RED, 1-px poke RED, synthetic ring px RED undilated / GREEN dilated (4/4). Own facts 0. V/V and Vgl/Vgl hand-back 0. Two Vgl runs identical |
| P5-L | Recorded | mutationScanMs 0–0.1. Hand-off completedMs 3.3–3.5 |

## DONE / NOT RUN
- **DONE:** N1 and N2 (KB, CvC, pass); gates 1, 2, 4 and 4b; G-OFF host ×3; gate 6; gate 7; P5-7; P5-A ×3 plus 1 rep at 2560;
  N3 plus its KB; N3 CvC at 2560; P5-H (from the P5-A runs); P5-L.
- **NOT RUN:**
  - a second rep at 2560 (the plan asks for 2);
  - N3 CvC at 1600 and 1920;
  - a G-OFF host 1600 re-run, to settle the key-set difference;
  - P5-F;
  - all of phase 2: G-OFF P2 off fast/slow/no-bridge, G6 P2 auto fast ×2/slow/no-bridge with N5 and the frozen KB,
    off-report-scored KB, fast vs fast-rep2 CvC, A7′, and the A7 re-run;
  - Q3 (20-min soak).

## Resume commands (from main checkout `output/`; `G=…/.claude/worktrees/gates-glc-r2`, `O=…/output/gates-glc/r2`; run `pgrep -f headless=new` first)
```
P="$G/.venv/bin/python -u"; F=output/p2-recovery/html-adversarial; cd $G; export PYTHONPATH=$G/src
# P5-A reps (N3 CvC per viewport) — one at a time
for V in 2560x1440:2560x1440-rep3 1600x1000:1600x1000-rep2 1920x1080:1920x1080-rep2; do mkdir -p $O/p5a/${V#*:}; $P scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport ${V%%:*} --gl-replay auto --artifact $O/p5a/${V#*:}/probe.json > $O/p5a/${V#*:}/run.log 2>&1; done
# P5-F (2560), each alone: planUnreadable rvfcUnavailable posterAmbiguous occlusionTooHigh bogusReason
mkdir -p $O/p5f/R; $P scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 2560x1440 --gl-replay auto --gl-force-fail R --artifact $O/p5f/R/probe.json > $O/p5f/R/run.log 2>&1
# G-OFF host 1600 re-run
VIEWPORTS=1600x1000 output/gates-glc/run_gates_glc.sh $G $O/goff-1600-rerun host
# Q3 (alone; >10 min, run in background)
output/gl-replay-c-harness/g3/run_arms.sh $G $O/g3 1 q3
# rescore
$G/.venv/bin/python output/gl-replay-c-harness/rescore_p5.py $G <run dirs>; $G/.venv/bin/python output/gl-replay-c-harness/g3/analyse_g3.py gates $O/g3
```
Phase 2 needs its own worktree at `9989e8bf`, which already contains the P2 stream. It runs `run_gates_glc.sh … p2fast|p2nobridge|p2slow`
for G-OFF P2, then the auto P2 runs, with `splices/run_spliced.py frozen $G $G/scripts/p2_recovery_html_adversarial.py …` for the N5 KB.

## Harness changes since r1
- `splices/splice.py` and `g3/analyse_g3.py`: the expected G2 sha is now `10a5b36a…`.
- `output/gates-glc/run_gates_glc.sh`: `VIEWPORTS` env selects host viewports, so each Bash call stays under 10 min.
- Everything else is as listed in r1 (the `-oldbytes` arm, the 3 s uploads/s window, the N1/N2 rows and the integrity checks).

## Evidence
`output/gates-glc/r2/`: `g3/` (all g3h arms plus `gates.json`), `goff/` (host ×3), `p5a/` (4 runs, the oldbytes KB,
`n3-cvc.txt`, `rescore.json`) and `shas-{start,end}.txt`.
