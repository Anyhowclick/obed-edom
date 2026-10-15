# Gate record r1: re-qualify the snapped freeze placement on Chrome 155

**Date and owner decision:** 2026-10-15, "Requalify chrome 155".

**Branch:** `claude/chrome155-requal`.
- Code commit: `9056168c`, by Codex GPT-5.6 Sol high. It sets `QUALIFIED_SNAP_MAJORS = (154, 155)` and updates the grant matrix test: 155 is granted, 156 refused.
- Review: Opus 5.5 high, r1. Approved, with no blocker or major findings.
  - Doc folds in `31191d76`: SKILL, README, the plan amendment and the handovers.
  - Plan rule (dissolve plan §13): add a major "after an `m-snap` run".

**Why:** this Mac's Chrome auto-updated to 155.0.8059.40 (2026-10-13) and then .79 (2026-10-14). The host refused the grant with `unqualified-version`, so every live Dissolve fell back to the stock frame-0 jump.
- Confirmed headlessly on the live path with F2 7→8: no take holders, and onset MAE vs frame 0 was 1.3 (vs 20.2 against the last pre-advance frame).

## DX-1 on Chrome 155.0.8059.79

**Run conditions:**
- Headless, ANGLE Metal GPU, AC power, Low Power Mode off.
- Pinned worktree at `9056168c`, using the handover recipe (`dx1_paced.py`).
- Decision record `q0b-2026-10-11/runs/decision_record_q0b1.json`. It was measured on 154 and is reused here: tuple engagement is gated, and tone stays identity.

**Arms run:** the recipe's 16 arms plus the 46-arm `m-snap` matrix (with twins). Scored with `dissolve_probe.py --score` (`dx1-score.log`, `dx1-verdict.json`).

**Results:**
- **PASS:** handoff, frozen_frame, frozen_region, cost, grant, cvc.
- **Arms that MATCH:** grant-chrome, grant-attach, channel-predefined, life-grant-reload, on, on2, off, opaque-off, noblend, m-on, m-paused, m-off, m-hold, m-raw.
- **`m-snap` at DPR 1** (base, clip-x, clip-y, letterbox-frac, letterbox-frac clip-x, shift): reference PASS (interior 0.0, edge 0.0), mask PASS, geometry PASS. The snapped holder lands exactly on the live movie paint on 155.
- **`holder_pixels`: INCONCLUSIVE in every arm.** No decision record anywhere carries an `lPath` (W5 never qualified one), so this check cannot score in any DX-1. The same was true at #262's merge.
- **DPR 1.5 / 2 cells: INCONCLUSIVE.** The headless window opens at 1920×993, a known harness limit that was INCONCLUSIVE at #262's merge too.
- **Other INCONCLUSIVE checks:** screen, cut, foreground, tone, overlay, exterior, hidden, shown, scope and lifecycle. Their controls were not in this run list, and they are outside the freeze-qualification scope, as at merge.
- **Not re-run:** DX-2 (managed OBS). It uses CEF 127 with its own `frac` qualification and no Chrome version gate.
- **Tone:** not compared. `m-tone` is not in this list, and tone is REPORTED-only under identity L.

**Verdict:** Chrome 155 meets the same written bar as 154 did at #262's merge, the `m-snap` run plus `grant-chrome`. On `reference` it is stronger: it was INCONCLUSIVE at merge and is PASS here.

**Pending:**
- Full suites.
- Owner eye on a live (headed) Dissolve 7→8 with the host log showing `placement.reason == "granted"`. This covers the review's headed-Chrome check.
