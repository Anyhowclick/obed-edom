# d4b piece D — grouped verse text + live refit

Worktree `feat/dsk-gen` @ 9b486a8. Evidence: `~/Desktop/dsk-d4-work/evidence-r9b/` (run.out, payload_slides.json,
png/png.00N.png, acceptance9.csv). Probes: `scratchpad/probe_src.py`, `scratchpad/probe_runaware.py`,
`scratchpad/src_payload.json`.

## Facts (measured)

### F1 — GW 5 is a verse slide whose verse lives inside group 0
Source payload (probe_src.py) for GW 5, top-level items: `image 0` (crowd photo, 3840x2561 @ 1920,-1024),
`image 1`/`image 2` (side panels), `shape 0` (textless 4897x1807 scrim), `group 0` (frame 645x92 @ 4702,15).
No top-level `text` item at all -> `_is_text_slide_kept` (dsk_plan.py:59) counts only top-level `text` and
returns `False`; the slide is classified content, the photo is LW-cropped/right-anchored and the group is
affine-fitted on top (png.001.png).

`groupChildText[0]` = "Matthew 18\n19 Again, truly I tell you that ... by My Father in heaven." (32 words,
> `DEFAULT_TEXT_SLIDE_WORDS` = 10).
`groupChildren[0]` (iwa_runs.py:648 `_group_child_records`) = two children:
- `{kind: shape, kindIndex: 0, autosize: false, x 4702.5, y 15.4, w 645.0, h 92.0}` — the badge ("Matthew 18", AzoSans-Bold 65)
- `{kind: text,  kindIndex: 1, autosize: true,  x 4303.6, cy 89.2, y -88.7, w 1442.7, h 355.7}` — the verse
`kindIndex` is the per-kind counter *inside the group* (iwa_runs.py:663-700); a text-bearing shape consumes both
counters, so the verse is addressable as `text item 2 of group 1 of slide <ord>` — the exact shape
`_group_known_child_lines` already emits (dsk_assemble.py:1200-1203).

Two consequences visible in png.001.png:
1. The group's own frame (645x92) is the badge only — the autosize verse child (1442.7x355.7, y -88.7..267)
   sticks far outside it. `fit[group]` is therefore the badge rect, and children are placed relative to it, so
   the verse lands outside the band.
2. `groupCaption` is **null** for GW 5 (`_single_text_leaf` needs exactly one text leaf; there are two —
   iwa_runs.py:594-617), so `group_text_sizes` is empty, `caption_child` is `None`
   (dsk_assemble.py:1191), and **no text size is written at all** — the verse keeps its source 70/85 pt.

Deck survey (probe_src.py, `groupChildText` > 10 words): GW **3, 4, 5** (same Matthew 18 group, 32 w),
**44** (23 w), **50** (2 coincident groups, 44 w), **51** (2 groups, 26 w), **53** (15 w), **54** (33 w).
10 group entries on 8 slides; only GW 5 is in the nine-slide kept set. 50/51 carry an L/R mirror pair, so
`mirror_duplicates` (dsk_plan.py:467, already `group_child_text`-aware) must stay in front of the new classifier.

### F2 — the estimator is run-blind, and that is the whole of defect 2
`wrapped_height` (dsk_plan.py:885) measures the whole string in ONE font at the item's *lead style* size.
The verse boxes are mixed-run: the emphasis runs are **ArgentCF-Bold at ~1.21x the lead size**. Output runs
(attach_runs on out-r9b):

| slide | box | style size | emphasis run | live h | predicted h (single-font) | live/pred | OVERFLOW read-back |
|---|---|---|---|---|---|---|---|
| GW 13 | text:1 | 63.7 | 77.35 ArgentCF-Bold | 269 | 242.1 (3 lines) | 1.11 | 249.0 |
| GW 17 | text:1 | 51.8 | 62.9 ArgentCF-Bold | 186 | 140.9 (2 lines) | 1.32 | — (under +2pt gate) |
| GW 17 | text:2 | 51.8 | 62.9 ArgentCF-Bold | 189 | 80.9 (1 line)  | **2.34** | 142.0 |
| GW 28 | text:1 | 67.2 | 81.6 ArgentCF-Bold | 349 | 254.3 (3 lines) | 1.37 | 340.0 |

The error is **not** constant, not per-line and not a font offset: it is line-count quantisation
(an extra wrapped line is worth 100% on a one-line box). `_TEXT_SAFETY_PT` = 15.0 (dsk_plan.py:807) cannot
cover a 2.34x error. Run sizes themselves were written correctly (`_run_size_ranges`, dsk_assemble.py:184 —
63.7/77.35 = 70/85 x t=0.91), so this is purely a *measurement* defect.

A run-aware estimator (probe_runaware.py: wrap across runs with each run's own font+size, line height =
1.157 x max run size on that line) gives: 273.7 vs 269, 153.7 vs 186, 166.6 vs 189, 382.0 vs 349 — within
±18%, still **under**-predicting on GW 17. Good enough as a first guess, not as an authority.

### F3 — the in-script read-back is stale
Read-back 249.0 vs final 269 (GW 13), 142.0 vs final 189 (GW 17 text:2), 340.0 vs 349 (GW 28).
`_text_overflow_lines` (dsk_assemble.py:1246) reads `height of <addr>` immediately after that item's write
block; Keynote has not finished re-laying the box. Any refit that trusts a single immediate read is refitting
against a stale number. (Same signature as the resizer's raise-readiness poll, PR #80.)

### F4 — the live plumbing for a second pass exists
- `LiveBatch.run()` (dsk_live.py:451-488) may be called repeatedly inside one `with`; the scratch copy and
  the Keynote process survive between calls (`__exit__` quits, dsk_live.py:490).
- `build_assembly_script` opens the scratch, writes, then `save theDoc in <staging>` + `close theDoc saving no`
  (dsk_assemble.py:1514-1518). A second pass therefore needs pass 1 to stop before the save.
- Precedent for a second osascript against the still-open document: `keynote.py:527` `_build_superscript_fix_script`
  ("`open` here is bring-to-front of the already-loaded document, then export and close", keynote.py:532) run by
  `_run_superscript_fix` (keynote.py:613) after `generate_deck`'s pass 1 (keynote.py:1996).
- **Hazard**: `LiveBatch.run`'s -1712 retry re-copies the pristine scratch and re-runs only *that* script
  (dsk_live.py:479-487). Retrying pass 2 alone would run against an unwritten deck.
- `OVERFLOW` is parsed in `assemble_dsk_deck` (dsk_assemble.py:2358) into `AssembleResult.overflows` and a warning
  only — no behaviour.
- The sdef has **no `ungroup` verb** (`/Applications/Keynote Creator Studio.app/Contents/Resources/Keynote.sdef`;
  commands are export/duplicate/get/set/delete/make/... only). `group` is an `iWork container` exposing
  `text item`/`shape` elements, so in-place child addressing is the only scripted route. `duplicate … to
  <location>` exists but child->slide extraction is unproven and would orphan GW 5's group build
  (`apple:dissolve` on `('group', 'Matthew 18\n19 Again…')`, run.out).

## Design A — grouped verse text (defect 1)

Chosen: **(b) address the group's text children directly**; keep the group. (a) is impossible (F4, no `ungroup`);
(c) refusal is the fallback only where metadata is missing.

1. **Classification.** `_is_text_slide_kept(kept, text_slide_words)` (dsk_plan.py:59) gains
   `group_child_text: Mapping[int, str]`: a kept `group` whose `groupChildText[ki]` has > `text_slide_words`
   words makes the slide text, and contributes its **text children** as long ids. `_filter_kept_items`
   (dsk_plan.py:68) already receives `group_child_text` — thread it in. Media drop (dsk_plan.py:108-116) then
   removes image 0/1/2 unchanged; the scrim is already dropped by `is_panel_backdrop`.
2. **Id shape.** Introduce `GroupChildId = ("groupchild", group_kindIndex, child_kindIndex)` alongside `ItemId`,
   carried in `long_text_ids` / `stacked_ids` / `text_sizes` / `run_sizes` / `fits`. Everything that keys on
   `iid[0] in ("text","image",...)` must ignore this tag (delete order, crops, movie ids).
3. **Boxes.** `_text_boxes` (dsk_assemble.py:228) gains a group branch: geometry from `groupChildren[ki]`,
   text+runs from a new `attach_group_child_runs` (mirrors `attach_group_captions`, keyed
   `{group kindIndex: {child kindIndex: {text, font, size, runs}}}`) — `groupedText` is a slide-level DFS leaf
   list and must NOT be matched back by text equality (50/51 have two identical groups).
   Short children (badge, <= `text_slide_words`) go to `short_fit`; long children to the stack. Same
   `fit_text_stack` / `_stacked_text_rects` / `_short_row_rects` as today.
4. **Writes.** New `_group_stacked_child_lines(number, ordinal, group_ki, per-child rect + size/run-ranges)`:
   for each child, `set width/position` (never `height` on an autosize child, as today
   dsk_assemble.py:1205-1208) and `set size of characters i thru j of object text of theObj` using
   `_run_size_ranges` on the child's runs. Same `_locked_write_block` + `_wrap_group_locks` wrappers.
   On a text slide the group takes **no** affine path: skip `slide_affine_scale`/`group_scale`/
   `_group_known_child_lines`/`_group_blind_child_lines` for that group (dsk_assemble.py:1313-1323) — `scale` is
   meaningless once the children are stacked into the band. The group frame follows its children.
5. **Refusals.** Group text > threshold but `groupChildren[ki]` missing (nested/rotated/masked/naturalSize
   disagreement) -> reuse the existing refusal wording at dsk_assemble.py:497. Group text child with
   unresolvable font/size -> existing `_text_boxes` warning + skip.
6. Overflow read-back (`_text_overflow_lines`) is emitted for group text children too, addressed
   `text item <k+1> of group <g+1> of slide <ord>`.

## Design B — measure-then-refit (defect 2)

Two halves: a better first guess, and a live authority.

1. **Run-aware estimator.** `TextBox` gains `runs: tuple[Run, ...] | None`. `wrapped_height` grows a
   run-aware sibling `wrapped_height_runs(runs, default_font, width)`: tokenise per run (same
   `_WRAP_BREAK_CHARS` / `_PARA_BREAK_CHARS` rules), advance with each run's own resolved font at its own
   size, line height = `_LINE_HEIGHT_FACTOR x max run size on the line`, plus `_BOX_PADDING_PT`.
   `fit_text_stack` uses it whenever runs are known, falling back to today's single-font path (and its
   warning) otherwise. Keep `_TEXT_SAFETY_PT` as is. *Not* a fix on its own (F2): first guess only.
2. **Pass 1 / pass 2 split.** `build_assembly_script(..., finalize: bool = True)`: with `finalize=False` it
   omits `save`/`close` (dsk_assemble.py:1514-1518) and leaves the document open. New
   `build_refit_script(plan, refits, *, ordinals, scratch_path, staging_path, finalize)`:
   `open` the scratch by POSIX path (bring-to-front, keynote.py:532), re-write only the boxes named in
   `refits` (size/run-ranges + position for the whole stack of the affected slides), re-measure, and
   `save`/`close` when `finalize`.
3. **Settled measurement.** Replace the one-shot read in `_text_overflow_lines` with
   `_text_measure_lines`: poll `height of <addr>` until two consecutive reads agree (`delay 0.2`, <= 5 polls),
   then always log `OBED\t<n>\tMEASURE\t<item key>\t<h>` (every stacked box, not only the overflowing ones) and
   keep the existing `OVERFLOW` line as the final gate. This is what F3 demands and mirrors the resizer's
   readiness poll.
4. **Refit loop** in `assemble_dsk_deck` (dsk_assemble.py:2329-2385), at most `_MAX_REFITS = 2` rounds:
   - parse `MEASURE` into `{(number, item key): measured_h}`;
   - per box, correction `r = measured_h / predicted_h(at the size actually written)`, clamped to `[1.0, 3.0]`;
   - re-run `fit_text_stack` for that slide with heights multiplied by the box's `r` (a `height_correction`
     mapping argument), giving new `t`, sizes and rects; re-emit those slides via `build_refit_script`;
   - stop when every `MEASURE` on the slide fits its rect within +2pt.
   `r` is not scale-invariant (line-count quantisation), hence the bound and the re-measure after each round.
   After the last round, a box still over budget: `allow_split` -> fall into the existing split path
   (dsk_assemble.py:604-660) for that slide and run one more refit round; `--no-split` -> `AssemblyRefusal`
   under `--text-fit warn`, or shrink to the measured-fit size under `--text-fit shrink`, never below
   `--min-text-pt`. `AssembleResult.overflows` must be **empty** on success.
5. **Retry hazard.** `LiveBatch.run`'s -1712 recopy (dsk_live.py:479-487) must not fire on a pass >= 2:
   add `run(..., retry_on_1712: bool = True)` and pass `False` for refit passes; a -1712 there aborts the batch
   (the operator re-runs from the top). One live agent, one `LiveBatch`, no deck re-open.

Offline-first throughout: everything except the `MEASURE` numbers is computed offline; the live session only
reports heights and applies writes.

## Steps

1. `wrapped_height_runs` + `TextBox.runs` + `fit_text_stack(height_correction=None)`.
   Tests (`tests/test_dsk_plan.py`): `test_wrapped_height_runs_charges_emphasis_run_font` (GW 17 text:2 runs,
   51.8/62.9 ArgentCF-Bold, width 1849 -> >= 2 lines, and >= 1.9x the single-font estimate);
   `test_fit_text_stack_height_correction_shrinks_t` (correction 1.4 on one box lowers `t`).
2. Group-aware classification: `_is_text_slide_kept` + `_filter_kept_items` take `group_child_text`.
   Tests (`tests/test_dsk_plan.py`): `test_group_child_text_makes_slide_text` (GW 5 shape: group 32-word child,
   3 images -> is_text, images in `dropped_media_text`); `test_group_child_text_short_caption_not_text_slide`
   (6-word caption -> unchanged content slide).
3. `attach_group_child_runs` in `iwa_runs.py` + test `test_attach_group_child_runs_keys_by_group_and_child`
   (two identical groups on one slide keep separate entries).
4. `_text_boxes` group branch + `_group_stacked_child_lines` + the affine skip.
   Tests (`tests/test_dsk_assemble.py`): `test_group_verse_slide_stacks_children_not_affine`
   (script contains `text item 2 of group 1 of slide 1` with a position inside the band and a
   `set size of characters` write; contains no `iWork items of group 1` blind loop; the images are deleted);
   `test_group_verse_slide_refuses_without_group_children` (existing refusal wording).
5. `_text_measure_lines` (poll + always-log) and the `MEASURE` parse.
   Tests: `test_measure_lines_poll_until_stable` (script shape); `test_assemble_parses_measure_lines`
   (fake proc stderr -> `{(13,'text:1'): 269.0}`).
6. `build_assembly_script(finalize=False)` + `build_refit_script`.
   Tests: `test_assembly_script_finalize_false_has_no_save` ; `test_refit_script_reopens_and_saves`.
7. Refit loop in `assemble_dsk_deck` + `_MAX_REFITS` + `run(retry_on_1712=False)` on refit passes.
   Tests (`tests/test_dsk_live.py`, `tests/test_dsk_assemble.py`): `test_refit_loop_converges_in_two_rounds`
   (fake batch returning 269 then a fitting height -> two `run` calls, no overflows);
   `test_refit_loop_refuses_when_still_overflowing` (warn mode) and `..._shrinks` (shrink mode);
   `test_live_batch_run_no_retry_flag`.
8. Offline acceptance: extend `tests/test_dsk_content_rules_acceptance.py` with GW 5 —
   no image in the plan, the two group children stacked inside the band, badge above verse.
9. Full suite green; then the live re-run of the SAME nine slides (5,13,17,21,24,28,32,33,48) into
   `out-r10`/`evidence-r10`, with the PNG export, using the existing r9b invocation.
10. Re-run `accept9.py` (as `accept10.py`) against out-r10 plus the new GW-5 checks.

## Acceptance

- `png.001.png` (GW 5): badge + verse stacked inside the band (y >= 704, bottom <= 1054), **no photo**,
  verse text visibly shrunk to band size, emphasis runs still ArgentCF-Bold yellow.
- `png.003.png` (GW 17), `png.002.png` (GW 13), `png.006.png` (GW 28): last line fully visible, boxes
  non-overlapping, every long box inside the band.
- `run.out`: `Overflows (0)`; no `text … overflow` warnings; refit rounds logged and <= 2 per slide.
- Offline on the out deck: every kept text/group-child text rect satisfies `y >= 704 and y+h <= 1054`.
- Builds report unchanged from r9b (GW 5's group `apple:dissolve` still present — the group is not deleted).

## Open questions (design-changing)

1. **Stale read-back (F3).** Is the two-consecutive-reads poll enough, or does Keynote only settle the height
   after some other event (the save)? If a poll cannot produce a settled number, the refit must instead measure
   in a *separate* pass after a save+reopen — a third pass, and a different `LiveBatch` shape. Cheapest probe
   during the r10 live run: log `MEASURE` both immediately and again at the end of the slide loop.
2. **Badge sizing on GW 5.** The badge child ("Matthew 18", 65 pt in a 645x92 box) is a *shape*, not the
   stacked verse. Does the owner want it scaled by the same `t` as the verse (uniform verse-slide look) or
   left at source size and merely repositioned (today's short-row rule for top-level badges)? The top-level
   path keeps short boxes at source size; I plan to match that unless told otherwise.
3. **Splitting a grouped verse.** If a group's verse still does not fit after two refits and `allow_split` is
   on, splitting means duplicating the slide and hiding text *inside a group* on each part. Acceptable, or
   should a grouped verse simply refuse instead of splitting?
