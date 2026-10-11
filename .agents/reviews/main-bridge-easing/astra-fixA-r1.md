REQUEST CHANGES

1. **MAJOR — `src/obed_edom/p2_verdict.py:3778–3792` — CLASSIFICATION: new class.** Slow early callbacks inflate both the motion band and displacement cap, allowing a genuinely late overlay to pass.

   Reproducer: keydown at 0 ms; polls at **90, 155, 170, 185, 200, 215 ms**; marker at 91 ms, observed on frame 2. Healthy easing crosses 1 px around 152 ms and is readable by 170 ms. A stalled overlay first detected at 215 ms is **three additional callbacks late**, exceeding the two-callback slack.

   Nevertheless, `frames=6`, `marker=2`, `delay=215`, `marker_to_trigger=124`, `pollMaxGapMs=90`, and displacement **1.234 px** produce **`pass`, `failed=[]`** against the exact commit. The whole-window mean is 35.83 ms, widening the band to 168.5 ms despite subsequent callbacks taking 15 ms.

   **Fix:** derive the allowance from recorded callbacks around the predicted departure, excluding earlier startup delays; derive the displacement cap from that deadline. Preserve the independent stall ceilings and add this variable-cadence regression case.