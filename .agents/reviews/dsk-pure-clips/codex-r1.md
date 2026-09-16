1. **MAJOR — Per-movie export includes movies the assembler intentionally dropped.**  
   [dsk_movie_export.py:980](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:980), [dsk_movie_export.py:990](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:990)  
   `per_movie=True` enumerates every top-level movie in `items`, rather than the movies in `cls.kept`. A slide containing a centre movie plus a side-only/off-canvas movie either fails at `_rect_intersect`, or later fails assembly because the exported side movie is “unknown.”  
   **Fix:** derive movie jobs from the sorted movie IDs in `cls.kept`, then look those IDs up in `items`. Add a centre-plus-side-movie test.

2. **MAJOR — A partial per-item clip mapping silently deletes movies.**  
   [dsk_assemble.py:2189](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2189), [dsk_assemble.py:1540](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:1540), [app.py:1861](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1861)  
   Mappings reject unknown IDs but do not require every kept movie ID. All original movies are deleted, while only supplied clips are reinserted. The dashboard’s single operator-supplied clip marks the whole slide satisfied and maps only the first movie, so a two-movie slide loses the second movie.  
   **Fix:** require mapping keys to equal the kept movie-ID set. Either remove the single-clip dashboard override for multi-movie slides, accept one clip per item, or reject such an override explicitly. Keep the legacy single `Path` branch separate.

3. **MAJOR — Magic-move chain anchoring depends on the requested selection.**  
   [dsk_assemble.py:1316](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:1316), [dsk_assemble.py:1421](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:1421)  
   Chains are built only across `kept_numbers`. Requesting slide 12 alone from an 11→12 magic-move chain gives slide 12 its own anchor. Likewise, excluding the middle of 11→12→13 breaks slide 13 away from slide 11.  
   **Fix:** construct chain topology from the full source slide/build sequence, independently of operator inclusion. Compute the true head’s auto anchor even when the head is outside the requested range. Treat source-skipped slides explicitly as either chain breaks or members, rather than letting selection decide.

4. **MAJOR — Build verification does not implement “one movie-start per inserted clip.”**  
   [dsk_assemble.py:4573](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4573)  
   A surplus `apple:movie-start` is tolerated only when a matching source movie-start also appears as missing. If Keynote auto-adds a movie-start to an imported clip whose source movie had none, a valid assembly is refused. The allowance is also pooled across all clipped movie IDs, so it is not actually capped per clip identity.  
   **Fix:** permit at most one auto-added movie-start per inserted clip filename/identity, independently of source builds. Continue handling deleted source movie-starts through the missing-build logic. Update the existing “no paired source build” test, which currently locks in the contrary behavior.

5. **MAJOR — Clip z-order restoration is ambiguous and non-enforcing.**  
   [dsk_assemble.py:4153](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4153), [dsk_assemble.py:4165](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4165)  
   Matching only by basename cannot distinguish two inserted paths named `clip.mov`; reverse scanning assigns them in reverse insertion order, potentially reversing overlapping clips. A pre-existing movie with the same basename also makes correctness depend on undocumented serialization order. Worse, lookup or reorder failure is only a warning, so assembly can succeed with the clip still covering live overlays.  
   **Fix:** give every inserted file a unique collision-checked staging basename and/or identify inserted archive IDs by a pre/post deck diff. Require exactly one match per clip and refuse assembly if any required move is missing, ambiguous, or rejected.

6. **MAJOR — The clip-content assertion uses the un-clipped movie rectangle.**  
   [dsk_movie_export.py:1127](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:1127), [dsk_movie_export.py:827](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:827)  
   For a movie mostly outside the centre panel, `expected_area` includes the invisible portion. If less than half the original rectangle intersects the panel, a correct crop is rejected for covering under 50% of the expected rectangle. The added test happens to use an exact 50% intersection.  
   **Fix:** use the visible intersection (`job.crop_rect`) as the expected content rectangle, adjusted to the normalized crop origin.

7. **MINOR — Even normalization can trip the aspect guard for valid small crops.**  
   [dsk_movie_export.py:1125](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:1125), [dsk_assemble.py:2199](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2199)  
   A 101×100 intersection becomes 102×100, changing aspect by about 0.99% and exceeding the 0.5% guard. Similar odd-sized crops below roughly 200 px fail despite originating from the correct movie.  
   **Fix:** establish the final even output geometry before planning and fit from that same geometry, or crop then scale to an even multiple preserving the original ratio. Do not simply loosen the guard without accounting for the resulting Keynote size drift.

8. **MAJOR — Generator manifest merges can retain stale final `clip` fields.**  
   [dsk_stage_export.py:416](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:416), [app.py:1914](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1914)  
   Rerunning Generator over a deck previously exported merges the old entry, adds `srcClips`, but never removes `clip`. Old `srcClips` can similarly survive when an ordinal is now static or absent. This violates the “Generator never writes `clip`” contract and can expose stale final assets to manifest consumers.  
   **Fix:** add an explicit Generator manifest mode that removes `clip` and replaces/removes `srcClips` for all regenerated slide entries, rather than only overlaying new keys. Test Generator-after-Exporter and movie-to-static regeneration.

9. **MAJOR — Source-intermediate deletion can escape the output tree through a symlink.**  
   [app.py:2075](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2075)  
   Safety is checked against `src_dir.resolve()`. If `out_dir/src` itself is a symlink, both sides resolve to the external directory and `candidate.unlink()` deletes the resolved external target. Separately, if every manifest entry is missing or rejected, `to_delete` is empty and `srcClips` is never dropped after the successful export. Duplicate entries can also cause a partial-delete failure.  
   **Fix:** refuse a symlinked `src` directory and symlinked candidate components, validate lexical relative paths under the real output directory, deduplicate targets, and always write `drop_src=True` after a successful export—even when zero files existed.

10. **MINOR — Transition verification accepts any transition on clip slides.**  
    [dsk_assemble.py:4644](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4644)  
    Every transition mismatch on a clip slide is discarded. A failed dissolve write, wrong transition effect, or wrong duration therefore passes verification.  
    **Fix:** compare the output transition against `apple:dissolve` and `plan.clip_dissolve[slide]` within a small duration tolerance; suppress only that expected source-to-dissolve change.

11. **NIT — Dashboard result types do not exactly match the API.**  
    [DskGenerator.tsx:50](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/dashboard/src/tabs/dsk/DskGenerator.tsx:50), [app.py:1928](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1928), [app.py:2025](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:2025)  
    `ordinals` is typed as `number[]`, but the API returns an object mapping source slide to ordinal. The backend also still emits `hasManifest` after the exporter type removed it.  
    **Fix:** type `ordinals` as `Record<string, number>` and either retain/type `hasManifest` deliberately or remove it from the backend and tests.

I did not find an ordinal-shift or persistent-source-mutation defect in the normal duplicate-slide path: each duplicate is inserted immediately after its source and deleted before the next job, while failures are confined to the disposable scratch deck. The missing coverage is chiefly around the failure cases above; the new AppleScript tests currently assert emitted strings but do not exercise failed deletion/export cleanup.