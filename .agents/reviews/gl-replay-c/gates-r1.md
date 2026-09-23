> **SUPERSEDED by `gates-r2.md` (`9989e8bf`, G2 kept at v1).** Kept as the record of the v2 `moduleVersion` blocker.

# GL-replay option (c) headless gates r1: STOPPED at gate 2 (2026-09-23, `ca08e2e4`)

Plan: `.agents/plans/keynote_live_gl_replay_c.plan.md` rev 1, §8. Phase 1 only (no P2, G6, N5 or A7′ runs). The round
stopped after the first armed batch. The core refuses G2 v2, so the armed path never arms. Nothing after gate 2 ran.
Phase 2 (`d5c71661`) did not run either. Its core and G2 bytes are identical to `ca08e2e4` (`git diff --stat` is empty),
so it inherits the blocker.

## Provenance
- **Commit.** Clean detached worktree `.claude/worktrees/gates-glc-r1` at `ca08e2e4`, not dirty at start or end.
  Set up with `uv sync --all-extras --all-groups` and a fixture symlink to main-checkout `output/p2-recovery/html-adversarial`.
- **Shas (start == end).** G2 `e3ae63f4…` v2. Core `e9338aff…`. Fixture: `index.html` `5908d479…`,
  `preserve-inject.json` `53cf8339…` and `continuity-plan-inject.json` `91a29d5e…` are unchanged.
  Evidence: `output/gates-glc/shas-{start,end}.txt`.
- **Env.** `OBED_LIVE_GL_REPLAY` was unset. `pgrep -f headless=new` was empty before each batch. There were ≤ 3 Chromes.
  The load was 21 → 10 (see `output/gates-glc/g3/batches.txt`). No Keynote, no OBS.
- **KB splices** (harness only, `output/gl-replay-c-harness/splices/splice.py`). Each asserts exactly one substitution and
  prints the resulting sha:
  - `oldbytes` = `git show d56fb0dd:` text, sha `4f8850e0…` asserted;
  - `frozen` = the LIVE `perLiveUpload()` call removed, sha `28dbb5e8…`. It is built and checked, but not yet used (P2 only);
  - `v1diag` is **diagnostic only, not a KB**: the page `API.version` literal 2 → 1, sha `10a5b36a…`.

## Blocker: the core refuses module version 2
- Core `live_continuity_js.py:531` `zoneState()` has `m.version !== 1 ? 'moduleVersion'`. The zone goes
  `pending → retired (moduleVersion)` at load, before `#1`. G2 then stands down `assetUnbound` on `#1`, with 0 uploads and 0 iterations.
- This happened in all three armed arms (`armed`, `armed-2`, `armed-lb`). Their `result.json` files show `coreEvents` zone reason
  `moduleVersion`, `apiFinal.version` 2 and `standDowns ['assetUnbound']`.
- `tests/test_live_continuity_js.py:1976` and `:2963` pin exactly this refusal (`version: 2` ⇒ `moduleVersion`).
- Plan D6/§6 (OQ-2 bump 1→2) and "core untouched (`e9338aff`)" cannot both hold. The G2 unit sandbox runs without the core,
  so it could not catch this.
- Fixing it needs a decision. One option is to keep `API.version` 1, which reverses OQ-2. The other is to make the core
  accept 2, which moves `PINNED_CORE_SHA256`, `CONTINUITY_VERSION`/allowlist review and G-OFF. Either way, every gate re-runs on the new tip.

## Results

| Check | Verdict | Numbers |
|---|---|---|
| N1 KB (`armed-oldbytes` vs control, 1920) | RED, right reason | Ring max 251/251/252 at P2/P2b/P2c, fracOver8 0.767 (== r3 251/0.767). Other red: only N2 (its sibling). Every existing hand-off check passed on old bytes. A repeat in the diag batch read 251, fracOver8 0.739–0.742 |
| N1 CvC (control-2 vs control) | 0 | max 0 at P2/P2b/P2c, n = 6737 ring px |
| N2 CvC (control burst vs own P2c/P3; control, control-2) | PASS ⇒ **N2 gates** (OQ-5) | B00–B03 match P2c (0), B04–B09 match P3 (0). Control's own P2c vs P3 ring differs (max 255 on 0.4 %), so build 1 has two ring states and no third |
| N2 KB (`armed-oldbytes`) | RED, right reason | B00–B03 match neither (vs P2c 252–254, fracOver8 0.76; vs P3 255). B04–B09 match P3 after the hand-off |
| G-OFF host ×3 | NOT RUN | Stopped. The fix may touch the core |
| Gate 1 install order | PASS | 245 wrapped at install, served order plan < core < gl-replay < fit < #stage < main.js, and the host reports `injected` v2 `e3ae63f4…`. Install precedes the core's refusal |
| **Gate 2 (uploads/s)** | **FAIL / STOP** | `ca08e2e4` armed: **0 uploads/s, 0 iter/s** (state RETIRED, `moduleVersion`). Old bytes, same machine: 29.89 and 29.93/s (r3 ≈ 30/s) |
| Gates 4/4b, 6, 7, G5, Q3 | NOT RUN | Stopped |

**Diagnostic, not a gate: `armed-v1diag`** (new bytes with only the version literal set to 1, one run at 1920, `output/gates-glc/g3-diag/`).
- It arms and goes LIVE, with `innerRect {4,4,952,268}`, `glErrors` 0 and **29.89 uploads/s** (interleaved `armed-oldbytes` 29.93/s, a 0 % drop).
- N1 reads max 0 at P2/P2b/P2c. N2 passes: B00–B03 match P2c, B04–B09 match P3.
- Every other `handoff_checks` row is green against the batch-1 control.
- So the version refusal is the only blocker seen, but this is not a qualification of any commit.

## Harness changes (copies only; the old dirs are untouched)
- `output/gl-replay-c-harness/g3/`: copies of g3h `common.py`, `analyse_g3.py` and `run_arms.sh`, plus `g3_flow.py` from
  `gates-g5g6/r1/p57` (g3h plus the `goto31` arm).
  - `g3_flow.py`: an arm whose name contains `-oldbytes` or `-v1diag` applies that splice before `provenance()`, and
    `res["splice"]` records it.
  - `g3_flow.py`: after P2c, every arm (control included) reads `stats()` twice `G3_RATE_S` = 3 s apart and records
    `res["rate"]` (uploads/s, iter/s). This adds 3 s before the late force and the burst in every arm.
  - `run_arms.sh`: an absolute `<root>` is used as is, so output goes to `output/gates-glc/…`.
  - `analyse_g3.py`: N1 is a gating row in `handoff_checks` and replaces `_report T-ring at P2c`. N2 is a row that gates
    only when N2 CvC passes. New `newChecks` holds the CvC and KB sections and lists every other red check on the KB arm.
    `uploadsPerS` is added per arm and `innerRect`/`rate` go into gate-2 `reportOnly`. Integrity now requires module sha
    `e3ae63f4…` (or `4f8850e0…` for `-oldbytes`) and a splice record that matches the arm name.
- `output/gl-replay-c-harness/splices/`: `splice.py` and `run_spliced.py` (a runpy wrapper for probe/P2, not yet used),
  plus the `d56fb0dd` G2 file.
- `output/gates-glc/run_gates_glc.sh` (an unchanged copy of `run_gates_g5g6.sh`) and `output/gl-replay-c-harness/rescore_p5.py`
  (a copy of `gates-g5g6/r3/offline/rescore.py`). Neither is used yet.

## Evidence
- `output/gates-glc/g3/`: control, control-2, control-lb, armed, armed-2, armed-lb, armed-oldbytes, plus `gates.json`
  (a partial scoring that includes `newChecks`, `uploadsPerS` and `*.log`). In it, gates 4/4b read FAIL only because the
  armed arms never armed, and gates 6/7 read INCONCLUSIVE because they were not run. Neither is a finding.
- `output/gates-glc/g3-diag/`: `armed-v1diag`, `armed-oldbytes`.
