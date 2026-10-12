**All three round 2 classes are closed. No actionable fold regression or genuinely distinct new class found. Both design choices are justified.**

Static review of `e2733f34..32067445`; no tests run. I accept the supplied corpus invariance, artifact rescoring, and suite results as evidence of preserved measured behavior.

**Standards: PASS — no actionable findings.** The changes reuse existing retirement machinery and keep the new safety checks localized. Comments explain non-obvious contracts.

**Spec: closure findings**

1. **MAJOR · closed class — r2 #1: refused carries leave rejected decoders alive.**  
   [live_continuity_js.py:1964](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity_js.py:1964)

   **Evidence:** `pickCarried` records the refusal before immediately retiring the pooled/held candidates. Retirement pauses and removes them, invalidates their generation/remount state, and removes pool membership. `zoneMode` and the retirement sweep also consult the refusal, covering later teardown, stash, and remount attempts. This closes the lifecycle mechanism, including absent candidates that arrive later.

   **Fix:** none further required.

2. **MAJOR · closed class — r2 #2: translucent movies qualify for opaque carry.**  
   [live_continuity.py:1308](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1308), [live_continuity.py:1600](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/src/obed_edom/live_continuity.py:1600)

   **Evidence:** movie and video layers must explicitly record opacity. The check examines movie-subtree opacity and ancestor/object opacity along the draw path across events, requiring exact numeric `1`. Either nonopaque endpoint refuses the carry before overlap/glReplay qualification. Single pairs, opacity changes, and equally translucent repeated candidates are therefore covered independently of R1b.

   **Fix:** none further required for the demonstrated class. Updating the synthetic host fixture to include real-export opacity records is appropriate.

3. **MINOR · closed class — r2 #3 / r1 #5: attribution falsely certifies retirement.**  
   [live_continuity_probe.py:2186](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2186), [live_continuity_probe.py:2842](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/obs-mac-camera-swap-fbc63b/scripts/live_continuity_probe.py:2842)

   **Evidence:** ownership now distinguishes target, foreign, and unknown. A target-linked decoder defeats a foreign stamp, retaining conflicting carry notes and pool entries as adverse evidence. Positive refusal evidence must establish target ownership and, when stamped, name the source. Unattributed positive notes no longer prove retirement.

   **Fix:** none further required.

**Design judgments**

- **Accept generation-scoped refusal.** `clear()` invalidates old preserved work and starts a fresh generation. Allowing newly created decoders to retry the boundary matches that lifecycle and avoids permanently disabling it after a mid-chain landing.
- **Accept separate R9.** R1b concerns whether pairing is trustworthy; R9 concerns whether a chosen pair can render correctly. Per-carry R9 preserves that distinction without weakening asset-wide R1b.

No additional real-export failure mechanism was established. Hypothetical duplicate draw paths or malformed layer structures remain **edge cases**, not new classes.

The core-byte change still reopens **Q2–Q6 under plan §4**. Stored-artifact rescoring does not replace those live gates.

**VERDICT: PASS — Standards 0 actionable findings; Spec 0 actionable findings; all three r2 classes closed. S3 remains subject to the required S2 qualification gates.**