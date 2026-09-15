# Review 2 — d4b piece D2 (run-aware estimator + live measure-then-refit), fix round 2

Scope: `git diff 9b486a8 -- src tests` on `feat/dsk-gen` (278d555) plus the uncommitted tree.
Suite re-run from the worktree: **2315 passed, 84 skipped, 1 xfailed** (81s) — matches the report.

Verdict: **REVISE** — one must-fix (G1: under `--text-fit shrink` the fallback can write text *larger*
than pass 1 wrote, on a box it knows overflows, and label it "shrunk"), plus two should-fixes. The three
load-bearing round-1 findings (F1 correction arithmetic, F2 badge re-stack, F3 run-aware pass 1) are
genuinely fixed — I reproduced both against the real GW deck, not by reading.

## Verification of round-1 findings

Probes are in the scratchpad: `probe_rounds.py` (real `Sermon_PK (GW).key`, slides 13/17/28, live
heights modelled as `k × wrapped_height_runs(t)` with the brief's measured `k`: 0.983 / 1.21 / 1.134 /
0.914), `probe_shrink.py`, `probe_shrink2.py`.

- **F1 (correction arithmetic) — FIXED, verified over two rounds.** `dsk_assemble.py:2531-2534`. The
  ratio denominator `plan.fits[...].h` is the *corrected* estimate from the previous round (because
  `fit_text_stack` multiplies `height_correction` into `heights`, `dsk_plan.py:1032`, and
  `_stacked_text_rects` copies those heights into the rects), so the running product
  `correction *= measured/rect.h` telescopes to `measured / raw_estimate(t_last)` — exactly the form
  the review asked for. Probe, one-round case: pass-1 `t` 0.80/0.64/0.90, GW 17 lands at `t=0.58`
  (not the old collapse to 0.35) and `todo` empties after round 1. Probe, forced two-round case (live
  ratio worsens 10% below `t=0.62`): round 1 `corr=1.21`, round 2 `corr=1.331 = 1.21 × 1.10` — it
  accumulates, sizes are monotonically non-increasing, and round 2 converges. No revert.
- **F2 (badge re-stack) — FIXED.** `dsk_assemble.py:2517-2524`, emitted as `TextRefit(rect, None)`.
  Probe: after the refit, the short row's bottom sits exactly `_TEXT_STACK_GAP` (10.0pt) above the new
  stack top on all three of GW 13/17/28 — the measured 8.2 / 11.7pt overlaps are gone.
- **F3 — FIXED.** `_text_boxes:250` now attaches runs, so pass 1 and the refit share one estimator.
- **F4 — FIXED** (`build_refit_script:1643` routes through `_staged_id_for`; the MEASURE key correctly
  keeps the *source* `kind_index`). **F5, F6, F8, F9, F11, F12 — FIXED** and, except F5/F8, tested.
  `HIDDEN` reaches both `warnings` and `AssembleResult.hidden` (2736-2741, 2804).
- **F7 — mostly fixed** (measured-fit size, runs preserved via `_run_size_ranges`, floor only when
  clamped, final re-MEASURE, `overflows` filtered by `todo` only) **but see G1.**
- **F13 — partially deferred**, F10 fixed, **F14 — half-wired, see G2**, F15 — see G4.

## Findings

**G1 (must-fix, correctness). The shrink fallback's `t_prev` defaults to 1.0, so it can write the box
*bigger* than pass 1 did — on a box it has just declared still overflowing.**
`dsk_assemble.py:2603-2609`. `last_t` is only ever populated by `_build_refit_round` (2493-2494), and
that function returns `{}` — `break`ing the loop before any `last_t` entry exists — whenever
`measured.get(key)` is missing (`any_new` stays False, 2519-2527), `len(boxes) != len(stacked)` (2513),
or `fit_text_stack` returns `None` (2537). All three land in the shrink branch with `t_prev = 1.0`,
i.e. the *source* size, not the size pass 1 actually wrote.
Reproduced (`probe_shrink2.py::test_enlarge`, 120-word single-font box, pass 1 fits at `t=0.96`): pass 1
emits `set size of object text of theObj to 38.4`; the shrink pass emits **`… to 40`** — a 4% *increase* —
with the warning `slide 13: text text:0 shrunk to 40.0pt after refit`. The missing-`MEASURE` trigger is
precisely the dropped/truncated-stderr case round 1's F8 called out; the `fit is None` trigger is the
single most likely route into shrink mode at all. (In the `fit is None` route the floor usually rescues
it — `probe_shrink2.py::test_fit_none_route` clamps to 24pt — but the missing-MEASURE and
`len(boxes)` routes do not.)
Fix: seed `last_t` with pass 1's fitted `t` before the loop. It is not on the plan today; the cheapest
honest source is to persist it alongside `stack_bands` (a `stack_t: dict[int, float]` set at
`dsk_assemble.py:573`), then `last_t = dict(plan.stack_t)` at 2563. Deriving it from
`plan.run_sizes`/`plan.text_sizes` divided by the source size also works but re-derives what pass 1 knew.
Whatever the source, also make `t` never exceed the previously written size: `t_prev` must be a real
upper bound, since the whole branch exists because the box overflows.

**G2 (should-fix). MEASURE2 is emitted, then thrown away — and its parser is dead code.**
`_second_measure_lines` (1291) is emitted per stacked box (1417) and `_parse_measure2_lines` (1308) is
defined, but `grep -rn "MEASURE2\|_parse_measure2_lines" src tests` finds exactly one consumer:
`elif key == "MEASURE2": continue` (2753). The height reaches no log line, no warning, no
`AssembleResult` field, and no test. So the probe F14 asked for — "prove the first MEASURE had settled
rather than agreeing twice on a stale value" — cannot answer that question on r10 after all, while the
deck pays the extra AppleScript reads. Either wire it up (`measure2[(slide, key)] = float(...)`, then
one `log(...)` or a warning per box where `abs(measure2 - measured) > 2.0`, which is the single line
that would actually falsify the design) or delete `_second_measure_lines`, `_parse_measure2_lines`,
`_MEASURE2_RE` and the emission. Half of it is worse than either.
Note the report claims F14 was "present … not touched, out of scope" — it is in fact new in this diff
(1291-1317, 1417), so the out-of-scope framing does not hold.

**G3 (should-fix, latent mis-write). `_staged_id_for` assumes every delete target was deleted; the hide
branch means some were not.** `build_refit_script:1643` + `_staged_kind_ranks:2205-2209` drop every id
in `plan.deletes` when computing staged ranks. But `_delete_or_hide_placeholder_lines`
(`remap_keynote.py:67`) is applied to *every* delete target regardless of kind (`dsk_assemble.py:1420-1431`),
and a hidden default title/body item **retains collection membership** — round 1's own F4 note says so.
So if a slide's delete list contains a `text` item that turns out to be the default body item, the
staged text indices computed here are one too low for every text item after it, and the refit — a
geometry *write* — lands on the wrong box. Not live on the r10 set (GW 17's text deletes are shapes/above
the stack), and pass 1 is unaffected because it addresses source indices and deletes last
(`_slide_lines`, deletes emitted after the geometry/measure blocks). The information needed is already in
hand: `assemble_dsk_deck` collects `hidden` (2735-2741) with the object's address before
`_run_refit_and_finalize` runs (2771). Fix: pass the hidden ids down and treat them as *not* deleted in
`_staged_kind_ranks`, or skip the refit for any slide that reported a `HIDDEN` on a `text` item.

**G4 (nit, house style). One review back-reference and two over-long docstrings survive F15.**
`dsk_assemble.py:1264` still reads "…on the first read, F3)" — a pointer into a review that is not in
the repo. The report's F15 grep used an unescaped `|` in a BRE, so it matched nothing and the check was
vacuous; `grep -rnE "\bF[0-9]\b|D2 step"` over the four files finds it (everything else it returns is
pre-existing, from D1/D4). Also still unfixed from F15: `_text_measure_lines`'s docstring is 7 lines
(1262-1268) and `_delete_or_hide_placeholder_lines`'s is 11 (`remap_keynote.py:70-79`), both carrying
history prose ("the branch fell through to a plain delete", "as before"). `_build_refit_round`'s new
docstring (2456-2460) adds its own: "a fresh, unaccumulated ratio would discard an earlier round's fix"
documents a bug that no longer exists. Trim to what the next reader needs.

**G5 (nit). `build_refit_script`'s `finalize` is dead in exactly the way F13 flagged.**
`dsk_assemble.py:1616`; both call sites (2578, 2620) pass `finalize=True` explicitly, the default is
`True`, and no test passes `False` (`grep -rn "finalize=False" tests` → nothing). The report's defence
("genuinely used … removing it would require restructuring a load-bearing path") does not survive that
grep — removing the parameter and always emitting `save`/`close` is the same three-line change that was
just made to `build_assembly_script`. Either remove it or accept the inconsistency knowingly.

**G6 (nit). The shrink warning names only the smallest run.** `2611-2616`: `written_size` is
`t * min_source_size`, so a mixed-run box reports "shrunk to 24.0pt" while its ArgentCF-Bold run is
written at ~31pt. Report the range (or the lead size) when `ranges` is a tuple. Related: when
`_run_size_ranges` returns `None` with `unresolved`, the shrink path flattens every run to
`t * min_source_size` (2611) without the "preserving source sizing"/"flattening" warning pass 1 emits at
585-599 — a silent loss of the emphasis ratio. It also re-passes `warnings=warnings` at 2608, so a gap
warning already emitted by a refit round can duplicate here.

**G7 (nit, carried over from F8's "Related"). `measured` is `update`d, never reset per round** (2581).
A round whose write block errors leaves the previous round's height in place; with the new accumulating
correction that no longer no-ops, it multiplies the same ratio in a second time (bounded only by the 3.0
clamp) — conservative rather than wrong, but silent. Clearing the round's keys before `update` would
make a dropped MEASURE visible instead.

**G8 (nit, tests).** Three small things:
- `test_refit_second_round_accumulates_correction` (tests/test_dsk_assemble.py:1302) re-does
  `plan.fits[13].update(...)` by hand, which `_build_refit_round` already did at 2528 — harmless, but it
  reads as if the production code did not persist the rects. Drop the line. The test does discriminate
  (it fails against a non-accumulating `correction`), but it only pins the *sign* of the change; a
  round-2 case where `measured2 == rect_h` should leave `corr` unchanged would pin the magnitude, which
  is the half of F1 that actually over-shrank GW 17.
- No test covers G1, and none covers MEASURE2 (G2) — `grep -rn MEASURE2 tests` is empty.
- tests/test_dsk_assemble.py:325-328 — four consecutive blank lines left by the removed
  `test_assembly_script_finalize_false_has_no_save`.

## What is right

- The correction/re-stack pair now behaves on the real deck: one round for the live `k` values, two
  rounds under a deliberately non-linear estimator error, badge gap exactly 10pt on 13/17/28.
- The shrink path's other three properties all hold as specified: measured-fit size, per-run ranges
  preserved, floor note only when `t_floor` actually clamped, final re-MEASURE parsed and
  `overflows[:]`/stale-warning filtering keyed on the post-shrink `todo` (2624-2631) rather than cleared
  unconditionally.
- `_staged_id_for` in `build_refit_script` (modulo G3), the `plan.autosize` guard, the `Iterable` import,
  the refusal parity with pass 1, and the `HIDDEN` end-to-end path are all done properly and tested.
- Suite is green and the two new end-to-end shrink tests drive the real `assemble_dsk_deck` path rather
  than asserting on a string.
