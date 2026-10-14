## Standards

- Blocker: no findings.
- Major: no findings.
- Medium: no findings.
- Low / new class — [tests/test_live_evidence_contract.py:209](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/tests/test_live_evidence_contract.py:209): `sampleRows` is exercised only with a deliberately invalid row. The assertion merely requires `row.busy` among the errors, so it remains green if valid managed feed rows also produce an unrelated schema/path error.
  - Failure scenario: `managed_session()` rejects every valid `sampleRows` record, but the malformed-row test still passes.
  - Exact fix: “Add valid schema-2 `sampleRows` to the `managed-g2-session` legal fixture so `test_producer_shapes_are_legal` exercises the managed-session wiring, or add one focused assertion that `managed_run()` returns no errors for a session containing valid `sampleRows`.”

## Spec

- Blocker: no findings.
- Major: no findings.
- Medium: no findings.
- Low: no findings.

The pending-scene rule matches `_INSTALL`: initial idle uses `sceneId`, final idle uses `nextSceneId`, and `busy === false` excludes automatic, queued, playing, and non-manual states. Terminal transitions advance the hash to `#atScene`, so departure/reset remains correct; looping returns reset after the intervening hash departure.

No downstream feed consumer depends on the old `samples` key. The remaining managed `samples` producer/consumer pair belongs to the separate G2 precheck. No live old-SHA pin remains; only historical review prose mentions `f1fe0dd6…`.

Out-of-scope note: [live_gl_replay_js.py:1263](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/src/obed_edom/live_gl_replay_js.py:1263) is a real risk for a `glReplay` boundary with D7’s automatic-run shape. The first ready idle can occur after the automatic event with `sceneId === atScene`, causing the strict `sceneId === atScene - 1` assertion to report `sceneMismatch`. Actual D7 feed entries are bridges rather than `glReplay`, so this does not block this patch.

Summary: Standards has one low finding; Spec has no findings. Tests were not rerun.