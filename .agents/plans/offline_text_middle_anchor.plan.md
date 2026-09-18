---
name: Offline text — middle-anchor reposition (OPEN 1 reopened)
overview: >-
  2026-09-18. Two Fable peers in series (analysis + adversarial review) overturned the "middle-anchored
  autosize text is BLOCKED on Δh" conclusion of the 2026-09-18 handover: it was a mis-diagnosis. Middle
  text does not drift on Δh for a position-only write; the 174px that blocked it was the deck's one
  right-aligned box under the shipped absolute `pos_x`. This plan captures the corrected diagnosis, the
  reworked increment (drop the `top_anchored` refusal + a delta-form x write), the four diff bugs to fix,
  the gate rework, and the single owner-gated live experiment that confirms it. Grow-height width writes
  (c) stay behind their own flag as the only unvalidated mechanic. Wall-time lever is still NOT unlocked
  (non-text specs keep the AppleScript fallback pass alive) — this is a coverage/correctness win.
  Source artifacts (this session's scratchpad): `dh_middle_analysis.md` (peer 1),
  `dh_middle_review.md` + `adv/` (peer 2). Canonical resizer plan: `cg_resizer.plan.md`.
todos:
  - id: corrected-diagnosis
    content: >-
      RECORD OF FACT (offline-evidenced; live confirm still owed). (1) A position-only write changes no
      layout input, so Keynote's re-laid-out height is identical seed→final (Δh=0 by determinism);
      re-measured per-label with an FFT matcher + positive/null controls (82/82 injected-shift detection),
      0 of ~100 resolvable middle boxes moved vertically across the full pipeline (pass-1 save → seed
      reopen → offline write → AppleScript session → export). (2) The 174px "middle drift" was slide-70
      ki18 in the post-z-order verify index = the deck's one kFrameAlignTop RIGHT-aligned grow-both box
      (stored x = right edge, off-canvas); Δ174.00 = its width to the pixel under `_text_fields`'
      `pos_x = spec.x`. Not a `naturalSize(0,0)` mis-render. (3) Reading (i) of the "centre-preservation"
      hypothesis is algebraically the shipped top-delta formula (sy≡1, `reported_h` is already CG-scale);
      reading (ii) is worse for position-only and only correct paired with a width write. `ta-derive`
      still bars deriving the absolute render height offline — but the middle fix never needed it.
    status: pending
  - id: shipped-defects-161
    content: >-
      Two confirmed latent defects in the default-OFF `OBED_OFFLINE_TEXT` path shipped by PR #161
      ("correct, live-validated" is contested). (a) `pos_x = spec.x` is absolute, but stored x is the
      anchor point: centre for centre-aligned grow-both (b=½), right edge for right-aligned (b=1). 68
      centre + 1 right box on Full_Report_Card land w/2 (or w) to the left. The right-aligned case is not
      latent — it produced the live Δ174 in `run_on_fix_validate`, so the top-only shipped path DID
      convert a box wrongly; the `nw>0` gate then hid it for an unrelated reason. (b) A grow-height box
      keeps pass-1's 0.25× canvas-scaled width under a position-only write → wrong wrap; `verify_live_frames`
      compares x/y only, so it passes a visibly wrong box. Both must be fixed regardless of the enable
      decision.
    status: pending
  - id: impl-drop-top-and-delta-x
    content: >-
      THE INCREMENT (GO, on this session's implementation branch `research/resizer-middle-anchor-text`).
      In `iwa_write._slide_edits` text branch + `_text_fields`: (a) drop the `top_anchored` requirement —
      the position-only y-delta is anchor-agnostic for a∈{0,½,1} when Δh=0; (b) write x as a delta
      `stored[0] + (spec.x − reported[0])` (symmetric with y, anchor-agnostic for b∈{0,½,1}) instead of
      absolute — this fixes both the 68 centre boxes and the right-aligned Δ174. Keep it position-only
      (never a size) and seed-gated. Default OFF behind `OBED_OFFLINE_TEXT` as today. Update the
      docstring + the `middle_anchored_hard_misses` / `unlaidout_hard_misses` tests whose stated evidence
      ("174 measured on a middle box" / "on a (0,0) box") is wrong.
    status: pending
  - id: impl-four-diff-bugs
    content: >-
      Peer 2's four bugs in peer 1's sketch, to fix in the increment. (1) `used_reported` accounting
      (~iwa_write.py:749): key the 0-fallback flag off the BRANCH taken (position-only ⇒ seed used;
      fixed-frame ⇒ pos_y/size_*; regrow ⇒ no seed), NOT off field names — adding "pos_x" to the tuple
      regresses the 2d59f9c fixed-frame path and miscounts regrow. (2) Grow-height regrow (flag c) must
      pass `_natural_writable(obj, both_axes=False)` or an editableBezier text box silently skips
      `_write_natural_size` → gating `text-natural-width` violation. (3) Regrow's `pos_y = spec.y +
      a·spec.h` is wrong for title/body/list roles: `spec.h` is a recipe SLOT rect (titleDst/bodyTextDst/
      _style_text_box), not `s·h_wall`; only role `other` is the affine image — restrict (c) to `other`
      or derive h differently. (4) `test_autosize_text_reposition_x_without_y_needs_no_seed` inverts
      (delta-x now needs the seed) — update the contract explicitly. Also note `align not in
      _ANCHOR_FRACTION` refuses None, stricter than `_autosize_rect`'s middle default.
    status: pending
  - id: gate-rework-nw
    content: >-
      The conversion ceiling, not the math, is the risk. Pass 1's refont+save zeroes BOTH `naturalSize`
      axes (4/4 subset boxes: grow-both had nw==0, grow-height had nh==0). Peer 1's plan keeps the `nw>0`
      "laid-out" gate whose only justification is the misattributed 174 → it would refuse ~every grow-both
      box and report a phantom ~0 ceiling. Rework: in the experimental arm, drop/arm-off `nw>0` (keep it
      only if the pass-1 snapshot proves nw>0 boxes exist), and attribute every verify failure to its
      (anchor, grow-mode, nw, nh) class from a pass-1 snapshot so a real drift is never blamed on the
      wrong gate. The genuinely un-renderable class (`naturalSize.width==0` invalid-cache sentinel, e.g.
      ki18) stays refused only if the snapshot shows it is distinguishable from the benign post-pass-1
      zeroing — decide empirically, not by theory.
    status: pending
  - id: verify-wh
    content: >-
      Add live `w` (and `h`, loosely) to the offline-written-text comparison in `verify_live_frames`, so
      the grow-height wrap defect (b) is gated instead of invisible. `verify_offline_frames` still
      excludes text. Replace the §5 PNG check's band matcher (`png_shift.py`, no positive control, blind
      inside multi-label bands, search radius too small for a 174px move) with a per-label matcher that
      has a positive control (peer 2's `adv/label_shift2.py` is one).
    status: pending
  - id: live-experiment
    content: >-
      OWNER-GATED (Keynote hands-off). One run confirms (a)+(b) and decides (c) and the nw gate. Deck
      `Full_Report_Card_Wall.key --slides 4,57,70,123`; flags `OBED_OFFLINE_WRITE=verify OBED_OFFLINE_TEXT=on
      OBED_OFFLINE_TEXT_REGROW=on --validate` on the reworked branch. Snapshot `dest` right after
      `_require_pass1_saved_closed` for an offline `text_census.py` pass-1 census (the true ceiling +
      per-class nw/nh). Measure offline: (1) pass-1 nw/nh per anchor/grow-mode; (2) `verify_live_frames`
      text row ≤0.5px on all but the genuinely-refused sentinel; (3) per-label PNG matcher vs the retained
      `subset_off_validate_CG` baseline. Kill criteria PER CLASS: a middle box |dy|>1 kills (a); a
      centre/right label |dx|>1 kills (b); a grow-height box still narrow-wrapping kills (c) → grow-height
      stays on AppleScript. Do NOT run without an explicit owner go; do NOT enable by default without one.
    status: pending
  - id: wall-time-note
    content: >-
      Wall-time lever is still NOT unlocked. 277 non-text specs (188 masked — ~70 origin crops convertible
      via OBED_OFFLINE_MASKCROP, ~118 offset crops not — plus 89 group specs) keep the single osascript
      open/save/close fallback session alive on a substantial slide set, and that session dominates cost,
      not per-object writes. Text conversion shrinks the session body (~704→~280 specs): a modest speed
      win + a real coverage/correctness win. Deleting the pass needs offset crops + groups.
    status: pending
---

# Offline text — middle-anchor reposition (OPEN 1 reopened)

See the todos above for the actionable record. Narrative and evidence live in the two peer artifacts
(this session's scratchpad): `dh_middle_analysis.md` and `dh_middle_review.md` (+ `adv/`). Implementation
lands on `research/resizer-middle-anchor-text` (behind `OBED_OFFLINE_TEXT`, default off); this plan branch
carries the design only. The live experiment is owner-gated and enabling-by-default is an owner call.
