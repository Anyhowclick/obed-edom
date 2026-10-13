# Plan critique r6 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 7 `cacfe9fb`. Prompt: `plan-astra-r6.prompt.md`.

**Part A**

References: `P` = [rev-7 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md); `B` = [dpatch10.py](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/planner/dpatch10.py). HEAD is `cacfe9fb`; the working plan matches it. Checks ran in memory/stdout; no files were edited.

| r5 # | Status | Evidence | Remaining fix wording |
|---|---|---|---|
| r5-1 | partly closed | P:173–183; B:21–26. Paint containment, content visibility and canvas view-box cases now skip. All 55 property-rejection rows reproduce on both players. The broader faithful-paint claim still fails: findings #3–4. | Close the remaining paint-admission holes with conservative skips. |
| r5-2 | closed | P:177,298–305,390,485–487; B:32. Admission compares all four colour-space fields against `Q`; unexpected range/primaries, null transfer and failed inspection skip. Q0b records decoded tuples and fixes the constants. | None; actual qualification of `Q` remains pending Q0b. |
| r5-3 | closed | P:289–301,363,385,425–429,485–488. Identity fallback makes tone nonblocking and omits the identical raw arm. Foreground retains its independent, tone-invariant reference. | None. |
| r5-4 | closed | P:173–182; B:23–26,42. Relevant scene branches must be absolute/block; the flex-order counterexample now skips on both players. | None for the ordering counterexample. |
| r5-5 | closed | P:298–305,485–487 specifies snapshot→live samples, medians, shared-channel agreement, interpolation, endpoints, observed entries, numerical launch agreement and HEVC N/A versus missing-capture treatment. | None for the reported construction/evidence omissions. |
| r5-6 | closed | P:292,452–453 supplies boundary and integrity controls. Controlled-clock execution publishes 37 ms on success, rejection and exception, both players. | None. |

**Part B — NEW findings**

1. **Severity: major. Class: new class. §§3.2, 8, 9.0 — The allowlist rejects Chromium’s default video and canvas styles.**

   **Claim:** The code-derived profile admits the real movie DOM represented by the six deck stubs.

   **Evidence:** P:173 allows only `overflow:visible` or `hidden`; B:23 rejects `clip`. B:42 additionally requires every later foreground branch element—including the canvas itself—to have `overflow:visible`.

   Chromium’s UA stylesheet gives **video, canvas and img** `overflow:clip; overflow-clip-margin:content-box`. The behavior dates from Chrome 108. [Chromium stylesheet](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/html/resources/html.css), [Chrome’s implementation notice](https://developer.chrome.com/blog/overflow-replaced-elements)

   The player does not override these defaults: `xB.initVideo` @2268249 calls helper `a` @1977282, which sets geometry, position, opacity and visibility; canvas construction around @2297600 likewise leaves overflow untouched. These offsets are identical in both players.

   Both stub families instead default overflow to `visible`. Re-running the unchanged methods with UA-correct video/canvas overflow changes **all six deck cases to zero holders**. Separately, correcting only an intersecting foreground canvas also rejects the movie.

   Q0b 2’s mandatory admission check **would catch this**; the present stub result does not establish engagement.

   **Exact fix wording:** “Model the supported Chromium UA defaults explicitly. Permit the verified `overflow:clip`/content-box case on borderless, padding-free bitmap leaves, including foreground canvases, while retaining the conservative ancestor-clip restrictions. Distinguish a bitmap leaf’s own content clipping from clipping by its branch ancestors. Correct both stub families and require real computed-style admission in headless Chrome and CEF before W1.”

2. **Severity: major. Class: new class. §§3.2, 8, 9.0 — Body overflow is incorrectly treated as a clip to the body’s bounding box.**

   **Claim:** Every admitted `overflow:hidden` ancestor supplies a rectangular clip that can be intersected using `getBoundingClientRect()`.

   **Evidence:** B:34 applies this rule through `<html>`. The player’s embedded stylesheet sets `body{overflow:hidden;margin:0}` @1941444, while the stage and other visible page components are positioned out of normal flow. Neither the player’s body handling nor [live_host.py:418](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_host.py:418) assigns the body a viewport-sized box.

   With visible overflow on `<html>`, the body’s overflow propagates to the **viewport**; the body then has used overflow `visible`. Its computed `hidden` value therefore does not establish a clip to its own box. [CSS Overflow, viewport propagation](https://drafts.csswg.org/css-overflow-3/#overflow-propagation)

   The deck stub at `node_f3_r10_decks.py:54` substitutes a 1920×1080 body with **visible** overflow, concealing both differences. In-memory execution with computed body overflow `hidden` and a zero-height body rectangle takes **zero holders**, despite an otherwise admissible movie. The zero-height case follows from an absolute-only page; its actual rectangle must be recorded in Q0b.

   This remains independently wrong after fixing finding #1.

   **Exact fix wording:** “Handle the export’s verified root/body overflow propagation as a viewport clip, not a clip to the body’s bounding rectangle. Keep ordinary element clipping unchanged. Add a zero-height, viewport-propagating body case to the existing table, correct the deck stub’s body styles, and record root/body rectangles and overflow in Q0b’s real-DOM evidence.”

3. **Severity: major. Class: edge case. §3.2 — Unlisted paint sources still pass the ‘positive allowlist’.**

   **Claim:** Anything outside the supported painted-bitmap profile skips, and admitted paint is reproducible by the snapshot.

   **Evidence:** B:19–26 never examines `border-image-source` or CSS-generated/replacement content. `own()` considers tag names, conventional decoration and DOM text, but not generated content.

   In-memory execution admitted:

   - A foreground canvas with `border-image-source:linear-gradient(red,red)`, `border-image-slice:0 fill` and explicit `border-image-width:10px`, while all four border styles remain `none`. Only its bitmap is redrawn.
   - A later intersecting `DIV` with `content:url(foreground.png)`. It is classified as having no own paint and ignored.

   Border images can paint independently of ordinary border styles; CSS content can replace an element with an image. Generated `::before`/`::after` boxes are another uninspected paint source. [CSS border images](https://drafts.csswg.org/css-backgrounds/#border-image-source), [CSS replacement content](https://drafts.csswg.org/css-content-3/#content-property), [CSS generated pseudo-elements](https://drafts.csswg.org/css-pseudo-4/#generated-content)

   These are source/specification counterexamples, not claims that the supplied decks currently use those styles. They invalidate the advertised admission guarantee, and ordinary P2 engagement cannot detect them.

   **Exact fix wording:** “Require no border-image or CSS replacement/generated paint on admitted bitmap elements and relevant scene branches. Inspect generated pseudo-elements where they can cover the movie, or conservatively reject their presence. Extend the existing property/case table with transparent-canvas border-image, replacement-content and generated-foreground cases; preserve stock behavior rather than reproducing them.”

4. **Severity: major. Class: edge case. §3.2 — The bounding-box prefilter bypasses even existing unsupported-paint checks.**

   **Claim:** Every other painted element meeting the movie region is checked before admission.

   **Evidence:** B:39–40 discards nonintersecting **element rectangles before inspecting decoration or branch styles**. A border box does not bound all paint: shadows and other ink overflow can extend beyond it. [CSS ink overflow](https://drafts.csswg.org/css-overflow-3/#ink-overflow)

   Reproduction using the unchanged Node methods:

   - Movie region starts near x=109 and ends at x=1061.
   - A later positioned div has rectangle `[1100,800,100,100]`.
   - Its opaque red shadow is offset −200 px horizontally, painting inside the movie region.

   Result: **one holder, zero foreground redraws**. The div is discarded by the rectangle test before `deco()` can notice its shadow. The holder consequently covers foreground paint that admission should have rejected.

   Merely adding more properties to `al()` or `bm()` cannot fix this ordering error.

   **Exact fix wording:** “Use rectangle nonintersection only after proving that the element’s paint is confined to that rectangle. Conservatively skip candidates exposed to unsupported overflowing paint before applying the rectangle prefilter; do not calculate general shadow/filter bounds. Add an outside-border-box shadow crossing the movie and a confined nonintersecting positive to the existing table.”

**Part C — Closing inventory**

`VERIFIED` identifies a checked static property or reproduced retained result; it does not certify pending browser measurements.

| Verifiable claim class | Status | Evidence / measurement and scheduling |
|---|---|---|
| Revision identity | VERIFIED | HEAD `cacfe9fb`; working plan matches. |
| Inline methods versus builder | VERIFIED | Exact correspondence with `dpatch10.reps()`; D1 replacement is 7,896 bytes. |
| Supported stock player hashes | VERIFIED | Both full hashes match `SUPPORTED_PLAYERS`. |
| Two PDF.js insertions and displaced offsets | VERIFIED | Removing the two insertions reproduces the older player exactly. |
| All 13 anchor counts and offsets | VERIFIED | Recomputed both players; each occurs once, at the listed offsets. |
| Anchor interval disjointness | VERIFIED | All 13 intervals disjoint. |
| Replacement containment, including self and hook | VERIFIED | Empty containment set. |
| R1–R5 / R6–R8 / D1–D4 order independence | VERIFIED | All six group orders produce identical bytes on both players. |
| Anchor consumption and replacement uniqueness | VERIFIED | Every rendering anchor absent afterward; each replacement present once. |
| Complete patched JavaScript | VERIFIED | Rendering/on/off outputs all pass stdin `node --check`, both players. |
| Off identity and repinning scope | VERIFIED | Existing off hashes preserved; new on/rendering hashes require the planned repin. |
| In-memory patching and unknown-player refusal | VERIFIED | Existing runtime mechanism supports the specified integration; no disk-player mutation required. |
| CSS routing and flattened transition structure | VERIFIED | Primary player construction supports the stated Dissolve/cut mechanism. |
| Render/animate separation and D4 placement | VERIFIED | D4 precedes teardown; render precedes timer-driven animation. |
| Export census | VERIFIED | Recomputed 25 roots: 42 Dissolves, 8 cuts, 67 Magic Moves, 382 builds. |
| Predicate engagement and source immutability | VERIFIED | Real-class execution: 46 Dissolves, 8 cuts, 79 stock, zero mutations. |
| Predicted layer IDs | VERIFIED | Real `VB` allocations match inserted selectors on both players. |
| Construction-failure behavior | VERIFIED | Five failure cases return stock; abandoned rules target no constructed nodes. |
| Dissolve/cut near-misses | VERIFIED | Existing 21 + 10 near-misses reproduce stock behavior. |
| Additive cross-fade arithmetic | VERIFIED | Correct under its stated geometry/coverage assumptions. |
| Complementary 1-ms cut contract | VERIFIED | Implementation and fractional-opacity acceptance agree. |
| D3 attachment and failure handling | VERIFIED | Cut leaf, Dissolve wrapper, missing-wrapper discard and throwing append reproduce. |
| Add-only video behavior | VERIFIED | All 105 rows per player record zero video touches. |
| Existing F3 property table | VERIFIED | All 55 explicit property-rejection rows skip; table completeness is separate. |
| Actual UA overflow compatibility | FINDING #1 | UA-correct bitmap defaults make every deck stub produce zero holders. |
| Root/body clipping semantics | FINDING #2 | Viewport propagation is incorrectly replaced by body-box clipping. |
| Stage preserve-3d and movie relocation | VERIFIED | Updated model reflects `Cg.adjustStageToFit` and `M.parentNode.appendChild(L.movieDiv)`. |
| Remaining paint-property coverage | FINDING #3 | Border-image and generated/replacement content escape inspection. |
| Paint-overlap discovery | FINDING #4 | Nonintersecting border boxes can paint into the movie region. |
| Flex/grid ordering exclusion | VERIFIED | Relevant non-block/non-absolute branches reject; flex-order case skips. |
| Independent X/Y geometry and aspect-changing fill rejection | VERIFIED | Existing equal/unequal-fill and source-alpha cases reproduce. |
| Multiple-movie holder ordering | VERIFIED | Supported stub cases reproduce last-first admission and reversed attachment. |
| Foreground redraw opacity and ordering | VERIFIED | Existing α=1/0.2947/0.5 rows reproduce; redraw follows tone mapping. |
| Actual P2/DSK DOM engagement | NOT VERIFIABLE STATICALLY | Q0b 2 catches P2 admission failure; Q0b 6 schedules DSK. P2 engagement alone does not establish every DSK case. |
| Real scaled/letterboxed/DSF-2 pixels | NOT VERIFIABLE STATICALLY | Full-resolution residuals in Q0b 5, after findings #1–2. |
| Analytic LUT arithmetic | VERIFIED | 128→139.1595; maximum +11.3268 at 113; minimum −4.3243 at 9. |
| Source-alpha check and tone/redraw sequence | VERIFIED | Alpha inspected before committing mapped pixels; foreground drawn afterward. |
| Complete tuple admission | VERIFIED | Full tuple comparison; unsupported/null/failed inspection rows skip. |
| Qualified tuple set and provenance | NOT VERIFIABLE STATICALLY | Q0b 1 records decoded tuples and fixes `Q`; media/CEF records retain tuples and served digest. |
| Measured-LUT construction contract | VERIFIED | Sampling, median aggregation, interpolation, endpoints and observed-set recording specified. |
| HEVC unavailable versus missing evidence | VERIFIED | Undecodable path is explicit N/A with evidence; decoded but uncaptured is INCONCLUSIVE. |
| Actual fixed-map validity and launch agreement | NOT VERIFIABLE STATICALLY | Ramp/patch/encoding comparisons and two CEF launches: Q0b 1; DX-2 confirmation. |
| Conditional tone acceptance | VERIFIED | Nonidentity candidate/raw controls block; identity residual reports without contradictory outcomes. |
| Independent foreground reference | VERIFIED | Pre-D4 compositor `S_live`; comparison does not derive truth from the holder. |
| Foreground pixel preservation and negative sensitivity | NOT VERIFIABLE STATICALLY | `m-fg`/`m-fg-omit`, shifted/double-painted cases: Q0b 3, DX-1, DX-2. |
| Total-D4 timing coverage/publication | VERIFIED | Enclosing timer and `finally`; 37-ms controlled-clock success/rejection/exception results reproduce. |
| Cost instrument boundary/integrity contract | VERIFIED | 50 ms PASS, above-bound FAIL, missing/nonfinite INCONCLUSIVE specified. |
| Actual total cost and memory use | NOT VERIFIABLE STATICALLY | Q0b 4; retained/transient allocation categories are stated correctly. |
| Main bridge and S2 hold residual ownership | VERIFIED | Existing independent paint remains assigned to the post-S2 Q6 follow-up. |
| Terminal bridge pixels and control sensitivity | NOT VERIFIABLE STATICALLY | Q0b 5 and `m-bridge-off`/`m-bridge` in DX-1/DX-2. |
| Historical browser pixel maxima and freeze/tone claims | NOT VERIFIABLE STATICALLY | Retained reports are historical; current-byte repetitions scheduled in Q0b/DX-1/DX-2. |
| Browser API support versus compositor qualification | VERIFIED | They are correctly distinguished; API availability does not certify CEF pixels. |
| Decoder binding and demixing algebra | VERIFIED | Unique-region binding and independent progress fit support `(F−eB)/(1−e)`. |
| Exact frozen-index and demixing behavior | NOT VERIFIABLE STATICALLY | Bound rVFC/holder/screenshot evidence: Q0b 6 and DX-M. |
| Capture integrity and expected-FAIL semantics | VERIFIED | Missing/malformed evidence remains INCONCLUSIVE; never satisfies FAIL. |
| Patch-off media evidence | VERIFIED | Intentional holder absence distinguished from missing candidate evidence. |
| Texture, flash, curve, monotone, hand-off and cut controls | VERIFIED | Applicable positive/negative controls and synthetic cases specified. |
| CEF session matrix and calibration | VERIFIED | Includes media/cut/bridge negative; unclamped caps reject `n>4`. |
| Lifecycle coverage | VERIFIED | Advance, replay, queue, skip, navigation, hide/show, automatic, wrap and terminal rows retained. |
| Actual lifecycle cleanup | NOT VERIFIABLE STATICALLY | Q0b dry run and DX-1 lifecycle scenario. |
| Production transparency and owner-visible result | NOT VERIFIABLE STATICALLY | DX-3 pre-check, candidate/null observation and recorded tone decision. |
| Switch, preview, oracle and runtime-version separation | VERIFIED | Existing integration supports the specified unchanged switch and version contract. |
| Regression scheduling | VERIFIED | Full gates, opacity/hand-back probes, `mmo`, `g2`, `mmo-cef` retained. |
| Work-stream disjointness | VERIFIED | W0 changes stripper/test; W1–W4 ownership is separate; W3 follows W2. |
| Minimal-tests rule | VERIFIED | Shared parametrized tables accommodate these fixes; no additional test function is needed. |
| Final owner decisions 1–7 | VERIFIED | Preserved; none of these findings requires reopening them. |

**Verdict: needs another planning pass.**