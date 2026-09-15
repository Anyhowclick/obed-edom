# Opus review 2 — content placement by shape (`feat/dsk-placement-shape`, 861685c)

Read-only re-review of the fix commit `861685c` on top of `2298d29` (review 1's subject), in
`<scratchpad>/wt-placement`. No repo edits, no Keynote, no commits; probes in `<scratchpad>/probe2/`.

Suite run (venv `/Users/anyhowclick/Desktop/work/obed-edom/.venv`, `PYTHONPATH=src`):
`tests/test_dsk_assemble.py tests/test_dsk_content_rules_acceptance.py tests/test_dsk_plan.py`
→ **364 passed, 1 xfailed** (up from 356; the GW deck is present, so the `@pytest.mark.deck`
acceptance rows really ran, including the two new GW 16/22 rows).

## Verdict: **APPROVE-WITH-NITS**

All six review-1 findings are resolved in code, plan and tests, and the deck-wide behaviour is
right. What remains is that the *new* plan prose introduced by this commit contains two factual
errors about its own flip list (findings 1 and 2 below) — the plan of record is the thing the owner
eyeballs before the gold run, so these should be corrected before the commit is taken as the record.
No code change is required.

---

## Review 1 findings — verification

### R1-1 (blocking, per-item test flips GW 16/22) — **RESOLVED**

`_content_anchor` now measures the union (`dsk_assemble.py:405-412`), option (a) of the two offered.
Deck-wide probe over `Sermon_PK (GW).key` (`include_side=False`), comparing the retired count rule,
the per-item shape rule (2298d29) and the union rule as shipped:

| GW | count | per-item (2298d29) | union (861685c) | n | union aspect |
|---|---|---|---|---|---|
| 5, 15, 21, 32, 33, 42 | right | centre | **centre** | 1 | 3.56 |
| 24 | centre | right | **right** | 2 | 1.14 |
| 16, 22 | centre | right | **centre** | 2 | 3.56 (halves 1.77) |
| 48 | right | right | right | 1 | 1.50 |
| 2 | centre | centre | centre | 3 | 3.56 |

Every brief expectation holds: 5 centre, 21 centre, 32/33 centre, 24 right, 48 right — plus 16/22
corrected to centre. No other slide in the deck changes.

### R1-2 (blocking, stale count-rule text) — **RESOLVED**

All seven cited spots are updated with an explicit "superseded 2026-09-12" marker: the owner-answers
header (`dsk_content_rules.plan.md:9-10`), the golden-evidence paragraph (`:110-111`), the four
Acceptance rows for 48/24/21/5 (`:561-564`) and the coverage summary (`:611-613`).

### R1-3 (group semantics undocumented) — **RESOLVED**

D3 now states both the `_group_has_media` leaf test and the group-bbox-including-caption rect
(`dsk_content_rules.plan.md:317-322`), and `test_mixed_group_bbox_with_caption_centres`
(`tests/test_dsk_assemble.py:5011-5022`) pins it.

### R1-4 (side panels can flip the anchor) — **RESOLVED**

`_content_ids` drops side-panel items unconditionally via `is_side_panel_item`
(`src/obed_edom/dsk_assemble.py:365-387`), documented in D3 (`:320-322`) and pinned by
`test_side_panel_item_excluded_from_placement_with_include_side`
(`tests/test_dsk_assemble.py:5025-5037`), which is discriminating — without the filter the slide has
3 content items and would centre. Verified harmless on non-LW walls: `is_side_panel_item` returns
`False` unless `is_lw_wall`, and with `include_side=False` such items were never in `cls.kept`
anyway, so nothing else in the deck moves (probe: no GW slide's content union differs from
`fit_slide`'s union).

### R1-5 (test discrimination gaps) — **RESOLVED**

Boundary pinned in both directions — `test_lw_aspect_boundary_2_5_centres` (2000/800 = 2.50 exactly,
pins `>=` not `>`) and `test_lw_aspect_boundary_2_49_does_not_centre` (1990/800 = 2.4875);
`test_three_items_with_one_lw_still_centred` covers 3+-with-LW; `test_union_of_two_halves_diptych_centres`
is the unit-level GW 16 case and is discriminating against the per-item rule; the two new
`@pytest.mark.deck` rows (`test_gw16_diptych_union_centred`, `test_gw22_diptych_union_centred`)
pin it on the real deck.

### R1-6 (house-style nits) — **RESOLVED**

The four-quote docstring opener is gone (`dsk_assemble.py:395`), and "post-LW-crop" is replaced by
"the masked rect clipped to the panel" in the plan (`:324-326`).

---

## New findings (all in prose added by this commit)

### 1. (must fix, doc) The D3 flip table's own "new" column contradicts the shipped behaviour for GW 16/22 — `.agents/plans/dsk_content_rules.plan.md:361-362`

The table rows read:

```
| **16** | centre | **right** | 2 | halves 1.77/1.78, union 3.56 → **centre** |
| **22** | centre | **right** | 2 | halves 1.77/1.78, union 3.56 → **centre** |
```

Under the column header "new (union shape)" the value is **right**, which is the *per-item* result
this commit deliberately rejected; only the trailing aspect cell says `→ centre`. A reader scanning
the column — which is exactly how the owner will use it at gold-run time — reads the opposite of
what ships. Measured: both slides are `centre` (probe above).
Fix: put `**centre**` in the "new (union shape)" column for 16 and 22, and move the per-item result
into the aspect/notes cell (e.g. `halves 1.77/1.78 → per-item right; union 3.56 → centre`).

### 2. (must fix, doc) "Ten slides change anchor" is wrong — seven do — `.agents/plans/dsk_content_rules.plan.md:366-367` and `:576-582`

Against the retired **count** rule, the slides whose anchor changes are 5, 15, 21, 32, 33, 42
(right→centre) and 24 (centre→right) = **seven**. GW 16 and 22 are `centre` under the count rule and
`centre` under the shipped union rule — net **unchanged**; 2 and 48 are unchanged as well. The "ten"
figure is carried over from review 1, where it counted the *per-item* commit's flips (nine by my
count, and that number was itself loose). The follow-on sentence at `:578-580` compounds it:
"16/22 centre→right→centre via the union fix" describes an intermediate state that never ships.
Fix: say "seven GW slides change anchor vs. the retired count rule (5/15/21/32/33/42 right→centre,
24 centre→right); 16/22 and 2 stay centre, 48 stays right. 16/22 are unchanged only because the
union reading was chosen — a per-item reading would have flipped them to right, which is the
decision awaiting owner confirmation." The "owner should eyeball" guidance is right either way.

### 3. (nit) `_content_anchor`'s docstring overclaims union identity — `src/obed_edom/dsk_assemble.py:397-399`

"the same union `fit_slide` lays out" is not exact: `fit_slide` is called with `wall=` and unions
`_filter_kept_items`'s full kept set (text boxes, badge shapes, and with `--include-side` the side
images), whereas `_content_anchor` unions only the content ids with side panels removed. On the GW
deck the two coincide on every slide (probed), and with `include_side=True` they deliberately do
not. Suggested wording: "the union of the kept *content* rects — the same clip `fit_slide` uses,
restricted to content". The same claim appears in the plan (`:325-326`) and in the test-section
header comment (`tests/test_dsk_assemble.py:4913-4915`).

### 4. (nit) `plan_assembly` already has `items_by_id`; `_content_anchor` rebuilds it — `src/obed_edom/dsk_assemble.py:401` vs `:483`

Identical dict comprehension, built twice per slide. Harmless (small n), and keeping
`_content_anchor(cls, items, ...)` callable from tests with a bare item list is a fair reason to
leave it. Noted only so it is not re-found; no action needed.

### 5. (nit) `_content_ids`' new `items_by_id`/`wall` are positional — `src/obed_edom/dsk_assemble.py:365-370`

`_content_anchor` right beside it makes `include_side`/`wall`/`group_signature` keyword-only; the
private helper now takes two positional context args before the optional `group_signature`. Making
`wall` keyword-only would match the neighbouring style. Cosmetic.

### 6. (nit) The D3 heading spans two source lines — `.agents/plans/dsk_content_rules.plan.md:317-319`

`### D3. Placement by SHAPE (owner correction 2026-09-12, supersedes "placement by count";` with the
"UNION reading applied per opus review 1 finding 1 …" continuation on the next lines renders as a
truncated heading plus a stray paragraph. Put the parenthetical on the heading line or move it to
the first body sentence.

---

## What is right

- Union measurement matches what is actually laid out for every GW slide; the LW threshold, the
  1–2/3+ fallback, zero-content → centre, `--anchor` and `--no-auto-anchor` precedence are unchanged.
- Degenerate rects are skipped before the union (`:408-412`) and an all-degenerate content set falls
  through to the count branch rather than dividing by zero.
- Side-panel exclusion is unconditional and therefore independent of `--keep-side-panels`, which is
  the "side panels never anchor" decision of record.
- `_content_item_count` has no remaining callers in `src`, `tests` or `dashboard`.
- The whole flip set is now recorded in the plan (the substance is right; only the table cell and
  the count in findings 1–2 are wrong), which review 1 asked for.
