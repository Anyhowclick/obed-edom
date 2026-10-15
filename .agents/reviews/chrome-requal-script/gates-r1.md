# Gate record r1: one-command Chrome-major re-qualification (`scripts/chrome_requal.py`)

**Date:** 2026-10-15. **Landed:** PR #287 (`d8e8b066`).

**Roles:**
- Plan: Codex GPT-6 Astra high. Critique: Opus 5.5 high, 2 rounds (r1: 13 findings folded; r2: no blocker/major, 3 folded). Plan rev 2, retired after merge; the design lives in the script, dissolve plan §13 and SKILL. Resolved in critique: no env var (a scoped `mock.patch.object` instead), 28 arms not 62, fixtures from `main_checkout()`, no identity launch (plist version before and after plus each arm's recorded product; `m-raw` records none and is excluded), resume on `record.json`, the bar as script constants.
- Owner: approved rev 2 with the 28-arm default (DPR 1.5/2 and raw/preview-prod stay in full DX-1).
- Implementation: Codex GPT-5.6 Sol high. Review: Opus 5.5 high. r1 asked for changes (2 medium, 4 low), all folded. r2 approved, and its 2 lows were folded by the coordinator.

**Test baseline:** #285 pruned #284's `dx1-verdict.json`. The positive control of `tests/test_chrome_requal.py` is now this run's `verdict.json` (34 KB), committed as `tests/fixtures/chrome_requal/verdict-155.0.8059.79.json`.

## Acceptance run on Chrome 155.0.8059.79 (installed Stable)

**Command:**
`.venv/bin/python scripts/chrome_requal.py --chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --out ~/.cache/obed-edom/chrome-requal-155.0.8059.79-r1`

**Conditions:** headless, AC power, default decision record (sha256 pinned).

**Timeline:**
- **First attempt, 15:08:** captured 6 arms in 724 s, then refused `noblend` (exit 2). A peer session's pytest started inside the window, and the pre-review `wait_idle` refused at the 300 s timeout.
- **Resume, 16:42:** skipped the 6 saved arms and captured the other 22. Capture plus scoring took 430 s on an idle machine (load ≈ 1.7).
- Twenty-eight arms on an idle machine should take about 9 min.

**Output:**
```
PASS
QUALIFIED_SNAP_MAJORS = (154, 155)
Chrome 155 is already qualified
```

**Readings** (`verdict.json` sha256 `c1b6a697…316dd3`, committed as the test fixture above; the 240 MB of runs were trashed after merge):
- **Gates:** handoff, frozen_frame, frozen_region, cost, grant and cvc PASS. Model, complement, no_dip, curve and monotone are also PASS.
- **Core arms:** all 14 MATCH (grant-chrome, grant-attach, channel-predefined, life-grant-reload, opaque-off, off, noblend, on, on2, m-paused, m-off, m-on, m-hold, m-raw).
- **DPR-1 cells:**
  - `m-snap`, clipx, clipy, lbfrac, lbfrac-clipx and lbfrac-clipy: reference, mask and geometry PASS.
  - `m-snap-shift`: reference and mask PASS. It has no geometry check.
  - Every cell has empty problems. `holder_pixels` is INCONCLUSIVE only for "no L_path for the arm's compositing path".
- **Product:** every non-raw arm recorded `HeadlessChrome/155.0.8059.79`, and the plist version was the same before and after the run.
- **Overall DX-1:** INCONCLUSIVE by construction. Aggregate checks whose controls are not in the 28-arm list stay INCONCLUSIVE, as on #284.

**Re-run check:** a second identical invocation printed `skipped` for all 28 arms, re-scored PASS, and exited 0 in 64 s.

**Correction:** `chrome155-requal/gates-r1.md` listed shift with geometry and omitted lbfrac-clipy; fixed in place.

## Full suites

Run on the pre-merge tree `9bc19f01`/`ef597451`, before main (#285/#286) was merged in. The worktree had the main checkout's `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx` symlinked.
- **Python 3.13.11:** 11010 passed, 38 skipped, 1 xfailed, 0 failed (262 s).
- **Python 3.10.10 floor:** 11010 passed, 38 skipped, 1 xfailed, 0 failed (328 s).
- **Dashboard:** `test:ui` 330 passed; `test:maps` 542 + 2 passed, 0 failed.

## Pending

- Full suites on the merged tree: skipped by the owner (2026-10-15, "Skip the merged-tree re-run; the merge only changed a path constant."). `tests/test_chrome_requal.py` passes 13/13 on the merged tree.

- None for this PR. Each new major goes in a release PR: the printed `QUALIFIED_SNAP_MAJORS` line plus a short gate record pasting the script's output.
- Chrome Beta is not installed on this Mac, so the `--chrome` Beta path was not exercised. The binary is routed through `d.CHROME` and the host's `chrome_path`, as reviewed.
