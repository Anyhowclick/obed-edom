Round 2 is still honestly RED on the recorded trace, but the instrument is not generally fail-closed. I found four high-severity ownership/provenance holes.

## Findings

1. **High — `_score_feed_engaged` accepts unproven or out-of-window draw events.**  
   [`_score_feed_engaged`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:415>) does not enforce several pinned event fields:

   - `authoredBy` is never inspected; a `mo-prepaint-draw` with `authoredBy:"geom"` passes.
   - Event `contextType` is never checked. The sampled 2D context may belong to an outgoing canvas, not the incoming canvas that allegedly received the draw.
   - Missing `canvasId` passes because membership is checked only when it is non-null.
   - Missing `hashNum` and `sceneHash` passes because an unknown hash is not rejected.
   - There is no upper boundary-window limit. `hash2` is unused, and events are collected after the later restart run, so a draw at an unrelated later hash can satisfy Finding 1.

   Concrete false-positive: outgoing canvas O is player-bound to decoder D and supplies stable 2D samples; later, an incoming canvas gets one geometry-selected prepaint from D—or an event with no canvas/hash provenance. `feedEngagedAt1to2` becomes green even though the incoming canvas was never player-bound to D during the sampled after-window. I directly exercised the function: events at hash `#99`, with `authoredBy:"geom"`, and with canvas/hash/authorship fields missing all returned `ok=True`.

2. **High — The boundary resolver has replaced the old whole-deck fallback with another whole-deck fallback.**  
   [`_extract_movie_layers`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:170>) and [`_derive_movie_texids`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:329>) accept the sole footprint-sized `contents` tween anywhere in the deck when any ancestor name merely contains `"magic-move"`.

   There is no requirement that:

   - the ancestor be an `apple:magic-move-*` transition,
   - the tween have video-layer ancestry,
   - it belong to the 1→2 boundary, or
   - it be tied to `movie1`.

   Concrete false-positive: slides 1/2 contain no resolvable boundary; slide 4 contains a footprint-sized nonmovie shape under `apple:magic-move-*`. Its P→Q tween becomes `movie1` outgoing/incoming. Even an ancestor named `not-a-magic-move-caption` is classified `withinMagicMove=True`; I verified that directly.

   The poster-absent regression is meaningful for this fixture, but the selected remedy is over-broad.

3. **High — Repeated real boundaries are still hidden by `(from,to)` deduplication.**  
   [`_derive_movie_texids`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:337>) groups all occurrences under one `(from,to)` key and tests only `len(movie_cfs) == 1`. `boundaryOccurrences` is diagnostic only.

   Concrete failure: P→Q appears at both 1→2 and 3→4. The resolver accepts it as one unique boundary, despite being unable to identify which occurrence is gated. [`test_f3_repeated_pair_provenance_is_preserved`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/tests/test_p2_adversarial.py:167>) explicitly locks in this fail-open behavior by expecting successful resolution.

4. **High — Decoder ownership is keyed to reusable canvas IDs, and multiple same-key decoders can still feed.**  
   [`authoredDecoderByCanvasId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:502>) stores `canvas.id → video`, not canvas-element identity.

   Concrete stale-ID failure: player draws decoder D into canvas element C1; C1 is removed during the observed rebuild; new element C2 reuses the same texture ID and creates a 2D context but has not drawn a video. [`boundDecoder`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:794>) returns D for C2, prepaint labels it `authoredBy:"player-draw"`, and [`footprintOwnerDecoderId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:470>) reports D. This recreates the stale-ID alias that F4 removed from context ownership.

   Ownership is also only per canvas, not one decoder for the cut. If sibling D1 is player-drawn into outgoing O and sibling D2 into incoming I, both active rVFC loops feed their respective canvases. For equal-overlap stacked canvases, `footprintOwnerDecoderId` silently chooses the first map insertion. If I/D2 wins, samples are stable on D2 and the incoming event from D2 passes, even though D1 is simultaneously feeding O. This violates “startTextureFeed runs for that one element only.”

5. **Medium — Steady folding does not use the resolved crossfade owner.**  
   [`_fold`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:361>) ignores `occs[*]["owner"]`. It instead finds whichever slide steady owner contains the endpoint texture.

   Concrete failure: a crossfade owned by object A has endpoint P, while object B’s steady set contains `{P, P2}`. The resolver folds P2 from B. If the crossfade owner is `None`, it can still fold an identified steady owner containing P, so owner-`None` is not actually non-foldable.

   The current F5 test does exactly this structurally: `_magic_move(...)` is a sibling of the video nodes, so the crossfade owner is `None`, yet the test expects A2 to be folded.

6. **Medium — Failed player draws can establish false authorship.**  
   The draw wrapper records ownership before delegating to the original draw in [`installDrawRecorder`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:538>).

   Concrete failure: the player attempts `drawImage(video, …)` while the video is invalid or otherwise causes the original call to throw. The map still records that video as the authored decoder; a later feed can use the false binding.

7. **Medium — The 17 tests do not protect the integrated ownership seam.**  
   The direct `_times` tests and the basic scorer-condition tests are load-bearing. Important gaps remain:

   - No test proves `feedEngagedAt1to2` is still folded into `continueThroughMagicMove1to2`.
   - No collector test ensures engagement events survive.
   - No rejection tests for `authoredBy:"geom"`, missing hash/canvas, event context mismatch, or draws after the boundary window.
   - No JavaScript tests for stale canvas IDs, two sibling decoders feeding separate slots, failed authored draws, or footprint-owner ties.
   - The “before boundary” test only rejects `hashNum < hash1`; it does not test unknown or later hashes.
   - The repeated-pair test enshrines acceptance rather than rejection.
   - The poster-absent regression is useful for the fixture but also protects the over-broad whole-deck structural selection.

## Clean checks

- `continueThroughMagicMove1to2` does explicitly include `feed_engaged.ok`; the fold itself is correct.
- Two distinct footprint Magic Move pairs fail closed as ambiguous.
- `from` maps to outgoing and `to` to incoming, with `from != to`.
- `movieTexids()` now correctly requires both sides.
- The required engagement event kinds are retained by the collector.
- The getContext change is clean: target feed/prepaint paths check the element’s own stamp before calling `getContext('2d')`; there is no ID fallback. The unguarded calls create private diagnostic canvases, not player target canvases.
- `feedDraw` has no asynchronous gap and resets the flag on exceptions. There is no currently reachable nested `feedDraw` call, although the boolean would not preserve an outer value under true nesting.

Pytest could not start because the read-only environment provides no writable temporary directory. Module import and targeted direct scorer/extractor probes succeeded. No files were changed.