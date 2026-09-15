# VERDICT: APPROVE

`PYTHONPATH=src … -m pytest -q tests/test_dashboard_api.py tests/test_diagnostics.py tests/test_sessions.py`:
`95 passed, 2 skipped`. Scope of this review: the round-8 change only.

## Verified

**The mkdir moved inside the guarded constructor.** `_run_diff_check` (`app.py:1036`) now calls
`_diagnostics_path(job.id)`, which is pure path arithmetic (`app.py:668-670`, docstring says so),
so the unguarded `diff_work_dir(job.id)` mkdir that ran before the `try` is gone.
`DiagnosticsWriter.__init__` (`diagnostics.py:43`) does `path.parent.mkdir(parents=True,
exist_ok=True)`, inside the constructor that `_run_diff_check` already wraps in
`except OSError: job.log(…); diag = None`. Confirmed by running it: a missing parent is created
(`base/a/b/diagnostics.jsonl` lands), and a parent that cannot be created raises
`PermissionError` (an `OSError`) out of the constructor rather than mid-pass.

**Symlink guard still precedes the mkdir.** `diagnostics.py:41-43` — the `is_symlink()` check on
both `path` and `tmp_path` raises before the mkdir line. Verified against a symlinked target:
refused, and the symlink's target file is untouched. Ordering matters here (a mkdir on a
symlinked ancestor would be a write through the link), and it is correct.

**Read and write paths are identical by construction.** Both `_trusted_diagnostics_path`
(`app.py:679`) and `_run_diff_check` (`app.py:1036`) call the same `_diagnostics_path(job_id)`;
there is no longer a second spelling of the location to drift. `diff_work_dir` remains imported
and used only at `app.py:824` for the match pass, which should create its directory.

**No regression to the symlink 404 tests.** `test_diagnostics_endpoints_404_when_the_canonical_file_is_a_symlink`
and `test_diagnostics_endpoints_404_when_the_result_path_escapes_the_work_dir` both pass. The
rejection is still two-layered: `candidate.is_symlink()` returns None outright, and the
`resolved_parent / candidate.name != expected` comparison would also fail, since `expected`
follows the link while the literal path does not.

**New test is honest.** `test_run_diff_check_discards_diagnostics_when_the_path_is_unwritable`
(`test_dashboard_api.py:829`) blocks the path with a regular file where a directory is needed
and asserts the check pass completes with `diagnosticsPath=None` — it exercises the real
constructor and the real `except OSError` branch, not a stub writer.

## Nit (non-blocking)

**LOW — `src/obed_edom/web/app.py:680`**: `expected_parent = expected.parent` is assigned and
never used, left over from the pre-helper version of this function. Delete the line.
