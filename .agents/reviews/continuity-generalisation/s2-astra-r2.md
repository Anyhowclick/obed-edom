**Five of the six r1 classes are closed. R1 #5 remains partially open, and two additional MAJOR S2 gaps block S3.** Both deliberate deviations are justified.

Static review of `702db627`; no tests run. I accept the supplied corpus, rescore, and suite results as evidence of preserved measured behavior.

**Standards: PASS — no actionable findings.** The added comments explain non-obvious safety contracts and fit the documented exception.

**Spec: actionable findings**

1. **MAJOR · new class — ordinary carry refusal leaves rejected decoders alive.**  
   [live_continuity_js.py:1951](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:1951)

   **Evidence:** `pickCarried` detects ambiguity or loop mismatch, emits `preserve-refused`, then returns `null` without retiring or unpooling its candidates. The fresh destination plays raw, but the source’s entry remains `pin`/`bridge`, so preservation remains allowed. In a bridge→pin chain, the previous held overlay can therefore continue painting beside the raw destination. Pooled candidates likewise remain eligible for keep-warm/remount.

   This violates §2.2’s refused-boundary behavior. The existing refusal test checks the raw destination and note, but never checks candidate cleanup.

   **Fix:** persist the boundary’s runtime refusal, retire its source candidates, and prevent subsequent stash/remount for that refused source. Verify both pooled and held candidates under ambiguity and loop mismatch. This is a remaining S2 gap, not a fold regression.

2. **MAJOR · new class — translucent movies can qualify for an opaque bridge.**  
   [live_continuity.py:1404](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1404), [live_continuity_js.py:1070](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:1070)

   **Evidence:** R1b rejects differing opacity only when there are multiple pairing candidates. A single moving pair at opacity `0.5` passes; so can repeated candidates whose opacities all agree. No other derivation check requires unit opacity. The bridge reparents the video onto the stage and explicitly sets opacity to `1`; the settled hold repeats that assignment.

   The resulting runtime plan contains no opacity, so an opacity-only change can even retain an allowlisted signature. Corpus plan invariance therefore does not establish rendering safety for this class.

   **Fix:** conservatively refuse carries with unsupported effective opacity, including opacity changes, until the renderer represents them correctly. Cover single-pair and equal-opacity repeated-instance cases. This is another remaining S2 gap.

3. **MINOR · new class — the new attribution filter can still falsely certify retirement; r1 #5 is not closed.**  
   [live_continuity_probe.py:2183](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2183), [live_continuity_probe.py:2824](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2824)

   **Evidence:** `bound_to_instances` trusts an explicit foreign stamp before examining decoder IDs. If a wrong-instance reuse names sibling `src`/`dst` but its `oldElId` identifies the retiring decoder, the carry note is discarded before scoring. A pool entry restamped to that sibling is similarly excluded.

   Conversely, an unstamped `preserve-refused` note with no decoder IDs returns `True` and can satisfy the positive retirement requirement. “Cannot exclude this note” is insufficient proof that the target instance was refused. Both cases undermine §4’s instance-specific, fail-closed evidence.

   **Fix:** distinguish proven target ownership, proven foreign ownership, and unknown/conflicting ownership. Positive retirement proof must establish target ownership; adverse evidence must retain unknowns and any decoder linked to the target. Add missing-attribution and conflicting-stamp/decoder controls.

**R1 closure assessment**  
Severities below retain the original finding’s severity.

| R1 | Classification | Evidence and disposition |
|---|---|---|
| **1 — MAJOR** | **Closed class** | [live_continuity.py:1398](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1398) checks all attributed candidates before assignment and refuses the entire asset pairing. Unattributed builds still refuse attempted carries. **Accept the deviation:** F3/OQ-10 does not establish the remaining movie assignment after exclusion. No further fix required. |
| **2 — MAJOR** | **Closed class** | [live_continuity.py:1368](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1368) recursively traverses descendants, including beneath exempt effects. **Accept the deviation:** exempting only movie-start and its direct `renderMovie` preserves detection of independent with-previous builds. No further fix required. |
| **3 — MAJOR** | **Closed class** | [live_continuity_js.py:1347](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:1347) uses exact canonical equality and rejects multiple movie-key claims. Probe matching also removes substring aliasing. The overlapping-name edge case is closed. |
| **4 — MAJOR** | **Closed class** | [live_continuity.py:1620](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1620) refuses all-nonvideo destinations, covering web and image movies. Mixed destinations retain a video capable of triggering the specified asset-wide restart retirement. No further fix required for this class. |
| **5 — MINOR** | **Not closed; attribution class remains** | Ordinary stamped sibling cases are fixed, but decoder/stamp conflicts and unattributed positive notes remain unsafe. See finding 3. |
| **6 — MINOR** | **Closed class** | [live_continuity_js.py:624](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:624) checks loop before memoisation; the existing glReplay failure path retires the rejected candidate. No further fix required. |

**VERDICT: FAIL — Standards 0 findings; Spec 2 MAJOR and 1 MINOR. S3 must not remove `QUALIFIED_PLAN_SHA256` with these gaps unresolved.**