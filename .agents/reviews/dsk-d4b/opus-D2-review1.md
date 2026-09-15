# Review — 418a85d "run-aware wrap estimator and live measure-then-refit loop (d4b piece D2)"

Verdict: **REVISE**. The plumbing (MEASURE poll, parse, refit script, `retry_on_1712=False`, the ph-review
nits) is sound and the suite is green (2310 passed, 84 skipped, 1 xfailed, 82s). But the three load-bearing
pieces of Design B are each wrong in a way that shows up on exactly the slides D2 targets: the correction
denominator is the *old* single-font estimate (F1 — GW 17 over-shrinks ~2x, and a round 2 undoes round 1),
the badge row is not re-stacked (F2 — measured 8–12pt badge/verse overlap on GW 17/28), and pass 1 still
uses the single-font estimator, so the run-aware guess never reaches the first write (F3). Each is a small,
local fix.

## Estimator probe (requested)

`wrapped_height_runs` on out-r9b's real runs (scratchpad/probe_d2.py), band width 1849 and 1892 give the
same numbers, and they reproduce the plan's F2 table exactly:

| box | live h | run-aware | single-font | live/run-aware |
|---|---|---|---|---|
| GW 13 text:1 | 269 | 273.7 | 242.1 | 0.98 |
| GW 17 text:1 | 186 | 153.7 | 140.9 | 1.21 |
| GW 17 text:2 | 189 | 166.6 | 80.9 | 1.13 |
| GW 28 text:1 | 349 | 382.0 | 254.3 | 0.91 |
| GW 13 text:0 (badge) | 82 | 87.6 | 87.6 | 0.94 |

So the run-aware estimator is a good first guess (±21%, worst case still under-predicting), as designed —
which is precisely why F1 and F3 below matter.

## Findings

**F1 (must-fix, correctness). The correction ratio divides by the estimate that is being replaced, so the
refit over-shrinks, and a second round throws the first round's correction away.**
`dsk_assemble.py:2429-2431` — `predicted_h = plan.fits[slide_no][box.item_id].h`, i.e. pass 1's
**single-font** rect, while `fit_text_stack` then applies that ratio to the **run-aware** estimate
(`dsk_plan.py:1021-1028`). The two errors are multiplied instead of the second replacing the first.
Measured (scratchpad/probe_d2e.py, real r9b heights): GW 17 text:2 gets `r = 189/80.9 = 2.34` applied to a
run-aware 166.6 → an effective target of ~390pt against a true 189, and the slide's fit collapses to
`t = 0.350` (source 70pt → 24.5pt, at the `--min-text-pt` floor) where `189/166.6 = 1.13` is the honest
correction. GW 28 likewise `r = 1.37` on a run-aware estimate that was already 9% **over**.
Second failure in the same expression: `plan.fits` is rewritten at 2449 with the *corrected* rect, so round
2's `r` is measured/(already-corrected), and the fresh `height_correction` dict (2426) does not accumulate
round 1's factor. Simulation (scratchpad/probe_d2c.py, a box whose true height is 2.0x the estimate):
`pass1 t=0.900 → round1 r=2.00 → t=0.580 (fits) → round2 r=1.00 → t=0.900 (live 666.8 vs rect 333.4)`.
A round 2 — which fires whenever round 1 lands more than 2pt over, i.e. routinely, given line-count
quantisation — *reverts* the fix and the run then refuses (warn) or drops to `--min-text-pt` (shrink).
Fix: compute `r` against the estimator the refit will use, at the size actually written —
`measured_h / wrapped_height_runs(runs scaled by the t last written, band.width)` — not against
`plan.fits[...].h`; equivalently, carry a persistent per-box correction across rounds and multiply into it.
Then the clamp `[1.0, 3.0]` is a real guard rather than a load-bearing bound. (Note the `1.0` lower clamp
also forbids correcting the *over*-predicting direction, GW 28's 0.91 — deliberate per plan, but it means
the refit can only ever shrink.)

**F2 (must-fix, correctness). A refit round re-stacks the long boxes but leaves the badge row where pass 1
put it — measured overlap on GW 17 and GW 28.**
`dsk_assemble.py:2439` calls `_stacked_text_rects` only; pass 1 pairs it with `_short_row_rects`
(`dsk_assemble.py:569-571`), which hangs the badge one gap above the stack top. The stack is
bottom-anchored (`_stacked_text_rects`, 166-176), so every refit moves the stack top. Measured with the real
r9b heights (scratchpad/probe_d2e.py): GW 13 −0.3pt (harmless), **GW 17 stack top 822.2 → 804.0 while the
badge occupies 738.0..812.2 → 8.2pt overlap**, **GW 28 799.7 → 778.1 against a badge at 742.4..789.8 →
11.7pt overlap**. Both are text slides in the nine-slide r10 set and both are refit targets, so this lands
in the live run. Fix: recompute `_short_row_rects(short_fit, short_row_h, new stack top)` in
`_build_refit_round` and emit the short boxes in the round's `TextRefit` writes (position only, no size
change); `short_fit`/`short_row_h` are not currently kept on `AssemblyPlan` — either stash them alongside
`stack_bands` (the pattern the commit already added at 141/754) or recompute them from
`plan.fits` minus `plan.stacked_ids`.

**F3 (must-fix, scope). Pass 1 never uses the run-aware estimator.**
`_text_boxes` (`dsk_assemble.py:246`) constructs `TextBox(...)` with no `runs`, and it is the only
`TextBox(` construction in `src/`; `_box_with_runs` (2371) is called *only* from `_build_refit_round`. The
payload already carries the runs at plan time (`load_assembly_inputs` → `attach_runs`, 931). Design B step 1
is "`fit_text_stack` uses it whenever runs are known" — the improved first guess. As shipped, every text
slide still gets the single-font first write (GW 17 text:2: 80.9 predicted vs 189 real) and therefore always
needs at least one live refit round; the offline acceptance in
`tests/test_dsk_content_rules_acceptance.py` and the "every rect inside the band" offline gate still grade
against the bad estimate. Fix: attach the runs in `_text_boxes` (one line, `_box_with_runs`'s body) so both
passes share one estimator — which also makes F1's denominator naturally correct.

**F4 (should-fix). The refit script addresses source `kindIndex`, not staged (post-delete) indices.**
`dsk_assemble.py:1604-1610` builds `f"{name} {kind_index + 1} of slide {ordinal}"` from the source id, but
it runs against a deck pass 1 has already deleted from; `_staged_kind_ranks`/`_staged_id_for`
(`dsk_assemble.py:2153/2187`) exist for exactly this translation and are used by the stroke/z-order paths.
Not live on this deck — I checked all nine r10 slides (scratchpad/probe_d2d.py): the only text deletes are
GW 17's `text:3/4/5`, all above the stacked `text:1/2`, so staged rank == source index everywhere. It is a
silent mis-write the first time a slide deletes a text item below a stacked one (a left-side mirror, a
dropped caption). Fix: route the refit address through `_staged_id_for`. Ordinals are fine — `plan.ordinals`
already includes split parts and pass 1 uses the same map.
(Hidden title/body placeholders do not shift anything: hiding retains collection membership. That is why the
`HIDDEN` branch must keep hiding rather than deleting.)

**F5 (should-fix). `_delete_order`'s dual dedupe keeps the address of the kind that is deleted *first*,
which is the one that shifts the other kind's indices.**
`dsk_plan.py:38-54` sorts by `(kind, -index)` and keeps the first survivor, so GW 17's dual resolves to
`("shape", 1)` and drops `("text", 3)` (pinned by `tests/test_dsk_plan.py::test_delete_order_dedupes_dual_shape_text_address`).
`"shape" < "text"`, so the emitted order is `shape 2` … `text item 6`, `text item 5`. Deleting object
17290708 *as a shape* removes it from the slide's text collection too, so the remaining text items renumber
and `text item 6` becomes a −1728 → slide-level refusal. Descending-within-kind only protects against
same-kind shifts. Keeping the **text** address instead (and never emitting the shape one) is safe here
because no other shape address remains; in general, resolve a dual to the address of the kind that sorts
**last** among the kinds present in that slide's delete list, so every other kind's addresses have already
been consumed. Today this is masked whenever the dual is the title/body placeholder (hidden, not removed) —
which is exactly the unverified invariant the ph-review's F2 asked to retire.
Related: `dsk_movie_export.py:302,593` still call `_delete_order` without `id_by_item`, so the clip-export
scratch script keeps the duplicate address (tolerant there — it only logs DELETEFAIL — but inconsistent).

**F6 (should-fix). The `HIDDEN` marker is emitted but never parsed.**
`remap_keynote.py:88,91` logs it; `grep -rn HIDDEN src/ tests/` finds no consumer. The ph-review's F1 asked
for it "parsed into `warnings`/a result field next to `DELETEFAIL`, so the run states which object tripped
it". As shipped it reaches raw `run.err` only, and neither `assemble_dsk_deck`'s stderr loop (2620-2650,
which matches `OBED\t…` — `HIDDEN` lines do not start with `OBED`) nor `_DELETEFAIL_RE` sees it, so the
"was the hide branch ever taken?" question the marker exists to answer still cannot be answered from
`AssembleResult`. Fix: one regex + a `warnings.append` / `AssembleResult` field. Otherwise the identity /
try / `id of` rework (F3 of the ph-review) is correctly done and well tested.

**F7 (should-fix). Shrink mode jumps straight to the floor, flattens the runs, and then declares success.**
`dsk_assemble.py:2515` writes `TextRefit(rect, min_text_pt)` — a single flat size for the whole box, wiping
the ArgentCF-Bold emphasis ratio the whole D2 exercise is about, and at `--min-text-pt` rather than "the
measured-fit size, never below `--min-text-pt`" as the plan specifies. The final write is then never
re-measured (its `proc` is discarded, 2523), and `overflows[:]` at 2525 clears *every* eligible key
unconditionally, so `AssembleResult.overflows` is empty even when the box is known to still overflow — the
acceptance criterion "`Overflows (0)`" becomes unfalsifiable. Pass 1's stale `"slide N: text text:K
overflow"` warnings (2637) also survive the successful refit, so `run.out` still shows overflow warnings on
a clean run. Fix: shrink to the fitted size with run ranges scaled (reuse `_run_size_ranges` at the shrunken
`t`), parse the final MEASURE, and only clear the keys that actually came back under budget.

**F8 (nit, latent crash). `measured[key]` can `KeyError`.**
`dsk_assemble.py:2431`. `_refit_still_over_budget` (2396) puts a key in `todo` when `measured_h is None`,
and `_build_refit_round` then indexes `measured[key]` directly. Narrow today (MEASURE is logged immediately
before OVERFLOW inside the same `try`), but a dropped/truncated stderr line turns a text-fit problem into an
unhandled exception mid-batch. Use `.get` and skip. Related: a refit round whose write block errors emits no
MEASURE, and `measured` is `update`d rather than reset, so the loop silently re-reads the previous round's
height and believes nothing changed.

**F9 (nit). The refit writes `height` on boxes pass 1 deliberately leaves autosizing.**
`dsk_assemble.py:1614` always emits `set height of theObj`; `_slide_lines:1355-1356` guards it with
`if item_id not in autosize_ids`, and `build_refit_script` has no access to `plan.autosize` (it `del plan`s
its only argument, 1587). Not live on the r10 set (`plan.autosize` is empty for all nine slides), but it
contradicts the pass-1 invariant the plan states explicitly ("never `height` on an autosize child").
Fix: pass the autosize set (or stop `del plan` and read `plan.autosize`).

**F10 (nit). `build_refit_script`'s `plan` parameter is dead (`del plan`, 1587)** — drop it, or use it for
F4/F9. Both tests pass a `plan` that is never read.

**F11 (nit). The unresolved-run-gap refusal is not honoured on a refit.**
`dsk_assemble.py:2446`: `run_sizes = ranges if isinstance(ranges, (tuple, float)) else sizes[box.item_id]`.
Pass 1 treats `ranges is None and unresolved` with `t < 1.0` as an `AssemblyRefusal` under `--text-fit warn`
(585-593); the refit silently flattens instead. `_unresolved` is discarded at 2444. Also
`_run_size_ranges(..., warnings=warnings)` is re-called every round, so its warnings duplicate per round.

**F12 (nit). `Iterable` is used unimported.** `dsk_assemble.py:2391`. Harmless at runtime only because of
`from __future__ import annotations`; `typing.get_type_hints(_refit_still_over_budget)` raises
`NameError: name 'Iterable' is not defined`. Add it to the `collections.abc` import at line 14.

**F13 (nit). `build_assembly_script(finalize=False)` is dead code.** The implementer's (sanctioned)
deviation means pass 1 always finalizes; nothing in `src/` passes `finalize=False`, and the only coverage is
`test_assembly_script_finalize_false_has_no_save`. Either drop the parameter or state in the docstring that
it exists for a future held-open variant — right now the docstring advertises a pass-1 mode that is not
used.

**F14 (nit, residual risk — the plan's own open question 1). The settling poll can exit on two identical
*stale* reads.** `_text_measure_lines` (1246-1279) reads, compares to `prevH = -1`, waits 0.2s, reads again,
and exits on the first match. r9b's evidence is that Keynote returns the pre-relayout height (249 vs 269);
nothing proves the relayout has *started* within 200ms, in which case two stale reads agree and the poll
certifies the stale number. The plan's cheapest probe — "log MEASURE both immediately and again at the end
of the slide loop" — was dropped; without it, r10 cannot distinguish "the poll settled" from "the poll
agreed twice on a stale value". Recommend adding a second end-of-batch MEASURE pass under a distinct key for
the r10 run only; it is a handful of lines and it is the one thing that would falsify the whole design.
Cost note: the poll always spends at least one 0.2s delay per stacked box (the first comparison is against
the `-1` sentinel), worst case 0.8s.

**F15 (nit, style). House rules.** "MINIMAL NATSPEC, no history prose": the diff carries plan bookkeeping in
shipped docstrings — `D2 step 5` (`dsk_live.py:460`), `D2 step 2` (`dsk_assemble.py:1457`), `D2 steps 2/4`
(1582), `D2 step 4` (2384, 2414, 2468, `dsk_plan.py:1008`) and `(F1)`/`(F2)`/`(F3)` back-references
(`dsk_plan.py:42,922`, `remap_keynote.py:77,79`) — these name a scratchpad plan and a review that will not
be in the repo. Several new docstrings also run well past two lines
(`_delete_or_hide_placeholder_lines` 11, `_text_measure_lines` 7, `_run_refit_and_finalize` 6). Trim to what
the next reader needs (`remap_keynote.py`'s "-10003, `default title item` is read-only per Keynote.sdef" is
worth keeping; "F1"/"F3" is not).

## Tests

- **Green, and no regression on non-text slides.** Full suite 2310 passed / 84 skipped / 1 xfailed. The only
  behaviour reaching a non-text slide is the `_delete_order` dedupe (engaged only when `objects_graph` is
  available) and the extra `MEASURE` log lines, which are consumed by their own `elif` before the
  `movie_props` fallback (2638-2641) and so cannot pollute `movie_props`.
- **`test_wrapped_height_runs_charges_emphasis_run_font` does not use real values** (the brief asked).
  It invents "Steadfast love of the LORD…" / "his mercies never come to an end;" rather than GW 17 text:2's
  actual runs, and `predicted >= 1.9 * single` is near-tautological: the run version renders the same words
  with a 62.9pt bold second run against a 51.8pt single-font baseline. Pin the real run list and assert
  `≈166.6` (I reproduced it from out-r9b; it is stable across band widths 1849 and 1892).
- **`test_refit_loop_converges_in_two_rounds` is misnamed and misses F1**: it asserts `len(calls) == 2`, i.e.
  pass 1 + **one** refit. Nothing in the suite exercises a *second* refit round's correction arithmetic,
  which is why the round-2 regression in F1 is invisible. Add a test where round 1 measures over, round 2
  measures slightly over (2–10pt), and assert `t` (or the written size) is monotonically non-increasing
  across rounds.
- Also untested: the badge/short-row position after a refit (F2), staged addressing (F4), the shrink path's
  emitted size (F7 asserts only the warning string), and the `HIDDEN` marker end-to-end (F6).
- `test_delete_or_hide_placeholder_lines_branches_on_title_and_body`'s `script.count("try") >= 2` also counts
  `end try`; use the line-anchored count.

## What is right

- `_text_measure_lines` / `_parse_measure_lines` / the `MEASURE` `elif` are clean, and the `MEASURE`-always +
  `OVERFLOW`-as-gate split matches the plan.
- `retry_on_1712=False` is correct and correctly tested (`test_live_batch_run_no_retry_flag` asserts one
  `run_osascript`, one `copy_keynote`, no quit-and-wait), and it is passed on every refit call.
- Split slides are excluded twice over (`_eligible_refit_items` returns empty for `plan.splits`, and the
  `text:idx:ordinal` keys fail `isdigit()`), so the out-of-scope interaction is clean; `plan.ordinals`
  already accounts for parts, so the refit's ordinals are right.
- `stack_bands` is the right thing to have persisted (verified populated exactly for the stacked slides,
  `None` elsewhere, with the per-slide shrunken heights 258.5/265.8/292.6 for GW 13/17/28).
- The ph-review's F3 rework (`id of` inside a `try`, `missing value`/raise fall-through to plain delete) and
  F7 (helper moved to `remap_keynote`, `indent` parameter replacing the `f"  {ln}"` surgery) are done
  properly and well covered.

## Probes (read-only, in scratchpad)

`probe_d2.py` (run-aware vs live heights), `probe_d2c.py` (round-2 regression simulation),
`probe_d2d.py` (staged text indices + autosize + stack bands on the nine r10 slides),
`probe_d2e.py` (stack-top movement vs badge rects with the real measured heights).
