1. **MAJOR — `src/obed_edom/web/app.py:1900-1907`**  
   Generator manifests key clips by the original FW slide instead of the resulting DSK ordinal. `_publish_generator_clips()` returns `{fw_slide: path}`, but that mapping is passed directly as `clips=` while `categories` and `source_slides` use DSK ordinals. When excluded slides shift ordinals—for example FW slide 5 becomes DSK slide 2—the manifest creates/updates slide 5 with the clip and slide 2 without it. The Exporter then re-exports slide 2 unnecessarily and may retain a bogus slide 5 entry.  
   **Fix:** convert the published mapping before writing:
   `clips={result.ordinals[fw]: path for fw, path in published.items() if fw in result.ordinals}`. Add a test where included FW slides are non-contiguous and ordinals differ.

2. **MAJOR — `src/obed_edom/web/app.py:1967-1968`, `src/obed_edom/dsk_stage_export.py:370-384`**  
   Any `manifest.json` in the folder is trusted without verifying its `deck` field. If two decks share a folder, slide 2 of deck B can reuse deck A’s clip solely because the manifest says slide 2 and that file exists. The subsequent merge also imports all of deck A’s slide metadata into deck B’s manifest.  
   **Fix:** accept a manifest only when its normalized/resolved `deck` matches the selected deck, or introduce a stable deck identity. On mismatch, ignore it entirely rather than merging it. Add same-folder/different-deck propose and apply tests.

3. **MAJOR — `src/obed_edom/dsk_stage_export.py:374-384`**  
   Manifest clip paths are not constrained to the output directory or expected naming scheme. Absolute paths discard `out_dir`, and `../` entries escape it, so an unrelated existing movie can be treated as an already-published clip. Even after deck validation, a malformed/stale manifest could silently reuse the wrong media.  
   **Fix:** require `clip` to be a basename equal to `clip_name(deck.stem, slide)`, resolve the candidate, and verify its parent is exactly `out_dir`. This likely means passing the deck/stem into `published_clips`. Test absolute paths, traversal, and a filename belonging to another stem.

4. **MAJOR — `src/obed_edom/dsk_stage_export.py:570`, `src/obed_edom/web/app.py:2052-2062`**  
   `export_stage_pngs()` rewrites `manifest.json` without the previously read manifest, temporarily dropping Generator fields such as `source_slide` and entries outside the selected range. `_run_dsk_export_apply()` restores them afterward, but an exception, cancellation, or process exit between these writes leaves the manifest permanently clobbered. A failure in the final write has the same result.  
   **Fix:** make `export_stage_pngs()` optionally skip manifest writing, and let the orchestrator perform one atomic merged write after all assets succeed. Alternatively pass `existing` through. Write via a temporary file followed by `os.replace`. Add a failure-injection test after stage export and a subset-range preservation test.

5. **MAJOR — `src/obed_edom/dsk_live.py:572-579`**  
   Exceptions during `LiveBatch.__enter__()` leave process state behind. After the lock is acquired and display poke starts, `_fingerprint_source`, directory creation, or `copy_keynote` can raise; Python will not call `__exit__` when `__enter__` fails. The lock descriptor remains held and the caffeinate/poke thread can remain active for the dashboard process, blocking subsequent exports. The new clip path exercises this scaffold directly.  
   **Fix:** wrap post-lock setup in `try/except` and synchronously stop the poke, remove any work directory, release the lock, and quit Keynote if setup launched it before re-raising. Add tests for fingerprint and copy failures after lock acquisition. Exceptions after a successful `__enter__` are otherwise cleaned up by `__exit__`.

6. **MINOR — `src/obed_edom/dsk_movie_export.py:480-508`**  
   Missing ffmpeg is detected only after Keynote has opened the deck and rendered every requested `.m4v`. The job ultimately fails cleanly and `LiveBatch` cleans up, but a long live export is wasted before the deterministic dependency error appears.  
   **Fix:** preflight `ffmpeg_exe()` before entering `LiveBatch` and raise the existing actionable error immediately. Add a test asserting `LiveBatch` is never entered when ffmpeg is unavailable.

7. **MINOR — `dashboard/src/tabs/dsk/DskExporter.tsx:59,96,194-195`**  
   The reused count is transient client state derived immediately before Apply, not part of the apply-result API. Restoring or reopening an already-completed job reports `0 reused`; retries can also retain a count from a previous proposal. Additionally, `clips` counts both reused and newly exported clips, so the summary “N clip(s), M reused” does not clearly report newly created clips.  
   **Fix:** have `_run_dsk_export_apply()` return `reusedClips` and `exportedClips` or explicit counts, type them in `ExportResult`, and render directly from the completed result. Add a UI test that initializes from a completed/restored job rather than traversing Apply.

No filename collision exists between `<stem>.NNN.mov` and `<stem>.NNN.SS.png`, and `os.replace` in clip export is same-volume because the temporary file is created under `out_dir`; Generator publication copies external sources and only replaces files already in that directory. Subset ordinal handling inside `_build_dsk_export_script()` is correct—the manifest-key conversion in finding 1 is the subset-related defect.