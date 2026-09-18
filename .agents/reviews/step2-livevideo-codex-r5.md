## Verdict

Not fully fail-closed. The ordinary cases are rejected, and no 2→3 restart regression is evident, but the null tolerance introduces one real false-green class.

### P1 — Null samples can conceal a handoff

[stableFootprintDecoder](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:471) ignores decoder identity on null samples. I reproduced this passing:

- D1 before the flip.
- Ten after-window samples: seven D1, three null.
- D1’s rVFC advances.
- The three null captures represent D2 temporarily occupying the footprint.

Result: `ok=True`, `nonNullFrac=0.7`. The counter and rVFC do not close this because D1 can advance off-footprint while synchronized D2 supplies the visible counter.

[crossingIdentity](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:497) has a related weaker form: it discards null pre-samples and has no coverage or recency requirement. One matching pre-owner observation plus nine null pre-samples passes. Thus it fails on complete absence, but can pass on near-complete absence.

To retain fail-closed semantics, tolerated nulls need independent provenance—for example, distinguish and reject `ambiguous` ownership, carry candidate decoder IDs, and only tolerate an event-proven remount gap for the same decoder.

### Confirmed behavior

- Observed D1-before/D2-after: rejected by `crossingIdentity`.
- All-null pre-window: rejected.
- Flat bound-decoder rVFC: rejected.
- After-window coverage below 70%: rejected.
- Exactly 70%: accepted, including the masked-handoff case above.
- A persistent D2 after the flip is rejected when D1 was observed before.

### Restart

No 2→3 regression found. The two scorer changes exclude `hash >= 6` and do not feed the restart verdict. The post-change live artifact reports:

- `deliberateRestart2to3: True`
- `preserveDidNotBlockRestart: True`
- fresh restart decoder `4`
- one matching reuse-skip and retire event
- no reuse after the boundary
- no stitched restart

See [REPORT.md](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/REPORT.md:17) and [report.json](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial/report.json:1005).

The Round-4 strict-hash carry-over also remains: [_norm_hash](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:1760) still prefix-normalizes malformed hashes before strict validation.

Verification: all 20 parameterless live-continuity tests passed by direct invocation. Standard pytest could not initialize because the read-only environment has no writable temporary directory. No files changed.

Skill used: [obed-edom SKILL.md](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/.agents/skills/obed-edom/SKILL.md)