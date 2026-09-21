# Verdict: FAIL

## BLOCKER

None.

## MAJOR

1. [scripts/p2_recovery_html_adversarial.py:2970](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2970>) — The page-side collector is not fail-closed on a partial or truncated dump. `_collector_rows_for` extrapolates the first/last available row when a sample lies outside the dump, while missing owner/media fields are tolerated downstream. A dump omitting an interval containing a decoder handoff or rVFC rewind can assign neighboring healthy evidence to those captures; sufficient later rows can still satisfy continuity in both the bracket and main 3→4 finding.

   Smallest sound fix: return collector metadata including first/last timestamps, row count, dropped rows, and errors; validate monotonic timestamps and required schemas; require every sampled badge time to be genuinely bracketed. Gate that validation in all three bracket arms and `advance_c_ok`. Do not extrapolate endpoints.

2. [scripts/p2_recovery_html_adversarial.py:3352](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3352>) — The press-relative cut still fails open when its timestamp is missing or later than every badge frame. `_at_cut_from_perf` returns `None`, but `_moving_index_run_at_cut` interprets `covered_from=None` as index zero at [line 3386](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3386>). No all-arms integrity key requires a finite `advanceKeyPerfMs` and valid in-range `atCutFrom`. With the real schedule beginning at sample zero, positive arms can remain green and the bracket can PASS without the claimed clock boundary.

   Smallest sound fix: distinguish “invalid cut boundary” from legitimate index `0`; require finite page-clock timestamps and an in-range `atCutFrom` in A1/B/A2 and MAIN before scoring.

## MINOR

1. [.agents/plans/p2_freeze_control_3to4.plan.md:223](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/.agents/plans/p2_freeze_control_3to4.plan.md:223>) — §10.8 still documents `advancePressIndex + 1`, contradicting the page-clock implementation and the observed `atCutFrom == 0`. The section title also says rounds 4–7 despite round-8 data, and line 263 mentions only two load batches rather than the supplied three.

   Smallest sound fix: rewrite §10.8 around `_at_cut_from_perf`, update the section title and recorded batch loads.

2. [scripts/p2_recovery_html_adversarial.py:2874](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:2874>) — The round-5 minimal-comment finding remains open. Production comments still embed review IDs, deleted-implementation history, measurements, and lengthy failure narratives already recorded in plan §10.

   Smallest sound fix: retain concise behavioral invariants and one plan reference; remove review-history commentary.

3. [.agents/plans/keynote-alpha.md:20](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/.agents/plans/keynote-alpha.md:20>) — The operator index does document the required `--reuse-export --disposable --wait-profile fast|slow` invocation. It does not explain that original HEVC is unsuitable for the headless gate or warn that omitting `--reuse-export` deletes the entire output directory at [script line 4630](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4630>).

   Smallest sound fix: add one explicit warning beside the documented invocation.

Checked without finding: `rehandoffPairSound` rejects wrong runtime generations under the current implementation; a generation bump creates a new `started`, while trigger identity separately checks generation and scene. `ownerSettledAllArms` now fails closed for every arm. Constants `9`, `190 ms`, and `100 ms` match code and the recalibration arithmetic.