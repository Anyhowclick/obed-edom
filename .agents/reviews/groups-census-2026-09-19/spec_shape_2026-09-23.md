# Group spec shape — offline_groups.plan todo 1 (measured 2026-09-23)

One full-deck benchmark run (`--slides 1-129,135-143,145-155`, defaults: offline write, text
reposition and mask-crop all ON) with a throwaway `OBED_DUMP_SPECS` hook in
`iwa_write._slide_edits`' group branch (reverted, never committed). Wall 09:20 → 09:42 (22 min).
Dump + classifier: `output/groups-measure/` in the measuring worktree; classifier copied here as
`spec_shape_classify.py`.

Fallback line reproduced the 2026-09-19 baseline exactly:
`text-grow-height-width 88, group-needs-keynote:group-residual 83, masked-media 57, group-child-scale 6`
(95 slides / 234 specs).

## Buckets (the 83 `group-residual` misses)

| Bucket | Specs | Slides |
|---|---:|---|
| (a) translate-only (`w`/`h` absent or within 0.5px of the union) | **0** | — |
| (b) scaled, no `children` (uniform sx==sy, 1.06×–16.2×) | 27 | 20, 35, 36, 42, 78, 118, 124–128 |
| (c) `children` spec (per-child autosize writes) | 56 | 11, 17, 26, 28, 38, 40, 49, 55, 56, 60, 61, 64, 75, 77, 80–82, 92, 94, 108–110, 124–128, 149 |

Seed rows: 62/83 had a live `("group", ki)` row (their slide carried a text spec, so the bulk
read ran); 21 did not. Irrelevant given (a) = 0.

Side finding on bucket (b): on slides 124–128 the live-reported group frame differs from the
offline composed union by up to 472×186 px (the zero-extent autosize-text-child cause from the
census). Any offline scaled write there would be built on the wrong union.

## Verdict: STOP (plan's own bar)

The pass bar was (a) ≥ 20. It is 0: every residual group is either a scaled write (needs the
union the census showed is wrong) or a per-child autosize write (needs Keynote's text layout).
The seeded-translate increment (`OBED_OFFLINE_GROUP_SEED`) and its live gate buy nothing and
are closed unbuilt. The groups family is live-bound; the AppleScript fallback pass survives.

Increments 2 and 3 (masked-media epsilon / snap-90 / overhang) are independent of this and
remain open. Note the largest fallback family is now `text-grow-height-width` (88), the unbuilt
`OBED_OFFLINE_TEXT_REGROW` width write — a bigger lever than either.
