- **MEDIUM — edge case — [scripts/dissolve_probe.py:1368](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1368): A late pending record can hide a visible reset.** After normal fade progress, both animations restart at `ct=0, start=None`, with values and effective opacities `[0,1]`, immediately before teardown. `pending()` accepts this record and `score_curve()` skips it despite earlier animation progress.

  **Confirmed scenario:** final transition rAF at 1584 ms resets to `[0,1]`; the last screenshot covers 1550–1560 ms; the DOM disappears at 1600 ms. Both DX-1 and CEF `on` still return **MATCH**, with every blocking check **PASS**.

  **Exact smallest fix:** at line 1369, change `if not pending(r):` to `if both or not pending(r):`, recording an integrity problem for pending records after timed samples. Add a late-reset regression while retaining the valid leading-pending case.

**Closed class:** the round 1 bypass for incorrect initial animation values or effective opacities is fixed.

No other medium-or-above findings. Only small Python checks were run; no pytest or browsers.

**CHANGES REQUIRED**