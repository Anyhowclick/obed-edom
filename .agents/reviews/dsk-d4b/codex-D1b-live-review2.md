APPROVE

1. **FOLLOW-UP — Major — general top-level autosize text retains the same position-before-size exposure.**  
   [src/obed_edom/dsk_assemble.py:2165](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2165), [src/obed_edom/dsk_assemble.py:2411](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen/src/obed_edom/dsk_assemble.py:2411)  
   Only `cluster_autosize_ids` receives size-before-position ordering. Other autosize text—including the noted GW 13/17 stacked boxes—still emits position before text/run size. Refit writes have the same ordering.  
   **Fix:** in a separate follow-up, carry reliable raw-autosize identity for all top-level text and make both emitters use `width → size/run sizes → position` with height omitted for autosize items. Add GW 13/17 regressions.

Round-1 findings 1–3 are closed:

- The alignment transform is removed; `_slide_lines` writes exact `{rect.x, rect.y}`.
- `build_refit_script` also writes the unmodified `rect.y`, restoring emitter consistency.
- Tests now assert exact y values, ordering, and refit behavior.
- Reordering is restricted to raw-height-zero heading/numeral cluster IDs. Fixed-frame and non-cluster items retain their existing order.
- Tuple `run_sizes` writes are accumulated before the final position write for cluster autosize items.

Static review only; tests were not executed, as requested.