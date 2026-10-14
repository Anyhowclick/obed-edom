# W6 live3 fold 4 — review r4 (2026-10-14)

Build on your uncommitted diff. Read `.agents/reviews/cef-placement-2026-10-13/review-live3-r4.md` fully. Fold BL-A and M-A only
(lows are not folded this round).

- BL-A: record DSK first-rVFC timing only for the outgoing holder-bound decoders (those with region + detach; on the historic
  m-snap-cef-dsk dump exactly ids 9/10) and have `media_integrity` compare by paired decoder id. Add a row to the existing table
  whose `vids` include extra prior-slide decoders (as on the real dump). Verify the new record function on the historic
  `m-snap-cef-dsk/record.json` (read-only; use a clone) yields exactly the two bound decoders.
- M-A: tie the +5 s to the decoder bound to the `#t=5` clip (not abs()); tolerance ≤0.25 s, skipping a leading preroll record at
  mediaTime 0 if present. Additionally require the two holder strips' decoded frame indices to differ by 5 s × counter fps ± 3
  frames (derive fps from the pinned counter movie, do not hard-code), fail closed (INCONCLUSIVE) otherwise.

Fewest test additions; parametrize existing tables. Re-score the 25 fps run (fresh APFS clone, baseline mode).
Report → `SCR/impl/W6-live3-fold4-report.md`: per finding fix + file:line, tests with exact counts, re-score table, open items.
