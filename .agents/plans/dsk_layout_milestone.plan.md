# DSK layout milestone — put kept slides on the template's own slide layouts

Status: planned (read-only design pass, 2026-09-14, worktree `dsk-gen`, branch `feat/dsk-gen`).
Every number below is reproduced by a script in the planner scratchpad
`plan-layout/` (`p1_layout_inventory.py`, `p2_slide_vs_layout.py`, `p3_raw_object.py`,
`p4_slide_archive.py`, `p5_gold_table.py`, `p6_template_table.py`, `p7_out_table.py`,
`p8_panel_assets.py`, `p9_pp7.py`, `p10_connection_lines.py`, `p11_text_metrics.py`,
`p12_font_sizes.py`, `p13_alignment_and_panels.py`). No Keynote was opened.

Decks read (read-only): GW `~/Desktop/Diff-Checker/Sermon_PK (GW).key` (63 slides, 7680×1080),
GOLD `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key` (43 slides, 1920×1080),
TEMPLATE `~/Desktop/Default Templates/2026_Lower-Thirds (ENG).key` (16 slides, 1920×1080,
31 layouts), latest output `~/Desktop/dsk-d4-work/out-r12b/Sermon_PK_DSK.key`.

---

## §0 OWNER SUMMARY

1. **The gold look is a layout, and we already own the layout.** The Lower-Thirds template
   carries all 31 layouts the gold deck uses, geometry-identical. "Variation (2)" is
   `Verse Standard (Variation 2)` — used by 21 of 43 gold slides.
2. **What a layout actually gives you:** the translucent panel (1869×213 image at y=840.4)
   is *untagged* layout artwork, inherited for free. The verse text, the badge text and the
   rose pill are *sage-tagged* slots (`Text`, `Text-1`, `Media`) that live as ordinary,
   editable items on each slide. Gold slides own exactly those three and nothing else.
3. **Recommendation — Option A.** Keep today's copy-and-transform pipeline (it is the only
   thing that preserves builds), set the base layout per class so the panel comes from the
   layout, and drive the verse/badge rects from the layout's measured slots instead of band
   arithmetic. Option B (fill placeholders, delete source items) is rejected: the layout
   slots are *not* `default title item`/`default body item` (those placeholders exist but
   are unused and absent from `ownedDrawables`), and deleting source items destroys builds.
4. **What changes on screen:** black band → blue-grey rounded panel; cyan badge text →
   white bold text on a rose pill; badge jumps from wherever GW put it (x=714/778/1312 in
   r12b) to the fixed slot x=63.1; verse at a fixed 45 pt in a fixed 1799×177 slot.
5. **Import is dedupe-safe.** The GW deck owns no layout named like the DSK ones (only
   `BLANK`/`BLACK BLANK`/`Blank`/`Sermon Title`/…), so importing `Verse Standard
   (Variation 2)`, `Verse 1 Line (Variation 2)`, `Point 3 Lines`, `Point (2 Lines)`,
   `Num Point with Verse-Pre`, `Blank Black` by name is safe. Never import `Blank`.
6. **The pill is not scriptable live.** Its width is a *mask* crop (exact law: mask right
   edge pinned at 1832.5315, height 75.52111); AppleScript has no mask property. It has to
   be an offline write after the live pass — piece L4.
7. **Q2/Q3/estimator fold-ins:** heading-only is 60 pt + 46 pt badge in gold, flat, on
   `Point 3 Lines`/`Point (2 Lines)`. Q3's 0.75 badge scale becomes moot — the badge is a
   fixed layout slot. The estimator still picks the heading *size* (that rule reproduces
   gold exactly), but `wrapped_height` over-predicts (159.84 vs Keynote's 130).
8. **Owner questions (§5):** (a) the template has *no* single two-column heading+verse
   layout — it splits into `Num Point with Verse-Pre` / `-Post`; keep D1b's hand
   two-column on `Point 3 Lines` (what gold does) or adopt the split? (b) gold 33/34 use a
   267-tall panel that exists in no layout — refuse, or keep hand-placing it? (c) GW
   payload 7's two curved connector arrows are unaddressable — refuse that slide?

---

## §1 Measurements

### 1.1 Gold-deck layout inventory (`p1_layout_inventory.py`, `p5_gold_table.py`)

Gold's theme carries **31 layouts**; `Blank`×2, `Point 3 Lines`×3 and
`Verse Standard (Variation 2)`×2 are **duplicate names** (copy-paste residue — a hazard for
any name-based `slide layout "…"` lookup). Usage across the 43 gold slides:

| layout | gold slides | n |
|---|---|---|
| `Verse Standard (Variation 2)` | 3, 9–11, 14–17, 20–28, 35–38 | 21 |
| `Blank Black` | 1, 4, 12, 13, 18, 19, 31–34, 43 | 11 |
| `Verse 1 Line (Variation 2)` | 5–8 | 4 |
| `Point 3 Lines` | 29, 30, 39, 41 | 4 |
| `Point (2 Lines)` | 2, 40, 42 | 3 |

"Variation (2)" = **`Verse Standard (Variation 2)`**, layout index 2.

### 1.2 What a layout owns, and what a slide owns

`KN.SlideArchive` has **`templateSlide`, a direct object reference to its layout slide**
(cheaper and exact vs. the `templateSlideId` uuid scan `_base_layout_slide_for_ordinal`
uses today). `sageTagToInfoMap` tags the layout's *slots*; untagged drawables stay on the
layout as inherited artwork.

`Verse Standard (Variation 2)` (identical in gold and template except a hand-edited badge box):

| tag | kind | rect (template) | role |
|---|---|---|---|
| `Text` | text | 53.6, 866.4, 1799.0 × 177.0 | verse body, 45 pt, left-aligned |
| `Text-1` | text | 63.1, 785.8, 933.1 × 82.1 | badge text, 40 pt AzoSans-Bold |
| — | image | 25.5, 840.4, 1869.0 × 213.0 | **panel** (inherited, never on the slide) |
| `Media` | image | 50.4, 789.1, 958.5 × 75.5 | **pill** (resized per slide) |

Gold slide 3 owns exactly `Text` (53.6, 866.4), `Text-1` (63.9, 789.1, 274.8 × 75.5) and
`Media` (50.4, 789.1, **301.8** × 75.5) — no panel. So **gold slides carry their own
top-level items over layout artwork**; they do *not* fill `titlePlaceholder` /
`bodyPlaceholder` (those objects exist — 15156404 / 15156418 — but are not in
`ownedDrawables` and carry none of the content).

Other layout slots (template, `p6`/`p12`/`p13`; `TATvalue0` = left, `TATvalue2` = centre):

| layout | slots | panel |
|---|---|---|
| `Verse 1 Line (Variation 2)` | `Text-1` verse 53.6, 967.0, 1812.9×73.0 @45 pt L; `Text` badge 63.1, 878.4, 945.9×77.0 @40 pt; `Media` pill 50.4, 879.1 | 26.0, 929.8, 1868×**120** |
| `Point 3 Lines` | `Text` 53.6, 860.9, 1812.9×177.0 @45 pt **centre** | 26.0, 842.9, 1868×**213** |
| `Point (2 Lines)` | `Text` 53.6, 886.9, 1812.9×177.0 @45 pt **centre** | 26.0, 893.9, 1868×**163** |
| `Num Point with Verse-Pre` | `Text` heading 53.6, 892.7, 1812.9×158.0 @**75 pt** centre; `Text-1` num 960.0, 852.4, 161×51 @30 pt centre; inherited circle group 919.4, 852.2, 81.1×57.5 | 213 |
| `Num Point with Verse-Post` | `Text-1` verse 427.5, 900.2, 1422.3×125 @45 pt L; `Text-2` ref 426.9, 836.4, 286.3×73 @45 pt L; inherited num text 234.9, 852.4; circle group 194.4, 852.2, 81.1×57.5; divider **line** 407.7, 870.4, 158×0; **point text parked off-canvas at x=−671.5** | 213 |

Note the `Media` pill slot is absent from `Verse 1 Line` (non-variation) in the template.

### 1.3 The two-column and heading-only gold slides

| gold | layout | slide-owned items |
|---|---|---|
| 29 | `Point 3 Lines` | heading text 80.2, 906.4, 375.5×137.6 @**60 pt** ArgentCF-Bold; num badge group 245, 866, 46×46; verse-ref text 506.5, 854.9, 242.6×69 @40 pt; verse 502.1, 911.7, 1300.5×125 @45 pt — **no pill image** |
| 30 | `Point 3 Lines` | heading 80.2, 894.2, 375.5×104 @**80 pt**; badge group 245, 866, 46×46; ref 505.3, 854.9, 331.7×69 @40 pt; verse 500.9, 911.7, 1369.7×125 @45 pt |
| 34 | **`Blank Black`** | heading 112, 891, 312×104 @80 pt; badge 245, 824, 46×46; ref 505, 793, 332×69; verse 501, 841, 1370×205 @40 pt; **own panel image 26, 788, 1867×267** |
| 33 | **`Blank Black`** | text 219, 802, 1482×230; **own panel 26, 788, 1867×267** |
| 39 / 41 | `Point 3 Lines` | heading 726.7, 906.4, 466.7×137.6 @**60 pt** (2 lines); badge group 937, 866, 46×46 (centre x = 960) |
| 40 / 42 | `Point (2 Lines)` | heading 750.7 / 691, 934.4, 481.2 / 600 × 80.0 @**60 pt** (1 line); badge group 688 / 629, 954, 46×46 |

So: heading-only is **60 pt flat** in all four gold slides (not 60/80), badge **46 pt**;
2-line headings put the badge *above*, centred on 960; 1-line headings put it *inline left*
(the pair heading+badge is centred on 960 either way).

**Two-column has no layout.** The template's answer to "point + verse" is two slides
(`…Verse-Pre` = number + full-width 75 pt heading; `…Verse-Post` = number + divider + verse,
heading parked off-canvas). Gold 29/30/34 instead put both on one slide by hand. D1b's
constants (`HEADING_COL_W=450`, `COL_GUTTER=8`, `NUMBER_BADGE_PT=46`, left column
[43, 493], right [501, 1892]) match **gold**, not the template's Pre/Post slots
(1812.9 heading, 81.1 badge, verse at 427.5 with a divider). No D1b constant becomes a
layout slot unless the owner picks the Pre/Post split (§5 Q1).

### 1.4 The pill: an exact, unscriptable mask law (`p8`)

The pill on every gold verse slide is the **same image data (id 27859, natural 1887×136),
rotated 180°**, masked. Measured across gold 3 / 5 / 9 / 20 / 23 / 35 / 38 and the layout:

* mask height **75.52111** and mask y **50.9344** — constant everywhere;
* mask `x + width` = **1832.5315** — constant (mask right edge pinned; width varies);
* frame width == mask width; frame x **50.4** constant; frame y 789.1 (standard) / 879.1 (1-line).

Widths seen: 958.4864 (layout default), 362.117, 355.328, 308.117, 301.829, 279.416,
258.049, 202.557. Keynote's sdef exposes **no mask property** (`dsk_generator.plan.md`
"image … no stroke, no mask"), so per-slide pill width cannot be set live — it is an
offline IWA write.

### 1.5 Layout import is dedupe-safe against the GW deck (`p1` on GW)

GW's 16 layouts: `LED Ratio`, `2026 FILLER`, `2026 FILLER SIDE BLANK`, `2026 FILLER BLANK`
(×2), `Sermon Title` (×3), `BLACK BLANK`, `BLANK` (×2), `SOT`, `2026 FILLER CENTRE BLANK`,
`BMG FILLER`, `MAP BLANK`, `Blank`. None collides (case-insensitively) with
`Verse Standard (Variation 2)`, `Verse 1 Line (Variation 2)`, `Point 3 Lines`,
`Point (2 Lines)`, `Num Point with Verse-Pre`, `Blank Black`. **`Blank` collides** with
GW's `Blank`/`BLANK` — never import it.

Alpha gate (`layout_alpha_safe`, full-canvas-drawable rule): every layout we want is
`alpha_safe=True` (`Blank Black` has 0 drawables; the verse/point layouts own only band art).
The template's `Blank`, `Photo Disclaimer`, `Ways To Give English/Bahasa/Chinese`, `Jesus QR`
and `Pre-Svc Announcements` are **not** alpha-safe.

### 1.6 Today's output (`p7` on out-r12b)

All 16 output slides sit on `Blank Black` with hand-placed rects; the deck still carries all
16 GW layouts plus the imported `Blank Black`. Badge texts land at x=714 / 778 / 1312 —
wherever the GW source put them, scaled. Panel: none.

### 1.7 GW payload 7 (human slide 4) (`p9`, `p10`)

Items (7680×1080): `text#0/#1` + `shape#0/#1` + `group#0` on the left half, their mirror
`text#2/#3`, `shape#2/#3`, `group#1` at +2446.70; `image#0` −1119, −315, 9917×1395 (the
earth/space wall backdrop); `image#1/#2` the two side-panel scrims. Plus **two
`TSD.ConnectionLineArchive` drawables at x=3000.46 and x=5447.16, each 216×214.9, each with
a build** — they carry no `connectedFrom`/`connectedTo`, so they are free-standing curves,
not auto-following connectors.

Classifier verdict (`dsk_plan.classify_deck`, all attachments on):
`category="built"`, `build_count=4`, `is_text=True`,
`kept=(text0, text1, shape0, shape1, group0)`, `dropped_side=(image1, image2)`,
`dropped_duplicate=(text2, text3, shape2, group1, shape3)`, `connection_line_builds=2`.
`image#0` is dropped silently by `is_backdrop`. **No refusal today.**

Builds on the slide: `group#0` `apple:dissolve` In (identity `('group','Elohim (plural)')`),
`shape#1` `com.apple.iWork.Keynote.LineDraw` In (the cyan highlight box around "God"), the
mirrors of both, and 2 connection-line builds. Slide transition `apple:dissolve` 0.6 s.
GW 7 was **not** in the r12b keep list `[5,13,17,21,24,28,32,33,44,46,48,50,51,52,53]`, so
it has never been exercised live.

Banked build evidence from the r12b log: geometry-only rewrites **preserve** builds
(slide 5 and 44 group dissolves survive into the output), but slide 17's
`apple:dissolve character` build went **missing** — a text-size/run-size write destroys a
character-level build.

### 1.8 Autosize write order (`dsk_assemble.py:2148-2170`, `:2412-2424`)

`_slide_lines` emits `width → [height] → position → size` for every top-level text **except**
`cluster_autosize_ids`, which get `width → size → position`. `build_refit_script` emits
`width → position → [height] → size` for all. The 2026-09-14 live probe
(`.agents/reviews/dsk-d4b/probe-autosize-2026-09-14.log`) shows position moves on every
size/height write (`B_after_width` y −140, `C_after_size` y 232, `D_after_height` y 247) and
settles only when position is written last. It also measures a 60 pt two-line heading in a
450-wide box at **height 130**, where `dsk_plan.wrapped_height("Praise and Worship",
"ArgentCF-Bold", 60.0, 450.0)` returns **159.84** (= 2 × 1.157 × 60 + `_BOX_PADDING_PT` 21.0)
— a +23 % over-prediction, all of it in the padding term and the line factor.

---

## §2 Design and recommendation

### 2.1 The three mechanisms, measured

**(A) Keep item-transform; switch base layout per class; drive rects from layout slots.**
Feasible today. `set base layout` is proven to work and to change what is drawn (the
layout-alpha probe: reassigning to `Blank Black` dropped the lower-third artwork, 0.80 →
0.99 transparent). Builds ride on the surviving source drawables — proven by r12b. The only
new live capability needed is importing *several* named layouts instead of one. The pill
needs an offline mask write (§1.4). **Cost:** we still compute rects; we just read them from
a measured slot table rather than `DEFAULT_BAND` arithmetic.

**(B) Fill layout placeholders with the source text, delete the source items.** Rejected on
measurement: the gold/template slots are `sageTagToInfoMap` entries (`Text`, `Text-1`,
`Media`), **not** `titlePlaceholder`/`bodyPlaceholder`, so AppleScript's
`default title item` / `default body item` do not address them; they surface only as ordinary
`text item n` / `image n`, i.e. exactly what (A) already writes. And deleting the source items
deletes their builds — the owner's PP7 wish (§1.7) dies immediately. Whether `set base layout`
even materialises the tagged slots onto an *existing* non-empty slide is **unverified offline**
and would be a live precondition we cannot gate.

**(C) Hybrid — layout for artwork, source items for content.** This *is* (A). What gold
does, item for item.

**Recommendation: (A).** It is the smallest change that produces the gold look, it keeps
every build we can keep, and every rect in it is already measured.

### 2.2 Class → layout mapping (from gold's actual usage, §1.1/§1.3)

| generator class | layout | slots used |
|---|---|---|
| verse, 1 rendered line | `Verse 1 Line (Variation 2)` | verse 53.6/967.0/1812.9×73; badge 63.1/878.4; pill 50.4/879.1 |
| verse, 2–3 lines (default) | `Verse Standard (Variation 2)` | verse 53.6/866.4/1799×177; badge 63.1/785.8; pill 50.4/789.1 |
| point, ≤2 lines | `Point (2 Lines)` | text 53.6/886.9/1812.9×177 centre |
| point, 3 lines | `Point 3 Lines` | text 53.6/860.9/1812.9×177 centre |
| heading-only | `Point 3 Lines` (2-line) / `Point (2 Lines)` (1-line) | 60 pt heading + 46 pt badge, pair centred on x=960 |
| two-column heading+verse | `Point 3 Lines` + D1b's hand geometry | — (§5 Q1) |
| verse needing 4 lines (gold 33/34) | none exists | (§5 Q2) |
| image / movie / full-bleed content | `Blank Black` | — |

### 2.3 Verification, offline

Every layout decision is checkable without Keynote: resolve each output slide's layout by
`KN.SlideArchive.templateSlide` (direct ref), assert its name, assert `layout_alpha_safe`,
and assert each kept item's rect equals the slot rect within tolerance. Re-run
`p5_gold_table.py`-shaped output against the produced deck.

---

## §3 Pieces (one sonnet each, in order)

**L1 — autosize write order (the standing Codex follow-up).** `dsk_assemble._slide_lines`
and `build_refit_script`: carry raw-autosize identity for *all* top-level text (not just
`cluster_autosize_ids`) and emit `width → size/run sizes → position`, height omitted for
autosize items. Tests: extend the existing ordering assertions to a non-cluster autosize
text; add GW 13 and GW 17 regressions asserting no `set height` and position-last.
Offline A/B: emitted script diff only — no geometry change expected until a live run.
~120 lines.

**L1 landed (2026-09-14).** `_raw_autosize_ids` (renamed/generalised from
`_cluster_autosize_ids`) now covers every kept top-level text id per slide, including
stacked ids (GW 13/17's stacked verse boxes were previously excluded from autosize
detection and still got `set height`); `cluster_autosize_ids` dropped from `AssemblyPlan`
(redundant once ordering keys off `plan.autosize`). `_slide_lines`, `build_refit_script`,
and `_group_stacked_child_lines` all emit `width → size/run sizes → position` with height
omitted for autosize text; fixed-frame order is unchanged (no probe evidence for it).
Fixed-frame regressions still pass. Full suite: 2458 passed / 84 skipped / 1 xfailed, one
pre-existing unrelated failure (`test_dsk_deck_builds`, a shared external-deck-state
issue, not caused by this change). Deck-wide A/B against `0bfd8d1` on all 41 non-empty/
non-movie GW slides: geometry/deletes byte-identical; 32 slides' scripts changed, every
changed line either a dropped `set height` or a width/position/size reorder.

**L1 fix round 1 (2026-09-14, Codex review 1 of `7ef00bd`, 2 MAJOR/1 MINOR, REVISE).**
1. `_group_known_child_lines` now accumulates a `groupCaption` autosize child's size
write before position (was width → position → size, same bug the non-group path had
already fixed); fixed-frame child order unchanged.
2. Centralised autosize detection in one `_autosize_text_ids` helper (thin wrapper over
`_raw_autosize_ids`) used by both `plan.autosize` and `SplitPart.autosize`; deleted the
`w == 0.0 or h == 0.0` payload heuristic everywhere. No payload-level `soft_geometry`/
`geom_source == "autosize"` pre-write flag exists in this codebase (that field is a
post-write verification concept in `offline_inspect.offline_wall_payload`, unrelated to
planning) and the `plan-layout/p9_pp7.py`/`p11_text_metrics.py` files the review named do
not exist here, so precedence collapsed to graph-backed (b) else no-autosize (c) — matching
production, which always supplies `deck=`/`fw_deck=` (`dsk_assemble.py:3764`). A deck-wide
parity probe on GW (70 kept top-level text ids, 41 non-empty/non-movie slides) found the old
heuristic disagreed with the graph on 50/70 ids, always in the same direction (heuristic
said fixed-frame, graph says autosize) — i.e. `set height` was being wrongly emitted for
most of the deck's genuine autosize boxes pre-fix; zero false positives (heuristic-autosize
but graph-fixed) were found.
3. Fixed a genuinely vacuous test (`test_gw17_stacked_long_boxes_are_raw_autosize_position_last`
asserted on `("text", 4)`, which is raw-autosize per the graph but not `kept`/planned on
GW 17 at all, so the old `continue`-if-absent guard always skipped it; corrected to
`("text", 2)`, the box actually present) and made the refit fixture raw-height-zero via a
graph fixture instead of payload width-zero. Added graph-backed-vs-graphless parity tests
and a groupCaption regression.
Deck-wide A/B against `7ef00bd` (41 non-empty/non-movie slides): `fits`/`deletes`
byte-identical; 4 scripts changed (slides 2, 7, 37, 61), every diff a single `set position`
line moving one line later (the groupCaption reorder) — no slide's fixed-frame/autosize
classification flipped on this deck. Targeted suite 475 passed/1 known-failed/1 xfailed;
full suite 2461 passed / 84 skipped / 1 xfailed, same pre-existing `test_dsk_deck_builds`
failure.

**L2 — multi-layout import, dedupe-gated.** `dsk_live.layout_import_lines` takes a list of
layout names and imports each missing one (donor slide per layout, deleted after);
`dsk_assemble.check_layout_import_preconditions` loops the whole list (name absent from the
FW deck *or* the FW-owned one alpha-safe, and the template's match alpha-safe); refuse on
`Blank`. Switch `_base_layout_slide_for_ordinal` to `KN.SlideArchive.templateSlide`.
Add `DEFAULT_DSK_LAYOUT_NAMES`. Tests: synthetic theme objects with a colliding name; a
duplicate-name theme (gold has three `Point 3 Lines`) must refuse, not pick arbitrarily.
Offline A/B: the assembled deck gains 5 layouts; every kept slide still on `Blank Black`.
~200 lines.

**L3 — layout slot table + per-class base layout.** New `dsk_assemble.LAYOUT_SLOTS`
(the §1.2/§2.2 table, as frozen `Rect`s + point sizes), `layout_for_slide(cls, lines)`, and
per-slide `set base layout of slide N to <layout>` instead of one blanket layout. Verse and
badge rects come from the slot, not the band. Tests: table values pinned to the numbers in
§1.2; class mapping table-driven. Offline A/B: verse slides' `text#0` rect becomes
(53.6, 866.4, 1799, 177) or (53.6, 967, 1812.9, 73); badge `text#1` x becomes 63.1 on every
verse slide (was 714 / 778 / 1312 in r12b). ~280 lines.

**L4 — pill (`Media`) offline write.** After the live pass, for each verse slide: ensure a
pill image exists (copy the layout's `Media` drawable into the slide's `ownedDrawables` via
`iwa_write`, reusing data id 27859), then set frame width = badge-text width + pad and mask
`{x: 1832.5315 − w, y: 50.9344, w, h: 75.52111}`, frame x 50.4, y 789.1 / 879.1. Refuse if
the resolved layout has no `Media` slot. Tests: mask law round-trip over the eight measured
widths; refusal path. Offline A/B: every verse slide gains one image whose
`x+mask.width == 1832.5315`. ~250 lines.

**L5 — heading-only and point classes (Q2, Q3).** Heading-only: 60 pt flat, badge 46 pt,
pair centred on x=960, badge above for 2 lines / inline-left for 1 line, on
`Point 3 Lines` / `Point (2 Lines)` per line count. Drop the Q3 0.75 badge scale — the verse
badge is now a fixed 40 pt slot. Recalibrate `wrapped_height` against the probe (drop
`_BOX_PADDING_PT` for heading boxes; 159.84 → ~130 for the measured case) **without**
touching the size-chooser rule `n_lines × 1.157 × s ≤ 140`, which reproduces gold exactly.
Tests: gold 39–42 reproduced; the estimator regression pinned to 130 ± tolerance.
Offline A/B: heading-only slides' heading size 60 and badge 46. ~220 lines.

**L6 — connection lines (PP7).** Add `TSD.ConnectionLineArchive` to `iwa_kindindex`
`_PBTYPE_KIND`/`KIND_ORDER` so the offline reader sees them, make `mirror_duplicates` dedupe
them (the +2446.70 pair on GW 7), and — because Keynote's sdef offers no scriptable handle —
**refuse** any kept slide that still has a connection line after dedupe, naming it. Tests:
GW 7 refusal with both lines reported; a synthetic single-line slide. Offline A/B: GW 7 moves
from "kept, silently wrong" to "refused". ~200 lines.

---

## §4 Acceptance rows for the live run (rXX)

Same CSV shape as `~/Desktop/dsk-d4-work/accept12.py` (`check,expected,actual,result`):

1. `imported layouts present` — expected the 6 `DEFAULT_DSK_LAYOUT_NAMES`, actual from
   `_theme_layout_slides` of the output; PASS on exact set.
2. `no duplicate imported layout names` — expected 0, actual count of case-insensitive
   duplicates among the imported names.
3. `every kept slide's base layout resolves` — via `templateSlide`; expected 0 unresolved.
4. `base layout per class` — per kept slide, expected the §2.2 layout, actual resolved name.
5. `every resolved layout alpha-safe` — expected all True.
6. `verse slot rects` — per verse slide, expected (53.6, 866.4, 1799.0, 177.0) or the 1-line
   slot, actual from `compose_geometry`, tolerance 1.0 pt.
7. `badge slot x` — expected 63.1 on every verse slide.
8. `pill mask law` — expected `mask.x + mask.width == 1832.5315` and `mask.height ==
   75.52111` on every verse slide's pill, tolerance 0.01.
9. `panel not slide-owned` — expected 0 slide-owned drawables of width > 1500 on verse/point
   slides (the panel must come from the layout).
10. `heading-only constants` — expected heading 60.0 pt and badge 46.0 × 46.0.
11. `autosize write order` — expected 0 `set height` lines for raw-autosize text and
    position-after-size in both emitters (assert on the emitted script, not the deck).
12. `builds preserved` — expected the r12b tolerated set unchanged; no new `missing` entries.
13. `GW 7 refused` — expected a refusal naming 2 connection lines.
14. **PNG read-back** — export slide images of 3 verse slides, 1 point, 1 heading-only and
    confirm by eye: rounded blue-grey panel, rose pill fitted to the badge text, white bold
    badge, yellow bold emphasis runs, superscript verse numbers.

---

## §5 Open questions for the owner (design-changing only)

**Q1 — two-column.** The template has no single heading+verse layout; it splits into
`Num Point with Verse-Pre` (number + full-width 75 pt heading) and `Num Point with
Verse-Post` (number + divider line + verse ref + verse, heading parked off-canvas). Gold
29/30/34 do it on one slide by hand on `Point 3 Lines`. Keep D1b's hand two-column (matches
gold; 450 pt left column, 46 pt badge, no divider), or adopt the template's two-slide
Pre/Post split (75 pt heading, 81 pt badge, divider at x=407.7)?

**Q2 — 4-line verses.** Gold 33 and 34 use a **267-tall** panel that exists in no layout
(available panel heights: 120, 163, 213). Options: (a) refuse and let the operator fix;
(b) keep hand-placing a 267 panel on `Blank Black`, as gold does; (c) split into two slides.

**Q3 — GW payload 7.** Its two curved connector arrows are `TSD.ConnectionLineArchive` with
builds and no scriptable handle. The `Elohim (plural)` dissolve and the `LineDraw` on the
cyan highlight box *can* be preserved (geometry-only writes keep builds) and would export
through `dsk_stage_export.py`, **but only if we do not write a text size on that slide** —
slide 17's `dissolve character` build was destroyed exactly that way. Accept a refusal for
GW 7, or accept the slide with the arrows dropped and the highlight box's LineDraw kept?

## Owner decisions (2026-09-14)

- **Q1 — two-column:** KEEP D1b's single-slide hand two-column (matches gold 29/30/34); do not adopt the Pre/Post split.
- **Q2 — 4-line verses:** SPLIT into two or more slides (reuse the existing split path with the layout's slot as the budget); never hand-place a 267 panel.
- **Q3 — GW payload 7:** KEEP THE ARROWS TOO. Connection lines survive copy-and-transform; since they have no AppleScript handle, piece L6 moves them OFFLINE after the live pass with the same affine as their sibling group (geometry-only write, builds preserved) instead of refusing. The slide's text must not be resized (character/line builds die on a size write) — refuse with a named reason only if its text does not fit unscaled.
- Live verification is deferred until Keynote is free (no Keynote 2026-09-14 ~11:50–12:50).
