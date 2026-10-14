# W6 live4 fold — harness/instrument fixes from the 2026-10-14 live passes

Read `.agents/reviews/cef-placement-2026-10-13/impl/W6-live4-report.md` (your diagnosis). Implement ONLY items 2 and 3:

- Item 2 (HARNESS): `NOOFFSET_Y_DISPLACEMENT` so the nooffset-y content sits at y=-80 (near clip 27.42…187.61, clear of the
  event-2 image at y≥190, displacement 80 < content height). Prove offline on real p2bin geometry: no visible later-painted
  element overlaps the clip region, the strip stays outside the clip, the displaced-content attribution overlap is non-empty.
  Update the existing table rows.
- Item 3 (INSTRUMENT): foreground scoring keeps τ for the direct holder candidate; demixed candidates use the amplification-aware
  bound the region scorer already uses (τ/(1-e)) or the pre-division residual — reuse that code, do not raise τ globally.
  Add/extend a table row reproducing the live case (e=0.7994, one-LSB perturbation → passes; a real foreground defect at the same e
  still fails).

Do NOT touch item 1 (product edge row) — a separate stream handles it in src/. Fewest test additions; parametrize existing tables.
Re-score today's four live takes offline with the final code (fresh APFS clones of SCR/live4/out; the rescore tool is SCR/tools/rescore.py,
or call managed_obs_qualify.placement_gates directly) and report per-arm outcomes per take.
