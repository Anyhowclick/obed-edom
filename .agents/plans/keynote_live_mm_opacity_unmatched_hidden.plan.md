# Magic Move: keep never-visible source leaves invisible through the held endpoint

**Draft for subsequent implementation; 2026-10-15. Investigator → planner: GPT-6 Astra. No implementation or gates run.** Evidence: `.agents/reviews/mm-opacity-unmatched-hidden/investigation.md`, `offline_evidence.json` there; F2 exports at `~/Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/`. **Not yet critiqued**; see the handover `alpha-keynote-parallel-2026-10-15.md`. Builds on `keynote_live_mm_opacity.plan.md`, `keynote_live_mm_opacity_fade.plan.md`, and `keynote_live_handback_geometry.plan.md`. This plan records recommendations without requesting an interactive decision in this task.

## 1. Finding and scope

Old F2 slide 3→4, zero-based leaf slots 7 and 8: source map images at `[568,510,44,50]` and `[652,506,88,59]`, constant-zero wrappers, leaf initial opacity 1/hidden false, leaf tracks `opacity 0→0` followed by `hidden true→true`, both `forwards`. Stock GL flattens away the wrapper and ignores the equal-endpoint opacity and hidden tracks; it draws Opacity 1 from onset through settle. R1/R2 know ancestor product 0, but both constant-opacity and fade admission reject this leaf. The terminal canvas persists until destination scene teardown, nominally about 300 ms after the 1.5 s MM in the preloaded manual-show path. It does not become visible through end-of-track reversion.

Desired behavior: both source-only images contribute zero pixels from first MM draw through removal of the held canvas. Slide 4's automatic Malaysia build proceeds on its authored timing. Normal matched map pieces, fades, hand-back geometry, and output integration retain their behavior.

Scope is the **proved never-visible encoding under a proved zero ancestor chain**, not generic unmatched-object detection, a complete GL animation/fill implementation, or a change to transition timing. The raw stock control remains raw; the product change reaches live and Build Preview through their existing shared rendering replacement tuple.

## 2. Minimal patch and admission

Implement only in `src/obed_edom/live_runtime.py`, within the SHA-pinned, count-checked, **in-memory** `_MM_OPACITY_REPLACEMENTS` path used by `patch_player` and `patch_rendering`. Never modify an exported `assets/player/main.js` on disk. Keep `mm_opacity` precedence/rollback and `RUNTIME_VERSION` unchanged. Unknown input SHA, missing/ambiguous anchors, or wrong output SHA still raises `LiveRuntimeUnsupported`.

At **R1 setup**, add a small predicate to `_MM_OPACITY_NODE` and resolve an admitted leaf to `e.obedOpacity=0`. R3 already honors a non-null zero; no per-frame helper, new GL wrapper, skipped draw, texture upload, or lifetime change is required. Reuse the effect name `B`, inherited proof `X`, and effect duration `D` already available through R1/R2/R13. Keep the existing `__obedFade` rule intact. Do not make zero an absorbing value for every unknown node in `__obedChainOpacity`.

Admission must require all of the following; any missing, malformed, unrecognized, or failed check leaves current behavior intact:

1. Effect name is exactly `apple:magic-move-implied-motion-path`; effect duration is positive and finite. The ordinary chain proof supplies a **known, finite, effective ancestor product exactly 0**. Use animated node values, not a scan for `initialState.opacity===0`.
2. A terminal textured leaf, no children, no movie/web-video role or contents change; initial opacity 1, hidden false, scale 1 as in the observed leaves. No attempt to infer visibility from texture identity or `singleTextureOpacity`.
3. Exactly one non-property animation group, begin 0, duration equal to the effect duration, fill `both`, removedOnCompletion false, additive false, repeatCount/timeOffset 0, autoreverses false. No nested group, path, keyTimes/values, or other timing override.
4. Exactly two scalar tracks, in the observed order: opacity then hidden. Opacity is numeric **0→0**, begins at 0, has positive duration no longer than the effect, and fill `forwards`. Hidden is boolean **true→true**, begins at the opacity endpoint and ends at the effect endpoint, has positive duration, and fill `forwards`.
5. Both tracks have the observed non-additive, non-repeating, zero-offset, non-autoreversing completion flags (`removedOnCompletion:true`). Reject extra properties/unsupported animation encodings rather than treating them as inert. Validate recognized timing functions; F2 uses EaseInEaseOut on opacity and none on hidden. Timing checks use a documented ≤1e-9 seconds comparison for exporter roundoff, not broad scheduling slack.

The ancestor proof plus this leaf shape establishes invisibility over the entire effect and held endpoint; no inference from “unmatched” geometry is necessary. The constant-zero leaf track begins at zero and the hidden tail covers the remainder. The ancestor proof must still reject unknown wrappers; do not independently broaden its admission. This is intentionally narrower than correcting every constant `forwards` opacity track.

**Guard-critical counterexample:** F2's legitimate zooming slots 10/11 have initial-zero wrappers but opacity `1→1 both`, so their effective ancestor product is 1. They must never enter this branch. Likewise, existing Alpha_DSK fades under 0.611768 wrappers stay on the existing fade branch.

Preserve draw order, program count, geometry and textures. Writing Opacity 0 through R3 suppresses the contribution while preserving the structure observed by GL replay. Do not filter these leaves out of `setupTexture`, because that renumbers draw slots and changes the recorded frame.

Recompute **on and rendering** SHA pins for both supported players after composing the entire current replacement tuple. **Off** hashes must remain byte-identical. The repository's pins changed concurrently during investigation; use the implementation checkout as the candidate base, and use immutable `real-patched/main.js` as the reported-bug baseline. Do not restore old tuple/pin bytes wholesale.

## 3. Minimal evidence and tests

Extend the existing real-method extraction checks in `tests/test_live_runtime.py`; do not create a second patch framework or tests that merely echo the predicate. One compact real F2 wrapper/leaf fixture plus a table of meaningful mutations is enough.

- Execute the actual extracted setup and QB draw methods from both supported players. At t=0, 0.49995−epsilon, 0.49995+epsilon, an interior point, 1.5−epsilon, and terminal progress 1: stock and immutable old patched reproduce 1; candidate produces 0. Include terminal clamping/continued hold observation in the rendered gate, since a pure method call cannot demonstrate canvas persistence.
- Negative cases: visible matched initial-zero/animated-one wrapper; real existing Alpha_DSK fade; unknown/animated/hidden ancestor; wrong effect; nonzero endpoints; delayed opacity; false→true hidden or hidden false; wrong fill; extra opacity track; extra transform/contents track; nested group; repeats/additivity/offset; mismatched intervals; non-finite/malformed duration. Assert they retain the prior player's result, not that all fallbacks return 1.
- Existing pin/anchor checks cover both real players, on/off/rendering composition and failure on unsupported/corrupt input. Add cases to the existing checks rather than redundant tests.
- Extend the existing corpus mirror with the new branch, but require agreement with the extracted real methods on the exact positive and boundary/negative fixtures. A Python mirror alone is not acceptance evidence.

No pytest or suites are run for this investigation. Subsequent implementation uses focused existing checks and the gates below, consistent with the owner's minimal-test rule; it does not inherit a blanket full-suite gate from older plans.

## 4. Gates

Missing evidence, wrong player/effect, a missed automatic-build window, unavailable GL, or an unexercised branch is INCONCLUSIVE and blocks promotion.

| Gate | Required green evidence | Positive / known-bad control | Negative / null control |
|---|---|---|---|
| **UH-0 real methods and pins** | Both supported players; real F2 leaves resolve/draw 0 at all samples; expected outputs pinned; off unchanged; rejected shapes preserve prior behavior. | Stock and immutable old patched give 1 for both leaves. | Legitimate matched map and existing fades keep their prior nonzero draws; malformed shape stays legacy. |
| **UH-1 headless reproduction** | Old F2, 1920×1080, automatic timing preserved; every target GL draw has effective Opacity 0; target-draw ROI before/after is identical; compositor frames show neither duplicate through the measured Dlast→removal hold and destination build start. Cover `patch_rendering` and `patch_player`, both supported player hashes; GL replay/continuity off for causal isolation. | Stock and old patched on identical data must show both nonzero target contributions and the held artifact. No “pass” if they fail to reproduce. | Candidate-vs-candidate repeat; two-leaf-removal twin; visible sibling control. `newexp3` additionally confirms no admission when those leaves are absent. |
| **UH-2 corpus and existing MM regression** | Current patch versus candidate changes exactly old F2 `(f2350147…,7)` and `(f2350147…,8)` when old F2 is added; zero changed leaves in the 26-effect/122-leaf fixture census; zero shimmer/sparkle census explicitly recorded. Existing MO and HB headless gates and Alpha_DSK fade checks remain green. | Existing MO/HB/PF known-bad arms retain their discrimination; stock controls are separate from incremental candidate comparison. | Existing fixed-vs-fixed controls; all rejected branches and legitimate F2 matched pieces unchanged. |
| **UH-3 integration with Stage B** | After composing both streams, a continuity-on F2 pass still suppresses the two leaves; on the already-qualified P2 G2 fixture, MO GL-on/forced-stand-down and hand-back checks still pass. Validate installation order and effective cached uniforms. | Existing replay/stand-down controls, without changing their thresholds or expected geometry. | Plain preview reproduces the same correction without any Stage B code. No G2 claim on F2 unless a usable `glReplay` boundary actually engages. |
| **UH-4 owner eye** | Owner's F2 old slide 3→4: no small Malaysia copies during zoom, settled hold, or just before automatic Malaysia build; main map motion, textures, and destination build unchanged. Check actual product path. | `mm_opacity` off / saved stock old export reproduces the report. | Edited F2 remains clean; existing visible matched pieces remain visible. |

UH-1 uses the `mm_opacity_probe.py` logger pattern with a small F2 driver, not that script's hardcoded P2 sequence. Sample from first draw, not only its existing settle window. Resolve actual texture/program/rect identity and capture cached uniform values. Record D0, Dlast, actual scene index, canvas removal, automatic build start and frame gaps; a generic sleep or final screenshot misses this short hold. Capture RGBA inside draws and correlate with page/compositor frames during the hold. Prove each target texture is nonempty in the known-bad arm.

For UH-2, reuse `scripts/mm_opacity_probe.py` (headless MO-1/MO-4/MO-5, GL-on and forced stand-down), `scripts/mm_handback_probe.py` (HB-1/HB-2), and the fade plan's PF-1/PF-2 Alpha_DSK samples (6→7 slot 3; 7→8 slots 4/8 and stable slot 6). Preserve their established thresholds and controls; do not silently rebaseline a failure. Investigate failures at the renderer/recording boundary before changing any expectations. This patch does not justify new OBS qualification or blanket suites; a newly observed integration defect is a reason to revisit that scope, not preemptively broaden it.

Pixel tolerances for a full-page repeat must be calibrated against fixed-vs-fixed capture noise and remain decisively below both known-bad map contributions. The more direct per-target-draw zero-contribution assertion has exact equality in the same framebuffer at Opacity 0; do not loosen it merely to make a page-level noise metric pass.

## 5. Work streams and coordination

| Stream | Owned work | Completion condition |
|---|---|---|
| **W1 patch + focused checks** | `live_runtime.py`, both sets of on/rendering pins, existing runtime test extensions and compact F2 fixture. | UH-0; precise changed-set evidence for UH-2. |
| **W2 headless evidence** | Reuse logger/extraction patterns; F2 scratch driver and score/report; existing MM/fade/hand-back regression runs. Keep artifacts in a designated writable scratch directory. | UH-1/UH-2 with positive/negative controls and frame-boundary evidence. |
| **W3 integration and review** | Compose with Stage B, assess combined bytes/hooks, then owner visual qualification and short gate record. | UH-3/UH-4, no unresolved rendering regression. |

These are ownership boundaries for later execution, not a request to spawn agents during this non-interactive investigation.

**Stage B (S2 follow-ups session) owns `live_continuity_js.py` and the MM feed / GL replay context hooks.** This fix requires no edits to those files/hooks and must not replace, reorder or fork them. The overlap is precise: W1 changes Opacity submitted by QB for admitted leaves; Stage B may wrap the same WebGL context and feed/replay textures/draws, including held frames, and may observe uniform state cached by the player. The diagnostic logger also wraps draw/uniform calls. Coordinate logger installation so it observes the final effective uniform, cannot overwrite zero, and cannot perturb the recorder's frame or slot topology. Preserve original draw count/order and texture binding sequence.

`live_gl_replay_js.py`'s `wrapContexts`, recorded-frame replay, `restOpacity`, `proveOpacity`, context-loss and getContext hooks stay Stage B's responsibility. If a replay proof/expectation changes, first show the combined per-draw record; request that owner stream's adjustment rather than patching the hooks here. Do not change continuity retirement/hold timing to conceal this renderer bug. Any edits to shared `mm_opacity_probe.py` or fixture expectations have one writer agreed between W2 and Stage B. Compose and re-pin shared runtime changes serially; no use of stale pins captured during this investigation.

## 6. Owner questions (recorded; no response needed for these deliverables)

- **OQ-1 — Admission breadth.** Recommend the exact never-visible opacity/hidden pair under an effective zero ancestor, MM only. Defer general constant-`forwards` tracks, hidden-animation evaluation, and arbitrary unknown subtrees until independently evidenced. It fixes both F2 leaves and changes no current fixture leaf.
- **OQ-2 — Release bar.** Recommend headless reproduction with controls, existing MM/fade/hand-back regressions, Stage B composition, and owner eye on old F2 3→4 as blocking; no new OBS take or full suites for this small rendering admission change.
- **OQ-3 — Durable regression data.** Recommend retain a compact sanitized F2 subtree fixture in the existing test-fixture family and keep the old raw export read-only for the headless/eye gate. The edited export no longer contains the defect, so it cannot replace the positive fixture. Avoid committing the whole owner's deck.

## 7. Acceptance and rollback

Ship only after UH-0…UH-4 pass. Record input/player/output hashes, exact admitted leaf set, per-frame/hold evidence and owner-eye result. `mm_opacity=off` remains the existing byte-identical rollback. No new switch, fallback renderer, texture repair, scene timer change or main.js disk rewrite is part of this plan.
