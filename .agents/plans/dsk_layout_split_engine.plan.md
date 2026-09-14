# DSK layout milestone — the SPLIT ENGINE (Codex L3 review 2, findings 1, 2, 3, 6)

Status: planned (read-only design pass, 2026-09-14, worktree `dsk-gen`, branch `feat/dsk-gen`,
HEAD = the L4 merge `5f50311`; L3 rounds B+A are WIP `74f7b52`/`fb981aa`). No Keynote was
opened, no git was run. Every number below is reproduced by a script in the planner
scratchpad `plan-split/` (`s0_runaware_spans.py`, `s1_split_candidates.py`,
`s2_unresolved_and_groupchild.py`, `s3_gold_anchor.py`, `s4_vertical_alignment.py`,
`s5_builds_on_candidates.py`, `s6_r12b_calibration.py`) plus the ready-to-run live probe
`plan-split/probe_split_delete.applescript`.

Decks read (read-only): GW `~/Desktop/Diff-Checker/Sermon_PK (GW).key`, GOLD
`~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key`, TEMPLATE
`~/Desktop/Default Templates/2026_Lower-Thirds (ENG).key`, r12b output
`~/Desktop/dsk-d4-work/out-r12b/Sermon_PK_DSK.key` + `evidence-r12b/run.out`.

---

## §0 SUMMARY

1. **Gold is TOP-anchored, not bottom-anchored.** Every gold `Verse Standard` verse box is
   `kFrameAlignTop` at the slot's own y=866.4 on 1-, 2- and 3-line slides alike, and so is
   every GW split-candidate source box. A part therefore needs no content-height rect: write
   the slot x/w and `position = (slot.x, slot.y)`, no height, position last. Finding 2's
   suggested bottom-align is contradicted by the measurement (§1.3).
2. **The budget is a HEIGHT, not 3 lines.** Run-aware, eleven parts measure 177.2–303.6 pt
   against a 177 pt slot, and GW 28/30/36/52 plan a degenerate ONE-part "split" that deletes
   nothing and overflows by 11–22 pt undetected. Pack by height ≤ slot.h, ≤3 lines as a guard.
3. **Run-aware windowing is necessary, twice over:** GW 12 p0 and GW 30 p0 predict 3 and 2
   flat-45pt lines but wrap to 4 and 3 at the emitted mixed sizes. GW 49 is the only box with
   unresolved runs (4 of 5, 83 chars) and today emits the entire box at 25 pt, not 45.
4. **Builds are nearly a non-issue:** 12 of 14 candidates carry NO build on the split box
   (GW 20's two `KLNSparkle` are on dropped boxes). Only GW 5/54 carry one — `apple:dissolve`
   In on the **group** — which r12b proves survives size writes on its text child. Clone per
   part; refuse only a character-level build (r12b slide 17 banked it dead on a size write).
5. **Recommendation: keep the character-window design;** §2.6 costs the two alternatives.
6. **Owner question (design-changing):** we emit emphasis runs at **54.64 pt** (GW's 85/70
   ratio on a 45 pt lead) where **gold uses 50 pt**. Those 4.6 pt are exactly what push eight
   3-line parts from 177.2 to 188–199.5 pt over the 177 pt slot. Cap emphasis at gold's 50 pt
   and several slides stop splitting, or keep the source ratio and split more?

---

## §1 Measurements

### 1.1 Split candidates: flat-45 pt prediction (today) vs run-aware (proposed)

`s1_split_candidates.py` — one single-slide `plan_assembly(..., layout_policy="import")` per
slide, then each planned part's own `char_window` re-wrapped with the sizes
`_windowed_run_ranges` actually emits. Slot = `Verse Standard (Variation 2)` verse
(1799.0 × 177.0 @45 pt) or `Point 3 Lines` text (1812.9 × 177.0 @45 pt).

| GW | cat | parts today | part | emitted sizes | flat-45 lines | run-aware lines | run-aware h | vs 177 |
|---|---|---|---|---|---|---|---|---|
| 5 | verse | REFUSED (group child) | — | 45 / 54.64 | 5 | 5 | 303.6 | **+126.6** |
| 12 | verse | 2 | 0 | 45 / 54.64 | 3 | **4** | 251.6 | **+74.6** |
| 12 | | | 1 | 45 | 1 | 1 | 73.1 | ok |
| 18 | verse | 2 | 0 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 18 | | | 1 | 45 / 54.64 | 2 | 2 | 147.4 | ok |
| 19 | verse | 2 | 0 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 19 | | | 1 | 45 | 2 | 2 | 125.1 | ok |
| 20 | verse | 2 | 0 | 45 | 3 | 3 | 177.2 | +0.2 |
| 20 | | | 1 | 45 / 54.64 | 2 | 2 | 147.4 | ok |
| 28 | verse | **1 (no-op)** | 0 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 29 | verse | 2 | 0 | 45 | 3 | 3 | 177.2 | +0.2 |
| 29 | | | 1 | 45 / 54.64 | 1 | 1 | 84.2 | ok |
| 30 | verse | **1 (no-op)** | 0 | 45 / 54.64 | 2 | **3** | 199.5 | **+22.5** |
| 35 | verse | 2 | 0 | 45 | 3 | 3 | 177.2 | +0.2 |
| 35 | | | 1 | 45 / 54.64 | 2 | 2 | 147.4 | ok |
| 36 | verse | **1 (no-op)** | 0 | 45 / 54.64 | 3 | 3 | 188.4 | **+11.4** |
| 38 | verse | 3 | 0 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 38 | | | 1 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 38 | | | 2 | 45 | 1 | 1 | 73.1 | ok |
| 49 | point | 2 | 0 | **25** (see §1.2) | 3 | 3 | 107.8 | ok |
| 49 | | | 1 | **25** | 1 | 1 | 49.9 | ok |
| 52 | verse | **1 (no-op)** | 0 | 45 / 54.64 | 3 | 3 | 199.5 | **+22.5** |
| 54 | verse | REFUSED (group child) | — | 45 / 54.64 | 5 | 5 | 292.5 | **+115.5** |

Two line-count divergences (GW 12 p0: 3→4, GW 30 p0: 2→3) and eleven parts over the slot
height. The four `1 (no-op)` rows are slides where the box failed `fit_text_stack` at 45 pt,
produced a single chunk, and therefore emit a full-text "window" that deletes nothing — a
split that does not split.

`saved naturalSize` comparison: only GW 5, 28 and 52 of this candidate set were in the r12b
keep list `[5,13,17,21,24,28,32,33,44,46,48,50,51,52,53]`, and none of them was split in
r12b (the split path is new in L3 round B), so there is no saved per-part geometry to compare
against anywhere. §1.4 calibrates the estimator against r12b's saved heights instead; §4
probe H1 supplies the missing per-part live number.

### 1.2 Unresolved runs (`s2_unresolved_and_groupchild.py`)

| GW | box | box font / pt | runs | runs with no `size` | chars affected | resolved sizes |
|---|---|---|---|---|---|---|
| 12/18/19/20/28/29/30/35/36/38/52 | `text 1` | AzoSans-Regular 70 | 3–14 | **0** | 0 | 70 / 85 |
| 49 | `text 0` | ArgentCF-Bold 180 | 5 | **4** | 83 | 100 only |

GW 49 is the whole of finding 1's second half: `_windowed_run_ranges` skips the four
unresolved runs, finds one resolved 100 pt run, and (because `fallback` is overwritten by
*every* resolved run, whether or not it intersects the window) returns the scalar
`100 × 45/180 = 25.0` for the entire box — so both parts render at 25 pt, not the slot's
45 pt lead. Note the run fonts are also frequently `None` (5–10 of the runs on the verse
boxes); the run-aware wrapper must fall back to the box's own `item["font"]` for those, which
is what `s0_runaware_spans.py` does and what `_box_with_runs` already does for heights.

### 1.3 Where gold's verse text sits in the 177 pt slot (`s3_gold_anchor.py`, `s4_vertical_alignment.py`)

Every gold slide on `Verse Standard (Variation 2)` — 1-, 2- and 3-line alike:

| gold | lines | x | y | w | h (saved) | top-off | centre-off | bottom-off | valign |
|---|---|---|---|---|---|---|---|---|---|
| 14, 37 | 1 | 54.0 | 866.0 | 1838/1799 | 177.0 | −0.4 | −0.4 | −0.4 | `kFrameAlignTop` |
| 3, 11, 16, 17, 22, 24, 26, 28, 35, 38 | 2 | 54.0 | 866.0 | 1799–1838 | 177.0 | −0.4 | −0.4 | −0.4 | `kFrameAlignTop` |
| 9, 10, 21, 23, 25, 27, 36 | 3 | 54.0 | 866.0 | 1799–1838 | 177.0 | −0.4 | −0.4 | −0.4 | `kFrameAlignTop` |
| 5, 6, 7, 8 (`Verse 1 Line`) | 1 | 54.0 | 967.0 | 1813 | 73.0 | — | — | −3.4 | `kFrameAlignTop` |

The gold box's **raw** stored height is `0.0` with `naturalSize = (w, 177.0)` — the
raw-autosize signature `_raw_autosize_ids` keys on — and it stays 177.0 for one line as for
three. Its position y is the slot's y on every one of them. GW's own split-candidate boxes
(`s4`, GW 5/12/18/19/20/28/29/30/35/36/38/52/54) are all `kFrameAlignTop` with raw height
`0.0` as well. Per `iwa_geometry._autosize_rect`, for `kFrameAlignTop` **the stored y is the
visual top**, so a re-autosize after a delete can only move the box's *bottom*.

### 1.4 Estimator vs Keynote's own saved heights (`s6_r12b_calibration.py`)

r12b's six long written boxes, run-aware estimate (`Σ 1.157 × max_size_per_line + 21`) vs the
saved naturalSize height: slide 2 218.2 vs 219.0 (+0.8), slide 3 200.3 vs 186.0 (+14.3),
slide 4 217.7 vs 189.0 (+28.7), slide 7 212.6 vs 241.0 (**−28.4**), slide 11 143.2 vs 179.0
(**−35.8**), slide 15 168.2 vs 193.0 (**−24.8**). Gold's 3-line 45 pt case (gold 23) is
exact: core 156.2 + padding 21 = 177.2 vs a 177.0 slot.

**The estimator errs in BOTH directions by up to ~36 pt (roughly half a line).** It is good
enough to plan windows; it is not good enough to be the final authority. Hence §2.3: the
offline naturalSize read of the saved staging deck must cover split parts and must be able to
refuse.

### 1.5 Builds on the split candidates (`s5_builds_on_candidates.py`, `iwa_builds.deck_builds`)

| GW | builds on slide | on the split box / its group? |
|---|---|---|
| 12, 18, 19, 28, 29, 30, 35, 36, 38, 49, 52 | 0 | — |
| 20 | 2 × `KLNSparkle` In on `text#4`, `text#5` | **no** (both on dropped boxes) |
| 5 | 1 × `apple:dissolve` In on `group#0` | **yes**, on the group that owns the verse child |
| 54 | 1 × `apple:dissolve` In on `group#0` | **yes**, same shape |

Banked from `evidence-r12b/run.out`: GW 5's group dissolve **survived** the r12b run with its
identity unchanged, after D1 wrote width/size/position on that group's text child — so a
size write on a group child does not kill a group-level dissolve. GW 17's
`apple:dissolve character` build on `text#1` **died** on a text-size write (`tolerated_missing`).
Note the group build's `identity` is `('group', <the group's full content signature>)`, i.e.
it embeds the verse text — per-part deletes will change it (§2.4).

---

## §2 Design and decision

### 2.1 Run-aware line spans (finding 1)

New `dsk_plan.wrap_line_spans_runs(runs: Sequence[Run], width: float) -> list[LineSpan] | None`,
the span-returning sibling of `wrapped_height_runs`, sharing its tokeniser verbatim (same
`_WRAP_BREAK_CHARS`/`_PARA_BREAK_CHARS`/`_WRAP_MARGIN`/`_WRAP_OVERSAMPLE`, run-boundary words
never split by a synthetic space, so superscript verse numbers stay attached to their verse).
Each `LineSpan` is `(start, end, max_size)` over the **concatenated run text** — the same index
space `char_window` already uses. Prototype and reference implementation:
`plan-split/s0_runaware_spans.py` (used for every number in §1).

The runs handed to it are the runs the emitter will actually write: source run size × `t`,
with the unresolved policy already applied. So the resolution order is inverted from today's:

1. **Resolve sizes first, window second.** Compute the whole box's per-run emitted size table
   once (`_emitted_run_sizes(item, t, lead_pt, text_fit) -> list[(lo, hi, size)] | Unresolved`),
   then `_windowed_run_ranges` becomes a pure *restriction* of that table to `[start0, end0)`.
   It can no longer pick a fallback from a non-intersecting run because it no longer picks
   fallbacks at all.
2. **Unresolved-run policy, explicit** (Codex's prescription, adopted): a run with no `size`
   makes the table `Unresolved`. Under `--text-fit warn` → `AssemblyRefusal` naming the slide
   and box ("run sizes unresolved, cannot split"; GW 49 refuses). Under `--text-fit shrink` →
   flatten **every** run to the slot's lead size (45 pt), with a named warning. Never
   `100 × t`.
3. **Fonts:** a run with no `fontName` inherits the box's `item["font"]`; a box whose own font
   is unresolved refuses (today's behaviour, unchanged).

### 2.2 Part packing: a height budget, not a line count

Replace `chunks = [spans[i:i+3] ...]` with a greedy pack over run-aware spans:

```
budget = slot.h + _SPLIT_TOL (2.0, the tolerance the OVERFLOW emitter already uses)
height(lines) = Σ _LINE_HEIGHT_FACTOR × line.max_size + _BOX_PADDING_PT
```

Add lines to the current part while `height ≤ budget` **and** `len(lines) ≤ 3`; start a new
part otherwise. A single line that alone exceeds the budget refuses, naming the slide/box
(it cannot be fixed by splitting). The degenerate 1-part outcome becomes impossible: if the
pack yields one part, the box fits and the split branch must not be taken at all — make
`plan_assembly` re-check and fall back to the normal slot-fit path, so GW 28/30/36/52 either
split properly or fit, never emit a no-op window.

Note the `t` used for the 45 pt lead is unchanged (`split_pt / split_box.size`); only the
packing criterion and the span source change.

### 2.3 Part geometry and verification (finding 2)

**Geometry.** §1.3 settles it: every part gets the slot rect's `x`/`w` and
`position = (slot.x, slot.y)` — top of the slot — and **no height write** (autosize).
The emitted order is unchanged and already correct: `width → run sizes → character deletes →
position` (position last for autosize ids; the deletes are appended to `size_lines`, which for
an autosize id are emitted before the position line). This is exactly what gold's own boxes
look like, for every line count. Hypothesis to confirm live (§4 H1): a `delete characters`
on a `kFrameAlignTop` box leaves the frame's top where it is; position-last makes it moot
either way.

**Offline measurement and refit must cover split parts.** Today `_eligible_refit_items`
returns `frozenset()` for any slide in `plan.splits` and `_offline_measure` `continue`s on it,
so nothing verifies a part and a part's `OVERFLOW` record cannot refuse. Change:

* Key every measurement by **output ordinal**, using the key shape `_text_measure_lines`
  already emits for splits: `text:<srcIdx>:<ordinal>`. `_offline_measure` iterates
  `plan.ordinal_to_number` (not `plan.ordinals`), computes `_staged_kind_ranks(number, plan,
  part=ordinal - plan.ordinals[number], ...)` per ordinal, and emits split keys in that shape
  and unsplit keys in today's `text:<srcIdx>` shape.
* `_eligible_refit_items` gains the part's own `SplitPart.stacked_ids` per ordinal (group-child
  ids still excluded, per D1 step 6).
* `_refit_still_over_budget` reads a split key's rect from `plan.splits[n][part].fits`, and its
  band from the slot band (`plan.stack_bands[n]`, already the slot after L3 round B).
* A split part still over budget after `_MAX_REFITS`, or with no measurement at all, **refuses**
  under `--text-fit warn` (`_refuse_on_missing_measures` already refuses the missing case once
  the key is eligible). C5's "split is not re-run after a refit" stands: we correct the part's
  geometry, we never re-window live.

### 2.4 Builds on split boxes (finding 3)

Measured (§1.5), the policy is small:

1. **Refuse** when the split box (or, for a group child, the group) carries a build whose
   `effect` is character- or word-level (`apple:dissolve character` and any `effect` ending in
   ` character`/` word`, plus `KLNSparkle`-class text builds targeting the box). Banked dead on
   a size write (r12b slide 17). The refusal names slide, box and effect. No GW candidate hits
   this today, so it costs nothing and prevents a silent "unexplained missing build".
2. **Clone** every other build on the split box/group: each part keeps its duplicated copy.
   `_merge_split_part_builds` currently sums each part's long-box builds into `long_builds`
   and compares that sum against the single source build → surplus. Fix: for a `char_window`
   split, the long box is the **same source box on every part**, so the expected count is
   *one copy per part*. Collapse `long_builds` to one representative per
   `(effect, animationType)` and record the expected multiplicity, then have `_verify_builds`
   tolerate exactly `len(parts) − 1` surplus copies of it, consumed like the movie-start
   tolerance already is — never a blanket tolerance.
3. **Identity.** A group build's `identity` is `('group', <content signature>)` and the content
   signature embeds the verse text, so each part's clone gets a *different* identity from the
   source's. For a split slide's cloned build, match on `(kind, effect, animationType)` and
   require the part identity's text to be a contiguous slice of the source identity's text;
   report anything else as a genuine mismatch. This is the one new tolerance and it must be
   named in the run log ("slide N: cloned build on split part k, identity narrowed").

### 2.5 Group-child split — GW 5/54 (finding 6)

Both are one group (`group#0`) holding a short badge child and a long verse child
(`text` child 1), 5 lines at 45 pt (303.6 / 292.5 pt against a 177 pt slot) → 2 parts each.
The minimal correct design reuses everything above:

* `plan_assembly`'s char-window branch drops its `split_box.item_id[0] != "text"` refusal and
  its `any(box.item_id[0] == "groupchild" …)` guard for the single-box case; the window is
  computed from `groupChildRuns[g][k]` text/font/size/runs (already attached by
  `attach_group_child_runs`), exactly as `_text_boxes` does for the group-child `TextBox`.
* Emission goes through the existing `_group_stacked_child_lines` path, which already wraps
  every child write in a per-child unlock/relock inside one group-level lock/relock and already
  emits `width → run sizes → position` for a stacked text child. Append this part's
  `delete characters` lines between the size lines and the position line, addressed
  `text item k+1 of group g+1 of slide <ordinal>` — the same address the size write uses, so no
  new addressing risk. The badge child stays position-only.
* Per-part geometry: the verse child takes the slot rect's x/w and the slot's top y, like a
  top-level part (its composed geometry is the group origin plus the child rect —
  `_group_child_geometry`/`compose_geometry` already handle this on the verification side).
* Builds: the group's `apple:dissolve` is cloned per part under §2.4, including the narrowed
  identity.
* Measurement: no *live* refit for group-child text (D1 step 6 stands — there is no live
  fallback), but the **saved** part geometry is still checked offline via `compose_geometry` in
  `verify_staged_layouts_alpha_safe`, and a `groupchild:` OVERFLOW under `--text-fit warn`
  already refuses. So a group-child part is planned once, offline, with the run-aware estimator
  and its `_TEXT_SAFETY_PT` margin, and verified — never blindly written.

### 2.6 Alternatives, costed

* **`set object text` per part instead of character deletes.** Rejected. It discards the box's
  run styling wholesale — superscript verse numbers and every emphasis run would have to be
  rebuilt by character range afterwards, which is strictly more writing than the deletes we
  already do and reintroduces the exact index bookkeeping the window approach solves. Its
  effect on a box-level dissolve build is unknown and would need its own probe. It also breaks
  the copy-and-transform contract that keeps builds alive at all.
* **Refuse >3-line verses; require the operator's `--split N=k`.** Rejected: owner decision Q2
  is explicit — split into two or more slides, with no top-level-only exception — and it would
  regress GW 5/54, which render today.
* **Keep character windows (recommended).** The mechanism is already landed and the review's
  four objections are all fixable in-place: run-aware spans (§2.1), a height budget (§2.2),
  top-of-slot geometry with per-ordinal offline verification (§2.3), and a build policy that is
  a refusal for 0 of today's slides and a clone for 2 (§2.4/§2.5).

---

## §3 Pieces (one sonnet each, in order)

**S1 — run-aware spans + the unresolved-run policy (~260 lines).**
`dsk_plan.wrap_line_spans_runs` (port `plan-split/s0_runaware_spans.py`, sharing
`wrapped_height_runs`' tokeniser), and in `dsk_assemble` a single
`_emitted_run_sizes(item, t, lead_pt)` table with `_windowed_run_ranges` rewritten as a pure
restriction of it. Tests: a mixed-size box whose flat-45 wrap and run-aware wrap differ
(GW 12's own text, expected line counts 3 vs 4 written as literals, not recomputed);
a window whose only resolved run lies outside it (asserts the fallback is the 45 pt lead, not
that run); GW 49 refuses under `warn` and flattens to 45 pt with a named warning under
`shrink`; run `fontName=None` inherits the box font. Offline A/B: `run_sizes` lines change on
GW 49 only (25 → refusal/45); every other candidate's emitted sizes are byte-identical.

**S2 — height-budget packing, and no more no-op splits (~200 lines).**
Replace the 3-line chunker with the greedy height pack (§2.2); refuse a single over-budget
line; when the pack yields one part, fall back to the non-split slot-fit path. Tests: the §1.1
table pinned per slide as expected part counts and per-part line counts (literal, not derived
from the function under test); GW 28/30/36/52 no longer produce a 1-part split; an
over-budget single line refuses. Offline A/B: part counts on GW 12/18/19/28/30/36/38/52 change;
GW 20/29/35/49 unchanged.

**S3 — part geometry + per-ordinal offline measurement and refusal (~300 lines).**
Part rect = slot x/w at the slot's top y, no height (§2.3). `_offline_measure`,
`_eligible_refit_items`, `_refit_still_over_budget` and `_refuse_on_missing_measures` all keyed
by output ordinal with the `text:<idx>:<ordinal>` key shape. Tests: a two-part fixture where
part 1's saved naturalSize exceeds the slot → refusal under `warn`; a part whose measurement is
absent → refusal; emitted-script test pinning `width → size → delete → position` order for a
part and asserting no `set height`; the part rects pinned to (53.6, 866.4, 1799.0). Offline
A/B: split slides gain MEASURE/refit coverage; no geometry change on unsplit slides.

**S4 — build policy on split boxes (~220 lines).**
The §2.4 refusal (character/word-level build on a split box) and cloned-build semantics in
`_merge_split_part_builds` + `_verify_builds` (per-part multiplicity, narrowed identity,
consumed tolerance). Tests: a synthetic split slide whose box carries
`apple:dissolve character` refuses, naming box and effect; a 3-part split whose box carries a
whole-object dissolve verifies clean with exactly 3 copies and refuses with 2 or 4; a cloned
group build whose part identity is a slice of the source's verifies, and one whose identity is
unrelated refuses. Offline A/B: GW 20's `KLNSparkle` builds stay untouched (not on the split
box); no other candidate's build report changes.

**S5 — group-child split, GW 5/54 (~280 lines).**
§2.5: drop the two group refusals for the single-box case, window from `groupChildRuns`, emit
the deletes inside `_group_stacked_child_lines` between the size and position lines, per-part
geometry, group build cloned per part, offline `compose_geometry` verification of the part's
composed child rect. Tests: GW 5 and GW 54 plan 2 parts each with pinned windows and line
counts (2 + 3 lines); the emitted script addresses `text item 2 of group 1 of slide N`, keeps
the lock/unlock nesting, and orders width → size → delete → position; the badge child stays
position-only; GW 5's group build is cloned twice. Offline A/B: GW 5/54 move from REFUSED to a
2-part split on `Verse Standard (Variation 2)`.

---

## §4 Live probes needed

`plan-split/probe_split_delete.applescript` (same shape as the 2026-09-14 autosize probe;
needs a `probe.key` copy of the pristine GW deck beside it; logs `OBEDSPLIT` lines to
`plan-split/probe_split_log.txt`).

* **H1 — does a `delete characters` re-autosize around the centre, like a size write?**
  Arms on GW 38's verse box: initial → width → size → tail delete → head delete → position →
  delay. PREDICTION (from §1.3's `kFrameAlignTop`): `height` shrinks at each delete while the
  reported `position` y does **not** move. If y *does* move by about half the height delta, the
  box behaves middle-anchored and §2.3's "position last" is not merely tidy but load-bearing —
  the plan is unchanged either way, but the acceptance row's tolerance would tighten.
* **H2 — does position-last settle the frame?** PREDICTION: `F_after_position` y equals the
  written 866.4 and `G_after_delay1` is identical to it.
* **H3 — does a group-child character delete kill the group's dissolve build?** Arms on GW 5's
  group 1 / text item 2, then saves. PREDICTION: the build survives (r12b banked the same
  group's dissolve surviving size writes on this very child); its `identity` changes to the
  surviving half of the verse text. Read back after the run with
  `deck_builds('<plan-split>/probe.key')[5]`. A dead build here would force §2.4 case 1 to
  cover group-level builds too, i.e. GW 5/54 refuse instead of split — **the one probe result
  that would change the design.**

---

## §5 Acceptance rows for the live run (rXX)

Same CSV shape as `~/Desktop/dsk-d4-work/accept12.py` (`check,expected,actual,result`).

1. `split part counts` — expected the §1.1 part counts per GW candidate (as revised by S2),
   actual from `plan.parts`; exact match.
2. `no no-op splits` — expected 0 slides with `len(plan.splits[n]) == 1`.
3. `every part's verse rect` — expected (53.6, 866.4, 1799.0) x/y/w on every split part's verse
   box (or the `Point 3 Lines` slot for point slides), actual from `compose_geometry` on the
   saved output; tolerance 1.0 pt.
4. `no set height on a part` — expected 0 `set height` lines for any split part's long box
   (assert on the emitted script).
5. `part height within the slot` — expected every split part's saved naturalSize height ≤ 179.0
   (177 + the 2.0 pt tolerance); actual from the offline read.
6. `part text is contiguous and complete` — expected the concatenation of the parts' rendered
   texts, in ordinal order, to equal the source box's text; actual from the output deck.
7. `run sizes on every part` — expected 45.0 lead with emphasis at the agreed emphasis size
   (54.64 today, 50.0 if the §0 owner question is answered "cap"); expected 0 parts emitting
   25.0 (GW 49).
8. `GW 49` — expected a refusal naming the box under `--text-fit warn`, or all runs at 45.0
   under `shrink`.
9. `GW 5/54 split` — expected 2 parts each on `Verse Standard (Variation 2)`, no refusal.
10. `cloned builds` — expected exactly one `apple:dissolve` In per part on GW 5/54's group,
    `len(parts)` copies total, with each part identity a slice of the source identity; expected
    0 unexplained missing/surplus builds deck-wide.
11. `no character-level build on a split box` — expected 0 (a refusal if any appears).
12. **PNG read-back** — export both parts of GW 38 and both of GW 5 and confirm by eye: the
    verse text starts at the panel's top edge exactly as gold's does, no clipped line, the badge
    and pill unchanged between parts.

## Owner decisions (2026-09-14 17:30)

- **Emphasis size: CAP at gold's 50 pt** on a 45 pt lead (do not carry the source 85/70 ratio). Fewer slides split; matches gold.
- Live probe (§4) approved and run immediately; results appended below by the orchestrator.
- **Probe results (17:35, `.agents/reviews/dsk-layout/probe-split-delete-2026-09-14.log`):** H1 CONFIRMED — on GW 38's verse each `delete characters` shrank `height` (385 → 281 → 177) with `position` y unchanged (top-anchored); H2 CONFIRMED — `set position {54, 866}` read back {54, 866} after a 1 s delay; H3 CONFIRMED — GW 5's group `apple:dissolve` build survived a tail delete on `text item 2 of group 1` (identity now the surviving half of the verse text) → GW 5/54 SPLIT (design §2.5 stands). Keynote's `size of object text` read on a mixed-run box reports the smallest run (30) — read-back is not a size authority.
