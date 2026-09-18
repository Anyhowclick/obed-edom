Round 4 is not clean. Two High fail-open edges remain.

## Findings

1. **High — the lower bound is not guaranteed to be strictly after `hash1`.**  
   [`_score_feed_engaged`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:442>) uses `n2` whenever parseable, without verifying `n2 > n1`. It also leaves `lower=None` when both hashes are unparseable.

   Concrete results:

   - `hash1=#1, hash2=#2, draw=#1` → correctly rejected.
   - `hash1=#1, hash2=#0, draw=#1` → incorrectly accepted.
   - `hash1=bad-a, hash2=bad-b, draw=#1` → incorrectly accepted.

   Therefore a pre-advance `hash1` draw can still satisfy `incomingFeedDraw` when flip metadata is regressive or unparseable. That violates the stated fail-closed contract.

2. **High — decoder ambiguity remains DOM-order dependent.**  
   [`footprintOwnerDecoderId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:471>) keeps only one `ambiguous` boolean. A later better canvas resets it without reconsidering previously seen distinct decoders against the new best overlap.

   Concrete overlap sequence in DOM order:

   - D1 canvas: `100000`
   - D2 canvas: `104000` → marked ambiguous with D1
   - another D1 canvas: `106000` → becomes best and clears ambiguity

   D2 remains only 1.9% below the final best—inside the intended 5% tolerance—but the function returns D1. Reordering the same canvases returns ambiguous. Thus D1 can own the incoming draw while D2 simultaneously feeds outgoing pixels and the gate can still see a stable D1.

   The nominal cases work: two exact sibling owners return null, and two stacked canvases owned by the same decoder are not ambiguous. The defect is the multi-canvas ordering case.

## Verified closed

- `hash2=#2` is the correct observed flip anchor; `hash1=#1` is rejected and the real `#4` cut event lies inside `[2,6)`.
- The real deck’s Magic Move node is `type:"transition"`, and texids still resolve to movie1 `0885… → A223…`.
- A non-transition node bearing the accepted name is rejected.
- The two new tests are load-bearing for their direct regressions, but they do not cover regressive/unparseable hashes or JavaScript tie ordering.
- The `#6` exclusion is an acceptable fail-closed Step-2 residual. JS-level multi-feeder enforcement would also be acceptable as Step 2 once the ownership gate is fully order-independent.
- The current offline artifact keeps Finding 1 RED through `motionAcrossFlipOk`, `stableDecoder`, `contextType2d`, and `incomingFeedDraw`.

I directly ran all 17 no-filesystem scorer tests successfully. The read-only environment prevented an independent full pytest run because the suite creates a temporary directory. No files were changed.