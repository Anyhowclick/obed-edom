**READY FOR IMPLEMENTATION**

I reran the **234 evidence rows on both real extracted players** against rev 12’s §3.1 methods: outcomes exactly match the banked results, both players agree, and all harness invariants hold. Another **36 targeted cases per player** matched expectations. The four candidate digests match their manifest and pass `node --check`; the methods match the evidence build after removing presentation line breaks.

| r9 finding | Status | Evidence |
|---|---|---|
| **1. Tag-name exemptions** | **CLOSED** | The rendered `SCRIPT` overflow and hidden rendered `HEAD` with a filter each produce **0 holders** on both players. Default `display:none` metadata produces **1**. Additional rendered/hidden cases across all nine formerly exempt tags confirm that rendering state controls admission. |
| **2. Shadow trees** | **CLOSED within the declared source scope** | The open-shadow host produces **0 holders**. Additional roots inside the stage, beneath a clipping witness, on a hidden host, and on an opacity-zero host also reject. The root check precedes both paint shortcuts. Closed roots are explicitly governed by the source invariant and residual discussed below. |
| **3. `kx` / `ky`** | **CLOSED** | Both **960×1080** and **1920×1079.5** base rectangles produce **0 holders**; the full-slide positive produces **1**. The baseline holder is **952×268 CSS pixels with a 952×268 backing**, read in full at `(0,0,952,268)`. |
| **4. Wording** | **CLOSED** | §14 now states that no smaller crop exists on the measured full-content regions, no crop A/B has run, and the clipped diagnostic remains required. §9.0 puts real-page engagement first; §13 explicitly excludes active view transitions from the guarantee. |

These results support the closure account in [§8.4 and the acceptance requirements](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md:499).

The closing sweep produced **no new demonstrated false admission or false pass within that scope**:

- **Exterior-proof escapes:** hidden ancestor filters/reflections, invalid SVG witnesses, unclipped captions, fixed descendants and fixed pseudo-elements reject. Valid clipped-subtree positives remain admitted.
- **Unproven attached pixels:** transparent or alpha-254 first/last pixels and boundary rows/columns reject. Full-backing readback remains before foreground redraw.
- **Geometry outside the model:** unsupported DPR, stage/nested scales, rotation, fractional origin and mismatched base extents reject. Unit-scale integer-origin letterboxing remains admitted.
- **Capture instruments:** §§9–10 retain independent foreground inventory and mask controls, paused-reference state checks, `perfect`/`perfect-shift`, and timestamped hide/show coverage with dropped-action controls. I found no concrete false pass in these contracts. Their browser/scorer execution remains pending.

The **closed-shadow-root residual is acceptable for implementation readiness**. I independently confirmed the absence of root-creation markers in the checked stock players, candidate players and host sources; the supplied [invariant evidence](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-rev12-2026-10-12/results/shadow_invariant.txt) also covers the P2 index. This is a bounded source invariant, not runtime detection: `shadowRoot === null` cannot establish absence. Extensions or future scripts outside that inventory remain outside the guarantee. Any such script brought into supported scope must satisfy the invariant or trigger a revised root-handling design.

This verdict approves proceeding with implementation. Rev-12 browser engagement, capture controls, cost and CEF qualification remain mandatory under §9.0.