## Findings

1. **Medium — `score_index_progression` can pass after losing visibility for most of the capture window.**  
   [html_alpha_probe.py:1363](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/src/obed_edom/html_alpha_probe.py:1363)

   `None` values are removed before every check. Consequently:

   ```python
   [2, 6, 10, 14, 18, 22] + [None] * 16
   ```

   returns `ok=True`. A restart that advances for six captures and is then occluded, replaced by an undecodable poster, or otherwise loses its ROI for the remaining 16 captures passes. Thus all-`None` and static-flat wrong ROIs fail closed, but sparse/partially occluded ROIs do not.

   Require adequate decodable coverage—especially at the end of the window—or treat long `None` runs as failure. The existing sparse test only checks two decodes, below `min_decodable`; it misses the threshold case.

2. **Medium — the replacement is not strictly at least as strong as full-footprint MAE.**  
   [p2_recovery_html_adversarial.py:1805](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:1805)

   `presentedMotionOk` combines target-decoder rVFC with a global 24×12 patch, but never establishes that the patch belongs to that decoder. Concrete false pass: the target decoder’s rVFC advances while its visible footprint is static/occluded, but another counter-bearing layer occupies the hardcoded ROI—or only the counter corner remains exposed while the rest of the movie is covered. Index progression passes; whole-footprint MAE would reject the static majority.

   For this fixed fixture, the current ROI visibly lies inside the intended left grating movie and the other movie is far to the right, so the constant itself is reasonable. But the claim that any wrong ROI fails closed is too strong. Binding expected counter progression to the target decoder’s media time, or adding a parity-resistant whole-footprint check, would close this gap.

3. **Low — large backward/reset jumps can be accepted as wraparound, and the test does not catch it.**  
   [html_alpha_probe.py:1375](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/src/obed_edom/html_alpha_probe.py:1375)  
   [test_html_alpha_probe.py:1469](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/tests/test_html_alpha_probe.py:1469)

   The scorer accepts every modular delta up to 128, despite real observed gaps being 1–4. For example:

   ```python
   [200, 14, 18, 22, 26, 30, 34]
   ```

   returns `ok=True`: `200 → 14` is interpreted as forward `+70`, although such progress is impossible between captures and could be a backward reset.

   The added backward test `[2, 6, 10, 200, 14, ...]` passes because `10 → 200` is rejected; it does not prove that the claimed `200 → 14` drop is rejected. A conservative maximum forward step, ideally cadence-derived, would preserve genuine wraparound while rejecting this.

## Overall assessment

A truly frozen, continuously visible poster fails through `minDistinct`/stall-run, and normal modulo wrap works. However, the implementation is not fully fail-closed because sparse undecodable tails pass, and the tiny patch is not source-bound.

The tests cover constant freeze, too-few decodes, nominal wrap, short stalls, and a copied live sequence. They do not cover sufficient-but-sparse decoding, a genuine large raw drop, target/ROI binding, or decoding the actual slide-3 screenshots through `INDEX_PATCH_ROI_SLIDE3`.

I found no regression to unchanged `score_composited_index_run` or the restart scorers themselves. I could not rerun pytest in this read-only environment because no writable temporary directory is available; I directly executed the scorer counterexamples above.