**REQUEST CHANGES** — reviewed pinned commit `18bbc221`; shared checkout HEAD differs.

- **R2 item 1: CLOSED** — `src/obed_edom/p2_verdict.py:3839–3854,3884`. Late trigger remains `inconclusive` with either hold cadence; recorded deadline is frame 5, trigger frame 6. **CLASSIFICATION: closed class.**
- **R2 item 2: CLOSED** — `src/obed_edom/p2_verdict.py:3839–3854`. Loaded-run reproduction passes with either recovered or slow hold cadence. **CLASSIFICATION: closed class.**

**MINOR — `src/obed_edom/p2_verdict.py:3505` — CLASSIFICATION: edge case.** Marker bracketing rejects a legitimate timestamp tie. A poll followed immediately by runtime marker creation can return the same coarsened `performance.now()` value; the next callback correctly observes the marker, but `previous_poll >= marker_started` rejects it. Equal readings are permitted by [High Resolution Time](https://www.w3.org/TR/hr-time-3/#dfn-coarsen-time).

Reproduced: polls **30/60/90/120/150/180/210 ms**, marker **90 ms**, marker frame **4**, trigger **215 ms**, displacement **2.192 px**. Result: `inconclusive`, only `firedAtRuntimeMotionStart`. Moving the marker to **90.1 ms** produces `pass`.

**Fix:** allow equality for the preceding poll (`>` instead of `>=`), or record marker visibility per callback; add this regression.

No recorded-but-skipped departure check found: recording follows departure calculation and reaches its branch synchronously (`scripts/p2_recovery_html_adversarial.py:1324,1343,1357`). Poll, trigger, and runtime marker use the same `performance.now()` clock. Nominal **16.67 ms** cap extrapolation cannot bypass the independent frame deadline; no additional late-overlay admission found.

Validation: **19 pinned trigger cases passed**, plus the reproductions above. No files edited.