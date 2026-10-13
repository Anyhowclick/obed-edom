Reviewed **e8131d77 against rev 12**. HEAD advanced to documentation-only `54000459` during review; the reviewed code stayed unchanged.

| R2 finding | Status | In-memory result |
|---|---|---|
| Offscreen navigator | **CLOSED** | `[0, 10000, 130, 360]` now makes the arm INCONCLUSIVE. |
| Missing spatial classes | **CLOSED** | Zero textures invalidate caption/geometry arms; opaque incoming invalidates `m-snap`, including when only its twin is affected. |

**New Major finding — blank incoming texture can falsely validate stale reference captures.**  
[dissolve_probe.py:1728](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:1728)

The “checks never read B” argument is false for reference captures: `reference_problems` uses `far_mask(A, B)` to select pixels for its stale-capture check.

Independently reproduced with `media_run("m-snap")` and a valid twin:

1. Create an unchanged opaque patch at `[200:210,100:110]`, setting incoming equal to outgoing there consistently in both runs.
2. Make the main F50/B screenshot pairs copies of A0, except that patch’s red channel decreases by 10/20 respectively. Stable pairs and the midpoint equation remain valid, but captures are stale everywhere the actual textures differ.
3. With correct `tex-in`: **INCONCLUSIVE**, reporting stale/reused frames.
4. Zero only the main `tex-in`: **MATCH**, with holder pixels, reference, mask and geometry all **PASS**, `problems=[]`.

Blank B expands the comparison mask onto the unchanged patch, whose unrelated variation conceals the stale captures. Reference qualification needs independent texture/capture consistency validation.

The zero-incoming argument remains sound for engagement-only checks, including `m-raw-end`; blanket rejection of transparent incoming would be inappropriate.

**Validation:** 213 callable scorer cases passed in memory; one filesystem-dependent case excluded. The reported full suite and 786-mutation sweep were not independently rerun. No substantive standards findings.

**CHANGES REQUIRED**