# Handover — pass-1 hides offline, resume (2026-09-24)

Supersedes `pass1-hides-offline-2026-09-23.md` for this work. Plan and single source of truth:
`.agents/plans/pass1_hides_offline.plan.md`. Read its §Owner decisions 1–5c and §Review log first.

## Where things stand

- **Branch:** `claude/pass1-hides-offline`. It is local and unpushed, based on origin/main 5b3b55e8. Its worktree is
  `.claude/worktrees/pass1-hides-offline-review-0930ce`.
  - Before pushing or opening a PR, merge `origin/main` and rerun the suites.
- **Built:**
  - Writer: `src/obed_edom/iwa_hides.py`.
  - Wiring and the AppleScript fallback: `offline_write.py` and `remap_keynote.py`.
  - JS deferral: `remap_keynote.js`.
  - Comparison checker: `scripts/deck_decode_diff.py`.
  - Dashboard abort UX: `web/app.py`, `ResizeTab.tsx`, `HistoryTab.tsx`, `api.ts`.
  - `needsKeynote`, `maskGeom` and `maskedDescendant` on offline payload items: `offline_inspect.py`.
- **Flag:** `OBED_OFFLINE_HIDES` defaults to off. It flips to on only after a GREEN live gate (owner decision 2, todo `g-flip-docs`).
- **Offline evidence (round 6, fcefaa68^):**
  - FRC dry run: 129 slides, 929 hides, 0 refused, verify passes, 44 orphan `Data/` dropped.
  - Slides 20 (twin risk) and 122 (builds) are excluded before deferral and stay on the Keynote delete.
  - Stage time: 24.4 s at load average ~5; 37.6 s at load ~35, which is not comparable. Re-time on a quiet machine.
  - `planSha256` is unchanged.
- **Suites at HEAD:** pytest 6455 passed, 86 skipped, 1 xfailed; node tests ok; test:ui 248; test:maps 542 + 2; tsc clean.
- **Round 7 (Sol S6 fixes) is committed but not dry-run.** The FRC figures above are from round 6. Round 7 added a refusal for a
  header reference with no decoded body counterpart. That rule is unmeasured on real decks and could refuse real hides, and under
  decision 4 a post-save refusal aborts the run.

## Review state

- **Rounds so far:** C1 (Sol), A1 (Astra H advisory), A2 and A3 (Astra H), S4, S5 and S6 (Sol H).
  - S6's 3 majors are fixed in round 7 (fcefaa68) but not yet re-reviewed. Everything earlier is closed.
  - The owner switched the reviewer back to **GPT-5.6 Sol, high effort**:
    `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s read-only -o out.md "$(cat p.md)" < /dev/null`.
- **Raw rounds:**
  - They live in the worktree's git-ignored `output/pass1-hides-offline-review/`: `*.prompt.md` and the outputs.
  - Pass the previous rounds to each new round so it can classify findings and check that fixes closed.
  - Delete them once the item lands; the plan's review log is the durable record.
- **Stopping rule:** the owner hasn't set one. The coordinator's rule has been to continue until Sol returns no BLOCKER or MAJOR.

## Next steps

Status 2026-09-24: **DONE and ready for review.** The live gate is GREEN (record
`.agents/reviews/pass1-hides-offline-2026-09-24/README.md`), owner decisions 1–7 are in the plan, `OBED_OFFLINE_HIDES` defaults to
on, and one integration PR is open. Never merge it.

- After merge: delete the raw review rounds in this worktree's git-ignored `output/pass1-hides-offline-review/` (owner rule), then
  remove the worktrees `pass1-hides-offline-review-0930ce`, `pass1-hides-live-c37d924a` and `pass1-hides-gate-A`.
- Follow-up (separate plan): `followup-mm-leftovers`. The planner's off-slide-leftover rule deletes Magic Move partners;
  this is pre-existing on main.

## Implementer roster used

- Planners: both Opus at extra-high (the new default).
- Implementers: Opus at medium effort, split by disjoint files:
  - A: the checker.
  - B: the writer, plus `offline_inspect.py`.
  - C: the JS.
  - D: the wiring.
  - E: the dashboard.
- Resume these peers by name if they are still live. Otherwise brief fresh ones from the plan.
