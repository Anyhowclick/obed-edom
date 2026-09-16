The diff is not ready for a live run.

## Round-5 item 5

**PARTIAL — whole-run failure boundary.**

Export and assembly now share the `try`, and `.src-*` is removed in `finally`. [app.py:1895](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1895), [app.py:1968](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1968)

Two rollback holes remain:

- `_publish_generator_clips` returns its write journal only after all files succeed. If it writes one destination and then refuses a later destination, assignment at line 1932 never completes, leaving `published_files` empty; the earlier file survives the failed run. [app.py:1932](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1932), [app.py:2021](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2021), [app.py:2031](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2031)
- On rerun, `copy2` overwrites an existing managed destination without backing it up. A later manifest failure then unlinks that destination instead of restoring its previous contents, leaving the previous manifest referencing a missing clip. [app.py:1958](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1958), [app.py:1961](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1961), [app.py:2031](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2031). The regression checks only that the newly introduced slide-3 clip disappears; it does not verify that the overwritten slide-2 clip survives. [test_dsk_dashboard_api.py:560](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:560), [test_dsk_dashboard_api.py:577](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:577)

**Fix:** preflight every destination before writing, publish through a caller-owned journal, and preserve/restore existing destinations until the manifest commit succeeds. Add a later-destination-failure regression and assert that an overwritten prior clip retains its original bytes after manifest failure.

## New MAJOR: symlink-safe Generator publication

**FIXED.**

Publication refuses a symlinked `src/`, refuses each symlinked destination, and verifies that every resolved destination parent is the real `src/` directory. [app.py:2004](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2004), [app.py:2009](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2009), [app.py:2021](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2021), [app.py:2024](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2024)

Generator regressions cover both the directory and destination cases. [test_dsk_dashboard_api.py:583](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:583), [test_dsk_dashboard_api.py:638](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_dashboard_api.py:638)

## New findings

- **MAJOR — the required 11→12→13 magic-move chain is explicitly replaced with dissolves.** Every movie/mixed slide records either its original dissolve duration or `0.5`, emits a dissolve, and verification rejects anything other than that dissolve. Therefore FW 11 and FW 12 cannot retain their outgoing magic moves. [dsk_assemble.py:3](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:3), [dsk_assemble.py:2303](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2303), [dsk_assemble.py:3435](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:3435), [dsk_assemble.py:4768](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4768). The current test enshrines forced dissolve. [test_dsk_assemble.py:2176](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_assemble.py:2176)  
  **Fix:** preserve source magic-move transitions on chain members 11 and 12, retain the source dissolve on 13, and add a three-slide clip-chain emission/read-back regression.

- **MINOR — Exporter cleanup can commit dangling `srcClips` metadata.** It commits a manifest retaining `srcClips`, deletes those files, then performs a second manifest commit. If the second write fails, the manifest still references deleted intermediates. [app.py:2179](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2179), [app.py:2206](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2206), [app.py:2213](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2213)  
  **Fix:** commit the final manifest once, then make intermediate cleanup best-effort, or quarantine files until the final commit succeeds.

Python AST parsing passed for the six modified backend modules. No files were changed.
---
Maintainer note (2026-09-16): the "MAJOR — magic-move chain replaced with dissolves" finding is NOT a defect. Owner decision 4 of this round: clip slides get a dissolve as the interim treatment because the pure clips cannot carry the source magic move; the Keynote-alpha work may later retain source transitions. Chain membership still drives the shared anchor.
