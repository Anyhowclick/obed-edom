## Round-1 findings

1. **FIXED** — Per-movie jobs now come exclusively from `cls.kept`, then resolve those IDs through `items_by_id`. [dsk_movie_export.py:983](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:983)

2. **FIXED** — Mapping keys must cover every kept movie; a single path is rejected for multi-movie slides, and the dashboard rejects its single-clip override in that case. [dsk_assemble.py:2200](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2200), [app.py:1871](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1871)

3. **FIXED** — Chain topology is derived from the full `builds` sequence, propagated to the true head, and the head’s content anchor can be calculated when it is outside the selection. [dsk_assemble.py:1317](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:1317), [dsk_assemble.py:1365](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:1365)

4. **FIXED** — Surplus movie-starts are matched by staged clip filename and capped at one per identity, independently of missing source builds. `verify_builds` aggregates by identity, so separate report rows cannot reset the allowance. [dsk_assemble.py:4625](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4625), [iwa_builds.py:335](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/iwa_builds.py:335)

5. **FIXED** — Clips receive unique staged basenames; matching must produce exactly one drawable, and missing, ambiguous, or refused reorders abort assembly. [dsk_assemble.py:4144](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4144), [dsk_assemble.py:4211](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4211)

6. **FIXED** — Per-movie coverage uses `job.crop_rect`, offset by the normalized crop origin. [dsk_movie_export.py:816](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:816), [dsk_movie_export.py:1126](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:1126)

7. **NOT FIXED** — Export still expands a 101×100 crop to 102×100, while fitting preserves the original visible aspect; the 0.5% guard therefore still rejects the real generated clip. The new test manufactures an even width matching the pre-existing fit instead of passing the actual 102×100 result. [dsk_movie_export.py:224](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:224), [dsk_assemble.py:2221](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2221), [test_dsk_assemble.py:239](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/tests/test_dsk_assemble.py:239)

8. **PARTIAL** — Current movie and static ordinals have stale `clip`/`srcClips` removed, but existing entries for ordinals absent from the new run are copied unchanged because `regenerated` contains only current `source_slides`/`src_clips`. [dsk_stage_export.py:421](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:421), [app.py:1919](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1919)

9. **FIXED** — A symlinked `src` is refused, candidate symlinks/traversal are skipped, resolved targets are constrained and deduplicated, and `drop_src=True` is always written. [app.py:2080](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2080)

10. **PARTIAL** — Reported mismatches are now checked against the expected dissolve, but verification still examines only `report["transitions"]`. `verify_builds` emits an entry only when output differs from source, so a silent failed write leaving the original magic move unchanged is never checked against `plan.clip_dissolve`. [iwa_builds.py:347](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/iwa_builds.py:347), [dsk_assemble.py:4683](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4683)

11. **FIXED** — `ordinals` is now a record, `clips` matches the array-valued API, and `hasManifest` was removed from both backend and exporter result type. [DskGenerator.tsx:49](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/dashboard/src/tabs/dsk/DskGenerator.tsx:49), [app.py:2025](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2025)

## New findings

1. **MAJOR — Pure-video intermediates retain the source outgoing transition.**  
   [dsk_movie_export.py:397](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:397), [dsk_assemble.py:3370](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:3370)  
   **Scenario:** A movie on slide 11 with an outgoing magic move is duplicated and exported without resetting its transition. The resulting “pure” clip bakes that source transition, then the assembled DSK slide adds a dissolve, producing two transition treatments.  
   **Fix:** Set the duplicate slide to `no transition effect` before each per-movie export; leave the dissolve solely on the assembled DSK slide.

2. **MAJOR — Operator-supplied clips bypass the load-bearing aspect guard.**  
   [app.py:1871](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1871), [dsk_assemble.py:2221](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2221)  
   **Scenario:** An operator supplies a clip whose aspect differs from the fitted movie rect. No dimensions enter `clip_sizes`, so assembly succeeds even though Keynote’s aspect-locked insert changes the requested geometry.  
   **Fix:** Probe operator clips with ffprobe, populate `clip_sizes`, and reject non-video or mismatched media exactly like generated clips.

3. **MAJOR — Generator mode preserves stale Exporter `stages`.**  
   [dsk_stage_export.py:421](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:421), [dsk_stage_export.py:449](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:449), [app.py:1919](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1919)  
   **Scenario:** Exporter writes PNG stages for a static slide; Generator is rerun over that deck. It supplies no `assets`, so the old `stages` array survives and exposes final assets from the previous deck revision.  
   **Fix:** In Generator mode, remove both `clip` and `stages` for every regenerated slide, and prune entries for ordinals absent from the new deck.

4. **MINOR — `AssembleResult.clips_inserted` returns deleted temporary paths.**  
   [dsk_assemble.py:5409](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:5409), [dsk_assemble.py:5541](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:5541), [dsk_live.py:673](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_live.py:673)  
   **Scenario:** Existing clips are copied into `batch.work`, `plan` is replaced with those staged paths, and that mapping is returned after `LiveBatch` deletes the work directory. CLI/library callers receive paths that no longer exist.  
   **Fix:** Preserve and return the normalized original clip mapping separately from the staged execution plan.