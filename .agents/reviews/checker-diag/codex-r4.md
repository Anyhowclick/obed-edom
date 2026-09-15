VERDICT: REVISE

1. MED — `src/obed_edom/web/app.py:1031`, `src/obed_edom/web/jobs.py:287` — Diagnostics are written to the canonical job directory, but purge still trusts client-patchable `result["workDir"]`. After patching `workDir` and re-checking, deleting the job leaves the canonical `diagnostics.jsonl`—containing the sermon text—behind. Purge the server-derived `.diff/<job.id>` directory for diff jobs, without creating it, and add a patch → re-check → delete test.

2. LOW — `tests/test_diagnostics.py:362` — The claimed non-selected-attempt regression test constructs only one clean attempt and manually inserts an impossible carried value. It does not exercise the full two-attempt behavior from Codex round 3. Build a consistent typed-then-fallback record, change only the typed attempt’s dropped-title result, and assert replay detects the accumulated-carry change while the fallback classification remains unchanged.

All earlier production-code findings are otherwise fixed. `select_text_sources` preserves the old typed → clean/full decision and attempt order; replay compares the full tried sequence, `typedSkip`, accumulated carry, and severity-mapped outcome separately; atomic publication and endpoint canonical-path/symlink checks remain intact.

The exact prescribed pytest command was attempted, but pytest could not initialize because the read-only environment has no usable temporary directory; collection did not start.