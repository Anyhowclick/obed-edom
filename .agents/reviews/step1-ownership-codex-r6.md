Round 6 is not fully clean. The two r5 defects are closed, but one narrow fail-open edge survives.

## Finding

1. **High — floating-point rounding can exclude a decoder exactly on the inclusive 5% ambiguity boundary.**

   In [`footprintOwnerDecoderId`](</Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/scripts/p2_recovery_html_dissolve_live.py:498>), the comparison at line 502 is numerically brittle.

   Concrete scenario using the exact checked-in function:

   - D1 covers the full ROI: overlap `255136`.
   - Same-key D2 covers exactly 95% using a normal fractional DOM width of `904.4px`.
   - Computed D2 overlap: `242379.19999999998`.
   - Computed cutoff: `242379.2`.
   - Mathematically D2 is exactly within the inclusive 5% band, but floating-point rounding excludes it.
   - Result: `{elId:"D1", via:"player-draw"}` instead of `{elId:null, via:"ambiguous"}`.

   This remains order-independent, but it is fail-open because two distinct decoders at the intended ambiguity boundary can resolve to one owner. The band comparison needs a small scale-relative epsilon.

## Verified closed

- r5-F1: zero/negative overlap is excluded by `ov > 0`; the remote same-key scenario returns `via:"none"`.
- r5-F2: an unresolved footprint key immediately returns `via:"unknown-key"`.
- Wrong-key canvases are excluded even when they have greater overlap.
- Empty candidate sets return `none`; finite positive candidate sets cannot produce an empty near band.
- Multiple canvases belonging to one decoder resolve to that decoder.
- Multiple distinct decoders clearly inside the band return `ambiguous`.
- The r4 sequence `D1=100000, D2=104000, D1=106000` returned `ambiguous` under all six DOM permutations.
- No regression found in the previously verified F1/F2/F5/F6 guards.

Injected JavaScript syntax passed, and all 21 directly runnable no-filesystem adversarial tests passed. No files were changed.