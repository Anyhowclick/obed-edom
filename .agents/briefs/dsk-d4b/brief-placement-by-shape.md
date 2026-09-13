# Brief: placement by SHAPE (owner correction 2026-09-12, supersedes plan D3 "placement by count")

Worktree: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen (branch feat/dsk-gen). Run everything from there.
Tests: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_dsk_assemble.py tests/test_dsk_plan.py` then the full suite.
HARD RULES: do the work yourself — NO Agent tool. Never touch Keynote / osascript. Do NOT commit or git add. Edit only src/obed_edom/dsk_assemble.py, src/obed_edom/dsk_plan.py, tests/test_dsk_assemble.py, tests/test_dsk_content_rules_acceptance.py, .agents/plans/dsk_content_rules.plan.md (section D3 + step 9 only).
House style: minimal docstrings, NO inline comments, no bookkeeping words in code.

## The owner's rule (from reviewing the r9b PNGs)
Auto anchor for a content slide (decision.anchor None/"auto", `no_auto_anchor` False) is decided by the SHAPE of the kept content items after LW crop, not by their count:
- If ANY kept content item is "LW-dimension" (its band-fitted rect aspect w/h >= 2.5 — the crowd photo GW 21 crops to 4494x1265 = 3.55, GW 5 photo 5120x1441 = 3.55, the movies 3840x1080 = 3.56) → anchor "centre".
- Else (all squarish/small: wheelchair GW 48 1381x921 = 1.5, the GW 24 phone screenshots 504x1080 = 0.47): 1 or 2 items → "right"; 3 or more → "centre" (the three conference posters slide).
- Explicit `--anchor` still wins. `plan.anchors[number]` records the derived anchor and the run log line stays.
Use the item's post-crop size (the crop box / naturalSize the plan already computes for LW crops) or, if the crop is not known at anchor time, the source rect clipped to the LW frame — read `fit_slide` / `_content_item_count` and pick the place where the post-crop w/h is available; keep it one helper `_content_anchor(...)` returning "centre"|"right".

## Text + picture slides
On a slide that is BOTH text (cls.is_text with long_text_ids) and keeps a non-full-wall picture, the stacked long text boxes must span the FULL band width (x=43, w=1849) like pure text slides — not the remaining width beside the picture. Check what `_stacked_text_rects` / `stack_band` do today when a picture is kept; if they already use the full band, add a test that pins it; if they narrow the band, remove the narrowing.

## Tests
- Rewrite `test_single_content_item_right_aligned` (GW 48 stays right), `test_two_items_centred` → the two GW 24 phone items are now RIGHT (rename), add `test_lw_dimension_item_centred` (a single 3840x1080 movie / 4494x1265 image → centre, union centred on the band centre 967.5), `test_three_squarish_items_centred`, `test_lw_item_among_squarish_centres`.
- Acceptance file (deck-marked, may be skipped locally if the deck is absent): update the GW 21 / GW 32 / GW 33 expectations from right edge 1892 → centred on 967.5, GW 24 → right edge 1892, GW 48 unchanged, GW 5 per current classification.
- Plan doc D3 + step 9: rewrite to the shape rule above with the measured aspects; mark it "owner correction 2026-09-12".

## Report
Write to the scratchpad file named in your prompt: per-slide derived anchors for the nine slides 5,13,17,21,24,28,32,33,48 as computed by the new helper on the real GW payload if the deck fixture is available (`tests/test_dsk_content_rules_acceptance.py` shows how inputs are loaded), the tests added, final suite counts, anything not done and why.
