## Round 1

- CLOSED — chain-head anchor. `src/obed_edom/dsk_assemble.py:1521-1531` now returns and caches a videos-only head’s actual planned anchor, including an explicit operator anchor. Tests cover both auto-centre and explicit-left propagation.

- CLOSED — inconsistent stacking/order predicate. `src/obed_edom/dsk_movie_export.py:218-248`, `:1103-1119` and `src/obed_edom/dsk_assemble.py:2464-2476` classify the same visible source rectangles and pass the resulting mode into both FW and DSK ordering. Partial stacks explicitly refuse.

- CLOSED — incomplete/nondeterministic build-in metadata. `src/obed_edom/iwa_builds.py:103-165` exposes flags and delay; `src/obed_edom/dsk_assemble.py:1335-1375` selects chunk-ordered candidates; `:2497-2510` refuses multiple candidates; `ClipBuildIn` carries effect, duration, flags, and delay.

## New findings

- BLOCKER — `src/obed_edom/dsk_assemble.py:5128-5153`: every successfully rewritten `apple:dissolve` clip is subsequently rejected by `_verify_builds`. The output build identity uses the uniquely staged clip filename, so it is a surplus relative to the source movie; the verifier tolerates only surplus `apple:movie-start`, not the planned replacement effect. FRC 50 therefore reaches `clip_timing`, rewrites the upper build, then fails the immediately following build verification and produces only a refused deck. Tolerate exactly one inserted build matching `plan.clip_build_in`’s expected effect/type and that staged clip’s identity, while continuing to reject extras.

- BLOCKER — `src/obed_edom/dsk_movie_export.py:508-524` and `src/obed_edom/dsk_assemble.py:2497-2510`: the intermediate “pure-video” export retains the selected source movie’s build and exports it through Keynote, so the source build-in is already baked into the media. The assembler then adds the same timing/effect again to the inserted clip. An On Click source gets Keynote’s measured 2-second self-playing delay in the intermediate, then another 2-second On Click delay during final DSK export; FRC 50 can similarly receive its 8-second delay twice. Strip/neutralize the retained movie’s build before intermediate export, or retain the baked timing and do not recreate it. Refuse On Click when flattening cannot preserve an actual operator click.

- MAJOR — `src/obed_edom/dsk_assemble.py:1387-1391`, `:2497-2510`: copying only `automatic`/`referent` loses what a relative flag referred to before non-movie builds were dropped. Example: lower movie chunk 0, shape chunk 1 as a new build group, upper movie chunk 2 with `automatic=True, referent=False`. Source means “With Build 2”; the compacted output places the upper movie at chunk 1, meaning “With Build 1.” Carry the source build-group head/predecessor through planning and refuse when that referent is removed, or translate the source groups explicitly.

- MAJOR — `src/obed_edom/iwa_movies.py:320-330` and `src/obed_edom/iwa_write.py:2055-2063`: build/chunk resolution still requires co-location with the movie/slide. That violates the owning-member rule even though `_patch_archive_fields` can already edit each archive through its own `id_to_file` member. A valid slide referencing a build or chunk stored in another IWA member is refused. Resolve and patch every archive in its actual owning member; only the slide-reference rewrite belongs to the slide member.

- MAJOR — `src/obed_edom/iwa_movies.py:621-629`: the write is not transactional. `patch_slide_builds` rewrites the deck first; a later dotted-field encoding failure, member rewrite refusal, or read-back mismatch leaves the reordered slide partially mutated while reporting refusal. Preflight and encode all slide/archive edits, then commit them in one `_rewrite_members` operation. Verification failure also needs rollback or verification of a temporary package before copy-back.

- MAJOR — `src/obed_edom/iwa_movies.py:562-573`: duration comparison considers only the build duration. If the source and build are both `0.5`, but the auto-created chunk is `0.0`, `writeDuration` is false, the chunk remains `0.0`, and read-back deliberately expects that wrong value. Compare the build and chunk independently against `build_in_duration`, write each field that differs, and verify both equal the source duration.

- MAJOR — `src/obed_edom/dsk_movie_export.py:232-248`: the all-pairs partial-stack rule false-refuses ordinary rows. Three side-by-side movies where adjacent items overlap just over 5% after centre clipping yield two stacked pairs and one non-pair, aborting the entire apply as “partial overlap.” The same occurs with staggered magic-move rows. Distinguish layering from small row overlap—using containment/build evidence or visual row components—before invoking the partial-stack refusal.

- MINOR — `src/obed_edom/iwa_movies.py:184-197`: `_patch_archive_fields` says duplicate archive IDs are prohibited but silently lets the last patch replace earlier fields. The current effect and duration happen to share one dictionary, but another caller supplying separate patches would lose one. Merge compatible fields or refuse duplicate IDs before encoding.

- MINOR — `src/obed_edom/web/app.py:1795-1807`: `stackedMovies` is always calculated against the centre panel. After an operator enables `keepSide`, the assembler uses whole-wall visibility, so the review chip can claim source-build order while assembly chooses visual order. Compute both modes or derive the displayed flag from the current decision.

The same-media-file ambiguity is handled correctly: clips receive unique staged basenames (`dsk_assemble.py:4558-4565`), then build lookup is constrained by the resolved movie archive ID and exact drawable reference. The default non-build-in timing path still writes the same three flag fields and zero delay as before.

CHANGES-REQUESTED