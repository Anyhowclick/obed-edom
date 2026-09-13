# Opus review 3 — piece D1 (fix round 3, `e7c46f1`)

## Verdict: **APPROVE-WITH-NITS**

Scope: `git diff 357b4a0 e7c46f1 -- src tests` (D1 commits `4055328`, `f372a51`, `e7c46f1`; the
merged placement branch `34e7aa5` ignored), plus `.agents/plans/dsk_pieceD.plan.md`.
All three required-before-approval items from review 2 are implemented and **verified on the real
deck**, and a whole-deck A/B of the planner shows the round changes exactly one number on GW —
GW 53's badge x — with no other output drift. The four remaining points are nits; one of them
(finding 1) is a *test* defect, not a product defect, and should be fixed before the piece is
considered gated.

Evidence: offline probes against `~/Desktop/Diff-Checker/Sermon_PK (GW).key`
(`<scratchpad>/q1.py`..`q8.py`, plus `old/` = `git archive 34e7aa5 src`). No Keynote, no repo edits,
no commits, no Agent tool. Targeted suites green at HEAD:
`462 passed, 1 skipped, 1 xfailed` (`tests/test_dsk_{assemble,plan,content_rules_acceptance}.py`,
`tests/test_iwa_runs.py`).

---

## Review-2 findings: resolution status (all verified on the deck)

| # | Review-2 finding | Status |
|---|---|---|
| 1 | GW 53 badge 213 pt off the canvas | **Fixed.** `dsk_assemble.py:806-808` clamps `badge_x` into `[band.x_min, band.x_max - badge_w]` and refuses at `:799` when `badge_w > band.width`; the clamp precedes `_refuse_on_short_row_overlap` as asked. Reproduced: GW 53 badge now `x=1246.97 w=645.03 right=1892.00` (exactly the band edge), no overlap with `('text',1)` (right `412.93`). Every groupchild rect on 5/51/53/54 satisfies `band.x_min <= x` and `x+w <= band.x_max` (`q1.py`). |
| 2 | "no resolvable runs" conflated with "short label"; nested children addressed without `group_path` | **Fixed.** `:743-748` refuses when a long-id group child has no `text`/`font`/`size`; `:595-602` refuses *any* child of a text-triggering group with a non-empty `group_path`, unconditionally and before `long_ids` is built, so the mixed top-level-long-text case is covered. Confirmed the live payload really carries `group_path`: `load_assembly_inputs` uses `_attach_full_group_children` (`dsk_assemble.py:1181`, the recursive producer), not `iwa_runs.attach_group_children`. The `_all_group_child_records` per-level `counters` collision is now unreachable and the plan says so. |
| 3 | Text-carrier group still anchored content; image child not dropped | **Fixed.** `text_group_kis` hoisted to `:595`, threaded into `_content_anchor`/`_content_ids` as `exclude_group_kis` (`:446-465`, `:495-505`); an image child of a text-triggering group refuses at `:786-790`. Both owner decisions are recorded in `dsk_pieceD.plan.md` ("D1 fix round 3"). Whole-deck A/B: **no anchor changes anywhere on GW** — as predicted, no text-triggering group there has a media child. |
| 4 | Nits (`_item_label`, x-only docstring, two f-strings) | **Fixed** — `:890`, `:223-225`, `tests/test_dsk_assemble.py:613,739`. |

### Whole-deck A/B (the strongest regression evidence)

Planned every slide at `34e7aa5` and at `e7c46f1` and diffed `fits`/`crops`/`deletes`/refusals for
all 61 slides (`q2.py`). **One line differs:**

```
< 1487.855   (GW 53 badge x, off-canvas)
> 1246.971   (GW 53 badge x, clamped to the band)
```

No other rect, crop, delete order or refusal changed. 58 slides plan in one batch (matching the
smoke test's `checked == 58`) and the full assembly script builds (259,955 chars, `q8.py`).

---

## Brief checklist

1. **Classification.** `is_text` includes 3/4/5/44/50/51/53/54; the six group-text slides are
   `5, 44, 50, 51, 53, 54`, each with `long_text_ids == (('groupchild', 0, 1),)`. GW 50 and 51 both
   report `dropped_duplicate == (('group', 1),)` and **no `('groupchild', 1, 1)` survives** — dedupe
   still precedes the classifier (`q1.py`, `q3.py`).
2. **AppleScript shape.** For GW 5 and 53 the emitted lines are
   `text item 2 of group 1 of slide <ord>` and `shape 1 of group 1 of slide <ord>`, position/width/
   run-sizes only; **no `set height` on either group child**, no `iWork items of group`, no
   `(width of theObj)`; one `theGroupObj` lock/unlock/relock wraps both children, each child having
   its own inner lock guard; `MEASURE`/`OVERFLOW` keyed `groupchild:0:1` (`q3.py`). The `set height`
   lines present on GW 53 belong to its top-level `text 0/1` and `shape 0`, correctly.
3. **No affine path / blind loop.** `5 in plan.group_children` is `False`, `('group',0)` is absent
   from `plan.fits[5]`, and `"iWork items of group"` does not appear in the whole-deck script.
   `plan.crops[5] is None`; `plan.deletes[5] == (('image',2),('image',1),('image',0),('shape',0))` —
   the full-wall photo is dropped, the group is not. `_delete_order` and the crop z-order path are
   byte-identical to the pre-round output for every slide (A/B above).
4. **Badge geometry.** GW 5/54 are sole occupants → centred (`x=644.99`, i.e. exactly
   `43 + (1849-645)/2`); GW 51/53 follow the group's fitted x, then clamp. The verse's stacked rect
   is `x=43.00 w=1849.00` on all four — full band width, as required. "Centred" for the sole-occupant
   case is a judgment call the acceptance criteria do not constrain; it is now documented in the plan
   and is the only placement that cannot collide, so I accept it.
5. **GW 5 acceptance numbers** (computed, `q1.py`): verse `y=821.96`, `bottom=1054.00` (band top
   `704.0` → `y >= 704` ✓, `bottom <= 1054` ✓); badge `y=719.96 bottom=811.96`, entirely above the
   verse ✓; `crops[5] is None` ✓. Matches `test_gw5_group_verse_text_slide_no_image`.
6. **Refit exclusion.** `_eligible_refit_items` (`:2780-2790`) drops every `GroupChildId` before
   `_text_boxes` is called, and `_build_refit_round` skips groupchild-stacked slides explicitly
   (`:2845`), so there is no KeyError path and no vacuous "overflows empty". The plan records it as a
   decision (`dsk_pieceD.plan.md:207-208`). Safe.
7. **GW 44/50 refusals are correct behaviour, not a D1 bug.** Reproduced and measured (`q4.py`,
   `q5.py`, `q6.py`): on both slides the top-level heading dominates the short row, leaving
   `stack_band.height == 78.55` (GW 44) / `93.43` (GW 50) out of the 350 pt band. GW 44's verse has
   four hard line breaks (`U+2028`/`\n`), so at `t=0.18` it is still `85.56 pt` tall against a
   `63.55 pt` budget (band minus `_TEXT_SAFETY_PT`). The refusal therefore holds all the way down to
   `--min-text-pt 12` (it would only clear around ~9 pt). GW 51, same layout but a one-line
   24-word verse, plans fine at `t=0.49`. So the refusal is the band budget, correctly enforced —
   out of this brief's GW-5-only scope, correctly excluded from the smoke test, and correctly
   recorded in the plan's "Known regressions / deferred".
8. **House style.** Clean: no new inline noise, docstrings carry the reasoning, `Iterable` already
   imported, message strings use `_item_label` throughout.
9. **Tests discriminate.** Ran the five new tests against `old/src` (`34e7aa5`): four fail, one
   passes vacuously — see finding 1.

---

## Findings

### 1. (nit, but fix before gating) `test_gw53_badge_x_clamped_to_band_right_edge` is vacuous — it asserts on the verse, not the badge
`tests/test_dsk_assemble.py:1578-1589`

```python
badge = next(rect for iid, rect in plan.fits[53].items() if iid[0] == "groupchild")
```

`plan.fits[53]`'s insertion order is
`[('text',0), ('text',1), ('shape',0), ('groupchild',0,1), ('groupchild',0,0)]` — the **verse** comes
first, and it always spans the band exactly, so both assertions are trivially true. Verified: this
test **passes unchanged against the pre-fix `34e7aa5` code**, where the badge sat at `x=1487.86,
right=2132.89` (`q7.py`). The regression it is named for is actually caught only by
`test_gw_group_text_slides_short_row_stays_within_band_x`, which does iterate every groupchild rect
(and does fail on old code).

**Fix:** select the badge by id, and pin the clamped value —
```python
badge = plan.fits[53][("groupchild", 0, 0)]
assert badge.x == pytest.approx(1246.97, abs=0.5)
assert badge.x + badge.w == pytest.approx(BAND.x_max, abs=1e-6)
```

### 2. (nit) The clamp moves the badge 241 pt with no warning
`src/obed_edom/dsk_assemble.py:806`

`badge_x = min(max(badge_x, band.x_min), band.x_max - badge_w)` silently discards the
group-relative placement whenever the group's fitted rect is narrower than the child's source width
— on GW 53 that is a 240.9 pt horizontal move. Every other geometry compromise in this module
(`run ranges leave a gap`, overflow, flattened sizes) emits a `warnings` entry. Suggest appending
`f"slide {number}: group {group_ki} child {ki} badge x clamped {orig:.1f} -> {badge_x:.1f} to stay in the band"`
when the clamp actually bites, so the operator sees it in `run.out` rather than only in the deck.

### 3. (nit) The `badge_w > band.width` refusal has no test
`src/obed_edom/dsk_assemble.py:798-802`

A synthetic group child wider than 1849 pt would cover it in two lines, and it is the only new
refusal in this round without one (`image nested in`, `nested inside a text-triggering group`, and
`text/font could not be resolved` all have discriminating tests). Unreachable on GW today
(max badge width 645.03), so genuinely a nit.

### 4. (informational, no action) The 44/50 plan note under-states the cause
`.agents/plans/dsk_pieceD.plan.md`, "Known regressions / deferred"

"at default `--min-text-pt` the budget is too tight" reads as a marginal miss. Measured, it is not
marginal: the refusal persists at `--min-text-pt 12` and would only clear near 9 pt, because the
heading consumes ~271 pt of the 350 pt band on GW 44. Worth one sentence in the plan so nobody
later "fixes" it by lowering the floor.

---

## Required before approval

Nothing blocking. Finding 1 should land before the piece is gated (a named regression test that
passes on the buggy code is worse than no test); findings 2–4 can ride along with the next round.
