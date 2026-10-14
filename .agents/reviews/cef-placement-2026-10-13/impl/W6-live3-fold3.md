# W6 live3 fold 3 — review r3 (2026-10-14)

Build on your uncommitted diff. Read `.agents/reviews/cef-placement-2026-10-13/review-live3-r3.md` fully. Reviewer scratch: `SCR/r3/`.

Decisions (binding, coordinator under owner delegation):
- BL1: option (a). Remove the forced holder_pixels FAIL entirely and the "integer-phase backing" path; attribution only gates
  (non-PASS → INCONCLUSIVE), the pixel scorer's own verdict stands. Add a harness-only in-memory slide override scoped to
  `m-snap-cef-nooffset-y` and its twin that moves the near-y video so the dropped y offset (stage-local origin) is well inside the
  content height (target ~100–150 css px displacement) while keeping the corrected near-y clip semantics (near edge clipped,
  strip outside per O-M1 or decodable). The existing displaced-content attribution then applies and a real pixel FAIL must result.
  Prove on real p2bin geometry offline; add the row "correct (offset-included) holder on this geometry → holder_pixels PASS,
  arm MISMATCH/not MATCH".
- BL2: make the second DSK decoder really start at 5 s in a way the player honours (e.g. `#t=5` media fragment on that clip's URL
  in the in-memory doc; served bytes and path unchanged). Verify against the actual DSK/p2-binary `main.js` how `src` is set.
  Add a fail-closed check (record + scorer) that the two decoders' first rVFC mediaTimes differ by ≈5 s (tolerance from frame
  period); otherwise INCONCLUSIVE. Replace the offline test that models `media + 5.0` with one driven by the doc rewrite.
- M1: route non-alias movies of the DSK arm through the existing `h264_copy` path, as `cef-skip-dsk` does.
- L1/L2: add the cost-representativeness note and the underlay-omit inheritance to your report.

Fewest test additions; parametrize existing tables. Re-score the 25 fps run (fresh APFS clone, baseline mode).
Report → `SCR/impl/W6-live3-fold3-report.md`: per finding fix + file:line, tests with exact counts, re-score table, open items.
