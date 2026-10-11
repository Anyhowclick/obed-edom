# Plan critique r7 (final) — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 8 `d299b549`. Prompt: `plan-astra-r7.prompt.md`.

**Part A**

References: **P** = [rev-8 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md); **B** = [dpatch11.py](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/planner/dpatch11.py). The working plan matches `d299b549`. All checks used memory/stdout; no files were edited.

| r6 # | Status | Evidence | Remaining fix wording |
|---|---|---|---|
| r6-1 | **closed** | P:168–173; B:23,44. UA `overflow:clip` is admitted on bitmap leaves, including foreground canvases. Both players reproduce all six deck-stub admissions. Recorded debug DOM agrees. | None for the reported UA-default rejection. Final-byte browser/CEF engagement remains Q0b work. |
| r6-2 | **closed** | P:168; B:27,36. Root/body propagation uses viewport bounds. Zero-height body and non-propagating static-body cases admit on both players. | None for the reported body-box clipping error. |
| r6-3 | **partly closed** | B:28 rejects border images, replacement content and generated content on checked elements. Original negative cases skip. However, its initial visibility shortcut bypasses generated-content checks: finding **#2**. | Inspect potentially painted pseudo-elements/text independently of whether their originating element has a visible box. |
| r6-4 | **partly closed** | B:30 runs the gate before B:42’s rectangle rejection. The outside-box shadow skips; confined nonintersection admits. But the gate still does not establish paint confinement: finding **#1**. | Require actual bitmap confinement and conservatively reject unsupported paint families before rectangle filtering. |

**Part B — NEW findings**

1. **Severity: major. Class: edge case. §3.2 — The new gate still admits paint outside the rectangle, and foreground bitmap positioning is unchecked.**

   **Claim:** P:154–159 says clipping or `object-fit:fill/contain/scale-down` confines replaced content, making the rectangle prefilter sound.

   **Evidence:** B:28 checks `objectFit` but not `objectPosition` or `overflowClipMargin`. B:33 checks the movie’s position; B:46 does not check a redrawn canvas’s position.

   Running the unchanged extracted methods through the existing Node harness admitted:

   | Added case | Result |
   |---|---|
   | Later image at `[1100,800,100,100]`, `overflow:visible; object-fit:contain; object-position:-200px 0px` | One holder; no foreground redraw |
   | Same placement using a canvas and `object-fit:fill` | One holder; no foreground redraw |
   | Intersecting canvas with UA clipping and `object-position:-50px 0px` | One holder; redraw uses the entire unshifted bitmap |

   The first two can paint at x=900–1000, inside the movie’s approximately x=109–1061 region. The third copies pixels that the live canvas’s shifted, clipped presentation does not show. `object-position` controls positioning separately from sizing; `drawImage` does not reproduce that CSS presentation. [CSS Images positioning](https://drafts.csswg.org/css-images-3/#the-object-position), [Chromium replaced-element overflow](https://developer.chrome.com/blog/overflow-replaced-elements)

   The property list also leaves **SVG strokes/markers and column rules** outside its confinement argument. B:28 permits an overflowing SVG with `object-fit:fill` and ignores column-rule properties. Those paint sources can extend beyond the rectangles being tested. Node confirms admission, although their browser pixels were not rerun here. [SVG bounding-box distinctions](https://svgwg.org/svg2-draft/coords.html#BoundingBoxes), [Multicolumn overflow](https://drafts.csswg.org/css-multicol-1/#overflow)

   **Exact fix wording:**  
   “Before rectangle filtering, admit only explicitly supported paint families. Require centred `object-position` on every redrawn canvas. For replaced-content confinement, verify both overflow axes and the clip margin, or require a supported fit and position that keep the content inside the box. Conservatively reject SVG/vector paint, painted column rules and other unqualified paint sources; do not infer confinement from `object-fit` alone. Extend the existing case table with shifted outside-box image/canvas, shifted clipped foreground canvas, SVG stroke and column-rule negatives.”

   **Disposition:** Must fix before implementation; ordinary P2 engagement cannot detect these cases.

2. **Severity: major. Class: closed class. §3.2 — `checkVisibility()` is not a safe shortcut around pseudo-element and text inspection.**

   **Claim:** Every relevant element and its `::before`/`::after` are checked before rectangle filtering.

   **Evidence:** B:28 starts with:

   ```js
   if (!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})) return !0;
   ```

   Therefore neither pseudo-element is inspected when the originating element has `visibility:hidden` or no associated box.

   Two valid cases escape:

   - A hidden element whose `::before` explicitly has `visibility:visible`, generated content and paint over the movie.
   - A `display:contents` element containing visible text or generated content.

   `checkVisibility()` returns false for an element without a box; that does not mean its contents cannot paint. A hidden element can also have visible descendants, including generated child boxes. [CSSOM visibility algorithm](https://drafts.csswg.org/cssom-view/#dom-element-checkvisibility), [CSS visibility](https://www.w3.org/TR/CSS22/visufx.html#visibility), [CSS Display](https://drafts.csswg.org/css-display-3/#box-generation)

   In-memory execution with the corresponding visibility results produced **one holder and zero redraws** for both cases. The visible-origin generated-content control correctly produced zero holders. The later element scan cannot recover pseudo-elements or direct text omitted here.

   **Exact fix wording:**  
   “Do not treat a false originating-element `checkVisibility()` result as proof that its pseudo-elements or text cannot paint. Check generated content and `display:contents` text before that shortcut, or conservatively reject those cases unless subtree suppression is proven. Preserve safe handling of genuinely non-rendering script/style and suppressed subtrees. Add hidden-origin/visible-pseudo and display-contents text/pseudo negatives to the existing table.”

   **Disposition:** Must fix before implementation. This completes the still-open generated-paint portion of r6-3.

3. **Severity: minor. Class: new class. §§3.2, 9.0–9.1 — Q0b lacks an explicit order-sensitive witness for the newly admitted `preserve-3d` topology.**

   **Claim:** P:176–178 establishes document-order reconstruction; Q0b settles the remaining compositor question.

   **Evidence:** The recorded seven wrappers genuinely have `preserve-3d` with no transform, and admitting them is consistent with the probe. The specification supports painting-order treatment of coplanar transformed elements; this is **not evidence that the proposed ordering is wrong**. [CSS Transforms rendering contexts](https://drafts.csswg.org/css-transforms-2/#3d-rendering-contexts)

   However:

   - Q0b 2 checks admission.
   - Q0b 3’s full-image comparison uses **texture plus candidate holder** against the resulting transition.
   - The independent foreground check at P:366 covers counter-block pixels.
   - `m-fg` does not explicitly require its two foreground layers to overlap each other, or require a swapped-order negative.

   Consequently, the stated checks can verify snapshot attachment and fading without detecting an incorrect relative ordering elsewhere in the holder. A wrong holder used as reference predicts its own wrong transition correctly. Existing independent foreground controls remain valid; the missing requirement concerns the newly admitted wrapper topology.

   **Exact fix wording:**  
   “In Q0b 3, exercise the real preserve-3d build-wrapper topology with two distinguishable foreground canvases overlapping each other over tone-invariant counter pixels. Compare the holder and demixed outgoing pixels against paused pre-D4 `S_live` at ≤τ. Require a swapped-redraw-order control to FAIL; missing overlap, reference or engagement is INCONCLUSIVE. Record the actual wrapper/branch ordering. Reuse `m-fg` and the existing parametrized tests.”

   **Disposition:** Fix the criterion before implementation; Q0b/implementation review settles the actual browser behavior.

The **frozen-index criterion is already exact and fail-closed**: P:344–346,364 requires a uniquely bound decoder, its last pre-detach rVFC record, offset zero, and agreement across demixed frames. Missing evidence is INCONCLUSIVE. The recorded sheet shows 44 before advancement and 48 held during the fade; it does **not** establish that 48 was the last presented frame. Rev 8 correctly acknowledges this. No additional planning finding is needed for that pending measurement.

The **document-wide scope is deliberately conservative**, rather than demonstrably always inert. A nonintersecting host text element causes a skip in the harness, but the live host hides its navigator, slide-number and help UI (`live_host.py:424,432`). No primary evidence establishes permanent rejection on normal output. Final-byte host/CEF engagement remains mandatory in Q0b; restricting the scan to `#stage` would miss outside overlays.

**Part C — Closing inventory**

`VERIFIED` means the static property or retained evidence was checked; it does not certify future browser qualification.

| Claim class | Status | Evidence / measurement that settles it |
|---|---|---|
| Revision and base identity | VERIFIED | Plan matches `d299b549`; `origin/main` is `1589d096`. |
| Inline methods match builder | VERIFIED | Joining the displayed method lines reproduces B’s methods; D1 is 8,990 bytes. |
| Supported stock hashes and PDF.js delta | VERIFIED | Both full hashes match; removing the two insertions reproduces the older player. |
| Thirteen anchor counts, offsets and disjointness | VERIFIED | Each occurs once at the listed byte offset; intervals are disjoint on both players. |
| Replacement containment, including self and hook | VERIFIED | Empty containment set. |
| R1–R5 / R6–R8 / D1–D4 composition | VERIFIED | All six group orders produce identical bytes on each player. |
| Anchor consumption/replacement uniqueness | VERIFIED | Rendering anchors disappear; replacements occur exactly once. |
| Patched JavaScript syntax | VERIFIED | Rendering, on and off outputs all pass stdin `node --check`, both players. |
| Off identity and repinning | VERIFIED | Off hashes remain `7cf00b56…` / `4f9fbffd…`; on/rendering need the scheduled repin. |
| In-memory patching and unknown-player refusal | VERIFIED | `live_runtime.py:181–218`; no disk-player mutation required. |
| CSS routing, flattened textures and render/animate separation | VERIFIED | Primary player routing and construction code; Dissolve/cut absent from GL list. |
| Export census | VERIFIED | Recomputed 25 roots: 42 Dissolves, 8 cuts, 67 Magic Moves, 382 builds. |
| Predicate, copying and JSON immutability | VERIFIED | Both players: 46 copied Dissolves, 8 cuts, 79 stock, zero mutations. |
| ID prediction and construction failures | VERIFIED | Real `VB` allocations agree; five failures return stock and abandoned rules target no built nodes. |
| Near-miss refusal | VERIFIED | All 21 Dissolve and 10 cut near-misses remain stock. |
| Additive cross-fade and complementary-cut arithmetic | VERIFIED | Correct under the stated geometry/coverage assumptions. |
| D4-before-teardown and D3 attachment | VERIFIED | Source placement; cut/wrapper/discard/throwing-append cases reproduce. |
| Add-only video handling | VERIFIED | All 123 stub rows on both players report zero video touches. |
| UA replaced-leaf overflow correction | VERIFIED | Corrected cases admit; recorded computed styles support the change. |
| Root/body viewport clipping correction | VERIFIED | Corrected propagation cases admit; ordinary static-body case remains usable. |
| Preserve-3d wrapper admission | VERIFIED | Recorded wrappers match the admitted no-transform case. |
| Actual coplanar redraw order | FINDING #3 | Order-sensitive independent reference/control required in Q0b 3; browser outcome remains pending. |
| Paint-property completeness and rectangle soundness | FINDING #1 | Shifted bitmap and unsupported-paint admissions remain. |
| Pseudo-element/text inspection coverage | FINDING #2 | Originating-element visibility shortcut misses painted content. |
| Original shadow/content/border-image negatives | VERIFIED | Existing gate cases reject; confined/hidden-shadow positives admit. |
| Document-wide gate engagement on real outputs | NOT VERIFIABLE STATICALLY | Final-byte Chrome/CEF host captures and first-rejection diagnostics: Q0b 2, DX-2. |
| Six deck-stub admissions | VERIFIED | Both players reproduce P2 2/4 and DSK 2/3/5/7 counts and listed redraws. |
| Recorded real-DOM probe | VERIFIED | Exact arm has no holder; debug arm has one per transition, reported 22/20 ms. New paint gate was not exercised. |
| Geometry, clipping, opacity and multi-movie stub behavior | VERIFIED | Existing 123-row table and deck tables reproduce identically on both players. |
| Real geometry/edge fidelity | NOT VERIFIABLE STATICALLY | Full-resolution letterbox, 2560×1440 and DSF-2 captures: Q0b 3/5. |
| Frozen 48 versus last presented frame | NOT VERIFIABLE STATICALLY | Unique decoder/rVFC binding and exact-index comparison: Q0b 6, DX-M. |
| Frozen-index and demixing acceptance contract | VERIFIED | Offset zero, independent progress, bounded outgoing weight, separated samples and integrity requirements. |
| Independent foreground reference | VERIFIED | `S_live` is pre-D4 compositor evidence; general ordering coverage needs #3. |
| Actual foreground preservation/control sensitivity | NOT VERIFIABLE STATICALLY | `m-fg`, omission/shift/double-paint controls and added order witness: Q0b 3, DX-1/2. |
| Analytic LUT and tone/redraw sequence | VERIFIED | LUT construction and endpoint behavior; source-alpha check precedes commit; foreground follows tone mapping. |
| Complete colour-tuple admission | VERIFIED | All four fields checked; unsupported/null/failed inspection cases skip. |
| Measured-LUT and identity-fallback decision rules | VERIFIED | Sampling, channel agreement, interpolation, endpoints, launch bounds and conditional controls specified. |
| Actual qualified tuples and fixed-map validity | NOT VERIFIABLE STATICALLY | Encoding/patch/ramp measurements, two CEF launches: Q0b 1; DX-2 confirmation. |
| HEVC unavailable versus missing capture | VERIFIED | Explicit N/A with decode evidence; missing capture remains INCONCLUSIVE. |
| Total-take timing instrument | VERIFIED | `finally` publication; controlled-clock success/rejection/exception cases reproduce. |
| Actual cost and memory behavior | NOT VERIFIABLE STATICALLY | Final gate/LUT workload and retained allocations: Q0b 4, DX-M. Debug 22/20 ms is not final-byte qualification. |
| Main bridge residual and Q6 ownership | VERIFIED | `keepAtSlot` maintains visible opacity 1; follow-up remains after S2. |
| Bridge pixels and negative-control sensitivity | NOT VERIFIABLE STATICALLY | Q0b 5; `m-bridge-off` and report-only `m-bridge`, DX-1/2. |
| Historical cross-fade/cut/tone maxima | NOT VERIFIABLE STATICALLY | Historical reports are distinguished from final-byte repetitions: Q0b, DX-1/2. |
| Capture integrity and expected-FAIL semantics | VERIFIED | Missing/malformed evidence cannot satisfy a negative control. |
| Texture, flash, curve, cut, hand-off and screen controls | VERIFIED | Applicable controls and synthetic cases are specified. |
| CEF session matrix/calibration | VERIFIED | Controls retained; unclamped calibration rejects `n > 4`. |
| Actual CEF compositor qualification | NOT VERIFIABLE STATICALLY | Q0b and DX-2; API availability alone does not establish pixels. |
| Lifecycle coverage and cleanup | NOT VERIFIABLE STATICALLY | Required scenarios are enumerated; execution/cleanup settled by Q0b dry run and DX-1. |
| Production transparency and owner-visible result | NOT VERIFIABLE STATICALLY | DX-3 affected-transition precheck, candidate/null and tone decision. |
| Switch, preview, oracle and runtime-version separation | VERIFIED | Existing integration supports the prescribed contract. |
| Regression/work-stream/minimal-test requirements | VERIFIED | Gates retained; fixes fit existing parametrized functions; W3 follows W2. |
| Final owner decisions 1–7 | VERIFIED | Preserved; no finding requires reopening them. |

**MUST-FIX-BEFORE-IMPLEMENTATION:** #1 confinement/bitmap positioning; #2 pseudo/text visibility bypass; #3 explicit coplanar ordering criterion. Actual frame binding, compositor ordering, tone, engagement and cost remain Q0b measurements.

**Verdict: ready for owner review after listed fixes.**