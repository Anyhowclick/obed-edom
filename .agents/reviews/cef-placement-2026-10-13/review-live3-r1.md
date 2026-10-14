# Review live3 r1 — W6 2A fix (Opus 5.5 high), 2026-10-14

Verdict: not ready for the live rerun. anim_problem fix and raw-tone twin can land.

- M1 major: corrected near clip cuts the counter strip out of every near cell (near-x clip 490.34 vs strip 109–446; near-y clip
  902.45 vs strip 795–815) → holder_strip None → positive near cells INCONCLUSIVE live, while the nooffset exemption passes the
  negatives. Options: (a) far-side second strip copy in the counter fixture (fixture digests change); (b) record "strip clipped by
  geometry" and rely on the paused rVFC reference for frame identity. Add a correct-near-clip scorer row. Coordinator/owner call.
- M2 medium: `_clip_near` shifts only the video child; sibling visible texture (foreground canvas 3231B69B…) moves +379 x / +110 y
  onto the new clip edge. Shift every child of parent["layers"]; test every child's absolute near edge. Likely also why
  m-snap-cef / wrongrule-cef have no edge band.
- M3 medium: m-tone-cef expects tone PASS only because decision L="analytic"; the take applies identity; plan §0/§2.7/§5 W5:
  identity take, tone gates report only. Add "tone" to CEF_PLACEMENT.reported (or score with identity); keep mask and tone
  observation enforced. Re-label PRODUCT → INSTRUMENT.
- M4 medium: nooffset exemption keyed on splice substring + twin expect used only as a trigger; no positive attribution that the
  FAIL is the dropped offset. Explicit Arm field; drop twin expect; attribution check A0 ≈ S_live shifted by predicted displacement.
- L1 low: anim_problem spec-faithful; finished-with-pending-play still rejected (fails closed, ok).
- L2 low: raw-tone twin reuse valid.
- L3 low: tests can't catch M1/M2; synthetic negative strip doesn't model off-canvas strip.
