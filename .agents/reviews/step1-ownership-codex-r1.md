## Findings

1. **High — The Finding-1 gate can pass without any ownership or feed-engagement proof.**  
   [`_run`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:1678>) gates only continuity, hash change, visible motion, index progression, and player errors. It does not require:

   - resolved texids,
   - `motionAcrossFlip.ok`,
   - stable per-sample decoder identity,
   - a non-null/2D `contextType`, or
   - a `texture-feed-draw`/`mo-prepaint-draw` event at the 1→2 boundary.

   Worse, event collection omits `texture-feed-draw`, `texture-feed-skip`, `texture-feed-skip-canvas`, and `mo-prepaint-skip` ([event filter](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:1527>)). Concrete false-positive: texid resolution returns null, the id-bound feed never engages, and all motion samples have null ownership; a remounted DOM video or ordinary player motion can still satisfy continuity/visible-motion/index and produce green. This directly violates Step 1’s “engagement at #1→#2 is provable in events” endpoint and is fail-open by absence.

2. **High — Feeding is still asset-key-bound, not bound to one exact decoder.**  
   [`boundDecoder`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:763>) overwrites `best` for every ready same-key decoder and returns the last enumeration result. Independently, every active same-key decoder passes the check in [`startTextureFeed`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:849>) and draws into every matching canvas. With two ready `movie1` decoders, both rVFC loops race to paint the same outgoing/incoming canvases.

   `footprintOwnerDecoderId` then chooses the first equal-overlap feed state, not necessarily the decoder that painted last ([selection](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:470>)). Thus decoder A can supply the scored clock while decoder B supplies the visible pixels. The other-movie ready fallback is gone, but defect #4’s same-key sibling hole remains.

3. **High — Texid derivation still accepts a whole-deck spurious `contents` tween.**  
   [`_derive_movie_texids`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:267>) accepts the sole deck-wide footprint-sized crossfade whenever no steady-anchored boundary exists ([fallback](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:275>)). Therefore a same-sized nonmovie `contents` tween on slide 4 becomes the claimed 1→2 boundary if slide 1/2 data is missing, unreadable, or simply does not anchor it. No warning is emitted.

   Additionally, `set(crossfades)` discards occurrence provenance. The same pair repeated at multiple boundaries becomes one “unambiguous” pair. This does not satisfy “require the crossfade be the one at the gated boundary.”

4. **High — The context-type ID cache can turn a passive observation into the forbidden probe.**  
   [`recordedCtxType`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:535>) falls back from the element stamp to a permanent `canvas.id → type` map. If an old 2D canvas `X` is removed and a newborn canvas reuses ID `X` before the player calls `getContext`, the new element is incorrectly reported as already 2D. `moFeedCanvas` then calls `newCanvas.getContext('2d')`, creating the context and potentially breaking the player’s later WebGL request. The resulting event misleadingly reports a passively observed 2D context.

   The wrapper otherwise delegates correctly, and an ID assigned after `getContext` on the same element is handled by `__obedCtxType`; the stale-ID alias is the defect.

5. **Medium — Steady-texture folding can target another same-sized movie’s canvases.**  
   After resolving one crossfade, the producer unions every footprint-sized steady texture from slides 1 and 2 into the respective slots ([return construction](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_adversarial.py:291>)). Example: steady sets `{A, X}` and `{B, Y}`, with unique boundary `A→B`. The output becomes outgoing `{A,X}` and incoming `{B,Y}`, so movie1 is fed into the unrelated same-sized movie’s `X/Y` canvases. Size equality is not authored-object identity.

6. **Medium — The new tests are not load-bearing for the changed integration.**  
   [`test_frozen_bound_clock_fails_despite_sibling_higher_clock`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/tests/test_html_alpha_probe.py:413>) supplies only an already-collapsed frozen vector and explicitly supplies no sibling. It never calls `_times`; reverting the decoder-ID filter would leave the test green.

   The handoff/restart tests exercise the unchanged `score_motion_across_flip`, whose relevant behavior already had coverage. Since `motionAcrossFlip.ok` is not part of the actual finding gate, those tests remain green even with the integration hole in finding 1. There are also no tests for crossfade provenance, multiple same-key decoders, stale canvas IDs, or feed-event gating.

7. **Low — A one-sided texid object is treated as valid despite being malformed/unresolved.**  
   [`movieTexids`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:744>) accepts the object when either set is nonempty. For example, `{"decoderKey":"movie1","outgoing":[],"incoming":["X"]}` enables feeding rather than producing `mo-no-texids`. A genuine `from != to` boundary necessarily supplies both sides, and the function’s own comment says empty slots should yield null.

## Explicit category results

- Texids: defects 3 and 5; ambiguity is not sound.
- One-decoder binding: defect 2. The geometric `feedCanvasFor` fallback and other-key ready fallback are gone. Normal filename casing and ordinary query strings are handled.
- Passive `getContext`: defect 4. Delegation itself is correct.
- Max-of-same-key clock: no defect in `_times` when `decoder_id` is supplied; a direct check returned the frozen bound decoder rather than the advancing sibling. Selection and gate integration remain defective via findings 1–2.
- Scoring/tests: defects 1 and 6.
- Fail-open/null handling: defects 1 and 7.

The pytest suite could not start in this read-only environment because `tests/conftest.py` requires a writable temporary directory. No files were changed.

Skill used: [obed-edom/SKILL.md](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/.agents/skills/obed-edom/SKILL.md>).