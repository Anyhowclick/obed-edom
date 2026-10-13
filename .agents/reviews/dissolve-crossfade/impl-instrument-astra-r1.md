- **MEDIUM — new class — [scripts/dissolve_probe.py:1363](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1363): Pending records bypass curve validation.** Scenario: one rAF records incoming/outgoing opacity `0/0.5`, both animations at `ct=0, start=None`; subsequent playback is correct and screenshots miss the initial dip. The scorer skips that record, `no_flash` checks only incoming opacity, and normal rAF cadence never invokes `pending()`. A small synthetic check confirmed **MATCH with every check PASS**; the baseline scorer returns **INCONCLUSIVE**.

  **Exact smallest fix:** retain the empty-animation skip, validate exactly one incoming and one outgoing animation, then skip all-pending records only when `pending(r)` confirms their initial animation values and effective opacities. Otherwise append an integrity problem.

No other medium-or-above findings. No pytest or browsers run.

**CHANGES REQUIRED**