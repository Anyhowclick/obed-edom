Plan a **frac-only boundary redraw**, retaining the existing fractional interior. The saved evidence establishes the defect’s mechanism; the proposed redraw must pass targeted CEF pixel qualification before shipping. No repository files were changed, and no apps or pytest were run.

1. **Record the numerical diagnosis.**

   All four saved takes reproduce the same result using the scorer’s **per-launch measured LUT and verified mask**: interior **2**, edge **9**, exactly **15** failing pixels.

   The recorded geometry produces:

   ```text
   holder:              (109,795), size 952×268
   content origin:      (109.367224,795.036194)
   fractional draw:     (0.351707,0.036194), size 952×268
   ```

   The draw’s x origin deliberately uses the video origin plus the locally rounded contain offset; it is not simply `content.left - holder.left`.

   At the top row, canvas edge coverage leaves approximately `a=0.03619385` of the snapped underlay visible:

   ```text
   holder ≈ (1-a) × fractional sample + a × snapped sample
   ```

   | Representative x | Fractional sample from row 796 | Snapped sample | Predicted row 795 | Saved row 795 | LUT(saved) / live |
   |---:|---:|---:|---:|---:|---:|
   | 478 | 12 | 180 | 18.0806 | 18 | 17 / 8 |
   | 502 | 108 | 249 | 113.1033 | 113 | 124 / 119 |
   | 537 | 249 | 81 | 242.9194 | 243 | 245 / 250 |

   This model matches the entire non-corner top row within **1 raw LSB** in every take. Live rows 795 and 796 are identical across this counter strip. Substituting that equal-content row **as a diagnostic only** changes the score to interior **2**, edge **1**. The original bottom/left/right edge maxima are **1/0/0**.

   Thus the observed failure is fractional **canvas quad coverage mixing horizontally misregistered underlay pixels**, not missing whole rows or foreground masking. The evidence supports full compositor coverage at this phase. It does not establish every possible compositor edge phase.

   Keep `round(cw)` and `round(ch2)`: replacing the width with `cw` changes the source sample at x=478 from approximately **744.000758 to 744.391813**, disturbing the already-correct interior. Simply extending an out-of-bounds source rectangle also fails: `drawImage` proportionally clips its destination. [Canvas specification](https://html.spec.whatwg.org/multipage/canvas.html#dom-context-2d-drawimage)

2. **Implement direct-video boundary sampling, after the existing opacity scan.**

   Preserve the snapped underlay and fractional draw. After the whole-backing opacity check, redraw boundary rows and columns into **integer device-pixel rectangles**, then redraw their intersections.

   For destination column `e`, the source crop origin is:

   ```text
   sx = clamp((e + 0.5 - fx) × videoWidth / roundedWidth - 0.5,
              0, videoWidth - 1)
   ```

   A one-source-pixel-wide crop drawn into one destination column samples the required pixel center. Apply the corresponding formula vertically. For this take, the top source crop starts at **0.434534785**; it does not copy source row zero or holder row one.

   Include any adjacent cells only partially covered by the original quad. A fixed one-pixel ring alone is insufficient for some locally rounded contain geometries: an offline example gives `fx=-0.47`, `fw=951`, `ww=952`, leaving **1.47 pixels** at the right boundary.

   In [live_runtime.py:154](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:154), replace the span beginning `if("frac"===pl){var fx=` and ending at the existing alpha-scan `if(d[j]<255)return;` with these exact concatenated byte literals. Keep the preceding snapped draw and following `Y.forEach` unchanged:

   ```python
   b'if("frac"===pl){var fx=dx+(r.left-R.left)+Math.round(cx-r.left)-u0,fy=dy+(r.top-R.top)+Math.round(cy'
   b'-r.top)-v0,fw=Math.round(cw),fh=Math.round(ch2);g.drawImage(v,fx,fy,fw,fh)}for(d=g.getImageData(0,0,'
   b'ww,hh).data,j=3;j<d.length;j+=4)if(d[j]<255)return;if("frac"===pl){var ex=[],ey=[],ei,ej;for(ei=0;ei'
   b'<ww;ei++)if(ei===0||ei===ww-1||ei<fx||ei+1>fx+fw)ex.push(ei);for(ei=0;ei<hh;ei++)if(ei===0||ei===hh-'
   b'1||ei<fy||ei+1>fy+fh)ey.push(ei);var sx=ex.map(function(e){return Math.max(0,Math.min(vw-1,(e+.5-fx)'
   b'*vw/fw-.5))}),sy=ey.map(function(e){return Math.max(0,Math.min(vh-1,(e+.5-fy)*vh/fh-.5))});for(ei=0;'
   b'ei<ey.length;ei++)g.drawImage(v,0,sy[ei],vw,1,fx,ey[ei],fw,1);for(ei=0;ei<ex.length;ei++)g.drawImage'
   b'(v,sx[ei],0,1,vh,ex[ei],fy,1,fh);for(ei=0;ei<ex.length;ei++)for(ej=0;ej<ey.length;ej++)g.drawImage(v'
   b',sx[ei],sy[ej],1,1,ex[ei],ey[ej],1,1)}'
   ```

   This adds **599 bytes**, normally eight narrow draws, no intermediate canvas, no pixel writeback, and no additional readback. Fully covered non-boundary pixels retain the original fractional draw byte-for-byte.

   Keeping the alpha scan **before** repair preserves the existing fractional-only underlay-omission refusal. Subsequent source-over draws cannot reduce an already-opaque destination’s alpha.

   **Qualification risk:** the sampling coordinates are exact algebraically, but CEF’s filtering of fractional one-pixel source crops is unverified. Canvas does not specify a precise smoothing algorithm. Saved PNGs cannot prove that this new draw path reaches 2 LSB. [Canvas specification](https://html.spec.whatwg.org/multipage/canvas.html#dom-context-2d-drawimage)

3. **Amend frozen §11.5 explicitly.**

   Replace its draw/scan sequence with:

   > Frac retains the existing snapped underlay and locally rounded fractional quad, followed by the existing whole-backing alpha==255 scan. After successful opacity validation, redraw the first and last device rows and columns, plus any other cells not wholly covered by the fractional quad. Sample the original video at the unchanged fractional mapping’s pixel centers, clamped to the original image’s edge texel centers. Draw rows and columns into integer device rectangles and their intersections last. Then perform the existing foreground redraw and holder attachment. Fully covered non-boundary pixels remain untouched. No product tone map, pixel writeback, intermediate resampling canvas, or snap-path change is introduced.

   Keep §5’s mask, reference, interior **and edge** requirements unchanged. Add **≤2 LSB boundary residual** as this fix’s qualification target; passing the existing τ=4 alone is insufficient.

4. **Extend existing offline tables; add no new test framework.**

   In [tests/test_live_runtime.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/tests/test_live_runtime.py), extend `_fractional`’s expected traces and the existing Node case table. Reuse current fractional, near-clip, integer-stage-origin, DPR-refusal and foreground cases. Add the exact saved geometry, the two-cell boundary example, and a one-pixel backing case.

   Assert the precise source coordinates, row/column/intersection order, unchanged holder geometry, and:

   ```text
   snapped draw → fractional draw → whole-backing scan
                → boundary draws → foreground
   ```

   Extend the existing alpha-failure row to `placement="frac"` and require **zero repair draws after rejection**. Update the existing trace-order assertion narrowly; do not simply allow arbitrary draws after readback. Retain all snap expectations, including DPR 1.5/2, unchanged.

   In [tests/test_dissolve_probe.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/tests/test_dissolve_probe.py), extend the existing edge-step table over four sides and a corner: interior 2/edge 9 must fail; interior 2/edge 2 must pass. Add the measured transition triplets as a compact scorer regression. These test scoring and coordinates, **not CEF rasterization**.

   Existing nooffset and underlay-omission splice anchors remain intact. Keep their counted-splice checks.

5. **Update only the live-on output pins.**

   Computed in memory against both real stock players, for the exact replacement above:

   | Stock prefix | New `SUPPORTED_PLAYERS[*][0]` / `REAL_PATCHED_SHA256[sha][True]` |
   |---|---|
   | `e9b2fad4` | `dd8f692d7269aca4267025a51c060f41e4b7219492482686024990afd043d5c2` |
   | `17c0c938` | `c40d6baab203fe356b92eee1b39e979ff9398e0bfa2be85c251d61145926cffd` |

   `[1]` and `[2]` stay unchanged: off output is untouched, and rendering-only output excludes the freeze method. Do not mechanically re-pin rendering output merely because the older §11.5 wording mentions it.

6. **Qualify narrowly before spending 45 minutes on placement.**

   First run a scratch subset through the existing managed placement machinery, retaining calibration, per-launch LUT, verified twins and references. There is no existing managed `--arms` selector; do not invent that CLI flag.

   Start with `m-snap-cef` and its twin, `wrongrule-cef`, and `m-snap-cef-underlay-omit`. Require corrected interior/edge **≤2/≤2**, reference equality, verified mask, wrong-rule pixel failure, and underlay-omission refusal.

   Then exercise all four sides and corners with unmasked horizontal and vertical transitions at multiple fractional phases, including the recorded phase, complementary phases and the two-cell contain case. Flat existing left/right edges cannot qualify general edge sampling.

   Next run the four near/far clip cells and twins, nooffset controls, `m-snap-cef-dsk`, and foreground/cost arms. Require two DSK holders and total take ≤50 ms. The separately diagnosed nooffset-y layout and foreground-demix issues must be resolved independently before their gates can qualify this change.

   Once targeted results pass, run the full placement profile with `--takes 2`; it already iterates both output rates, giving four takes. Run the required Chrome DX-1 regressions and `wrongrule-chrome`. Byte-check that snap admission and drawing remain unchanged; consequently the additional 18-cell real-DSF matrix is unnecessary under §5.

7. **Fail closed if exact boundary sampling does not qualify.**

   The existing two-draw contract demonstrably cannot meet the requested tolerance at this geometry. An exact replacement is **not yet verified**, but the evidence does not establish that one is impossible.

   If the proposed source-crop path exceeds 2 LSB, changes interior pixels, or misses the cost bound, do not ship it or weaken scoring. Disable frac takes by inserting:

   ```javascript
   if("frac"===pl)return;
   ```

   immediately before the outer `var ad=[];` video scan. The existing `finally` still publishes take time; no frac holder is created, and stock movie transition behavior remains. Recompute live-on pins for that fallback.

   The mandatory invariants throughout are unchanged snap bytes and behavior at **DPR 1, 1.5 and 2**, unchanged Chrome snap arms, unchanged foreground masks, and identity-tone product drawing.