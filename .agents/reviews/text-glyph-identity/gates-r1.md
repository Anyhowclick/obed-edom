# Text-glyph identity (D1g): gate record

Branch `claude/suspicious-yalow-7eadf3`, cut from main `a70bbc0e`. Plan `.agents/plans/keynote_export_texture_text_identity.plan.md` rev 3. The owner chose the OQs on 2026-10-15 (plan §7).

## Roster
- Plan: Codex GPT-6 Astra high, then Opus 5.5 high critique, rounds 1–3. Review log in plan §8.
- Implementation: Codex GPT-5.6 Sol high. Round 1 implemented, round 2 simplified it to local style, round 3 folded the review.
- Code review: Opus 5.5 high.
  - r1: 2 medium and 5 low, all folded:
    - fail-closed `_glyph_twin` on unexpected JSON shapes;
    - G1 `PreviewStale` → INCONCLUSIVE;
    - a donor-id scan over every leaf;
    - style;
    - refusal params moved into the existing test;
    - a non-vacuous effect-leaf assertion;
    - the `F2Row` table.
  - r2: all folds confirmed, nothing new.
  - Mutation runs: each structural guard is killed by its own test.

## Reproducer (owner-approved Keynote use, 2026-10-15 14:50–14:52)
- I ran two serial `export_html` runs of the unchanged F2.key `f99a68ef…` into `~/Desktop/StageT-text-glyph-evidence/2026-10-15/attempt-0{1,2}`. Peers had a "need window" and a "done".
- **Export is nondeterministic.** The tree hashes `1c1291ef…` and `c6627004…` differ from each other and from `c664279e…`.
- attempt-01 collides the base **i** (33×135 on a 357×235 entry): this is the owner's G2 refusal.
- attempt-02 collides the base **s**.
- The effect twins keep their natural ids. Details are in `investigation.md`.

## Results
| Gate | Result |
|---|---|
| Targeted (`test_preview_textures.py` + `test_html_preview.py`) | 86 passed |
| G1 (`scripts/texture_repair_check.py g1`) | **PASS** on the merged tree (main `6cf7da26` merged in). Every row passes. `preview/3b9019` and `preview/59cb` had been reported missing before the merge; #286 had moved them to `Continuity/stage-t-exports`. |
| Full suite, Python 3.13.11 (worktree venv), commit `9847eb30` | 11003 passed, 38 skipped, 1 xfailed |
| Full suite, Python 3.10.10 floor | 11003 passed, 38 skipped, 1 xfailed |
| Dashboard `test:ui` / `test:maps` | 330 passed (44 files) / 542 + 2 passed |
| G2 live F2 prepare (owner) | pending |
| G3 owner eye | **PASS (owner, 2026-10-15): the repaired copies are correct.** Chrome via a local server, stock player. Repaired copies `~/Desktop/StageT-text-glyph-evidence/2026-10-15/attempt-0{1,2}-repaired` (trees `ea5a63b6…`, `5d63e95e…`; 0 hits after) beside the unrepaired `attempt-0{1,2}` controls. Check all eight Malaysia letters through the Twist & Scale build and the settled slide (i in 01, s in 02), and the 176×205 map. |

G1 rows:

| Row | Before | Outcome | After |
|---|---|---|---|
| F2 (`c664279e`) | 1 hit | D2×1 | 0 hits |
| F2/attempt-01 (`1c1291ef`) | 2 hits | D1g×1 (base i → `9C60C2B5`) + D2×1 | 0 hits |
| F2/attempt-02 (`c6627004`) | 2 hits | D1g×1 (base s → `A7274F8D`) + D2×1 | 0 hits |
| F2/synthetic-glyph-i-both | 3 hits | refused with "slide 4 (33×135 text) …" | tree unchanged |
| Alpha_DSK fixture | — | D1×1, D2×3, D3×1 | — |
| qual-decks | — | D3×2; across-first-build D3×1 | — |
| Every other fixture | — | clean | — |
