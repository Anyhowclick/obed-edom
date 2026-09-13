# Opus review — 8e1ea6f (refit stop-reasons, per-box offline logging, `*.refused.key`)

Worktree `.claude/worktrees/dsk-gen`, branch `feat/dsk-gen`. Read-only; no Keynote, no osascript.
Full `tests/test_dsk_assemble.py`: **285 passed** (29.8s). Discrimination run against a reverted-src
copy in the scratchpad: the 4 new tests fail, the 2 strengthened/added pre-existing-behaviour tests
(`gw53`, `badge_wider`) pass on both (expected — those code paths are older).

## Verdict: APPROVE-WITH-NITS

The root-cause claim is **confirmed by measurement** (below). The code is correct on every skip path I
could construct. Findings 1–2 are substantive but belong to a follow-up brief (this commit is
deliberately observability + artifact retention); 3 is a small real defect; 4–8 are nits.

---

## (1) Root cause — REPRODUCED

`plan_assembly` on the real GW deck, slide by slide, reproduces the r11 pass-1 numbers exactly:

| slide | box | predicted rect h | r11 offline |
|---|---|---|---|
| 13 | text:1 | **243.1** | 269 |
| 17 | text:1 | **135.8** | 186 |
| 17 | text:2 | **83.9** | 189 |
| 28 | text:1 | **273.7** | 349 |

GW 17 plan `t = 0.64`, stack band h = 265.8, w = 1849. Simulating round 2 exactly as
`_build_refit_round` does:

```
round1 corrections {('text',1): 1.370, ('text',2): 2.252}
fit_text_stack(boxes, stack_band, 66.0, height_correction=corr) -> None
  floor 66 -> None   floor 60 -> None   floor 50 -> None   floor 40 -> None
  floor  0 -> t=0.35 (total 239.5 <= 265.8)
```

So round 2 yields `fit is None` for GW 17, `refits == {}`, and pre-fix the slide vanished with no
trace before the generic "still overflows after refit" refusal. The new bookkeeping is the right fix
and the new log line does say so.

**Correction to the brief's premise:** the corrections did **not** reach the 3.0 cap — they were 1.37
and 2.25. The cap is not implicated in r11; the floor (`--min-text-pt 66`) is. Nothing in the diff
depends on the wrong premise, but don't carry "the cap was hit" forward into the next brief.

## (2) Is the 3.0 cap / `measured/rect` ratio sensible? — the 84 **is itself a bug**

Yes, the estimator is being fed the runs (GW 17 text:2 = 3 runs, `AzoSans-Regular 70` /
`ArgentCF-Bold 85` / `AzoSans-Regular 70`, all resolvable, `wrapped_height_runs` returns a value).
The 84 is nevertheless wrong, and measurably so:

```
t=0.64  text:2 est=83.9  (1.21 lines)   <-- planned
t=0.74  text:2 est=166.6 (2.43 lines)   <-- matches the 166.6 from the earlier probes
single-line width of text:2 vs band, oversampled:
  t=0.63 fill=0.971   t=0.64 fill=0.987   t=0.65 fill=1.002
```

At the planned `t=0.64` the estimator packs the whole verse onto **one line at 98.7% of the band
width**. Keynote wraps it (offline measured 189 ≈ 2 lines + padding). The estimator has vertical
padding (`_BOX_PADDING_PT=21`) and a flat vertical safety (`_TEXT_SAFETY_PT=15`) but **no horizontal
margin at all**, so it sits directly on the wrap boundary; a ~1.5% width error flips a line and halves
the box.

That makes `r = measured_h / rect_h` the wrong axis of correction for this failure mode. Height is a
step function of `t` through the wrap count; multiplying a 1-line estimate by 2.25 produces a curve
that is ~2.7 lines tall at every `t ≤ 0.64` and therefore unfittable at any `t` above the floor — which
is precisely the `None` above. The ratio is fine for an under-predicted *line height*; it cannot repair
an under-predicted *line count*.

1. **[major, follow-up brief] `src/obed_edom/dsk_plan.py:1043` `wrapped_height_runs` (and
   `wrapped_height`, ~:285) — no horizontal wrap safety margin.** Charge the wrap width with a margin
   (e.g. compare against `scaled_width * 0.97`, or subtract the text box's horizontal insets) so a box
   at 97–100% fill is predicted as wrapped. With that, GW 17 text:2 predicts ~168 instead of 84, the
   round-1 correction becomes ~1.12 instead of 2.25, and the r11 refit plausibly converges. Please
   re-run the `fill=` probe above across the GW deck before picking the constant — this is a
   deck-wide estimator constant, not a GW-17 patch. Do NOT "fix" r11 by raising the 3.0 cap or
   lowering `--min-text-pt`; measured, GW 17 needs `t=0.35` under the bad correction.
2. **[minor] `src/obed_edom/dsk_assemble.py:2875-2878` — the cap is silent.** When
   `correction.get(...) * ratio` is clipped by `max(1.0, min(3.0, ...))` nothing is recorded, so a future
   run that genuinely does hit the cap will look the same as one that did not. One `log`/`warnings`
   line when the clamp bites (`slide N: text K correction clipped 3.41 -> 3.0`) would have settled the
   "was it the cap?" question in this brief without a probe.

## (3) Refused-deck copy

No scratch leak: `staging_path = batch.work / f"staged-{out_path.name}"` (3264) is the saved staging
deck, not `batch.scratch`; `refused_path` is under `out_path.parent`, outside `batch.work`, so it
survives `LiveBatch.__exit__`. Non-refusal path untouched (`copy_keynote(staging_path, out_path)` at
3352 is outside the `try`). `copy_keynote` clears an existing dest, and the test asserts `out_path`
is *not* created on refusal. Good.

3. **[minor] `src/obed_edom/dsk_assemble.py:3346-3350` — a failing copy destroys the refusal.**
   `copy_keynote` shells out to `ditto` with `check=True`; if it raises (full disk, dest permissions),
   the `CalledProcessError` replaces the `AssemblyRefusal` and the operator loses the actual reason.
   Fix: wrap the copy in `try/except Exception as exc: log(f"could not keep the staged deck: {exc}")`
   and let the bare `raise` re-raise the refusal either way.
4. **[nit] `src/obed_edom/dsk_assemble.py:3316-3320` — pass-1 AppleScript refusals are outside the
   `try`.** The two `raise AssemblyRefusal` for `proc.returncode != 0` fire before the `try:` at 3326,
   so if the pass-1 script did save and *then* failed, the staged deck is still discarded. Cheap to
   cover: open the `try` immediately after `proc = batch.run(...)` (3279).

## (4) Log formats and stop-reason coverage

All four skip paths in `_build_refit_round` set a reason (groupchild 2858, box-count 2864, `not
any_new` 2881, `fit is None` 2886), the stale-reason `pop` at 2891 is correct and tested, and every
slide in `todo` that produces no write is logged on both exits (the `break` path 3078-3081 and the
continue path 3102-3105). I could not construct a fifth silent path: an empty `stacked` falls through
to `not any_new`.

5. **[nit] `src/obed_edom/dsk_assemble.py:3104` — "refit stopped after round N" is emitted for a slide
   the loop has *not* stopped for.** On the continue path other slides may still be refitting, so this
   slide gets the same "refit stopped" line re-printed every remaining round. Suggest reserving "refit
   stopped after round N" for the `break` path (3080) and using "no refit written in round N: slide X:
   …" at 3104.
6. **[nit] `src/obed_edom/dsk_assemble.py:2886-2889` — raw float repr in the reason.** `correction
   {slide_correction}` prints e.g. `{('text', 1): 1.3696612665684833, ('text', 2): 2.251788...}` on a
   real run (only the synthetic test sees a clean `3.0`). Format it: `{iid: round(v, 2) for ...}`.
7. **[nit] `src/obed_edom/dsk_assemble.py:2999-3013` `_log_offline_measures` fires for every eligible
   box on every measure** — on the GW deck that is tens of lines per round, mostly boxes that are fine.
   Consider marking or restricting to the over-budget set (`over=+` only), or keep as-is if the
   operator wants the full table. Also, the `rect is None or h is None` branch skips silently; a
   missing measure is refused elsewhere, but a missing rect would disappear here.

## (5) Tests

`test_refit_stopped_logs_reason_and_per_box_offline_measures`,
`test_build_refit_round_records_stop_reason_when_fit_returns_none_at_floor`,
`test_build_refit_round_clears_stop_reason_once_a_slide_fits` and
`test_refusal_after_pass1_saves_copies_staging_deck_next_to_out` all fail on reverted src — they
discriminate. `gw53` now indexes the badge by `("groupchild", 0, 0)` and pins 1246.97 / band right
edge; that is the fix review 3 asked for. `test_group_badge_wider_than_band_refuses` covers the
pre-existing refusal as requested.

8. **[nit] the new badge-clamp *warning* (`dsk_assemble.py:808-813`) has no test.** `grep -n clamped
   tests/` finds only the gw53 comment. GW 53 is a real clamp case, so
   `test_gw53_badge_x_clamped_to_band_right_edge` can assert the warning text is in `plan.warnings`
   in the same call — the third of the three review-3 nits is otherwise only half-landed.
9. **[nit] the r11 repro test does not use the r11 shape.** It drives corrections to 3.0 via
   `measured=5000`, whereas the live failure had corrections 1.37/2.25 and failed on the floor. The
   test is still a valid discriminator for the bookkeeping, but its comment ("corrections reached the
   cap") mis-describes the incident. Either fix the comment or feed the real 186/189 numbers.

## (6) House style / rule of record

Comment density, refusal/log phrasing, keyword-only params and docstring style match the file.
No inline noise beyond the file's established "why" comments. No new lint config to check
(ruff not installed in `.venv`).

10. **[nit] the new operator-visible contract is undocumented.** `*.refused.key` and the
    `refit stopped after round N: …` / `slide N: text K offline=… rect=… over=…` lines appear nowhere in
    `.agents/plans/dsk_pieceD*.plan.md` (the only plan edit in this commit is the unrelated GW 44
    floor note). Add a line to the rule of record so the next operator knows the artifact exists and
    where it lands.
