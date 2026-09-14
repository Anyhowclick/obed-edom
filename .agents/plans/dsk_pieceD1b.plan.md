# Piece D1b — two-column band for "point heading + verse" slides

Status: planned (read-only design pass, 2026-09-13). Extends `.agents/plans/dsk_pieceD.plan.md` (Design A) and `dsk_content_rules.plan.md`. Code under change: `src/obed_edom/dsk_assemble.py` (`plan_assembly` text-slide branch) plus a small helper in `src/obed_edom/dsk_plan.py`.

## 1. The problem today

On a GW slide that carries **both** a point heading (the big `ArgentCF-Bold` short text plus its numbered circle) **and** a verse, `plan_assembly` puts the heading into `short_fit`, so `short_row_h` becomes the heading's affine-fitted height and the verse stack band collapses. Measured on the real GW deck at `HEAD e7c46f1` with `DEFAULT_BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)` (top 704, width 1849):

| GW | today's outcome | `short_row_h` | verse budget | verse size |
|---|---|---|---|---|
| 44 | **refuses** — "grouped verse text does not fit the band at --min-text-pt 24.0 -- refusing to split text inside a group" | — | 78.0 pt | — |
| 50 | **refuses** — same message | 246.6 | 93.4 pt | — |
| 51 | "succeeds" badly: heading 229.9 pt / 246.6 tall, verse crushed into a 93.4 pt strip at **34.3 pt** | 246.6 | 93.4 | 34.3 |
| 52 | heading 229.9 pt, verse strip | 246.6 | 93.4 | — |
| 53 | heading 137.7 pt / 170.3 tall, verse at t=0.74 | 170.3 | 169.7 | 51.8–62.9 |
| 46 | heading 178.2 pt / 191.2 tall, verse at t=0.40 | 191.2 | 148.8 | 28–34 |

The gold deck says this vertical stack is wrong: the band is **two columns**.

## 2. Measured gold-deck numbers

Gold deck: `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key`, 43 slides, read with `obed_edom.offline_inspect.offline_wall_payload`. Mapping to GW by verse text:

| gold | GW | heading | verse |
|---|---|---|---|
| 29 | 44 | "Praise and Worship" | 2 Kings 3:15 |
| 30 | 46 | "Prayer" | James 5:16 |
| 34 | 50 | "Your Faith" (GW says "Faith" — injected typo) | Luke 5:17 |
| 35 / 36 / 37 | 51 / 52 / 53 | **heading dropped by the owner** | Luke 5:18 / 19 / 20 |
| 39–42 | 56/57/… | heading-only, single centred column | — |

### Gold two-column geometry (raw, rounded to whole pt by the offline reader)

**gold 29 (GW 44)**
- heading `text[0]` x=80 y=906 w=375 h=138, **60.0 pt** ArgentCF-Bold, colour `[65535,64507,0]` — 2 lines
- number badge `group[0]` x=**245** y=866 **w=46 h=46**
- verse badge `shape[0]`/`text[1]` "2 Kings 3" x=506 y=855 w=243 h=69, 40.0 pt AzoSans-Bold, cyan `[0,65021,65535]`
- verse `text[1]` x=**502** y=912 w=1300 h=125, **45.0 pt** AzoSans-Regular

**gold 30 (GW 46)**
- heading `text[2]` x=80 y=894 w=375 h=104, **80.0 pt** — 1 line
- number badge `group[0]` x=**245** y=866 **w=46 h=46**
- verse badge "James 5 (MSG)" x=505 y=855 w=332 h=69, 40.0 pt
- verse `text[0]` x=**501** y=912 w=1370 h=125, **45.0 pt**

**gold 34 (GW 50)**
- heading `text[0]` x=112 y=891 w=312 h=104, **80.0 pt** — 1 line
- number badge `group[0]` x=**245** y=824 **w=46 h=46**
- verse badge "Luke 5" x=505 y=793 w=332 h=69, 35.0 pt
- verse `text[1]` x=**501** y=841 w=1370 h=205, **40.0 pt**
- content anchor `image[0]` "4 lines.png" x=26 y=788 w=1867 h=267

**gold 39–42 (heading-only)** — heading 60.0 pt in all four, number badge 46×46 in all four. These stay single-column.

### Constants the gold numbers pin down

- Heading-box centre x is **267.5 / 267.5 / 268.0** across gold 29/30/34 → left column centre **268.0**.
- Number badge x is **245.0** on all three, w=46 → its centre is also 268.0.
- `43.0 (band.x_min) + 450.0 / 2 = 268.0` exactly, and `43 + 450 + 8 = 501` = the measured verse-column left edge (501/501/502). So:
  - **`HEADING_COL_W = 450.0`**, **`COL_GUTTER = 8.0`** (= 2 × `_TEXT_GAP_PT`)
  - left column `[43.0, 493.0]`, right column `[501.0, 1892.0]`, **right width 1391.0**
  - verse box right edges 1802/1871/1871 ≤ 1892 (the gold boxes are autosized; the column is the bound)
- **`NUMBER_BADGE_PT = 46.0`** (source circle is 81×81 → scale 0.5679), constant in every gold heading slide.
- Verse badge: source 645×92 → gold 69 tall (scale 0.75), left edge = verse x + 4 (`_TEXT_GAP_PT`).
- Heading point sizes 60 / 80 / 80 are reproduced exactly by **`min(80.0, largest s with n_lines(s) × 1.157 × s ≤ 140.0)`**:
  - 2 lines: `2 × 1.157 × 60 = 138.8 ≤ 140`, at 61 → 141.2 > 140 → **60** (gold 29 ✓, and gold 39/41 ✓)
  - 1 line: the block cap allows 121 pt, the 80 pt cap binds → **80** (gold 30, 34 ✓)
  - so **`MAX_HEADING_PT = 80.0`**, **`MAX_HEADING_BLOCK_PT = 140.0`**, using `dsk_plan._LINE_HEIGHT_FACTOR = 1.157`.
  - Width never binds here: longest heading line at 80 pt is 400.0 pt ("Your Faith") ≤ 450; keep the width check anyway as a guard.
- Vertical: gold does **not** bottom-align the two columns. Left-block vs right-block vertical-centre deltas are +9 / −14 / −10 pt across gold 29/30/34, whereas bottom-alignment would be off by +7 / −39 / −51. → **centre the left block on the right block's vertical extent.**

## 3. Detection rule

A slide is a **heading+verse** slide when all hold, using `cls.kept` only:

1. There is exactly one kept top-level `text` item whose font family is `ArgentCF*`, whose text is non-empty and **≤ 5 words** → the *heading*.
2. There is a kept top-level `text` item whose stripped text is **all digits, length ≤ 2** → the *point number*; its paired kept unfilled `shape` (81×81 circle, no text) is the *number circle*. Heading, number and circle together are the **heading cluster**.
3. `cls.long_text_ids` is non-empty (a top-level long text, or a D1 group-child verse).

Measured over the whole GW deck: slides with a heading cluster are `44, 45, 46, 50, 51, 52, 53, 55, 57, 59, 60`; of those, the ones that also carry a verse — the D1b set — are exactly **44, 46, 50, 51, 52, 53** (six). 44/50/51/53 are group-child verses, 46/52 are top-level.

Refuse (do not two-column) when: more than one ArgentCF heading candidate, more than one point number, more than one long text box, or a non-heading short top-level text that is neither the verse badge nor part of the heading cluster. Those keep today's behaviour.

**Should 51/53 (and 52) also become two-column?** From the gold deck: gold 35/36/37 render those verses **full-width with no heading at all** — the owner deleted the repeated "Faith" heading, keeping it only on the run's first slide (GW 50 → gold 34). The generator has no content-deletion remit, so the honest answer is: yes, apply two-column to 51/52/53 as well (it is strictly better than today's 34.3 pt crushed verse), and record the divergence from gold. See open question Q1 for the optional repeat-suppression rule that would match gold exactly.

## 4. Layout algorithm

Split `band` into `left = Band(band.bottom, band.height, band.x_min, band.x_min + 450.0, band.sample_count)` and `right = Band(band.bottom, band.height, band.x_min + 458.0, band.x_max, band.sample_count)`.

**Right column (verse)** — the existing path, with `band` → `right`:
- `short_fit` contains only the verse badge (group child or top-level shape+text), x forced to `right.x_min` (the owner rule: left-aligned), w/h unchanged from source (645×92, as D1 already places group-child badges unscaled).
- `short_row_h = 92.0`, `budget = 350 − 92 − 4 = 248.0`, `stack_band = replace(right, height=248.0)`.
- `fit_text_stack([verse_box], stack_band, min_text_pt)` → `_stacked_text_rects` → `_short_row_rects`. Emphasis runs flow through `_run_size_ranges` unchanged.

**Left column (heading cluster)** — new, does *not* use the affine path:
- `heading_pt(text, font, budget)`: largest integer `s` in `[80 … min_text_pt]` with
  `longest_line_width(s) ≤ 450` **and** `n_lines(s) × 1.157 × s ≤ 140` **and** `wrapped_height(text, font, s, 450) ≤ 350 − 46 − 4 = 300.0`.
  Returns `None` → refuse the slide (fall back to today's single column is *not* acceptable; refuse so the operator sees it).
- Heading rect: `Rect(left.x_min, y, 450.0, wrapped_height(...))`, text centred in the box.
- Number circle + numeral: scaled to 46×46, centred on `left.x_min + 225.0 = 268.0`, sitting `_TEXT_STACK_GAP = 4` above the heading. Numeral point size scales by `46/81 = 0.5679`.
- Left block height = `46 + 4 + heading_h`; its top y = `right_block_centre − block_h/2`, where `right_block_centre = (verse_badge_y + band.bottom) / 2`.
- `t_heading = heading_pt / source_size` is what goes into `text_sizes` / `_run_size_ranges` for the heading and the numeral.

**Refusals**
- Never split a two-column slide: if the right column does not fit at `min_text_pt`, refuse (`slide N: two-column verse does not fit the verse column at --min-text-pt …`). This is already the behaviour for group-child verses; extend it to top-level verses on two-column slides.
- Refuse if the verse badge is wider than the right column (`645 > 1391` never trips today, but guard it).
- Refuse if two-column applies *and* an image crop applies (same rule as the split path).
- Refuse if the heading cluster's number circle has no resolvable numeral (font/size unresolved) — do not silently drop the badge.

**D2b offline-refit interaction** — the refit is already band-driven: store the **right column** band in `plan.stack_bands[number]` and keep only the verse badge in `plan.short_fit[number]`. `_build_refit_round` then re-fits the verse inside the column with no further change. The left column's rects must be recorded in `plan.fits` but kept **out of** `plan.short_fit`, otherwise `_build_refit_round`'s `_short_row_rects` call would drag the heading back into the verse's short row. Add `plan.two_column: dict[int, Band]` (left band) so a later round can re-derive the left block's centring when the verse height changes.

## 5. Implementation steps (one Sonnet, ≈ 280 lines)

1. **`dsk_plan.py`** (~45 lines): add `longest_line_width(text, font_name, size) -> float | None` (mirrors `wrapped_height`'s `_wrap_lines` + `getlength` / `_WRAP_OVERSAMPLE`) and `fit_heading_pt(text, font_name, col_width, budget, *, max_pt, max_block_pt, min_pt) -> float | None`. Pure, unit-testable, no deck needed.
2. **`dsk_assemble.py` constants** (~8 lines): `HEADING_COL_W = 450.0`, `COL_GUTTER = 8.0`, `NUMBER_BADGE_PT = 46.0`, `MAX_HEADING_PT = 80.0`, `MAX_HEADING_BLOCK_PT = 140.0`, each with the gold slide it was measured from in the comment.
3. **`_heading_cluster(cls, items_by_id) -> HeadingCluster | None`** (~50 lines): the §3 detection, returning the heading item id, numeral id, circle id, or `None`.
4. **`_two_column_rects(number, cluster, items_by_id, band, verse_block_top, warnings)`** (~60 lines): left-column rects + heading/numeral sizes, or raise `AssemblyRefusal`.
5. **Wire into `plan_assembly`** (~70 lines): before `short_fit` is built, if `_heading_cluster` fires and `long_ids` is non-empty, (a) pull the cluster ids out of `short_fit` and out of the affine `fit`, (b) use the right-column band everywhere the current code uses `band` for the stack and the short row, (c) after the verse rects are known, call `_two_column_rects` and merge, (d) record `stack_bands[number] = right`, `two_column[number] = left`.
6. **`AssemblyPlan.two_column`** field + refit guard in `_build_refit_round` (~20 lines).
7. **Plan doc**: new section in `.agents/plans/dsk_pieceD.plan.md`, "D1b — two-column heading+verse band", carrying the §2 table verbatim.

Sequencing: 1 → 2 → 3 → 4 → 5 → 6 → 7. Steps 1 and 3 are independently testable before the wiring lands.

## 6. Tests

`tests/test_dsk_plan.py` (no deck):
- `test_fit_heading_pt_two_lines_caps_at_block` — `("Praise and\u2028Worship", "ArgentCF-Bold", 450, 300)` → `60.0`; at 61 the block would be 141.2 > 140.
- `test_fit_heading_pt_one_line_caps_at_max_pt` — `"Faith"` → `80.0` (block cap would allow 121).
- `test_fit_heading_pt_width_bound` — a synthetic long single word returns a size whose longest line ≤ 450.
- `test_fit_heading_pt_returns_none_below_min` — budget 30 pt → `None`.

`tests/test_dsk_assemble.py` (synthetic payloads):
- `test_heading_cluster_detected` / `test_heading_cluster_rejects_two_headings`.
- `test_two_column_refuses_instead_of_splitting` — long verse, `allow_split=True`, still refuses.
- `test_two_column_short_fit_excludes_heading` — `plan.short_fit[n]` holds only the verse badge; `plan.stack_bands[n].x_min == 501.0`.

`tests/test_dsk_content_rules_acceptance.py` — new `@pytest.mark.deck` rows against the real GW deck, asserting the algorithm's own output (tolerance 0.5 pt), with the gold number in the docstring:

| test | assertions (algorithm output, measured) | gold reference |
|---|---|---|
| `test_gw44_two_column_heading_and_verse` | heading `Rect(43.0, 834.8, 450.0, 159.8)` @ **60.0 pt**; number badge `Rect(245.0, 778.8, 46.0, 46.0)`; verse badge `Rect(501.0, 719.4, 645.03, 92.0)`; verse `Rect(501.0, 821.4, 1391.0, 232.6)`, `t = 0.59`, lead size **41.3 pt**; `44 not in plan.splits` | gold 29: badge x **245**, heading **60 pt**, verse x 502 @ 45 pt |
| `test_gw50_two_column_heading_and_verse` | heading `Rect(43.0, 858.2, 450.0, 113.6)` @ **80.0 pt**; number badge `Rect(245.0, 802.2, 46.0, 46.0)`; verse badge `Rect(501.0, 720.0, 645.03, 92.0)`; verse `Rect(501.0, 822.0, 1391.0, 232.0)`, `t = 0.48`, lead **33.6 pt** | gold 34: badge x **245**, heading **80 pt**, verse x 501 @ 40 pt |
| `test_gw46_two_column_top_level_verse` | heading @ **80.0 pt** at `Rect(43.0, 870.7, 450.0, 113.6)`; badge `Rect(245.0, 814.7, 46.0, 46.0)`; verse `Rect(501.0, 847.0, 1391.0, 207.0)`, `t = 0.67`, lead **46.9 pt** | gold 30: badge x **245**, heading **80 pt**, verse @ 45 pt |
| `test_gw51_52_53_also_two_column` | all three: heading 80.0 pt, badge x 245.0; verse column x 501.0 w 1391.0; verse lead **60.9 / 39.2 / 70.0 pt** (`t = 0.87 / 0.56 / 1.00`) — up from today's 34.3 pt on 51 | gold 35/36/37 drop the heading (see Q1) |
| `test_gw54_unchanged_single_column` | GW 54 has a verse but no heading cluster → verse still `x=43.0 w=1849.0` | gold 38 |
| `test_gw57_heading_only_unchanged` | heading-only slides keep today's affine path | gold 40 |

The badge-x **245.0** assertion is the load-bearing one: it is an exact, independent hit on the gold deck's measured 245 and validates `HEADING_COL_W = 450.0` and `NUMBER_BADGE_PT = 46.0` together.

## 7. Open questions that change the design

- **Q1 — repeated headings.** Gold keeps the heading only on the first slide of a heading run (GW 50) and deletes it from GW 51/52/53. Should D1b add a *repeat-suppression* rule ("heading text identical to the previous in-deck slide's heading → drop the cluster, verse goes full-width single column")? That reproduces gold exactly for all six slides and is a ~20-line addition, but it is the generator deleting source content, which no other rule does. **This is the single biggest open question**; the plan above deliberately does not do it.
- **Q2 — heading-only slides.** Gold 39–42 use a fixed 60 pt heading and the same 46 pt number badge; today's affine path gives 140.3 pt (GW 57). Should `MAX_HEADING_PT` / `NUMBER_BADGE_PT` be applied to heading-only slides too? Out of scope here, but the constants are already measured.
- **Q3 — verse badge scale.** Gold shrinks the verse badge to 69 pt tall (0.75) and re-fits its label to 35–40 pt; D1 places group-child badges unscaled at 645×92. Left as-is (pre-existing D1 behaviour) — confirm the owner accepts the 92 pt badge in the column.
- **Q4 — left-block vertical centring.** Chosen over bottom-alignment from gold deltas of ±14 pt vs ±51 pt. If the owner prefers a fixed baseline, this is a one-line change.
- **Q5 — content anchor.** Gold 34 keeps a full-width image (`4 lines.png`, x=26 w=1867) under a two-column band. The anchor/`_content_ids` logic is untouched by this plan; confirm no interaction with crop planning on GW 53 (which has `4 Man Faith 2.png`).

---


## Owner decisions (2026-09-14 00:55)

- **Q1 — repeated headings: DROP.** A heading cluster whose heading text equals the previous in-deck slide's heading is suppressed
  (heading + number + circle deleted); the verse then takes the full band as a single-column text slide (reproduces gold 35/36/37 for
  GW 51/52/53). Add it as step 5b (~20 lines) with a test (`test_gw51_52_53_repeat_heading_dropped_full_width`) and update the §6 rows
  for 51/52/53 accordingly.
- **Q3 — verse badge: keep current (unscaled) size.** The next milestone after D1b applies the proper template slide layout instead of
  hand-placed rects; badge scaling belongs there.
- Q2 (heading-only slides) — unanswered; leave today's affine path.

---

## Fix round 1 (Codex D1b-p2 review 1 of 56879cf)

- **`_two_column_rects` now takes `min_text_pt`** and forwards it to `fit_heading_pt` (was hardcoded to
  `DEFAULT_MIN_TEXT_PT`, ignoring `--min-text-pt`). Also requires the heading's own source `size` resolved
  (refuses otherwise, alongside the existing font/numeral-size refusal).
- **Repeat-heading predecessor is deck-order, not batch-order.** `_repeat_heading_state` (new) walks
  `payload["slides"]` in full ascending order once, independent of `kept_numbers`, skipping only
  `cls.category == "empty"` slides; a slide with no heading text resets the run (a headingless intervening
  slide now breaks it, which the old per-batch `prev_heading_text` accumulator did not). A slide outside the
  current call's `classes` (no `SlideClass`) falls back to `_heading_text_from_payload_slide`, which applies
  the same single-ArgentCF-candidate rule straight off the payload item without a `cls.kept` filter -- the best
  available signal for a slide `plan_assembly` never classified (**superseded by Fix round 3 below**: this
  payload-only approximation missed group-child verses and the badge/long-text-count rules, so it disagreed
  with `_heading_cluster` on the real deck; it has been removed in favour of reclassifying the whole payload).
  This is a real, not merely theoretical,
  correction: GW46's own true predecessor is GW45 ("Prayer", heading-only), which shares GW46's heading text.
  **This turned out to be wrong** (see Fix round 2 below): the gold deck keeps GW46 two-column despite GW45
  sharing its heading, so round 1's blanket "any matching predecessor heading text drops the run" rule was too
  broad. The three GW44/50/51/53 badge/short-row tests that relied on GW51/53's old (batch-dependent) "heading
  kept when planned alone" behaviour were moved to GW44/50, whose real predecessors are not heading matches.
- **Refit re-centring.** `plan.two_column_cluster: dict[int, HeadingCluster]` (new `AssemblyPlan` field) records
  the cluster ids alongside `plan.two_column`'s left `Band`, so `_build_refit_round` can, after computing the
  round's verse/short-row rects, rederive the left block's `circle_y`/`heading_y` off the new right-block centre
  and emit position-only (`TextRefit(rect, None)`) refits for the heading/circle/numeral. Previously `plan.two_column`
  was dead metadata and the left block silently stayed pinned to the pre-refit centring.
- **Heading/numeral sizing goes through `_run_size_ranges`.** `_two_column_rects` now computes
  `t = heading_pt / heading_source_size` for the heading and the constant `NUMBER_BADGE_PT / _HEADING_CIRCLE_PT`
  (46/81) for the numeral, calling `_run_size_ranges` for each: a tuple result goes to `run_sizes`, a uniform
  float (or a run-gap, flattened with a warning) to `text_sizes`. Previously both were always a single flat
  point size, which would have silently discarded a mixed-size heading or numeral run.

## Fix round 2 (GW46 keeps its heading -- owner-pinned rule)

Round 1's deck-order repeat rule dropped GW46's heading because its immediate predecessor GW45 ("Prayer",
heading cluster, no verse -- `_heading_cluster` returns `None` since `cls.long_text_ids` is empty, `category`
"static") carries the same heading text. But the gold deck (gold 30 = GW 46, §2 above) **keeps** "Prayer" on
GW46 as a two-column slide -- round 1's rule was derived from gold 34->35/36/37 (GW50->51/52/53), where the
predecessor is itself a heading+verse (two-column-eligible) slide.

**Owner-pinned rule (orchestrator decision, owner confirmation pending):** a heading cluster is suppressed only
when the immediate non-empty predecessor in deck order is itself heading+verse (two-column-eligible) with an
identical heading text. A heading-only predecessor (heading cluster, no verse) does not suppress; a headingless
predecessor still breaks the run (unchanged from round 1).

`_repeat_heading_state` now tracks `prev_has_cluster` alongside `prev_heading_text`; `repeats[number]` is set
only when the current slide has a cluster, its heading text is non-`None`, and **both** the predecessor's
heading text is non-`None` and the predecessor itself had a cluster. For a predecessor outside the current
batch's `classes` (no `SlideClass`), `_heading_cluster_present_from_payload_slide` (new) approximates has-cluster
straight off the payload: the same digit-in-circle geometry test as `_heading_cluster`, plus a long-text proxy
(any raw text item over `DEFAULT_TEXT_SLIDE_WORDS` words, since there is no `cls.long_text_ids` to consult).
**Superseded by Fix round 3 below** -- this approximation is removed; every predecessor is now reclassified
through the real `classify_slide` pipeline before `_heading_cluster` is asked about it.

Measured (deck-order batch `[44, 45, 46, 50, 51, 52, 53]`, full `plan_assembly` call together):
- 44, 46, 50 -> two-column; 51, 52, 53 -> full-width (heading dropped, unchanged from round 1).
- GW45 itself: `category == "static"`, `long_text_ids == ()`, `_heading_cluster` returns `None` (heading-only,
  confirmed no verse), `_heading_text_for_repeat_check` returns `"Prayer"`.
- Gold deck: the plan's own mapping (§2) lists gold 39-42 as the heading-only, single-centred-column pattern
  (those map to GW56/57/...); GW45's own gold counterpart is not individually enumerated in this plan's gold
  survey, so we report the heading-only pattern by analogy rather than a direct gold-slide measurement for
  GW45 specifically.
- `test_gw46_two_column_top_level_verse` restored (deleted `test_gw46_repeat_heading_dropped_top_level`) with
  round 1's original pin re-measured against round 2's code: unchanged at `t = 0.65`, lead `45.5 pt` (heading
  `Rect(43.0, ~882.2, 450.0, 113.56)` @ 80.0 pt, badge `Rect(245.0, ~826.2, 46.0, 46.0)`, verse
  `Rect(501.0, ~852.5, 1391.0, ~201.5)`) -- the geometry never depended on the repeat-heading decision, so
  re-measuring after the rule fix reproduces the pre-round-1 numbers exactly.
- New synthetic unit test `test_two_column_repeat_heading_survives_heading_only_predecessor`: a heading-only
  predecessor sharing the next slide's heading text does not suppress it (companion to the existing
  `test_two_column_repeat_heading_survives_headingless_predecessor` and
  `test_two_column_repeat_heading_dropped_when_planned_alone`, both unchanged -- their predecessors are
  themselves heading+verse).

## Fix round 3 (Codex D1b-p2 review 2 of 9604e2e -- predecessor classification must be real)

Review 2's MAJOR: `_heading_cluster_present_from_payload_slide` (round 2's approximation) scanned only
top-level text/shape items and required merely *any* text over `DEFAULT_TEXT_SLIDE_WORDS` words -- it ignored
`cls.kept`, group-child verses (`groupChildren`/`groupChildText`), dedupe, and backdrop-drop settings, and
skipped `_heading_cluster`'s badge-match and single-long-text-id rules entirely. On the real deck this
disagreed with `_heading_cluster`: GW44/50/51/53's verse is a group child, which the approximation could never
see, so it always reported "no cluster" for those predecessors and never suppressed a same-heading successor
planned right after one of them.

**Fix:** both payload-approximation functions (`_heading_text_from_payload_slide`,
`_heading_cluster_present_from_payload_slide`) are deleted. `_repeat_heading_state` now takes
`full_classes_by_number: Mapping[int, SlideClass]` -- the *whole deck's* classification, not the planning
batch's -- and calls `_heading_cluster`/`_heading_text_for_repeat_check` on every predecessor exactly as it
would on a batch slide; there is no more a "slide outside `classes`" branch. `plan_assembly` gained an optional
`all_classes: Sequence[SlideClass] | None` parameter and a new `_full_classes_by_number` helper that resolves
it: caller-supplied `all_classes` wins (the real CLI path -- `assemble_offline_deck` now passes
`all_classes=classes`, and `load_assembly_inputs` already classifies the whole deck via `classify_deck`, so
this is free); absent that, `_classify_all_slides_from_payload` (new) reclassifies every slide in `payload` via
`classify_slide` directly, with group-movie/-build/connection-line counts left at their defaults. That
degradation is safe for this purpose: `_heading_cluster`/`_heading_text_for_repeat_check` read only
`cls.kept`/`cls.long_text_ids`/`cls.is_text`, none of which those counts affect (only `cls.category`,
`build_count`, `movie_count` would differ, and this pass never reads those). This fallback deliberately never
loads the deck graph or `fw_deck` from disk, so a caller that defers deck loading stays lazy (an earlier
attempt that called `classify_deck` from a lazily-loaded `fw_deck`/deck-graph broke that laziness --
`iwa_builds.deck_builds` unconditionally opens the `.key` zip for its data index even when a `deck` graph is
supplied -- so it was dropped in favour of the payload-only path).

New tests (`tests/test_dsk_assemble.py`):
- `test_repeat_heading_predecessor_uses_group_child_verse`: a group-child-verse predecessor (mirroring GW
  44/50/51/53) now correctly suppresses a same-heading successor planned alone -- proven both via the plan
  (heading dropped, verse `x=43`) and directly via `_heading_cluster` on the reclassified predecessor.
- `test_repeat_heading_predecessor_unmatched_badge_does_not_suppress`: a predecessor with an extra top-level
  text that fails the badge-match rule is not a cluster (`_heading_cluster` returns `None`) and must not
  suppress.
- `test_repeat_heading_predecessor_multiple_long_text_ids_does_not_suppress`: a predecessor with two
  `long_text_ids` is not a cluster and must not suppress.
- `test_repeat_heading_gw51_planned_alone_matches_batch` (real deck): GW51 planned alone now matches its plan
  in the GW `{44, 46, 50, 51, 52, 53}` batch exactly -- heading dropped, verse `x=43.0`/`w=1849.0` both ways;
  the batch's own two-column set stays `{44, 46, 50}`.

A/B vs 9604e2e (every GW slide planned alone, and the same deck-order batch as `test_gw_every_kept_non_movie_slide_plans_under_default_flags`): the deck-order batch is byte-identical (it always had the whole deck's real classes -- `load_assembly_inputs` classifies every slide regardless of `--slides`). Planned alone, GW51 and GW52 both change from two-column (heading kept, wrong) to full-width (heading dropped, correct) -- both slides' immediate predecessors (GW50, GW51) are group-child-verse clusters the round-2 approximation could not see. GW53 (predecessor GW52, a top-level-text cluster the approximation *could* see) was already correct and is unchanged. No other slide, in either scenario, changed.

## Fix round 4 (Codex D1b-p2 review 3 of 0adc25a -- no reclassification fallback; all_classes contract)

Review 3's MAJOR: round 3's `_classify_all_slides_from_payload` fallback forwarded `text_slide_words`, dedupe,
backdrop, and group-child text/geometry, but its `classify_slide` call omitted `include_side` (batch
classification passes the per-slide setting) and left `connection_line_builds` at zero (`classify_deck`
supplies the real count). Both can change `category`/`kept`/`long_text_ids` from batch classification, and
`_repeat_heading_state` reads `cls.category` (a connection-line-only intervening slide is `built` in batch
classification but `empty` in the fallback, so the fallback could wrongly treat it as transparent to the run).

**Fix (ORCHESTRATOR DECISION): the fallback is deleted, not patched.** `_classify_all_slides_from_payload` is
removed entirely. `_full_classes_by_number(payload, classes, all_classes)`: caller-supplied `all_classes` wins
as before; else, when `classes` already covers every slide number in `payload` (a synthetic single-/few-slide
payload built to match `classes` -- unaffected, since `classes` already equals the payload's full
classification), uses `classes` directly; else raises `ValueError("plan_assembly: planning a subset of the
deck needs all_classes (the whole-deck classification)")`. `plan_assembly`'s docstring states the new
requirement. `classify_slide` is no longer imported by `dsk_assemble.py`.

Every direct `plan_assembly` caller that plans a subset of a deck-backed payload now passes
`all_classes=classes` (or the fixture's full `by_number.values()`): `tests/test_dsk_assemble.py`'s
`test_gw_every_kept_non_movie_slide_plans_under_default_flags`, `test_gw_text_slides_stay_within_band_top`,
`test_gw44_badge_x_clears_title_right_edge`, `test_gw_group_text_slides_short_fit_stays_within_band_x`,
`test_gw50_badge_x_clamped_to_band_right_edge`, `test_gw17_28_forced_split_at_floor_66_refuses_gw28_single_box`,
`test_gw13_forced_floor_66_refuses_its_badge_gapped_single_box`, `test_gw49_plans_under_shrink_and_refuses_under_warn`,
`test_repeat_heading_gw51_planned_alone_matches_batch`, and the three round-3 synthetic predecessor tests
(`test_two_column_repeat_heading_dropped_when_planned_alone`, `..._survives_heading_only_predecessor`,
`..._survives_headingless_predecessor`, `test_repeat_heading_predecessor_uses_group_child_verse`,
`..._unmatched_badge_does_not_suppress`, `..._multiple_long_text_ids_does_not_suppress`), whose synthetic
payloads include a predecessor slide outside `classes` and so now need an explicit `all_classes` covering both
slides. `tests/test_dsk_content_rules_acceptance.py`'s `_plan_one` fixture helper now takes `by_number` and
always passes `all_classes=list(by_number.values())`; `test_gw51_52_53_repeat_heading_dropped_full_width`
passes `all_classes=list(by_number.values())` directly. The CLI path (`assemble_offline_deck`) already passed
`all_classes=classes`; no `src/` caller needed a change (grepped every `plan_assembly(` call in `src/` and
`tests/`; `_build_refit_round` does not reclassify or replan, per the review).

New tests (`tests/test_dsk_assemble.py`):
- `test_repeat_heading_predecessor_include_side_matches_batch_classification`: a predecessor classified with
  `include_side=True` (an extra side-panel long-text box, kept only under `include_side`) breaks its own
  heading cluster (two `long_text_ids`) and must not suppress; the same predecessor classified with
  `include_side=False` drops that side text, keeps one `long_text_ids`, and does suppress -- both via
  `all_classes`, proving `_full_classes_by_number` uses exactly what the caller classified, not its own guess.
- `test_repeat_heading_connection_line_only_slide_breaks_run_consistently_with_batch`: an intervening
  no-items slide classified with `connection_line_builds=0` is `category == "empty"` (transparent, run
  continues, heading suppressed) versus `connection_line_builds=1` is `category == "built"` (breaks the run,
  heading kept) -- both via `all_classes`.
- `test_plan_assembly_subset_of_deck_without_all_classes_raises`: a subset `classes` (payload has a slide
  `classes` doesn't cover) without `all_classes` raises `ValueError` naming `all_classes`.

A/B vs 0adc25a: with `all_classes=classes` passed (as `assemble_offline_deck` already does, and as every
updated test now does), `_full_classes_by_number` returns exactly `{c.number: c for c in all_classes}` --
byte-identical to round 3's `all_classes is not None` branch, which was untouched. Every GW slide planned
alone and the GW `{44, 46, 50, 51, 52, 53}` batch are therefore identical to 0adc25a's. No behavioural change
on the `all_classes`-supplied path; the change is confined to what happens when it is omitted for a deck
subset (refuse instead of silently reclassifying).

## Live r12 finding -- two-column heading/numeral floating off-canvas

Measured on the live r12 output deck (`~/Desktop/dsk-d4-work/out-r12/Sermon_PK_DSK.key`, read via
`offline_wall_payload`): GW 44's heading text `x=43 y=835 w=450 h=868` (PNG shows no heading, it sits below
the canvas) and GW 50's heading `h=451` (PNG clips it at the bottom edge); the numeral boxes came back at
`h=74`/`h=43` against a planned 46.0.

The brief's premise -- that the AppleScript emission never writes `set height` for these two boxes -- is
**wrong**: rebuilding the emitted script offline for GW 44/46/50 (`_slide_lines`) shows `set height of theObj`
IS written for both the heading (planned h e.g. 159.84) and the numeral (46.0) on every one of the three
slides, before this round's fix.

Root cause: `offline_wall_payload(GW_DECK)["_offline"]["soft_geometry"]` flags GW 44/46/50's heading
(`text` kindIndex 1, 1, 3) and numeral (`text` kindIndex 0) as `geom_source == "autosize"` --
`iwa_geometry._compose_record` sets this whenever the raw IWA frame height is exactly `0.0` (a genuine
Keynote "auto size" text box, not a fixed frame). Keynote silently re-autosizes such a box on save, so an
explicit `set height` write is a no-op that keeps the box at its old (pre-shrink) autosize height -- exactly
the r12 symptom. `dsk_assemble`'s own `plan.autosize` detection only flags an item when the POST-COMPOSITION
payload item has `w == 0.0 or h == 0.0`, which is never true here (composition backfills real w/h from
`naturalSize` via `_autosize_rect`), and the cluster-building loop explicitly skips `cluster_ids`, so nothing
ever marked these boxes autosize.

Fix (`src/obed_edom/dsk_assemble.py`): new `_cluster_autosize_align(cluster, id_by_item, objects_graph)`
reads the raw object geometry for `cluster.heading_id`/`cluster.number_id` (the same `objects_graph`/
`id_by_item` `plan_assembly` already builds for crops) and flags an id autosize when its raw frame height is
`0.0`, recording its vertical-alignment code (`_vertical_alignment`, default `kFrameAlignMiddle` when unset --
matching `_autosize_rect`'s own middle/justify/unknown fallback). Flagged ids are folded into `slide_autosize`
so the existing `plan.autosize` mechanism in `_slide_lines` (the same check that already skips `set height`
for a fixed-size-0 top-level text box) drops the write -- no parallel mechanism. New `AssemblyPlan.cluster_align`
field carries the alignment code through to `_slide_lines`, which adjusts the WRITTEN position (not the
planned rect, which stays a plain visual-top rect exactly as `_build_refit_round`'s cluster reposition already
produces): `kFrameAlignTop` writes `rect.y` unchanged, `kFrameAlignBottom` writes `rect.y + rect.h`, anything
else (middle/justify/unset) writes `rect.y + rect.h / 2`. Because the transform is applied at emission time
from whatever `rect` is current in `plan.fits`, a refit round's position-only cluster rewrite
(`_build_refit_round`'s `cluster_rects` block, which only ever changes `y` and never `h`) needs no changes --
it stays consistent automatically.

Tests added (`tests/test_dsk_assemble.py`): `test_two_column_autosize_heading_and_numeral_skip_set_height` and
`test_two_column_fixed_frame_heading_still_gets_set_height` (synthetic two-column payload with a mocked
`objects_graph`, autosize vs fixed-frame raw geometry); `test_gw44_cluster_heading_and_numeral_are_autosize`
(real GW 44, asserts both cluster ids land in `plan.autosize[44]`).

A/B vs the prior commit (`git show HEAD:.../dsk_assemble.py`, offline, whole GW deck, every slide planned
alone): only GW 44/46/50 differ. Per slide, the diff is exactly: `set height` dropped for both the heading and
numeral text boxes, and the written `y` shifted by `+h/2` for each (all six resolve to `kFrameAlignMiddle`,
no `verticalAlignment` set on any of the six source objects) -- e.g. GW 44 numeral `{245, 778.77}` ->
`{245, 801.77}` (46/2 = 23), heading `{43, 834.77}` -> `{43, 914.69}` (159.84/2 = 79.9); GW 46/50 shift by
their own `h/2` the same way. No other slide's emitted script changes.

**Out of scope, not changed:** the same `geom_source == "autosize"` signal also fires for GW 13's main
stacked long text box (`text` kindIndex 1) and GW 17's (kindIndex 1, 2, 4, 5) -- i.e. the general top-level
stacked-text path likely has the same "Keynote overrides `set height`" exposure, not just the two-column
cluster. This brief scoped the fix to `_two_column_rects`/the heading cluster only; the stacked-text path is
untouched and is a separate, larger-surface finding for a future round.
