# Plan critique r4 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 5 `e5c644bb`. Prompt: `plan-astra-r4.prompt.md`.

**Part A — Round-3 disposition**

`P:line` refers to the [rev-5 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md). The working file matches `e5c644bb`. Checks ran in memory/stdout; no files were edited.

| r3 # | Status | Evidence | Remaining fix wording |
|---|---|---|---|
| r3-1 | closed | P:89–94, 235–236, 371, 478–482 explicitly retain main’s terminal bridge as a Q6(b) residual, add `m-bridge`, and assign retirement to S2. Main’s `keepAtSlot` still confirms the stated behavior. | Preserve the explicit scope limitation and S2’s blocking handover. |
| r3-2 | closed | P:305–306, 327–332 specifies decoder binding, independent progress fitting, demixing, bounded amplification and separated samples. P:435–437 adds overlap and two-decoder cases. | Preserve these corrections. The new foreground-reference gap is finding #4 below. |
| r3-3 | closed | P:374–378 gives `m-off` its own complete-evidence contract and intentionally requires no holder. P:437–438 distinguishes behavioral FAIL from missing evidence. | None for the original contradiction. |
| r3-4 | partly closed | P:172–175 adds occlusion/order admission and canvas redraw. The 47-row table reproduces its stated outcomes, but additional admitted cases violate foreground preservation. | Apply findings #2–3. |
| r3-5 | partly closed | Reflections through `transform`, nonuniform matrices, unsupported object positioning and the listed clips are rejected. Uniform-scale and letterboxed holder coordinates reproduce. `fill` still uses the wrong vertical mapping; additional CSS clipping/transform cases remain admitted. | Apply findings #1–2. |
| r3-6 | partly closed | Natural-resolution inspection replaces the sparse probe, but its source rectangle is wrong for aspect-changing `fill`. Transparent pixels contributing to the holder can remain unchecked. | Apply finding #1. |
| r3-7 | closed | P:137, 159–161 selects attachment by kind. Rerun: real cut attaches to the leaf; missing Dissolve wrapper and throwing append attach nothing. | None. |
| r3-8 | partly closed | P:398–401 adds all four requested cut/media sessions, holder evidence and continuity/G2 state. However, the newly designated independent-overlay negative is absent from DX-2. | Apply finding #5. |
| r3-9 | partly closed | Exported cut timing is enforced; all ten cut near-misses are rejected. P:109–111 accurately permits partial opacity inside 1 ms, but P:348 still rejects it. | Apply finding #6. |
| r3-10 | closed | P:469–477 accurately distinguishes decoder ownership from overlay retirement, labels live-video tone continuity unmeasured, and defines Q5(a)/(b) acceptance consequences. | None. |
| r3-11 | closed | Header includes R8, D4 and the hook. Recomputed D4 offsets: 2353722 / 2353760. | None. |

**Part B — New findings**

1. **Severity: major. Class: closed class. §§3.1–3.2 — `object-fit: fill` breaks both foreground geometry and the opacity proof.**

   **Claim:** Every contributing source pixel is checked, and foreground canvases are redrawn at their displayed geometry.

   **Evidence:** P:136 uses `sx=vw/cw` for **both axes** of `getImageData`; Q7(b) also uses it for foreground Y and height. See [dpatch7.py:44](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/planner/dpatch7.py:44) and [dpatch8.py:18](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/planner/dpatch8.py:18).

   In-memory execution with a 1920×540 source displayed at 952×134, `object-fit:fill`:

   - Both builders admit a source whose transparent pixel lies on row 400: only approximately the first 271 source rows are inspected.
   - Q7(b) maps foreground at displayed Y offset 55 to source Y 110.924; the correct value is 221.642. Its height is likewise approximately halved.

   The attached canvas still contains the entire source. Consequently, unchecked transparency can expose the baked movie underneath, and foreground can move visibly.

   **Exact fix wording:** “Use independent source scales `sx=videoWidth/contentWidth` and `sy=videoHeight/contentHeight` for opacity bounds and foreground redraw. Alternatively, conservatively reject `fill` when those scales differ. Add aspect-changing fill, lower-source transparency and foreground-placement rows to the existing parametrized table.”

2. **Severity: major. Class: edge case. §3.2 — The admission predicate still accepts CSS appearance that `drawImage` does not reproduce.**

   **Claim:** Admitted videos and “plain canvases” can be reproduced exactly by the snapshot.

   **Evidence:** P:136; `dpatch8.py:7–13`. Additional in-memory cases all attach successfully:

   - Foreground canvas with a CSS background or box shadow.
   - Foreground canvas or video with a nonzero corner radius.
   - Video with `transform:none; scale:-1 1`.

   `drawImage(canvas)` copies the bitmap, not its CSS background, shadow or clipped presentation. Rounded replaced-element content is clipped even without an overflowing ancestor. Individual `scale`/`rotate` properties also contribute separately from `transform`. These behaviors are specified by the [HTML canvas source rules](https://html.spec.whatwg.org/multipage/canvas.html#image-sources-for-2d-rendering-contexts), [CSS corner clipping](https://drafts.csswg.org/css-backgrounds/#corner-clipping), and [CSS transformation-matrix rules](https://drafts.csswg.org/css-transforms-2/#ctm).

   Thus a rounded foreground canvas can paint bitmap corners that were invisible before the transition; a CSS-backed foreground can disappear.

   **Exact fix wording:** “Define a narrow, checked plain-bitmap profile. Skip unsupported CSS decoration, replaced-element corner clipping, and individual transforms on the relevant chains; include legacy clipping where applicable. Do not infer plain appearance from tag name and `transform` alone. Extend the existing admission table with these counterexamples rather than implementing a general CSS renderer.”

3. **Severity: major. Class: closed class. §3.2 — Earlier document order plus `z-index:auto` does not prove an element is behind the movie.**

   **Claim:** P:174–175 says the position and z-index rules preserve document paint order for every admitted case.

   **Evidence:** The earlier-element branch in P:136 / `dpatch7.py:40–42` checks only z-index. The positioned-branch requirement exists only in Q7(b)’s **later-canvas** branch.

   In-memory counterexample: an earlier absolutely positioned canvas, followed by a movie under static, untransformed ancestors. Both builders attach the movie holder and ignore the canvas. Under [CSS painting order](https://www.w3.org/TR/CSS2/zindex.html), the earlier positioned canvas paints above the later in-flow replaced content. The holder subsequently covers foreground already baked into the outgoing texture.

   **Exact fix wording:** “Apply a proven paint-order restriction to earlier intersecting paint as well as later canvases. If the branches cannot be shown to follow the supported ordering, skip the movie. Add an earlier-positioned/later-static counterexample to the existing table; avoid general stacking reconstruction.”

4. **Severity: major. Class: new class. §§9.0–9.1, 10 — The media oracle can pass a permanently wrong foreground reconstruction.**

   **Claim:** The reconstructed reference, frozen-region check and visual cases qualify foreground preservation.

   **Evidence:** P:305–306 constructs A2 from the candidate holder. P:326–328 excludes media rectangles from the ordinary model residual. Inside those rectangles, P:349–350 checks the counter and constancy—not agreement with an independent foreground reference.

   A malformed holder with a missing square can therefore:

   - Decode the correct frozen frame.
   - Produce constant `Ô`.
   - Match “texture + holder” exactly, because that reference contains the same omission.

   A scalar check illustrates the blind spot: movie value 100 under foreground value 240 at opacity 0.2947 should yield 141.258. Omitting the foreground yields demixed value 100 at `e=.2,.4,.6`: zero spread despite a 41.258-LSB error. P2’s square can be wrong without changing its counter strip.

   P:309’s “no foreground lost” requirement is useful, but its independent reference and failure control are unspecified.

   **Exact fix wording:** “Add an independent foreground-preservation reference inside admitted media regions, obtained without using the candidate holder as ground truth. Separate the accepted video tone step from foreground geometry/opacity/order. Add omitted, shifted and double-painted foreground negatives and a correct-redraw positive to the existing scorer table, and require this check in Q0b, DX-1 and DX-2.”

5. **Severity: major. Class: closed class. §9.2 — CEF still lacks the designated negative for independent overlays.**

   **Claim:** DX-2 uses DX-1’s checks and establishes their controls before accepting candidates.

   **Evidence:** P:296 designates `m-bridge-off` as the negative for “No independent overlay.” P:367 requires that check on `m-on`. P:398–399 schedules neither bridge arm in CEF.

   `m-hold` is not equivalent: its holder is a canvas inside the transition container. It tests an unfaded snapshot, not detection of a separately painted tagged decoder outside the transition DOM.

   **Exact fix wording:** “Run `m-bridge-off` in DX-2 as the independent-overlay negative, with tagged-decoder/rVFC/rAF integrity. Under Q6(b), also retain the candidate bridge result as a reported residual if captured; its expected FAIL must not become a main-patch PASS requirement. Require the instrument control outcome before accepting CEF `m-on`.”

6. **Severity: minor. Class: closed class. §§2, 9.1, 10 — The cut acceptance rejects behavior expressly permitted by the implementation.**

   **Claim:** The cut is a complementary 1-ms opacity swap, but P:348 requires no frame with both effective opacities greater than zero.

   **Evidence:** P:109–111 permits intermediate partial opacities. At the midpoint, the prescribed animations produce `(0.5,0.5)`, which fails P:348 despite being correct. The retained cut records reproduce stock union in 2/27 rAF samples and patched union in 0/44; that sampling result does not establish impossibility.

   **Exact fix wording:** “Align the cut gate with the stated guarantee: incoming zero before animation, complementary opacities during the permitted 1-ms swap, incoming-only afterward, and no full-strength union. Define the screenshot equivalent. Add a valid fractional-time cut sample to the existing scorer table.”

7. **Severity: minor. Class: new class. §§3.2, 9.0, 12.7 — The cost contract omits the new admission/redraw work and aggregate transition stall.**

   **Claim:** P:185–186 and 307 describe one draw plus region readback per admitted movie, with a 50-ms per-movie stop.

   **Evidence:** P:136 also scans the whole document per candidate video, repeatedly reads geometry/computed styles, traverses ancestor/subtree chains, and draws every admitted foreground canvas. Rejected candidates incur scanning costs too. Multiple individually acceptable takes can collectively exceed the stated stall budget.

   The quoted Q7(b) byte delta is accurate: **7010−5903 = 1107 bytes**.

   **Exact fix wording:** “Measure total D4 wall time, including admission of rejected candidates, all movie copies, opacity readbacks and foreground redraws. Apply the transition-stall stop to that total; retain per-movie timings as diagnostics. State retained canvas memory separately from transient readback/compositor allocations.”

**Part C — Closing inventory**

“VERIFIED” below means the static property or retained record was checked. It does not mean an unperformed browser qualification passed.

| Verifiable claim class | Status | Evidence / measurement and scheduling |
|---|---|---|
| Reviewed revision and inline builder correspondence | VERIFIED | Working plan matches `e5c644bb`; inline methods equal Q7(b)’s builder, ignoring line breaks. |
| Both stock player identities | VERIFIED | Full SHA-256 values match `SUPPORTED_PLAYERS`. |
| Two PDF.js insertions and offset displacement | VERIFIED | Removing the two insertions at 2331091 and 2331362 reproduces the other player exactly. |
| All 13 anchor counts, offsets and interval disjointness | VERIFIED | Recomputed on both players for both builders. |
| Replacement containment, including self | VERIFIED | Empty containment set for both variants. |
| R1–R5 / R6–R8 / D1–D4 order independence | VERIFIED | All six group orders produce identical bytes, both players and variants. |
| Anchor consumption and replacement uniqueness | VERIFIED | Every original anchor absent; every replacement present once. |
| Complete patched JavaScript | VERIFIED | Rendering/on/off outputs pass stdin `node --check`, both players and builders. |
| D1 size and Q7(b) incremental bytes | VERIFIED | 5903 / 7010 bytes; delta 1107. |
| CSS routing, flattened transition topology and hidden-to-opacity behavior | VERIFIED | Primary player classes and controller paths support the stated mechanism. |
| Separate render/animate tasks and D4 placement | VERIFIED | D4 precedes `displayScene`; ordinary play follows in the same task. Self-playing residual remains explicit. |
| Fixture census | VERIFIED | 25 roots; 42 Dissolves, 8 cuts, 67 Magic Moves, 382 per-object builds. |
| Shape predicate, copied kinds and source immutability | VERIFIED | Real-class rerun: 46 Dissolves, 8 cuts, 79 stock; zero mutations. |
| Construction failures and abandoned IDs | VERIFIED | All five failures return stock; surviving rules target no constructed nodes. |
| Pre-order allocation and predicted rule IDs | VERIFIED | Real `VB` allocation agrees in both players. |
| Dissolve and cut near-misses | VERIFIED | All 21 Dissolve and 10 cut near-misses rejected. |
| Additive arithmetic and isolation | VERIFIED | Correct under its stated geometry/coverage assumptions; consistent with [Compositing’s cross-fade operator](https://drafts.csswg.org/compositing-2/#porterduffcompositingoperators_plus_lighter). |
| D3 attachment kind, slot consumption and append failure | VERIFIED | Real cut leaf, Dissolve wrapper, missing-wrapper discard and throwing-append results reproduced. |
| Add-only behavior toward videos | VERIFIED | No video writes, pause/play calls or reparenting; all 47 existing proxy rows record zero touches. |
| Existing 47-row F3 table | VERIFIED | Stated outcomes reproduced for both variants; table does not prove untested admission cases. |
| Uniform-scale, translated-origin and letterboxed holder mapping | VERIFIED | Existing numerical cases reproduce the stated slide coordinates. |
| Aspect-changing `fill` mapping and opacity coverage | FINDING #1 | Independent X/Y mapping or conservative rejection required. |
| Plain-canvas CSS appearance and clipping | FINDING #2 | Bitmap-only redraw does not reproduce all admitted styles. |
| Occlusion and earlier-element paint order | FINDING #3 | Earlier `z-index:auto` is insufficient. |
| Canvas opacity multiplication and source-over redraw | VERIFIED | Correct for the supported plain bitmap/group cases; existing alpha 1/0.2947/0.5 rows reproduce. |
| No double-paint over baked content | FINDING #1 | The current opacity-region error defeats this guarantee. |
| Overlapping-movie handling | VERIFIED | Existing restricted stub case freezes the later movie only; broader ordering remains finding #3. |
| Admission engagement on actual P2/DSK DOM | NOT VERIFIABLE STATICALLY | Q0b 2 and 5 require real-DOM verdicts and foreground captures. |
| DSF 2, larger viewport and host-path geometry | NOT VERIFIABLE STATICALLY | Q0b 5 schedules captures; stubs alone are insufficient. |
| Full-resolution reconstructed-reference edge maxima | NOT VERIFIABLE STATICALLY | Q0b 3 schedules measurement; independent foreground correctness additionally needs finding #4. |
| Capture cost and memory | FINDING #7 | Total D4 timing needed; Q0b 4 is the assigned measurement point. |
| Main bridge residual and qualification restriction | VERIFIED | `keepAtSlot`/`slotLive` and the qualified-plan refusal support the scoped claim. |
| Main bridge’s actual terminal pixels | NOT VERIFIABLE STATICALLY | Q0b 1 and DX-1 `m-bridge(-off)` schedule the measurement. |
| S2 hold/bridge integration requirement | VERIFIED | Git-ref source retains the outgoing hold; rev 5 assigns retirement and blocking bridge qualification to S2. |
| Q5(a) wording and acceptance | VERIFIED | Tone is report-only numerically; noticeable DX-3 step reopens Q5. No guaranteed live-element alternative is claimed. |
| Q6(b) scope/default | VERIFIED | Coherent as an explicit retained residual, with S2 ownership; it does not claim complete main terminal-media correction. |
| Q7(b) default as written | FINDING #1–4 | Unsound until geometry, admission and independent foreground acceptance are corrected. |
| Historical cross-fade/opaque/software pixel maxima | NOT VERIFIABLE STATICALLY | No planner-run PNGs remain at the supplied location. Fresh current-byte repetitions are scheduled in Q0b/DX-1. |
| Historical cut rAF counts | VERIFIED | Retained JSON reproduces stock 2/27 and patched 0/44 union samples. |
| Historical cut screencast counts and freeze/tone pixels | NOT VERIFIABLE STATICALLY | Required image evidence is not retained there; Q0b 6 and DX-2 schedule fresh captures. |
| Browser feature availability | VERIFIED | [Chrome 100 `plus-lighter`](https://web.dev/blog/web-platform-03-2022); [Chrome 121 visibility options](https://groups.google.com/a/chromium.org/g/blink-dev/c/ruNqbP3wDSY); installed OBS framework plist reports CEF 127. |
| CEF compositor and tone behavior | NOT VERIFIABLE STATICALLY | DX-2 remains required. |
| Decoder binding and demixed-estimate algebra | VERIFIED | Unique geometry binding rejects ambiguity; subtracting incoming contribution corrects the earlier raw-decoding error. |
| Exact rVFC reference agreement and demixing noise | NOT VERIFIABLE STATICALLY | Current-byte `m-on`/`m-paused` captures in Q0b, DX-1 and DX-2 settle it. |
| `m-off` and other per-arm media evidence | VERIFIED | Holder absence is intentional only for `m-off`; complete evidence is required before behavioral FAIL. |
| Foreground correctness within media regions | FINDING #4 | Constancy and candidate-derived A2 are insufficient. |
| Shared integrity and INCONCLUSIVE semantics | VERIFIED | Scene/texture/digest/dimensions/sampling requirements are explicit; INCONCLUSIVE cannot satisfy FAIL. |
| Texture-model, complement, dip, curve, monotone and hand-off controls | VERIFIED | Their written positive/negative contracts are coherent; executions remain scheduled. |
| Screen-path and delayed-animation coverage | NOT VERIFIABLE STATICALLY | Q0b 6 and DX-1 schedule the relevant arms. |
| Cut acceptance contract | FINDING #6 | Must permit the implementation’s fractional 1-ms samples. |
| DX-2 added cut/paused/hold sessions | VERIFIED | Present with holder and continuity/G2 evidence requirements. |
| DX-2 independent-overlay control | FINDING #5 | Designated negative is missing. |
| CEF calibration formulas and boundary | VERIFIED | Unclamped formulas jointly require `n≤4`; boundary cases remain assigned. |
| Lifecycle scenario completeness | VERIFIED | Advance, replay, queue/skip, go-to/back, hide/show, automatic delay, loop and terminal retention/navigation are listed. |
| Lifecycle pixels, timing and cleanup outcomes | NOT VERIFIABLE STATICALLY | Q0b dry run and DX-1 scenario must demonstrate them. |
| Switch, pins, reports, preview and stock oracle separation | VERIFIED | Existing routing supports the design; off hashes reproduce `7cf00b56…` / `4f9fbffd…`; on/rendering require implementation re-pins. |
| Fresh-strip/shared-media resolver contract | VERIFIED | W2/W3 share provenance and decode requirements; W0 changes only stripper and its test. |
| Production transparency and owner-visible improvement | NOT VERIFIABLE STATICALLY | DX-3 pre-check and separate candidate/null observations are scheduled. |
| Regression inventory | VERIFIED | Includes full gates, opacity/hand-back probes, P2 arms and managed `mmo`, `g2`, `mmo-cef`; outcomes remain unmeasured. |
| Minimal-tests rule | VERIFIED | Three new functions remain coherent; findings fit additional rows in existing parametrized tables. |
| Work-stream file disjointness and dependencies | VERIFIED | W0–W4 files are disjoint; conditional W5 is separate; W3 follows W2. |
| Final owner decisions 1–4 and F2 deferral | VERIFIED | Preserved; no reopening required by these findings. |

**Verdict: needs another planning pass.**