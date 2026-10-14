# W6 live3 fold 1 — review r1 + owner decisions (2026-10-14)

Your uncommitted diff from the previous pass is in the worktree; build on it. Review: `.agents/reviews/cef-placement-2026-10-13/review-live3-r1.md`
(read it fully). Your previous report: `.agents/reviews/cef-placement-2026-10-13/impl/W6-live3-report.md`.

Owner decisions (binding):
- O-M1 near-clip strip: GEOMETRY-AWARE. When decoder content + holder `canvasRect` show the counter strip lies outside the holder
  canvas, record "strip clipped by geometry" (not an integrity failure) and prove frame identity with the paused rVFC reference
  check. No fixture change. Fail closed when the geometry does not prove the strip is outside (partial overlap / unreadable → as today).
- O-cut: `cut` is REPORTED in the CEF_PLACEMENT profile (inherited, fix lives with the dissolve follow-ups). cut-on/cut-off still run.
- O-scope: fix the edge-band (m-snap-cef, wrongrule-cef) and DSK cells in this PR.
- Coordinator (plan §0/§2.7/§5 W5, review M3): `tone` REPORTED in CEF_PLACEMENT (identity take); keep mask and the
  "CEF placement tone observation" check enforced; `m-tone-raw-cef` stays the identity negative.

Tasks:
1. M1 per O-M1, applying to near cells and their twins; add a scorer row for a correct near clip (positive MATCH) built on real
   p2bin geometry.
2. M2: `_clip_near` shifts every child of `parent["layers"]` by the same amount; test that every child's absolute near edge is
   unchanged (not via the helper's own model). Then determine from the live records/images whether the m-snap-cef / wrongrule-cef
   empty edge band has the same cause (foreground texture placement) or another; fix the harness layout if unambiguous so the
   verified mask leaves edge-band pixels (§5 requires interior AND edge — do not redefine the band).
3. M4: explicit `Arm` field (e.g. `strip="displaced"`) instead of the splice substring; drop the twins' trigger-only `expect`;
   add the attribution check (holder region ≈ live reference shifted by the predicted displacement within τ over the overlap);
   reconcile with O-M1 since the displaced strip may also be off-canvas.
4. M3 + O-cut profile changes.
5. DSK (`m-snap-cef-dsk`): investigate whether its two decoders can play existing pinned counter-strip movies (reuse an existing
   fixture/splice path; no new fixture bytes) and whether 5 mid frames are reachable by existing capture settings. Implement ONLY
   if it is a reuse with no §5/§11 contract change; otherwise write a concrete proposal (files, fixture, contract delta, risk) and stop.
6. L3: tests that would have caught M1/M2; fewest additions, parametrize existing tables.
7. Re-score the 25 fps run (fresh APFS clone, tool baseline mode) and report the per-arm table, noting which cells only a live rerun
   can settle.

Report → `SCR/impl/W6-live3-fold1-report.md`: per finding fix + file:line, tests with exact counts, re-score table, open items.
