# Gate record r1: one-command Chrome-major re-qualification (`scripts/chrome_requal.py`)

**Date:** 2026-10-15. **Branch:** `claude/exciting-vaughan-75bbe4` (on top of #284 `claude/chrome155-requal`).

**Roles:**
- Plan: Codex GPT-6 Astra high. Critique: Opus 5.5 high, 2 rounds (r1: 13 findings folded; r2: no blocker/major, 3 folded). Plan `.agents/plans/chrome_requal.plan.md` rev 2.
- Owner: approved rev 2 with the 28-arm default (DPR 1.5/2 and raw/preview-prod stay in full DX-1).
- Implementation: Codex GPT-5.6 Sol high. Review: Opus 5.5 high. r1 asked for changes (2 medium, 4 low), all folded. r2 approved, and its 2 lows were folded by the coordinator.

**Kept file:** `.agents/reviews/chrome155-requal/dx1-verdict.json` is the positive control of `tests/test_chrome_requal.py`. Do not delete it in review-artifact cleanup.

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

**Readings** (`verdict.json` sha256 `c1b6a697…316dd3`, kept in the out dir with the 240 MB of runs, not committed):
- **Gates:** handoff, frozen_frame, frozen_region, cost, grant and cvc PASS. Model, complement, no_dip, curve and monotone are also PASS.
- **Core arms:** all 14 MATCH (grant-chrome, grant-attach, channel-predefined, life-grant-reload, opaque-off, off, noblend, on, on2, m-paused, m-off, m-on, m-hold, m-raw).
- **DPR-1 cells:**
  - `m-snap`, clipx, clipy, lbfrac, lbfrac-clipx and lbfrac-clipy: reference, mask and geometry PASS.
  - `m-snap-shift`: reference and mask PASS. It has no geometry check.
  - Every cell has empty problems. `holder_pixels` is INCONCLUSIVE only for "no L_path for the arm's compositing path".
- **Product:** every non-raw arm recorded `HeadlessChrome/155.0.8059.79`, and the plist version was the same before and after the run.
- **Overall DX-1:** INCONCLUSIVE by construction. Aggregate checks whose controls are not in the 28-arm list stay INCONCLUSIVE, as on #284.

**Re-run check:** a second identical invocation printed `skipped` for all 28 arms, re-scored PASS, and exited 0 in 64 s.

**Correction to `chrome155-requal/gates-r1.md`:** its `m-snap` DPR-1 list should read "base, clipx, clipy, lbfrac, lbfrac-clipx, lbfrac-clipy (reference, mask, geometry) and shift (reference, mask; no geometry check)".

## Full suites

Run on `9bc19f01`/`ef597451` plus the gate record. The worktree had the main checkout's `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx` symlinked.
- **Python 3.13.11:** 11010 passed, 38 skipped, 1 xfailed, 0 failed (262 s).
- **Python 3.10.10 floor:** 11010 passed, 38 skipped, 1 xfailed, 0 failed (328 s).
- **Dashboard:** `test:ui` 330 passed; `test:maps` 542 + 2 passed, 0 failed.

## Pending

- None for this PR. Each new major goes in a release PR: the printed `QUALIFIED_SNAP_MAJORS` line plus a short gate record pasting the script's output.
- Chrome Beta is not installed on this Mac, so the `--chrome` Beta path was not exercised. The binary is routed through `d.CHROME` and the host's `chrome_path`, as reviewed.
