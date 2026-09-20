---
name: Offline groups — seeded translate + the masked-media residue
overview: >-
  2026-09-19. Closes the last offline-write fallback family. MEASURED FIRST (census:
  `.agents/reviews/groups-census-2026-09-19/` (census + scripts)). Findings that reshape the problem:
  (1) `group-residual` is ONE cause, not four — 93 of 94 groups fire only the zero-extent
  `ShapeInfoArchive` trigger, and 903 of those 935 children are AUTOSIZE TEXT BOXES with the
  `h==0.0` layout-cache sentinel, the same phantom the middle-anchor text increment cleared;
  effect-style and rotated-nested-group fire ZERO times. (2) The offline child UNION cannot be
  repaired — pass 1 zeroes `naturalSize`, and the stored group frame is a median 137px off the
  union — but `bulk_geometry.js` ALREADY reads groups live, so the anchor-cancelling delta the
  text arm shipped (`pos = stored + (spec - reported)`) makes a TRANSLATE-ONLY group write exact
  regardless of sub-cause, because the sub-causes corrupt the union, never the translation.
  (3) masked-media's 57 are NOT "rotated/cross-member, fundamental": cross-member is ZERO,
  overhang is 48 of 75, and only 7 masks are genuinely rotated. (4) The real blocker is the
  `children` (per-child autosize) spec slice, which `iwa_write._slide_edits` does not read at
  all and which needs Keynote's live relayout — its size is the ONE number the census could not
  measure offline, so todo 1 measures it before any code is written.
todos:
  - id: measure-spec-shape
    content: >-
      MEASURE BEFORE BUILDING (owner's rule). The census sized the deck structure but NOT the
      planner's spec shape, which decides everything downstream. Add an env-gated dump
      `OBED_DUMP_SPECS=<path>` in `remap_keynote` right after `transform_dicts = [t.as_dict()
      for t in transforms]` (~line 1418) writing the list as JSON; run the standard full-deck
      benchmark (`--slides 1-129,135-143,145-155`) once and classify every `kind=="group"` spec
      that the writer missed with `group-needs-keynote:group-residual` into THREE buckets:
      (a) translate-only (`w`/`h` absent or equal to the live reported size within 0.5px, no
      `children`), (b) scaled (`w`/`h` present and different, no `children`), (c) `children`
      spec (per-child autosize writes). Also record, per spec, whether a live `("group", ki)`
      seed row exists in the bulk read. PASS bar for proceeding: bucket (a) is non-trivial
      (>=20 specs). If (a) is near zero and (c) is ~all 83, STOP — the seeded-translate
      increment buys nothing and the wall-time lever is unreachable without an offline autosize
      text layout engine, which is out of scope; say so and close the family as live-bound.
      Cheap: one run, no new refusal logic, the dump is throwaway and never merged.
    status: pending
  - id: seeded-group-translate
    content: >-
      INCREMENT 1 (the main one), opt-in `OBED_OFFLINE_GROUP_SEED`, default OFF, mirroring
      `OBED_OFFLINE_MASKCROP`. Add `"group"` to `_OFFLINE_SOFT_SEED_KINDS` (offline_write.py:37)
      so a group-only slide still triggers the bulk read, and update the comment block above it
      (it currently states groups never need `reported`, which this change falsifies). In
      `iwa_write._slide_edits`' `kind == "group"` branch, BEFORE the `needs_keynote` miss:
      if the flag is on AND the spec carries no `children` AND the write is translate-only
      (spec `w`/`h` absent, or within 0.5px of `rep[2]`/`rep[3]`) AND a trustworthy seed exists
      (`have_reported` and `rep[2] > 0 and rep[3] > 0`, the same `seed_ok` gate the text path
      uses), emit `pos_x = stored[0] + (spec.x - rep[0])`, `pos_y = stored[1] + (spec.y -
      rep[1])` and NO size, NO child ops. Everything else keeps today's miss. Count it in
      `soft_fallbacks` accounting like the text path. WHY IT IS EXACT: children are stored
      parent-relative, so translating the parent frame translates the subtree verbatim; the
      union never enters the arithmetic, so a wrong union (zero-extent text child, off-axis
      mask, effect, rotated nested group) cannot reach the result. WHAT WOULD MAKE IT WRONG
      LIVE: (i) a zero-filled seed row — covered by `_drop_unreadable_seed_rows` plus the
      `seed_ok` gate; (ii) a group whose live frame is NOT the union of its children (Keynote
      re-deriving the frame on open) — that is the real risk and the live gate below is what
      tests it; (iii) a `children` spec slipping through — refused explicitly, not by accident;
      (iv) a scaled spec mis-classified as translate-only by the 0.5px test — tighten to exact
      `is None` if the live run shows any drift. Tests: seed present/absent, `children` refused,
      scaled refused, delta arithmetic, flag helper, end-to-end convert-under-flag.
    status: pending
  - id: seeded-group-live-gate
    content: >-
      LIVE VALIDATION GATE for increment 1. Subset slides 11,17,26,36,110,124 (covers the
      textbox-only sub-cause at depth 0 and 1, the 2-child and 28-child shapes, and the worst
      slide cluster) with `OBED_OFFLINE_WRITE=verify OBED_OFFLINE_GROUP_SEED=on --validate`.
      Two measurements, both required. (1) `verify_live_frames` group max delta <= 2.0px
      (`LIVE_VERIFY_TOL._default`) — NOT the offline `group` self-consistency number, which is
      meaningless here because this write never touches `compose_geometry`'s union. (2) PIXEL
      check per converted group region against the AppleScript oracle baseline for the same
      subset (the same oracle the offset-crop round used): the autosize text inside the group
      must land in the same place and at the same wrap. A group that moved correctly but whose
      text re-wrapped is a FAIL — that is precisely the failure `_child_ops_lines` exists to
      avoid. KILL: any group beyond 2px, or any re-wrapped/re-anchored text child -> keep
      groups refused, revert to the AppleScript fallback, and record the finding. Null control:
      the same subset with the flag OFF must show the same group fallback count as the
      benchmark. Expected reduction: bucket (a) from todo 1 (unknown until measured; the
      optimistic ceiling is 83 -> 0, the pessimistic floor is 83 -> 83 if everything is a
      `children` spec).
    status: pending
  - id: masked-residue-epsilon-and-snap90
    content: >-
      INCREMENT 2, independent of groups and much cheaper than it looks — the census says the
      masked-media 57 are mostly NOT rotated. Two exact, low-risk extensions to
      `_is_axis_aligned_crop`, together behind `OBED_OFFLINE_MASKCROP_EDGE` (default OFF):
      (i) an overhang EPSILON — 15 of 48 overhang cases exceed the frame by <=0.01px, pure
      float noise from Keynote's own arithmetic; admit `over <= max(0.01, 1e-6 * max(fw, fh))`.
      (ii) EXACT-90 masks — 3 cases at frame 90.0 / mask 0.0, plus 16 at 0.0357 deg and 1 at
      359.9721 deg which are visually zero; `_masked_rect` already snaps 90s and trusts these
      (displacement < 1.5px), so `_is_axis_aligned_crop`'s stricter `_is_rotated` (0.01 deg) is
      the sole thing refusing them. Admit a frame/mask angle pair whose `_snap90` displacement
      is within `_MASK_TRUST_PX`, and compose the transform through the SNAPPED angles so the
      writer and the reader agree. WHAT WOULD MAKE IT WRONG: raising the angle tolerance past
      the measured gap — do NOT touch `_MASK_TRUST_PX`, reuse it. Oracle: frame verify `image`
      max delta <= 2px PLUS the per-region pixel diff vs the AppleScript baseline, same as the
      offset-crop round. Expected reduction: masked-media 57 -> ~36 (removes 16+3+1 near-zero
      rotations and 15 epsilon-overhangs, minus double counting).
    status: pending
  - id: masked-residue-overhang
    content: >-
      INCREMENT 3, `OBED_OFFLINE_MASKCROP_OVERHANG` (requires increment 2), default OFF.
      Admit an axis-aligned mask window that extends PAST the image frame (26 genuine cases,
      worst 307px = 8.5% of frame — a letterboxed image inside a larger mask).
      `_masked_media_fields`' transform is already exact for it (image pos = target -
      mask_pos*s); the unproven bit is identical to the offset-crop unknown: how Keynote
      redistributes an overhanging crop across a reopen. So the gate is identical too — a PIXEL
      check, not a frame match. Keep `iwa_geometry.MASK_OVERHANG_TOL` (0.5) as the outer sanity
      bound; this admits only within it. WHAT WOULD MAKE IT WRONG: Keynote clamping the mask to
      the frame on open, which would silently re-crop the image — the pixel check catches it,
      a frame check would not. KILL: any region differing beyond anti-alias -> keep overhang
      refused. Expected reduction: masked-media ~36 -> ~10.
    status: pending
  - id: wall-time-lever-verdict
    content: >-
      DECIDE, with numbers, whether the AppleScript fallback pass can be deleted. The pass runs
      whenever ANY spec misses, so it dies only at fallback == 0 deck-wide. After increments
      2+3 the masked-media residue is ~7-10 GENUINELY ROTATED masks (frame 1-2 deg with a
      counter-rotated mask) — those stay refused: the composed rect is a snapped approximation
      and an offline write would bake in the lever-arm error `_MASK_TRUST_PX` exists to catch.
      So even a perfect group increment leaves ~7-10 specs and the pass SURVIVES. Deleting it
      needs a rotated-mask writer as well (compose the mask AABB through the true angles rather
      than snapped — the arithmetic is in `_mask_corner_aabb` already; the open question is
      whether the JXA frame Keynote reports for a rotated masked image is the true AABB or the
      snapped one, which the live verify can answer directly). RECOMMENDATION recorded here so
      it is not rediscovered: pursue the fallback-pass deletion only if todo 1 shows bucket (a)
      is large AND increments 2+3 pass; otherwise take the partial win (fewer fallback slides =
      a shorter pass, still ~15 min but less Keynote round-tripping) and leave the pass in
      place. Do not promote any flag to default without its own live gate.
    status: pending
---

# Offline groups — seeded translate + the masked-media residue

Actionable record in the todos above. Census of record:
`.agents/reviews/groups-census-2026-09-19/groups_census.md` (tables + reproducible scripts beside it). Canonical resizer plan:
`cg_resizer.plan.md`. The pattern this mirrors — extend an already-exact transform behind an
opt-in flag, gate it live with the right oracle, promote only on a PASS — is
`offline_text_middle_anchor.plan.md` and the mask-crop offset promotion (PR #167, shipped;
its plan is in Git history).

The one structural warning this plan carries forward: `iwa_write._slide_edits` has no notion of
a group spec's `children` list. Until todo 1 reports how large that slice is, nobody should
assume the group family is closeable at all.
