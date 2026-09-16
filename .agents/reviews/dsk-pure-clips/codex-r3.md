Read-only review complete; no files changed. Five items are fixed and two remain partial.

## Round-2 items

1. **PARTIAL — #7 aspect handling.** The specific 101×100 → 102×100 case is accepted, and insertion adopts the clip aspect. However, the resolution-dependent tolerance is not sound, and normalized crop-origin changes are not propagated. [dsk_assemble.py:2239](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2239), [dsk_assemble.py:2246](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2246), [dsk_movie_export.py:1127](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:1127)

2. **FIXED — #8 stale manifest entries.** Generator mode prunes ordinals absent from the current `source_slides`, and removes old `clip`, `stages`, and obsolete `srcClips` from every regenerated ordinal. The dashboard enables this mode. [dsk_stage_export.py:424](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:424), [dsk_stage_export.py:436](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:436), [dsk_stage_export.py:449](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:449), [app.py:1925](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1925)

3. **FIXED — #10 silent transition-write failures.** Verification now independently reads every output clip slide’s actual transition and requires the planned dissolve/duration, regardless of whether `verify_builds` emitted a transition diff. [dsk_assemble.py:4715](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:4715)

4. **FIXED — New 1, pure clips retaining source transitions.** Each scratch duplicate is explicitly set to `no transition effect` before export. [dsk_movie_export.py:398](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:398)

5. **PARTIAL — New 2, operator clips bypassing the aspect guard.** The dashboard path now probes clips and passes their dimensions into assembly. [app.py:1882](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1882), [app.py:1911](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1911)  
   The CLI still validates only existence/extension and calls assembly without `clip_sizes`; assembly silently skips the guard when a size is absent. [cli.py:560](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/cli.py:560), [cli.py:581](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/cli.py:581), [dsk_assemble.py:2226](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2226)

6. **FIXED — New 3, stale Exporter stages in Generator mode.** Regenerated entries explicitly discard `stages`, while absent ordinals are removed. [dsk_stage_export.py:424](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:424), [dsk_stage_export.py:449](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:449)

7. **FIXED — New 4, deleted temporary paths in `clips_inserted`.** The normalized caller mapping is captured before staging and returned independently of the disposable execution plan. [dsk_assemble.py:5424](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:5424), [dsk_assemble.py:5578](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:5578)

## New findings

1. **MAJOR — The widened aspect workaround is not geometrically sound.** [dsk_movie_export.py:1127](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:1127), [app.py:1901](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1901), [dsk_assemble.py:2239](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2239), [dsk_assemble.py:2246](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_assemble.py:2246)

   **Scenario:** `max(0.5%, 1/w + 1/h)` accepts a 16×10 operator clip for a 16:9 target: the mismatch is 10%, but tolerance is 16.25%. Conversely, a legitimate 1×1080 crop normalized to 2×1080 changes aspect by 100%, exceeding the approximately 50.09% tolerance. Also, when odd `x`/`y` is rounded down, the exported clip contains padding on the left/top, but assembly retains the old `rect.x/y`; narrow crops can therefore shift substantially after scaling. The `width_bound` test also compares a DSK-space fitted rectangle with the FW-space `wall_rect`, so it cannot reliably identify the constraining axis.

   **Fix:** Pass exact pre-normalization and normalized crop geometry into assembly and transform that rectangle using the same affine scale, including origin offsets. Keep operator clips on a strict aspect threshold; do not infer normalization allowance solely from media resolution.

2. **MINOR — Generator reruns leave orphaned files under `src/`.** [app.py:1963](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/web/app.py:1963), [dsk_stage_export.py:424](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_stage_export.py:424)

   **Scenario:** A first run publishes two clips or an additional slide. A later run removes one movie/slide. The manifest correctly drops its entry, but the old `.src.mov` remains. Because it is no longer referenced by `srcClips`, the Exporter cleanup will never discover it.

   **Fix:** Capture the previous manifest’s managed `srcClips` and, after the new deck and manifest commit successfully, safely delete old referenced files absent from the new manifest.

3. **NIT — Per-movie progress and structured export errors no longer match the parsers.** [dsk_live.py:38](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_live.py:38), [dsk_movie_export.py:413](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:413), [dsk_movie_export.py:419](/Users/anyhowclick/Desktop/dsk-d4-work/wt-pure/src/obed_edom/dsk_movie_export.py:419)

   **Scenario:** Markers now use `12.0`, while both regexes require the slide digits to be followed immediately by a tab. Progress callbacks never fire, per-clip `wall_s` falls back to total batch time, and failures lose the structured error message.

   **Fix:** Keep the first marker field as the integer slide number and put the movie index in a separate tab-delimited field, or update both parsers explicitly.