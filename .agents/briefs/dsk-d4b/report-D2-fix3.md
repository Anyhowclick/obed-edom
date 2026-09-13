# Report: D2 fix round 3 — apply opus review 2

Worktree: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen (branch feat/dsk-gen). No commits/git add made. Only edited files: src/obed_edom/dsk_assemble.py, src/obed_edom/remap_keynote.py, tests/test_dsk_assemble.py.

## G1 (must) — shrink fallback could enlarge — FIXED

- AssemblyPlan.stack_t: dict[int, float] added (dsk_assemble.py dataclass, next to stack_bands).
- plan_assembly now sets stack_t_map[number] = t right where pass 1's fit_text_stack succeeds for the whole stack (same site stack_bands/short_fit are recorded), and returns it on the plan.
- _run_refit_and_finalize seeds last_t: dict[int, float] = dict(plan.stack_t) before the refit loop (was {}), so a slide that reaches the shrink fallback via a missing MEASURE, len(boxes) != len(stacked), or fit_text_stack is None route now has t_prev = pass 1's real fitted size instead of defaulting to 1.0 (the source size). The existing t = max(min(t_fit, t_prev), t_floor) arithmetic already enforced t <= t_prev as an upper bound -- the only bug was the wrong seed.
- Tests added:
  - test_shrink_fallback_never_writes_above_pass1_size -- reproduces probe_shrink2.py::test_enlarge (120-word single-font box, OVERFLOW with no MEASURE, forcing the missing-MEASURE route straight into shrink). Asserts the emitted size <= pass1_size (computed independently via plan_assembly(...).stack_t[13] * 40.0).
  - test_refit_round_dropped_measure_warns_and_keeps_prior_size -- the missing-MEASURE-mid-refit-loop route: pass 1 overflows and measures, round 1's re-measure is dropped entirely ("OBED\t13\tdone" only), asserts the loop doesn't fabricate a correction and resolves cleanly via the shrink fallback.

## G2 (should) — MEASURE2 dead code — WIRED UP

- assemble_dsk_deck's stderr-parsing loop now handles MEASURE2 inline: builds a measure2: dict[(slide, item_key), float] and, when abs(measure2_height - measured_height) > 2.0, appends and logs "slide N: text K measure settled at X but re-read Y at end of slide".
- Removed _parse_measure2_lines and _MEASURE2_RE -- now genuinely dead once the comparison is done inline against the same _OBED_PROP_RE match already used for MEASURE/OVERFLOW (no second full-stderr pass needed). The emission (_second_measure_lines) is untouched, as required.
- Test added: test_measure2_mismatch_warns_end_to_end -- drives assemble_dsk_deck with a MEASURE/MEASURE2 pair 10pt apart and asserts the exact warning string.

## G3 (should) — hidden items mis-shift staged refit index — FIXED

- Root cause was slightly different from the literal suggestion: a hidden delete target is never in plan.fits in the first place (it's excluded from fit_slide's kept set, same as any deleted item), so subtracting hidden from the delete set inside the old "for kind, idx in fits_here: if (kind, idx) in deleted: continue" loop was a no-op. Rewrote _staged_kind_ranks to compute retained_ids = (set(fits_here) - deleted) | (deleted & hidden) -- i.e. explicitly add back any delete target that turned out to be hidden (still occupies a slot in Keynote's item collection) rather than merely declining to filter it out of a set it was never in.
- _staged_id_for and build_refit_script now take a hidden: frozenset[ItemId] / Mapping[int, frozenset[ItemId]] parameter and thread it through.
- assemble_dsk_deck reverses each HIDDEN log line's AppleScript address ("text item 3 of slide 5") back to (kind, kindIndex) via a new _item_id_from_addr helper (_ADDR_RE + _AS_KIND_NAMES_REV), builds hidden_ids: dict[int, set[ItemId]] during the same stderr scan that already parses HIDDEN lines, and passes it into _run_refit_and_finalize(..., hidden=...), which threads it to both build_refit_script calls (round refits and the shrink fallback).
- Test added: test_refit_script_staged_index_retains_hidden_item_below_stack -- a text item at a lower kindIndex is deleted; without hidden= the item above it addresses one slot too low (text item 2); with hidden={13: frozenset({("text", 0)})} it correctly addresses text item 3.

## G4 (nit, house style) — stale review references / long docstrings — FIXED

- dsk_assemble.py _text_measure_lines docstring trimmed from 7 lines (with the dangling "F3" reference) to 3 lines, no review back-references, -10003/mechanism facts kept only where load-bearing.
- remap_keynote.py _delete_or_hide_placeholder_lines docstring trimmed from 11 lines to 2, keeping the -10003/sdef fact and the HIDDEN log format (both load-bearing for readers), dropping the "as before"/history prose.
- _build_refit_round docstring trimmed from 5 lines to 3 (still over the "<=2" target by one line given the formula plus the persisted-correction fact both need stating; both are load-bearing, not history prose -- no bug-that-no-longer-exists justification left in it).
- Verified: grep -rnE "\bF[0-9]\b|D2 step" src/obed_edom/{dsk_assemble,dsk_plan,remap_keynote}.py (dsk_live.py has no matches either) -- the only remaining hits are in dsk_plan.py (F2/F3/F9), which the review itself flagged as pre-existing D1/D4 material out of scope for this diff; nothing new remains in dsk_assemble.py or remap_keynote.py.

## G5 (nit) — dead finalize param — REMOVED

- build_refit_script's finalize: bool = True parameter deleted; the function now always emits save/close unconditionally (same shape as build_assembly_script). Both call sites in _run_refit_and_finalize updated to drop finalize=True and instead pass the new hidden= argument. No test referenced finalize= (confirmed by grep), so no test changes were needed for this one beyond what G3 already touched.

## G6 (nit) — shrink warning reports smallest run, duplicate gap warnings — FIXED

- The final shrink-fallback block now computes lead_source_size = float(item.get("size") or min_source_size) (the box's own lead/base size, matching fit_text_stack's sizes[box.item_id] semantics used everywhere else) instead of min_source_size, and reports it (or, when _run_size_ranges resolves a genuine per-run tuple, the lo-hi range) rather than always the smallest run's size.
- The unresolved/gap path now emits the same "run ranges leave a gap, flattening run sizes to the lead size under --text-fit shrink" warning pass 1 and the refit rounds already emit, deduped via the shared warned_gaps set (declared once in _run_refit_and_finalize and reused across rounds and the final block) -- previously this path was silent.
- The re-call to _run_size_ranges in the shrink fallback now passes warnings=None (matching round 1's pattern) instead of warnings=warnings, so a gap warning a refit round already emitted can't be duplicated by the final block re-deriving ranges for the same box.

## G7 (nit) — measured never reset per round — FIXED

- In the refit loop, the keys attempted in the just-run round (todo, captured before the round) are popped from measured before measured.update(_parse_measure_lines(...)) -- a dropped MEASURE for one of those keys now shows up as genuinely missing (not the stale prior-round height), so _refit_still_over_budget correctly keeps it in todo rather than silently reusing an old measurement.
- _build_refit_round now emits "slide N: text K measure missing this round, no correction change" when a todo key has no measured entry (previously silent -- any_new just stayed False for that box).

## G8 (nit, tests) — FIXED

- test_refit_second_round_accumulates_correction: dropped the redundant plan.fits[13].update(...) line (the production code already persists rects inside _build_refit_round).
- Added test_refit_second_round_measured_equals_rect_h_leaves_correction_unchanged -- a round-2 case where measured == rect_h (ratio 1.0), pinning the magnitude of the correction accumulation, not just its sign.
- Removed the 4 consecutive blank lines at tests/test_dsk_assemble.py (between test_script_overflow_readback_omitted_for_uniform_run_text and test_refit_script_reopens_and_saves, left over from the deleted test_assembly_script_finalize_false_has_no_save).

## Test counts

- Targeted run (tests/test_dsk_assemble.py tests/test_dsk_plan.py tests/test_dsk_live.py): 347 passed, 1 xfailed (was 342 passed, 1 xfailed before this round -- net +5 new tests, all passing).
- Full suite: 2320 passed, 84 skipped, 1 xfailed (review 2's baseline was 2315 passed, 84 skipped, 1 xfailed -- exactly +5, matching the 5 new tests added; no regressions, no test deleted besides the redundant line in G8).

## Not done / deviations

- Nothing from the brief's finding list was skipped. The one deliberate deviation from the review's literal suggested implementation is in G3: instead of merely excluding hidden from the deleted set inside the fits_here loop (which, on inspection, is a no-op since hidden ids are never members of fits_here), I changed _staged_kind_ranks to explicitly add hidden delete-targets back into the retained-id set ((set(fits_here) - deleted) | (deleted & hidden)). This is the actual fix needed to make the bug reproducible/fixable; the literal suggestion as worded would not have changed behavior. Verified with a dedicated before/after test.
- _build_refit_round's docstring is 3 lines, not strictly <= 2, because trimming further would drop either the correction formula or the fact that it persists/clamps across rounds -- both are load-bearing for a reader modifying the accumulation logic, not review-bookkeeping prose. Everything else requested was trimmed to <=2 lines.
