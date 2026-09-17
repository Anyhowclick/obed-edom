# dsk-clip-timing review round 1 — reconciliation (Claude high-effort + GPT-5.6 Sol)

Scope: `git diff origin/main` for branch integrating visual-order clip naming + offline
movie-start timing + assembler wiring. Full suite green before review (3494 passed, 87
skipped; only the 3 pre-existing maps failures). Codex raw output: `codex-r1.md`.

## Findings folded (owner "go" 2026-09-17)

- **B [MAJOR, both]** `web/app.py` published clip order was recomputed from crop rects,
  diverging from the assembler's item/fitted-rect order → naming↔timing mismatch; also a
  `rects[mid]` KeyError when `crop_rect` is None. Fix: publish from `result.clips_inserted`
  (authoritative visual order), delete the crop-based pre-assembly order; rewrite the
  dashboard visual-order test + fix malformed `clips_inserted` mocks.
- **A [MAJOR flagged, latent in practice]** `iwa_movies.patch_clip_start_timing` permuted
  only within existing movie-chunk slots, so After-Transition was not pinned to absolute
  `buildChunks[0]`, and verify was self-referential. GOLD CONFIRMATION (offline read of
  `Alpha_DSK.key` slides 6–8 and the r16 generated DSK deck): live overlays are STATIC (no
  build chunks); every build chunk on a clip slide is a movie-start, so the movie chunk is
  at position 0 naturally and the timing RULES match the gold (leftmost continuity = After
  Transition, second = With Build 1). Fix is safe hardening: front-load `target_order`, keep
  non-target chunks after, verify explicit positions 0..n-1.
- **D [MINOR, both]** `_restore_clip_timing` did not assert `clip_timing` is a 1:1 permutation
  of the inserted clips. Fix: refuse (`AssemblyRefusal`) on missing/extra/dup.
- **E [MINOR, Claude]** `_restore_clip_timing` discarded `patch_clip_start_timing`'s verified
  return and re-read the whole deck once per slide. Fix: consume the return.

## Owner decisions
- **A**: confirm against gold first (done — see above). Hardening applied; no real-deck change.
- **C [Codex only]**: the deckless "guess all-distinct" fallback affects only planning-only /
  test callers (live apply always resolves `objects_graph` via `fw_deck`). Owner: KEEP the
  fallback, document why. No refusal added.

## Dropped
- Claude candidate "delay 0.0 may not round-trip" — false positive; tests round-trip it
  through the real `IWAFile` codec and pass.
