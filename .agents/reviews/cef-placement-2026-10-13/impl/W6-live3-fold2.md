# W6 live3 fold 2 — review r2 + DSK decision (2026-10-14)

Build on your uncommitted diff. Read `.agents/reviews/cef-placement-2026-10-13/review-live3-r2.md` fully, and your
`.agents/reviews/cef-placement-2026-10-13/impl/W6-live3-fold1-report.md`. Reviewer scratch (capture hook `cap.py`, `nooffx.npz`,
`nooffy.npz` attribution inputs): `SCR/r2/`.

Decisions (binding):
- Owner: DSK — point both DSK decoders at the existing pinned counter movie. Coordinator (per r2): each decoder must keep a
  distinct, checkable frame identity (distinct seek offsets of the same pinned counter movie, or two existing pinned counter
  movies) so a swapped holder↔decoder binding is detected; no new fixture bytes; holder strips must decode. Do NOT add a new capture
  source and do NOT lengthen the transition now — the 2A DSK screenshots took ~190 ms vs ~100 ms on `on` at lower load (real
  church-video decode/PNG entropy); the live rerun measures cadence. Record per-shot duration so the rerun shows it. If the counter
  movie is opaque where the clips had alpha, report what that changes for the DSK gates.
- Coordinator: nooffset-y (r2 M1) — attribute explicitly that the holder matches the integer-phase backing (fail closed if not);
  no weak negative.

Tasks: B1 + M2 (move inset foreground clear of the strip rows/cols; one layer crosses a holder/video edge by several device px;
synthetic painter handles `edgefg`; assert strip decodes AND interior + edge kept); B2 (bracket comparison at fractional
displacement, discriminating d±2 FAIL, d=5.37 row; correct the τ statement); M1 per decision; L1 wording in your report; L3 —
fail closed (raise) if the parent has a non-zero bounds origin or a transform; DSK per decision with tests (distinct identity,
swapped binding → detected). Fewest test additions; parametrize existing tables.

Re-score the 25 fps run (fresh APFS clone, tool baseline mode) and confirm historic nooffset-x attribution now PASSes at its true
phase. Report → `SCR/impl/W6-live3-fold2-report.md`: per finding fix + file:line, tests with exact counts, re-score table, open items.
