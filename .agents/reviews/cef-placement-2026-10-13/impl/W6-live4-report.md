Investigation was read-only; no repo files, OBS, Chrome, Keynote, pytest, or gates were touched.

Evidence root: `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live4/out`

## 1. `m-snap-cef` edge failure

**Cause/class: PRODUCT.** The fractional holder’s canvas/opaque-underlay composition does not reproduce the live CEF video compositor at the fractional **top content edge**. It is unrelated to the new foreground crossing or its mask.

The holder box is device coordinates `[109,795)–[1061,1063)`. In all four takes, exactly these 15 unmasked top-edge pixels exceed τ=4:

| Coordinates `(x,795)` | Raw holder / A0 | Scorer-toned holder | Perfect reference | Live | RGB residual |
|---|---:|---:|---:|---:|---:|
| 478, 597, 716, 835, 954 | 18 | 17 | 8 | 8 | 9 |
| 502, 621, 740, 859, 978 | 113 | 124 | 119 | 119 | 5 |
| 537, 656, 775, 894, 1013 | 243 | 245 | 250 | 250 | 5 |

All values are identical in R/G/B; alpha is 255 everywhere and has zero residual. `ref-perfect-0` equals `live-0` at every listed pixel, consistent with the recorded reference PASS `0/0`.

Evidence:

- The scorer explicitly evaluates the one-device-pixel edge band outside the verified production mask: [dissolve_probe.py:2274](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2274), [dissolve_probe.py:2284](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2284).
- All four records reproduce `interior=2, edge=9`, τ=4.
- Every listed pixel is `mask=false`; the mask itself verifies PASS.
- The fg-omit twin’s saved holder pixel is byte-identical at all 15 coordinates. Therefore foreground inclusion is not causal.
- The intended crossing foreground is at approximately `[98.852,872.536,80,20]`, crossing the holder’s **left** edge by 10.148 px. The failures are on the **top** edge at y=795, far outside that foreground support. The harness layout is defined at [dissolve_probe.py:226](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:226) and installed at [dissolve_probe.py:1360](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:1360).
- `wrongrule-cef` still behaves correctly as the negative control: expected FAIL, observed `183/183`.
- The clip-cell edge maxima are actually `far-x=0`, `far-y=2`, `near-x=0`, `near-y=1`, identically in all four takes. The failing top-edge coordinates are masked by the stock full-frame foreground in far-x/far-y/near-x; near-y scores a different clipped edge at y=902. Those cells therefore do not contradict the base-cell failure.

The underlying product path is the snapped opaque underlay followed by the fractional draw at [live_runtime.py:154](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:154). At the fractional top edge, its first canvas row is visibly different from the live compositor.

**Proposed fix:** correct the product’s fractional edge composition so the first/last device rows match the live element. Do not dilate the foreground mask further or suppress the edge band. If the two-draw algorithm cannot be made exact, `frac` must fail closed rather than grant a visibly wrong holder.

**Contract/outcome:** §5 must not change: it explicitly requires foreground crossing plus interior and edge scoring ([plan:351](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/plans/keynote_live_cef_placement.plan.md:351)). Expected `m-snap-cef` remains PASS and `wrongrule-cef` remains FAIL. Changing the specified two-draw algorithm would require amending the frozen §11.5 implementation contract ([plan:854](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/plans/keynote_live_cef_placement.plan.md:854)).

## 2. `m-snap-cef-nooffset-y` zero holders

**Cause/class: HARNESS.** The y=125 override moves the video under unrelated, later-painted slide artwork. The product’s occlusion guard correctly refuses to freeze it.

Recorded geometry is identical in the main and twin across all four takes:

- Video/content: `x=109.3673…1060.8673`, `y=125…392.6094`.
- Near-y visible/clip region: `x=109.3673…1060.8673`, `y=232.4186…392.6094`.
- Unrelated texture `18B86872…`: `[740,190,353,313]`, or `x=740…1093`, `y=190…503`.
- Intersection: `x=740…1060.8673`, `y=232.4186…392.6094`.

The refusing condition is the per-video overlap/ownership guard:

1. The visible element overlaps `c`.
2. It is visible and `own(...)` treats its rendered canvas/image as paint.
3. It is later than the video in DOM order.
4. Its common ancestor with the video is the stage `G`.
5. Therefore `if(P===G||!G.contains(P))return` fires at [live_runtime.py:145](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:145), specifically line 148.

That exits the video callback before canvas allocation/drawing at lines 152–165. Consequently `H` remains empty and `U.__obedFrozen` is not published at [live_runtime.py:166](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:166).

This is not:

- the shared paint/geometry gate—otherwise the take would have returned before scanning videos;
- clip geometry—the recorded near clip is valid;
- opaque-backing rejection—the backing canvas was never created or scanned;
- decoder timing—the decoder detached normally.

The `finally` publication at [live_runtime.py:167](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:167) explains why `dump.takes` still records costs: main/twin costs range 2.2–16.9 ms despite zero holders.

The harness introduced this placement through `NOOFFSET_Y_DISPLACEMENT=125` and `_nooffset_y`: [dissolve_probe.py:241](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:241), [dissolve_probe.py:1459](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:1459).

**Proposed fix:** place the content at `y=-80` instead of 125.

- Near clip starts at `-80 + 107.418584 = 27.418584`.
- Visible bottom is `-80 + 267.609375 = 187.609375`.
- That leaves about 2.39 px before the unrelated image begins at y=190.
- Displacement magnitude is 80 px, safely below the 267.609 px content height.
- The video’s top counter strip remains outside the near clip.

The mathematical closest integer is `y=-78`, whose bottom is approximately 189.609; `-80` provides safer clearance.

**Contract/outcome:** no §5 or §11 change. This is solely a harness-layout correction. The expected result remains a real `holder_pixels=FAIL`, making the negative-control arm MATCH.

## 3. One `m-fg-cef` mismatch

**Cause/class: INSTRUMENT noise at a demix boundary, not a product foreground defect.** τ is **4**, derived for every take by [managed_obs_qualify.py:1688](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/managed_obs_qualify.py:1688).

Results were:

- 25 fps A: worst 2
- 30 fps A: worst 5
- 25 fps B: worst 3
- 30 fps B: worst 3

In the red take:

- The direct holder candidate matches live exactly: worst 0 over all 532 pixels.
- Earlier demixed candidates have maxima 1, 1, 2, 2.
- The sole failure is the final admitted candidate at `e=0.7994464`, immediately below `DEMIX_E_MAX=0.8`.
- At `(278,804)`, demixed RGB is `[189,227,182]`; live is `[189,232,180]`. Only G exceeds τ, by 5.
- Demixing divides by `1-e≈0.20055`, amplifying a one-LSB capture/composition perturbation by approximately 4.99.

The demix formula and cutoff are at [dissolve_probe.py:1987](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:1987). Foreground currently applies the unscaled τ to both the exact holder and all demixed candidates at [dissolve_probe.py:2045](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2045) and [dissolve_probe.py:3424](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:3424). By contrast, `score_region` already accounts for demix amplification using `τ/(1-e)` at [dissolve_probe.py:2032](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2032).

**Proposed fix:** keep the direct-holder comparison at τ=4, but assess demixed foreground evidence with a mathematically scaled residual bound—or compare the pre-division residual—rather than increasing τ globally. The current take should not be waived without that scorer correction.

**Contract/outcome:** no §5 or frozen §11 schema change. This corrects the instrument while retaining the “foreground intact” requirement. Expected `m-fg-cef` remains PASS/MATCH.