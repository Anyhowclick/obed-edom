# Offline-write fallback — measurements of 2026-09-23

Three measurements in one day, one instrument each, all on the full FRC deck
(`Full_Report_Card_Wall.key`, `--slides 1-129,135-143,145-155`, defaults: offline write, text
reposition and mask-crop all ON). Every throwaway hook was reverted and never committed. Scripts in
this folder; raw dumps and output decks stayed in the measuring worktree's git-ignored `output/`.

Both runs reproduced the same fallback line exactly:
`95 slides / 234 specs = text-grow-height-width 88, group-residual 83, masked-media 57, group-child-scale 6`.

## 1. Where a 22-minute run actually goes (m1 run, file mtimes; the log has no timestamps)

| stage | wall | share |
|---|---:|---:|
| planner + offline source read (cached payload) | ~1 min | |
| **pass 1: copy the 6.7 GB deck, import layouts, set 16:9 canvas, JXA scale + refont, save + close** | **~12 min** | **~55%** |
| bulk live read + offline IWA patch (148 slides) | ~4 min | ~18% |
| AppleScript fallback session (1 session, 234 specs, 95 slides) | **78.7 s** | **~6%** |
| final save + post-run | ~3 min | ~14% |

The working assumption "wall time is dominated by the fallback" was wrong. Pass 1 dominates and
nobody has profiled it. This is the lever; see §5.

## 2. Groups (`group-residual` 83) — offline_groups.plan todo 1: STOPPED

Throwaway `OBED_DUMP_SPECS` hook in the writer's group branch; 179 group specs seen, 83 missed.

| bucket | specs | slides |
|---|---:|---|
| (a) translate-only | **0** | — |
| (b) scaled, no children (uniform sx==sy, 1.06×–16.2×) | 27 | 20, 35, 36, 42, 78, 118, 124–128 |
| (c) `children` (per-child autosize writes) | 56 | 11, 17, 26, 28, 38, 40, 49, 55, 56, 60, 61, 64, 75, 77, 80–82, 92, 94, 108–110, 124–128, 149 |

Bar was (a) ≥ 20. The seeded-translate increment has nothing to write; the family is live-bound.
On slides 124–128 the live group frame differs from the offline union by up to 472×186 px, so a
scaled offline write there would build on the wrong union. Masked-media increments 2+3 in
`offline_groups.plan.md` are unaffected and still open. Classifier: `groups_spec_shape_classify.py`.

## 3. Grow-height text (`text-grow-height-width` 88) — offline_text_regrow.plan m0 + m1: bar passed, deprioritised

### m0 — offline census (`regrow_m0_census.py`, wall deck vs post-fallback deck)

| | wall | post-fallback CG |
|---|---:|---:|
| text drawables, stored w > 0 | 128 | 107 |
| h == 0 (grow-height) | 123 | 102 |
| width-fixed bit (flags & 1) on h==0 | 123/123 | 102/102 |
| h==0 with nh == 0 (half-filled cache) | 0 | 14 |

No rotation, all `bezierPathSource`, no None vertical alignment. The fallback's `height:` write
does not change box type (h stays 0), so arm A and arm B are the same kind of box. Anchor mix of
the h==0 class: **91 Middle+centre**, 11 Top (5 right, 4 left, 2 centre).

### m1 — live dump of the 88 misses (`regrow_m1_analyze.py` → `regrow_m1_analysis.txt`)

| finding | value |
|---|---|
| effective anchor from `stored.y − rep.y` | matches the style on all 88 (77 middle, 11 top) |
| role | other 82, title 5, list 1 |
| b_h = (stored.x − rep.x)/rep.w | −0.01…0.01 on every alignment: stored x IS the left edge for width-fixed boxes; pos_x needs no anchor term |
| stored.w − rep.w | ±0.4 px: size_w = spec.w |
| fallback's actual result | w == spec.w exactly; stored centre y == spec.y + nh_actual/2 (visual top == spec.y) |
| h_new via spec.h (needed for the 77 middle boxes) | within 1.5 px for 73 (dh +3.0 ×45, +0.9 ×18, +2.5 ×6, +1.5 ×4); outliers are 4 multi-line `title` slot rects (21, 31, 115, 120), 1 `list`, 3 top-anchored body boxes (y exact anyway) |
| convertible under "role other only, refuse title/list" | **84 of 88** — plan bar (≥ 60) PASSED |
| slides whose ONLY misses are grow-height | 28 slides / 49 specs |

The write is sound: `size_w = stored.w + (spec.w − rep.w)`, `natural_w = size_w`, position deltas
unchanged, and for a middle anchor `pos_y = spec.y + spec.h/2` (≤ 1.5 px centre error). But the
whole family buys ≈ 20–30 s of fallback body per run (§1), and the session survives (groups
live-bound, masked-media open). Owner decision 2026-09-23: **lower priority, not closed** — the
plan's todos stay pending; value is a smaller live-write surface, not speed.

## 4. Stale beliefs corrected today

- `OBED_OFFLINE_WRITE` / `OBED_OFFLINE_TEXT` / `OBED_OFFLINE_MASKCROP` are default-ON in code.
- The 2026-09-05 "Keynote re-shrink-wraps on open" result (c70540de3) is confounded (absolute pos_x,
  size_w on grow-both boxes, fixed-frame path) and is an unknown, not a verdict.
- "Only role `other` is the affine image" is false (body text, corner-translated text, demoted lists
  are `other` too).
- A half-filled naturalSize cache (nw > 0, nh == 0) already occurs after today's fallback (14 boxes).

## 5. Next: profile pass 1

Pass 1 (`remap_keynote.py`, the JXA/AppleScript body between "Copying … → …" and the pass-1 save)
is ~12 of 22 minutes and has never been timed stage by stage: deck copy (6.7 GB), layout import,
canvas + layout application, the 3822-item geometry/refont apply, save, close. First step is a
timestamped log line per stage (a permanent, cheap `say` with elapsed seconds), then one run.
