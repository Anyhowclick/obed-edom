## BLOCKER

None.

## MAJOR

None.

## MINOR

None.

## Verified sound

- `reidentify()` preserves normalized same-asset assignments, including query strings and export suffixes. Facade reuse and the fresh same-asset 3→4 bridge remain intact.
- Different assets are removed from all pool queues, lose the preserved marker, and receive the correct planned or null identity.
- Pool snapshots and census attribution fail closed for unattributable entries.
- The settled-ROI check is non-vacuous in the runtime path: the ROI list comes from the same samples as `flipIndex`, and at least four after-pairs require at least five post-flip frames. Every frame is checked for non-black content and settled-frame equality.
- Hash movement is strictly parsed and forward-only.
- Geometry values, including `scale`, affine elements, anchors, and clipping values, are finite-number guarded.

Static review only; no tests, browsers, edits, or scripts were run.

**VERDICT: PASS**