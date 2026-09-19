# Groups census — the last offline-write fallback family (2026-09-19)

READ-ONLY measurement. No Keynote, no osascript, no repo edit.

## Inputs

| What | Path |
|---|---|
| Source wall deck | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key` |
| Last full-deck output (post-pass-1 + AppleScript fallback) | `~/Desktop/Full_Report_Card_offline_CG.key` |
| Benchmark log | `~/Desktop/textrepos-run/run_fulldeck.log` lines 175–177 |
| Slide range | `1-129,135-143,145-155` (the benchmark's `--slides`) |

Log baseline to beat: fallback **146 specs / 67 slides** =
`group-needs-keynote:group-residual` **83**, `masked-media` **57**, `group-child-scale` **6**.

## Scripts (all in this scratchpad; run from the worktree with `uv run python <script> <deck.key>`)

| Script | What it produces |
|---|---|
| `group_census.py` | `census_wall.json` — per-group `needs_keynote` + every `_group_residual_reason` trigger fired (no early return), child kinds, nesting depth, plus a top-level masked-media dump |
| `residual_classify.py` | classifies the residual groups by sub-cause (reads `census_wall.json`) |
| `union_compare.py` | stored group frame vs `_group_union` vs a union that admits autosize text children via `_autosize_rect` → `union_compare.json` |
| `masked_census.py` | masked image/movie refusal breakdown (rotated / overhang / cross-member) against the CURRENT `_is_identity_mask` + `_is_axis_aligned_crop` gates |
| `overhang_census.py` | overhang magnitude distribution |

---

## 1. Group-residual sub-causes

Source deck, in-range slides: **190 groups**, of which **94 `group-residual`**, 96 clean.
Zero `rotated-group` (no group on the deck carries a non-zero angle).

| Sub-cause fired | Groups | Share |
|---|---:|---:|
| zero-extent `TSWP.ShapeInfoArchive` child, **text boxes only** | **85** | 90.4% |
| zero-extent `TSWP.ShapeInfoArchive` child, **non-textbox only** (h=0 rules) | **8** | 8.5% |
| off-axis masked child | **1** | 1.1% |
| `_has_effect_style` (shadow/reflection) | **0** | — |
| rotated nested group | **0** | — |
| more than one sub-cause on the same group | **0** | — |

**No group fires two sub-causes.** The family is effectively one cause.

### 1a. What the zero-extent children actually are

935 zero-extent `ShapeInfoArchive` children across the 94 groups:

| | count | shape of the record |
|---|---:|---|
| `isTextBox=True` | **903** | `w` often >0, **`h == 0.0` always**, `naturalSize.height > 0` on all 903 |
| `isTextBox=False` | **32** | `w = 1317.48`, `h = 0.0`, `naturalSize = (1317.48, 0.0)` — genuine zero-height rules/divider lines |

All 935 carry a `bezierPathSource`. **None is a connector.** The comment in
`_group_residual_reason` ("zero-size connector") is a misnomer: 96.6% of them are
**autosize text boxes with the `h == 0.0` layout-cache sentinel** — the *same phantom class*
the middle-anchor text increment cleared (`.agents/plans/offline_text_middle_anchor.plan.md`).
In the SOURCE deck their `naturalSize.height` is still populated; pass 1 zeroes it, which is why
an offline-only union reconstruction cannot rely on it (see §2).

### 1b. The 8 non-textbox groups and the 1 off-axis group

| slides | ki | group |
|---|---|---|
| 19, 20 | 0, 1 | backdrop image + one 1317×0 rule |
| 35, 36 | 0, 1 | 21 images + 7 rules (28 children) |
| 42 | 0 | single image child, frame angle 357°, mask angle 3° → `_masked_rect` displacement > 1.5px |

### 1c. Nesting depth and child kinds (residual groups)

depth 0: 73 · depth 1: 21 (no group deeper than one nested level).
Children across the 94: `ShapeInfoArchive` 972, `ImageArchive` 123, `GroupArchive` 21.
Child count: 2 children → 56 groups; 4 → 20; 3 → 3; 5 → 2; 1 → 1; and four big groups each at 28 / 85 / 113.

### 1d. Per-slide distribution

| slide | residual groups (census) | log fallback specs |
|---|---:|---:|
| 127 | 11 | 9 |
| 126 | 10 | 8 |
| 128 | 10 | 8 |
| 124 | 8 | 8 |
| 125 | 8 | 6 (+6 `group-child-scale`) |
| 36 | 6 (4 text + 2 rule) | 6 |
| 110 | 3 | — |
| 11, 17, 19, 20, 26, 35, 40, 61, 75, 109 | 2 each | 2 on 11/17/26 |
| 28, 38, 42, 49, 55, 56, 60, 64, 77, 78, 80, 81, 82, 92, 94, 108, 118, 149 | 1 each | — |

### 1e. Cross-check against the log: 94 (census) vs 83 (log) — reconciled

The census counts **groups present in the source deck**; the log counts **planner specs that
reached the offline writer**. The census is ≥ the log on every worst slide and never below it.
The 11-group gap is accounted for by groups that never receive a geometry-bearing spec: hide-role
groups, groups on slides the planner left alone, and groups whose spec carries no `w/h/x/y`
(`_spec_bears_geometry` False). The ordering of the worst slides matches exactly.
**Conclusion: same population, census is a safe upper bound. Proceed.**

---

## 2. Why the refusal exists, and how wrong the union is

`_compose_record` gives a group `x/y/w/h` = `_group_union` (AABB of children), and
`_group_fields` writes `pos = spec + (stored - union) * s`. `_is_real_box` drops every
zero-extent child from that union, so a group with a zero-height autosize text child gets a
union that is missing that child's real extent → the offset `(stored - union)` is wrong →
refuse rather than mis-write. That is the correct call given the current inputs.

Measured (source deck, 94 residual groups; `union_compare.json`):

| compare | n | max Δ | median Δ | ≤2px |
|---|---:|---:|---:|---:|
| stored group frame vs `_group_union` (real children) | 71 | 3880.9 | 137.2 | 16 |
| stored group frame vs union admitting autosize children | 94 | 3880.9 | 57.3 | 21 |
| `_group_union` vs union admitting autosize children | 71 | 552.7 | 0.0 | 48 |

Three facts fall out:

1. **The stored group frame is NOT the live frame.** Median 137px off. Using it as the anchor
   is not an option; the union model in `iwa_geometry` is right.
2. **23 of the 94 groups have NO real child at all** (`_group_union` returns `None` — every
   child is a zero-extent text box). For those `_compose_record` silently falls back to the
   stored frame, which §2.1 shows is badly wrong. These are the worst of the family.
3. Admitting autosize children into the union changes the answer for 46 of 94 groups
   (23 that had no union + 23 whose text extends past the images, up to 552px) and is a no-op
   for the other 48.

**But (2) cannot be rebuilt offline at write time.** `_autosize_rect` reads `naturalSize`, and
pass 1 zeroes `naturalSize` on every autosize box (the text increment measured 136/136).
So the offline union can never be repaired from the archive alone on the deck that is actually
being patched. **The union is a dead end; the live seed is not.**

---

## 3. The seed that is already in hand

`bulk_geometry.js` line 144 already reads `["groups", "group"]` — the bulk live read returns a
live `(x, y, w, h)` for every group, and `_reported_from_bulk_rows` already keys it as
`("group", kindIndex)`. Two things stand between that and a group write:

- `_OFFLINE_SOFT_SEED_KINDS = frozenset({"text"})` — a slide whose only seed-needing spec is a
  group does not trigger the bulk read at all (`_soft_seed_slides`).
- `_slide_edits`' group branch misses on `needs_keynote` before it ever looks at `rep`.

With the seed, a **translate-only** group write needs no union:

```
pos_x = stored[0] + (spec.x - reported[0])
pos_y = stored[1] + (spec.y - reported[1])
```

This is the exact anchor-cancelling delta the text increment shipped. It is insensitive to
*every* `group-residual` sub-cause, because those corrupt the offline **union**, never the
**translation** — children are stored parent-relative and follow the parent frame verbatim.

---

## 4. The measurement this census could NOT make (and the plan's first todo)

**How many of the 83 are translate-only vs scaled vs `children` specs.**
That lives in the planner's `transform_dicts`, which the repo never dumps and which cannot be
reproduced without a pass-1 run. What is known:

- The log says `Group child geometry: 56 group(s) hold an autosize text box and are written
  child-by-child`. `remap_keynote.py:552` puts those on `_child_ops_lines` (per-child absolute
  writes, group never written) — and `iwa_write._slide_edits` **does not read `spec["children"]`
  at all**. A `children` spec is therefore structurally un-writable offline today, and a naive
  group-level write for one would be exactly what the planner refuses.
- 85 of the 94 residual groups hold an autosize text box, so the `children` set and the
  residual set overlap heavily. 56 < 83, so a material slice of the 83 is NOT a `children` spec.
- `_child_ops_lines` sets a child WIDTH and then reads back the height Keynote derived
  (`set _ch to height of _c`). That read-back is a live autosize relayout. It is **category (c):
  genuinely needs live layout**, and no offline write can substitute for it.

Sizing the three buckets is cheap (one env-gated JSON dump on a normal run) and must precede
any code. That is todo 1 of the plan.

---

## 5. Masked-media: the 57 are NOT what the brief assumed

Same gates as shipped today (`_is_identity_mask` OR `_is_axis_aligned_crop`, offset crops now
folded into the default per `offline_maskcrop_offset.plan.md`). In-range slides only.

| deck | convertible | rotated | overhang | cross-member | total refused |
|---|---:|---:|---:|---:|---:|
| `Full_Report_Card_Wall.key` (source) | 740 | 27 | 103 | **0** | 130 |
| `Full_Report_Card_offline_CG.key` (post-run proxy) | 269 | 27 | **48** | **0** | **75** |

75 (output proxy) vs 57 (log) — same reconciliation as §1e (not every refusable object gets a
spec). Two corrections to the brief:

**(a) Cross-member masks: ZERO.** Not a cause on this deck at all.

**(b) Most of the refusals are overhang, not rotation** (48 of 75). And the 27 "rotated" are
mostly not rotated in any meaningful sense:

| (frame angle, mask angle) | n | verdict |
|---|---:|---|
| (0.0357°, 0°) | 16 | float noise; visually zero. `_masked_rect`'s 1.5px displacement gate accepts it; `_is_rotated`'s 0.01° gate refuses it |
| (90°, 0°) | 3 | exact quarter turn — `_snap90` handles it; the transform is exact |
| (359.9721°, 0°) | 1 | float noise |
| (1°, 359°) / (358°, 2°) / (2°, 358°) / (359°, 1°) | 7 | **genuinely rotated** |

So the genuinely-rotated masked-media residue is **7**, not 57.

Overhang magnitude (48 cases, output deck):

| bucket | n |
|---|---:|
| ≤ 0.01px (float noise) | 15 |
| ≤ 0.5px | 16 |
| ≤ 2px | 18 |
| > 10px (genuine letterbox, worst 307px = 8.5% of frame) | 26 |

`_masked_media_fields`' transform (`image pos = target - mask_pos*s`) is arithmetically exact for
an axis-aligned overhanging mask too — the overhang refusal is precautionary, and the unknown is
the same one the offset-crop round settled: Keynote's redistribution across a reopen. Same
PIXEL-check oracle applies.

**Bottom line for the wall-time lever:** masked-media is reducible from ~57 to roughly
**7 (genuinely rotated)** by three cheap, independent, already-exact extensions
(≤0.01px epsilon, exact-90° snap, in-plane overhang). It is no longer the family that blocks the
lever — groups are, and specifically the `children` slice of them.
