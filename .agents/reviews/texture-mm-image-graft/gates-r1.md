# Texture identity (D2 image route): gate record

Branch `claude/texture-mm-image-graft` (from main `25849a82`, incl. #277). Plan `.agents/plans/keynote_export_texture_identity.plan.md` rev 4; owner: OQ-1–7 per rec (2026-10-14).

## Roster
- Plan: Codex GPT-6 Astra high (advisory + plan), critiqued by Opus 5.5 high r1–r3 (`plan-critique-r*.md`).
- Implementation: Codex GPT-5.6 Sol high.
- Code review: Opus 5.5 high, two rounds.
  - r1 (`code-review-r1.md`): 1 medium and 8 low folded; 1 informational item not folded (it would add test rows beyond the approved set).
  - r2 (`code-review-r2.md`): r1 confirmed closed, no regressions; 4 low folded.

## Results (2026-10-14)
| Gate | Result |
|---|---|
| Targeted (`test_preview_textures.py`, `test_html_preview.py`) | 79 passed |
| G1 offline corpus (`scripts/texture_repair_check.py g1`; `g1-result.json`) | **PASS** |
| Full suite, Python 3.13.11 (worktree venv) | 10882 passed, 38 skipped, 1 xfailed |
| Full suite, Python 3.10.10 floor | 10882 passed, 38 skipped, 1 xfailed |
| G2 live prepare (F2 + Alpha_DSK) | pending (Keynote, owner-run) |
| G3 owner eye on repaired F2 copy | pending |

G1 rows:
- **F2:** 1 hit → D2×1 → 0 hits.
- **F2/synthetic-357** (synthetic defect, real chain and donor): 2 hits → D2×2 → 0 hits.
- **Alpha_DSK fixture:** D1×1, D2×3, D3×1.
- **qual-decks:** D2 → D3×2; across-first-build → D3×1.
- **3b9019:** slide 10 still refuses, as before.
- **Every other export:** clean (0 hits).

The F2 rows are pinned by source and export-tree SHA-256. Skips are the usual Mac-, deck- and recording-dependent ones; the git-ignored fixtures are linked from the main checkout.
