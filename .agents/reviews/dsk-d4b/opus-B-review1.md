# opus-B review 1 — d4b piece B (steps 4–7), worktree dsk-gen @ 6106b88 + uncommitted diff

**Verdict: REVISE.**

Reproduced: scoped 305 passed, full suite 2166 passed / 84 skipped. Regression check clean —
`plan_assembly` fits/text_sizes/deletes are **byte-identical to HEAD** on the non-text slides
3,5,21,24,48,50,57,58,61 (diffed HEAD `src` via `git archive` against the worktree). Split ordinal
arithmetic, descending-duplicate emission and `ordinal_map(keep, parts)` are correct as written.
The findings below are in the text path, not the assembly path.

---

## HIGH

### 1. Mixed-run text is silently FLATTENED on every GW verse slide
`dsk_assemble.py:414` (`slide_text_sizes.update(stacked_text_sizes)`) + `:956`
(`set size of object text of theObj to …`).

The pre-existing path deliberately refused to write a size when a box had >1 distinct run size
(`dsk_assemble.py:406-412`: warn `"mixed run sizes"`, `continue`). The stacked path bypasses that
guard entirely and unconditionally injects a single size, and `set size of object text` applies to
the **whole** text object.

Evidence (probe over `Sermon_PK (GW).key`): *every* long verse box in the deck is mixed-run —
GW 7,8,10,11,12,13,14,17(×2),18,19,20,28,29,30,35,36,37,38,46,52 all have runs `[70.0, 85.0]`.
`plan.text_sizes[13][("text",1)] == 70.0` is now written, so the 85 pt emphasis run is flattened to
70 pt on the DSK deck. No `mixed run sizes` warning is emitted either, because the loop `continue`s
past stacked ids at `:381`. This contradicts "template gives size, **source gives style**".

Fix: scale **per run**, not per object — emit `set size of text i thru j of object text of theObj`
per run range (run offsets are already available via the `runs` mapping plumbed into
`plan_assembly`), or, as a minimum, fall back to the existing warn-and-skip behaviour for mixed-run
boxes and keep the geometry stretch only.

### 2. The stacked box overlaps the badge on GW 13 — the owner's reference slide
`dsk_assemble.py:143-157` (`_stacked_text_rects`).

Long boxes are laid from `band.bottom` upward with no regard for the short items, which keep the
generic affine. Measured plan output for GW 13:

- badge `("text",0)`/`("shape",0)`: `(44.8, 740.4, 651.2, 81.5)` → bottom **821.9**
- stacked verse `("text",1)`: `(43.0, 790.0, 1849.0, 264.0)` → top **790.0**

31.9 pt of vertical overlap, and full horizontal overlap (44.8–696 inside 43–1892). GW 17 and 38
happen to clear; 13 does not. `test_john17_after_dedupe_does_not_overlap` only checks long-box vs
long-box, so nothing catches this.

Fix: reserve the short items' occupied height — stack the long boxes upward from `band.bottom` but
cap the stack top at `min(short_rect.y)` for short items that overlap in x, and feed that reduced
height into `fit_text_stack` as the budget (not `band.height`). Add an assertion to the GW-13 test
that no stacked rect intersects any short-item rect.

### 3. The live OVERFLOW read-back is suppressed for exactly the boxes the estimator sized
`dsk_assemble.py:963` (`if kind == "text" and item_id not in text_sizes: … _text_overflow_lines`)
and `:381` (`if iid[0] != "text" or iid in stacked_ids: continue`).

Because stacked boxes are now *in* `text_sizes`, the overflow read-back is never emitted for them,
and they are excluded from `shrink_text_sizes` so `--text-fit shrink` is a no-op on them too. Net:
the predictor-sized boxes are the **only** boxes in the deck with zero live feedback. The owner rule
is the opposite — "the wrap estimator is a predictor only, the live OVERFLOW read-back stays the
authority".

Fix: emit `_text_overflow_lines(number, kind_index, addr, rect.h)` for stacked ids regardless of
their presence in `text_sizes` (change the guard to `item_id not in text_sizes or item_id in
stacked/split ids`), and make `--text-fit shrink` re-derive a shrink size for them.

### 4. A build on a repeated short item refuses the whole assembly on any split slide
`dsk_assemble.py:1583-1598` (merge) + `:1605-1638` (surplus, no tolerance path).

Plan D4 mandates the badge/short items be repeated on **every** part. Merging the parts per source
number therefore counts a badge build N times against a source count of 1 → `real_surplus` →
`AssemblyRefusal`. Reproduced synthetically:

```
AssemblyRefusal builds verify surplus on assembled deck:
 [{'slide': 17, ..., 'identity': ('text', 'BADGE'), 'count': 1}]
```

`test_verify_builds_merges_split_parts` only exercises builds on the *long* boxes (one per part), so
it passes vacuously against this case. GW 17's two `dissolve character` builds sit on the long boxes
so the forced-split acceptance run escapes, but GW 7 (4 builds) and GW 20 would not.

Fix: when a slide has `plan.splits`, de-duplicate the merged builds for items that are **retained on
every part** (the intersection of the parts' fit ids) — count them once — or tolerate surplus up to
`parts[number] - 1` for identities whose source item is in that intersection. Add the badge-build
case as a test.

### 5. Split ordinals are invisible to the stroke pass and the alpha-safe pass
`dsk_assemble.py:1190` and `:751-753`.

- `_restore_stroke` still builds `inverse_ordinals = {ordinal: number for number, ordinal in
  plan.ordinals.items()}`. With 13/17(split)/21 that is `{1:13, 2:17, 4:21}` — ordinal **3**
  (part 2) resolves to `None`, so part 2's card styles are re-keyed to the `-3` sentinel and fail the
  kept-subset check, and its media census is recorded as `(-3, True)` (foreign). Plan D4 names this
  explicitly: "`_restore_stroke`'s `_rekey_slides` takes the same extended inverse map". Not done.
- `_staged_retained_ids(number, plan)` (`:1535`) reads `plan.fits[number]` / `plan.deletes[number]`,
  which for a split slide are the **unsplit** dicts — so even part 1's staged kindIndex ranking is
  computed from a fit set that still contains the other long boxes. Wrong staged indices → wrong
  retained/foreign verdict for the stroke restore.
- `verify_staged_layouts_alpha_safe` (`:751`) iterates `plan.kept` and checks only
  `plan.ordinals[number]`; part 2+ slides are never alpha-checked at all.

Fix: use `plan.ordinal_to_number` in `_restore_stroke`; give `_staged_retained_ids` a `part`
argument that reads `plan.splits[number][part]` when present; iterate `plan.ordinal_to_number.items()`
in `verify_staged_layouts_alpha_safe`. Also `AssembleResult(ordinals=plan.ordinals)` (`:1794`) under-
reports the split parts in the run log.

---

## MEDIUM

### 6. The +1-line margin is charged at full box height, so the band is left a third empty
`dsk_plan.py` `fit_text_stack` (`total += h + _LINE_HEIGHT_FACTOR * size` per box) vs
`dsk_assemble.py:145-157` `_stacked_text_rects` (no margin).

Measured GW 17: `t = 0.73` (51.1 pt, from a 70 pt source) and the written rects are
`(43, 824.6, 1849, 139.2)` + `(43, 973.9, 1849, 80.1)` — **229.3 pt used out of a 350 pt band**.
The text was shrunk 27% and 120 pt of band was then left blank. F9 predicted t = 0.91 for this slide
at a 20 pt floor with no margin; the declared "deviation" is really this design: on 2–3 line boxes a
per-box +1 line is a 30–50% height reservation, not a ±1 line safety allowance.

This is also the one place the margin is *not* applied consistently: it governs the fit decision but
not the written height. Writing the un-margined height is the risky direction (predictor 1 line short
→ Keynote overflows the box), which finding 3 then hides.

Fix: charge the margin **once for the stack**, not once per box, and write the margined height into
the rect so the fit decision and the geometry agree. Then re-derive the expected `t` values.

### 7. `min_text_pt` refuses a box that is already below the floor and fits trivially
`dsk_plan.py` `fit_text_stack`: `if any(s < min_text_pt for s in sizes.values()): return None` runs
on the **first** iteration at `t = 1.00`.

```
20pt box, floor 24 -> None          # would then raise "does not fit the band even alone"
20pt box, floor 10 -> (1.0, {…: 20.0})
```

The floor is meant to bound *downscaling*, not to reject source text that is already smaller. With
the new default of 24 this is a live refusal risk on any deck with sub-24 pt body text.

Fix: `min_size = min(min_text_pt, min(box.size for box in boxes))`, i.e. never refuse at `t == 1.0`
on the floor alone.

### 8. The base glyph size comes from the leading char/para style, not the runs
`dsk_assemble.py:170-180` (`_text_boxes` reads `item["size"]` / `item["font"]`).

`offline_inspect.py:113,227-228` documents `size`/`font` as the **leading run** style. GW 49's box
reports lead `ArgentCF-Bold @ 180.0` while its only real run size is `100.0`. Because the search
starts at `t = 1.00` this is an *upscale* hazard: a box whose leading style overstates the real size
and whose text happens to fit would be written at 1.8× its source glyph. (GW 49 escapes only because
it doesn't fit and comes down to `t = 0.31` → 55.8 pt.) `plan_assembly` already receives `runs`;
`_text_boxes` ignores it.

Fix: derive the base size from `runs[number][iid]` (max, or the dominant run) with the payload
`size` only as fallback; this pairs with finding 1's per-run write.

### 9. Font index deviates from the plan and misses `.ttc`
`dsk_plan.py` `_build_font_index`.

D4 specifies an index "built from each file's `ImageFont.getname()`"; the implementation matches on
the normalised **filename stem** instead (with a `" - "` prefix strip for the `Rui Abreu - ` files).
Undeclared deviation. Consequence: a PostScript name that differs from its filename silently fails to
resolve and the slide falls back to affine-only with a warning — a quiet behaviour change rather than
a refusal. Also only `.otf`/`.ttf` are scanned; `/System/Library/Fonts` is largely `.ttc`.

Fix: index by `ImageFont.truetype(path).getname()` as planned (cache it), keep the stem match as a
secondary key, and add `.ttc` to the suffix set.

### 10. The 10 pt stack gap is defined twice, in two modules
`dsk_assemble.py:68 _TEXT_STACK_GAP = 10.0` and `dsk_plan.py _TEXT_GAP_PT = 10.0`. `fit_text_stack`
uses one and `_stacked_text_rects` the other; changing either silently desynchronises the fit budget
from the written geometry. Import the `dsk_plan` constant (or pass `gap` through) and delete the
duplicate.

---

## NITS

11. `tests/test_dsk_assemble.py:3452` `test_split_script_duplicates_in_descending_order` does not
    test descending order — there is only one split slide, and `dup_idx < slide21_write_idx` holds
    trivially because every duplicate precedes every `_slide_lines` block. Add a case with **two**
    split slides and assert the `duplicate slide` lines appear in descending base-ordinal order.
12. `tests/test_dsk_plan.py` `test_fit_search_returns_measured_t`: `assert t38 is not None and
    t49 is not None` is dead — `_t_for` already asserts `result is not None` and returns a float.
13. `test_wrapped_height_matches_golden_boxes` reads the **GW** deck, not the golden; the name is
    misleading. It also validates the predictor only where F9 already reported it working (13/17 at
    the box's own width/size), which makes the "±1 line" claim weaker than it reads.
14. Style: docstrings over the ≤2-line rule — `wrapped_height` (4), `fit_text_stack` (5),
    `resolve_font_path` (3), `ordinal_map` (3), `_filter_kept_items` (4).
15. `tests/test_dsk_assemble.py:23` `from obed_edom.dsk_assemble import SplitPart` is a second import
    statement from the same module immediately below the first — merge it. `tests/test_dsk_plan.py`
    has a mid-file `import` with `# noqa: E402`; move it to the header.
16. `_wrap_lines` splits only on ASCII space; the plan also names a thin/narrow space as a break
    opportunity. Conservative (overestimates lines), so low risk, but it is an undeclared narrowing.
17. `_stacked_text_rects` recomputes `wrapped_height` for every box instead of reusing the heights
    `fit_text_stack` just computed — wasted work and the exact seam where finding 6's margin drift
    lives. Return the heights from `fit_text_stack` and consume them.

---

## Things checked and found sound

- `ordinal_map(keep, parts)` running-sum, `ordinal_to_number`, and `plan.ordinals[n] + part`
  addressing: correct, including multiple split slides (probe: 13,17,21 with 17 split →
  `ordinals {13:1,17:2,21:4}`, `ordinal_to_number {1:13,2:17,3:17,4:21}`).
- `duplicate slide K to after slide K of theDoc` emitted descending over **pre-duplication**
  ordinals, after the layout-assignment block and before any geometry write — addresses never shift
  under an already-emitted line, and duplicates inherit the assigned base layout. The precedent
  (`maps_keynote.py:1245`) is real; that duplicates carry builds/transitions/notes remains an
  unverified live assumption and belongs in the live gate, not in a unit test.
- Per-part `deletes` are correct: `_delete_order(base_deletes + other_long)` leaves exactly one long
  box per part and keeps the short items.
- Refusal when a single box cannot fit alone fires on both the `n == 1` and the per-part path.
- The text-slide media drop lands in `excluded_ids` → `deletes`, and `_filter_kept_items`'s ordering
  (media drop before dedupe, `long_text_ids` filtered after dedupe) is right.
- No regression on the non-text assembly path (diff vs HEAD, above).
