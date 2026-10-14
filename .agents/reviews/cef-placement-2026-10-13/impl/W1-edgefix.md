# W1 edge fix — frac boundary redraw (2026-10-14)

Owner decision: try a product fix for the m-snap-cef top-edge residual (live4: interior 2, edge 9, τ=4, 15 px on row 795).
Plan: `.agents/reviews/cef-placement-2026-10-13/edgefix-plan-astra.md` (Astra high). Critique (Opus 5.5 high, approve with
changes) is folded below and overrides the plan where they differ. Diagnosis: `impl/W6-live4-report.md` §1.

Files: `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` only.

Implement plan steps 2 and 5, with these changes:
1. Fail closed for frac before drawing when any holder cell's pixel centre lies outside the fractional quad — the live compositor
   paints background there (pixel-centre, non-antialiased rule on all four edges), which no canvas fix can match:
   `if(fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5)return;` (place it so no holder is created and the existing `finally` still
   publishes take time). The recorded live geometry (fx 0.3517, fy 0.0362, fw 952, fh 268, ww 952, hh 268) must pass it.
2. Redraw only partially covered rows/columns: use `ei<fx||ei+1>fx+fw` and `ei<fy||ei+1>fy+fh` (drop the unconditional
   first/last ring terms). On the live geometry that is 3 draws. Fully covered pixels keep the fractional draw byte-for-byte.
3. Keep the whole-backing alpha scan BEFORE the repair (underlay-omission refusal unchanged); repair draws, then foreground
   (`Y.forEach`) as today. Snap path byte-identical at DPR 1/1.5/2 apart from the single `pl` compare.
4. Pins: recompute `SUPPORTED_PLAYERS[*][0]` and test `REAL_PATCHED_SHA256[*][True]` for both stock players from the final bytes
   (the critique's values for the plan's exact literal were dd8f692d… / c40d6baa…; yours will differ after changes 1–2). `[1]`
   and `[2]` must stay unchanged — assert that. Record the previous values in the existing pin-history comment.
5. Tests (minimal, extend existing Node trace/case tables in tests/test_live_runtime.py only): exact live geometry → the 3
   boundary draws with exact source coordinates, order snapped → frac → scan → boundary → foreground, unchanged holder geometry;
   an out-of-quad-centre geometry (the plan's fx=-0.47, fw=951, ww=952 case) → no holder; frac alpha rejection → zero repair
   draws; snap cases (incl. DPR 1.5/2) unchanged. No dissolve_probe scorer tests.
6. Update the `patch_player` docstring sentence on frac minimally.

Do not touch scripts/ or the plan file. Fallback is NOT pre-authorised: if something makes the fix unimplementable, report and stop.
