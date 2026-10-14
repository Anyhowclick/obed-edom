## Standards

- Blocker: no findings.
- Major: no findings.
- Medium: no findings.
- Low: no findings.

## Spec

- Blocker: no findings.
- Major: no findings.
- Medium: no findings.
- Low: no findings.

## Round-1 fold

Closed class — [tests/test_live_evidence_contract.py:43](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_evidence_contract.py:43), [:79](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_evidence_contract.py:79), and [:213](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_evidence_contract.py:213).

- The legal case retains `kind="managedRun"`, so valid `sampleRows` reaches `managed_run()` and `managed_session()`.
- The violation derives from that legal case and corrupts `busy`.
- Direct validator controls confirmed:
  - Legal `sampleRows`: no problems.
  - Identical rows under old `samples`: `managed.sample.*` errors.
  - Tampered `sampleRows`: `row.busy`.

No further fix required.

The pending-scene rule matches the real `_INSTALL`; departure/reset and loop behavior remain sound. No downstream feed consumer expects the old `samples` key, and the new SHA matches the module with no active stale pin.

Out-of-scope edge case, not a finding: [live_gl_replay_js.py:1263](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_gl_replay_js.py:1263) remains a real D7-shaped automatic-run risk, but the affected D7 entries are bridges rather than `glReplay`, so it does not block this diff.

Summary: 0 Standards findings; 0 Spec findings. No pytest rerun.