# Texture identity (D2 image route): gate record

Branch `claude/texture-mm-image-graft` (from main `25849a82`, incl. #277). Plan `.agents/plans/keynote_export_texture_identity.plan.md` rev 4; owner: OQ-1–7 per rec (2026-10-14).

## Roster
- Plan: Codex GPT-6 Astra high (advisory + plan), critiqued by Opus 5.5 high r1–r3 (review log: plan §8; raw rounds pruned at merge).
- Implementation: Codex GPT-5.6 Sol high.
- Code review: Opus 5.5 high, two rounds (raw rounds pruned at merge; dispositions below).
  - r1: 1 medium and 8 low folded; 1 informational item not folded (it would add test rows beyond the approved set).
  - r2: r1 confirmed closed, no regressions; 4 low folded.

## Results (2026-10-14)
| Gate | Result |
|---|---|
| Targeted (`test_preview_textures.py`, `test_html_preview.py`) | 79 passed |
| G1 offline corpus (`scripts/texture_repair_check.py g1`; `g1-result.json`) | **PASS** |
| Full suite, Python 3.13.11 (worktree venv) | 10882 passed, 38 skipped, 1 xfailed |
| Full suite, Python 3.10.10 floor | 10882 passed, 38 skipped, 1 xfailed |
| G2 live prepare (F2 + Alpha_DSK), 2026-10-15, owner-run, cache outside every `output/` | Alpha_DSK **ready**: D4×1 repaired, slide 8. F2 **refused**: slide 4, a 33×135 *text* glyph of the per-character Twist & Scale build. Out of scope (text, no D1 identity); new issue. |
| G3 owner eye on the repaired F2 copy (stock + patched player) | **PASS for the repair**: correct Malaysia map in place of the squashed Asia map. Owner also saw two duplicate small maps after MM 3→4 in both players. A JSON diff shows the repair changed only the Malaysia leaf id, so this is a separate, pre-existing MM end-of-transition bug, tracked separately. |
| Re-export after the owner's deck edit (F2.key `6fea812c…`, export tree `a2c7fd9a…`) | Keynote collided **both** maps for real. The new route repaired both (D2, slide 3 pages 11 and 12; corr 0.996 / 0.985). G1 re-pinned to this export. |
| Re-export after the 2 % Asia-map edit, 2026-10-15 (F2.key `f99a68ef…`, export tree `c664279e…`) | Only the 357×235 map collides now (`DF3DB700`, slide 3 page 12): D2×1, corr 0.985. The page-11 pair no longer collides. G1 re-pinned: **PASS**, 29 rows, 0 failed, 0 inconclusive. |

G1 rows:
- **F2:** 1 hit → D2×1 → 0 hits.
- **F2/synthetic-357** (synthetic defect, real chain and donor): 2 hits → D2×2 → 0 hits.
- **Alpha_DSK fixture:** D1×1, D2×3, D3×1.
- **qual-decks:** D2 → D3×2; across-first-build → D3×1.
- **3b9019:** slide 10 still refuses, as before.
- **Every other export:** clean (0 hits).

The F2 rows are pinned by source and export-tree SHA-256. Skips are the usual Mac-, deck- and recording-dependent ones; the git-ignored fixtures are linked from the main checkout.
