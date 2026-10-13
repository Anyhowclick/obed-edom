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

## Next (owner: 2026-10-14)

1. **Send "need window" to the peer sessions first.** The CEF placement session runs long managed-OBS passes; its 2B is
   also moved to tomorrow.
2. **Full suites on the PR head**, in the worktree `.venv` (3.12) and `.venv310` (3.10 floor; both already synced):
   `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/ -n auto --dist worksteal -q -p no:cacheprovider`,
   then the same with `.venv310`. The last green run was 10807 passed on pre-rebase `4b5d16d7`.
3. **The full headless gate on the PR head.**
   - Use a read-only clone of the export: `cp -cR` both `html` and `manifest.json` from
     `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/output/.html-preview/7e3c930194d00effe3a21ee0e86a20baddb74223f661b9fa23186282aaf7081d-p3-r1/`
     into a scratch dir. The probe's resolver accepts any root.
   - Run: `PYTHONPATH=$PWD/src .venv/bin/python scripts/line_draw_probe.py <scratch>/html --manifest <scratch>/manifest.json --out <scratch>/gate`.
   - Expected (last run, pre-rebase `g4`/`g5`):
     - PASS: `on`, `hold-p1`, `hide-show`, `destroy`, `busy`.
     - Controls: `off` fails reveal; head-static fails hand-back.
     - Refused: diamond (diff 124) and protrusions (127).
     - INCONCLUSIVE: `neighbour`, because Chrome 155 gets no snap grant. Top-level `pass` is therefore false by design;
       read the per-arm verdicts.
   - Re-score offline with `--score <dir>`.
4. **Fold the results into the gate record and the PR checklist.** If a check reddens, compare against the pre-rebase
   behaviour before blaming #269. mm-fade touches only GL Magic Move leaf fades, and Line Draw is CSS.
5. **Optional review r3** (Opus 5.5 high, the reviewer's model class differs from Sol's) on the rebase resolution only.
   Round 3 still folds every severity; from round 4 only majors count.

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
