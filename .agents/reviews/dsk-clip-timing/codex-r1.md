1. **MAJOR** — [src/obed_edom/iwa_movies.py:406](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/iwa_movies.py:406): Clip chunks are only permuted within their existing slots, so “After Transition” is not guaranteed to occupy absolute `buildChunks[0]`.

   Failure scenario: a slide has an existing overlay chunk at position 0 and inserted clip chunks at positions 1 and 2. `slots == [1, 2]`, so the designated After-Transition clip remains at position 1 and actually becomes “After Build 1.” The verification passes because [line 422](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/iwa_movies.py:422) derives `expected_pos` from that same incorrect `new_chunk_ids`, rather than requiring position 0.

   Suggested fix: construct `new_chunk_ids` as `target_order + non_target_chunks`, preserving only the relative order of non-target chunks, and verify explicit positions `0..len(target_order)-1`. The fixture at [tests/test_iwa_movies.py:465](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/tests/test_iwa_movies.py:465) contains only clip chunks, so all current timing tests miss this production-relevant case. Add an unrelated chunk before and between the clip chunks.

2. **MAJOR** — [src/obed_edom/web/app.py:1921](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/web/app.py:1921): Published clip order is independently recomputed from normalized crop rectangles, not the FW item order accepted by the assembler.

   Failure scenario: movie A is at `(2000.2, 500)` and movie B at `(2001.2, 0)`. Export and assembly order them A, B by source `x`. Even normalization floors both crop `x` values to 2000, so the dashboard breaks the tie by `y` and publishes B as `.01` and A as `.02`. The deck insertion/timing order remains A, B, while filenames and manifest order become B, A.

   Suggested fix: after assembly, publish directly from the ordered `result.clips_inserted` mapping, or return an explicit authoritative order from the assembler. Remove the pre-assembly crop-based `clip_order` recomputation. [tests/test_dsk_dashboard_api.py:258](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/tests/test_dsk_dashboard_api.py:258) locks in the wrong ordering authority by deliberately supplying kind-index-ordered results and expecting crop rectangles to repair them; replace it with a fractional-coordinate case and assert the assembler’s order is used.

3. **MAJOR** — [src/obed_edom/dsk_assemble.py:2289](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/dsk_assemble.py:2289): Missing source movie metadata is guessed as “all distinct” instead of being refused.

   Failure scenario: a planning caller supplies two clips without `deck`/`fw_deck`, while both source movies actually have `playsAcrossSlides=True`. The returned plan cascades the second clip as After Previous instead of With Build 1. This directly violates the owner-final “refuse on any ambiguity; never guess” requirement. The helper compounds this by defaulting absent entries to false at [line 1276](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/dsk_assemble.py:1276).

   Suggested fix: refuse multi-clip planning when the source graph or any flag cannot be resolved, and require `set(plays_across) == set(order)` inside `_clip_timing_for_slide`. Add a test asserting that a multi-clip, deckless planning call raises `AssemblyRefusal`.

4. **MINOR** — [src/obed_edom/dsk_assemble.py:4434](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/dsk_assemble.py:4434): The timing restore does not assert that `clip_timing` is a one-to-one permutation of every inserted clip.

   Failure scenario: a two-clip `AssemblyPlan` contains a timing entry for only one clip. Both clips are resolved, but [line 4450](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/dsk_assemble.py:4450) sends only the listed clip to the patcher. The omitted clip retains Keynote’s nondeterministic start flags and potentially `playsAcrossSlides=True`; no refusal occurs, and build verification tolerates its movie-start build.

   Suggested fix: before resolving or writing, require the timing IDs to equal `list(item_clips)` exactly, including order and uniqueness. Add missing, extra, duplicate, and reordered timing-plan refusal tests.

No separate efficiency issue rises above these findings. Fixing finding 2 also removes duplicated ordering logic and its extra geometry pass.