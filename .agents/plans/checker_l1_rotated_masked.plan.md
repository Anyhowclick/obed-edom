---
name: L1 — rotated-masked accuracy guard (flag the flip/compound case, trust the rest)
overview: >-
  v2 step-3 reframed lever L1. Today `iwa_geometry._masked_rect` flags EVERY masked
  image whose frame or mask carries any rotation > 0.1° as `rotated-masked`
  (needs_keynote) — a CATEGORY guard. Measurement (Keynote-free, cache oracles,
  2026-08-31) shows the guard cries wolf: on DSK 25/27, on FULL 3/10 rotated-masked
  images are offline-EXACT (≤0.5px) — the residual only appears in the genuine
  off-axis / compound-flip case. Replace the category flag with an ACCURACY flag:
  snap each angle to its nearest 90° multiple; when both residuals are ≤ EPS the
  snapped composition is integer-exact, so TRUST it (no flag); only a real off-axis
  residual falls back. DSK checker image-fallback 27→2, FULL 10→7. iwa_geometry is
  SHARED with the resizer, so this lands behind a resizer gold-deck plan-equivalence
  gate proving the change is plan-neutral on the Map + Full gold decks.
todos:
  - id: gate
    content: >-
      DONE (uncommitted). Promoted the scratchpad `validate_remap_plan.py` diagnostic
      into COMMITTED-quality tests in `tests/test_offline_inspect.py`: refactored the
      MAP gate into `_assert_two_tier_gate_green(deck)` and added
      `..._full_deck` (FULL carries the rotated-masked images MAP lacks → THIS is the
      resizer plan-neutrality gate for L1) + `test_l1_cleared_rotated_masked_images_are_
      write_safe` (parametrized map/full: every VOUCHED masked image ≤2px vs the cached
      JXA oracle — the "cleared ⇒ write-safe" property). All local-only (skipif),
      Keynote-free. Two-tier gate proves L1 is plan-neutral for the resizer (images are
      BULK_KINDS → bulk overwrites geometry); the cleared-accuracy test is what proves
      L1's own correctness. 4 gate/accuracy tests pass. status: completed
    status: completed
  - id: rule
    content: >-
      DONE (uncommitted). `iwa_geometry._masked_rect` now composes the mask box at
      angles SNAPPED to nearest 90° (`round(a/90)*90`) and gates on DISPLACEMENT (not
      an angle threshold — error is offset×sin(residual), so a 1° residual on a long
      lever arm misses by px). `d` = top-left distance between snapped and raw
      compositions; vouch (no flag) iff `d <= _MASK_TRUST_PX` (1.5). `d` is a rigorous
      upper bound on the error. Subsumes the old `_MASK_ANGLE_EPS=0.1` axis-aligned
      branch (snap 0→0 = `(fx+mx,fy+my)`). Unit tests updated: an exact-90 mask is now
      VOUCHED; a displacement (not angle) lever-arm test. status: completed
    status: completed
  - id: verify
    content: >-
      DONE. Peer verdict SOUND-WITH-FOLLOWUPS, all 3 addressed: (1) the cleared-accuracy
      test now asserts ≥1 OFF-AXIS mask is vouched on FULL (else a flag-every-rotated
      regression stays green — peer found 19 such, incl. genuine new clears sl15/sl61);
      (2) corrected the "rigorous upper bound" claim to `displacement + ~0.5px integer
      rounding` (measured counterexample sl61: err 1.56 > disp 1.48; ~0.44px headroom,
      threshold must not be raised); (3) parametrized skip is now per-deck not FULL-only.
      Self-verify: full suite 523 passed, 1 xfailed (pure-offline gate), Keynote never
      opened; no VOUCHED leak (rotated-masked stays out of VOUCHED_NEEDS_KEYNOTE);
      INSPECT_VERSION unchanged. Peer confirmed the two-tier gate is trivially green
      w.r.t. L1's math (bulk overwrites images) — it guards the resizer plan/splice
      bookkeeping; the cleared-accuracy test is what proves L1's composition. NOT
      COMMITTED (user hold).
    status: completed
isProject: false
---

# L1 — rotated-masked accuracy guard

Parent plan: `.agents/plans/checker_offline_geometry_v2.plan.md` (step-3 reframed,
lever L1). Read the SKILL "Reading a `.key` offline (IWA)" masked-image section and
`iwa_geometry.py` module docstring first.

## The problem: a category guard that cries wolf

`iwa_geometry._masked_rect` composes a masked image's visible box as the mask
rectangle mapped mask-local → image-local → slide. Axis-aligned (both angles within
`_MASK_ANGLE_EPS=0.1°` of 0) it collapses to `(fx+mx, fy+my, mw, mh)` — exact. ANY
rotation above 0.1° on either the frame or the mask takes the rotated corner-AABB
branch and is flagged `rotated-masked` (needs_keynote) unconditionally — a guard on
the CATEGORY "is rotated", not on the actual error.

## Measurement (Keynote-free, cache oracles, 2026-08-31)

`scratchpad/l1_measure{,2,3}.py`. For every image flagged `rotated-masked`, composed
position vs the cached exact-bytes JXA oracle, plus the raw frame/mask angles:

| Deck | rotated-masked | composed err distribution |
|---|---|---|
| DSK  | 27 | 24 at exactly 180°/180° → **0.4px**; sl2 (358/2) 6.9px; sl17 (357/357) **95px** |
| FULL | 10 | sl151-153 at 90°/0° → **0.4-0.5px**; 7 near-0-residual (1-2°) → 1.6-36px |
| GW   | 4  | all near-0-residual (2°/358°) → 0.5-9.4px |
| MAP  | 0  | — |

The signal is clean once you look at the angle *residual from the nearest 90°
multiple*: images sitting at an EXACT 90-multiple (0/90/180/270) compose to
integer-exact geometry (Keynote lays them out at that clean rotation, and sin/cos of
a 90-multiple are exact 0/±1). The error appears only when frame/mask carry a small
OFF-axis residual (1-3°) — there the corner-AABB applies a rotation Keynote did NOT,
and the error scales with the mask offset's lever arm (sl29: 2° × large offset =
36px; sl17's 357/357 compounds to net -6° → 95px). **DSK slide 17 — the DSK17
ordering-bug image — is exactly this: a flip encoded as frame357+mask357.**

## The rule: displacement-gated snap-to-90 (NOT an angle threshold)

An angle threshold is unsafe: the composition error is `offset × sin(residual)`, so a
1° residual on a long lever arm still misses by px (FULL sl23/40/52: 1° residual, 3-5px
error). The right signal is DISPLACEMENT. For a masked image, compose the mask box at
the angles SNAPPED to their nearest 90° multiple (the clean rotation JXA lays a masked
image out at) AND at the RAW angles; let `d` = the top-left distance between the two.

- **`d ≤ _MASK_TRUST_PX` (1.5):** return the SNAPPED composition, `needs_keynote=None`
  (vouched). At snapped-0/0 this IS today's `(fx+mx, fy+my)` axis-aligned formula.
- **`d > 1.5`:** still return the snapped composition (best-effort, unused) but flag
  `rotated-masked` → falls back to the bulk/legacy Keynote read.

`d` **bounds the error up to integer rounding**: JXA lays the image out at either the
snapped rotation (error≈0) or the raw one (our snapped value is `d` from it), and both
sides round to whole points, so error_vs_JXA ≤ `d + ~0.5px` whatever the offset (an
angle threshold gives no such bound). 1.5 sits in a wide MEASURED gap (accurate cases
≤1.48px, wrong cases ≥2.45px); with the rounding term the worst vouched case measured
1.56px, ~0.44px under the 2px write tolerance — so do NOT raise the threshold.

### Result (measured on the modified code, `scratchpad/l1_verify.py`)

| Deck | rotated-masked before | flagged after | cleared, max err vs JXA |
|---|---|---|---|
| DSK  | 27 | **2** (sl2 d=3.5, sl17 d=94.8) | ≤0.48px |
| GW   | 4  | 2  | ≤1.20px |
| FULL | 10 | 5  | ≤1.56px |
| MAP  | 0  | 0  | ≤0.50px |

DSK checker image-fallback **27→2** (the memory's "27→~2"). Every VOUCHED masked image
(incl. axis-aligned ones) is within 1.56px of JXA across all four decks — zero
cleared-but-wrong. GW/FULL clear MORE than an angle rule would (displacement correctly
trusts accurate small-residual images), and still flag every genuinely-off case.

## Why it is safe for the SHARED resizer, and what the gate proves

`iwa_geometry` feeds both the checker and the resizer, so the flag/value change must
not move the resizer's remap plan. Two facts bound the blast radius:

1. **`image` ∈ `BULK_KINDS`.** In the production two-tier read
   (`two_tier_wall_payload`) every masked image's geometry is OVERWRITTEN by the bulk
   Keynote read, and after the splice the `rotated-masked` guard reason is CLEARED
   (`GEOMETRY_GUARD_REASONS`). So with full bulk, whether L1 flags 27 or 2 images, the
   spliced payload — and therefore the remap plan — is byte-identical. The FULL-deck
   gate (`gate` todo) locks this.
2. **`rotated-masked` stays UNVOUCHED.** A CLEARED image is not "vouched needs_keynote";
   it simply carries `needs_keynote=None` like any axis-aligned mask, because its
   snapped composition is exact. The new risk L1 introduces is only in the paths that
   TRUST an unflagged image without a bulk read: the tier-1 guard (`offline_wall_payload`
   → `unvouched_items`) and any future slim-bulk that drops `image` from `BULK_KINDS`.
   The gate's accuracy assertion (cleared ⇒ ≤2px vs JXA) is exactly the proof those
   paths need.

The existing MAP gate cannot regress: MAP has 0 rotated-masked images.

## Residual risk

A masked image genuinely rotated to ~1° off a 90-multiple (deliberate near-90°
rotation plus a degree) would snap-and-trust with a small composed error that a large
lever arm could push over 2px. None occur on the four measured decks (max cleared
0.48px). Mitigations: EPS is small (1°); the change only touches masked images (a
minority class); and the gate's cleared-accuracy assertion is the backstop that would
catch such a case on any deck under test. Documented, accepted — the per-run
structural guard still protects untested decks (any item the offline read cannot vouch
falls back).

## Non-goals / deferred

- Slim-bulk (dropping `image` from `BULK_KINDS`) is a SEPARATE lever; L1 only makes it
  non-fatal. Not in this plan.
- Improving the best-effort value of FLAGGED images (snap-then-flag would give sl17
  0.9px instead of 95px) is unnecessary — flagged items fall back and the value is
  unused. Optional, noted, not done.
- INSPECT_VERSION stays 4: the payload SHAPE is unchanged (same fields); only a
  geometry value and a flag change, both already part of the v4 contract.
