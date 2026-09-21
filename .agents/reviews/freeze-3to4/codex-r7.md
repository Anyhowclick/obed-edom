Verdict: `FAIL`

## BLOCKER

None.

## MAJOR

1. [scripts/p2_recovery_html_adversarial.py:3717](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3717), [scripts/p2_recovery_html_adversarial.py:4235](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:4235), [tests/test_p2_adversarial.py:1603](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/tests/test_p2_adversarial.py:1603) — `collectorSeriesSound` does not require each capture’s own timestamp to be bracketed. Production replaces `None` badge timestamps with neighboring timestamps, while the freeze scorer omits those captures from `covered_positions`. A post-cover/pre-flip screenshot with a missing, torn, or unlogged badge can therefore show a live counter or wrong ROI, borrow another frame’s collector evidence, leave `unbracketed == 0`, and disappear from `allInHoldMeasured`/`everyInHoldStale`; later frozen flip-plus-six frames can still produce PASS. The same substitution permits a collector that started late or ended early to keep MAIN’s `advanceOk` true and finding 13 green when the uncovered endpoint has no badge timestamp. Smallest sound fix: use raw `perfNowMs` for collector integrity, count every `None` as unbracketed, and require zero missing/CRC-bad/unlogged/sequence-invalid badge samples in every arm, except the exact identified re-handoff pair. Add a regression using the production `_nearest_sample_times` path.

2. [scripts/p2_recovery_html_adversarial.py:3569](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/scripts/p2_recovery_html_adversarial.py:3569) — `advanceKeyPerfMs` is sampled after separately awaited keyDown and keyUp calls, not at keydown. A badge can paint after keydown but before the later `performance.now()` evaluation; the subsequent screenshot may contain that post-key frame, yet `_at_cut_boundary` excludes it. A reset or wrong ROI confined to that first frame can consequently be discarded while A1/A2 remain pass-capable. Smallest sound fix: install a one-shot page-side ArrowRight `keydown` listener before dispatch, require exactly one matching event, and use its recorded timestamp. Add a regression whose badge timestamp lies between keydown and the post-dispatch evaluation.

## MINOR

1. [.agents/plans/p2_freeze_control_3to4.plan.md:288](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/.agents/plans/p2_freeze_control_3to4.plan.md:288) — The plan claims strict bracketing prevents an interior gap from lending neighboring evidence, but the new test explicitly demonstrates the opposite; `dropped == 0` is load-bearing. Smallest sound fix: state that strict bracketing catches truncated endpoints, while the cumulative drop counter catches overwritten rows.

2. [.agents/plans/keynote-alpha.md:27](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/freeze-3to4/.agents/plans/keynote-alpha.md:27) — The documented “~129 unit tests” is stale against the supplied 367-test result. Smallest fix: update it to 367 or remove the volatile count.