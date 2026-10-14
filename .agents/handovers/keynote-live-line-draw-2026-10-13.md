# Line Draw draws along its path: handover (2026-10-13)

**PR [#270](https://github.com/Anyhowclick/obed-edom/pull/270), open, branch `claude/keynote-live-line-draw`.** Do not merge
without the owner. Plan `.agents/plans/keynote_live_line_draw.plan.md` rev 6 (owner decisions in §4). Gate record
`.agents/reviews/line-draw/gates-r1.md`. Contract: SKILL.md "Line Draw builds".

## State

- **The dissolve report (Stage T G4) is closed with no fix.** Alpha_DSK's non-MM changes 1→2, 2→3 and 3→4 are authored
  `none`, and the owner confirmed the deck was never set to dissolve. The real Dissolves (5→6, 10→11, 11→end) pass
  `__obedShape`.
- **Slide 2's Line Draw now draws on Chrome and on the managed OBS Keyer.** The owner eyeballed both: "looks correct" and
  "looks good". Box: Clockwise, 0.8 s. Arrow: Start to End, Include endpoints, 0.7 s, head riding the tip.
- **The branch is one feature commit plus the gate record, rebased on main after #269 (mm-fade).** The rebase resolved
  conflicts in the replacement tuple, the pins and the anchor tests. Combined order:
  - opacity 0–4;
  - hand-back 5–7;
  - dissolve 8–11;
  - mm-fade 12;
  - Line Draw 13–18 (`LINE_DRAW = slice(13, 19)`).

  On/rendering pins were recomputed and the off pins are unchanged. `test_live_runtime.py` passes 176/176.
- **The pre-squash history is on the local branch `backup/line-draw-pre-squash` (`4b5d16d7`).** Delete it once #270
  merges.

## Done 2026-10-14

- Both suites on the rebased head: 10813 passed, 0 failed (3.12 and the 3.10 floor).
- Full headless gate (`g6`): green apart from `neighbour`, which is INCONCLUSIVE because Chrome 155 gets no snap
  grant.
- `hold-p1` reveal timing was flaky because the probe's capture-to-animation clock mapping lands one frame differently
  from run to run. The owner made it report-only; the arm now gates only the held composite. See the gate record.

## Open

- **Owner review and merge of #270.** Only the owner merges.
- **Optional:** the owner compares slide 2 against Keynote's native playback.
- **Optional follow-up:** stamp each captured frame with the page's animation time instead of mapping capture
  timestamps. That would make the reveal-timing checks deterministic.
- After merge, delete the local branch `backup/line-draw-pre-squash`.

## Lessons (also in memory `line-draw`)

- **Keynote's HTML export degrades builds.** Line Draw ships as an opacity fade while keeping `shapePath`. Check the
  exported effect before blaming a player patch.
- **Engines rasterise PDF textures differently.** Chrome 155 measured the head diff at 31 and CEF 127 at 39. Calibrate
  pixel bars on every qualified engine: a Chrome-only bar of 38 made the Keyer fade the arrow.
- **Implementer JS ran in the player's module scope.** Undeclared assignments hit a player `const`, and setup silently
  fell back to the fade. A per-function lexical test now guards this.
- **Check that a pixel instrument can measure at its capture scale before gating on it.** At headless 1512 px the arrow
  pose check could not separate a 2 px / 3° offset, so the owner chose an eye gate.
- **CEF drops key input just after attach.** Retry `goTo` after a settle; the second host attach in one OBS session
  failed without it.
- **The Keyer screenshot driver was scratch-only.** It is a ~50-line wrapper over `managed_obs_qualify`'s `launch_engine`,
  `source_shots` and `unpremultiply`, run with the scratch `DEFAULT_HOME` and quit clean. Re-create it if the Keyer needs
  re-checking.
