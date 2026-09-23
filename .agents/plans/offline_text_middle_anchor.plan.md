---
name: Offline text — middle-anchor reposition (COMPLETED 2026-09-21)
overview: >-
  2026-09-18. Two Fable peers in series (analysis + adversarial review) overturned the "middle-anchored
  autosize text is BLOCKED on Δh" conclusion of the 2026-09-18 handover: it was a mis-diagnosis. Middle
  text does not drift on Δh for a position-only write; the 174px that blocked it was the deck's one
  right-aligned box under the shipped absolute `pos_x`. This plan captures the corrected diagnosis, the
  reworked increment (drop the `top_anchored` refusal + a delta-form x write), the four diff bugs to fix,
  the gate rework, and the single owner-gated live experiment that confirms it. Grow-height width writes
  (c) stay behind their own flag as the only unvalidated mechanic. Wall-time lever is still NOT unlocked
  (non-text specs keep the AppleScript fallback pass alive) — this is a coverage/correctness win.
  Completed 2026-09-21 after the owner authorized the whole-deck gate and accepted subtle rendered
  differences unless materially large. The original per-class 1px experiment criterion below is
  retained as historical context; rollout evidence instead combines Keynote live verification with
  an alignment-aware, fixed 8px rendered-translation ceiling. Source artifacts: `dh_middle_analysis.md` (peer 1),
  `dh_middle_review.md` + `adv/` (peer 2). Canonical resizer plan: `cg_resizer.plan.md`.
todos:
  - id: corrected-diagnosis
    content: >-
      RECORD OF FACT (offline-evidenced, live-confirmed 2026-09-21). (1) A position-only write changes no
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
    status: completed
  - id: shipped-defects-161
    content: >-
      Two confirmed latent defects in the formerly default-OFF `OBED_OFFLINE_TEXT` path shipped by PR #161
      ("correct, live-validated" is contested). (a) `pos_x = spec.x` is absolute, but stored x is the
      anchor point: centre for centre-aligned grow-both (b=½), right edge for right-aligned (b=1). 68
      centre + 1 right box on Full_Report_Card land w/2 (or w) to the left. The right-aligned case is not
      latent — it produced the live Δ174 in `run_on_fix_validate`, so the top-only shipped path DID
      convert a box wrongly; the `nw>0` gate then hid it for an unrelated reason. (b) A grow-height box
      keeps pass-1's 0.25× canvas-scaled width under a position-only write → wrong wrap; `verify_live_frames`
      compares x/y only, so it passes a visibly wrong box. Both must be fixed regardless of the enable
      decision.
      DONE: the delta-form position defect is fixed and whole-deck/live verified. Grow-height width
      writing was not promoted; that class remains on the AppleScript fallback, while the rendered
      oracle checks wrapping for every converted label.
    status: completed
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
      DONE 2026-09-21; the default is now ON with explicit fail-closed kill switches.
    status: completed
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
    status: completed
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
    status: completed
  - id: verify-wh
    content: >-
      RESOLVED DIFFERENTLY: live `verify_live_frames` still compares text x/y only; live w/h was not
      added. Grow-height width writes remain excluded and fall back to AppleScript. The old band matcher
      was replaced by a per-label rendered oracle with independent A-null export, four-direction positive
      controls, alignment-aware A/B footprints, and a fixed 8px phase-correlation ceiling across all 339
      converted labels. This is the wrapping/render bar; the live readback remains the position bar.
    status: completed
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
      stays on AppleScript. HISTORICAL criterion: superseded by the owner's 2026-09-21 go and explicit
      acceptance of subtle visible differences. The completed whole-deck gate uses an 8px fixed rendered
      translation ceiling and measured 7px maximum, while live geometry measured under 1px in both arms.
    status: completed
  - id: wall-time-note
    content: >-
      Wall-time lever is still NOT unlocked. 277 non-text specs (188 masked — ~70 origin crops convertible
      via OBED_OFFLINE_MASKCROP, ~118 offset crops not — plus 89 group specs) keep the single osascript
      open/save/close fallback session alive on a substantial slide set, and that session dominates cost,
      not per-object writes. Text conversion shrinks the session body (~704→~280 specs): a modest speed
      win + a real coverage/correctness win. Deleting the pass needs offset crops + groups.
      CLOSED 2026-09-23 (owner): informational note, not a task; wall-time work continues in
      `pass1_profile.plan.md`.
    status: closed
---

# Offline text — middle-anchor reposition (completed 2026-09-21)

See the todos above for the actionable record. Narrative and evidence live in the two peer artifacts
(this session's scratchpad): `dh_middle_analysis.md` and `dh_middle_review.md` (+ `adv/`). Implementation
landed before the whole-deck rollout on `codex/resizer-offline-flip-gate`. `OBED_OFFLINE_TEXT` is now
default-on; explicit `off`/`0`/`false`/`no` remain the production kill switch. Final evidence and the
owner-approved acceptance bar are recorded in `cg_resizer.plan.md`.
