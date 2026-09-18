Finding 1 remains honestly RED, but round 3 is not generally fail-closed yet. Two high-severity holes survive.

## Findings

1. **High — pre-transition draws at `hash1` satisfy `incomingFeedDraw`.**  
   [`_score_feed_engaged`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:433>) uses the inclusive lower bound `hn >= num(hash1)`. Here `hash1 == #1` is captured before `ArrowRight`, while `preserve_events` spans the entire run.

   Concrete false-positive: the invisible incoming canvas receives a successful player-authored draw at `#1` before the transition; later motion/stable-decoder/context checks pass, but no incoming draw occurs during the cut. That old event still makes the verdict green. I directly exercised `hashNum=1` with `restart_min_hash=6`; `_score_feed_engaged` returned `ok=True`. `hash2` remains unused.

2. **High — F4’s stale-ID fix works, but the one-decoder invariant is still unenforced.**  
   [`startTextureFeed`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:848>) starts per decoder and permits each decoder to feed canvases individually bound to it. [`footprintOwnerDecoderId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:471>) resolves equal-overlap ties by first DOM order because it updates only for `ov > bestOverlap`.

   Concrete false-positive: sibling D1 is player-drawn into outgoing O and D2 into incoming I; both feeds run. If I occurs first in DOM, the footprint samples report stable D2, and D2’s valid incoming event satisfies the scorer, while D1 simultaneously supplies outgoing pixels. This still violates “one exact decoder across both slots.”

3. **Medium — F2 remains broader than an authored transition.**  
   [`_extract_movie_layers`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:228>) checks only the name prefix, not `type == "transition"`. A group named `apple:magic-move-implied-motion-path` marks descendant crossfades as Magic Move; I directly confirmed this.

   The known real variant, `apple:magic-move-implied-motion-path`, is accepted, so the predicate is not too strict for the fixture. The remaining problem is breadth: the new test rejects `not-a-magic-move-caption`, but does not reject a non-transition node bearing the accepted prefix.

4. **Medium completeness limitation — hash `#6` cannot be classified safely.**  
   [`_score_feed_engaged`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:462>) excludes `hn >= 6`. This correctly prevents the 2→3 restart from proving Finding 1, and `#4` remains accepted. However, the trace also contains cut-related prepaint activity at `#6`, immediately before the restart events at the same hash.

   Therefore a genuine incoming repair that engages only at `#6` is rejected. That is fail-closed, but incomplete; event ordering or a transition-phase marker would be needed to distinguish pre-restart cut work from restart work. The test uses `#99`, not the exact `#6` boundary.

5. **Medium — F7 coverage remains incomplete.**  
   The eight additions in [`test_p2_adversarial.py`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/tests/test_p2_adversarial.py:472>) are load-bearing for the Python authorship/canvas/context/hash guards, loose-substring rejection, and removal of steady folding. However:

   - No test exercises WeakMap element identity or equal-overlap sibling ownership.
   - No test proves a throwing `drawImage` leaves ownership unchanged.
   - No test rejects an otherwise-valid draw at pre-click `hash1`.
   - No test requires the Magic Move ancestor to be a transition.
   - Reverting either F4 or F6’s JavaScript change would leave these tests green.

## Category disposition

- **F1:** Authorship, canvas membership, event context, known-hash, and late-event checks are closed. The inclusive lower boundary remains fail-open; `#6` is a deliberate but incomplete exclusion.
- **F2:** Loose substring matching is closed; transition-type validation remains open.
- **F3:** Acceptable documented residual. Repeated-pair provenance remains preserved, and the non-movie-raster limitation is clearly scoped. The current fixture has one occurrence. One stale inline claim says repeats “cannot masquerade,” although the contract correctly says they can.
- **F4:** New-element stale-ID alias is closed; no implementation ownership map remains keyed by canvas ID. Multi-decoder feeding and overlap ties remain open.
- **F5:** Closed. Exact `[from]`/`[to]` output is conservative and resolves the fixture to movie1 `0885…/A223…`.
- **F6:** Closed by inspection: ownership is recorded only after `orig.apply` returns, and `__obedFeeding` prevents successful instrument draws from recording authorship.
- **F7:** Partially closed; the new Python tests are useful but do not cover the JavaScript fixes or the surviving seams.

The focused 18 no-filesystem scorer/clock tests passed directly. I could not independently rerun the full 88-test suite because this review environment has no writable temporary directory. No files were changed.