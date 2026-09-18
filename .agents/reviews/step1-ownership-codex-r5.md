Round 5 is **not clean**. Both r4 defects are fixed in their stated scenarios, but the ownership rewrite introduces one new High fail-open edge.

## Findings

1. **High — zero-overlap canvases can become the footprint owner.**  
   [`footprintOwnerDecoderId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:479>) collects every authored, visible-sized canvas but never requires `rectOverlapArea(...) > 0`.

   Concrete failure:

   - One same-key authored canvas exists completely outside the requested footprint.
   - Its overlap is `0`.
   - `bestOverlap=0`, `tol=1`, so it enters `near`.
   - The function returns its decoder with `via:"player-draw"` instead of unresolved.

   I executed the exact checked-in function and obtained:

   ```text
   zero overlap single → {elId:"D1", key:"movie1", via:"player-draw", contextType:"2d"}
   ```

   This can bind continuity and engagement to a remote canvas while the scored ROI is supplied by unrelated content or another decoder. The previous implementation returned null for zero overlap, so this is a round-5 regression.

2. **Medium, latent — an unresolved footprint key disables key filtering.**  
   At [line 484](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:484>), `wantKey == null` admits every movie key.

   Concrete scenario: an unrecognized rect overlapping only a movie2-authored canvas returns movie2 as `player-draw`, rather than unresolved. The current caller supplies the exact known `MOVIE_ROI`, so this does not presently affect Finding 1, but the helper itself is not fail-closed.

## Verified closed

- **r4-F1:** Correct. Draws at `hash1` are always rejected; unparseable `hash1` rejects all; regressive `hash2=#0` cannot admit `#1`; `#2` and the real `#4` cut count; `#6` is excluded.
- **r4-F4 ordering:** The `D1=100000, D2=104000, D1=106000` set returns ambiguous in all six DOM permutations. Multiple canvases owned by D1 resolve to D1; exact D1/D2 siblings return ambiguous. The near-band cannot be empty when candidates exist, and the 5% boundary is correctly inclusive.
- **F2:** Still requires `type == "transition"` plus the Magic Move prefix. The real artifact resolves movie1 `0885… → A223…`.
- **F5:** Still emits only `[from]` and `[to]`; no steady folding.
- **F6:** Ownership is recorded only after the original `drawImage` succeeds.
- **F1 guards:** Authorship, incoming slot/canvas, bound decoder, 2D context, known hash, and restart boundary checks remain intact.
- The saved slow-profile report keeps Finding 1 RED on `motionAcrossFlipOk`, `stableDecoder`, `contextType2d`, and `incomingFeedDraw`; Finding 2 passes. Its restart verdict is the documented capture-timing inconclusive result, and round 5 did not alter restart logic.

Validation: all 21 no-filesystem adversarial tests passed; Python and injected-JavaScript syntax passed. The environment has no writable temporary directory, so I could not independently rerun the complete 92-test suite or both offline profiles. No files were changed.