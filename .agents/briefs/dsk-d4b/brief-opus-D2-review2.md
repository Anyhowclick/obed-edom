# Review brief: d4b piece D2 (run-aware estimator + live measure-then-refit), fix round 2

Worktree: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen (branch feat/dsk-gen). Read-only review: you may run tests and write probe scripts ONLY under the scratchpad dir given in your prompt; do not edit repo files, do not touch Keynote / osascript, do not commit.
Tests: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider` from the worktree.

Scope = everything since 9b486a8 on the branch (`git diff 9b486a8 -- src tests`) plus the uncommitted working tree. Rule of record: .agents/plans/dsk_pieceD.plan.md (Design B, steps 1,5,6,7). Prior review: .agents/reviews/dsk-d4b/opus-D2-review1.md (F1–F15) — verify each finding is resolved or explicitly deferred; the implementer's report is at <scratchpad>/report-D2-finish.md.
Live facts you must reason against (measured on out-r9b): GW 13 text:1 live 269 vs run-aware 273.7; GW 17 text:1 186 vs 153.7; GW 17 text:2 189 vs 166.6; GW 28 text:1 349 vs 382.0; badge rows on GW 17/28 sit 8–12pt above the stack top.

Check especially: (1) correction arithmetic across TWO rounds with real numbers — simulate with a probe, not by reading; (2) badge/short row re-stack on refit and its emitted writes; (3) staged addressing in build_refit_script; (4) shrink path = measured-fit size, runs preserved, floor only when clamped, overflows cleared only for keys that came back under budget; (5) HIDDEN parse reaches AssembleResult; (6) MEASURE2 probe and its parse; (7) house style (no plan/review bookkeeping words, minimal docstrings, no inline comments); (8) tests actually exercise the fixes (not tautological).
Verdict format: APPROVE / APPROVE-WITH-NITS / REVISE, then numbered findings with file:line, severity, and the concrete fix. Write the review to the scratchpad path named in your prompt and return it as your final message.
