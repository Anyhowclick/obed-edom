## Findings

- BLOCKER: none.
- MAJOR: none.
- MINOR: none.

## Verified sound

- `stsd` parsing now validates entry count, sample-entry bounds, minimum size, and printable fourcc bytes.
- Codec reporting probes every distinct resolved file, fails closed on disagreement or unreadability, and the added `files`/`mixed` fields do not break existing consumers.
- DOM instance checking does not falsely reject the fixture’s healthy cases:
  - Slide 1’s two instances occupy distinct rectangles.
  - Slide 3’s authored-layer remount matches its expected rectangle.
  - Slide 4’s body overlay matches while the opacity-zero suppressed sibling is excluded.
- Pixel-inconclusive slides remain inconclusive; instance evidence only downgrades pixel-green results.
- Each visible pass independently gates stage fit, and clipped expected rectangles are instrument errors.
- `stopError` prevents the overall probe from passing.
- `retireSlot()` only removes bridged decoders whose generation is obsolete or continuity is disabled; those nodes are no longer legitimately owned by the active slot.
- ProRes and VP8 mappings are corrected.
- Tests meaningfully cover the malformed parser cases, per-file aggregation, mixed/unreadable host behavior, measured duplicate geometry, stage transformations, clipping, stop failures, and connected-slot retirement.

Static read-only review only; no tests, browsers, or files under `scripts/` were executed.

**VERDICT: PASS**