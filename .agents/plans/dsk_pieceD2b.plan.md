# d4b piece D2b — Design B revision: measure from the SAVED deck, not the live script

Worktree: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen` @ `f4e5759`
Supersedes the "live MEASURE is the authority" half of `.agents/plans/dsk_pieceD.plan.md` (Design B). Everything else in Design B — measure-then-refit, `_build_refit_round` arithmetic, `build_refit_script`, `_MAX_REFITS = 2`, shrink fallback — is kept unchanged.

## 1. Why the design changes

The live read is not stale-proof. Inside the writing AppleScript, `height of <text item>` is stale after `set width/position/size` even with the 2-consecutive-reads poll (`delay 0.2` × ≤5) and the end-of-slide re-read: three runs on 2026-09-13 read GW 13 = 219, GW 17 = 122 / 70, GW 28 = 246, while the SAVED deck holds 269, 186 / 189, 349. The stale values sit **below** the predicted rects, so:

- `OVERFLOW` never fires → `_run_refit_and_finalize` returns at its `if not eligible_keys: return` guard,
- the refit never runs, and the band breaches survive to `out_path` (GW 13 bottom 1080 > 1054; GW 17 boxes overlap).

The poll cannot fix this: two consecutive reads of the same stale value agree, and `MEASURE2` (a re-read at the end of the slide loop) reports the same stale number. The only read that has ever matched reality is the offline read of the saved package (`accept11p.py` → `offline_wall_payload`).

So: **pass 1 already saves and closes to `staging_path` before the refit loop starts.** Measure from that file.

## 2. Shape of the new loop

Unchanged: pass 1 writes → `save theDoc in staging_path` → `close`.

```
measured = offline measure of staging_path        # NEW authority
todo     = stacked boxes over budget / out of band
for round in 1..2:
    refits = _build_refit_round(...)              # unchanged arithmetic
    build_refit_script(reopen staging, rewrite, save, close)   # unchanged
    measured = offline measure of staging_path    # NEW: re-read the file, not stderr
    todo = still over budget
shrink fallback (unchanged) → one more script → offline re-measure
```

Two live osascript passes per round stay exactly as they are; only the source of `measured` changes. `retry_on_1712=False` stays on every pass ≥ 2.

## 3. Step 0 (gate, do this first — offline, no Keynote)

The whole design rests on the saved-file text `h` being Keynote's own stored frame, not an offline re-estimate. `offline_inspect._item_from_record` marks records whose geometry came from `geom_source in {"group-union", "autosize"}` into `payload["_offline"]["soft_geometry"]`. If the stacked verse boxes land there, the offline read is an estimate and is no better than the live one.

Probe (read-only, on the existing evidence deck; ~20 lines in the scratchpad, not the repo):

```python
p = offline_wall_payload(Path("~/Desktop/dsk-d4-work/out-r11p/Sermon_PK_DSK.key").expanduser())
print(p["_offline"]["soft_geometry"])        # expect: no text entries on ord 2/3/6
print([(i["kindIndex"], i["y"], i["h"]) for i in p["slides"][1]["items"] if i["kind"]=="text"])
```

Expected: GW 13 (ord 2) text `h ≈ 269`, GW 17 (ord 3) `≈ 186` and `≈ 189`, GW 28 (ord 6) `≈ 349` — i.e. the numbers `accept11p.py` already reports — and **none** of those items listed in `soft_geometry`.

If a stacked text item **is** flagged soft, stop and re-plan: the fallback is the shrink-only path plus a hard offline band assertion before publish (§9, open question A).

## 4. Step 1 — new library function in `offline_inspect.py`

Name: **`offline_text_rects(key_path, *, deck=None)`** (module `src/obed_edom/offline_inspect.py`, placed next to `offline_wall_payload`).

```python
def offline_text_rects(key_path, *, deck=None) -> tuple[
    dict[int, dict[tuple[str, int], tuple[float, float, float, float]]],   # {ordinal: {(kind, kindIndex): (x, y, w, h)}}
    set[tuple[int, str, int]],                                            # soft: {(ordinal, kind, kindIndex)}
]:
```

Implementation is ~25 lines and reuses the existing path exactly as `accept11p.py` does — one `offline_wall_payload(key_path, deck=deck)` call, then bucket `slide["number"] → {(item["kind"], item["kindIndex"]): (x, y, w, h)}` for `kind in {"text", "shape"}` (the badge is a shape/short text and is re-stacked too), and lift `_offline["soft_geometry"]` into the second return value. It raises `ImportError` without the `iwa` extra, like the rest of the module.

Rationale for putting it here and not in `dsk_assemble`: `offline_inspect` already owns the IWA→JXA-shape translation and the guard sidecar; `dsk_assemble` already imports offline readers for `_restore_stroke` / `_verify_builds` / `verify_staged_layouts_alpha_safe`, so this is the same seam.

Tests (`tests/test_offline_inspect.py`, or `tests/test_dsk_assemble.py` if the former does not exist — check; use the existing fixture deck under `tests/fixtures`):
- `test_offline_text_rects_buckets_by_ordinal_and_kind_index`
- `test_offline_text_rects_reports_soft_geometry_items`

Diff: ~30 lines src, ~35 lines tests.

## 5. Step 2 — the adapter in `dsk_assemble.py`

New private helper, placed just above `_run_refit_and_finalize`:

```python
def _offline_measure(
    staging_path: Path, plan: AssemblyPlan, hidden: Mapping[int, frozenset[ItemId]],
    warnings: list[str],
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], tuple[float, float]]]:
    """{(source slide number, 'text:<srcIdx>'): measured h} plus {key: (y, bottom)} read
    from the SAVED staging deck."""
```

Mapping, which is the only real subtlety:

- **ordinal → source number**: `plan.ordinal_to_number` (already populated; `payload["slides"][i]["number"] == i + 1 == ordinal`).
- **staged kindIndex → source kindIndex**: `_staged_kind_ranks(number, plan, hidden=hidden.get(number, frozenset()))["text"][staged_idx]` — the list is the sorted source indices in staged order, so indexing it inverts `_staged_id_for`. Guard the index (`if staged_idx >= len(ranks)`, skip and append a warning) so an unexpected insert cannot raise.
- **split slides**: skipped entirely — `_eligible_refit_items` already returns `frozenset()` for `slide_no in plan.splits`, so the `text:<idx>:<ordinal>` key form never reaches the refit loop. Do not attempt the split key form here; leave a comment saying so.
- Heights come back whole-point rounded (`_round_pt`), which is ±0.5pt against a +2.0pt tolerance — harmless. Note it in the docstring.
- If `offline_text_rects` flags any measured stacked item soft, append a warning `slide N: text i offline geometry is soft ({reason}), refit measurement not vouched` and drop that key from `measured` (it then reads as "measure missing this round", the branch `_build_refit_round` already handles).

Test: `test_offline_measure_maps_staged_index_back_to_source_index` (fake `offline_text_rects` via monkeypatch; plan with a delete below the stack, mirroring the existing `test_refit_script_addresses_staged_index_after_a_delete_below_the_stack`).

Diff: ~45 lines src, ~40 lines tests.

## 6. Step 3 — thread it into `_run_refit_and_finalize`

Signature change: keep `measured` (callers still pass the live dict, now diagnostics-only) but add nothing else — `staging_path`, `plan`, `hidden`, `warnings` are all already parameters.

Edits, in order:

1. **Trigger.** Replace the `eligible_keys` derivation from `overflows` with the plan itself:
   ```python
   eligible_keys = {
       (n, f"text:{iid[1]}")
       for n in plan.ordinals
       for iid in _eligible_refit_items(plan, n)
   }
   ```
   This is the load-bearing fix: the loop must no longer depend on a live `OVERFLOW` line that provably never fires. Every stacked box on a kept, non-split slide is now checked.
2. **First measurement.** Immediately before the round loop: `measured, bands = _offline_measure(staging_path, plan, hidden, warnings)` — overwriting (not merging with) the live dict.
3. **Per-round re-measure.** Inside the loop, replace
   ```python
   for key in todo: measured.pop(key, None)
   measured.update(_parse_measure_lines(proc.stderr or ""))
   ```
   with `measured, bands = _offline_measure(staging_path, plan, hidden, warnings)`. Keep `proc` (still needed for the return code via `batch.run`).
4. **Shrink fallback.** Same substitution after its `batch.run`, before the final `_refit_still_over_budget`.
5. **Band check.** Extend `_refit_still_over_budget` with an optional `bands` argument: a key is also over budget when `y < band.top - 1.0` or `y + h > band.bottom + 1.0` for that slide's `plan.stack_bands.get(slide_no, band)`. This catches a box that fits its own rect but was placed out of the band (the GW 13 bottom-1080 case) and makes the loop's stop condition identical to the acceptance criterion in §8.
6. **Overflow reporting.** After the loop, rebuild `overflows[:]` from the final offline `measured` for `eligible_keys` still in `todo`, instead of filtering the live list. The existing stale-warning prune (`stale_prefixes`) stays.

Tests (in `tests/test_dsk_assemble.py`, extending the existing Design-B block at line ~1576; `_make_seq_live_batch` stays, the fakes move from stderr to the reader):
- `test_refit_loop_triggers_without_any_live_overflow_line` — pass-1 stderr contains **no** `OVERFLOW`, the faked offline reader returns 269.0 for a 220.0 rect; assert a refit script runs (`len(calls) == 2`).
- `test_refit_loop_converges_in_two_rounds_from_offline_reads` — rewrite of the existing converge test with a faked `offline_text_rects` sequence.
- `test_refit_loop_refuses_when_still_overflowing_offline` — rewrite of the refusal test; `len(calls) == 1 + dsa._MAX_REFITS`.
- `test_refit_loop_shrinks_from_offline_reads` — rewrite of the shrink test; `len(calls) == 1 + _MAX_REFITS + 1`.
- `test_refit_loop_treats_band_breach_as_over_budget` — measured `h` fits the rect but the offline `y + h` is 1080 > 1054; assert a refit round runs.
- `test_offline_measure_soft_geometry_item_warns_and_skips`.

Fake shape for all of these: `monkeypatch.setattr(dsa, "offline_text_rects", _seq_reader([...]))`, a tiny sequence closure alongside `_make_seq_live_batch`. `dsk_assemble` must therefore import the name into its own module namespace (`from obed_edom.offline_inspect import offline_text_rects`) so monkeypatching `dsa.offline_text_rects` works — match how `deck_builds` / `copy_keynote` are already patched in `_patch_common_with_batch`.

Diff: ~50 lines src, ~120 lines tests.

## 7. Step 4 — what happens to `_text_measure_lines` / `MEASURE2`

**Decision: delete `_second_measure_lines` and the `MEASURE2` branch; keep `_text_measure_lines` as a one-shot diagnostic with the poll removed.**

- `MEASURE2` existed solely to prove the first `MEASURE` had settled. The live fact settles that question the other way — both reads report the same stale value — so it costs script size and an extra AppleScript round-trip per stacked box and can never tell us anything again. Delete `_second_measure_lines`, its call site in `_slide_lines` (~line 1418), the `elif key == "MEASURE2"` branch in `assemble_dsk_deck` (~line 2792), and `test_...measure2...` if one exists.
- `_text_measure_lines`: keep the `log ... MEASURE ...` and the `OVERFLOW` line as **evidence only** — they are how a run's `run.err` shows the live/offline divergence, which is the entire finding here — but **delete the 5-iteration poll** (`_MEASURE_POLL_DELAY`, `_MEASURE_MAX_POLLS`, the `repeat`/`prevH` block), which buys nothing and costs up to 1s per stacked box. Replace with a single `set curH to (height of <addr>)`.
- Keep `_parse_measure_lines`; feed its result into a `live_measured` dict and, after the first offline measure, `log()` one line per box where `abs(live - offline) > 2.0`. Cheap, and it keeps the regression visible if a future Keynote makes the live read truthful.
- `overflows` in `AssembleResult` now carries offline numbers; the `warnings` text `slide N: text text:i overflow, height H` from the live pass stays but is pruned by the existing `stale_prefixes` logic once the box resolves.

Tests: `test_assembly_script_emits_no_measure2_lines`; adjust `test_refit_script_reopens_and_saves` (still asserts `'MEASURE" & tab & "text:0"' in script`, still passes) and `test_assemble_parses_measure_lines` (unchanged, now diagnostics).

Diff: ~-45 lines src, ~15 lines tests.

## 8. Offline acceptance rows (GW 13 / 17 / 28)

These are the rows the acceptance script must print PASS for, read from the **saved output** via `offline_wall_payload` (`ORD = {5:1, 13:2, 17:3, 21:4, 24:5, 28:6, 32:7, 33:8, 48:9}`; band `y_min = 704.0`, `bottom = 1054.0`, tol 1.0):

| # | Check | Expected |
|---|---|---|
| 1 | GW 13 (ord 2): every stacked text rect `y >= 704` | `y >= 704.0` for each (was `y+h = 1080`) |
| 2 | GW 13 (ord 2): every stacked text rect `y + h <= 1054` | bottom `<= 1054.0` — the breach that must close |
| 3 | GW 13 (ord 2): verse box `x ≈ 43`, `w ≈ 1849` | unchanged from `accept11p.py` |
| 4 | GW 17 (ord 3): exactly two long text boxes | `2` |
| 5 | GW 17 (ord 3): the two long boxes do not overlap | `rects_overlap(a, b) is False` (was overlapping) |
| 6 | GW 17 (ord 3): both long boxes `y >= 704` and bottom `<= 1054` | both in band |
| 7 | GW 17 (ord 3): badge (short text) bottom `<= min(long y) + 1` | badge above the stack |
| 8 | GW 17 (ord 3): stack gap `min(long y) - badge bottom ≈ _TEXT_STACK_GAP` | ±0.5 |
| 9 | GW 28 (ord 6): every stacked text rect `y >= 704`, bottom `<= 1054` | in band (offline `h ≈ 349` vs live-read 246) |
| 10 | GW 28 (ord 6): stacked rects pairwise non-overlapping | no overlap |
| 11 | all three: none of the stacked items appear in `payload["_offline"]["soft_geometry"]` | empty — the read is vouched |
| 12 | all three: `run.out` reports zero unresolved overflows after the refit | `result.overflows == ()` |

Rows 1/2/5/6/9 are the ones that FAIL on `out-r11p` today; rows 3/4/7 already pass and are regression guards. Add rows 1, 2, 9, 10, 11 to `accept11p.py`'s successor (that script lives outside the repo under `~/Desktop/dsk-d4-work/` — not a repo edit).

## 9. Ruling in/out the two "make the live read truthful" shortcuts

Both are cheaper than a reopen **if** they work, so they are worth one probe each before shipping — but neither blocks this plan; the reopen path is what Design B already builds and it is proven by `keynote.py:527` `_build_superscript_fix_script`.

**(a) Does `height of` become truthful after `save theDoc` inside the same script?**
Probe: in the pass-1 script, after the slide loop and after `save theDoc in <staging>` but **before** `close`, emit one extra read per stacked box on GW 13/17/28 as `OBED\t<n>\tMEASURE_AFTERSAVE\t<key>\t<h>`. ~8 lines of AppleScript, zero extra osascript invocations, no risk. PASS = the three slides read 269 / 186+189 / 349. Prior: low. Keynote's layout engine is lazy and the save serializes the *model*; there is no reason the accessor's cache invalidates. If it PASSes, a follow-up piece can collapse a round-trip — do not design for it now.

**(b) After `close` + `open`?**
Probe: a standalone throwaway script that opens `out-r11p/Sermon_PK_DSK.key`, reads `height of text 1 of slide 2/3/6`, logs them, closes saving no. ~15 lines, read-only against an existing deck. PASS = the same 269 / 186+189 / 349. Prior: high — this is the same state `build_refit_script`'s reopen already produces. **But it changes nothing:** the reopen is exactly what we are doing anyway, and a reopened live read costs an osascript round trip where the offline read costs an IWA decode we already perform for `_restore_stroke` / `_verify_builds`. **Ruled out as an alternative** to the offline read regardless of the probe result; keep the offline read as the authority.

Neither probe may be run by a plan agent, and neither touches Keynote in this session — hand them to the implementer or to whoever owns the live runs.

## 10. Step sequence and sizing (one Sonnet implementer)

| Step | Work | Diff |
|---|---|---|
| 0 | Offline gate probe (§3), scratchpad only | 0 |
| 1 | `offline_text_rects` in `offline_inspect.py` + 2 tests | ~65 |
| 2 | `_offline_measure` adapter + index-inversion test | ~85 |
| 3 | Thread into `_run_refit_and_finalize`; plan-derived `eligible_keys`; band check in `_refit_still_over_budget`; rebuild `overflows` + 6 tests | ~170 |
| 4 | Delete `MEASURE2`, de-poll `_text_measure_lines`, divergence log line + 1 test | ~-30 net |
| | **Total** | **~290 lines** |

Steps 1→2→3 are strictly sequential; step 4 is independent and can land first or last. Run `pytest tests/test_dsk_assemble.py tests/test_dsk_plan.py tests/test_offline_inspect.py` after each step; the acceptance rows in §8 are verified by a live run outside the repo, not by pytest.

## 11. Open questions that would change the design

- **A. Soft geometry on stacked text (gate §3).** If the saved-deck text `h` for a stacked box comes from the offline autosize estimator rather than a stored frame, the offline read has the same authority problem as the live one, and this design collapses to "shrink always, assert the band before publish". Resolve before step 1.
- **B. Whole-point rounding.** `_item_from_record` rounds to whole points. Against the +2.0pt tolerance this is fine, but if a future round tightens the tolerance below 1pt, `offline_text_rects` must read `rec["h"]` pre-rounding (it can — `compose_geometry` returns floats; only `_item_from_record` rounds). Noted, not acted on.
- **C. Split slides.** `_eligible_refit_items` excludes them, so a split slide that breaches the band is still silently published. Out of scope here; if the GW 17 two-box case is implemented as a split rather than a stack, this plan does not cover it — confirm GW 17 is `plan.stacked_ids`, not `plan.splits`, before step 3.
- **D. Badge/shape kinds.** `_offline_measure` maps `("text", idx)` only. If a badge is a `shape` in the source payload, its offline rect is read but never checked (it is positioned, not fitted) — correct today, but the band assertion in §8 row 7/8 is acceptance-script-side, not in-loop.
- **E. Hidden placeholders.** The staged index inversion depends on `hidden_ids` from pass-1 stderr being complete. A placeholder Keynote refuses to delete *and* does not log shifts every later index by one and silently mismeasures. Mitigation available if it bites: cross-check `len(ranks["text"])` against the offline text count per ordinal and refuse on mismatch (~6 lines; add in step 2 if cheap).


## Gate outcome (2026-09-13 13:55, measured on out-r11p)

- Step 0 probe: all stacked verse boxes ARE listed in `soft_geometry` (source `autosize`), i.e. their offline rect comes from
  `iwa_geometry._autosize_rect` = the archive's stored **naturalSize** (Keynote's own laid-out text size, written at save) with the
  y-anchor inferred from vertical alignment. Offline h: GW 13 269, GW 17 186/189, GW 28 349.
- Probe (b) — live `height of` on the freshly REOPENED saved deck: 219 / 122 / 70 / 246, identical to the in-script reads. The live
  `height` is therefore the FRAME height pass 1 wrote (`set height` on a non-autosize box, i.e. the predicted rect), not the text's
  laid-out height; the text simply overflows the frame. The r9b PNG (last line clipped at the canvas bottom) agrees with 269, not 219.
- Conclusion: the saved archive's naturalSize is the truthful authority; `soft_geometry` membership is expected and must NOT gate the
  read (drop §3's "stop and re-plan" branch; drop §9(a) — moot). The band check in §6.5 uses the offline y (stored top for
  top-aligned boxes) — keep. Open question A is resolved; E stands.

## Piece record (round 2, post Opus review 2)

- `_wrap_lines` (`dsk_plan.py`) now tokenizes consecutive-separator runs and joins with the *actual* break char instead of
  collapsing every run to a single space. This is a deliberate, plan-wide behaviour change: `wrapped_height` is the estimator the
  *planner* uses for every deck, not only ones exercising the D2b refit loop, so any source text containing thin spaces (U+2009)
  or runs of spaces now gets a taller (correct) prediction on ordinary planning runs, not just refits. The old code under-charged
  U+2009 by ~2.7x; the new prediction is the direction that prevents an overflow, not causes one. No existing test's numbers moved.
- C5 (re-running split after a refit) remains deferred: a still-overflowing split slide is left to the `text_fit` fallback, same
  as any other unresolved box; `_run_refit_and_finalize`'s docstring documents this.

## Piece record (round 3, post Opus refit-log review 1)

### A. Horizontal wrap margin

Opus review finding 1: `wrapped_height`/`wrapped_height_runs` charge the wrap width with no horizontal safety margin, so a box at
97-100% fill packs onto one line the live Keynote wrap flips to two. Added `_WRAP_MARGIN` (`dsk_plan.py`), a named constant both
functions wrap at `width * (1 - _WRAP_MARGIN)`.

Deck-wide validation against the four r11-measured GW boxes (pass-1 `t`, `plan.stack_bands[n].width`, real item `runs`, no
`height_correction`):

| slide | box | t | measured | m=0.00 | m=0.02 | m=0.03 | m=0.05 |
|---|---|---|---|---|---|---|---|
| 13 | text:1 | 0.80 | 269.0 | 243.1 (0.40 under) | 243.1 (0.40 under) | 243.1 (0.40 under) | 243.1 (0.40 under) |
| 17 | text:1 | 0.64 | 186.0 | 135.8 (0.97 under) | 135.8 (0.97 under) | 135.8 (0.97 under) | 135.8 (0.97 under) |
| 17 | text:2 | 0.64 | 189.0 | 83.9 (**2.03 under**) | 146.9 (0.81 under) | 146.9 (0.81 under) | 146.9 (0.81 under) |
| 28 | text:1 | 0.91 | 349.0 | 273.7 (**1.02 under**) | 363.2 (over-predicts) | 363.2 (over-predicts) | 363.2 (over-predicts) |

"under" is under-prediction in whole lines (`(measured - predicted) / (1.157 * size * t)`); bold = under by a whole line or more.
Margin 0.00 under-predicts GW 17 text:2 and GW 28 text:1 by a full line each (the r11 failure mode); margin 0.02 already clears
both and is stable through 0.05 (the wrap boundary these two boxes sit on doesn't move again in that range). GW 13 text:1 and
GW 17 text:1 stay under by <1 line at every margin tested — expected, since under-prediction below a whole line is not necessarily
estimator error (the live height includes Keynote's own line-height/padding slop the estimator doesn't model exactly).

Chosen: **`_WRAP_MARGIN = 0.02`** — the smallest of the tested set clearing every measured box.

Cross-check against `test_wrapped_height_matches_golden_boxes` (DSK deck, all long-text boxes, over-prediction bound
`predicted_lines - observed_lines <= 1.0 line`): margins 0.00/0.02/0.03 produce identical worst-case over-prediction (golden
slide 14 text:2 at 1.0012 lines, already at the bound pre-margin); margin 0.05 adds one more box at the bound (golden slide 30
text:0, 1.0025 lines) but still inside it. No golden-box number moved past the bound at 0.02, so the golden-box test's pinned
expectations are unchanged. Two other pinned real-deck values did move and were re-blessed: `test_gw13_gw17_stack_budget_and_fit_t_under_default_band`'s
GW 17 `t` (0.64 -> 0.63) and `test_unresolved_gap_below_t1_flattens_lead_size_under_shrink_text_fit`'s GW-49-shaped shrink size
(124.5pt -> 123.0pt) — both are the estimator now correctly predicting a taller wrap for the same source text, shrinking further
to fit.

### B. Nits (opus-refit-log-review1)

- `copy_keynote` of the refused-deck copy is now wrapped in `try/except Exception`, logging `could not keep the staged deck: …`
  and letting the original `AssemblyRefusal` propagate either way (never replaced by a `ditto` failure).
- The pass-1 AppleScript-refusal raises now sit inside the same `try` as the refit/verify steps, so a post-save pass-1 script
  failure also keeps the staged deck at `*.refused.key`, not just a refusal from `_run_refit_and_finalize` onward.
- `_build_refit_round` logs one line when the `[1.0, 3.0]` correction clamp bites: `slide N: text K correction clipped U -> C`.
- The continue-path per-round log (other slides still refitting) now reads `no refit written in round N: slide X: …`; only the
  `break` path (the loop actually stopping) still says `refit stopped after round N: …`.
- The `fit_text_stack found no t >= floor` stop reason rounds every correction float to 2dp before formatting.
- `_log_offline_measures` now prints a box only when it is over budget or its measure changed by more than 0.5pt since the
  previous measure (an optional `previous` mapping, threaded through all three call sites), plus one `N box(es) within budget and
  unchanged, not shown` line; a box missing its rect or measure now logs `offline measure missing a rect or height` instead of
  disappearing silently.
- `test_gw53_badge_x_clamped_to_band_right_edge` now also asserts the badge-clamp warning text is in `plan.warnings`.
- `test_refit_stopped_logs_reason_and_per_box_offline_measures` now scales its two offline measures to the real r11 corrections
  (1.37/2.25, derived from the fixture's own predicted rects) instead of driving both to the 3.0 cap; comment corrected to say
  GW 17 never hit the cap and the `--min-text-pt 66` floor is what refused it.

### Operator-visible artifacts and log lines (undocumented until now)

- `*.refused.key`, saved next to `out_path` (`{out_path.stem}.refused.key`), is the staged deck kept whenever assembly raises
  `AssemblyRefusal` after pass 1 has already saved — inspect it to see the state Keynote was in when the refusal fired.
- `slide N: text K offline=H rect=R over=+D` — one line per over-budget or newly-changed box after every offline measure round.
- `N box(es) within budget and unchanged, not shown` — the quiet-box count for the same round.
- `refit round N: slides [...]` — a round's live refit write went out.
- `no refit written in round N: slide X: <reason>` — a slide in this round produced no write (other slides may still be
  refitting).
- `refit stopped after round N: slide X: <reason>` — the refit loop has stopped entirely; slide X is one of the slides left over.
- `slide N: text K correction clipped U -> C` — the `[1.0, 3.0]` height-correction clamp bit for that box.
