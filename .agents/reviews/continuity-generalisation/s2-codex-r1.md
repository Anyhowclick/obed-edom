## Standards

PASS — no actionable standards violations or code-smell findings. The extensive runtime comments document non-obvious browser lifecycle behavior and frozen instrument contracts, so they are justified despite the minimal-comment standard.

## Spec

1. **MAJOR · new class — R2 filtering happens after pairing.**  
   [live_continuity.py:1562](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1562)

   Pairing includes instances that Keynote excludes because they build in/out; R2 is applied only afterward at line 1574. A built-out source can therefore take the nearest destination, be refused, and leave another source carrying to the wrong destination. Example centres: sources A=100 (builds out), B=200; destinations C=100, D=400. The code chooses A→C and B→D, then refuses A→C. Keynote excludes A and pairs B→C.

   Fix: exclude attributed R2 candidates before assignment, or conservatively refuse every pair for that asset at the boundary. Add a repeated-instance R2 test; current tests cover only isolated pairs.

2. **MAJOR · new class — nested builds bypass R2.**  
   [live_continuity.py:1365](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1365)

   `_build_targets` examines only immediate `event.effects`. Keynote “with previous” builds can be nested, which the probe already handles recursively. A nested build targeting the continuing movie is therefore carried instead of refused.

   Fix: recursively traverse effect trees, while exempting the complete movie-start effect subtree. Add nested attributed and unattributed R2 tests; `_add_build` currently inserts only top-level effects.

3. **MAJOR · edge case — overlapping asset names break restart retirement.**  
   [live_continuity_js.py:1345](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:1345), [live_continuity_js.py:2022](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:2022)

   `movieAssetKey` returns the first substring match. Python orders assets alphabetically, so plans containing `a.mov` and `ba.mov` assign `a.mov` first; a fresh `ba.mov` is classified as `a.mov`. `retireRestarted` then skips the actual `ba.mov` restart entry, leaving its carried overlay alive beside the fresh decoder.

   Fix: match canonical normalized asset names exactly, or fail derivation when asset keys are not uniquely matchable. Apply the same rule to the probe’s `matches_asset_keys`; add an overlapping-name restart test.

4. **MAJOR · edge case — a cut can emit an impossible restart for a web destination.**  
   [live_continuity.py:1600](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1600)

   `_cut_movies` checks only `src.kind`. A carried local video followed by a same-key destination marked `isStreaming` derives `restart`, although that destination creates an `<iframe>`, not a `<video>`. Consequently the video-only hook at [live_continuity_js.py:2041](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:2041) never calls `retireRestarted`, and the old held decoder can linger.

   Fix: require an eligible destination video before emitting `restart`; otherwise derive an R7 refusal/retire. Add a carry→cut→web test.

5. **MINOR · new class — retire qualification remains asset-wide, not instance-wide.**  
   [live_continuity_probe.py:2166](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2166), [live_continuity_probe.py:2757](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2757)

   The pool and event checks ignore the available source `objectId`/instance stamp. A legitimate same-asset sibling carry can falsely fail a retire; conversely, that sibling’s retirement note can satisfy a missing target-instance note. D1–D6 do not exercise “one same-asset instance retires while another continues.”

   Fix: bind snapshots, refusal notes, retirement notes, and carry events to `srcObjectId` and the associated decoder IDs. Add positive and missing-note sibling tests.

6. **MINOR · edge case — glReplay omits the carry-time loop guard.**  
   [live_continuity_js.py:621](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:621)

   `glCarried` checks objectID, geometry, liveness, and uniqueness but never compares `v.loop` with `GL.loop`. The ordinary pin/bridge path does, and §2.4 requires the check for glReplay too.

   Fix: reject the candidate before memoisation when its loop state differs, causing the existing retire fallback. Add a real-seam loop-mismatch test.

The reported green gates establish D1–D6/P2 behavior, but these uncovered shapes are outside that corpus. The detach a1 and settled-position Pass G changes do not interact with the findings above. No tests were run during this review.

**VERDICT: FAIL — four MAJOR safety gaps block S3 from removing `QUALIFIED_PLAN_SHA256`; Standards 0 findings, Spec 6 findings.**