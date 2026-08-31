---
name: L2a — masked-child group union (propagate L1's snap into groups)
overview: >-
  Bounded slice of v2 step-3 lever L2. Measurement (2026-08-31) showed the parent
  plan's "L2 shrinks for free after L1" was wrong: of the group-residual flags, the
  masked-child branch (MAP 6, FULL 7) was 0/13 within 2px — genuinely inaccurate, NOT
  free. BUT a probe showed 12/13 come within 2px once the group union composes the
  masked child through L1's SNAPPED two-stage transform (the union used a raw single
  transform that ignored the mask angle). So L2a = propagate L1 into `_leaf_bbox` +
  gate the group's masked-child residual on the SAME displacement as a top-level masked
  image. Result: group-residual MAP 53→47, FULL 100→94 (12 groups vouched with accurate
  geometry; the 1 genuine off-axis FULL group stays flagged). The dominant
  zero-size-shape branch (140 groups, half genuinely wrong to 3880px) is the HARD L2b,
  deferred. iwa_geometry is resizer-SHARED → lands behind the same gold-deck gate.
todos:
  - id: leaf
    content: >-
      `_leaf_bbox` masked-child branch: compose the mask rect through the SAME snapped
      two-stage transform as `_masked_rect` (mask-local→image-local→slide, both angles
      snapped to nearest 90°) and take the full AABB, replacing the old single
      `_frame_transform(x+mx,y+my,mw,mh,angle)` that ignored the mask angle. Factored a
      shared `_mask_corner_aabb` (full AABB) + `_snap90`; `_masked_rect` reuses them.
      Axis-aligned children unchanged (snap 0→0 = the old formula). status: completed
    status: completed
  - id: residual-gate
    content: >-
      `_group_residual_reason` masked-child branch: replace the category test
      (`_is_rotated(cangle) or _is_rotated(mangle)`) with the displacement gate — reuse
      `_masked_rect(...)`'s `rotated` flag so the group decision and the leaf
      composition never diverge. A near-90 masked child no longer forces fallback; a far
      off-axis one (>_MASK_TRUST_PX) still does. status: completed
    status: completed
  - id: gate
    content: >-
      Reuse the L1 gold-deck gate (`_assert_two_tier_gate_green` MAP+FULL) — group ∈
      BULK_KINDS so the bulk splice overwrites group geometry → plan-neutral for the
      resizer whether L2a flags or vouches. Add `test_l2a_cleared_masked_child_groups_
      are_write_safe` (map/full): every VOUCHED group whose subtree has a masked child
      is ≤2px vs JXA, and ≥1 has an OFF-AXIS masked child (else a flag-every-rotated
      regression stays green). Measured: MAP 138 such vouched groups (6 off-axis), FULL
      294 (6 off-axis), 0 over 2px. status: completed
    status: completed
  - id: verify
    content: >-
      DONE. 2 INDEPENDENT peers (I was the implementer — per the 2+1+2 preference that
      should have been a sub-agent, so I could not be a neutral reviewer; noted +
      memory updated). Peer 1 (correctness) SOUND: no regression (0 groups crossed
      ≤2px→>2px on either gold deck), full-AABB is the right union primitive, tests
      non-vacuous. Peer 2 (safety) SOUND: plan-neutral for the resizer (group∈BULK_KINDS,
      splice overwrites), and — the key check — ZERO role flips on the 12 vouched groups
      (~48px clear of PIN_KIND_MAX). Findings addressed: role-parity assertion added to
      the L2a test (is_pin/is_map offline==JXA); defensive empty-mask guard in
      _masked_rect; max-corner==top-left displacement note (measured 0.00px spread);
      test/plan comments. Full suite 526 passed, 1 xfailed; Keynote never opened.
    status: completed
isProject: false
---

# L2a — masked-child group union

Parent: `.agents/plans/checker_offline_geometry_v2.plan.md` (lever L2) and the L1 plan
`.agents/plans/checker_l1_rotated_masked.plan.md` (same displacement mechanism).

## Why this is NOT "free after L1" (the measurement that corrected the plan)

Group-residual flags today, by first-firing branch, with true error vs the JXA oracle:

| branch | MAP | FULL | accurate (≤2px)? |
|---|---|---|---|
| `rotated-masked-child` | 6 | 7 | 0/13 as-is — but **12/13 ≤2px** once the union snaps the child |
| `zero-size-shape` | 47 | 93 | MAP 18/47, FULL 53/93 — tangled with real 3880px errors → L2b, deferred |

The masked-child groups were genuinely inaccurate because `_group_union`→`_leaf_bbox`
composed a masked child with a RAW single transform that dropped the mask angle. L1's
insight (snap frame+mask to the nearest 90° multiple, the clean layout JXA reports)
applies one level down: snapping the child makes the union accurate for the near-90
majority, and the displacement gate flags only the genuine off-axis child.

## The change (mirrors L1 exactly)

- `_leaf_bbox`: masked child → `_mask_corner_aabb(x,y,w,h,snap(angle), mx,my,mw,mh,
  snap(ma))` (full AABB, snapped two-stage). Non-masked leaves untouched.
- `_group_residual_reason`: masked child → flag iff `_masked_rect(...)` returns
  `rotated` (displacement > `_MASK_TRUST_PX`). One source of truth with the top-level
  image guard.

## Result (measured on the modified code)

- group-residual: **MAP 53→47, FULL 100→94** — 12 groups vouched (MAP 6, FULL 6), the
  1 genuine off-axis FULL group stays flagged (slide 42 group[0]: 7px from JXA; its
  offline value also shifts ~122px vs the pre-L2a composition — irrelevant, it falls back).
- Vouched masked-child groups within 2px: MAP 138/138, FULL 294/294. Zero regressions.

## Safety (same as L1)

`group ∈ BULK_KINDS` → the two-tier bulk splice overwrites group geometry, so L2a is
plan-neutral for the resizer today (the FULL gold-deck gate proves it). The new value
is fewer groups forced to fall back (12), and an accurate offline group frame — the
`cleared ⇒ write-safe` property a future slim-bulk relies on, locked by the L2a
cleared-accuracy test. `group-residual` stays UNVOUCHED (a still-flagged group falls
back). INSPECT_VERSION unchanged.

## Deferred: L2b (the hard part)

The `zero-size-shape` branch (140 groups) needs a real per-group uncertainty model
(and the text shaper for autosize-text children) to separate the accurate half from the
3880px-wrong half. Not a bounded slice — its own plan.
