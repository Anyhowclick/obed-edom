# Pre-draw geometry gate record (2026-10-16)

Branch `claude/predraw-geometry` (local), from `claude/stage-b-arch` 7746df27. Plan: `.agents/plans/keynote_live_predraw_geometry.plan.md`. Step 0 and the owner tolerance decision: `step0-2026-10-16.md`.

## Rule
A pre-draw rider frame is exempt only when all of these hold:
- the existing bounds hold;
- every **visible** decoder sample in each zero-draw prefix frame is within **1 authored px** of the plan's authored `srcRect` on all four edges (owner, after Step 0);
- the time to the first completed GL draw of the context, `firstDrawAt − first move frame t`, is at most `PRE_DRAW_GRACE_MS`;
- no accepted stand-down happened at or before `firstDrawAt`.

One failed or unreadable prefix frame scores the whole visit. A missing `sourceRectError` or `firstDrawAt` is a contract refusal, and the carry then reads None.

`PRE_DRAW_GRACE_MS` stays **320 ms**: F4 41800609 is still not an ancestor. The fresh `preDrawMs` maximum is 264.5 ms (D7 b0to1), so the margin is 55.5 ms. `firstDrawAt` falls 0.1–1.7 ms after the old frame-`t` approximation.

## Process
- Plan: Codex GPT-6 Astra high. Critique: Opus 5.5 high (r1 NOT READY with 1 blocker and 3 majors; r2 NOT READY with 3 mediums; r3 READY). Critiques: `plan-critique-r{1,2,3}.md`.
- Owner: "step 0 check 1st, then the usual workflow". After Step 0, the owner chose 1 authored px.
- Implementation: Codex GPT-5.6 Sol high. Commits: 533f88d5 (Step 0), e9a3dd4b, 27aaaf9d (r1 fold), f9cdc159, 794dfe4c (control rework), 2966a19d (r3 fold).
- Review: Opus 5.5 high.
  - r1: 1 major (a weakened per-entry contract test, restored) and 6 lows, all folded.
  - r2: 1 low (indentation), folded by the coordinator. The coordinator also found that the moved-decoder test failed when run alone, because nothing put `scripts/` on `sys.path`. Fixed.
  - r3, on the reworked control: 1 medium. The translate was cleared only on the main hide path; it is now cleared wherever a pending departure hide is deleted. 1 low (plan wording), folded.
  - r4 (majors and blockers only): none.

## Red control rework (found in validation)
- **First design:** `startup-moved-decoder` reparented the decoder to `#body` with x+8 px. That escapes Keynote's source-layer hide at the first GL draw, so the decoder stayed visible through the first drawn frame. The 7746df27 scorer already caught it (old False, new False on every row), so it didn't isolate geometry.
- **Reworked (794dfe4c, 2966a19d):** an in-layer `translate: 8px 0`, cleared whenever the pending hide ends.
- **Proof that geometry alone separates it:** exactly the four motivating carries go from old True to new False, with offenders only in the two prefix frames. Every other carry keeps a hidden prefix and stays True.
- Superseded captures: `val/superseded-reparent/`, `val/superseded-794dfe4c/`.

## Validation captures (headless, one Chrome at a time, load 1.9–4.1)
Positives ran at f9cdc159; the instrument is unchanged after that commit. Each capture was re-scored with the 7746df27 scorer (`val/compare.py`); there are no contract errors in any artifact.

| Arm | Rider verdicts (new) | Old→new | Visible-prefix `sourceRectError` (authored px) |
|---|---|---|---|
| Alpha positive 1920 ×2, 2560 ×1 | all True, exempt True | identical | b5to6 0.781, b7to8-wa0121 0.686 (same at both viewports) |
| D7 positive 1920 ×2, 2560 ×1 | all True, exempt True | identical | b0to1 a/b ≤ 0.00006 |
| Alpha overlay-ride | all False | identical (exempt True→False) | 5–56, drawn-frame offenders continue |
| D7 departure-early-hide | all True, 0 exempted visible samples | identical | hidden |
| Alpha startup-moved-decoder (2966a19d) | b5to6, b7to8-wa0121 False; others True | True→False on those two | 8.62, 7.56 (prefix only) |
| D7 startup-moved-decoder (2966a19d) | b0to1 a/b False; others True | True→False on those two | 8.0 (prefix only) |

`labelsOverFeed` is True on every carry. The new aggregate check passes on both moved-decoder captures.

**Leaves outside this scope:**
- D7 `feedLive` is None on every carry, both here and in a 7746df27 baseline (D7 ×2, Alpha ×1, `val/base/`). It predates this work.
- One D7 b0to1-b `handbackContinuity` miss (pos-1920-2), and the Step 0 Alpha b7to8 `handbackContinuity`/`feedLive` miss at 533f88d5. Both are recorded timing variance (gate-record-2026-10-15); the baseline and the other runs are clean.

## Suites (2966a19d)
- 3.12: `uv run pytest tests/ -n auto --dist worksteal -rs`, **11233 passed, 88 skipped, 1 xfailed** (9:22). The skips are the worktree's sermon-outline fixtures and JXA/deck caches; none are in the changed test files.
- 3.10 floor: SUITE310
- Dashboard: DASHBOARD

## Not done / follow-ups
- Tighten `PRE_DRAW_GRACE_MS` after F4 lands, from completion-time (`firstDrawAt`) distributions.
- The geometry fold adds a few layout reads per entry per animation frame. That cost isn't in `callbackCostP95Ms`, and no observer effect showed up in these captures.
- Merging into `claude/stage-b-arch` goes through the Stage B coordinator.
