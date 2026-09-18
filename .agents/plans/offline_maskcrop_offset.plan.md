---
name: Offline masked-media — axis-aligned OFFSET crops
overview: >-
  2026-09-18. Extends the offline masked-media crop writer from origin-anchored to ANY
  axis-aligned crop within the frame (offset included) — the majority of real crops (~715 of
  1527 deck-wide, the biggest remaining masked-media miss and part of the wall-time lever).
  The `_masked_media_fields` transform is already exact for any axis-aligned mask
  (image pos = target - mask_pos*s); the ONLY blocker is that Keynote's redistribution of an
  OFFSET crop across a reopen is unproven (origin H/HV/V crops were live-validated in the
  prior round). So this lands behind a NEW opt-in `OBED_OFFLINE_MASKCROP_OFFSET` (requires
  `OBED_OFFLINE_MASKCROP`), pending a live experiment whose PASS bar is a PIXEL check, not just
  a frame match. Mirrors the middle-anchor text pattern (`offline_text_middle_anchor.plan.md`).
  Live runbook: this session's scratchpad `offset_crop_experiment_runbook.md`.
todos:
  - id: increment-built
    content: >-
      BUILT (branch feat/offline-maskcrop-offset). New predicate `_is_axis_aligned_crop`
      (axis-aligned mask fully within the frame at any offset; refuses rotation, overhang,
      non-finite/non-positive dims). `_masked_media_fields` gains `allow_offset_crop`; the gate
      is identity OR (allow_origin_crop AND origin) OR (allow_offset_crop AND axis-aligned). The
      transform is UNCHANGED (already exact). Flag `OBED_OFFLINE_MASKCROP_OFFSET`
      (`offline_maskcrop_offset_enabled`, requires OBED_OFFLINE_MASKCROP) plumbed
      run_offline_write -> _patch_offline_slides -> patch_deck_geometry -> _slide_edits, mirroring
      mask_crop. Default OFF. Tests: predicate, transform gating (offset written only under the
      flag, refused under origin-only), end-to-end convert-under-flag, flag helper.
    status: completed
  - id: live-experiment
    content: >-
      DONE 2026-09-18 (PASS). Subset 4,57,70,123, text off: masked fallback 6->1 (5 offset crops
      converted; the 1 left is rotated/cross-member). Frame verify image Δ0.48px PASS. PIXEL check vs
      the AppleScript oracle subset_off_validate_CG: slides 4 & 70 pixel-identical; 57 & 123 bands
      cross-correlate to best-fit shift <=1px (SAD 1.1-4.2/255) = sub-pixel edge resampling, NOT a
      wrong region. Redistribution SOUND. Evidence: run_offsetcrop.log + diff crops. Original design:
      OWNER-GATED. The unproven bit is redistribution, so the bar is a PIXEL check. Subset
      4,57,70,123 (has the 6 masked-media offset crops the middle-anchor run refused);
      `OBED_OFFLINE_WRITE=verify OBED_OFFLINE_MASKCROP=on OBED_OFFLINE_MASKCROP_OFFSET=on
      --validate` (text off, to isolate). Measure: (1) frame verify `image max Δ @2px` PASS
      (necessary, not sufficient); (2) PIXEL-diff each converted masked-image region in the run
      previews vs the AppleScript baseline `subset_off_validate_CG` (the oracle renders crops
      correctly) — PASS = no region differs beyond anti-alias; a differing region = wrong crop =
      redistribution unsound. Kill: any wrong region -> keep offset refused (revert to
      origin-only). Runbook in scratchpad `offset_crop_experiment_runbook.md`.
    status: completed
  - id: promote-if-validated
    content: >-
      If the pixel check PASSES, promote like the text arm: fold `_is_axis_aligned_crop` into
      the default `OBED_OFFLINE_MASKCROP` path and drop the offset flag (git keeps the arm).
      Then the masked-media misses shrink to rotated + cross-member masks only. Wall-time lever:
      offset crops are one half of the 277 non-text specs keeping the AppleScript fallback pass
      alive; groups (89, need live layout) are the other half — deleting the pass needs both.
    status: pending
---

# Offline masked-media — axis-aligned OFFSET crops

Actionable record in the todos above. This mirrors the middle-anchor text increment: extend an
already-exact transform behind an opt-in flag, validate live (here with a PIXEL check because
crop redistribution is the unknown), then promote to default on a PASS. Canonical resizer plan:
`cg_resizer.plan.md`.
