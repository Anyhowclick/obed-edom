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
  available signal for a slide `plan_assembly` never classified. This is a real, not merely theoretical,
  correction: GW46's own true predecessor is GW45 ("Prayer", heading-only), which shares GW46's heading text,
  so GW46 planned alone now also drops its heading (`test_gw46_repeat_heading_dropped_top_level`,
  `dsk_assemble.py`), matching what even the *unfixed* code already produced when GW45 was included in the same
  batch -- this is the batch-dependence bug being fixed, not a new regression. The three GW44/50/51/53 badge/short
  -row tests that relied on GW51/53's old (batch-dependent) "heading kept when planned alone" behaviour were
  moved to GW44/50, whose real predecessors are not heading matches.
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
