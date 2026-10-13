- **MEDIUM — edge case — [scripts/dissolve_probe.py:1436](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1436): Pre-start gap exemption can hide an outgoing dip.**  
  Scenario: the gap begins with transition DOM present, no animations attached, and effective opacities `[0, 0.5]`. Seventy milliseconds later, both animations are pending correctly at `[0, 1]`; subsequent playback is correct and screenshots miss the gap. The exemption checks only the ending record. Curve validation skips the empty animation list, and `no_flash` checks only incoming opacity.

  A synthetic DX-1 `on` arm returns **MATCH**, all seven blocking checks **PASS**. The previous strict gap rule makes the same evidence **INCONCLUSIVE**.

  **Exact smallest fix:** require `leaf_effs(a) == [0.0, 1.0]` alongside `not started and pending(b)` before exempting the gap. Add this regression while retaining the valid pre-start case.

**Closed classes:** both prior pending-record findings are fixed: incorrect initial values and pending resets after timed samples now return INCONCLUSIVE.

No other medium-or-above findings. Only small Python checks; no pytest or browsers.

**CHANGES REQUIRED**