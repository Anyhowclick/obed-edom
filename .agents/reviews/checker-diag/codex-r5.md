VERDICT: REVISE

1. **MED — `src/obed_edom/web/app.py:1031`** — `diff_work_dir(job.id)` performs `mkdir()` outside the diagnostics `try`, so an unavailable output directory can still abort the entire check pass before `DiagnosticsWriter`’s guarded open. Compute the canonical path without creating directories (`output_root() / ".diff" / job.id / "diagnostics.jsonl"`), letting the guarded writer open fail gracefully. Add a behavioral test using an unusable `OBED_EDOM_OUTPUT_ROOT` and assert the check completes with `diagnosticsPath=None`.

All earlier findings remain fixed. The exact pytest command was attempted but failed before collection because the read-only sandbox has no usable temporary directory.