The diff is not ready for a live run.

## Round-5 item 5 — FIXED

The previously reported publication rollback holes are fixed:

- All destinations are preflighted before the write loop begins. [app.py:2018](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2018), [app.py:2039](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2039)
- The caller owns the journal, and each completed write is recorded immediately. [app.py:1894](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1894), [app.py:1932](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1932), [app.py:2053](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2053)
- Existing destinations are renamed to backups before overwrite and restored during rollback; backups are discarded only after commit. [app.py:2041](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2041), [app.py:2057](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2057), [app.py:2075](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2075)
- Regressions cover later-destination failure and restoration of overwritten bytes. [test_dsk_dashboard_api.py:584](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:584), [test_dsk_dashboard_api.py:654](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:654)

## Exporter commit order — FIXED

Exporter now performs one atomic final-manifest commit with `srcClips` already removed, then deletes intermediates best-effort. [app.py:2252](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2252), [app.py:2255](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2255), [dsk_stage_export.py:491](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:491)

## New findings

- **MAJOR — Generator cleanup failure rolls back clips after the new manifest is already committed.** The Generator commits the new manifest, then calls `_delete_managed_src_clips` inside the same rollback-bearing `try`. Its `unlink()` is not best-effort. An unlink failure therefore enters the exception handler and removes/restores the newly published clips without restoring the previous manifest, potentially leaving the committed manifest referencing a missing new clip. [app.py:1941](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1941), [app.py:1955](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1955), [app.py:1959](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1959), [app.py:2118](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2118)  
  **Fix:** make stale cleanup best-effort after publication has committed and backups have been discarded, matching Exporter semantics.

- **MAJOR — rollback loses an operator clip located inside `src/`.** Such a source is moved with `os.replace`; the journal records only the destination and its backup. On a later failure, rollback deletes the destination but never restores the source to its original pathname, causing input-file loss. [app.py:1983](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1983), [app.py:2045](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2045), [app.py:2057](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2057)  
  **Fix:** copy caller-supplied sources regardless of location, or journal and restore the original source pathname.

Python AST parsing passed for the six modified backend modules. No files were changed.