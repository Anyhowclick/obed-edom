Three **MAJOR** findings. Static review only; no tests run. No actionable standards findings.

1. **New class · MAJOR — Bridge qualification does not enforce the assumed easing.**  
   [live_continuity_js.py:975](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/src/obed_edom/live_continuity_js.py:975)

   **Evidence:** `_EFFECT_TIMING_FUNCTIONS` constrains GL-replay pin qualification; that path rejects bridges. Ordinary bridge derivation checks geometry and transition duration without validating animation timing. Timing is also absent from the qualified runtime signature. Consequently, changing only a P2-shaped export’s movie timing to linear preserves qualification, but the overlay now moves eased—introducing the inverse mismatch.

   **Fix:** Validate the carried movie’s timing function, start offset, and animation duration before qualifying a bridge, or carry those values into the runtime. Add qualification tests that change these fields while preserving P2 geometry; the new motion tests assume the easing restriction rather than establish it.

2. **New class · MAJOR — Choosing alignment by minimum exposure can erase a real strip.**  
   [live_continuity_probe.py:6244](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/scripts/live_continuity_probe.py:6244)

   **Evidence:** Each screenshot selects whichever DOM rectangle within ±17 ms produces the fewest exposed pixels. Consider P2’s overlay lagging its poster by one 60-Hz frame. Near the midpoint, its right edge exposes approximately **8.5 px**, exceeding the 5-px limit. The next DOM sample matches the screenshot’s poster rectangle and removes that exposure from scoring. The older overlay protrudes only approximately 2.5 px leftward, absorbed by the 4-px dilation. This can score clean while the registered linear and null controls still fail.

   **Fix:** Establish synchronization independently of measured exposure. If plausible alignments disagree across the acceptance threshold, return INCONCLUSIVE. Add a genuinely delayed-overlay case alongside the existing timestamp-offset test, which currently endorses best-case alignment.

3. **New class · MAJOR — Missing temporal coverage can still produce PASS.**  
   [live_continuity_probe.py:6248](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/scripts/live_continuity_probe.py:6248)

   **Evidence:** Unaligned frames disappear from both the clean-share denominator and strip check. Coverage requires only an aggregate frame count. P2’s 1.2-second middle window needs 24 aligned frames; these can occupy approximately 0.4 seconds at 60 Hz. Those clean frames yield PASS even if the remaining 0.8 seconds is missing or unaligned and contains the defect.

   **Fix:** Require coverage throughout the window, bound maximum gaps and discarded-frame share, and classify insufficient coverage as INCONCLUSIVE. Add concentrated-sampling and mid-window dropout cases; existing tests cover only insufficient total counts.

The Bézier arithmetic itself looks correct: exact clamped endpoints, monotone curve, proper x-axis inversion, and the existing preserved start time. I found no other explicit bridge interpolation path needing the same change.

Supporting both players retains exact input admission and adds pinned output verification for all three patch modes. The byte-normalization proof and independent rational Bézier reference provide meaningful coverage. P2 reporting and preview routing remain consistent.

`run_gates.sh` rejects unexpected statuses, missing/stale exits, and wrong control/core identities. Those checks cannot detect a scorer’s false PASS. The thresholds and masks remain P2-calibrated; the disclosed D1 marker failure is outside this round’s scope.

**Verdict: REQUEST CHANGES — three MAJOR correctness findings remain open.**