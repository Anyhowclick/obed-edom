VERDICT: REVISE

1. **MED — `src/obed_edom/diagnostics.py:203`** — Replay re-runs every attempt but retains and compares only `replay_selected`. A change to an earlier typed attempt—particularly its carried point title—can therefore report `MATCH` when the fallback remains selected and unchanged, even though that earlier `carried` value feeds the final `text.point_carry` decision. Reconstruct and compare the complete attempt sequence, accumulating `carried` exactly as `compare_inspects` does; add a two-attempt regression test where only the typed attempt’s carry changes.

2. **LOW — `src/obed_edom/diff_keynotes.py:1435`** — Round-2’s required per-attempt `reason` remains absent. `typedSkip` is useful but does not satisfy the documented JSONL contract requiring each attempt’s branch reason. Record `typed-covers-both`, `filter-symmetric`, or `filter-asymmetric` on each attempt and compare it during replay.

3. **LOW — `src/obed_edom/web/app.py:674`** — Canonical-path validation follows the final `diagnostics.jsonl` symlink while calculating both `expected` and `candidate`; consequently, replacing the canonical file with a symlink still passes validation and serves/reveals its target. Resolve the canonical parent, append the literal filename afterward, reject a symlinked final component, and add GET/reveal tests for that case.

Round-1 findings are otherwise fixed. Round-2’s canonical writer path and atomic publication are fixed; `carried` remains incomplete as described above, and the per-attempt reason is still missing.

The exact prescribed pytest command was run, but this read-only environment has no writable temporary directory, so pytest failed during temporary-file initialization before collection.