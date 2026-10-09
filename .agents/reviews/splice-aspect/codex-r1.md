## Findings

1. **MAJOR — product-bug — [baseline.py:25](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/baseline.py:25)**  
   Existing v5 offline caches are not invalidated. A cache created before this commit can contain the stale aspect, satisfy the aspect/ID/tag checks, and be returned at [remap_keynote.py:385](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/remap_keynote.py:385) without executing the corrected splice. Tagged v5 caches have been possible since `1ad51ed8`, so this is not merely theoretical.  
   **Fix:** bump `INSPECT_VERSION` to 6, updating its documentation/tests, or persist and require a splice-semantics marker.

2. **MINOR — oracle-circularity — [test_offline_inspect.py:1265](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/tests/test_offline_inspect.py:1265)**  
   `_jxa_with_consistent_aspects()` obtains expected aspects from another invocation of the production offline reader. An upstream error that calculates or assigns the wrong aspect while leaving w/h within 1 point is copied into both plans, leaving this full-deck gate green. The positive control establishes that stale-frame detection remains effective, but not that consistent-frame aspects are correct.  
   **Fix:** retain this normalization but add an independent per-address aspect oracle, preferably captured from a controlled Keynote height write; otherwise document that this gate assumes separately validated aspects.

3. **MINOR — test-quality — [test_offline_inspect.py:853](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/tests/test_offline_inspect.py:853)**  
   The unit test covers a 0.5-point difference, a gross stale difference, `None`, and a zero **bulk** dimension. It does not pin the load-bearing boundary—exactly 1.0 retained versus just over 1.0 refreshed—or isolate x/y-only movement. Despite its prose, it also does not exercise an offline-zero frame; the zero-height case starts from offline 50×20. Hidden stale items are excluded from the plan comparison, and rotated items are unrepresented.  
   **Fix:** parameterize the exact boundary, one-axis and x/y-only changes, offline-zero/valid-bulk input, and rotated/masked cases; directly cover hidden stale items outside the transform comparison.

The predicate itself otherwise matches the stated semantics: it compares the pre-splice rounded w/h with row floats, uses `> 1`, preserves `None`, ignores x/y for staleness, and affects only the planner’s two aspect-snap paths plus persisted payloads.

**Verdict: REQUEST CHANGES — the stale-only logic is correct, but missing cache invalidation is release-blocking.**