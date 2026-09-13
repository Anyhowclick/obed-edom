# Opus review 2 — piece D1 (fix round, `f372a51`; merged HEAD `34e7aa5`)

## Verdict: **REVISE**

Scope reviewed: `git diff 357b4a0 f372a51 -- src tests`, plus the merged HEAD for the anchoring
question. All 11 findings of review 1 are addressed and I found no regression in what was already
right (AppleScript shape, no-affine path, dedupe-before-classifier, GW 5 acceptance geometry,
`checked == 58`). Two new problems block approval, both created by the finding-1 fix:

- **The new group-relative badge x puts GW 53's badge 213 pt off the right edge of the 1920 pt
  output canvas** — a real, reproducible defect on the real deck, replacing the old overlap defect.
- The new word-count gate for group children **conflates "short label" with "text/font could not be
  resolved"**, which re-opens the F9 hole for a nested group and emits a wrong AppleScript address.

Evidence: offline probes against `~/Desktop/Diff-Checker/Sermon_PK (GW).key`
(`<scratchpad>/p1.py`..`p6.py`). No Keynote, no repo edits, no commits, no Agent tool.
Targeted suites re-run green: `457 passed, 1 skipped, 1 xfailed`
(`tests/test_dsk_{assemble,plan,content_rules_acceptance}.py`, `tests/test_iwa_runs.py`).

(Note: the brief's last line names `opus-D1-review1.md`; that file is already banked as review 1, so
this is written as `opus-D1-review2.md` per the dispatch prompt.)

---

## Review-1 findings: resolution status

| # | Review-1 finding | Status |
|---|---|---|
| 1 | Centred badge overlaps other short-row content (GW 51) | **Fixed, but with a new defect** — badge now follows the group's fitted x (`dsk_assemble.py:765-776`) and GW 51 is clean (`badge x=1069.99` vs title right edge `730.86`); a `_refuse_on_short_row_overlap` guard and a GW 51 test were added. See new finding 1 for GW 53. |
| 2 | GW 51 wrongly excluded from the smoke test | **Fixed** — exclusion is now `(44, 49, 50)`, `checked == 58`, comment names only 44/50. Reproduced: 44/50 refuse, 51/53/54 plan. |
| 3 | GW 44/50 regression recorded only in a test comment | **Fixed** — `.agents/plans/dsk_pieceD.plan.md` gains a "Known regressions / deferred" section with the measured cause. |
| 4 | Stack vs short row split on kind, not word count | **Fixed** (`dsk_assemble.py:718-727`), with `test_group_short_label_stays_in_short_row_at_source_size`. See new finding 2 for the gap this introduced. |
| 5 | Overflowing group verse only warned | **Fixed** — `_run_refit_and_finalize` raises under `--text-fit warn`, stays a warning under `shrink`; both paths tested; plan updated. |
| 6 | Latent 3-tuple unpack in the refit path | **Fixed** — guarded in three places (`build_refit_script:1848`, `_build_refit_round` skips groupchild-stacked slides and filters `short_fit`), with two discriminating tests. |
| 7 | Unmapped child kinds emitted a bogus address / placed unconditionally | **Fixed** in both the plan loop (`:762`) and `_group_stacked_child_lines` (`:1518`), with a test. |
| 8 | Misleading `text 0` warning label | **Fixed** — `_item_label` (`:207`) applied across the message sites. |
| 9 | `fit.pop`/affine exclusion inside the "all boxes resolved" guard | **Fixed** — explicit `elif text_group_kis: raise AssemblyRefusal` (`:931`), with a test. Partially defeated by new finding 2. |
| 10/11 | House-style nits, tests do not discriminate | **Mostly fixed** — new tests pin the MEASURE key, `_eligible_refit_items`, the refit skip, the badge x, the unresolved-font refusal, the unmapped kind. Two f-string nits remain (finding 4). |

---

## New findings

### 1. (major) GW 53's badge is placed 213 pt off the right edge of the canvas
`src/obed_edom/dsk_assemble.py:765-776`

The fix for review-1 F1 places a short group child at `group_rect.x + (child.x - group.x)` — the
group's *affine-fitted* x plus the child's *source* offset — while the child keeps its **source
width**. When the group's fitted rect is narrower than source (it is scaled to fit the band), the
badge overhangs it. Reproduced on the real deck (`<scratchpad>/p2.py`, `p4.py`), band
`x_min=43, x_max=1892`, canvas `1920×1080` (`dsk_assemble.py:90`, `:157`):

```
GW 53  group fit rect   x=1488.27  w=403.73   (source group w=645, scale 0.626)
       badge  ('groupchild',0,0)   x=1487.86  w=645.03  ->  right edge 2132.89
```

That is **240.9 pt past `band.x_max` and 212.9 pt past the canvas right edge** — roughly a third of
the badge is cut off on the wall. GW 51 (`right 1715.02`) and the centred GW 5/54 (`right 1290.02`,
`1290.02`) are fine, so the defect is GW 53 only — and GW 53 is in the smoke test
(`checked == 58`), which passes because nothing anywhere asserts a short-row rect's **x** stays in
the band (`test_gw_text_slides_stay_within_band_top` checks y only;
`test_gw51_badge_x_clears_title_right_edge` pins 51 alone).

**Fix:** after computing `badge_x`, clamp into the band —
`badge_x = min(max(badge_x, band.x_min), band.x_max - badge_w)` (and refuse if
`badge_w > band.width`) — then keep the existing `_refuse_on_short_row_overlap` call *after* the
clamp so a clamp that creates a collision still refuses. Centring on the group rect's centre is not
enough on its own (GW 53 would still land at `right = 2012.6`). Add an assertion to the deck smoke
test that every `plan.fits[n]` rect satisfies `band.x_min <= x` and `x + w <= band.x_max`, and pin
GW 53's badge x explicitly.

### 2. (medium) "no resolvable runs" is silently treated as "short label", re-opening F9 and emitting a wrong address
`src/obed_edom/dsk_assemble.py:718-727`, `:1518-1523`, `iwa_runs.py:753-757`

The F4 word-count gate reads the child's text from `group_child_runs_map`; when that entry is
missing it scores 0 words and the child is dropped from `long_ids` — indistinguishable from a genuine
short label. `_group_child_runs` returns `None` for **any nested group** (`iwa_runs.py:766`), while
`_all_group_child_records` happily flattens nested children and tags them with `group_path`
(`dsk_assemble.py:1092`, `:1124`). So for a nested text-triggering group:

- if the group is the slide's only long-id source, `long_ids` empties and the F9 refusal at `:931`
  fires — correct;
- **if the slide also has a long top-level text, it does not.** `long_ids` is non-empty, `boxes`
  match, and the group's verse falls through into `short_children` and is written **position-only at
  source size** in the short row. Reproduced (`<scratchpad>/p6.py`):

```
long ids  (('text',1), ('groupchild',0,1))
stacked   frozenset({('text',1)})             <- verse not stacked
fits      ('groupchild',0,1): Rect(x=246.5, y=856.72, w=1442.0, h=120.0)   <- short row, source size
SCRIPT    set theObj to text item 2 of group 1 of slide 1
```

The address is also wrong: `_group_stacked_child_lines:1518` builds `... of group {group_ki+1} of
slide` and ignores `child["group_path"]`, unlike `_group_known_child_lines:1452` which builds the
full `group_chain` and wraps the ancestor locks via `_wrap_group_locks`. A nested child therefore
addresses the wrong object (MISS at best). Related: `_all_group_child_records` restarts its
`counters` per recursion level, so two children in different nesting levels of the same top-level
group can share a `kindIndex` and collide as the same `GroupChildId`.

Not reachable on the GW deck (every text-triggering group there is flat — verified in `p3.py`), so
this is latent, but it is a silent-degradation path exactly of the class F9 was raised about.

**Fix:** in the `long_ids` loop, separate the two cases —
```python
c_info = (group_child_runs_map.get(g_ki) or {}).get(c_ki) or {}
if not (c_info.get("text") and c_info.get("font") and c_info.get("size")):
    raise AssemblyRefusal(f"slide {number}: group {g_ki} child {c_ki} text/font could not be resolved ...")
if _word_count(c_info["text"]) > text_slide_words:
    long_ids.append(iid)
```
and, independently, refuse (or handle via `group_path`/`_wrap_group_locks`) any child of a
text-triggering group whose `group_path` is non-empty. Add a test for the mixed
top-level-long-text + unresolvable-group-child slide.

### 3. (low, latent — the merge resolver's question) A text-triggering group with a media child still counts for content anchoring, and its image child is placed rather than dropped
`src/obed_edom/dsk_assemble.py:585-591` (anchor) vs `:648` (`text_group_kis`); `_content_ids:441`;
`dsk_plan.py:_filter_kept_items` media drop

**Answer to the flagged point: yes, the premise is correct, but it needs only a cheap consistency
fix, not a redesign — nothing on the GW deck hits it.** `_content_anchor` runs at `:586`, before
`text_group_kis` exists at `:648`, and `_content_ids` counts any kept group whose
`groupChildSignature` carries an `image:`/`movie:` leaf. A group that triggers the text
classification *and* contains an image would therefore still vote for the auto anchor. I swept the
deck (`<scratchpad>/p1.py`): **no text-triggering group on GW has a media child**, so all six group
text slides come out `anchor centre` and no output changes today.

The consequence is also bounded: on a text slide the verse is restacked full band regardless of
anchor, so a wrong anchor only shifts short-row x — and since the badge now follows the group's
fitted rect, it would shift *consistently* with it. So this is a tidiness/consistency issue, not a
correctness break.

Worth fixing anyway, because `cls.long_text_ids` is already available at `:574`: hoist
`text_group_kis = {iid[1] for iid in cls.long_text_ids if iid[0] == "groupchild"}` above the anchor
block and pass it into `_content_anchor`/`_content_ids` as an exclusion set, so that a group being
used as a text carrier never anchors content — matching `_content_ids`' own docstring ("text-only
content never counts").

The **sharper sibling** of the same premise deserves an owner decision: a text slide drops every
*top-level* image/movie (`dropped_media_text`), but an image child of a text-triggering group is
neither dropped nor scaled — it lands in the short row at literal source size
(`_AS_KIND_NAMES` maps `image`, so `:762` does not skip it), which contradicts the owner's "GW 5 is a
text slide — DROP the full-wall photo". (A *movie* child is already refused upstream by
`slide {n}: movie nested in group unsupported` at `:645`.) Suggest refusing, or dropping the image
child, when a text-triggering group has an image child; either way record the decision in
`dsk_pieceD.plan.md`.

### 4. (nit) Leftovers
- `dsk_assemble.py:855`: `boxes[0].item_id[1]` is the last raw index format left; unreachable for a
  groupchild (guarded by the preceding `elif` at `:848`) but should use `_item_label` for
  consistency with the rest of the round.
- `_refuse_on_short_row_overlap` (`:218-233`) compares x-intervals only. Correct as a conservative
  proxy (all short-row rects are bottom-aligned into one row by `_short_row_rects`), but the
  docstring should say so — an x-only test can refuse a pair that is vertically separated inside a
  tall row.
- Two f-strings with no placeholder: `tests/test_dsk_assemble.py:613` (pre-existing, review-1 F10)
  and `:739` (new).

---

## What I re-verified on the real deck

- Classification unchanged and correct: group text slides `5, 44, 50, 51, 53, 54`, each
  `long_text_ids == (('groupchild', 0, 1),)`; GW 50/51 both report `dropped_duplicate ==
  (('group',1),)` with no `('groupchild',1,1)` surviving — dedupe still precedes the classifier.
- GW 5 acceptance: verse `x=43.00 w=1849.00 y=821.96 bottom=1054.00`, badge `y=719.96 bottom=811.96`
  (above the verse), band top `704.0`, `crops[5] is None`, no `('group',0)` entry in `plan.fits[5]`.
  All targets met.
- GW 44/50 refusals reproduce with the fix round in place and are the same correct
  "grouped verse text does not fit the band at --min-text-pt 24.0 -- refusing to split text inside a
  group" behaviour reviewed last round; GW 51/53/54 plan.
- No new affine/blind-loop leakage: the group's top-level fit entry is popped for all six slides.

## Required before approval
1. Clamp the group-child short-row x into the band and assert it (finding 1) — GW 53 is currently
   broken on the real deck.
2. Distinguish "unresolvable group child" from "short label", and stop addressing nested children
   without their `group_path` (finding 2).
3. Hoist `text_group_kis` above the anchor decision and settle the group-image-child question in the
   plan (finding 3).
Finding 4 can ride along.
