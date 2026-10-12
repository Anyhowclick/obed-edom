1. **Major — CLASS: acceptance coverage — §§9.0.5, 9.1.**  
   **Scenario:** P2 at **1920×1201, DPR 1.5**, stage origin **y = 60.5**, with a fractional ancestor clip. Both players’ rev-13 methods admit this combination. The investigator measured fractional letterboxing at DPR 1 and DPR 1.5 at an integer origin separately. The [new arms preserve that separation](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:725); the [clip gate](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:613) does not require fractional stage origins. Every specified run can therefore pass without qualifying this newly admitted combination. This is a concrete coverage gap, **not a demonstrated rendering failure**.

   **Exact fix:** Explicitly cross DPR **1/1.5/2** with integer and fractional letterbox origins, both unclipped and fractionally clipped on each axis. Require engagement, edge-inclusive holder comparison, `perfect`, same-frame omission twins, and a displaced-edge FAIL control at those geometries. Narrow admission for any failing combination. The current fallback to “unclipped-only at DSF ≠ 1” does not resolve an unqualified *unclipped* fractional-origin combination.

2. **Major — CLASS: stale acceptance-control anchor — §9.1.**  
   **Scenario:** Building [`m-snap-frac`](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:726) searches for rev 12’s `sn=function(z,e,k){return Math.round((z-e)*k)}`. That anchor occurs **zero times** in all four rev-13 candidate artifacts, so the counted splice cannot construct the required FAIL control.

   **Exact fix:** Search for `sn=function(z,e,k){return Math.round((z-e)*k*p)/p}` and replace it with `sn=function(z,e,k){return(z-e)*k}`. Require exactly one replacement on both players and their omission twins.

The remaining checks support the delta:

- I reran **265 harness rows on both players**: expectations and invariants pass. The fractional-box trace draws **469×394** and reads **469×394**; the old **469.5** draw width is gone. Boundary transparency still rejects.
- Foreground redraw coordinates consistently convert snapped CSS coordinates into device pixels. No coordinate-unit defect found; `m-fg` at DPR 1.5/2 is explicitly required.
- DSK 7→8 cost at DSF 2 and CEF geometry/DSF have explicit blocking outcomes.
- §3.1 matches the evidence methods; **D1 = 10,197 bytes**, all four digests match, and all four candidates pass `node --check`. No additional byte finding.

**CHANGES REQUIRED**