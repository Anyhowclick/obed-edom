# Plan critique r3 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 4 `4ffcd8ad`. Prompt: `plan-astra-r3.prompt.md`.

**Part A — Round-2 disposition**

References `P:line` refer to the [rev-4 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md). Player offsets below are bytes in e9b2fad4 unless both versions are listed.

| r2 # | Status | Evidence | Remaining fix wording |
|---|---|---|---|
| r2-1 | closed | D1/D2 now commit before construction. Re-executed both players’ real classes: all five construction failures return stock trees; abandoned rules target no allocated node. D3 does not change that cross-fade failure model. | Preserve commit-before-construct. Fix D3’s separate unsafe fallback in finding #7. |
| r2-2 | partly closed | P:332–337 restores scene, texture, dimensions, page-mode, digest and sampling integrity. The new `m-off` arm contradicts the mandatory-holder requirement. | Apply finding #3. |
| r2-3 | partly closed | Normal attachment now uses the outgoing opacity wrapper. The media oracle is separate, but its screenshot decoding is invalid during overlap; independent live overlays remain possible on main. | Apply findings #1–3 and #7. |
| r2-4 | closed | P:375–385 now explicitly covers queued skip, hide/show, actual automatic delay, terminal retention and subsequent cleanup. | The missing-row problem is closed; fix the newly exposed terminal-media behavior in finding #1. |
| r2-5 | closed | P:302,347,425–429 specifies the hand-off statistic, endpoint integrity, unchanged positive and injected-step negative. | None for the original finding. |
| r2-6 | closed | P:391–393 uses unclamped formulas and correctly rejects `n > 4`; boundary cases remain in test 5. | None. |
| r2-7 | closed | P:35–36,277–282 corrects P2 to 1.3 LSB. `analyze_full.py` uses full-resolution slices and maxima. | Preserve full-resolution scoring. Historical pixel maxima cannot be independently recomputed from the retained JSON alone. |

**Part B — New findings**

1. **Severity: major. Class: new class. §§3.2, 6.2, 9.1, 11–12 — Main’s continuity core can leave a full-strength movie over the frozen fade.**

   **Claim:** Main needs no change because nothing it paints remains visible during a dissolve.

   **Evidence:** That evidence establishes P2 **2→3**, not every qualifying transition. Main’s [`keepAtSlot`](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_continuity_js.py:1056) continues while the hash is at or beyond the slide-4 boundary, the decoder has not ended, and its generation remains live. It repeatedly sets `visibility:visible`, `display:block`, and `opacity:1`. [`slotLive`](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_continuity_js.py:1007) has no outgoing-transition condition.

   P2 slide 4 ends with a Dissolve. Its bridged decoder lives outside the player’s replaced slide DOM. D4 can snapshot it, but D3 neither removes nor fades the original. Executing the extracted `keepAtSlot` with a live decoder at hashes 9, 10 and 11 retained opacity 1 and scheduled another frame each time. This is a static counterexample to the claimed ownership guarantee; the exact terminal pixels still need the lifecycle run.

   DX-M only qualifies 2→3. The terminal lifecycle row compares against the stock twin, which can preserve this existing overlay defect.

   **Exact fix wording:** “Qualify outgoing media after both restart and bridge/pin ownership. Main’s bridge overlay must stop painting when its outgoing Dissolve/cut begins, while the captured holder owns the fade. Add the P2 slide-4 terminal transition to DX-M with a no-independent-live-overlay assertion. Assign any required main-core implementation and tests explicitly; remove the unconditional ‘no change to main’ claim.”

2. **Severity: major. Class: new class. §9.1 — The frozen-counter oracle rejects correct overlapping fades and lacks per-decoder binding.**

   **Claim:** Straight screenshot RGB remains constant while the movie’s alpha fades, so every screenshot can decode the frozen counter directly.

   **Evidence:** P:330–331,349–350. That is true only where the incoming contribution is zero. With incoming content,

   `F = (1−e)S + eB`.

   For an opaque black counter bit over an opaque white incoming pixel, a correct fade at `e=.75` produces RGB 191 and alpha 255. Direct threshold decoding changes the bit even though `S` is perfectly frozen. The region-alpha cutoff does not help: overlap alpha can remain 255 through the entire transition. The retained incoming P2 texture also contains content overlapping the recorded movie region.

   The prototype’s `f3analyze.py:45–50` selects the latest rVFC record across **all** videos. An in-memory two-video example selected frame 240 for movie A whose own last frame was 30. The current take happens to have only one populated relevant callback log.

   Finally, `f3model2.py:15–20` uses a screenshot as outgoing reference `A3`; reconstructed texture-plus-holder `A2` receives only median/p99 geometry diagnostics. Its 1.7-LSB result therefore does not establish the planned independent reconstruction’s maximum error.

   **Exact fix wording:** “Bind each holder to its source decoder identity and capture instant, and compare against that decoder’s last pre-freeze rVFC record. Decode transition screenshots from the premultiplied outgoing estimate `(F−eB)/(1−e)`, with a bounded outgoing weight and sufficient time-separated samples; alternatively prove the entire counter strip is incoming-transparent. Determine e independently of the media region. In Q0b, score the reconstructed texture-plus-holder reference at full resolution, including geometry maxima. Add overlapping incoming content and two simultaneous decoder records to the existing parametrized scorer test.”

3. **Severity: major. Class: closed class. §§9.1, 10.4 — `m-off` can only be INCONCLUSIVE under the written integrity contract.**

   **Claim:** `m-off` must FAIL frozen-frame checking because it shows the baked poster and has no index.

   **Evidence:** P:336 requires every media arm to have “a decodable holder”; P:368 deliberately supplies none. P:429 also classifies an undecodable holder as INCONCLUSIVE. Consequently the designated negative cannot satisfy its expected FAIL under the owner’s integrity rule.

   **Exact fix wording:** “Give media controls explicit per-arm evidence requirements. For `m-off`, require verified off bytes, successful live playback before the transition, the identified transition and outgoing texture, and captured movie-region pixels; a holder is intentionally absent. Define the behavioral failure from that complete evidence. Unexpected missing/undecodable holder evidence in `m-on` or `m-paused` remains INCONCLUSIVE. Add these distinctions to the existing scorer case table.”

4. **Severity: major. Class: new class. §§2, 3.2 — Visibility does not establish that placing a whole movie rectangle above the flattened texture preserves the slide.**

   **Claim:** Every qualifying video is fully visible, and its opaque holder covers exactly the region occupied by the movie in the baked texture.

   **Evidence:** P:136 and164–186 do not inspect occlusion or stacking. `checkVisibility` checks box existence and selected CSS visibility properties; it does not establish that other content is not covering the video. This follows directly from the [CSSOM View algorithm](https://drafts.csswg.org/cssom-view/#dom-element-checkvisibility).

   A movie beneath a foreground label or picture passes the predicate. Appending its complete rectangle after the flattened outgoing texture paints over that foreground content. Multiple holders follow document order, which is not necessarily their painted stacking order.

   **Exact fix wording:** “Admit a frozen region only when its visible coverage and stacking relative to the outgoing slide are established. Preserve foreground occlusion and overlapping-movie order, or conservatively skip unsupported compositions and document the residual. Add an opaque foreground-over-movie case and an overlapping-movies case to the existing behavioral table and Q0b visual checks.”

5. **Severity: major. Class: edge case. §3.2 — The geometry predicate admits transforms and clipping that the reconstruction does not reproduce.**

   **Claim:** Axis-aligned 2D transforms plus `contain`/`fill` provide exact visible-region geometry.

   **Evidence:** P:136 rejects only non-2D matrices and nonzero `b`/`c`. It accepts reflection and unequal X/Y scaling. The snapshot is subsequently drawn unreflected, and `contain` is recalculated from the transformed bounding rectangle rather than the local content box. Nonuniform scaling therefore changes the reconstructed letterboxing.

   The method also assumes centered `object-position`, uses the border rectangle as the content box, ignores `clip-path`/masks, and approximates all non-visible overflow as a rectangular clip on both axes. In-memory execution of the unchanged methods accepted reflected video, noncentral object positioning and a circular clipping ancestor.

   The base-layer-origin subtraction itself is correct for the intended uniformly scaled slide: letterboxing, a 2560×1440 origin at `(0,0)`, and DSF changes do not inherently break that mapping.

   **Exact fix wording:** “Restrict admitted media to geometry the snapshot reproduces: positive uniform transforms, the supported object-position and box model, and verified rectangular clipping; otherwise preserve the corresponding transform/content/clipping operation explicitly. Reject unsupported masks, reflections and nonuniform transforms. Add translated/letterboxed, 2560×1440, DSF≠1, reflected and nonuniform-scale rows to the existing geometry cases; schedule representative host-path checks in Q0b.”

6. **Severity: major. Class: edge case. §3.2 — The 32×18 probe cannot prove that the retained full-resolution canvas is opaque.**

   **Claim:** A movie with any transparency is skipped, guaranteeing no frozen-over-baked double image.

   **Evidence:** P:136 draws the full-resolution frame into `x`, downsamples it into a separate 32×18 canvas, and inspects only the latter. Sparse or sufficiently small transparent regions can disappear through downsampling or 8-bit rounding. The canvas eventually attached is still the original `x`.

   Thus the stated “any transparency” and “never a double image” guarantees do not follow from this probe.

   **Exact fix wording:** “Verify opacity over every source pixel contributing to the attached region, or use another conservative proof that cannot lose transparency through downsampling. Otherwise skip the movie. Add sparse transparency between probe samples and a small transparent edge feature to the existing alpha cases, and measure the stronger check’s capture cost in Q0b.”

7. **Severity: major. Class: closed class. §§3.1–3.2, 8 — D3 falls back to an unfaded Dissolve parent when its required wrapper is missing.**

   **Claim:** Every attachment failure leaves the baked frame; the layer fallback is for cuts.

   **Evidence:** P:137 unconditionally evaluates:

   `getElementById("layer"+id+"-opacity") || getElementById("layer"+id)`.

   On a Dissolve with a missing wrapper, it appends the holder to the blend leaf. That leaf has opacity 1; the missing child is where the fade belongs. The result can be a full-strength holder, exactly the attachment distinction identified in r2-3.

   The supplied `cutTargetsLayer` stub case merely removes the wrapper; its effect remains a Dissolve. Re-executing it confirms that this incorrect Dissolve fallback attaches one holder.

   **Exact fix wording:** “Select the attachment point by the engaged transition kind. Dissolve requires its outgoing opacity wrapper; if absent, discard the holders. Only an engaged `none` cut may attach directly to the outgoing layer. Make the cut test construct an actual cut, and add missing-Dissolve-wrapper and append-failure rows.”

8. **Severity: major. Class: closed class. §9.2 — CEF does not run the controls required to qualify the newly added behavior.**

   **Claim:** DX-2 qualifies the cut and drawImage path using §9’s blocking control contract.

   **Evidence:** P:389–394 schedules neither `cut-off`/`cut-on` nor `m-paused`/`m-hold`. Therefore CEF has no cut qualification and lacks the designated known-frame positive and full-strength-hold negative. `m-off` additionally has finding #3’s integrity contradiction.

   A candidate `m-on` capture alone does not demonstrate that CEF’s media instrumentation detects a wrong frame or an unfaded holder.

   **Exact fix wording:** “Add `cut-off`, `cut-on`, `m-paused` and `m-hold` to DX-2, reusing W2’s driver/scorer. Require an actual D4 holder capture in each applicable media session and record the active continuity/G2 state. Run the cut with its per-frame evidence contract. Establish all relevant control outcomes before accepting the CEF candidate.”

9. **Severity: minor. Class: edge case. §§2, 3.2 — A mirrored `hidden` animation is not intrinsically a discrete cut.**

   **Claim:** Only the first frame shows outgoing; every later frame shows incoming, with no partly visible pair.

   **Evidence:** `WB.createAnimationRuleForKeyframe` around @2283770 converts `hidden` values into **opacity** keyframes. Real-class execution after changing an otherwise accepted cut duration to 100 ms produced linear `0→1` and `1→0` opacity animations. D1 accepted it. It also accepted `fillMode:"removed"`.

   The eight stock cuts use 1 ms and `both`, so ordinary display cadence explains the observed endpoint-only samples. The predicate does not enforce those preconditions, however, and the arithmetic is continuous rather than discrete. `applyCssAnimation` also sets incoming visibility before animation playback; it does not wait until 100% to change visibility.

   **Exact fix wording:** “State the actual opacity-keyframe behavior. Either restrict cuts to the verified timing/fill shape and limit the guarantee accordingly, or make both sides explicitly discrete. Reject unsupported fill/timing cases and add them to the existing near-miss table.”

10. **Severity: minor. Class: new class. §§9.1–9.3, 12.5 — Owner question 5 is design-changing, but its cost and acceptance wording is inconsistent.**

   **Claim:** Accepting the snapshot’s tone step requires no change to either continuity core; moving/pausing the live video guarantees no step.

   **Evidence:** P:243 already requires an S2 core change even for snapshots; finding #1 exposes a main integration requirement. Avoiding decoder adoption remains a real simplification, but “no core change” is inaccurate.

   The live-video alternative avoids this particular drawImage conversion, but its resulting composited tone has not been measured. “No step” is currently a prediction. P:351 makes tone report-only pending the answer, P:393 refers to a subsequent Q0b bound, while P:405 independently requires no noticeable brightness step.

   **Exact fix wording:** “Recommend snapshotting because it avoids adopting decoder ownership, while listing the independent main/S2 outgoing-overlay changes required either way. Describe live-element tone continuity as an alternative to measure, not a guarantee. State exactly how answer 5(a) changes acceptance: which numerical tone checks remain report-only and whether DX-3 may still reject a noticeable accepted-limit step. Answer 5(b) triggers a revised implementation and gate scope before work begins.”

11. **Severity: nit. Class: edge case. §0 — The player-difference summary omits D4.**

   **Evidence:** P:9 says only R8 and `_ANCHOR` move. Rechecked D4 offsets are **2353722 / 2353760**, also differing by 38 bytes, as the later tables correctly state.

   **Exact fix wording:** “Only R8, D4 and the observation hook move among the listed replacement anchors.”

**Part C — Closing inventory**

“VERIFIED” denotes a checked static property or reproducible retained record, not a qualification run. Historical screenshots and frozen-frame PNGs are not retained at the supplied scratch location, so their pixel statistics could not be recomputed.

| Claim class / item | Status | Evidence or measurement that settles it; scheduling |
|---|---|---|
| Player identities | VERIFIED | Both complete SHA-256 values match the named supported players. |
| Anchor counts and offsets, R1–R8/D1–D4/hook | VERIFIED | All 13 anchors occur once in each player; listed offsets and lengths reproduced. |
| Opening offset-difference summary | FINDING #11 | D4 also moves by 38 bytes. |
| Interval disjointness; containment including self | VERIFIED | All intervals disjoint; containment set empty. |
| Six R1–R5 / R6–R8 / D1–D4 application orders | VERIFIED | All six produce identical bytes for each player. |
| Anchor consumption / replacement occurrence | VERIFIED | Original anchors absent; replacements occur once. |
| Complete patched JavaScript | VERIFIED | Rendering, on and off outputs for both players pass stdin `node --check`; no player files written. |
| D4 scope and method receiver | VERIFIED | `PB`, `UC`, `TB` share scope; `PB.prototype.__obedFreezeTake(U,A)` binds `this` to `PB.prototype`, where `__obedShape` exists. Strict methods are valid here. |
| D4 `B` guard | VERIFIED | Matches `jumpToScene_partFour`’s play branch. Self-playing mode adds a deferred play, correctly listed as a host-refused residual. |
| D1 shape/copy and source immutability | VERIFIED | Real-class rerun: 46 Dissolves, 8 cuts copied; 79 transitions unchanged; zero export mutations. |
| D1 five construction failures | VERIFIED | All build stock; no surviving rule targets built IDs. |
| D1 21 existing near-misses | VERIFIED | All rejected on both players. |
| D2 pre-order allocation and rule targets | VERIFIED | Real `VB` allocates predicted IDs; no mismatch across qualifying Dissolves. |
| D3 normal Dissolve/cut target | VERIFIED | Wrapper is correct for opacity; leaf is correct for hidden animation. |
| D3 missing-wrapper failure | FINDING #7 | Dissolve incorrectly attaches to the unfaded leaf. |
| D3 slot consumption and ordinary append exceptions | VERIFIED | Slot cleared before attachment; exceptions cannot alter committed cross-fade rules. Missing-wrapper behavior remains finding #7. |
| D4 decoder readiness and ordinary exception handling | VERIFIED | Existing stub cases reject undecodable, invisible, unsupported-fit and throwing-draw cases. |
| D4 “never modifies the video” | VERIFIED | Code inspection and proxy cases find no video writes, pause/play calls or reparenting. |
| Effective-opacity check | VERIFIED | Multiplies ancestor opacities, including the video; rejects translucent ancestors within the traversed chain. |
| Full visibility / occlusion / holder ordering | FINDING #4 | CSS visibility is insufficient to establish painted coverage. |
| Geometry under uniform stage scale and translated origin | VERIFIED | Base-layer subtraction and scale conversion are mathematically correct; coordinates are CSS pixels. |
| Letterboxed, 2560×1440 and DSF≠1 product captures | NOT VERIFIABLE STATICALLY | Need host-path captures. DX-1 currently fixes 1920×1080/DSF1; finding #5 adds explicit coverage. |
| Nonuniform/reflected transforms, object position and complex clips | FINDING #5 | Admitted but not reproduced. |
| Opaque-frame proof | FINDING #6 | Reduced probe does not prove full-resolution opacity. |
| Snapshot memory / attached cleanup | VERIFIED | Natural-size RGBA canvas is approximately 4 MB at 1920×540; attached holder follows transition DOM lifetime. |
| Unattached snapshot lifetime | VERIFIED | Bounded slot survives until D3 consumption or another take; it is not necessarily freed by the next unplayed navigation. |
| Stock source-over / plain-fade dip / additive formula | VERIFIED | Algebra agrees with [Compositing Level 2](https://drafts.csswg.org/compositing-2/#porterduffcompositingoperators_plus_lighter). |
| Frozen-movie formula | VERIFIED | Correct conditional on opaque, correctly positioned and correctly occluded `P_out′`; those premises have findings #4–6. |
| Cut keyframes, interpolation and fill assumptions | FINDING #9 | Actual keyframes are opacity interpolation; predicate accepts unsupported timing/fill. |
| Render→animate gap | VERIFIED | Construction and animation are separate tasks; copied initial incoming state covers the ordinary gap. |
| `p2cut` stimulus validity | VERIFIED | In-memory override changes effect name/duration and outgoing animation to the exported cut form while preserving two content textures. Suitable synthetic stimulus, not evidence of an affected on-disk cut. |
| Cut retained rAF counts | VERIFIED | Recomputed stock 2/27 union samples; patched 0/44. |
| Cut screencast counts | NOT VERIFIABLE STATICALLY | Frame images absent; fresh repeats scheduled in Q0b/DX-1. CEF coverage missing: finding #8. |
| Chrome `plus-lighter` availability | VERIFIED | [Chrome 100 release account](https://web.dev/blog/web-platform-03-2022). |
| `checkVisibility` option availability | VERIFIED | Chromium’s [feature record](https://groups.google.com/a/chromium.org/g/blink-dev/c/qpkOIzNakcI) identifies these aliases for Chrome 121; compatible with installed CEF127. |
| Installed versions | VERIFIED | Plists report Chrome154.0.8037.59, OBS32.2.2 and CEF127. |
| CEF compositing and drawImage output | NOT VERIFIABLE STATICALLY | DX-2 scheduled, but complete controls require finding #8. |
| Switch precedence / every-output routing | VERIFIED | Existing constructor→environment→auto behavior applies to the extended tuple. |
| Off-byte identity | VERIFIED | Rebuilt off hashes remain `7cf00b56…` / `4f9fbffd…`. |
| On/rendering pins and report shape | VERIFIED | Two new output digests per player are required; three-pin shape and `{mode,sha256}` need no redesign. |
| Runtime version / preview / stock oracle | VERIFIED | Version2 remains viable; preview uses rendering patch; paint oracle stays stock. |
| Scope: 42 Dissolves | VERIFIED | Independent census reproduced count and qualifying shape. |
| Scope: 8 cuts | VERIFIED | All terminate their decks and share incoming texture `9B0DBE…`; affected-content stimulus is synthetic. |
| Scope: outgoing movies | FINDING #1 | “Every qualifying start” exceeds demonstrated main-core ownership handling. |
| Scope: 382 per-object builds | VERIFIED | 167 movie-start +167 renderMovie +48 character Dissolves. |
| Scope: 67 GL transitions | VERIFIED | Census and renderer routing agree; D1 shape excludes these. |
| Scope: F2 transitions | NOT VERIFIABLE STATICALLY | Owner-authored Q-deck remains a separate follow-up; appropriately outside this patch. |
| Interplay: R1–R8 | VERIFIED | Byte composition and order independence checked. |
| Interplay: G2 | VERIFIED | D4 samples visible videos, not G2’s canvas; stated residual is real. Resulting regression behavior remains scheduled in §9.4. |
| Interplay: main continuity | FINDING #1 | Bridge-held outgoing movies invalidate the unconditional no-change claim. |
| Interplay: S2 at d88584eb | VERIFIED | Git-ref source confirms full-strength held restart decoder and delayed retirement. Ending painting at transition start is necessary; fresh-decoder restart behavior must remain intact. |
| Interplay: `managed_obs_qualify` | VERIFIED | `make_export:299` copies `html-player`; `mo3_script:611` uses `mm_opacity_probe.drive`. Shared corrected resolver is justified. |
| Interplay: opacity/hand-back probes | NOT VERIFIABLE STATICALLY | Scheduled reruns cross 2→3; unchanged GL results cannot be inferred from disjoint bytes alone. |
| Interplay: P2 `deliberateRestart2to3` | VERIFIED | Restart identity/rVFC and composited-counter progression are checked after reaching slide3. Frozen outgoing pixels need not inherently violate that contract. |
| Interplay: bridge-off timing | NOT VERIFIABLE STATICALLY | Previous R8 evidence demonstrates sensitivity to synchronous work and delayed observations. Full-tier rerun is scheduled; no automatic threshold relaxation is justified. |
| Interplay: `run_gates.sh` | VERIFIED | No player-output SHA pin; exact registered red/inconclusive sets remain enforced. Any changed set requires diagnosis before editing expectations. |
| Historical cross-fade, opaque comparison and tone numbers | NOT VERIFIABLE STATICALLY | Retained scripts/JSON inspected; pixel images absent. Q0b schedules fresh controls. |
| Historical freeze identity | VERIFIED | Retained callback record before take has mediaTime1.866667, frame56; the corresponding snapshot PNG is absent, so snapshot equality itself awaits rerun. |
| Historical 1.7-LSB media-model claim | FINDING #2 | Screenshot-reference fit does not prove independent reconstructed-reference maximum. |
| Common capture integrity | FINDING #3 | Static/fade requirements restored; media null requirements conflict. |
| `on`: P2 and DSK | NOT VERIFIABLE STATICALLY | Current-byte Q0b/DX-1 scheduled; media-region qualifications need findings #2–6. |
| `on`: D2 | NOT VERIFIABLE STATICALLY | Overlap-only contract is coherent; Q0b/DX-1 scheduled. |
| `on2`: CvC | NOT VERIFIABLE STATICALLY | Q0b/DX-1 scheduled. |
| `off` | NOT VERIFIABLE STATICALLY | Fresh expected model/complement failures scheduled; retained historical pixels absent. |
| `noblend` | NOT VERIFIABLE STATICALLY | No-dip negative and complement positive scheduled in DX-1/DX-2. |
| `opaque-off`, `opaque-on` | NOT VERIFIABLE STATICALLY | Control and matched-progress measurements scheduled; formula is sound. |
| `screen-off`, `screen-on` | NOT VERIFIABLE STATICALLY | Real host screen-path tests scheduled in Q0b/DX-1. |
| `delay-off`, `delay-on` | NOT VERIFIABLE STATICALLY | Counted delay splice is valid; capture/control outcomes scheduled in Q0b/DX-1. |
| `cut-off`, `cut-on` | FINDING #8 | Headless repeats scheduled; CEF arms absent. Timing guarantee also needs finding #9. |
| `m-on` | FINDING #2 | Raw screenshot decoder is not overlap-safe; 2→3 alone misses finding #1. |
| `m-paused` | FINDING #8 | Valid known-frame control in principle; not included in CEF. |
| `m-off` | FINDING #3 | Intended absence of holder currently invalidates the arm. |
| `m-hold` | FINDING #8 | Useful full-strength negative, but absent in CEF; evaluate outgoing contribution rather than alpha255 alone. |
| `on-sw` | NOT VERIFIABLE STATICALLY | Current-byte Q0b/DX-1 scheduled. |
| Model/complement/no-dip/curve/monotone/no-flash instruments | NOT VERIFIABLE STATICALLY | Controls and synthetic cases specified; actual product results require scheduled runs. |
| Hand-off statistic and controls | VERIFIED | Explicit endpoint statistic, missing-frame disposition and positive/negative cases now specified. |
| Frozen-index / frozen-region statistics | FINDING #2 | Require demixing, decoder binding and non-vacuous sampling. |
| Tone acceptance | FINDING #10 | Pending owner decision does not yet map consistently to DX-2/DX-3 acceptance. |
| CEF calibration | VERIFIED | At n4: τ5, complement6, no-dip248; any n>4 violates a cap. |
| Production transparency and codec behavior | NOT VERIFIABLE STATICALLY | DX-3 explicitly prechecks affected production export and a playable movie. |
| Lifecycle: advance / completion | NOT VERIFIABLE STATICALLY | Same-task D4→D3 sequence checked; product pixels/cleanup scheduled in DX-1. |
| Lifecycle: replay | NOT VERIFIABLE STATICALLY | Fresh take and IDs follow code; scheduled scenario must demonstrate them. |
| Lifecycle: queued advance / queued skip | NOT VERIFIABLE STATICALLY | Both native paths exist and are now scheduled. Ordinary keys cannot interleave within the synchronous take→attach task. |
| Lifecycle: go-to / back | NOT VERIFIABLE STATICALLY | Uses `jumpToScene`, normally with Bfalse; does not take a new freeze. Cleanup/arrival scenario scheduled. |
| Lifecycle: initial display | VERIFIED | Same controller path; missing previous base layer is caught and produces no snapshot. |
| Lifecycle: hyperlink transition | VERIFIED | The other direct `displayScene` call bypasses D4; explicitly documented residual. |
| Lifecycle: hide/show | NOT VERIFIABLE STATICALLY | Alpha host uses ancestor opacity; screen host uses black overlay. Mid-fade hide/show scheduled. |
| Lifecycle: automatic delay | NOT VERIFIABLE STATICALLY | Real automatic branch is now scheduled; holder is attached before animation delay. |
| Lifecycle: loop wrap | FINDING #1 | Frozen copy does not itself terminate a main bridge overlay. |
| Lifecycle: end-of-show | FINDING #1 | Stock-twin endpoint equality can accept an independently held movie; require explicit media behavior. |
| Test1: existing refusal/identity/syntax cases | VERIFIED | Tuple-derived machinery supports extension without new test families. |
| Test2: pins/composition/hand-back slice | VERIFIED | Explicit slice avoids accidentally treating D2–D4 as hand-back replacements. |
| Test3: real classes and freeze cases | FINDING #7 | Existing cases rerun; “cut” fallback case is actually a Dissolve. Add findings #4–6/#9 to the same table. |
| Test4: scorer cases | FINDING #2 | Extend the single table with overlap, decoder identity and corrected null semantics. |
| Test5: CEF env refusal/calibration | VERIFIED | Minimal extension and one calibration function are coherent. |
| Three-new-test-function count | VERIFIED | Proposed structure remains three new functions; additional cases can remain parametrized. |
| W0 | VERIFIED | Cherry-pick changes only stripper and its test; disjoint from W1–W4. |
| W1 | FINDING #1 | Assigned runtime/test files cannot implement a required main-core retirement change. Assign ownership explicitly. |
| W2 | VERIFIED | Resolver, driver and pure scorer belong together; fixes above fit its assigned files. |
| W3 | FINDING #8 | Can add missing CEF sessions within its own files, using W2’s shared interface. |
| W4 | VERIFIED | Documentation and S2 handover are disjoint; cannot substitute for main-core implementation. |
| Stream ordering / regressions | NOT VERIFIABLE STATICALLY | Parallel W1/W2 then W3 is coherent; full-tier outcomes may reveal additional owned-file work. |
| Owner decision1: folded switch | VERIFIED | Implementable with existing API/pin shape. |
| Owner decision2: every output | VERIFIED | Routing supports it; qualification gaps remain findings #5/#8. |
| Owner decision3: F1 now / F2 later | VERIFIED | Rev4 reflects the supplied decision. |
| Owner decision4: F3 now | FINDING #1 | Intended scope requires resolving outgoing-overlay ownership within this patch. |
| Owner question5: architectural choice | FINDING #10 | Design-changing and worth asking, with corrected costs and acceptance consequences. |

**Verdict: needs another planning pass.**