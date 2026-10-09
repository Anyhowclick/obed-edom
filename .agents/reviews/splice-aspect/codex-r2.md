## Spec

1. **MAJOR — stale/misaddressed aspect can be stamped fresh — [remap_keynote.py:318](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/agent-ad1565c2abe558572/src/obed_edom/remap_keynote.py:318)**  
   **Evidence:** A media count mismatch makes `_splice_bulk_geometry` skip that kind because `kindIndex` may be desynchronized. `_merge_legacy_slides` then installs live JXA geometry but blindly restores pre-splice image/movie aspects by that untrusted `kindIndex`. The result is stamped `spliceAspectRefreshed=True` at line 495 and can immediately—or from cache—snap JXA geometry using the wrong ratio at `map_remap.py:2910`.  
   **Fix:** Pass mismatched kinds into the merge and assign `aspect=None` for those JXA items, or restore an aspect only where correspondence and frame consistency are independently proven. Add a count-mismatch round-trip/planner regression.

2. **MINOR — fresh partial-fallback caches can be wrongly rejected — [inspect.py:825](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/agent-ad1565c2abe558572/src/obed_edom/inspect.py:825)**  
   **Evidence:** `_merge_legacy_slides` leaves JXA groups—and newly appearing media—without an `aspect` key, while `wall_payload_carries_aspect()` examines fallback slides despite `groupChildrenUnavailable`. Consequently a correctly marked fresh cache gets `carries=False` and is reread.  
   **Fix:** Normalize every fallback-slide image/movie/group to carry an explicit safe aspect, normally `None`, before stamping and caching.

3. **MINOR — Gold acceptance oracle may silently be offline — [test_iwa_geometry.py:599](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/agent-ad1565c2abe558572/tests/test_iwa_geometry.py:599)**  
   **Evidence:** `_cached_payload()` accepts any reader even though the test claims a JXA oracle. Normal acquisition can replace the shared digest entry with `reader:"offline"`, making the comparison partly circular.  
   **Fix:** Return the payload only when `payload.get("reader") == "jxa"`, matching the other cache helpers.

4. **MINOR — granular-fallback geometry check is vacuous — [test_offline_inspect.py:1614](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/agent-ad1565c2abe558572/tests/test_offline_inspect.py:1614)**  
   **Evidence:** The nested loops can fall through without asserting that a victim group retained offline geometry, and never check the claimed non-victim JXA overwrite.  
   **Fix:** Record and assert both observations explicitly.

The old-cache exception path itself is conservative: nulling aspects prevents the planner’s aspect snap and uses raw affine geometry, so it cannot propagate the stale ratio. The Gold autosize assertions cover all 497 boxes and are not weaker than the Map original; the other re-pointed assertions remain equivalent.

## Standards

5. **MINOR — duplicated test helper — [test_acquire_cache_read.py:326](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/agent-ad1565c2abe558572/tests/test_acquire_cache_read.py:326)**  
   **Evidence:** The same `boom_two_tier` stub is repeated at lines 326 and 358, with equivalent existing stubs elsewhere.  
   **Fix:** Reuse one module-level `_fail_two_tier` helper.

`git diff --check` passed. I could not independently run pytest because the read-only environment provides no writable temporary directory.

**Verdict: REQUEST CHANGES — one MAJOR remains: legacy media fallback can be incorrectly marked aspect-refreshed.**