# Review edge fix r1 — W1 frac boundary redraw + W6 live4 fold (Opus 5.5 high), 2026-10-14

Verdict: not ready for a full live run (1 blocker from W1×W6 interaction). Targeted 484 passed; pins recomputed (on d3ddd770… /
1036a8e2…, off and rendering unchanged); node --check OK; splice anchors intact (lut-identity pre-broken, unused).

- B1 blocker: W1 containment guard (`live_runtime.py:160`) refuses m-snap-cef-nooffset-x (splice frac-nooffset-x
  `dissolve_probe.py:172`: fx=-490 on holder [490,795,571,268], fx+fw=462<570.5) → 0 holders → MISMATCH/INCONCLUSIVE live.
  nooffset-y at y=-80 stays compatible. Fix (W6): `nooffsetx` override placing content at x≈-80 (Node: holder [300,795,571,268]);
  prove overlap/strip/attribution offline as for y. Include both nooffset arms in the first scratch subset.
- M1 medium: right/bottom repair branch (`ei+1>fx+fw`, vw-1/vh-1 clamps) untested; add Node row vrect [108.7,794.7,952,268].
- M2 medium: live can confirm the underlay-bleed fix (predict row 795 edge 9 → ~2) but not the repair source coordinates (counter
  flat across the edge); correctness rests on analysis + Node pins; the Python oracle copies the JS formula. Instrument limit.
- L1: repair after getImageData may sample frame N+1 while playing (paused probe unaffected); residual, 1-px line.
- L2: DSK extra draws negligible; ≤50 ms confirm live. L3: `score_displaced_holder` (:2341) |d|<1 → INCONCLUSIVE.
  L4: (:3433) pass demix_es only for existing demixed candidates. L5: widen nooffset_y overlap test to all events (claim holds).
  L6: diagnostic rescore with the pin rule relaxed to confirm m-fg-cef before live.
