# Gate 4: historical impact review (offline), 2026-10-16

Plan §10 gate 4, before gate 5a. This review takes every past live-continuity run and verdict that is still available and classifies it under the new C2 validity rules (cost, settled cadence, environment). Gate 5a takes this list together with the Q1 host rows and the Q2 cadence statistic.

**Method.** The work was offline and read-only. No browser, capture, suite or Keynote ran, and no code changed.
- Source: `output/evidence/` in the main checkout, plus the `.agents/` records on `claude/stage-b-arch` @ `8e136d37`.
- The scan read files by content, not by key name. It recognised records of these kinds:
  - probe records (`kind: live-continuity-*`, or `statusReasons` with arms or verdicts);
  - P2 recovery reports (`probe: p2_*`);
  - managed-OBS feed runs and summaries (`runs[].valid`; a summary is skipped when its `feed-<ts>.json` exists);
  - detach runs;
  - verdict JSON embedded at the end of `.log` files;
  - `run_gates` logs that have no JSON artifacts;
  - results-only `uptime` sets.
- **Per-record list: [`gate4-historical-impact-inventory.tsv`](gate4-historical-impact-inventory.tsv)** (1,453 rows). Columns: path, SHA-256 prefix, run time, type, host, head, deck, arms, environment source, instrument, recorded cost, original outcome, green-subcheck count, class and reason.
  - The time comes from the record (`generated`/`ts`) when present, otherwise the file mtime.
  - For copied folders (`norider-ab`, `q7-round2`, `c1-timing`, `f4-faststart/acceptance-*`), the mtime is the copy time, so this document gives run times from their `uptime` logs.

**Classes (plan §10).** Each record lands in one of three classes:
- **proved INVALID:** at least one recorded fact violates the rules.
- **not re-evaluable:** nothing violates the rules, but validity cannot be shown.
- **still valid.**

Missing health never proves validity. Per the plan, a known validity failure takes precedence over an unproven one.

## Headline

| | Records | proved INVALID | not re-evaluable | still valid |
|---|---:|---:|---:|---:|
| Unique run records (904 source files) | **1,374** | **1,103** | **271** | **0** |
| Rescored duplicates (`detach-fix-rescore`, `detach-main-p2/auto/*.rescored.jsonl`), excluded from the totals | 79 | 79 | 0 | 0 |

- **No historical run is still valid.** None carries the all-hook `instrumentCost`, a settled per-visit cadence record or the full C2 environment (build, load/uptime, Chrome counts, rates).
- **Why the 1,103 are INVALID:**
  - 986 on environment alone (a recorded build other than .79);
  - 84 on cost alone;
  - 33 on both (predraw).
- **What used to count:**

| Original outcome | proved INVALID | not re-evaluable | Total |
|---|---:|---:|---:|
| Green: qualification pass, P2 `success`, gate MATCH, text PASS | 280 | 76 | 356 |
| Matched red/control arm | 252 | 0 | 252 |
| Formerly valid OBS run (`valid=True`, `passed=False`) | 5 | 59 | 64 |
| Fail/invalid | 168 | 90 | 258 |
| Refusal (nothing ran) | 0 | 2 | 2 |
| Other (inconclusive, experiment `ok`, running, results-only) | 398 | 44 | 442 |

- The TSV column `greenSubchecks` counts green subchecks: `verdict: true` nodes inside each record.
- Under §4 precedence, an INVALID expected red is never a MATCH, so all 252 historical red matches lose their standing.

## Chrome builds on this Mac

Every live-log session header records `Browser.getVersion`. These are the headless/HDMI builds; the OBS CEF `Chrome/127.0.6533.120` sessions are excluded:

| Build | First seen | Last seen | Sessions |
|---|---|---|---:|
| 154.0.8037.59 | 2026-10-09 17:00 | 2026-10-13 12:41 | 1,691 |
| 155.0.8059.40 | 2026-10-13 15:18 | 2026-10-14 08:47 | 143 |
| **155.0.8059.79** (pin) | 2026-10-14 09:30 | 2026-10-15 14:47 | 92 |
| **155.0.8059.80** | 2026-10-16 11:58 | 2026-10-16 13:53 | 47 (predraw-geometry, worktree `funny-pasteur-751a72`) |

- The installed Chrome reads 155.0.8059.80. `Versions/155.0.8059.80` and `Info.plist` are dated 2026-10-16 08:53, and the .79 folder is still present.
- **Only the predraw-geometry runs have a recorded .80** (their own live logs). They are proved INVALID on environment.
- Runs after 08:53 without a recorded build are only *implied* .80, so they stay not re-evaluable. The plan forbids inferring history from today's machine. These are:
  - noRider A/B (10:20–10:27);
  - F4 acceptance (09:18–11:18);
  - the C1 timing split (17:22–17:34).
- **The C1 record's "on Chrome 155.0.8059.79" is not supported by any record.** `c1-timing/all-summary.jsonl` stores no build.
- **Forward consequence (owner, gate 5a).** The pinned rule (exact 155.0.8059.79) cannot be satisfied by fresh captures on this machine as installed. Either re-qualify .80 and move the pin, or restore .79 and hold updates.
  - Precedent: `chrome155-requal/gates-r1.md`.
  - The C2 environment check (session `stage-b-c2-environment-a`) encodes the exact pin.

## Rules as applied

**Environment.** Rows are listed from strongest evidence to weakest.

| Evidence | Applied | Records |
|---|---|---:|
| Build in the record: detach `chromeVersion`, adapter-proof `browser`, or `placement.product` (alpha-placement `fix-ab/d2-*`, `d5-*`) | ≠ .79 → proved INVALID | 244 (154) + 4 (.79) |
| **Linked: the record's `exportRoot` / worktree path names a worktree, and that worktree's own live-log sessions in the 4 h before the record show one build.** Matched on exact `exportRoot` first, then worktree name (gate worktrees `gate-<kind>-<head>`). Siblings without a path in the same gate-round folder inherit the round's link only if all linked siblings within 4 h agree. | ≠ .79 → proved INVALID | 714 (154) + 61 (.80) + 8 (.79) |
| Not recorded | not re-evaluable | 272 |
| Managed OBS (CEF): Chrome rule not applied (CEF policy preserved). OBS 32.2.2 and rates are recorded; load/uptime and Chrome counts are absent. | not re-evaluable | 71 |

**Cost.** The proposed gate is **8 ms p95 on every hook**. Owner Q2 has not frozen it yet.
- **Recorded `callbackCostP95Ms` / `costP95` above 8 → proved INVALID.** This is the only historical cost field, and it measures rVFC only. Recorded INVALIDs are 38–128 ms, ≥ 30 ms over the gate.
- **Identity → proved INVALID.** C1 shows that the `willReadFrequently:true` feed instrument from `1df31c33` on, with the pre-move capture active, costs 113–116 ms. A run on that instrument with the capture on and no recorded cost is INVALID. Head ancestry is checked with `git merge-base` (`03a35b28`, `39b32de9`, predraw heads ⊇ `1df31c33`; `51ead0a8`, `24b1c91d`, `c104d5a3` are not).
- **Capture patched out → not INVALID by identity.** The harness replaced the `atScene-1` guard in `alpha-placement/repro/run_dbg.py:11`, `norider-ab` `CAPTURE=off`, `f4-faststart/acceptance-39b32de9/acc.sh:9` (`NO_PREMOVE_CAPTURE=1`) and `f4-faststart/tools/run_obs_ab.py:8-10`.
- **Narrowing of the brief's rule.** Every feed instrument carries `willReadFrequently:true` from `9bf912b6` (10-14) until the C1 fix. But runs that recorded ≤ 3.1 ms on it are not observed over budget, and C1's single wrf:true draw costs about 7 ms. So "wrf:true" alone is not applied as INVALID. Decision 4 below gives the literal-rule count.
- Recorded ≤ 8 ms, or nothing recorded → not re-evaluable.

**Cadence.** This is reported only, and no statistic is frozen (Q2). No record has a settled per-visit partition with GL exclusions, so cadence decides no class.

## Inventory by group

INVALID = proved INVALID; n.r. = not re-evaluable. Run windows are in the TSV.

| Group | Records | Original outcomes | Environment | Recorded cost (ms) | Instrument | Class |
|---|---:|---|---|---|---|---|
| `s2-dev/{decks-4a2ea70f,g1*,i1–i4,ab-r8-D4,p2ctrl}` `.log` (09-25) | 40 | 29 green, 11 fail | not recorded | — | no feed | n.r. 40 |
| `main-bridge-easing/baseline-2026-10-09-main-linear` (P2) | 23 | 9 green, 14 fail | not recorded | — | no feed | n.r. 23 |
| `s2-dev/detach-*` | 242 | 242 experiment `ok`/`no-events` | in-record 154 | — | no feed | INVALID 242 |
| `s2-dev/decks-0ff28399` | 24 | 18 green, 6 other | linked 154 | — | no feed | INVALID 24 |
| `s2-dev/gates-0ff28399-j3` (incl. P2) | 46 | 11 green, 27 red ✓, 8 fail | linked 154 | — | no feed | INVALID 46 |
| `s2-dev/passg-fd00b12c` | 7 | 7 green | not recorded | — | no feed | n.r. 7 |
| `s2-dev/decks-702db627` | 2 | 1 green, 1 running | linked 154 | — | no feed | INVALID 2 |
| `s2-dev/decks-32067445`, `passg-32067445` | 25 | 25 green | linked 154 | — | no feed | INVALID 25 |
| `s2-dev/phaseD-867e415c` (incl. P2) | 77 | 42 green, 27 red ✓, 8 fail | linked 154 | — | no feed | INVALID 77 |
| `s2-dev/q7a-goto1` | 1 | 1 green | not recorded | — | no feed | n.r. 1 |
| `main-bridge-easing/r3`, `r3-rerun` (incl. P2, adapter proofs) | 33 | 8 green, 5 red ✓, 18 fail, 2 other | linked/in-record 154 | — | no feed | INVALID 33 |
| `s2-dev/cc-D1*` | 15 | 15 inconclusive | not recorded | — | no feed | n.r. 15 |
| `main-bridge-easing/freeze-ab` (P2) | 12 | 7 green, 5 fail | not recorded | — | no feed | n.r. 12 |
| `main-bridge-easing/final-dcd5b9e4` (incl. P2) | 31 | 14 green, 5 red ✓, 12 fail | linked 154 | — | no feed | INVALID 31 |
| `s2-dev/glclock-v6` (incl. P2) | 90 | 29 green, 28 red ✓, 30 fail, 3 other | linked 154 | — | no feed | INVALID 90 |
| `s2-dev/contract-smoke-de6df228` | 2 | 2 green | linked 154 | — | no feed | INVALID 2 |
| `s2-dev/fold-r12-r16` | 3 | 2 green, 1 fail | not recorded | — | no feed | n.r. 3 |
| `s2-dev/instr-v-{277c720b,9d4fbef5,8bdaf582,ecf1b553}` (incl. P2, managed OBS) | 432 | 130 green, 160 red ✓, 40 formerly valid (OBS), 80 fail, 22 other | 386 linked 154; 46 CEF | — | no feed | INVALID 386, n.r. 46 |
| `mm-fade-gates` (MO/HB probes: 2 JSON, 2 text PASS logs) | 4 | 2 green, 2 other | not recorded | — | no feed | n.r. 4 |
| `q7-attempt1` | 2 | 2 fail (`valid=False`) | 1 CEF, 1 not recorded | — | wrf:true (`c104d5a3`) | n.r. 2 |
| **`q7-attempt2`** (`51ead0a8`) | 3 | **3 formerly valid** | CEF | 2.6–3.1 | wrf:true | n.r. 3 |
| **`q7-attempt3`** (`03a35b28`) | 5 | **5 formerly valid** | CEF | **38.3–44.0** | capture on | **INVALID 5** |
| **`q7-round2/headless`** (`03a35b28`) | 8 | 5 inconclusive, 2 fail, 1 refusal; green subchecks | **linked .79** (`s2-followups-dsk-deck-902af1`, 14:42–14:47) | — | capture on | **INVALID 7**, n.r. 1 (`d7-unrepaired` refused) |
| `q7-round2/alpha-stall/ab-summary.jsonl` (about 17:30–17:50) | 12 | 12 inconclusive | not recorded | 2.4–128.3 | wrf:true | INVALID 7, n.r. 5 |
| `alpha-placement` incl. `fix-ab/` (20:51–22:57) | 36 | 5 green, 10 fail, 20 other, 1 refusal | 4 in-record .79, 32 not recorded | 0.2–3.0 | capture patched out; d2/d5 no feed | n.r. 36 |
| `f4-faststart/obs` (10-15 22:05–22:17) | 8 | **8 formerly valid** | CEF | — | capture patched out | n.r. 8 |
| `f4-faststart/acceptance-39b32de9/obs` (A4) | 8 | **8 formerly valid** | CEF | — | capture patched out | n.r. 8 |
| **`norider-ab`** (10:20–10:27) | 8 | 4 fail, 4 inconclusive | not recorded (implied .80) | — | 6 capture on, 2 patched | **INVALID 6**, n.r. 2 |
| `f4-faststart/acceptance-39b32de9/attach` | 6 | 6 fail | not recorded | — | no feed | n.r. 6 |
| `f4-faststart/acceptance-39b32de9/{headless,paint}/compare.jsonl` (A2/A3, 09:18–) | 20 | 20 fail | not recorded (implied .80) | 0.1–2.6 | capture patched out | n.r. 20 |
| **`f4-faststart/acceptance-39b32de9/gates/*.log`** (A5, two rounds) | 76 | 14 green, 17 fail, 45 other | not recorded (implied .80) | — | 54 MM-FEED gates with capture on (`39b32de9`); 22 others no feed | **INVALID 54**, n.r. 22 |
| **`predraw-geometry`** results-only (`*uptime.txt`, 11:58–13:47) | 61 | results only | **linked .80** (`funny-pasteur-751a72`, 47 sessions) | — | 33 capture on (headed sets), 28 A/B lines without a head | **INVALID 61** |
| `c1-timing/all-summary.jsonl` (17:22–17:34) | 12 | 10 fail, 2 inconclusive | not recorded (implied .80) | 2.53–119.38 | wrf:true variants | INVALID 5, n.r. 7 |

`ab-summary` detail: R `new-on-1/2`, `new-off-1`, `hyb-newscripts-oldsrc`, `bis-1df31c33` at **110.35–128.3** and the load-overlapped `bis-ca39b819`/`bis-dd16db52` at 124.6–127.0 are INVALID. N (2.4) and O (2.5–2.9) are not re-evaluable.

C1 detail: `01`/`10-head`, `02-old`, `09`/`09b-fidelity` (109.7–119.4) are INVALID. `08-single-384` is exactly **8.0**, so it depends on the equality rule (decision 3). The other runs (2.53–7.6) are not re-evaluable.

## Past verdicts that change class, and who cites them

1. **Q7 attempt 3: the five `valid=True` OBS feed runs.**
   - Change: formerly valid → **cost INVALID**. Both sessions recorded 38–44 ms.
   - The instrument's hand-back and paint verdicts are INVALID readings. The owner's eye observations stand as owner observations.
   - For the Alpha "jittery / first video stops" report, `alpha-b3to4-stall-2026-10-15.md` finding 2 attributes the jitter to this observer effect. So this evidence does not show a product defect.
   - Cited by: plan §1; `c6-gate-record.md` (offline replay parity is a scoring check and stands; its replayed verdicts carry no validity); `stage-b-implementation-2026-10-15.md`; `alpha-b6to8-placement-2026-10-15.md`; `alpha-b3to4-stall-2026-10-15.md`.
2. **`q7-round2/headless` on `03a35b28`.**
   - The verdicts: D7 feed-on "all six hand-backs 1–2", noRider/labels/artwork green, D7s green, and the reds `no-linger` and `interim-delay`.
   - Change: → **cost INVALID** by identity. The environment is linked .79, which is not a violation.
   - `d7-unrepaired` is a refusal (`arms: null`, nothing ran): not re-evaluable, and the refusal itself stands.
   - Cited by: `stage-b-implementation-2026-10-15.md` lines 49–51, 65–66; plan §1.
3. **Q7 attempt 2 (`51ead0a8`, pre-`1df31c33`): three `valid=True` runs.**
   - Change: formerly valid → **not re-evaluable**. Recorded rVFC is 2.6–3.1 ms, and other hooks, load and Chrome counts are absent.
   - Cited by: `keynote_live_continuity_stage_b_q7_handback.plan.md`.
4. **F4 warm-up OBS runs: 16 `valid=True`** (`f4-faststart/obs`, acceptance A4).
   - Change: formerly valid → **not re-evaluable** (capture patched out, CEF, no cost recorded).
   - Cited by: `f4-faststart-measure-2026-10-15.md`; `movie-warmup-2026-10-16/acceptance-record.md`.
5. **Alpha placement fix A/B (`alpha-placement/gate-record-2026-10-15.md`, `fix-ab/`).**
   - The greens: `handbackContinuity` B "T/T/T/T", P2 `--gl-replay auto` (`fix-ab/p2-gl-replay.report.json`, `success: true`), D2/D5 pass.
   - Change: → **not re-evaluable**. D2/D5 record `.79` in the record. The rest record no build, and cost ≤ 3.0 ms with the capture patched out.
6. **noRider A/B (same record, §noRider; 10-16 10:20–10:27).**
   - Change: `capOn` ×6 → **cost INVALID** by identity; `capOff` ×2 → not re-evaluable.
   - The record's own finding, that capture on vs. off gives identical offenders, still stands as a within-run comparison. The `capOff` arms carry it, and the root cause is the rider census counting frames before the first GL draw.
7. **Pre-draw geometry gate (`predraw-geometry/gate-record-2026-10-16.md`, `step0-2026-10-16.md`).**
   - Covers sets step0 `533f88d5`, val `f9cdc159`/`794dfe4c`, f4 `b3ddc071`, hand-back A/B, and final `9d5cf850`.
   - Change: → **environment proved INVALID** (own live logs record `Chrome/155.0.8059.80`), and cost INVALID by identity for the headed sets.
   - `PRE_DRAW_GRACE_MS` = 320 was set provisionally by the owner from stored 10-15 prefixes (176–315 ms; `gate-record-2026-10-16-predraw.md`, an offline replay that stands). These .80 runs only confirmed it "stays 320", so that confirmation is INVALID evidence.
8. **F4 acceptance (`movie-warmup-2026-10-16/acceptance-record.md`).**
   - Change: A5 MM-FEED gates (54 of 76 across two rounds) → **cost INVALID**. They are `39b32de9` with the capture on, and the record states "`callbackCostP95Ms` ~128 ms" for the MM-FEED failures.
   - The A5 non-feed gates, A2/A3 (capture patched out) and A4 (CEF, patched) → not re-evaluable.
   - The cold-start medians stand as product timing measurements, not continuity verdicts.
9. **C1 timing split (`c1-timing-split.md`).**
   - Change: the five expensive runs (the deliberate red) → cost INVALID; the rest → not re-evaluable.
   - Its relative conclusions are within-run comparisons and stand.
   - Its absolute acceptance numbers have no recorded build. **Gate 2 must re-measure on the build gate 5a pins.**
   - Cited by: `stage-b-instrument-restructure-2026-10-15.md`.
10. **`ab-summary.jsonl` (plan §4 M1).**
    - Change: R and load-overlapped → cost INVALID, which confirms their role as the red; N and O → not re-evaluable.
    - Cited by: plan §4; `plan-critique-r1/r2.md`; `alpha-b3to4-stall-2026-10-15.md`; `alpha-b6to8-placement-2026-10-15.md`.
11. **S2-era qualification (Chrome 154, linked).**
    - Records and their greens:
      - `continuity-generalisation/gates-r1.md` (`ecf1b553`, "DONE tier=full failed=0": P2 15/15, D3 15/15, host ×3, Pass G ×7, deck sweep 19/19, Vgl forced-ok ×4, L1/L2);
      - its `8bdaf582` final C1 round;
      - `main-bridge-easing/gate-record.md` (`dcd5b9e4` "failed=0", carry-cover 72/72; `87f8c450` r3);
      - S2 rounds `0ff28399`, `32067445`, `867e415c`, `702db627`;
      - `glclock` `c7d2d649`;
      - contract smoke `de6df228`.
    - Change: → **environment proved INVALID**.
    - The S2 managed-OBS "8/8 PASS" (40 summaries in `instr-v-*`) → not re-evaluable (CEF).
    - Gate 14 re-runs Q2–Q6 anyway, so nothing needs grandfathering.
12. **S2 detach experiments (242 runs).** Change: → environment proved INVALID (154 in record). Cited by the detach r8, contract and instrument plans and `alpha-b6to8-placement-fix-2026-10-15.md`.

## Records without retained run artifacts

These records are not re-evaluable, and they are not counted in the headline.

| Record | Head(s) | Live-continuity claim | Build stated |
|---|---|---|---|
| `continuity-generalisation/s1-gates-r1.md` | `421b4f39` | host ×3, P2 15/15, reds | none (pre-10-09) |
| `continuity-loopmode/gates-r1.md`, `gates-r2.md` | `21944ddb`…`bda4a537` | P2 14/14, L1, L2 6/6; OBS L5/soak PASS | none |
| `gl-replay-c/gates-r2.md` | `9989e8bf`, `bef57a23` | all gates PASS | none |
| `gl-replay-managed/gates-r1.md` | `812fd9d5` | OBS M0–M6 PASS | CEF 127 |
| `handback-geometry/gates-r1.md` | `7cd51e9f`, `0bb21fcc`, `ad13d8a3` | P2 14/14; OBS 25/30 PASS | none |
| `mm-opacity/gates-r1.md` | `102d4ca4`…`0f6d0380` | headless PASS, P2 14/14; MO-2 PASS ×10 | none |
| `gates-speedup-2026-10-09/gate-record.md` | `91f9daae`, `2bf11264` | 13/13, host ×3 PASS | **154.0.8037.59 stated** → environment INVALID on the record's own text |
| `s3/gates-r1.md` | `264acdd4` | full gates "failed=4"; A/B 12/12 | none (10-13) |
| `mm-fade/gates-r1.md` | `c0628297` | MO/HB probes PASS (partly retained: `mm-fade-gates/`, 4 records above) | none (10-13) |
| `stage-c/gates-r1.md`, `stage-t/gates-r1.md` | — | host G4 13 steps; G2 | none (10-13) |
| `mm-opacity-unmatched-hidden/gates-r1.md` | `ab58fdd6` | UH-1 7/7 (10-15 11:24) | none (between the .79 sessions) |
| `suite-speedup/gate-record.md` | — | stub rounds only; the real round is open | n/a (not live) |

## Cadence: per-visit data, no statistic frozen

Raw sampler rows survive only in the S2-era deck runs and the main-bridge-easing host gates. Restricted to `status: pass` runs, that is 44 files and 549 settled visits.
- A settled visit means consecutive rows of one sampler `scene` with `IdleAtFinalState` and `busy=false`.
- There is no GL exclusion data, and p95 is nearest-rank.
- Every one of these runs is environment INVALID (154) and has no feed instrument. The data shows the shape of the statistic, not calibration.

| Viewport (arms A/B/C) | Clock | Visits | median > 2P | median ≈ 33.3 | p95 > 2P | max > 2P | worst p95 | worst max |
|---|---|---|---|---|---|---|---:|---:|
| 1600×1000 | `t` | 64/50/58 | 0/0/0 | 8/9/8 | 12/10/12 | 12/12/14 | 35.9 | 76.1 |
| 1920×1080 | `t` | 68/68/48 | 0/1/0 | 7/11/7 | 12/14/8 | 12/15/8 | 35.2 | 36.3 |
| 2560×1440 | `t` | 64/50/58 | 0/0/0 | 7/7/8 | 12/10/12 | 13/12/13 | 35.6 | 84.0 |
| P2 host 1920 | `ts` (rAF) | 7/7/7 | 0/0/0 | 2/2/2 | 2/2/2 | 2/2/2 | 33.4 | 33.4 |

`2P` = 33.3333 ms (headless 60 Hz row). Observations:
- **Medians.** One median exceeds 2P: 33.35 ms (`decks-32067445/D3-1920` arm B, scene 0). 78 of 549 visits (14 %; 10–18 % per cell) sit at a 30 Hz median of about 33.3.
- **p95.** 108 of 549 visits (20 %; 17–21 % per cell) exceed 2P, at 33.4–35.9 ms. That includes the rAF-clock P2 visits at 33.4.
- **Max.** Clean passes exceed 2P by up to 50.7 ms. The largest are `main-bridge-easing/r3/gates/host-2560x1440.json` arm C at 84.0 and `host-1600x1000.json` arm C at 76.1, both in scene 0.
- So on this history, a per-visit p95 > 2P rule rejects about 20 % of clean visits, and a max > 2P rule rejects more. Plan §4 already raised this; these numbers quantify it.
- **Stage B era.** Only scene-level data exists (`ab-summary`, C1 `samplerCadence`), and §4 already tabulates it.

## Out of scope

These are listed so the count is complete.
- **Not live-continuity validity subjects:** dissolve/DX-1 freeze (`chrome155-requal`, `chrome-requal-script`; recorded .79), alpha movies, line draw (`line-draw-stamp-2026-10-14`), text glyph and texture graft.
- **Placement and design spikes:** CEF placement (`dissolve-alpha-2026-10-11/cef-placement-live-*`), the OBS run restructure, `cef-step`, `glfeed`, `phase0`, `mockup`, `textures`, `mm-shape-id`, `slide11`, `mm-freeze`, `obs-managed-spike`.
- **Product timing measurements:** the `f4-faststart` cold-start and gap files outside `acceptance-*`.
- **Diagnostics without verdicts:** `pingap*` paint-gap traces (27 files), `q7-round2/spike`, and the alpha-placement `stacks` / `dbg` sidecars.
- **Offline replays:** `fold-r12-r16/accept-*.json` and the `oracle` outputs.
- **Suite and tool logs:** `suites-*`, `tools-*`, `triage-*`, `merge-wip`.
- Chrome-qualified dissolve placement grants by major (`QUALIFIED_SNAP_MAJORS`), so .80 is still granted. Whether to requalify .80 there is a separate question.

## Owner decisions for gate 5a

1. **Chrome pin vs. the installed .80.** Re-qualify 155.0.8059.80 and move the pin, or restore .79 and hold updates.
2. **Accept this inventory** as the historical list: 1,103 proved INVALID / 271 not re-evaluable / 0 still valid of 1,374 unique run records, plus the no-artifact records table. No grandfathering, no rewrites.
3. **Cost equality.** C1 `single-384` sits at exactly 8.0 ms. State whether the gate is `> 8` or `≥ 8`.
4. **Scope of the wrf rule.**
   - Applied here: recorded cost first, then identity of the `1df31c33`-era capture.
   - A literal "any `willReadFrequently:true` instrument → INVALID" rule would add the 85 not-re-evaluable records that ran the feed instrument:
     - `alpha-placement` 30;
     - `f4-faststart` 36 (20 compare, 16 OBS);
     - C1 7;
     - `ab-summary` N/O 5;
     - noRider `capOff` 2;
     - Q7 attempt 1 ×2 and attempt 2 ×3.
   - Totals would become 1,188 / 186 / 0. Refusals and records without the feed instrument (d2/d5) are excluded.
5. **Q2 cadence.** On clean history, p95 > 2P hits about 20 % of visits and max > 2P more. Decide together with fresh C1-fixed per-visit captures (gate 3).

## Review log

- **r1, Opus 5.5 high, NOT READY.**
  - Blocker: inventory incomplete. Missing were P2 reports, 16 formerly valid F4 OBS runs, verdict JSON in `.log` files, mm-fade logs, and predraw/F4 counted nowhere.
  - Majors:
    - TSV fields;
    - noRider misattribution.
  - Mediums:
    - .80 stated as fact;
    - decision-4 count;
    - 79 detach rescores double-counted;
    - F4 overgeneralised;
    - cadence max understated.
  - Lows:
    - ab-summary R range;
    - linked .79 for `q7-round2/headless`;
    - d2/d5 in-record .79;
    - `d7-unrepaired` refusal;
    - `PRE_DRAW_GRACE_MS` provenance;
    - speculative cadence conditional;
    - a running run in the cadence sample;
    - dangling reference;
    - cite `exportRoot` for links.
  - **All 16 folded:**
    - the content-based rescan grew the inventory to 1,374 run records;
    - rescored duplicates are excluded;
    - .80 is recorded for predraw only;
    - the literal-rule count was recomputed from per-record flags;
    - the cadence table is restricted to pass runs.
  - The reviewer confirmed the live-log linking (via `exportRoot` worktrees and time windows), the .80 timeline, the recorded costs, the instrument ancestry and the narrowing of the wrf rule.
