# opus-B review 2 — d4b piece B (steps 4–7), worktree dsk-gen @ 6106b88 + uncommitted diff

**Verdict: REVISE.** (Round-1 HIGH 1/2/3/5 and MEDIUM 7/9/10 are genuinely fixed and verified below.
Two new defects at the same severity remain: the badge reservation is wrong *in kind* and demonstrably
mis-sizes the owner's reference slide, and the new build-merge dedupe can refuse a valid deck.)

Reproduced: scoped `tests/test_dsk_{assemble,plan,live}.py` 228 passed; full suite **2172 passed / 84
skipped**. **Regression clean**: `plan_assembly` output (fits/deletes/text_sizes/shrink/ordinals/warnings)
**and the whole generated AppleScript** are byte-identical to HEAD on the 14 kept non-text slides
2,5,15,16,21,22,24,42,44,45,48,50,51,53 (HEAD `src` via `git archive`, same payload pickle, 1660-line
script, `diff` empty).

---

## THE TWO MEASUREMENTS THE ORCHESTRATOR ASKED FOR

### (a) GW 13's refusal at `--min-text-pt 66` — the doubt is correct, and the golden deck disagrees with the code

Measured (`DEFAULT_BAND`, band top 704, bottom 1054, height 350):

| | GW 13 | GW 17 | GW 38 |
|---|---|---|---|
| badge fitted rect (y, h) | 740.4, 81.5 | 704.0, 74.2 | 704.0, 47.3 |
| `bottom_cap` (badge bottom) | 821.9 | 778.2 | 751.3 |
| stack budget handed to `fit_text_stack` | **232.1** | 275.8 | 302.7 |
| reserved out of the 350 band | **117.9** | 74.2 | 47.3 |

The badge's own scaled height on GW 13 is **81.5**, so **36.4 pt of the 117.9 pt reservation is dead
space above the badge** — exactly the affine-position artefact you suspected. `_stacked_text_rects`
then lays the verse at (43, 850.8, 1849, 203.2), i.e. **band rows 704–850 are empty** while the text is
shrunk to t = 0.75 (52.5 pt from 70 pt).

What the 350 pt band actually allows for GW 13's single verse box (real PIL metrics, AzoSans-Regular,
w 1849):

```
budget 232.1 (as shipped) : with-margin t=0.75 (52.5pt)   no-margin t=0.86 (60.2pt, h 230.0)
budget 268.1 (badge pinned to band top, +10 gap) : no-margin t=1.00 (70.0pt, h 264.0)
budget 350.0 (no reservation) : t=1.00 either way
```

So on the owner's **GOOD reference slide** the current rule shrinks 70 pt text by 25 % when the correct
stacking leaves it at 70 pt untouched, and refuses outright at floor 66 (`slide 13 box 1 does not fit
the band even alone`) where a pinned badge + no per-box margin fits at t = 0.95 (3 lines × 1.157 × 66.5
+ 21 = 251.8 ≤ 268.1).

**What the golden deck does** (`Sermon_PK (DSK)_with mistakes.key`, offline payload, every verse slide):
exactly two layouts, and the badge is **never** at a fixed position —

```
2-line verse : badge y=789 h=76 (x 63)   verse y=866  h=177 (x 54, w 1838, 45pt)  -> stack 789..1043
1-line verse : badge y=882 h=76 (x 63)   verse y=967  h= 73 (x 54, w 1813, 45pt)  -> stack 882..1040
```
(slides 3, 9, 10, 11, 14, 15, 16, 17, 20, 21, 22 vs 5, 6, 7, 8.)

The badge **moves with the verse**: it sits immediately above the long box, the whole `[badge, verse]`
group is bottom-anchored to the band, and the band top is left empty. The golden never pins the badge
to the band top either — it is the *stack* that is bottom-anchored, badge included.

**The stacking rule should be:** put the short/badge row *into* the stack. Lay `[badge (at its affine
scale), long box 1, …]` bottom-anchored at `band.bottom`, with the gap between them, and give
`fit_text_stack` the **full `band.height` minus the short row's scaled height and gap** as its budget —
not `band.bottom - (affine badge bottom)`. On GW 13 that is 350 − 81.5 − 10 = 258.5 (or 268.1 without
the gap), and the verse keeps its source size.

### (b) GW 17 at t = 0.74 with the band a third empty — **not** over-charging beyond the margin

Measured, boxes `('text',1)` 79 chars and `('text',2)` 75 chars, both 70 pt AzoSans-Regular @ w 1849:

```
size 52.5 (t .75): 2 lines each, raw 142.5 + 142.5 + 10 gap = 295.0
size 51.8 (t .74): 2 + 1 lines,  raw 140.9 +  80.9 + 10     = 231.8
size 50.4 (t .72): 1 line each,  raw  79.3 +  79.3 + 10     = 168.6
```

Under the shipped 275.8 budget: **0.74 is the true ceiling without the margin; the shipped answer is
0.72.** So the margin costs 1.4 pt of glyph here — the remaining ~49 pt of idle band is **line
quantisation**, not over-charging: t = 0.75 needs 295 pt raw, which no badge-aware budget (≤ 302) can
grant on this slide. (On the bare 350 band the margin costs far more: no-margin t = **0.91** — F9's
published number, reproduced exactly — vs 0.74 with it. That is the whole of the declared "fit-t
deviation".)

**Right answer for GW 17: t = 0.74.** Getting there means charging the margin once as a *budget*
reduction rather than as an extra line inside a box (see MEDIUM 3).

---

## HIGH

### 1. The badge reservation is wrong in kind, over-charges, and can refuse a whole slide
`dsk_assemble.py:355-364` (`bottom_cap` / `reserved_height` / `stack_band`).

Three separate problems, on top of the measurements above:

- **Dead space is charged to the text.** `bottom_cap = max(rect.y + rect.h for short_fit)` charges the
  gap *above* the badge to the text budget (36.4 pt on GW 13). Fix per (a): budget =
  `band.height - (short row scaled height) - gap`, with the short row laid immediately above the stack.
- **Hard refusal at `reserved_height == 0`.** Any slide whose lowest short item's *fitted* bottom
  reaches `band.bottom` yields `reserved_height = 0` → `fit_text_stack` returns `None` at every `t`
  → split → each part also `None` → `AssemblyRefusal("… does not fit the band even alone")`. A badge
  that happens to be the lowest element kills the slide with a misleading message. GW escapes only
  because its badges are all in the upper half.
- **x-overlap is ignored.** A short item off to one side (e.g. GW 17's badge at x 714–1219) reserves
  vertical space across the full 1849 pt band width even where nothing would collide.

Fix: build the stack as `[short row, long…]`, bottom-anchored, and pass `band.height` minus the short
row's height+gap; keep an x-overlap check only as a post-condition assertion.

### 2. `_verify_builds`'s new split dedupe collapses build *multiplicity* → false refusal
`dsk_assemble.py:1683-1700`.

The dedupe is "first occurrence of a common key wins", so a source slide carrying **two identical**
builds on a repeated short item merges to **one**. Reproduced with the shipped merge logic verbatim:

```
parts each carry: BADGE x2 (common) + one long-box build
merged            : BADGE x1, LONG1 x1, LONG2 x1
```

`compare_builds` counts with a `Counter` (`iwa_builds.py:335-345`), so source BADGE = 2 vs merged 1
is reported `missing count 1`; the badge is in no part's `deletes`, so `deleted_count = 0 < 1` →
`real_missing` → `AssemblyRefusal` (`:1760`). Round-1 finding 4 traded a surplus refusal for a missing
refusal. `test_verify_builds_tolerates_badge_build_repeated_on_every_part` uses one badge build per
part, so it passes over this.

Fix: merge by count, not by first-occurrence — `Counter` each part; for a key in `common_keys` take
`max` across parts, for every other key take `sum`; rebuild `merged_builds` to those counts. Add a
two-identical-badge-builds case.

---

## MEDIUM

### 3. The +1-line margin is written into one arbitrarily-chosen box's rect
`dsk_plan.py fit_text_stack` (`heights[dominant.item_id] += _LINE_HEIGHT_FACTOR * sizes[...]`) +
`dsk_assemble.py:148-157`.

Charging once per stack (round-1 MEDIUM 6) is right, but it is charged by **inflating the dominant
box's height**, and `_stacked_text_rects` then writes that inflated height as that box's rect.
`dominant = max(boxes, key=sizes)` ties arbitrarily when every box shares a size — GW 17 (both 50.4)
gives `('text',1)` h = 137.6 and `('text',2)` h = 79.3 for two boxes whose text is the same 1 line.
One box is silently a line taller than its content, the other is not.

Fix: subtract the margin from the *budget* (`band.height - margin`) and write the un-inflated heights,
so every rect equals its own measured height and the slack is real slack. Re-derive the expected `t`
(GW 17 → 0.74 under a 275.8 budget; 0.91 on a bare band).

### 4. Split slides never set `stacked_ids`, so their long boxes fall through the generic affine loop
`dsk_assemble.py:383-407` (split branch) vs `:423` (`if iid[0] != "text" or iid in stacked_ids`).

`stacked_ids` is only assigned in the *fit* branch. On a split slide it stays empty, so the long boxes
re-enter the per-item loop. Measured on GW 17 @ `--min-text-pt 66`:

```
warnings ('slide 17 text 1 mixed run sizes', 'slide 17 text 2 mixed run sizes')
```

— spurious (the parts do write per-run sizes), plus a dead affine `plan.text_sizes` entry. The live
hazard: if such a box has `w == 0.0` or `h == 0.0` it lands in `plan.autosize[number]`, and
`_slide_lines` reads `plan.autosize` (not the part's) at `:1010`, so **the part's `set height` write is
skipped** and the stack geometry is silently dropped.

Fix: set `stacked_id_map[number] = frozenset(long_ids)` on the split path as well (or skip
`long_ids` in the generic loop whenever the boxes were resolved), and have `_slide_lines` take the
part's autosize set.

### 5. `_run_size_ranges` can leave characters at their unscaled source size
`dsk_assemble.py:163-181`.

A run with `size is None` advances `pos` but emits no range, so those characters keep the **source**
size while their neighbours are scaled by `t` — the inverse of flattening, and invisible. Same class of
risk from `_match_runs_to_items` (`iwa_runs.py:298-315`), which matches runs to items by *normalised
text*: an identical-twin mismatch would hand a box character ranges that belong to another box.

Fix: after building `ranges`, require `ranges[0][0] == 1` and `ranges[-1][1] == len(item["text"])` with
no gaps; otherwise return `None` (flat write) and warn.

### 6. No test covers the budget arithmetic that actually ships
`tests/test_dsk_plan.py test_fit_search_returns_measured_t` asserts `t17 ≈ 0.74` against the **bare
350 pt band**. The product never produces 0.74 for GW 17 — `plan_assembly` yields **0.72** because of
the badge reservation. The one number the suite pins is a number the shipping path cannot emit.

Fix: assert the plan-level result (`plan.text_sizes` / `plan.run_sizes` scale for GW 13 and 17 under
`DEFAULT_BAND`), and assert the stack budget itself, so finding 1's change has to be re-blessed.

---

## NITS

7. `--text-fit shrink` still flattens a stacked mixed-run box to `max(run size)` (declared). It is the
   one path that contradicts "source gives style"; scaling the run ranges by the shrink factor would
   cost two lines. Also: for a *uniform*-run stacked box there is no `shrink_text_sizes` entry at all,
   so `shrink` writes the same fitted size as `warn` — the flag is inert there.
8. Overflow read-back for a split slide logs the badge once per part with the same
   `(number, "text:0")` key — downstream cannot tell the parts apart. Key it by ordinal.
9. `fit_text_stack`'s floor fix leaks across boxes: `min_size = min(min_text_pt, min(box.size ...))`
   lowers the floor for **every** box in the stack, so a 100 pt box stacked with a 20 pt one may be
   driven to 20 pt under a 24 pt floor. Per-box floor (`max(min_text_pt, ...)` applied per box) is
   what was meant.
10. `_build_font_index` opens every file in three font dirs through `ImageFont.truetype` on first use
    (~hundreds of opens, cached thereafter); and for a `.ttc` only face 0 is named, so sibling faces
    resolve by stem only. Acceptable, worth a line in the plan.
11. Golden inset differs from `DEFAULT_BAND`: golden verse x 54 / w ≈ 1838 and badge x 63, vs the
    written x 43 / w 1849. The live path reads the band from the reference deck, so this may be moot —
    but it is worth confirming with the owner that the verse should run the full band width.
12. AppleScript `characters i thru j of object text` is assumed to index the same string as
    `storage.text` (newlines included). Unverified offline; belongs in the live gate.
13. Round-1 nits 13/14/16 deferred as declared — `test_wrapped_height_matches_golden_boxes` still
    reads the **GW** deck, not the golden, and the docstrings on `wrapped_height` / `fit_text_stack` /
    `_stacked_text_rects` / `_filter_kept_items` remain 3–5 lines against the ≤2-line rule.

---

## Round-1 findings verified fixed

- **HIGH 1 (flattening)** — per-run character-range writes emitted and correct. GW 17 @ t = 1.0 writes
  `characters 1 thru 3 → 70`, `21 thru 30 → 85`, … : the 85 pt emphasis run survives. Ranges cover the
  full 79/75-char strings.
- **HIGH 2 (badge overlap)** — no overlap anywhere now. Clearances (stacked top − badge bottom):
  GW 13 **+28.9**, GW 17 **+48.9**, GW 38 **+2.3**. Test added and it is a real assertion (stacked vs
  *every* non-stacked rect).
- **HIGH 3 (overflow read-back)** — `item_id in stacked_ids_here` added to the guard; `OVERFLOW … text:1`
  and `text:2` confirmed present in generated scripts for both stacked and split boxes.
- **HIGH 5 (split ordinals)** — `_restore_stroke` uses `plan.ordinal_to_number` and derives
  `part = ordinal - plan.ordinals[number]`; `_staged_retained_ids(…, part=)` reads the part's own
  fits/deletes (verified: GW 17 part 1 keeps `('text',2)` and correctly ranks it to staged
  `('text',1)`); `verify_staged_layouts_alpha_safe` iterates `ordinal_to_number`.
- **MEDIUM 7 (floor at t = 1)** — no longer refuses at t = 1.0 (but see nit 9).
- **MEDIUM 9/10** — `getname()`-first index with `.ttc` added; single gap constant
  (`_TEXT_STACK_GAP = _TEXT_GAP_PT`).
- **Nit 11** — `test_split_script_duplicates_two_split_slides_in_descending_order` added and it is a
  real assertion. Independently reproduced with a synthetic 4-slide plan, parts {9:2, 20:3}:
  emits `duplicate slide 4 / duplicate slide 4 / duplicate slide 2`, and the final deck lands
  `{1:5, 2:9, 3:9, 4:13, 5:20, 6:20, 7:20}` = `plan.ordinal_to_number`. Base-layout assignment uses
  pre-duplication ordinals and precedes the duplicates, so duplicates inherit it.
- **Nits 12 / 15** — dead assert replaced; test imports merged.
- Per-part `deletes` still leave exactly one long box per part and keep every short item (verified on
  GW 17: part 0 deletes `text 2`, part 1 deletes `text 1`, both keep `text 0` + `shape 0`).
