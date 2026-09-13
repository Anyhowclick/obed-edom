# Opus review 1 — piece D2b (offline measurement authority) + Codex D2 review 1 fixes

Target: `8487145` (`git diff 8487145~1 -- src tests`), worktree `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen`.
Read-only; probes in the scratchpad only; no repo edits, no Keynote, no commits; no Agent tool used.

**Verdict: REVISE** — one correctness regression introduced by the C3 fix (finding 1), plus two
behaviour gaps in the new refusal/recheck wiring (findings 2 and 3). The core of D2b — plan-derived
trigger, offline naturalSize as the authority, band check, MEASURE2/poll removal — is correct, and
the C2 wrap fix is right (I verified it independently, see finding 5 preamble).

Verification I ran myself:
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_dsk_assemble.py tests/test_dsk_plan.py tests/test_offline_inspect.py -q` → **385 passed, 13 skipped, 1 xfailed** (matches the report). Note: the venv's editable install resolves `obed_edom` to the *main* checkout; without `PYTHONPATH=src` collection fails on an import error, so any run that did not set it was not testing this worktree.
- C2 equivalence probe (scratchpad `probe_c2.py` / `probe_c2b.py`): the three cases Codex named (equal-font split before punctuation, split with no whitespace at the boundary, split across one trailing space) **all match `wrapped_height` to the point**, as does a fuzz of 400 texts × every split position, and a narrow-width fuzz of **63 966 (text, width, split) combinations at widths 60–300 → 0 mismatches**. The C2 fix is genuinely correct.
- `_offline_measure` index-inversion probe (`probe_hidden.py`): delete-below-the-stack and hidden-placeholder cases both invert correctly; the open-question-E cross-check fires when a hide is unlogged.
- `_box_min_t` probe (`probe_minT.py`): see finding 1.

---

## Findings

### 1. `_box_min_t` loses the "floored at source" guarantee for a box whose runs are all below the floor — **high**

`src/obed_edom/dsk_plan.py:1024-1030`
```python
candidates = [min_text_pt / s for s in run_sizes if s >= min_text_pt > 0]
return max(candidates) if candidates else 0.0
```
When **every** run is already below `min_text_pt`, `candidates` is empty and the floor becomes `0.0`
— unbounded shrink. The docstring claims such a run is "never enlarged, floored at source"; the code
implements only the first half.

Measured (`probe_minT.py`, `min_text_pt=24.0`):

| box | `_box_min_t` | old floor |
|---|---|---|
| runs 20pt/18pt | **0.0** | 1.0 |
| no runs, size 20pt | **0.0** | 1.0 |
| runs 40pt/30pt | 0.8 | 0.6 (too loose — this is the bug C3 fixed, correctly) |

The old code was `min(1.0, min_text_pt / lead_source_size)` in the shrink fallback
(`dsk_assemble.py`) and `sizes[box] < min(min_text_pt, box.size)` in `fit_text_stack` — both of which
floor a below-floor box **at its own source size** (`t >= 1.0`, i.e. no shrink). After this commit:

- `src/obed_edom/dsk_plan.py:1050-1053` (`fit_text_stack`) will happily walk `t` down to 0 for such a
  box instead of returning `None`;
- `src/obed_edom/dsk_assemble.py:2677-2678` gives `t_floor = min(1.0, 0.0) = 0.0`, so the shrink
  fallback writes an arbitrarily small size, and `at_floor = t_floor > t_prev` is never true, so the
  "already at the floor, left at Npt" warning is also lost.

Fix:
```python
candidates = [min_text_pt / s if s >= min_text_pt else 1.0 for s in run_sizes] if min_text_pt > 0 else []
return max(candidates) if candidates else 0.0
```
(a below-floor run contributes `1.0` = "do not shrink me further", which reproduces the old
per-box semantics run-by-run). Add a test for the all-runs-below-floor box in both consumers —
nothing in the suite covers it today.

### 2. An offline-read failure or an E-mismatch skip cascades into two wasted live passes and a misleading refusal — **medium**

`src/obed_edom/dsk_assemble.py:2565-2568` (the broad `except`), `:2572-2578` (the count-mismatch
`continue`), interacting with `:2450-2452` (`measured_h is None` ⇒ over budget) and `:2723-2727`
(the new C4 refusal).

`eligible_keys` is now plan-derived, so **every** stacked box must come back from the offline read.
If the read raises (e.g. no `iwa` extra → `ImportError`, corrupt staging package) or an ordinal is
skipped by the open-question-E cross-check, those keys are all "measure missing" ⇒ over budget ⇒ two
live refit rounds that change nothing ⇒ shrink pass ⇒
`AssemblyRefusal("slide N: text text:i still overflows after refit and shrink")`.

Probed: with the hide unlogged, `_offline_measure` returns `{}` plus
`"slide 13: staged text count 2 != offline text count 3 on ordinal 1, refit measurement skipped"` —
that warning is the real cause, but it never reaches the refusal message, and three osascript passes
are burned first.

Fix: track the measure-missing keys distinctly from the over-budget ones (e.g. have
`_offline_measure` return the set of ordinals it could not vouch, or have
`_refit_still_over_budget` report the reason), and refuse immediately with the real cause
—`"offline measure failed: …"` / `"… staged text count … != offline text count …"`— rather than
after the loop with the wrong one. At minimum, append the offline-measure warnings to the refusal
text.

### 3. The post-shrink recheck narrows to `todo`, so a sibling the shrink pass displaced is never re-checked — **medium**

`src/obed_edom/dsk_assemble.py:2721`
```python
todo = _refit_still_over_budget(plan, measured, todo, bands=bands)
```
Each refit round re-checks the full `eligible_keys` (`:2657`), but the final shrink check only
re-checks the keys that were already failing. Since the shrink pass rewrites the stack geometry, a
box that was in band before the shrink can be pushed out of it (the band check is exactly the
GW 13 `bottom 1080` failure mode this piece exists to catch) and will be published unchecked —
and `overflows[:]` at `:2733` then clears it unconditionally.

Fix: pass `eligible_keys` there too, same as the round loop.

### 4. Band-check guard is inconsistent with `_build_refit_round`'s default — **low**

`src/obed_edom/dsk_assemble.py:2456` uses `plan.stack_bands.get(slide_no)` and silently performs
**no band check** when a stacked slide is absent from the map, whereas `:2512` uses
`plan.stack_bands.get(slide_no, band)`. Plan §6.5 specified `plan.stack_bands.get(slide_no, band)`.
`stack_band_map` is populated for every slide with `stacked_ids` (`:781-783`) so this is latent
today, but the two call sites should not disagree. The `top = bottom - height` arithmetic itself is
right: `DEFAULT_BAND` → `1054 - 350 = 704`, matching the measured `y_min 704` / `bottom 1054`.

### 5. `wrapped_height_runs` now collapses consecutive break characters — **low**

`src/obed_edom/dsk_plan.py:990-992` — `pending_sep` is overwritten by each successive separator, so
`"a  b"` is charged one space width. The old implementation used `_re.split(break_pattern, piece)`,
which yielded an empty word per extra separator and charged one space each — matching
`wrapped_height`, which does the same via `f"{current} {word}"`.

Measured (single run, so this is not a split-boundary artifact):
`"alpha  beta   gamma delta"` @ width 200 → `wrapped_height` **206.12** vs `wrapped_height_runs`
**159.84** (4 lines vs 3). The runs estimator now **under-predicts**, which is the dangerous
direction for a stack fitter. Either restore the per-separator charge, or make the collapse a
deliberate, documented, and tested choice applied to both estimators.

### 6. Thin-space separators diverge between the two estimators — **low / pre-existing, now visible**

`_WRAP_BREAK_CHARS = (" ", " ")`. `wrapped_height`'s `_wrap_lines` measures every join as
an **ASCII space** regardless of the actual break char; the new runs path charges the real one. In
AzoSans-Regular, U+2009 is 207/320 em vs the ASCII space's 77/320 — 2.7× wider. Measured:
`"alpha beta gamma delta"` @ 200 → `wrapped_height` 159.84, `wrapped_height_runs` 206.12.
The runs number is the more faithful one; `_wrap_lines` is the one that is wrong. Not introduced
here, and not blocking, but the two functions are used interchangeably (`fit_text_stack` picks
`wrapped_height_runs` only when `box.runs` is set), so a box's predicted height changes depending on
whether runs were attached. Worth a note in the D-series follow-ups.

### 7. C2's three named equivalence tests are still missing — **low (coverage, not behaviour)**

Acknowledged by the implementer. I verified the behaviour myself (preamble) and it is correct today,
so this is not a reason to hold the piece — but the tokenizer is the kind of code that silently
regresses under the next refactor and it currently has **zero** equality-with-`wrapped_height`
coverage. Add the three cases Codex named plus a small fuzz; ~15 lines, and the probe script in the
scratchpad can be lifted almost verbatim.

### 8. C6 is inert, not partial — **low, but must not be recorded as done**

`src/obed_edom/dsk_assemble.py:2193-2195`, `:2227-2232`. Both new `hidden` parameters default to
`frozenset()` and **no** call site passes anything (`:1766`, `:2321` unchanged; no test passes
`hidden=` either). The H2 misclassification Codex reported is therefore entirely unfixed, and the
new parameters have no coverage. Deferring is fine — Codex ranked it low and the brief said to cut
C6 last — but the ledger should say "C6 not started" rather than "C6 partial".

One substantive note for when it *is* wired: the implementer keys `hidden` by source slide number
and argues in the docstring that a delete-refused placeholder is a source-item property identical
across split parts. I agree with that reasoning, and it contradicts Codex's "key it by output
ordinal/part" only in form. But the `HIDDEN` marker is emitted per ordinal, so the *collection* side
still has to fold parts into one source-number key — make sure that fold is explicit rather than
last-writer-wins.

### 9. Test discrimination — **low**

- `tests/test_dsk_assemble.py:1682` (`test_refit_loop_triggers_without_any_live_overflow_line`) and
  `:1698` (`test_refit_loop_converges_in_two_rounds`) are now identical in fixture *and* assertions.
  The converge test no longer discriminates anything the trigger test does not; give one of them a
  genuinely two-round offline sequence (e.g. `[500, 300, 270]` with `len(calls) == 3`) so
  "converges in two rounds" means something again.
- `:1800` and `:1843` (`test_shrink_fallback_never_writes_above_pass1_size{,_mixed_run}`) now reach
  the shrink path via `_MISSING_RECTS` — i.e. via the measure-missing branch (finding 2), not via a
  measured over-budget height. That is a weaker fixture than the stderr version it replaced, and it
  will change meaning the moment finding 2 is fixed. Use a real over-budget rect.
- No `_offline_measure` test exercises a hidden placeholder, which is the one mapping the brief
  singles out. I probed both branches (correct with `hidden` supplied; E cross-check fires without
  it) — bank it as a test.
- `:1887` asserts `"repeat with i from 1 to" not in script` as the poll-removal guard. That is a
  generic AppleScript idiom; assert on the poll's distinctive text (`set prevH to -1`) instead.

---

## Items confirmed good (no action)

- **Staged→source index inversion** (`:2579-2585`): correct for a delete below the stack (probe:
  ranks `[1, 2]`, staged 0→`text:1`, staged 1→`text:2`) and for a hidden placeholder (`hidden`
  retains `text:0`, identity mapping). The `staged_idx >= len(ranks)` guard is in place, and the
  open-question-E cross-check (`:2572-2578`) fires exactly when it should.
- **Plan-derived trigger** (`:2620-2624`): the loop no longer depends on a live `OVERFLOW` line —
  this is the load-bearing D2b fix, and `test_refit_loop_triggers_without_any_live_overflow_line`
  covers it.
- **Band check** (`:2453-2461`): semantics and arithmetic correct (`top = bottom - height` = 704,
  `bottom + 1.0` = 1055), applied only after the rect check passes, and covered by
  `test_refit_loop_treats_band_breach_as_over_budget` (which genuinely discriminates: without the
  band check that fixture would stop at one call).
- **C1** (`:2407-2415`): applied after *both* the refit-round and the shrink-fallback `batch.run`;
  nonzero returncode and `MISS` both refuse; two tests, both discriminating.
- **C4** (`:2723-2727`): refuses on residual `todo`; `overflows` is empty on every non-exceptional
  return.
- **Gate outcome honoured**: `soft_geometry` is read into `_soft` and deliberately ignored, with a
  test asserting a soft-flagged item is still measured. §3's "stop and re-plan" branch and §9(a) are
  correctly absent.
- **Step 4 complete**: `_second_measure_lines`, its call site, the `MEASURE2` stderr branch, the
  `MEASURE2` warning, `_MEASURE_POLL_DELAY`/`_MEASURE_MAX_POLLS` and the repeat block are all gone
  (`grep` clean across `src/` and `tests/`); `_text_measure_lines` is a single read; the
  live-vs-offline divergence `log()` line is present at `:2629-2632`.
- **C5** deferral is documented in `_run_refit_and_finalize`'s docstring, as instructed.
- **House style**: matches the surrounding module — minimal NatSpec-style docstrings, no stray
  inline comments (the two in `wrapped_height_runs` and `_offline_measure` earn their place),
  consistent naming, `noqa` codes used the same way as elsewhere. `min_source_size` at `:2675` is
  now only a fallback for `lead_source_size`; still used, so not dead.

## On the two knowingly-deferred items

Both are acceptable to defer **this round**: C6 is Codex's own lowest severity and touches a path
this piece does not exercise, and the C2 tests guard behaviour I have now verified empirically. They
should be the first two items of the next round, and C2's tests should land before any further edit
to `wrapped_height_runs`.
