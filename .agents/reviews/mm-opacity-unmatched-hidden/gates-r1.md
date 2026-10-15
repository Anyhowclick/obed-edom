# Gate record r1: MM never-visible leaves (absorbing proved zero)

**Date:** 2026-10-15. **Branch:** `claude/mm-dup-fix`. **Plan:** `keynote_live_mm_opacity_unmatched_hidden.plan.md` rev 2, approved by the owner.

**Roles:**

| Role | Who | Note |
|---|---|---|
| Planner | GPT-6 Astra | |
| Plan critique | Opus 5.5 high | 2 rounds, closed |
| Implementer | Codex GPT-5.6 Sol high | `ab58fdd6`, plus the UH-1 driver |
| Code review | Opus 5.5 high | r1: approved after 3 lows (`code-review-r1.md`) |
| Coordinator (Opus) | | See below |

The coordinator's edits were mechanical:
- folded the r1 lows;
- re-pinned `scripts/detach_experiment.py` `SERVED_SHA256`/`L2_SERVED_SHA256` for the on variants only, after the full suite caught them (`91a6f6b4`; off unchanged);
- made three instrument fixes to the UH-1 driver (WebGL accessor read, preview-cache location, `UC` exposure splice) and gave the static arms a first-navigation hash.

## Results

| Gate | Result |
|---|---|
| UH-0 methods and pins | **PASS** (see details below) |
| UH-1 headless F2 3→4 (`uh1/`, run `20261015-112435`) | **PASS**, 7/7 arms and every cross-check (see details below) |
| UH-2 existing regressions (`uh2-mo.log`, `uh2-hb.log`) | **PASS** (see details below) |
| UH-3 Stage B composition | **Not run here.** Stage B (`claude/stage-b-implementation`, unpushed) lands second. Per plan §5 it rebases, recomputes all six pins plus the detach-experiment served SHAs, and re-runs UH-0, the UH-1 candidate arm with continuity on, and the full suites. Main's own continuity-on path is exercised by the owner-eye step. |
| UH-4 owner eye, old F2 3→4 | **PASS (owner, 2026-10-15).** Old F2 export, texture-repaired data, Chrome via a local server: stock player shows the two small duplicate maps after 3→4; fixed (`patch_rendering`, `ecff39e1…`) does not; Malaysia map and slide-4 build correct. A first pair built from the raw (unrepaired) export showed the Asia texture on slide 4's Malaysia leaf: that is #280's texture collision, not this fix. The live path was covered headlessly in UH-1. |
| Full suites on the merged tree (main `6914e169` + branch) | **PASS** (see details below) |

### UH-0 methods and pins
- `test_live_runtime.py`: 171 passed.
- On/rendering pins recomputed for both players; off byte-identical.
- Mutation checks (reviewer): reverting the JS or mirror line fails the new tests.
- Offline changed set (`uh0_changed_set.json`, base `e476ea74`): exactly old F2 `(f2350147…, 7)` and `(f2350147…, 8)` change, out of 29 distinct effects and 145 leaves. The 26-effect fixture corpus and the owner's current F2 are unchanged.

### UH-1 headless F2 3→4
Setup:
- Player B; 1920×1080; DPR 1; real GPU.
- Continuity and GL replay off.
- Automatic slide-4 build timing kept.
- Arms: stock, base (`e476ea74`) preview/live, candidate preview/live, and a candidate repeat of each.

Measurements:
- **Known-bad arms (stock and base, preview and live):**
  - slots 7/8 drawn at Opacity 1 in 62–73 draws each; per-draw ROI contribution L1 ≈ 0.42 M / 0.70 M;
  - their hold captures still contain the artifact. Hold vs candidate L1 equals the terminal contribution: 396 459 / 664 026.
- **Candidate and repeat arms (preview and live):** Opacity 0 in every draw. The ROI before/after each draw is exactly equal.
- **Hold (Dlast→R):** 264–282 ms for the patched players and 591 ms for stock.
  - No GL calls inside the hold.
  - At least one capture strictly inside the hold.
  - Candidate hold ROI equals its own terminal readback exactly (max 0).
  - Candidate vs repeat noise is 0.
- **Siblings 1/10/11** contribute in every arm.
- **Build onset** comes after canvas removal.

### UH-2 existing regressions
- `mm_opacity_probe`: MO-1, MO-4, MO-5 and MO-4 stand-down PASS under GL auto; MO-1 and MO-5 PASS under GL off.
- `mm_handback_probe`: HB-1 PASS at 1920, 2560 and 1600 (on 0.0 / 0.018 / 0.005 vs known-bad off 2.8 / 3.7 / 2.4); HB-2 PASS.
- PF (Alpha_DSK fades): covered offline. The changed-set census and the extracted-method fixture tests show no change to the 6→7 slot 3 and 7→8 slots 4/8 leaves (their product is 0.6118, not 0), so the PF scratch driver was not re-run.

### Full suites
- Python 3.13.11: 10996 passed, 38 skipped, 1 xfailed.
- Python 3.10.10: same counts.
- Dashboard `test:ui`: 330 passed.
- Dashboard `test:maps`: 542 + 2 passed.

## Evidence

All of it is outside every `output/`:
- Raw runs: in the session scratchpad.
- The UH-1 driver and the trimmed result: under `uh1/`.
- Source export: `~/Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/F2-html-old-stock`, read-only and copied per arm.
