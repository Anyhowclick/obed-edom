# C3 review r7 (2026-10-16) — major/blocker only

Diff: `1a421de2..d9ec04df` (r6 fold). Reviewer: one Opus 5.5 high lens, acceptance plus mutation. All findings executed
(`/private/tmp/claude-501/c3-review/r7/`). Suites (single process): paint 159, contract 133, probe 1911, all passing.

**Code: no defect.**
- The r6 fold is safe: only the never-decoded guard changes; results move from None to OLD-equivalent or stricter.
- The r6 battery's only changes are the r6 targets, back to OLD False.
- Every OLD≠NEW is in classes (a)–(e).
- Real captures show 0 changes vs r6; OLD≠NEW there is the 4 D7 b1to2 changes plus the 2 Alpha C1 changes, all class (b).
- Mutants: 11 of 12 on the new clause killed; the survivor is effectively equivalent.

| # | Sev | Finding | Fold |
|---|---|---|---|
| M1 | major (test gap; r4 F3 class) | Mutant `shared = None` on the no-common branch passes every test. On real captures it flips D7-null b2to3 (both counters) False → None | One pinning row "gl-after-only-decoder" (test only; the mutant must fail) |

The fold is test-only, so the coordinator verifies it by re-running the mutant rather than with another review round.
