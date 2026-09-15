# Opus review 1 — content placement by shape (`feat/dsk-placement-shape`, 2298d29)

Read-only review of `git diff HEAD~1 -- src tests .agents` in `<scratchpad>/wt-placement`.
No repo edits, no Keynote, no commits. Probes live in `<scratchpad>/probe/`.

Suite run (venv `/Users/anyhowclick/Desktop/work/obed-edom/.venv`, `PYTHONPATH=src`):
`tests/test_dsk_assemble.py tests/test_dsk_content_rules_acceptance.py tests/test_dsk_plan.py`
→ **356 passed, 1 xfailed** (the GW deck *is* present, so the `@pytest.mark.deck` acceptance rows
really ran).

## Verdict: **REVISE**

The code implements the owner's 2026-09-12 sentence faithfully and the four expected GW slides land
where the brief says. Two things block approval: an unreported owner-visible flip on GW 16/22 that
the per-item reading of the rule produces (finding 1), and the plan of record still asserting the
superseded count rule in four Acceptance rows plus two prose lines (finding 2), which leaves the
plan self-contradictory against its own D3.

---

## Findings

### 1. (blocking) The per-*item* aspect test flips GW 16 and 22 to `right`, and nobody recorded it — `src/obed_edom/dsk_assemble.py:391-394`

Deck-wide probe of `_content_anchor` over `Sermon_PK (GW).key` (old count rule vs new shape rule,
`include_side=False`):

| GW | old | new | items | clipped aspects |
|---|---|---|---|---|
| 5, 15, 21, 32, 33, 42 | right | **centre** | 1 | 3.56 |
| 24 | centre | **right** | 2 | 0.55, 0.55 |
| **16** | centre | **right** | 2 | 1.77, 1.78 |
| **22** | centre | **right** | 2 | 1.77, 1.78 |
| 48 | right | right | 1 | 1.50 |
| 2 | centre | centre | 3 | 1.19 ×3 |

GW 16 and 22 are diptychs that **tile the whole centre panel**: `image2 (1912,-151,1920x1280)` +
`image3 (3840,-191,1920x1280)` on 16, `image0`/`image3` likewise on 22 — clipped to
`(1920,0,1912x1080)` and `(3840,0,1920x1080)`. Each half is 1.77 so the "any item >= 2.5" test
misses, and two items → `right`; but their **union is 3840x1080 = 3.56**, i.e. exactly the
LW-dimension composition the rule is meant to centre. Right-flushing a panel-wide two-up is almost
certainly not what the owner asked for, and neither slide appears in the expected list
(5/21, 32/33, 24, 48).

Note that `fit_slide` scales and places the **union** of the kept rects, not the items one by one
(`dsk_plan.py:775-780`) — so testing the union's aspect is both the closer match to what is actually
laid out and a strict superset of the owner's examples: union aspect is 3.56 on 5/15/21/32/33/42
(centre), 1.14 on GW 24 (`x` 1944..2988 × 919 → right), 1.50 on GW 48 (right), 3.56 on GW 2 (centre,
which 3+ already gave), and 3.56 on 16/22 (centre — the fix).

Fix, pick one and say which in the plan:
(a) measure the **union** of the kept content rects against `_LW_ASPECT_MIN` (one-line change:
`_union_rect(visibles.values())` instead of `any(...)`), which reproduces every owner expectation
and corrects 16/22; or
(b) keep per-item and get an explicit owner ruling on 16/22 before the gold run.

Either way this commit must carry the flip list the way the earlier one did (`dsk_content_rules.plan.md:537-542`
records the GW 7/37 and 44/50/51/53/54 flips). Ten slides change anchor here and the diff records none
of them.

### 2. (blocking) Stale count-rule text in `.agents/plans/dsk_content_rules.plan.md`

D3 was rewritten but the rest of the plan was not. Exact rows/lines still asserting the superseded
rule — three of them now contradict the green acceptance tests in this same commit:

- **line 530** `| 24 | R1 dedupe + Q3 centred | 4 → 2 images; centred |` — **wrong**, the test is now
  `test_gw24_dedupe_four_to_two_right` asserting right edge 1892.0.
- **line 531** `| 21 | ... single item → right-aligned |` — **wrong**, now centre (cx 967.5).
- **line 532** `| 5 | ... single item → right-aligned, right edge 1892.0 |` — **wrong**, now centre.
- **line 529** `| **48** | R1 image dedupe + Q3 right (wheelchair) | ... |` — outcome still correct,
  but "Q3 right" names the retired count rule; it is right now because 1.50 < 2.5 and n ≤ 2.
- **line 9** `Q3 placement by COUNT (one item → right, more → centred)` — the owner-answers header
  still states the superseded answer with no "superseded 2026-09-12" marker.
- **lines 108-109** "Only the **right edge = 1892** and the **count→placement** pattern are rule
  evidence" — the golden evidence paragraph still cites count→placement.
- **line 571** "Q3 right-by-count (21,48) and centred (24)" — the coverage summary; all three slides
  are now the opposite or differently derived.

### 3. Groups: what the code does, and what D3 fails to say — `src/obed_edom/dsk_assemble.py:356-375`

- media-only group → counts (`_group_has_media` requires an `image:`/`movie:` leaf in the signature);
- badge group (shape + text, no media leaf) → does not count — correct, and it is why GW 5's caption
  group is excluded;
- **mixed group (media leaf + caption text) → counts, and the rect measured is the group's whole
  bbox including the caption**, not the media leaf's. So a photo with a wide caption strip can read
  LW-dimension and centre the slide on the strength of its text. No GW slide trips this today
  (slide 2's three media groups measure 1.19 each), but it is a real semantic and it is undocumented.

The rewritten D3 (`dsk_content_rules.plan.md:317-318`) only says "images/movies/groups; text and
text-bearing badge shapes excluded" — it never states the `_group_has_media` leaf test (that lives
only in a review note at line 537) and says nothing about which rect a mixed group contributes.
Fix: one sentence in D3 — "a group counts only when it has an `image:`/`movie:` leaf; its measured
rect is the group bbox, caption included."

### 4. `include_side` lets side panels change the anchor — `src/obed_edom/dsk_assemble.py:388-394`, `dsk_plan.py:112-117`

Plumbing is *consistent*: `plan_assembly` passes `decision.keep_side`, and `assemble()` builds
`include_side` from the same decisions (`dsk_assemble.py:2814`), so `cls.kept` and the clip frame
agree. But the consequence is unstated: with `--keep-side-panels N`, the two side images are no
longer in `dropped_side`, so they enter `_content_ids` as content. A slide with one squarish centre
photo plus two kept side panels becomes 3 content items → `centre` instead of `right`, purely
because side panels were kept; and a kept side pair clipped against the full 7680-wide wall can also
supply an LW-dimension rect. GW 32 is immune (the movie is 3.56, centre either way) and GW 8 keeps
zero content items, so nothing in the deck exposes it today.
Fix: decide and record whether side-panel items are "content" for anchoring; if not, drop
`cls.dropped_side ∪ side items` from `_content_ids` when `include_side` is on, and add a test.

### 5. Test discrimination (step 9) — `tests/test_dsk_assemble.py:4911-4989`

Against the **old count rule** the new tests split as follows:
- discriminating: `test_two_squarish_items_right_aligned` (old centre → new right),
  `test_lw_dimension_item_centred` (old right → new centre);
- not discriminating vs the old rule, but each pins a distinct branch of the new one:
  `test_lw_item_among_squarish_centres` (fails if the `any(...)` LW check is removed, since 2 items
  would fall through to `right`), `test_three_squarish_items_centred` (pins the 3+ branch),
  `test_single_content_item_right_aligned` (retained pin).

Gaps worth one test each:
- **no boundary test on `_LW_ASPECT_MIN`**: nothing pins 2.5 itself (`>=`) or a 2.49 near-miss, so the
  threshold could drift to `>` or to 3.0 with a green suite;
- no test for the 3+-with-an-LW-item case, and none for a *mixed group* (finding 3) or for
  `include_side=True` (finding 4);
- `test_text_and_picture_slide_stacks_full_band_width` correctly pins the D3 text+picture clause
  (`_stacked_text_rects` takes its rect from `band`) — that one is fine as written.

### 6. House style (nits)

- `src/obed_edom/dsk_assemble.py:385` — the docstring opens `""""centre"|"right" for …`: four
  consecutive quotes. Valid, but re-word it (e.g. start `"""Auto anchor ("centre" or "right") …`).
- `src/obed_edom/dsk_assemble.py:387` — the docstring says "post-LW-crop"; verified *correct* in
  substance (the payload rect for an image/movie is already the masked rect,
  `iwa_geometry.py:373-379`, and `_visibles_by_kept` then clips it to the panel/wall — the same
  `(frame ∩ mask) ∩ panel` the crop uses), so brief item (1) passes. Still, "post-LW-crop" reads as
  if `plan_crops` had run; "the masked rect clipped to the panel" is what it is.
- `_content_anchor` takes `no_dedupe`/`no_drop_panel_backdrop`/`text_slide_words` implicitly via
  `cls.kept` while `fit_slide` re-derives its own filter from the `plan_assembly` flags. Pre-existing
  for every other `cls.kept` consumer, not introduced here — no action, noted only so it isn't
  re-discovered.
- `_LW_ASPECT_MIN = 2.5` placement and naming match house style; `_content_item_count` has no stale
  callers anywhere in `src`, `tests`, or `dashboard`.

---

## What is already right

- `_content_anchor` measures the clipped (mask-aware) rect, not the source rect — brief item (1) holds.
- Zero content items still → `centre`, matching the old behaviour; `--anchor` and `--no-auto-anchor`
  still win (`dsk_assemble.py:470-473`, `test_no_auto_anchor_flag_forces_centre`).
- The derived anchor is recorded in `plan.anchors` and logged per slide (`dsk_assemble.py:2827-2828`).
- All four brief expectations verified on the real deck: 5 centre, 21 centre, 32/33 centre, 24 right,
  48 right.
