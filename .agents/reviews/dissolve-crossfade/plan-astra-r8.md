1. **Major — CLASS: closed class — §§3.1–3.2, 10: an ancestor filter defeats the exterior proof.**

   Put a visible, positioned, `overflow:hidden` clipper at x = −100 beneath an exterior parent with `visibility:hidden; filter:drop-shadow(300px 0 0 red)`. Its clipped text remains outside the stage, but the parent’s filter projects that paint into the movie. `pc(parent)` returns true at the visibility shortcut; `xo(child)` stops at the clipper without checking the filtering ancestor. The exact-method Node harness admits **one holder**; changing the parent to visible correctly rejects it. Filters process descendant rendering, and hidden ancestors can have visible descendants. [Filter rendering model](https://www.w3.org/TR/filter-effects-1/#FilterProperty), [visibility semantics](https://www.w3.org/TR/CSS22/visufx.html#visibility).

   **Exact fix wording:** “Validate effects that operate on descendant paint before the visibility shortcut. An exterior clipping witness is valid only if its clipped output cannot subsequently be expanded or displaced into `V` by ancestors. Add hidden-filter-parent/visible-clipped-child rejection and corresponding unfiltered admission controls.”

2. **Major — CLASS: edge case — §§3.1–3.2, 10: computed overflow and position do not establish a universal clipping witness.**

   An off-stage modal dialog with `overflow:hidden` qualifies as its own witness—even when fixed—while its `::backdrop` paints across the stage. Neither `pc` nor `xo` inspects `::backdrop` or top-layer membership. The modeled dialog is admitted by the exact-method harness. Top-layer elements and backdrops explicitly escape ancestor clipping. [Top-layer rendering](https://www.w3.org/TR/css-position-4/#top-layer).

   There is also no namespace restriction on witnesses. An SVG `<g>` styled `display:block; position:relative; overflow:hidden` does not thereby become an HTML overflow container. Beneath a visibility-hidden, overflow-visible SVG root, visible stroked descendants can obtain this false witness while painting beyond their geometric boxes. [SVG overflow applicability](https://www.w3.org/TR/SVG2/render.html#OverflowAndClipProperties).

   **Exact fix wording:** “Restrict exterior witnesses to qualified HTML layout containers where positioning establishes the required containing block and overflow clipping actually applies. Reject potentially painting top-layer content, including `::backdrop`, before element-test and exterior shortcuts. Add real-browser controls for modal/popover escapes and false SVG witnesses; retain clipped absolute/sticky/transformed descendants as positives where confinement holds. Verify iframe/foreignObject boundaries explicitly. Main’s overlapping bridged decoder must continue to reject admission.”

3. **Major — CLASS: closed class — §§2, 3.1–3.2, 10, 12.10: scanning the interior does not prove opaque cover of the attached canvas.**

   At DPR 1.5, an admitted 313×263 `fill` movie produces:

   - Canvas backing: **470×395**
   - Movie draw: **469.5×394.5**
   - Alpha readback: **469×394**

   Those are exact-method harness results. The last column and row remain attached but unexamined. Partial coverage or source transparency there can expose the baked frame. Foreground redraw does not repair the proof. §10’s “partial edge pixel outside it admits” explicitly institutionalizes this hole.

   **Exact fix wording:** “Before foreground redraw, require alpha 255 for every backing pixel that can contribute to the attached holder, including boundary pixels and the sampling footprint of subsequent scaling. Skip when opaque coverage cannot be proved. Do not admit an unchecked partial edge merely because it lies outside the interior scan. Replace that positive test with an attached-edge transparency rejection control.”

4. **Major — CLASS: new class — §§1.1, 3.2, 8.2, 10: the snapping formula is an empirical fit, not a complete Chromium model.**

   `round((z−R.left)·kx)` removes the stage mapping, but admission permits additional uniform transforms below the stage. A locally 101-pixel-wide video beneath a 1.5× transform remains admissible at stage scale 1; snapping its transformed 151.5-pixel extent is a different operation from snapping locally and then transforming. Fractional ancestor translations create the same order-of-operations problem.

   Chromium’s video painter snaps the local replaced rectangle plus paint offset before recording its compositor layer. The P2 fit does not establish equivalence for every admitted transform chain. [Chromium video painter](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/paint/video_painter.cc).

   **Exact fix wording:** “Describe `sn` as the measured model for the qualified geometry, not Chromium’s universal snapping rule. Specify the supported transform chain, coordinate space, pixel phase, DPR and clipping behavior. Add browser-reference cases with nested scale, fractional ancestor translation, fractional stage origin and clipped boundaries; conservatively reject combinations not demonstrated to preserve the required pixels.”

5. **Major — CLASS: new class — §§3.1–3.2, 9.0–9.2, 12.9, 13: the supposedly open geometry decision already has a permissive implementation default.**

   The bytes admit arbitrary DPR and stage scale. Qualification is restricted to DSF 1/stage scale 1, while failing geometries become report-only. Thus “documented limit” is already the effective shipping behavior despite §13 saying the owner has not selected it.

   DSF 2 is also a failure **at stage scale 1**, and its flat-area maximum is 5, above τ = 4. The evidence does not support describing all residuals as harmless content-edge resampling. Finding 3 demonstrates an independent admission-safety failure in this broader domain.

   **Exact fix wording:** “Separate DPR, stage scale and transform-chain qualification. Until a broader residual is explicitly accepted, admit only geometries demonstrated to satisfy the strict holder criterion. Any accepted visual residual must remain separate from mandatory opaque-cover, clipping and foreground-preservation checks. Record the shipping rule consistently in §3’s bytes, §9’s gates and §13.”

6. **Major — CLASS: closed class — §§8.2, 9.1, 10: the foreground-mask verification detects under-masking but not over-masking.**

   Requiring twin differences to lie inside the dilated alpha mask is useful, but a greatly oversized mask also satisfies that condition. A mask retaining only flat movie pixels can hide a shifted holder’s edge failures. Tone’s 50% cell coverage does not protect `m-snap`, whose required “out-only” class is outside the movie. Furthermore, only `m-tone` explicitly schedules its omit twin; `m-snap` nevertheless requires a *verified* mask.

   **Exact fix wording:** “Build the foreground mask from a complete, independently captured canvas inventory and a specified device-space mapping; verify both missed and excess support against a known raster control. Schedule a same-frame omit twin for every reference geometry requiring this verification. Reject oversized, shifted, empty or mismatched masks before scoring. Require a whole-rectangle-mask negative and a shifted-holder negative to remain detectable with the production mask.”

7. **Major — CLASS: closed class — §§9.0–9.1, 10: the seeked-reference sequence cannot satisfy the inherited temporal coverage contract.**

   Pausing after the first transition rAF and capturing `F50`, near-end `B`, `A0`, then `perfect` supplies only **one mid-progress state**. It cannot establish six mid-frames or three demixable frames with separated progress. The rev-9 scorer applies fade coverage even to paused arms; §9.1 supplies no explicit reference-profile exemption or separate temporal capture.

   Checking requested `currentTime` and midpoint algebra also needs instrument controls: identical stale screenshots can satisfy `F50=(A0+B)/2`.

   **Exact fix wording:** “Define a dedicated reference-capture profile with an explicit inventory of bound animations, paused-state checks, rendered endpoint opacities, stable captures and required reference images. Run temporal fade qualification separately with the existing six-mid-frame and separated-demixing requirements. Add valid-reference positives, stale/reused-frame and missing-animation INCONCLUSIVE controls, and a deliberately shifted `perfect` capture that fails its instrument check.”

8. **Major — CLASS: new class — §§9–9.1, 10: screencast capture fixes cadence but does not qualify the hide instrument.**

   The new test only makes insufficient coverage INCONCLUSIVE. There is no designated control proving that omitted hiding, opaque conversion of transparent frames, incorrect timestamp assignment, or failure to show again is detected. Existing cleanup and settled-frame controls do not exercise these checks.

   The wording also alternates between six frames *outside the hidden interval* and six frames *after show*. Those are different contracts: sufficient pre-hide footage must not conceal a broken restoration.

   **Exact fix wording:** “Require six distinct, correctly timestamped mid-progress screencast frames after show, plus captured evidence inside the hidden interval. Qualify alpha and screen capture separately with known transparent/black positives and deliberately visible negatives. Add dropped-hide, dropped-show, duplicate-frame and timestamp-shift controls; malformed or insufficient evidence is INCONCLUSIVE. List these controls in the round manifest before lifecycle candidates count.”

9. **Minor — CLASS: edge case — §§8.2, 9.0, 12.11, 14: the cost evidence supports the optimization, but overstates the crop conclusion.**

   The 9.4–9.8 ms figures are clearly identified as fractional-box prototype timings, and final-byte/fresh-launch/CEF measurements are appropriately pending. However, the retained scripts show no source-crop comparison. A ≤0.3 ms `drawImage` call measures synchronous call time; deferred rendering may be charged to readback. “Source crop measured unnecessary” therefore overstates the evidence.

   Not adopting a crop is reasonable for the measured full-content regions. Also, DSK 3→4 now costs more than 7→8 in the recorded rev-10 runs, so 7→8 should be called the **previous** worst case.

   **Exact fix wording:** “State that no smaller source crop exists for the measured full-content regions and that no crop A/B has yet been performed. Complete decision 11’s crop experiment using a clipped diagnostic, comparing total take time and pixel equivalence. Retain DSK 7→8 as mandatory, and recheck the other measured DSK transitions on final bytes before asserting the worst case.”

**Verdict: CHANGES REQUIRED — byte lengths, hashes, anchors and composition checks hold, and file ownership is disjoint; exterior containment, opaque coverage, geometry admission and the new capture controls need revision.**