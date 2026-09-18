No—I cannot confirm the masked-handoff P1 as closed end-to-end.

- **P1: `targetVia` is dropped before scoring.** Capture records it at [p2_recovery_html_adversarial.py:1241](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1241), but the `flip_samples` projection at [line 1590](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1590) omits it. Consequently, both ambiguity checks at lines 491 and 516 always see `None` in production.

  I reproduced:

  ```text
  direct scorer input with targetVia: False
  same data after production projection: True
  ```

  The new test passes because it supplies `targetVia` directly, bypassing this plumbing.

- **Remaining bracket edge:** capture stores only `target_after.via`. If `target_before` is ambiguous but `target_after` resolves—or the owner changes D1→D2 during the screenshot—the decoder is nulled by `bracketConsistent`, yet `targetVia` can say `"footprint-video"`. That null is then indistinguishable from a tolerated absence gap. The frame should carry ambiguity/handoff evidence from both bracket endpoints.

To close it, propagate `targetVia` into `flip_samples` and mark a sample as handoff/ambiguous when either bracket endpoint is ambiguous or two non-null bracket owners differ. Add a test through that capture-to-`flip_samples` transformation.

The strict-hash carryover is reasonable to defer under the stated fixture invariant: clean `#N?currentSlide=1` hashes make malformed-prefix input unreachable, while correcting it requires raw-hash pipeline changes. It should remain explicitly documented as fixture-scoped—not as end-to-end strict validation.