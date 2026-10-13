# Plan critique r2 — GPT-6 Astra (high), Codex `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only`, 2026-10-11

Raw output, kept while the plan is in review. Rev reviewed: rev 2 \`cd289a05\`. Prompt: `plan-astra-r2.prompt.md`.

**Part A — Round-1 disposition**

References below use the [rev-2 plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md). Player byte offsets are shared unless two offsets are given.

| r1 # | status | evidence | remaining fix wording |
|---|---|---|---|
| 1 | partly closed | CSS preflight, rejected-style readback, and ordinary rollback cases work. `NB.animateEffect` @2302687 skips the mirror after `cssAnimationRules=[]`. Missing DOM is not reconstructed; throwing setters can interrupt rollback. | Apply finding #1. |
| 2 | closed | Independently rebuilt both players in memory. D1 consumes its anchor; containment including self is empty; all six group orders agree; both outputs pass `node --check`. | None. |
| 3 | partly closed | S2 behavior confirmed through `origin/claude/s2-detach-fix` only. The limitation and owner decision are now explicit, but the proposed attachment point does not inherit the fade, and the unmasked oracle remains texture-only. | Apply finding #3. |
| 4 | closed | §9.1 now exempts opaque/D2 arms appropriately and identifies derived digests for `noblend` and delay variants. | Preserve these corrections while restoring the separate integrity requirements in finding #2. |
| 5 | partly closed | CEF now has stock, `noblend`, and opaque controls, plus fixed calibration formulas. The stated rejection boundary conflicts with the combined caps. | Apply finding #6. |
| 6 | partly closed | Effective-opacity instrumentation, delay controls, and scorer negatives are specified. Hide/show and queued skip are absent from the actual lifecycle scenario; the automatic branch is substituted rather than exercised. | Apply finding #4. |
| 7 | closed | Real screen-path arms are specified. Re-running `matched.py` reproduced eight comparisons, maximum **1.51 LSB**, p99.9 **1.22**. The one-LSB claim was withdrawn. | None for the original finding; separate measurement correction in finding #7. |
| 8 | closed | `managed_obs_qualify.py:611` delegates to `mm_opacity_probe.drive`; its `PLAN` includes `d23` before `mm34`. §9.4 now schedules `mmo-cef`. | None. |
| 9 | closed | Shared resolver explicitly specifies fresh corrected PDF overlays, mapped movies, provenance, and decoding checks. `make_export`’s existing PDF copies are excluded. | None. |
| 10 | closed | Re-executed the helper: 46 matching trees copied, 87 transitions unchanged, no source mutations; all 21 near-misses rejected. Geometry/media checks address the original counterexamples. | None. |
| 11 | closed | §9.3 now requires transparency/coverage classification and separates unaffected production regression controls from affected null demonstrations. | None. |
| 12 | closed | Independent census reproduced 25 roots, 48 character dissolves, 167 movie starts, and 167 `renderMovie` builds: **382**. | None. |

**Part B — New findings**

1. **Severity: major. Class: closed class. §§3.1–3.2, 8, 10.3 — Failure handling still does not guarantee stock output.**

   **Claim:** Every missing-node or exception path restores stock before removing the outgoing DOM.

   **Evidence checked:** Plan lines 131–159; player `renderEffects` @2312557–2313095 and `animateEffect` @2302687; in-memory Node fault injection.

   Normal rejected-value cases work. However, clearing animation rules and styles cannot restore a missing container or texture leaf. D3 still executes `a.removeChild(w)`, potentially replacing the intact outgoing slide with an incomplete transition.

   Exception handling is also incomplete: node lookup occurs outside `try`, and rollback style writes are unguarded. A setter that throws on installation and clearing reproduced an escaping exception with `obedDissolve=true`, incoming opacity still `0`, and incoming rules already emptied. The supplied tests cover rejected assignments, not throwing assignments or complete DOM restoration.

   **Exact fix wording:** “Remove the outgoing live DOM only after either a complete blended transition or a complete stock transition has been established. Missing transition nodes require rebuilding stock DOM or explicit refusal while retaining the intact outgoing slide. Protect lookup and rollback failures; add throwing-setter, missing-incoming, and incomplete-tree cases to the existing parametrized behavioral test, asserting the removal decision and visible tree.”

2. **Severity: major. Class: new class. §§9.1, 10.4 — The fold deletes essential capture-integrity requirements.**

   **Claim:** Missing or malformed evidence is INCONCLUSIVE.

   **Evidence checked:** `git diff 8e572864 cd289a05`; rev-1 §9.1 integrity paragraph versus rev-2 lines 323–373 and 419–423.

   Rev 2 removes the explicit requirements for six mid-transition screenshots, texture IDs matching export JSON, before/after scene identity, actual screenshot dimensions, and transparent computed page backgrounds. Specifying driver settings does not verify captured evidence. The corresponding missing-texture/too-few-frame scorer cases also disappear.

   Consequently, sparse endpoint-only captures can leave mid-frame checks vacuous, and misrouted or incorrectly rendered captures lack defined rejection rules.

   **Exact fix wording:** “Retain the shared capture-integrity checks alongside the per-arm table: expected texture identities and scene boundaries, verified image dimensions and page mode, finite/nonempty measurements, and at least six mid frames for fade-scoring arms. Define separate minimum observations for delay and lifecycle arms. Any violation is INCONCLUSIVE and invalidates the round; restore these cases within the existing parametrized scorer test.”

3. **Severity: major. Class: new class. §§6.2, 9.1, 12.4 — The S2 recommendation targets the wrong DOM node, and its proposed oracle rejects correctly fading live media.**

   **Claim:** Reparenting the decoder into the outgoing leaf makes it inherit the fade; the unmasked texture model qualifies whole-slide integration.

   **Evidence checked:** `NB.addAnimationNode` @2294205; `NB.applyCssAnimation` @2305735; S2 `live_continuity_js.py:1759–1777`; plan lines 338–352 and 456–462.

   The leaf `layer<id>` has opacity `1` during playback. Its child **`layer<id>-opacity`** carries the animation. Appending a video directly to the leaf makes it a sibling of the fading wrapper: it inherits blending but remains unfaded.

   Separately, the proposed unmasked reference remains two static texture canvases. Correctly fading a moving decoder produces different outgoing pixels from the exported poster, so it can fail that reference despite correct compositing. The hand-off check also excludes destination movie rectangles.

   **Exact fix wording:** “If decision 4(a) is selected, place held media beneath the outgoing opacity-animation wrapper and within the outgoing blend leaf, preserving its geometry. Qualify media pixels using synchronized media-aware references or deterministic controlled movie content, with an independent full-strength-hold negative control. Retain the static texture score separately; do not label it whole-slide equivalence or media hand-off validation.”

4. **Severity: major. Class: closed class. §§3.3, 9.1 — The lifecycle inventory overstates the scheduled coverage.**

   **Claim:** Every lifecycle path listed in §3.3 has a scenario row.

   **Evidence checked:** Plan lines 168–170 versus 368–373; player `advanceToNextBuild` @2349242, separate `advanceAndSkipBuild` around @2351030, `playCurrentScene` @2356281, and `currentSceneDidComplete` @2357464.

   The scenario omits **hide/show** and **queued skip**. Adding 300 ms to the timer tests the rendering gap but does not execute the actual `automaticPlay`/`beginTime` branch. Terminal cleanup also needs a distinct expectation: with no next scene, `currentSceneDidComplete` does not call `displayScene`, so terminal transition DOM/keyframes can legitimately remain.

   **Exact fix wording:** “Add hide/show and queued `advanceAndSkipBuild` rows. Exercise the real automatic transition branch through a provenance-recorded in-memory event override; retain the timer splice as the no-flash instrument control. For terminal playback, verify the stock-equivalent held endpoint, then trigger replay/navigation and assert cleanup. Define hidden-output expectations separately from visible-frame complement checks.”

5. **Severity: major. Class: new class. §§9, 9.1, 10.4 — The new hand-off check has no designated controls.**

   **Claim:** Every blocking check has a passing positive and failing negative control.

   **Evidence checked:** Control table at plan lines 305–313; hand-off threshold at line 352; scorer cases at 419–423.

   Hand-off is included in `on`’s “all → PASS” contract but absent from both the control table and synthetic scorer cases. Comparing against a stock twin plus τ establishes a threshold; it does not demonstrate that the scorer detects a hand-off discontinuity. The difference metric and required endpoint-frame coverage are also unspecified.

   **Exact fix wording:** “Define hand-off error as an explicit pixel statistic on identified final-transition and first-live frames. Missing either frame is INCONCLUSIVE. Add an unchanged hand-off positive and an injected above-threshold discontinuity negative to the existing parametrized scorer test and control table. Validate movie-region hand-off through the separate media-aware check.”

6. **Severity: minor. Class: edge case. §9.2 — The effective CEF calibration limit is four LSB, not seven.**

   **Claim:** The listed formulas and hard caps define bounded calibration, with `n > 7` INCONCLUSIVE.

   **Evidence checked:** Direct evaluation of plan lines 379–381.

   At `n=5`, the formulas produce τ=6, complement bound=7, and no-dip bound=247. The latter two violate the stated caps. Satisfying all three caps requires `ceil(n) ≤ 4`; the disposition of `4 < n ≤ 7` should not depend on an implementer choosing between rejection and clamping.

   **Exact fix wording:** “Apply the formulas without clamping. Any cap violation is INCONCLUSIVE; with these constants this means `n > 4`. Test `n=4` and `n=4+ε` in the existing calibration test.”

7. **Severity: minor. Class: new class. §§0, 8, 9.1 — The reported P2 maximum was computed on subsampled pixels.**

   **Claim:** Rev-2 P2 maximum residual is ≤1.2 LSB.

   **Evidence checked:** `scratchpad/planner/analyze.py`, which selects every second row and column; read-only full-resolution re-execution against `runs3/p2-t-patch`.

   Scoring all pixels raises the reported maximum to approximately **1.3 LSB** across the six mid frames. DSK remains approximately 1.5 LSB; opaque stock remains 0.7 LSB. This does not threaten τ=4, but the evidence should not present a subsampled maximum as the full-image maximum, and W2 should not inherit the subsampling.

   **Exact fix wording:** “Evaluate residual maxima over every pixel in the designated scoring mask. Record full-resolution measurements and update the P2 residual claim to approximately 1.3 LSB. Keep τ=4 unchanged.”

**Part C — Closing inventory**

“VERIFIED” below covers the stated static property or existing evidence, not an unperformed qualification run.

| Verifiable claim class / item | Status | Evidence or measurement needed; scheduled? |
|---|---|---|
| Stock player identities and two PDF.js insertions | VERIFIED | Both supplied SHA-256 identities and 38-byte total difference checked. |
| §1.1 renderer routing, tree construction, keyframes, timing mapping, separate tasks | VERIFIED | Both players; CSS Dissolve route, `WB`, `NB`, and controller paths inspected. |
| R1–R8, D1–D3, hook offsets/counts/disjointness | VERIFIED | All 12 intervals checked against both primary players. |
| Replacement containment, including self | VERIFIED | No replacement contains any anchor. |
| Six replacement-group orders | VERIFIED | Identical resulting bytes for both players. |
| Complete patched-player JavaScript and scoping | VERIFIED | In-memory rendering/on/off outputs pass `node --check` for both players. |
| Normal copy/predicate path | VERIFIED | 46 copies, 87 unchanged, zero source mutations; 21 near-misses rejected. |
| Unsupported CSS / malformed-tree stand-down | VERIFIED | Existing cases rerun; returns original base layer. |
| Ordinary rejected-style rollback | VERIFIED | Mirror rules removed; incoming opacity restored; real animation guard confirmed. |
| Missing-node and throwing failure paths | FINDING #1 | Complete stock restoration/removal safety is not established. |
| Initial incoming opacity and shared animation pass | VERIFIED | Player bytes and recorded rAF show initial zero and shared animation start. |
| Advance and ordinary completion | NOT VERIFIABLE STATICALLY | Product-path pixels and cleanup require DX-1; scheduled. |
| Replay | NOT VERIFIABLE STATICALLY | Repeated playback and cleanup require DX-1; scheduled. |
| Queued advance | NOT VERIFIABLE STATICALLY | Native queue execution requires DX-1; scheduled. |
| Queued skip | FINDING #4 | Separate player path lacks a scenario row. |
| Go-to interruption | NOT VERIFIABLE STATICALLY | DX-1 scenario scheduled. |
| Back interruption | NOT VERIFIABLE STATICALLY | DX-1 scenario scheduled. |
| Hide/show | FINDING #4 | Claimed coverage absent from scenario. |
| Real automatic dissolve delay | FINDING #4 | Timer splice does not exercise the automatic branch. |
| Loop wrap | NOT VERIFIABLE STATICALLY | In-memory header override and DX-1 scenario scheduled. |
| End of show | FINDING #4 | Terminal retention and subsequent cleanup need distinct expectations. |
| Source-over, plain-double-fade dip, additive formula, endpoints, no clamping | VERIFIED | Algebra agrees with [Compositing §9.1.15](https://drafts.csswg.org/compositing-2/#porterduffcompositingoperators_plus_lighter). |
| Geometry/media preconditions and grouping effects | VERIFIED | Predicate covers original counterexamples; player rendering inspected against [Transforms §7.1](https://drafts.csswg.org/css-transforms-2/#grouping-property-values). |
| Isolation and additive order independence | VERIFIED | Correct for the two-texture group; independent overlays remain outside the proof. |
| Exact Chromium intermediate surface format / rounding attribution | NOT VERIFIABLE STATICALLY | Pixel evidence measures error, not internal surface allocation; no compositor-format investigation scheduled. |
| Chrome feature availability | VERIFIED | Chrome 100 release documentation confirms [plus-lighter support](https://web.dev/blog/web-platform-03-2022). |
| Installed OBS/CEF availability | VERIFIED | Product pin is OBS 32.2.2; installed framework plist reports CEF 127. |
| CEF off-screen correctness | NOT VERIFIABLE STATICALLY | DX-2 explicitly scheduled. |
| Switch precedence, pins, report, runtime version | VERIFIED | `live_runtime.py`, `live_host.py`; three-pin shape and unchanged off digests confirmed. |
| Synthetic player builders and literal pin locations | VERIFIED | Builders derive tuple anchors; affected output literals confined to runtime and its tests. |
| Separate-switch cost / owner decision 1 | VERIFIED | Additional switch/report/pin combinations change the design; recommendation is coherent. |
| Census and scope classification | VERIFIED | 42 Dissolves, 8 cuts, 67 MM transitions, 382 builds reproduced. |
| Texture-fill trigger and P2/D2 PDF mappings | VERIFIED | Original PDF streams contain black fills at the cited texture indices; independent root-cause records support the page/texture distinction. |
| D2 lacks exclusive coverage | VERIFIED | Verifier records zero incoming-only and outgoing-only pixels. |
| Other transition families / F1 and F2 behavior | NOT VERIFIABLE STATICALLY | F1 instrumentation and F2 authored Q-deck are designated follow-ups. |
| Production exports actually affected | NOT VERIFIABLE STATICALLY | DX-3 pre-check scheduled; no blanket production claim established. |
| Interplay: R1–R8 | VERIFIED | Byte composition checked. |
| Interplay: G2 | NOT VERIFIABLE STATICALLY | CSS route is verified; unchanged behavior/statistics require scheduled G2 regression runs. |
| Interplay: main continuity | VERIFIED | LIVE/LIVEFIX banked Dissolve rAF records contain zero visible-video frames; DX-1 schedules revalidation. |
| Interplay: S2 | FINDING #3 | Held overlay behavior verified through git ref; attachment recommendation and media oracle require correction. |
| Interplay: `managed_obs_qualify` | VERIFIED | `mmo-cef` crosses Dissolve; existing PDF-copy behavior confirmed; rerun scheduled. |
| Interplay: opacity and hand-back probes | VERIFIED | Traversal and runtime digest checking confirmed; reruns scheduled. |
| Interplay: P2 adversarial harness | VERIFIED | Patched-player serving and software non-GL paths confirmed; full regression scheduled. |
| Interplay: `run_gates.sh` | VERIFIED | No player-output SHA pin found; full tier and unchanged-file ownership are consistent. |
| Interplay: preview / paint oracle | VERIFIED | Preview uses rendering patch; oracle preserves stock player bytes. |
| S2 merge/file proximity and W0 cherry-pick contents | VERIFIED | Git-ref diff confirms runtime unchanged and nearby fixture-path test change; W0 changes stripper and its test. |
| Q0 numerical evidence | FINDING #7 | Main outcomes reproduced; full-resolution P2 maximum needs correction. |
| Opaque matched-progress equivalence | VERIFIED | Eight comparisons reproduced maximum 1.51 LSB; ongoing bound remains report-only. |
| Common DX-1 capture integrity | FINDING #2 | Rev-1 checks were removed. |
| DX-1 `on`, P2 | NOT VERIFIABLE STATICALLY | Prototype supports expected PASS; product-host DX-1 scheduled. |
| DX-1 `on`, DSK | NOT VERIFIABLE STATICALLY | Prototype supports expected PASS; product-host DX-1 scheduled. |
| DX-1 `on`, D2 | NOT VERIFIABLE STATICALLY | Overlap-only contract is coherent; Q0b and DX-1 scheduled. |
| DX-1 `on2` | NOT VERIFIABLE STATICALLY | CvC scheduled in Q0b/DX-1. |
| DX-1 `off`, P2 and DSK | VERIFIED | Banked complement/model failures reproduced; DSK take is correctly marked exploratory for load. Fresh qualification scheduled. |
| DX-1 `noblend` | VERIFIED | Existing take fails no-dip at α≈191 and passes complement; rev-2 repeat scheduled in Q0b. |
| DX-1 `opaque-off` / `opaque-on` | VERIFIED | Required overlap-only classes and observed model/no-dip PASS are consistent; fresh DX-1 scheduled. |
| DX-1 `screen-off` / `screen-on` | NOT VERIFIABLE STATICALLY | RGB expectations follow algebra; real host-path measurements scheduled in Q0b/DX-1. |
| DX-1 `delay-off` / `delay-on` | NOT VERIFIABLE STATICALLY | Splice occurs once at both cited offsets; no-flash captures scheduled in Q0b/DX-1. |
| DX-1 `on-sw` | NOT VERIFIABLE STATICALLY | Existing rev-1 take is exploratory; qualifying rev-2 repeat scheduled. |
| DX-1 hand-off check | FINDING #5 | Controls, statistic, and required endpoint evidence are incomplete. |
| DX-2 `on` / `on2` | NOT VERIFIABLE STATICALLY | CEF candidate/CvC captures scheduled. |
| DX-2 `off` | NOT VERIFIABLE STATICALLY | Independent model/complement FAIL required; capture scheduled. |
| DX-2 `noblend` | NOT VERIFIABLE STATICALLY | No-dip FAIL and complement PASS required; capture scheduled. |
| DX-2 `opaque-off` / `opaque-on` | NOT VERIFIABLE STATICALLY | Positive-control captures scheduled. |
| DX-2 calibration and caps | FINDING #6 | Combined caps imply rejection above four LSB. |
| DX-3 affected null and unaffected production control | NOT VERIFIABLE STATICALLY | Pre-check and owner observations scheduled, with separate mode/SHA reports. |
| §9.4 regression matrix | VERIFIED | `mmo-cef` omission fixed; actual regression outcomes remain scheduled. |
| Test 1: existing generic coverage | VERIFIED | Tuple parametrization supplies the claimed additional anchor/refusal coverage. |
| Test 2: pins, hand-back slice, composition | VERIFIED | Required edits match current test structure; composition independently checked. |
| Test 3: real-player helper cases | FINDING #1 | Existing cases pass, but failure coverage needs the identified additions. |
| Test 4: synthetic scorer matrix | FINDING #2, #5 | Arithmetic/curve/monotonicity cases are appropriate; capture-integrity and hand-off cases are missing. |
| Test 5: env refusal and calibration | FINDING #6 | Existing refusal test is extensible; calibration boundary must be corrected. |
| Minimal-tests rule | VERIFIED | No gratuitous function-count growth: three planned new test functions, existing tests extended, behavior cases parametrized. |
| W0 | VERIFIED | Stripper and stripper-test files; coordinator prerequisite. |
| W1 | VERIFIED | Runtime and runtime-test ownership is disjoint. |
| W2 | VERIFIED | New probe and scorer-test ownership is disjoint. |
| W3 | VERIFIED | OBS harness/test ownership is disjoint; depends on W2. |
| W4 | VERIFIED | README, skill documentation, and plan-status ownership is disjoint. |
| Owner question 2: output scope | VERIFIED | Design-changing; all-output recommendation follows the texture-trigger evidence. |
| Owner question 3: follow-up scope | VERIFIED | Changes implementation scope; deferring unmeasured families is coherent. |
| Owner question 4: held-media behavior | FINDING #3 | The decision is design-changing and warranted; its concrete recommendation needs correction. |
| Equality to Keynote-app appearance | NOT VERIFIABLE STATICALLY | Algebra establishes a normal cross-fade; direct app comparison is explicitly unscheduled/out of scope. |

**Verdict: needs another planning pass.**