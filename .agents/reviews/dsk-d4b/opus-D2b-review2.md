# Opus review 2 — piece D2b (offline measurement authority) + Codex D2 review 1 fixes

Target: `1ab0768` (round-2 delta = `git diff 8487145 1ab0768 -- src tests`; whole piece = `git diff f34c574 -- src tests`),
worktree `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen`.
Read-only; probes in the scratchpad only; no repo edits, no Keynote, no commits; no Agent tool used.

**Verdict: APPROVE-WITH-NITS.** All nine findings from review 1 are genuinely resolved, including the
two that round 1 had knowingly deferred (C2 equivalence tests, C6 wiring). I re-probed the C2
tokenizer independently and found no divergence. No regressions. The four nits below are
follow-up-grade: one dead branch, one weak test seam, one C6-adjacent gap in a neighbouring pass, and
a note that the `_wrap_lines` fix is a plan-wide behaviour change worth recording.

## Verification I ran myself

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_dsk_assemble.py tests/test_dsk_plan.py tests/test_offline_inspect.py -q`
  → **397 passed, 13 skipped, 1 xfailed** (was 385; +12 new tests).
- Full suite `PYTHONPATH=src … -m pytest tests -q` → **2346 passed, 84 skipped, 1 xfailed**, no
  failures. The `_wrap_lines` separator change (finding 6) moved no other test's numbers.
- **C2 re-probe** (`<scratchpad>/probe_c2_r2.py`), the item the brief singles out: single-run and
  two-run equal-font splits, texts built from random words joined by `" "`, `"  "`, `"   "`,
  U+2009, U+2009U+2009, `" "+U+2009` and `"\n"`, at widths 60/100/200/300/500, **every** split
  position — **40 805 (text, split, width) combinations, 0 mismatches** against `wrapped_height`
  to 1e-6. Spot values: `"alpha  beta   gamma delta"` @200 → 206.12 == 206.12 (was 206.12 vs
  159.84); `"alpha beta gamma delta"` @200 → 206.12 == 206.12 (was 159.84 vs 206.12);
  `"a  b"` → 67.28 == 67.28. Consecutive breaks and thin spaces now agree in both
  directions.
- Read the round-2 source deltas in context (`dsk_assemble.py:2451-2472`, `:2571-2643`,
  `:2660-2790`, `:2917-2936`; `dsk_plan.py:884-905`, `:986-1037`).
- Confirmed `"set prevH to -1"` really is the poll's distinctive text: it exists at
  `f34c574:src/obed_edom/dsk_assemble.py:1285` and is gone at HEAD, so the new guard would have
  failed before the removal (the old `"repeat with i from 1 to"` guard was generic).

## Review-1 findings — resolution

| # | sev | status | evidence |
|---|---|---|---|
| 1 | high | **fixed** | `dsk_plan.py:1032-1035`: a below-floor run now contributes `1.0`, `min_text_pt <= 0` returns early. `_box_min_t` = 1.0 for all-below-floor (runs and no-runs), 0.8 for the mixed box. Both consumers covered: `test_box_min_t_all_runs_below_floor_does_not_shrink`, `test_fit_text_stack_all_runs_below_floor_refuses_to_shrink_further`, and end-to-end `test_shrink_fallback_all_runs_below_floor_leaves_size_unchanged` (asserts the written size == pass 1's size and the "already at the floor" wording). The `at_floor` predicate change to `>=` is required by this fix and is right: with `t_floor == t_prev == 1.0` the box is at its floor and must be reported as such, not as "shrunk to". |
| 2 | med | **fixed** | New `_refuse_on_missing_measures` (`dsk_assemble.py:2617-2632`) called after all three `_offline_measure` sites (`:2670`, `:2698`, `:2765`); `_offline_measure` now returns its own `measure_warnings` so the refusal text carries the real cause. Two discriminating tests: `test_refit_round_dropped_measure_refuses_immediately` (asserts `len(calls) == 2`, i.e. no wasted pass) and `test_refit_loop_refuses_immediately_on_unlogged_hide` (matches `staged text count 1 != offline text count 2`, `len(calls) == 1`). |
| 3 | med | **fixed** | `:2767` now passes `eligible_keys`, matching the round loop. |
| 4 | low | **fixed** | `_refit_still_over_budget` gained `band: Band \| None` and uses `plan.stack_bands.get(slide_no, band)` (`:2471`); all three call sites pass `band=band`. Now consistent with `_build_refit_round:2526` and with plan §6.5. |
| 5 | low | **fixed** | `pending_seps` is a list, every separator charged (`dsk_plan.py:988-1006`); verified by probe and by `test_wrapped_height_runs_charges_every_consecutive_separator`. |
| 6 | low | **fixed** | `_wrap_lines` now tokenizes with a capturing `tok_re` and joins with the *actual* break char (`dsk_plan.py:887-902`), so U+2009 is measured at its real width. `test_wrapped_height_thin_space_separator_matches_runs` covers it. The two estimators now agree on every case I could construct. |
| 7 | low | **fixed** | `test_wrapped_height_runs_equivalence_named_cases` (Codex's three named cases) plus `test_wrapped_height_runs_equivalence_fuzz` (seeded, ~50 texts × 2 widths × split positions). |
| 8 | low | **fixed (now actually wired)** | `hidden_map` is built once at `:2920` and threaded to `_restore_stroke` (`:2933` → `:1769`) and `_verify_builds` (`:2936` → `:2334` → `_merge_split_part_builds`). Both new paths have discriminating tests that assert the *wrong* answer without `hidden` (`test_staged_retained_ids_retains_same_kind_item_after_hidden_placeholder`, `test_merge_split_part_builds_dedupes_repeated_item_after_hidden_placeholder`). The fold-parts-into-one-source-key concern I raised is moot: `hidden` is keyed by source number and read per number at each call site. |
| 9 | low | **fixed** | Converge test is now a real two-round sequence (`[500, 400, 270]`, `len(calls) == 3`); both `never_writes_above_pass1_size` tests use real over-budget rects instead of `_MISSING_RECTS`; `test_offline_measure_hidden_placeholder_retains_staged_id` banks the probe (both branches: correct with `hidden`, E cross-check fires without); poll guard is now `"set prevH to -1"`. |

## Brief's checklist (re-checked at HEAD)

(1) staged→source inversion with a delete below the stack and with a hidden placeholder — correct,
now unit-tested for both. (2) `eligible_keys` is plan-derived, loop runs with no `OVERFLOW` line at
all. (3) Band semantics `top = bottom - height` (704) / `bottom + 1.0` (1055) correct, applied only
after the rect check, and the shrink fallback's recheck now spans the same key set. (4) C1
`_check_refit_batch_result` after both `batch.run` sites. (5) C2 verified above. (6) per-run floor in
both consumers; `t = min(max(min(t_fit, t_prev), t_floor), t_prev)` keeps `t <= t_prev` hard. (7) C4
refusal on residual `todo` intact. (8) MEASURE2 / `_second_measure_lines` / poll all gone, divergence
`log()` line present at `:2673-2676`. (9) house style matches the module. (10) tests discriminate
(see nit 2 for the one exception).

## Nits (none blocking)

### 1. Dead branch: the "measure missing this round" warning is now unreachable — low
`src/obed_edom/dsk_assemble.py:2518-2522`. `_build_refit_round` is only ever called with
`todo ⊆ eligible_keys`, and `_refuse_on_missing_measures` has already guaranteed every eligible key
is in `measured`, so `elif measured_h is None:` can never fire. Its only test was (correctly) replaced
by `test_refit_round_dropped_measure_refuses_immediately`, so it is now dead *and* untested.
Fix: delete the branch, or keep it as an explicit `AssemblyRefusal`/assert so it cannot silently
soften the new refusal contract later. (The parallel `measured_h is None` arm in
`_refit_still_over_budget:2465` is fine — it is a genuine defensive guard on a helper that unit tests
call directly.)

### 2. Finding 3's fix is tested at the helper, not at the call site — low
`tests/test_dsk_assemble.py:1733-1753` (`test_refit_still_over_budget_eligible_keys_catches_shrink_displaced_sibling`)
proves `_refit_still_over_budget` behaves differently for `todo` vs `eligible_keys`, but nothing
exercises `dsk_assemble.py:2767` itself; reverting that one line leaves the suite green. Fix: an
end-to-end shrink fixture whose post-shrink offline read puts a *sibling* out of band and asserts the
refusal. ~20 lines on top of the existing shrink fixture.

### 3. `_restore_crop_zorder` still assumes every planned delete happened — low, C6-adjacent
`src/obed_edom/dsk_assemble.py` (`_restore_crop_zorder`, the `deleted_not_cropped` / `target_index`
computation). It is the one post-pass in this group that was *not* given `hidden`, and it derives the
target z-order index by counting source items "not deleted". A delete Keynote refused (a `HIDDEN`
placeholder) is still counted as deleted, so a cropped image on such a slide lands one slot off.
Same class as C6, different function; out of scope for D2b but worth a follow-up line in the ledger.

### 4. `_wrap_lines`' separator fix is a plan-wide behaviour change, not only a refit one — low
`src/obed_edom/dsk_plan.py:887-902`. `wrapped_height` is the estimator the *planner* uses, so any
deck whose text contains thin spaces or runs of spaces now gets a taller prediction (correctly — the
old code under-charged U+2009 by 2.7×, and that is the direction that lets a box overflow). No test
moved, but this changes planner output on real decks, so it belongs in the piece record as a
deliberate behaviour change rather than a pure refactor.

## Items confirmed good (no action)

- `_refuse_on_missing_measures` raises before any further live pass at all three sites, and the
  message carries the offline warnings verbatim.
- `hidden` defaults are immutable-by-use (`Mapping[...] = {}`), matching the module's existing
  convention; no call site mutates them.
- `_offline_measure`'s ordinal coverage exactly matches `eligible_keys`' domain (both iterate
  `plan.ordinals`, both exclude `plan.splits`), so a missing ordinal surfaces as the count-mismatch
  refusal rather than a silent gap.
- Gate outcome still honoured: `soft_geometry` read into `_soft` and deliberately ignored; §9(a)
  absent; C5 deferral documented in `_run_refit_and_finalize`'s docstring.
- Stale-warning cleanup and `overflows[:]` filtering are unchanged and still correct (`todo` is
  provably empty at that point); the shrink pass's own warnings use prefixes the cleanup does not
  match, so they survive.
