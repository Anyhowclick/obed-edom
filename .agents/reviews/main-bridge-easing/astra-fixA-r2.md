**REQUEST CHANGES**

**R1 MAJOR: PARTIALLY CLOSED** — `src/obed_edom/p2_verdict.py:3785–3799`. The original regression now returns `inconclusive`, but post-trigger slowdown reopens the same false-pass class.

1. **MAJOR — `src/obed_edom/p2_verdict.py:3785–3799` — CLASSIFICATION: edge case.** Future cadence can validate an already-late overlay. Reproduced against `abefdb2d`: retain r1’s polls **90/155/170/185/200/215 ms**, marker **91 ms**, and displacement **1.234375 px**; set the first five post-trigger intervals to **25 ms**. The band becomes **136.04 ms**, accepting the **124 ms** marker→trigger delay; displacement cap becomes **5.072 px**. Result: **`pass`, `failed=[]`**, with maximum gap still **90 ms**.

   **Fix:** record pre-trigger callback timestamps and derive the deadline from actual callback opportunities around predicted departure; derive the displacement cap from that deadline. Add regression coverage where post-trigger cadence changes independently.

2. **MINOR — `src/obed_edom/p2_verdict.py:3785–3796,3831` — CLASSIFICATION: edge case.** Healthy loaded runs can become inconclusive when cadence recovers. With **30 ms** pre-trigger callbacks, **120 ms** marker→trigger, and displacement **D(90 ms) = 2.192 px**, post-trigger cadence of **30 ms** passes; changing it to **16 ms** produces only `firedAtRuntimeMotionStart`, because the band shrinks to **109.04 ms**. This requires no isolated stall.

   **Fix:** use the recorded pre-trigger callback sequence and add this cadence-recovery regression.

Fast post-trigger cadence cannot hide positive lateness: it narrows the band and cap. Its risk is false **inconclusive**, not a false `fail`.

Validation: all **16** targeted trigger cases passed; fewer than five recorded callbacks fail closed. No files edited.