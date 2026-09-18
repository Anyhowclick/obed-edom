## Finding

- **P2 — Finding #2 is not closed end-to-end.** `_strict_hash_num` is correct, but production first passes hashes through `_norm_hash`, which truncates `#1junk` to `#1`. This occurs for boundary hashes at [p2_recovery_html_adversarial.py:1446](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1446) and [p2_recovery_html_adversarial.py:1480](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1480), and for presented samples at [p2_recovery_html_adversarial.py:1310](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1310). The truncation is implemented at [p2_recovery_html_dissolve_live.py:1760](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:1760).

  I reproduced `liveContinuity1to2` returning `ok: True` when its malformed `#1junk/#2junk` inputs and sample hashes were first processed through the actual production normalizer. The new test at [test_p2_adversarial.py:477](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/tests/test_p2_adversarial.py:477) calls the gate directly, so it misses this plumbing bypass. Preserve raw/query-stripped hashes for strict validation rather than feeding the strict gate prefix-normalized values.

## Verdict

- #2: **not closed**
- #3: closed — IoU floor and IoU ranking prevent oversized-container wins.
- #4: closed — absent/malformed restart bounds invalidate the boundary.
- #5: closed — running-max comparison catches cumulative rewinds.
- #6: closed — exactly two crossing IDs, both equal to the bound decoder, are required.
- No new P1 or independent P2 finding, and no new restart regression found. The remaining P2 is the incomplete end-to-end closure of #2.

Residual #1 is acceptable for this fixture and a visual-continuity verdict. Composite counter decoding proves visible advancement, synchronized identical media makes an instance swap visually equivalent, and near-IoU distinct-decoder ambiguity fails closed. It should remain documented as fixture-specific: it does not prove general paint ownership or physical decoder preservation.

Verification: all 19 live-continuity tests and 21 parameterless adversarial tests passed by direct invocation. Standard pytest was unavailable because the read-only environment provides no writable temporary directory.