Reviewed `2aadd074`; `src/` is unchanged since `debfc685`. No tests run. The reported 125/781 passes and mutation failures remain implementer evidence. New survivors below are **static predictions for behavioral tests**, assuming mutation after patching or corresponding repinning.

**All eight r2 items close. The final sweep still finds uncovered behavior.**

| r2 item | Status | File:line evidence |
|---|---|---|
| r1#1 / S1 — video guard | **CLOSED** | Unknown video/style access is recorded; `toggleAttribute`, unknown style access and an allowed read have controls. Both videos use the guard. [tests:1051][t1051], [tests:1066][t1066], [tests:1497][t1497]. |
| S2 — copied content | **CLOSED** | Key-order-independent comparison covers the entire independently constructed expected tree; outgoing identity remains asserted. [tests:919][t919], [tests:930][t930]. |
| S3 — canvas geometry | **CLOSED** | Every attached holder reports position/overflow, holder rect, canvas intrinsic dimensions, positioning and CSS rect. [tests:1100][t1100], [tests:1157][t1157]. |
| S4 — tone channels | **CLOSED** | Three complete RGBA pixels are observed; `lutTone` uses non-neutral inputs and independent Python `_tone`. [tests:1086][t1086], [tests:1162][t1162], [tests:1231][t1231]. |
| S5 — actual cut take | **CLOSED** | `CUT` comes from `_cut_from(effect)`, reaches the take, and attachment uses the real construction’s engaged kind. [tests:1091][t1091], [tests:1186][t1186], [tests:1491][t1491]. |
| S6 — stale take | **CLOSED** | One controller performs success→rejection with a seeded stale slot; the row asserts immediate clearing and no attachment. [tests:1095][t1095], [tests:1192][t1192]. |
| S7 — atomic append | **CLOSED** | Append records require one fragment containing both holders; `appendSecondThrows` detects incremental attachment. [tests:1064][t1064], [tests:1175][t1175], [tests:1189][t1189]. |
| S8 — actual call sites | **CLOSED** | Extracted D2 consumes the returned copy; extracted D4 checks `B` and take-before-display; D3 checks draw→freeze→remove. [tests:922][t922], [tests:1036][t1036], [tests:1472][t1472], [tests:1498][t1498]. |

Standards: no actionable findings.

Spec: the following inventory distinguishes catching rows from gaps. **NO ROW** means the relevant behavior lacks a catching assertion; N1–N8 identify concrete survivors below.

| §3.2 behavioral clause | Catching rows / assertions | Remaining gap |
|---|---|---|
| Predicate: transition type and accepted names | `buildType`, `otherName`, accepted Dissolve/cut and stock corpus; [tests:965][t965] | — |
| Predicate: root→one container→two textured leaves; no root/container texture or animation; no leaf sublayers | `noLayers`, `nullBase`, `threeLeaves`, committed trimmed transitions | **NO ROW** for extra containers, forbidden root/container texture/animation, missing leaf textures or leaf sublayers. |
| Predicate: object IDs, video/poster flags, identity affine/rotation/scale/opacity/transform, visible state, leaf sublayer transform | `videoLayer`, `posterLayer`, `leafObjectID`, `containerObjectID`, `affine`, `rotation`, `scale`, `incomingTranslucent`, `transform3d`, `leafSublayer`, `containerRotation` | **NO ROW** for hidden state. |
| Predicate: incoming unanimated; one plain outgoing animation; Dissolve opacity 1→0 | `incomingAnimated`, `twoAnims`, `keyTimes`, `from05`, accepted transitions | **NO ROW** for outgoing path/nested animation, wrong Dissolve property or destination. **N1**. |
| Cut timing and copied incoming state/animation | `cutBaseline`, all ten cut near-misses, full expected-copy comparison, `mirrorControls`; [tests:930][t930], [tests:993][t993] | Actual animation execution/backwards-fill rendering belongs to browser acceptance, not these construction rows. |
| Commit before construction; correct CSS declarations and allocated IDs | Accepted construction, real `VB` IDs, D2 spy, `droppedBlend`, `droppedIsolation`; [tests:933][t933], [tests:1007][t1007] | — |
| Failure returns original tree; abandoned partial-insert IDs; export unchanged; engagement kind | Five construction failures, `stockTouched`, accepted-tree mutation comparison | **NO ROW** comparing complete original contents after rejected/failing construction. **N1**. |
| Take only for `B` and eligible first effect; before teardown; same-task attachment after draw | D2–D4 spies; `success`, `realCut` | **NO ROW** exercising a rejected effect through the actual take, or an actual take at a nonzero event index. **N2**. |
| Paint gate: whole document, once, before candidate processing | `gate_*`; rejected gate rows require `vfOpened == 0`; [tests:1507][t1507] | Gate invocation count and rectangle-read ordering are unobserved. |
| Gate exceptions: nonrendering tags, suppressed groups, hidden boxes; pseudo/content/text checked before visibility shortcut | `gate_scriptTextIgnored`, `gate_suppressedTextIgnored`, `gate_opacityZeroTextIgnored`, `gate_hiddenShadowIgnored`, `gate_hiddenOriginVisiblePseudo`, `gate_before`, `gate_after`, `gate_text`, `gate_displayContents*`, `gate_listItem` | Nonrendering-tag coverage directly exercises `SCRIPT` only. |
| Gate paint families and escaped-paint restrictions | `fgImg`, `gate_svgStroke`, shifted-image/canvas rows, generated `gate_*` properties; [tests:1255][t1255] | **NO ROW** directly covering `OBJECT`, `EMBED`, `IFRAME` or form-control rejection. |
| Common chain/branch allowlist | Generated `chain_*`, overflow-axis/radius rows, transform rotation/3D/nonuniform rows, foreground branch rows; [tests:1128][t1128], [tests:1248][t1248] | Shared properties have negative coverage. |
| Scene, stage and above-stage profiles | `wrapperPreserve3dNoTransform`, `uniformScale`, `stageNonUniform`, `stageNearUniform`, baseline hidden stage/static host | **NO ROW** rejecting transformed or wrongly positioned above-stage ancestors. **N3**. |
| Plain bitmap: undecorated, zero radii/padding, default view-box/rendering | Generated `video_*` and `fgCanvas_*` bitmap rows | Only top border, top-left radius and top padding are varied; other members have **NO ROW**. **N3**. |
| Movie admission: decoded/visible/ready, opaque chain, fit/position, qualified tuple, opaque source region | `notReady`, `invisible`, `translucentAncestor`, fit/position rows, tuple rows, `sparseAlpha`, `edgeAlpha`, `lowerTransparency` | **NO ROW** directly exercising absent decoded dimensions or outside-stage video. |
| Intersecting paint: scene-local common ancestor, valid entire branch, document order; decide videos last-to-first | `fgOutsideScene`, `fgBranch_*`, `earlier*`, `flexOrder`, `overlappingVideos` | `overlapLaterNotAdmitted` fails the whole-page gate; **NO ROW** isolates a later video rejected during admission. **N4**. |
| Tone: complete RGB conversion, preserved alpha, endpoint identity, writeback before foreground | `lutGrey128`, `lutTone`, alpha-rejection rows | **NO ROW** for positive inputs in the linear toe, or writeback/redraw ordering. **N6/N7**. |
| Geometry: centred content box, rectangular clipping, viewport propagation, slide coordinates | `letterboxedVideo`, `clippedPanel`, `clippedAway`, `stageScaledInSmallViewport`, `stage2560`, `letterbox`, `rootOverflowHidden`, `bodyStaticClipIgnored` | **NO ROW** for nonzero left/top source origins or independent x/y base-rect scales. **N5**. |
| Natural-size canvas, holder clipping, document-order attachment | `_holder` assertions, `overlappingVideos`, deck holder tables | Readback/writeback coordinates remain unobserved. **N5**. |
| Foreground redraw: eligible canvas, effective opacity, location, ordering; admitted later video stays above | `fgCanvas`, `fgTranslucent`, `fgGroupOpacityAlone/WithSibling`, `fgPlacementFill`, `fgClippedBranch`, `fgCanvas_objectFitContain`, DSK7 redraw list | Relative order of writeback versus redraw is unobserved. **N6**. |
| Snapshot/add-only failure model; video untouched; candidate errors tolerated | Guard control plus every row’s `touched == []`; `drawThrows`, `videoFrameMissing/Throws`, `noOldBase` | No mixed successful/throwing-candidate row directly isolates per-movie failure containment. |
| Attach by engaged kind, matching scene, required wrapper, one atomic fragment | `realCut`, `dissolveMissingWrapper`, `attachOtherScene`, `attachUnengaged`, `appendThrows`, `appendSecondThrows` | Stored scene provenance is untested. **N2**. |
| Cleanup: consume/drop slot; replace stale take; close transient frame; holders belong to transition DOM | Every row’s slot/frame assertions; `staleAfterSuccess`; attachment target assertions | Navigation/replay/queued-skip/end-of-show lifecycle has **NO W1 ROW**; explicitly assigned to W2/browser acceptance in §11. |
| Cost publication on every path, including gate and rejected candidates | `costSuccess`, `costRejected`, `costException`; controller/window equality | Publication is covered; inclusion of actual work is not. **N8**. |

The concrete new findings are:

1. **Major — CLASS: new class — incomplete predicate/fallback oracle.**  
   At [tests:965][t965], no case supplies `x.path` or nested `x.animations`; removing either rejection at [live_runtime.py:68][p68] survives. Separately, failure assertions at [tests:950][t950] inspect identity and selected constructed fields, not complete source contents: changing the construction catch to copy `o.texture` into `i.texture` before returning `b` survives those assertions while corrupting fallback content.  
   **Exact fix:** extend near-misses across the uncovered predicate fields listed above; snapshot and compare the entire input after every near-miss and construction-failure call, alongside stock identity, kind and ID assertions.

2. **Major — CLASS: closed class — actual take inputs and scene provenance remain fixed.**  
   Every actual take uses an accepted effect at index zero ([tests:1091][t1091], [tests:1332][t1332]). Removing `||!this.__obedShape(y)` at [product:79][p79], or changing stored `scene:A` to `scene:0` at [product:144][p144], survives. The latter prevents legitimate nonzero-scene attachment.  
   **Exact fix:** parameterize actual effect/event index; add rejected-effect takes and a successful take at index 3 followed by matching attachment and mismatched-scene discard.

3. **Major — CLASS: new class — allowlist dimensions lack negative controls.**  
   The property tables exercise bitmap top-side members and movie-chain properties ([tests:1128][t1128]). Replacing the above-stage branch with `if(u)return true` at [product:99][p99], or removing the `paddingRight` check at [product:91][p91], survives.  
   **Exact fix:** add rejected above-stage transform/position rows, and generate bitmap border/radius/padding negatives for every member read by the predicate.

4. **Major — CLASS: new class — later-video rejection is masked by the gate.**  
   `overlapLaterNotAdmitted` uses `objectFit:"cover"` ([tests:1221][t1221]), which rejects the whole take before admission. Removing `if(ad.indexOf(n)<0)return` at [product:134][p134] therefore survives.  
   **Exact fix:** make the later overlapping video pass the gate but fail candidate admission—for example `readyState:1`—and require the earlier overlapping video to be rejected too. Retain the both-admitted positive row.

5. **Major — CLASS: closed class — source coordinates and independent scales are unobserved.**  
   The canvas stub ignores readback origin and writeback destination ([tests:1086][t1086]); geometry uses one scale ([tests:1060][t1060]). Both `g.putImageData(D,0,0)` in place of `g.putImageData(D,X0,Y0)` and `ky=kx` survive.  
   **Exact fix:** add left/top clipping with nonzero source origin; assert complete `getImageData` arguments and `putImageData` destination. Add an actual unequal x/y base rectangle within the admitted tolerance and independently calculated holder/canvas expectations.

6. **Major — CLASS: new class — writeback can erase foreground undetected.**  
   Move `g.putImageData(D,X0,Y0)` after `Y.forEach(...)` at [product:139][p139]. Separate `draws` and `put` results remain identical ([tests:1086][t1086]), but browser writeback overwrites the foreground.  
   **Exact fix:** assert one ordered canvas trace: video draw → readback → toned writeback → foreground draws, including multiple foreground canvases.

7. **Minor — CLASS: edge case — tone’s linear toe is untested.**  
   At [product:58][p58], replace the conditional with its nonlinear branch alone. Inputs at [tests:1171][t1171] are zero or above the breakpoint; zero still clamps to zero, so all observed samples survive.  
   **Exact fix:** compare all 256 channel inputs against independent `_tone`, including positive values below the breakpoint.

8. **Minor — CLASS: new class — the clock cannot detect excluded work.**  
   Insert `t0=performance.now()` immediately after the gate at [product:116][p116]. All duration assertions still pass because the stub advances only on clock reads ([tests:1090][t1090]), although gate time is excluded.  
   **Exact fix:** advance deterministic time in gate, rejected-candidate, draw/readback/writeback and redraw operations; assert their total on success, rejection and exception paths.

**CHANGES REQUIRED**

[t919]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:919
[t922]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:922
[t930]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:930
[t933]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:933
[t950]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:950
[t965]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:965
[t993]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:993
[t1007]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1007
[t1036]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1036
[t1051]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1051
[t1060]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1060
[t1064]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1064
[t1066]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1066
[t1086]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1086
[t1090]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1090
[t1091]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1091
[t1095]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1095
[t1100]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1100
[t1128]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1128
[t1157]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1157
[t1162]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1162
[t1171]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1171
[t1175]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1175
[t1186]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1186
[t1189]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1189
[t1192]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1192
[t1221]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1221
[t1231]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1231
[t1248]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1248
[t1255]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1255
[t1332]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1332
[t1472]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1472
[t1491]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1491
[t1497]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1497
[t1498]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1498
[t1507]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1507
[p58]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:58
[p68]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:68
[p79]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:79
[p91]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:91
[p99]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:99
[p116]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:116
[p134]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:134
[p139]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:139
[p144]: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_runtime.py:144