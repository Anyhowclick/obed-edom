## Round-1 findings

1. **FIXED** — `src/obed_edom/web/app.py:1893-1910`  
   Published clips are converted from FW slide numbers to DSK ordinals before being returned and written to the manifest. The non-contiguous ordinal case is covered in `tests/test_dsk_dashboard_api.py:230-301`.

2. **FIXED** — `src/obed_edom/dsk_stage_export.py:363-384`, `src/obed_edom/web/app.py:1970-1971,2042`  
   `read_manifest()` rejects manifests whose resolved `deck` differs from the selected deck. Both propose and apply use that validated result, and same-folder/different-deck coverage exists in `tests/test_dsk_dashboard_api.py:467-538`.

3. **FIXED** — `src/obed_edom/dsk_stage_export.py:387-411`  
   Manifest clips must exactly match `clip_name(deck_stem, slide)`, resolve directly inside `out_dir`, and exist as a file. Absolute, traversal, alternate-stem, and malformed-name cases are tested in `tests/test_dsk_stage_export.py:491-526`.

4. **FIXED** — `src/obed_edom/web/app.py:2052-2067`, `src/obed_edom/dsk_stage_export.py:481-485,492-506,605-606`  
   The orchestrator suppresses the stage exporter’s intermediate manifest write and performs one merged final write. Manifest replacement is atomic via a same-directory temporary file and `os.replace()`. Existing entries and geometry are preserved.

5. **FIXED** — `src/obed_edom/dsk_live.py:572-606`  
   Post-lock setup is protected by cleanup that stops the display poke, removes the work directory, releases the lock, and attempts to close Keynote before re-raising. Fingerprint and copy failures are covered in `tests/test_dsk_live.py:197-241`.

6. **FIXED** — `src/obed_edom/dsk_movie_export.py:454-462,482`  
   `ffmpeg_exe()` is checked before payload processing or entering `LiveBatch`. The no-live-batch assertion is covered in `tests/test_dsk_movie_export.py:1988-2004`.

7. **PARTIAL** — `src/obed_edom/web/app.py:2040-2041,2071-2081`, `dashboard/src/tabs/dsk/DskExporter.tsx:193-196`  
   The completed result now carries persisted `exportedClips` and `reusedClips`, so restored jobs render correctly. However, `exportedClips` is calculated as `missing_clips | stage_slides`; every freshly exported stage-PNG slide is therefore counted as an exported clip. For one static slide and one newly exported movie slide, the UI reports two clips exported instead of one.  
   **Fix:** return `exportedClips=sorted(missing_clips)`. Update the API test currently expecting `[1, 3]` to expect `[3]`.

## New findings

- **MINOR — `src/obed_edom/dsk_stage_export.py:438-469`**  
  Merging does not remove output metadata that is incompatible with a slide’s current category. If a previously clipped slide becomes static/built, writing new `stages` preserves its old `clip`; if a stage slide becomes movie/mixed, writing its new `clip` preserves old `stages`. The manifest can consequently describe both stale and current assets for one slide, confusing consumers even though the returned `sequence` is correct.  
  **Fix:** for each updated `by_slide` entry, remove `clip`; for each updated `clips` entry, remove `stages`. Preserve untouched slides for subset exports, and add both category-transition tests.