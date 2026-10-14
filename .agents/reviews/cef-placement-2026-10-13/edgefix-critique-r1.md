# Edge-fix plan critique r1 (Opus 5.5 high), 2026-10-14 — approve with changes

Verified: diagnosis on all 4 takes (live compositor uses a pixel-centre, non-antialiased rule on all four edges: col 109 0.648
covered → full video; row 795 0.964 → full video; col 1061 0.35 → background 0; row 1063 0.036 → background 0); JS scope and no
collisions; node --check; splice anchors still unique; one-pixel source crops correct under clamp or neighbour-read; pins for the
plan literal dd8f692d… / c40d6baa…, off and rendering unchanged; invariants kept.

- Major 1: cells whose pixel centre lies outside the frac quad get background live; fail closed for frac:
  `if(fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5)return;`; two-cell case becomes an offline refusal row.
- Medium 2: fallback (disable frac) is the owner's call — stop and escalate. Medium 3: ≤2 LSB target is scope creep; gate on τ=4,
  report the residual. Medium 4: new four-side/phase arms are an owner decision with gate cost; use the pixel-centre evidence +
  Node coordinate tests. Medium 5: repair after getImageData may change raster backend/cost — boundary residual and DSK ≤50 ms are
  explicit pass criteria of the first scratch run. Medium 6: drop dissolve_probe scorer tests (unchanged code).
- Low 7: drop the unconditional first/last ring (3 draws instead of 8). Low 8: managed runner has no --arms; dissolve_probe
  --arms is headless Chrome only.
- Scratch subset: a wrapper may set managed_obs_qualify.PLACEMENT_ARMS (read at call time) to opaque-off, m-tone-cef(+twin),
  m-snap-cef(+twin), wrongrule-cef(+twin), m-snap-cef-underlay-omit, the four near/far clip cells(+twins), m-snap-cef-dsk,
  m-fg-cef, m-fg-omit-cef, then call main([... "--arm","placement","--takes","1"]); read per-arm results only.
