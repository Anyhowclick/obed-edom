# Plan critique r5 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 6 `218308c3`. Prompt: `plan-astra-r5.prompt.md`.

**Part A — Round-4 disposition**

References: `P:line` = [rev-6 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md); `B:line` = [dpatch9.py](/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/planner/dpatch9.py). HEAD is `218308c3`; the working plan matches that commit. Checks used memory/stdout only; no files were edited.

| r4 # | Status | Evidence | Remaining fix wording |
|---|---|---|---|
| r4-1 | closed | P:139,173–175; B:34–44 uses independent `sx`/`sy` and rejects aspect-changing fill. Rerun rejects lower-source transparency; accepted fill maps displayed Y=55 to source Y=110. | None. |
| r4-2 | partly closed | All original decoration, radius and individual-transform counterexamples now skip. Additional unsupported clipping/cropping remains admitted; finding #1. | Extend the existing whitelist and case table with conservative skips. |
| r4-3 | partly closed | Both branches now require positioning; the original earlier-positioned/later-static case skips. Raw document order still is not guaranteed for every admitted layout; finding #4. | Exclude reordered layout from the supported paint-order profile. |
| r4-4 | closed | P:335–337 establishes pre-D4 compositor `S_live`, independent of the holder. P:355,377,407,447–448 supplies foreground positives and omission/shift/double-paint negatives in Q0b, DX-1 and DX-2. | Preserve this independence. Resolve the separate tone-fallback contradiction in finding #3. |
| r4-5 | closed | P:408–411 schedules CEF `m-bridge-off`, requires its FAIL before acceptance, and keeps candidate `m-bridge` report-only. | None. |
| r4-6 | closed | P:352 accepts complementary intermediate opacities; P:444–445 explicitly accepts `(0.5,0.5)`. | None. |
| r4-7 | closed | B:10,46 measures total D4 time through `finally`; P:186–188 separates retained/transient allocations; P:312,358 applies the aggregate 50-ms budget. | Original cost-contract omission is closed. Add the missing instrument controls identified in finding #6. |

**Part B — New findings**

1. **Severity: major. Class: edge case. §3.2 — The narrowed bitmap profile still admits clipping and cropping that the snapshot discards.**

   **Claim:** Every admitted presentation is reproducible by the bitmap snapshot.

   **Evidence:** P:139,171–176; B:20–23,28,31–32. In-memory execution of the unchanged methods admitted both:

   - A movie under a 300-px-wide ancestor with `contain:paint; overflow:visible`. The holder remained **952 px wide**. Paint containment clips descendants independently of the computed overflow values inspected here. [CSS Containment §3.5](https://drafts.csswg.org/css-contain-2/#paint-containment)
   - A foreground canvas with `object-view-box:inset(25%)`. It was redrawn using the entire source bitmap. Only the movie receives the `objectViewBox` check. The property applies to replaced elements and changes the content region used by `object-fit`. [CSS Images §3.1](https://drafts.csswg.org/css-images-5/#propdef-object-view-box)

   These cases can reveal previously clipped movie pixels or change foreground content at transition start.

   **Exact fix wording:** “Require `object-view-box:none` for every redrawn canvas as well as the movie. Conservatively skip relevant chains with paint containment, including containment implied by `content-visibility`, unless their clipping is explicitly proved. Add these counterexamples to the existing F3 table; do not implement additional CSS rendering.”

2. **Severity: major. Class: new class. §§3.2, 9.0, 12.5 — Transfer-only admission exceeds the colour profile qualified for `L`.**

   **Claim:** The conservative colour restriction keeps unsupported movies outside the fixed BT.709 tone correction.

   **Evidence:** P:139,173,192–193; B:29 reads only `colorSpace.transfer`. An in-memory `VideoFrame` reporting `{primaries:"bt2020", transfer:"bt709", matrix:"bt2020-ncl"}` was admitted and received `128→139`. Q0b schedules BT.709 encodings, not that profile.

   Transfer characteristics and colour primaries are separate properties; matching transfer does not establish matching gamut conversion. Moreover, Chromium maps unsupported transfer enum values to unspecified, so a null transfer is not proof of an untagged BT.709 default. [WebCodecs colour-space definitions](https://www.w3.org/TR/webcodecs/#videocolorspace), [Chromium’s conversion implementation](https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/renderer/modules/webcodecs/video_color_space.cc)

   This does **not** establish an observed colour error for those movies; it establishes that the proposed qualification cannot justify applying `L` to everything admission accepts.

   **Exact fix wording:** “Record the complete decoded colour-space tuple during Q0b and restrict nonidentity `L` to the tuples actually qualified. Skip unexpected primaries/matrix/range combinations and failed or ambiguous inspection. Preserve untagged H.264 support where its decoded/default profile is established by Q0b; do not equate every unreported transfer with that default. Add reported non-BT.709 primaries and ambiguous-transfer cases to the existing table.”

3. **Severity: major. Class: closed class. §§9–9.3, 12.5 — The authorized identity fallback cannot satisfy the written tone acceptance.**

   **Claim:** Q5 can select identity `L` and ship a documented brightness-step residual.

   **Evidence:** P:484–485 permits that outcome, but P:300,356,378 still requires `m-tone` PASS and identity-`L` `m-tone-raw` FAIL. Under the fallback, those arms perform the same pixel operation. They cannot reliably produce opposite outcomes. P:410–411 requires every control outcome before accepting the candidate, and P:423 still requires no noticeable brightness step.

   The same conflict affects a headless path made report-only by P:482 unless its control requirement is also made conditional.

   **Exact fix wording:** “Make tone acceptance conditional on Q0b’s recorded decision. With a qualified nonidentity `L`, require the tone candidate and raw negative outcomes. With identity fallback, report the measured tone residual and mark tone-match acceptance nonblocking; do not require identical arms to PASS and FAIL. Retain foreground acceptance on the stated tone-invariant counter-block reference. State the same fallback exception in DX-3. Missing evidence remains INCONCLUSIVE and never counts as a negative-control FAIL.”

4. **Severity: major. Class: edge case. §3.2 — Positioning plus `z-index:auto` still does not prove raw document paint order.**

   **Claim:** P:176 says the two positioned branches make document order equal paint order.

   **Evidence:** B:22,37–40 checks positioning and z-index but not layout ordering. In-memory execution admitted an earlier canvas flex item with `position:relative; order:1`, followed in the DOM by the movie’s flex-item branch with `position:relative; order:0`. It ignored the earlier canvas and attached the movie holder.

   Flex painting uses **order-modified** document order. The earlier canvas can therefore paint above the movie despite satisfying both branch checks. [CSS Flexbox §4.3](https://drafts.csswg.org/css-flexbox-1/#painting)

   **Exact fix wording:** “Limit the paint-order proof to the player’s supported, non-reordered layout. Conservatively skip intersecting branches whose flex/grid ordering can differ from document order, including relevant ordering ancestors. Add an earlier-DOM/later-painted case to the existing table. Retain the current ordinary positioned-branch controls.”

5. **Severity: minor. Class: new class. §§9.0–9.1, 12.5 — The measured-LUT branch lacks a reproducible construction and incomplete-evidence decision.**

   **Claim:** Q0b deterministically chooses the analytic curve, a measured 256-entry LUT, or identity.

   **Evidence:** P:322 specifies a **220-step luma ramp**, while P:484 selects a measured **256-entry** table without defining how entries are indexed, how unobserved decoded RGB values are filled, or how duplicate/noisy observations are combined. P:482 requires the “same map” across launches without a numerical comparison rule. P:307 makes HEVC conditional on decoding, while P:483 requires HEVC agreement without defining the unavailable case.

   The analytic arithmetic is correct; the alternative decision cannot yet be reproduced from the written measurement contract.

   **Exact fix wording:** “Define LUT samples as decoded snapshot-channel value → live-compositor channel value. Specify deterministic aggregation, interpolation for unobserved entries, endpoint handling and the numerical inter-launch agreement bound. Record which entries were measured. Define the undecodable-HEVC outcome explicitly: its equivalence claim remains INCONCLUSIVE, with the stated fallback or conservative exclusion applied; it must not silently satisfy the three-encoding condition.”

6. **Severity: minor. Class: new class. §§9–10 — The new total-D4 cost gate has no designated controls.**

   **Claim:** Every blocking instrument has a passing positive and failing negative.

   **Evidence:** P:358 makes cost blocking, but P:287–301 has no cost-control pair. P:439–450 adds neither a timing-integrity case nor the 50-ms boundary cases. Successful `m-on` timing alone does not establish detection of an over-budget take or invalid timing evidence.

   **Exact fix wording:** “Extend the existing parametrized tables with cost controls: a known finite duration at 50 ms passes, 50 ms + ε fails, and missing/nonfinite timing is INCONCLUSIVE. Exercise total-timing publication on success, rejection and exception paths using a controlled clock. Name these controls in §9; add no new test function.”

**Part C — Closing inventory**

“VERIFIED” means the static property or retained record was checked; it does not imply an unperformed browser qualification passed.

| Claim class | Status | Evidence / measurement and scheduling |
|---|---|---|
| Revision identity and inline-builder correspondence | VERIFIED | HEAD `218308c3`; no working-plan diff; inline methods equal `dpatch9.py`. |
| Both stock player identities | VERIFIED | Full hashes match `SUPPORTED_PLAYERS`. |
| Player differences and displaced offsets | VERIFIED | Removing the two PDF.js insertions reproduces the older player; total difference 38 bytes. |
| All 13 anchor counts, offsets and interval disjointness | VERIFIED | Recomputed on both players; each count is one and intervals are disjoint. |
| Replacement containment, including self | VERIFIED | Empty containment set, including the hook. |
| R1–R5 / R6–R8 / D1–D4 composition | VERIFIED | All six group orders produce identical bytes on both players. |
| Anchor consumption and replacement uniqueness | VERIFIED | Original rendering anchors absent; replacements occur once. |
| Complete patched JavaScript | VERIFIED | Rendering/on/off outputs pass stdin `node --check`, both players. |
| D1 replacement size | VERIFIED | 7,502 bytes. |
| Off identity and existing pins | VERIFIED | Hook-only outputs retain both pinned off hashes. |
| CSS routing, flattened topology and hidden-to-opacity behavior | VERIFIED | Primary `jC`, `PB`, `NB`, `WB` code supports the stated mechanism. |
| Render/animate separation and D4 placement | VERIFIED | D4 precedes `displayScene`; normal transition rendering precedes the animation timer. |
| Export census | VERIFIED | Recomputed 25 roots: 42 Dissolves, 8 cuts, 67 Magic Moves, 382 builds. |
| Shape predicate, copied kind and source immutability | VERIFIED | Real-class rerun: 46 Dissolves, 8 cuts, 79 stock; zero mutations. |
| Predicted IDs and construction failure behavior | VERIFIED | Allocated IDs match rules; all five failure cases return stock without targeting constructed nodes. |
| Dissolve/cut near-misses | VERIFIED | All 21 Dissolve and 10 cut near-misses remain stock. |
| Additive cross-fade arithmetic | VERIFIED | Correct under the stated geometry and coverage assumptions. |
| Cut’s complementary 1-ms contract | VERIFIED | Implementation and revised gate agree; fractional `(0.5,0.5)` is allowed. |
| D3 attachment target and failure handling | VERIFIED | Cut leaf, Dissolve wrapper, missing-wrapper discard and throwing-append rows reproduce. |
| Add-only video behavior | VERIFIED | No playback changes/reparenting; all 72 proxy rows record zero touches. |
| Existing 72-row F3 table | VERIFIED | Reproduces on both players. |
| Independent X/Y geometry and opacity inspection | VERIFIED | Aspect-changing fill skips; lower-source transparency skips; accepted fill placement is correct. |
| Plain-bitmap and chain whitelist completeness | FINDING #1 | Paint containment and canvas view-box cropping remain admitted. |
| Paint-order proof | FINDING #4 | Reordered flex painting is not excluded. |
| Ancestor-decoration departure | VERIFIED | Allowing a background behind an opaque movie is coherent; black-body deck stubs remain admitted. A blanket ancestor-decoration ban is unnecessary. |
| Later admitted movie overlapping an earlier movie | VERIFIED | Last-first admission and reversed holder order reproduce both holders in the supported stub cases. |
| Canvas foreground alpha/redraw order | VERIFIED | Existing α=1/0.2947/0.5 rows reproduce; redraw follows tone mapping. |
| P2/DSK stub engagement | VERIFIED | All six listed movie slides admit their movies; P2 square and DSK foreground redraws reproduce. |
| Actual P2/DSK DOM engagement | NOT VERIFIABLE STATICALLY | Real computed-style verdicts and pixels: Q0b 2/6. Stubs do not prove browser engagement. |
| Host scaling, letterboxing and DSF 2 pixels | NOT VERIFIABLE STATICALLY | Full-resolution holder residual: Q0b 5. |
| LUT formula and numerical claims | VERIFIED | Recomputed 128→139.1595; maximum +11.3268 at 113; minimum −4.3243 at 9; endpoints fixed after quantization. Chromium documents the gamma-1.961 path. [Chromium colour-space source](https://chromium.googlesource.com/chromium/src/+/d89195f6038607cdf1dd3f7d1b95ff438a76fc68/ui/gfx/color_space.h) |
| LUT ordering relative to alpha/redraw | VERIFIED | Source alpha checked before its RGB is mapped; no mapped pixels are committed after an alpha failure; foreground redraw occurs afterward. |
| Browser colour-space admission | FINDING #2 | Transfer alone does not constrain the complete qualified colour profile. |
| Analytic-versus-measured LUT decision | FINDING #5 | Construction, repeatability tolerance and unavailable-codec outcome need definition. |
| Identity fallback and tone controls | FINDING #3 | Current PASS/FAIL and owner-gate requirements contradict fallback. |
| Actual tone continuity and content/path stability | NOT VERIFIABLE STATICALLY | Q0b 1 and DX-2: ramp/patch captures, encoding comparisons and two CEF launches. |
| Independent foreground reference | VERIFIED | `S_live` precedes D4 and does not derive from the candidate holder. |
| Foreground preservation pixels and negative sensitivity | NOT VERIFIABLE STATICALLY | `m-fg`/`m-fg-omit`, shifted/double-painted scorer cases: Q0b 3, DX-1, DX-2. |
| Total-D4 measurement coverage | VERIFIED | Timer encloses rejected candidates, scans, snapshots, readbacks, LUT and redraw work; `finally` publishes it. |
| Cost-instrument controls | FINDING #6 | No designated boundary/integrity controls. |
| Actual time and memory footprint | NOT VERIFIABLE STATICALLY | Q0b 4 measures aggregate time; natural-size canvas memory arithmetic is correct, actual allocations need measurement. |
| Main terminal bridge residual | VERIFIED | `keepAtSlot`/`slotLive` retain independent full-strength paint; Q6 follow-up ownership is explicit. |
| Main bridge’s terminal pixels | NOT VERIFIABLE STATICALLY | Q0b 5 and `m-bridge(-off)` in DX-1/DX-2. |
| S2 hold and follow-up scope | VERIFIED | Git-ref source retains the hold; rev 6 assigns retirement to a separate post-S2 PR. |
| Historical cut rAF observations | VERIFIED | Retained JSON reproduces stock 2/27 and patched 0/44 both-visible samples. |
| Historical pixel maxima, screencast union and freeze/tone images | NOT VERIFIABLE STATICALLY | Required planner PNGs are absent from retained runs; current-byte repetitions are scheduled in Q0b/DX-1/DX-2. |
| Browser/CEF availability claims | VERIFIED | Installed OBS is 32.2.2 with CEF 127; API availability does not establish compositor correctness. |
| Decoder binding and demixing algebra | VERIFIED | Unique-region binding, independent progress fitting and `(F−eB)/(1−e)` address incoming overlap. |
| Exact frozen-index agreement and demixing noise | NOT VERIFIABLE STATICALLY | Bound rVFC/holder/screenshot captures: Q0b 6 and DX-M in both browsers. |
| Shared capture integrity and expected-FAIL semantics | VERIFIED | Explicit scene/digest/texture/dimension/sample requirements; INCONCLUSIVE cannot satisfy FAIL. Tone branching needs finding #3. |
| `m-off` evidence contract | VERIFIED | Intentional holder absence is distinguished from missing candidate evidence. |
| Texture, flash, curve, monotone and hand-off controls | VERIFIED | Written controls and synthetic cases are retained; execution remains in DX-1/DX-2. |
| CEF cut/media/independent-overlay controls | VERIFIED | Required sessions include `m-bridge-off`; candidate bridge remains report-only. |
| CEF calibration formulas | VERIFIED | Unclamped formulas and caps imply rejection at `n>4`; boundary test is assigned. |
| Lifecycle scenario coverage | VERIFIED | Advance/replay/queue/skip/go-to/back/hide/show/automatic/wrap/terminal rows are present. |
| Lifecycle behavior and cleanup in browser | NOT VERIFIABLE STATICALLY | Q0b dry run and DX-1 lifecycle scenario. |
| Production transparency and owner-visible result | NOT VERIFIABLE STATICALLY | DX-3 pre-check and candidate/null observation; fallback wording needs finding #3. |
| Switch, runtime version, preview and stock oracle separation | VERIFIED | Existing code supports the stated integration; on/rendering repins are explicitly assigned. |
| Regression coverage | VERIFIED | Full gates, opacity/hand-back probes and managed `mmo`, `g2`, `mmo-cef` are scheduled. |
| Work-stream disjointness | VERIFIED | W0 touches stripper/test; W1–W4 have separate file ownership; W3 follows W2. |
| Minimal-tests rule | VERIFIED | Three new functions, existing tests extended, shared parametrized tables; findings can fit those tables. |
| Final owner decisions and exclusions | VERIFIED | Decisions 1–7 remain recorded; no video adoption or premature S2-core work is introduced. |

**Verdict: needs another planning pass.**