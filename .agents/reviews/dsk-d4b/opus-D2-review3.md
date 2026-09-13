# Review 3 — d4b piece D2 (run-aware estimator + live measure-then-refit), fix round 3

Tree under review: `feat/dsk-gen` @ **1123efd** (`git diff 9b486a8 -- src tests`). Working tree clean
apart from untracked `.venv`, so HEAD *is* the tree (no uncommitted cli.py/dsk_live.py edits to ignore).
Suite from the worktree: **2321 passed, 84 skipped, 1 xfailed, 2 FAILED** (84s) — see H4; both failures
are the concurrent `--rss-limit` work, not D2.

Verdict: **REVISE** — G1 is fixed on the route the probe exercised, but the *same* symptom (the shrink
fallback writing a box larger than pass 1 wrote, labelled "shrunk") survives on a second route I
reproduced: the floor `t_floor` can exceed `t_prev` and then wins the `max()`. One-line fix. Everything
else in G1–G8 is genuinely resolved, and the G3 deviation is the right call.

## Verification of G1–G8

- **G1 — fixed on the seeded route, see H1 for the residual.** `stack_t` is recorded at the same site as
  `stack_bands` (`dsk_assemble.py:588`, dataclass field 157, returned 820) and `last_t` is seeded from it
  (2576). Re-ran `probe_shrink2.py` unchanged against this HEAD: `test_enlarge` now emits
  `set size … to 38.4` in *both* pass 1 and the shrink pass (was 38.4 → **40**), warning
  `shrunk to 38.4pt`; `test_fit_none_route` still clamps to 24. The three routes into shrink
  (missing MEASURE, `len(boxes) != len(stacked)`, `fit is None`) all `continue`/`break` before touching
  `last_t`, so the seed is what they see — correct. Split slides have no `stack_t` entry, but
  `_eligible_refit_items` (2431) excludes split slides from refit entirely, so `t_prev = 1.0` is
  unreachable for them; when pass 1 never stack-fitted a slide, `1.0` is the genuinely correct default.
- **G2 — wired.** MEASURE2 now parsed inline (2786-2797) against the `measured` entry from the same scan,
  warning + `log` when `|Δ| > 2.0`; `_parse_measure2_lines`/`_MEASURE2_RE` gone; emission untouched.
  `test_measure2_mismatch_warns_end_to_end` (tests:1767) drives the real `assemble_dsk_deck`. One leftover
  in H3.
- **G3 — fixed, and the deviation is right.** I checked the implementer's claim directly: a hidden delete
  target is indeed never a member of `fits_here` (it is excluded from `fit_slide`'s kept set), so the
  review-2 wording ("treat them as not deleted" inside the old loop) would have been a no-op.
  `retained_ids = (set(fits_here) - deleted) | (deleted & hidden)` (2209) is the correct formulation:
  `hidden` is by construction a subset of `deleted` (the HIDDEN log is only emitted from the delete block,
  `remap_keynote.py:65-92`), and the address it carries is the **source** `kindIndex`, matching
  `plan.deletes` — `_delete_order` emits deletes high-to-low within a kind (`dsk_plan.py:38-45`), so no
  earlier delete shifts a later address, and a hidden item shifts nothing at all. `_item_id_from_addr`
  (93) reverses exactly the address `_slide_lines` writes (1416-1426). The test at tests:~`
  test_refit_script_staged_index_retains_hidden_item_below_stack` is a real before/after (text item 2 vs
  text item 3), not tautological.
- **G4 — fixed.** `grep -rnE "\bF[0-9]+\b|D2 step"` over `dsk_assemble.py`, `remap_keynote.py`,
  `dsk_live.py` is now empty; the only hits are pre-existing D1/D4 notes in `dsk_plan.py`. Docstrings at
  1262 (3 lines), `remap_keynote.py:70` (3), `_build_refit_round` (2466-2468, 3) keep only load-bearing
  facts. The 3-line `_build_refit_round` docstring is fine — the formula and the persistence/clamp are
  what a modifier needs.
- **G5 — fixed.** `finalize` is gone; `grep -rn "finalize" src/obed_edom/dsk_assemble.py` returns only
  `_run_refit_and_finalize`.
- **G6 — fixed.** `lead_source_size` (2616) drives both the written flat size and the warning; the range
  form `lo-hi pt` is emitted for a genuine per-run tuple (probe H1 shows `shrunk to 24.0-32.0pt`); the
  unresolved path now warns via the shared `warned_gaps`, and the re-derivation passes `warnings=None`
  (2623) so it cannot duplicate a round's gap warning.
- **G7 — fixed.** `for key in todo: measured.pop(key, None)` (2594) runs on the round's *own* `todo`
  (captured before the round; `todo` is only reassigned at 2597), so a dropped MEASURE surfaces as missing
  rather than stale, and `_build_refit_round` now says so out loud (2490-2494).
- **G8 — fixed.** Hand-`update` line dropped; `test_refit_second_round_measured_equals_rect_h_leaves_
  correction_unchanged` (tests:1327) pins the magnitude (ratio 1.0 ⇒ correction unchanged); the four blank
  lines are gone.

## Findings

**H1 (must-fix, correctness — G1 residual). `t_floor` can exceed `t_prev`, and `max()` lets it enlarge.**
`dsk_assemble.py:2617-2622`.
```
t_floor = min(1.0, min_text_pt / min_source_size) ...
t_prev  = last_t.get(slide_no, 1.0)
t       = max(min(t_fit, t_prev), t_floor)
```
`t_floor` is derived from the box's **smallest run** size, while pass 1's own floor inside
`fit_text_stack` is `min(min_text_pt, box.size)` — the **lead** size (`dsk_plan.py:1021`). On a mixed-run
box whose smallest run is below the lead, the shrink floor is strictly larger than the floor pass 1
honoured, so `t_floor > t_prev` is reachable and the `max()` writes the box *up*.
Reproduced (`probe_shrink3.py` in the scratchpad; single stacked box, lead 40pt, trailing run 30pt,
`--min-text-pt 24`, 240 words, OVERFLOW with no MEASURE):
```
PASS1:  characters 1-1180 → 28,  1181-1199 → 21
SHRINK: characters 1-1180 → 32,  1181-1199 → 24      (+14%)
WARN:   slide 13: text text:0 shrunk to 24.0-32.0pt after refit (floor 24.0pt)
```
i.e. exactly the G1 symptom — bigger than pass 1, on a box it has just declared still overflowing, sold
as a shrink. The `(floor …)` note even fires, so the log looks legitimate.
Fix: `t_prev` must be a hard upper bound — `t = min(max(min(t_fit, t_prev), t_floor), t_prev)`, or
equivalently clamp `t_floor = min(t_floor, t_prev)` before the `max`. Root cause worth fixing too: make
the floor base agree with pass 1 (`min_text_pt / float(item.get("size") or min_source_size)`, i.e. the
lead size already computed one line below as `lead_source_size`), so the two passes cannot disagree about
what "at the floor" means. When the floor would have exceeded `t_prev`, the honest warning is "already at
the floor, left at Xpt" rather than a shrink claim. G1's regression test
(`test_shrink_fallback_never_writes_above_pass1_size`, tests:1711) uses a uniform-run box and therefore
cannot see this — extend it with a mixed-run case (or add one alongside).

**H2 (nit, consistency with G3). `hidden` was threaded into the refit path only.**
`_staged_retained_ids` (2218) still calls `_staged_kind_ranks` with no `hidden` (2221), and its caller at
1791 uses the result to decide which staged `(kind, kindIndex)` survive when rewriting z-order/media in
the saved archive. If the G3 premise is right — a hidden default title/body keeps its slot — then that
path has the same off-by-one for every item above a hidden one; if the premise is wrong, G3's own fix is
the one that shifts. Either way the two sites should share one answer. Since neither can be settled
without Keynote, the r10 run is the place to confirm: the cheapest check is a slide whose delete list
contains the default body plus a text item above it, then compare the HIDDEN address against the staged
index the refit actually addressed. Worth a line in the r10 checklist rather than a speculative change.

**H3 (nit). `measure2` is now a write-only dict.** `2760`, `2789` — every consumer is the inline
comparison two lines later; nothing else reads the mapping. Drop the dict and compare directly (keep the
warning), or put it on `AssembleResult` if a later run wants the pairs.

**H4 (not D2, but the suite is red at HEAD).** `tests/test_dsk_assemble.py::test_cli_dsk_assemble_builds_
decisions` and `::test_cli_dsk_assemble_layout_name_override` fail with
`fake_assemble_dsk_deck() got an unexpected keyword argument 'rss_limit_bytes'` — the fakes were not
updated when `cli.py:484` started passing `rss_limit_bytes` (commit d9b41ef, the concurrent `--rss-limit`
work). Not caused by fix round 3, and the report's "2320 passed / no failures" was presumably measured
before d9b41ef landed on this branch; whoever owns the rss-limit change should add the kwarg to those two
fakes. Flagging so the D2 sign-off is not read as "suite green".

## What is right

- Both of round 2's load-bearing behaviours survive intact: re-running `probe_shrink2.py` and inspecting
  `_build_refit_round` shows the accumulating `correction` (2486-2489, clamped `[1.0, 3.0]`) and the badge
  re-stack (2528-2535, emitted as `TextRefit(rect, None)`) unchanged.
- The G3 fix is the rare case of an implementer correctly *not* following the review's literal wording,
  and saying so with the reason; the deviation report is accurate.
- Every G finding got a test that discriminates (I read the four new ones; none are tautological), and
  the G1 test independently recomputes pass 1's size from `plan_assembly(...).stack_t` rather than
  asserting on a hard-coded string.
- House style is clean in the D2 files now: no review bookkeeping, no inline comments added, docstrings at
  2-3 lines.
