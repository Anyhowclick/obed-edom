VERDICT: REVISE

1. **HIGH — `src/obed_edom/web/app.py:1025`, `src/obed_edom/diagnostics.py:34`** — The diagnostics writer trusts client-patchable `result["workDir"]`; after `PATCH /api/jobs/{id}`, re-checking can truncate `<arbitrary-directory>/diagnostics.jsonl`. Derive the write path from the canonical server-owned job directory, reject symlinks, and add a re-check test with a patched external `workDir`.

2. **MED — `src/obed_edom/diagnostics.py:34`, `src/obed_edom/web/app.py:1050`** — Re-check truncates the published file before the check succeeds. During execution it can be downloaded partially; if the check later raises, `JobRunner` retains the old result and endpoint but the file is now incomplete. Write to a sibling temporary file and atomically replace `diagnostics.jsonl` only after comparison, outline checking, and writer close succeed.

3. **MED — `src/obed_edom/diagnostics.py:155-187`** — Replay re-derives `strip_carried_point_title` but discards and never compares its `carried` result, although that value determines the separate `text.point_carry` finding. Replay can therefore report `MATCH` after point-title behavior changes. Include `carried` in `replay_selected`, compare it with the recorded selected attempt, and add a behavioral regression test.

4. **LOW — `src/obed_edom/diff_keynotes.py:1436`** — Text attempts omit the plan-required `reason` field (`typed-covers-both`, `typed-below-coverage`, etc.), and tests do not detect the omission. Record the branch reason and assert it through a generated diagnostics record.

The four round-1 fixes are otherwise present, and `select_text_sources` matches the old selection logic. The exact pytest command could not reach collection because the read-only environment has no usable temporary directory.