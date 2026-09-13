# Opus review 1 — piece D1 (commit 4055328, `feat/dsk-gen`)

## Verdict: **REVISE**

The core of Design A steps 2/3/4/8 is right and I could not fault the AppleScript shape, the
group's exclusion from the affine path, or the GW 5 acceptance geometry — I reproduced all of it
on the real deck. Two things block approval: the new badge placement rule produces an **actual
overlapping layout on GW 51**, and the smoke test's exclusion list + comment **misstate what the
deck does** (GW 51 plans fine; it was excluded anyway and the comment says it refuses).

All evidence below is from offline probes against `~/Desktop/Diff-Checker/Sermon_PK (GW).key`
(`<scratchpad>/probe_d1.py`, `probe2_d1.py`..`probe6.py`). No Keynote, no repo edits.
Targeted suite re-run green: `421 passed, 1 skipped, 1 xfailed`.

---

## What I verified (brief items 1–9)

**(1) Classification on the real deck — correct.**
Text slides now include `5, 44, 50, 51, 53, 54`, each with `long_text_ids == (('groupchild', 0, 1),)`.
GW 3/4 do **not** become text slides: both are `skipped` slides, so `classify_slide`
(`dsk_plan.py:396`) returns `empty` before filtering. I confirmed this is **pre-existing**, not a D1
regression — re-running the same classification against `HEAD~1`'s sources gives `3 empty / 4 empty`
there too. (`_filter_kept_items` called directly on slides 3/4 *does* return `is_text=True` with the
groupchild long id, so the only thing standing between them and a text slide is the skip flag.)

Dedupe ahead of the classifier: **works, and the bug fix is real.** GW 50/51 both give
`dropped_duplicate == (('group', 1),)`, `kept` without `('group', 1)`, and long ids containing only
`('groupchild', 0, 1)` — `('groupchild', 1, 1)` is gone. Without `dsk_plan.py:181-186` it would have
survived.

**(2) AppleScript shape — correct.** Generated script for GW 5 (verified by building the real
script):
- `text item 2 of group 1 of slide 1` gets `set width` → `set position` → four
  `set size of characters i thru j of object text` writes. **No `set height`** anywhere in the verse
  block. Write order matches the top-level stacked-text path (`dsk_assemble.py:1538-1553`).
- `shape 1 of group 1 of slide 1` gets `set position` only.
- Each child is wrapped in its own `_locked_write_block` (`theObj`/`wasLocked`) nested inside one
  group-level block (`theGroupObj`/`wasGroupLocked`) — same structure as `_group_known_child_lines`,
  with distinct variable names so the nesting is safe.
- Run ranges are contiguous and cover the full text (1–3, 4–33, 34–89, 90–141 at 33.6/33.6/40.8/33.6).

**(3) No affine path, and no blind loop.** `('group', 0)` is absent from `plan.fits[5]`, the script
contains no `iWork items of group 1 of slide 1` and no `(width of theObj)` live read. `_delete_order`,
`_restore_crop_zorder` and the stroke census are untouched by group children (deletes/crops are built
from top-level ids only; the stroke census works on the output object graph). `_staged_kind_ranks`
correctly skips `groupchild` (`dsk_assemble.py:2363`), and `_offline_measure`'s staged-vs-offline text
count cross-check is unaffected because `offline_text_rects` only ever sees top-level items.

**(4) Badge geometry.** The verse rect really is `x=43.0, w=1849.0` — identical to GW 13's golden
verse box. The badge is exactly centred (`x=644.99, w=645.03` → centre 967.5 = band centre). See
finding 1 for why "centred" is not defensible as written.

**(5) GW 5 acceptance numbers — met.** verse `y=821.96`, bottom `1054.00`; badge `y=719.96`,
bottom `811.96`; band top `704.0`. Badge above verse, both inside the band, no crop
(`plan.crops.get(5) is None`), deletes `= (image 2, image 1, image 0, shape 0)`, group kept.

**(6) Refit exclusion — safe, but unrecorded.** `_eligible_refit_items` filtering `groupchild` means
no `KeyError` and no vacuous overflow: the eligible-key set for GW 5/54 is empty, so
`_refuse_on_missing_measures` never fires on them. See findings 5 and 6.

**(7) GW 44/50 refusals are correct behaviour, GW 51 is not a refusal at all.** See findings 2 and 3.

**(8/9)** See findings 8–11.

---

## Findings

### 1. (major) Centred badge collides with other short-row content — real on GW 51
`src/obed_edom/dsk_assemble.py:655-659`

The badge is placed at `band.x_min + (band.width - badge_w) / 2`, ignoring every other occupant of
the short row. On GW 51 the short row also holds the kept `Faith` title and its number/bullet:

```
('text', 1)        x 232.5 .. 730.9   y 736.7 .. 983.3
('groupchild',0,0) x 645.0 .. 1290.0  y 891.3 .. 983.3   <- badge
```

~86 pt of horizontal overlap in the same row band: the badge is drawn on top of the title. The plan's
short-row rule (step 3, `.agents/plans/dsk_pieceD.plan.md:100`) is "same `_short_row_rects` as today",
and `_short_row_rects` deliberately keeps each item's **own fitted x/w/h** — the badge is the only
entry in the row that gets an invented x.

For GW 51 the affine-fitted group rect is `x=1070.4, w=673.9`, which clears the title cleanly; for GW
53 it is `x=1488.3`; so mapping the badge through the group's own fit rect (`fit_slide` result for
`('group', ki)`, captured *before* it is popped) reproduces the source-relative placement and does not
collide. The wrinkle is GW 5/54 where the group is the only kept item and its fitted rect stretches to
the full band (`x=43, w=1849`), which would left-align the badge.

**Fix:** capture the group's own fitted rect before `fit.pop`, and place the badge at the group's
fitted x (offset by the badge's source offset within the group) whenever the slide has other
short-row content; centre it only when the badge is the sole short-row occupant. Whatever rule is
chosen, add an assertion/refusal that no two short-row rects overlap, and a test pinning GW 51's badge
x against the title's right edge.

### 2. (major) Smoke-test exclusion and comment are factually wrong for GW 51
`tests/test_dsk_assemble.py:1244-1251`, `1257`

The comment asserts 44/50/51 all refuse at the default floor. Reproduced with exactly the test's
arguments (`SlideDecision(number, "in_deck")`, `BAND`, `runs`, `deck`, `fw_deck`):

```
44 REFUSAL: grouped verse text does not fit the band at --min-text-pt 24.0
50 REFUSAL: grouped verse text does not fit the band at --min-text-pt 24.0
51 OK  (t=0.49, short_row_h=246.6)   <- plans successfully
```

GW 51 is excluded from the only real-deck smoke test for no reason, silently dropping coverage
(`checked == 57`; it should be `58` with 51 restored) — and 51 is precisely the slide that exposes
finding 1. **Fix:** remove `51` from the exclusion tuple, restore `checked == 58`, and correct the
comment to name only 44 and 50.

### 3. (medium) The 44/50 refusals are a real coverage regression and are recorded only in a test comment
`tests/test_dsk_assemble.py:1244`

I agree the refusals are *correct* behaviour, not a D1 bug: both slides now carry a full-band verse
plus a tall top-level title competing for the same band (GW 50's short row alone is 246.6 pt of a
350 pt band, GW 44's title is 375 pt at source), so the verse genuinely cannot fit at
`--min-text-pt 24`. But these two slides **planned before this commit and do not plan now**, and the
only record of that is a comment inside a test. The brief's rule of record is
`.agents/plans/dsk_pieceD.plan.md`, and the commit touches no plan file at all.

**Fix:** add a short "Known regressions / deferred" entry to `dsk_pieceD.plan.md` naming GW 44 and 50,
the measured cause, and that they are deferred past this brief's GW-5-only scope.

### 4. (medium) Plan step 3 deviation: *every* text child is stacked, not just the long ones
`src/obed_edom/dsk_plan.py:427-429`, `dsk_assemble.py:651-660`

Plan step 3: "Short children (badge, <= `text_slide_words`) go to `short_fit`; long children to the
stack." The implementation splits on **kind**, not on word count: every `kind == "text"` child becomes
a stacked full-band-width long id, and every non-text child goes to the short row. On this deck every
group is exactly one shape + one text child, so it is currently invisible — but a group carrying a
short text label plus a verse would stretch the label to 1849 pt across the band. **Fix:** apply
`_word_count(child text) > text_slide_words` when deciding stack vs short row, mirroring the top-level
rule; or record the deviation in the plan.

### 5. (medium) A group verse that overflows has no fallback at all — only a warning
`src/obed_edom/dsk_assemble.py:2620-2627`, `1502-1511`

The `groupchild:<g>:<k>` MEASURE/OVERFLOW key is correctly opaque to the log parser
(`dsk_assemble.py:3072-3079`), so an overflowing group verse produces
`slide N: text groupchild:0:1 overflow, height …` as a warning. But because the id is excluded from
`_eligible_refit_items`, it can never enter `todo`, so neither the refit loop, the `--text-fit shrink`
fallback, nor the `warn`-mode refusal can act on it. A verse that the offline estimator got wrong
therefore ships overflowing with a warning nobody is forced to read. The exclusion itself is the
brief's authorized fallback — the *silent* part is not. **Fix:** raise/refuse (or at minimum escalate
to an explicit `AssemblyRefusal` under `--text-fit warn`) when a `groupchild:` OVERFLOW line appears,
and record the "offline fit only, no live refit" decision in `dsk_pieceD.plan.md`.

### 6. (low, latent crash) `_build_refit_round` can put a 3-tuple id into `refits`
`src/obed_edom/dsk_assemble.py:2730-2736` → `1783`

`plan.short_fit` now contains `('groupchild', g, k)` badge entries, and `_build_refit_round` copies
every short-row rect into `slide_refits`. `build_refit_script` then does `kind, kind_index = item_id`
(`:1783`), which raises `ValueError: too many values to unpack` on a 3-tuple. It is unreachable today
only by accident: the same slide's `stacked_ids` always contains the verse groupchild, and
`_text_boxes(list(stacked), items_by_id)` at `:2681` is called **without** `group_children` /
`group_child_runs`, so the verse is dropped with a warning and the `len(boxes) != len(stacked)` guard
at `:2683` short-circuits. That guard is doing unintended load-bearing work. **Fix:** filter
`groupchild` ids out of `short_fit` inside `_build_refit_round` (and/or guard `:1783` explicitly), and
skip slides whose `stacked_ids` contain a groupchild rather than relying on the box-count mismatch.

### 7. (low) Unknown child kinds emit an invalid address; non-text children are placed unconditionally
`src/obed_edom/dsk_assemble.py:1392`, `651-660`

`_group_stacked_child_lines` uses `_AS_KIND_NAMES.get(child["kind"], child["kind"])`, so an unmapped
kind produces a bogus AppleScript address instead of being skipped — `_group_known_child_lines:1327-1329`
deliberately does `if not name: continue`. Relatedly, the badge loop gives **every** non-text child a
short-row rect, including an `image` or `movie` child. **Fix:** skip kinds `_AS_KIND_NAMES` does not
map, in both the plan loop and the writer.

### 8. (low) Misleading warning text for group children
`src/obed_edom/dsk_assemble.py:239-241`, `247-250`

`_run_size_ranges` formats `text {item_id[1]}`; for `('groupchild', 0, 1)` that prints `text 0` — the
**group** index, not the child. Same shape at `:717/:722`. **Fix:** format groupchild ids as
`groupchild {g}:{k}`.

### 9. (low) The affine-exclusion and `fit.pop` live inside the "all boxes resolved" guard
`src/obed_edom/dsk_assemble.py:636-647`

If a group child's font/size cannot be resolved, `_text_boxes` warns and skips it, `len(boxes) !=
len(long_ids)`, and the whole block is skipped — so the group's top-level fit entry is **not** popped
and it takes the affine (`_group_known_child_lines`/`_group_blind_child_lines`) path, *after*
classification has already dropped the slide's media as a text slide. That is a silently degraded
slide. Note `text_group_kis` (`:596`) *does* exclude the group from `group_children`/`group_origin`
bookkeeping unconditionally, so the group would fall into the **blind** branch with a scale computed
for a layout it no longer has. **Fix:** refuse explicitly when a text-triggering group's children do
not all resolve, or hoist the pop/exclusion out of the guard.

### 10. (nit) House style / small cleanups
- `dsk_assemble.py:1392`: `"text item" if child["kind"] == "text" else _AS_KIND_NAMES.get(...)` is
  redundant — `_AS_KIND_NAMES["text"] == "text item"` (`remap_keynote.py:47`).
- `tests/test_dsk_assemble.py:610`: `f"set height of theObj to"` is an f-string with no placeholder;
  and `script.split(verse_addr)[1].split("on error")[0]` is a brittle way to scope the assertion.
- Nested `_locked_write_block` bodies are emitted at the outer indent level (cosmetic only; matches
  the existing `_group_known_child_lines` behaviour).

### 11. (nit) Tests do not discriminate on the new decisions
Nothing asserts: the badge's x (so finding 1 is invisible to the suite), the `groupchild:<g>:<k>`
MEASURE key, `_eligible_refit_items` excluding groupchild ids, or `_text_boxes`' groupchild
font/size-unresolved warning path. The two new deck tests and the two synthetic ones are otherwise
well targeted — `test_group_verse_slide_refuses_without_group_children` and
`test_gw50_51_mirror_pair_dedupe_ahead_of_group_classifier` both fail for the right reason if their
logic is reverted.

---

## Summary of required changes before approval
1. Fix the badge x rule so it cannot overlap other short-row content (finding 1), with a GW 51 test.
2. Restore GW 51 to the smoke test (`checked == 58`) and correct the comment (finding 2).
3. Update `.agents/plans/dsk_pieceD.plan.md` for the GW 44/50 regression, the no-live-refit decision,
   and the stack-vs-short-row-by-kind deviation (findings 3, 4, 5).
4. Close the latent 3-tuple unpack in the refit path (finding 6).
Findings 7–11 are nits and can ride along.
