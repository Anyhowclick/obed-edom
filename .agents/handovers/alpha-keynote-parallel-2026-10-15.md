# Handover: Alpha Keynote parallel session (F2 scoping → Stage T image grafts), 2026-10-15

Session "PDF page fix" (worktree `session-cleanup-review-6b8808`). Owner roster until 2026-10-27:
- Astra high plans.
- Opus 5.5 high critiques plans (at most 3 rounds).
- Codex GPT-5.6 Sol high implements.
- Opus 5.5 high reviews code.
The reviewer's model class always differs from the implementer's.

Machine rules:
- One heavy job machine-wide. Send "need window" to peers before suites, Chrome, OBS or Keynote, and "done" after.
- Never put real exports or caches under any `output/`: `tests/test_live_runtime.py:1391` censuses `output/`, including `.html-preview`.
- Keynote can't open decks under `/private/tmp`, so use `~/Desktop/...` work dirs.

## 1. State

| Thread | State |
|---|---|
| **F2 scoping** (other transitions/builds on fill-less DSK) | Plan `.agents/plans/keynote_live_f2_transitions_builds.plan.md` rev 5 and evidence `.agents/reviews/f2/` landed on main with #292 (2026-10-15); the `claude/alpha-keynote-parallel-cd09de` branch is retired. Owner decisions: small increments; increment 1 is Twist, Flop, Iris and Revolve transitions plus Sparkle, Anvil and Iris builds; GL is in scope for those names. The owner authored `~/Desktop/Convert wall to 16x9 CGs/F2.key` (9 slides) and Step 0 passed: every effect name was exported. The product-path eye step has not run yet (§3). |
| **PR [#280](https://github.com/Anyhowclick/obed-edom/pull/280)** (texture image grafts) | **Merged 2026-10-15** (`acda6b9e`); its raw review rounds were pruned at merge. Stage T D2 now repairs MM-zoomed PDF images using source-deck identity. Plan `.agents/plans/keynote_export_texture_identity.plan.md`, gate record `.agents/reviews/texture-mm-image-graft/gates-r1.md`. G1 passed and the full suites are green on 3.13 and the 3.10 floor; G3 owner eye passed the map repair. **Its G1 F2 pin is now stale:** the owner set the Asia map to 2 % after the pin, so F2.key is now `f99a68ef…` against the pinned `6fea812c…` and the F2 row will be INCONCLUSIVE. **Done in #281** (merged 2026-10-15): only the 357×235 map collides now (D2×1); G1 PASS. A flaky test from #278, `test_live_host.py::test_managed_probe_state_machine_renews_suppresses_and_stops`, failed 2 of 3 branch full runs under load and 0 of 2 on main; it passes alone. Tell the CEF/placement owner. |
| **MM 3→4 duplicate small maps** | **Fixed: #282 merged 2026-10-15** (`2bd0811b`). A proved zero ancestor now absorbs in `__obedChainOpacity`. Plan `keynote_live_mm_opacity_unmatched_hidden.plan.md` (review log §9); gate record `.agents/reviews/mm-opacity-unmatched-hidden/gates-r1.md` (UH-0/1/2 and owner eye PASS). Stage B re-pins (6 player pins plus `detach_experiment` served SHAs) and re-runs UH-3 on its rebase. The old F2 evidence export was trashed after merge; the committed fixture holds the regression. |
| **Dissolve 7→8 movie frame jump** | **Fixed: #284 merged 2026-10-15** (`8041b149`). Cause: Chrome auto-updated 154→155 (Oct 13/14), and `QUALIFIED_SNAP_MAJORS=(154,)` refused the freeze grant (`unqualified-version`). 155 re-qualified (DX-1 + `m-snap`; gate record `.agents/reviews/chrome155-requal/gates-r1.md`); owner eye PASS on a 1920×1080 output. Scaled stages (e.g. the MacBook screen, scale 0.79) still jump by design (decision 12). Follow-up: one-command re-qualification script (separate session). |

## 2. Next session (owner request 2026-10-15): fix the MM duplicate, then the Dissolve frame jump

Run them in **one** session and in order. Both change the shared `live_runtime.py` replacement tuple and the on/rendering SHA pins, so they must be composed and re-pinned serially.
1. Opus 5.5 high critique of the MM plan (≤3 rounds). Then owner review, Sol implementation and Opus review.
   - Gates: headless reproduction on the persisted old export with positive and negative controls, the existing MM/fade/hand-back regressions, full suites, and owner eye on old F2 3→4.
   - Coordinate with Stage B: it owns `live_continuity_js.py`, the MM feed and `live_gl_replay_js.py` hooks (plan §5).
2. Dissolve frame jump: investigate and reproduce on the product path, then plan per the roster.

## 3. Other open items from the owner's F2 eye check (2026-10-15)

- **Twist 6→7:** its animation covers the whole slide, and its alpha on fill/key is unverified. The owner is unlikely to use it, so it is deferred (F2 plan's unused-failure rule).
- **Slide 8 `PIN DROP WAVE.mov`:** **landed, #292 (2026-10-15).** Prepare converts silent real-alpha ProRes to VP9-alpha WebM under the same name; it plays in headful Chrome and managed OBS (owner eye PASS on both). Plan `keynote_live_alpha_movies.plan.md`, gate record `.agents/reviews/alpha-movies/gates-r1.md`. Still owed: managed-OBS physical fill/key at the DeckLink field test.
- **Per-letter glyph refusal:** landed in #289 (Stage T D1g). The owner's live F2 prepare now passes the texture step and stops only at the slide-8 alpha movie.
- **F2 increment 1's product-path eye step** (Alpha Keynote, HDMI Chrome + managed-OBS Keyer, beside native) is still pending. Current F2 now prepares fully (slide-4 glyph fix #289, slide-8 alpha movie #292).

## 4. Commands

- Raw export (owner Terminal, Keynote quit first):
  `cd ~/Desktop/work/obed-edom && OBED_DSK_RSS_LIMIT_GB=8 .venv/bin/python -c 'from pathlib import Path; from obed_edom.html_preview import export_html; d=Path.home()/"Desktop/Convert wall to 16x9 CGs"; export_html(d/"F2.key", d/"F2-html")'`
- Live prepare from a branch, with the cache outside `output/`: run from the branch worktree, setting `OBED_EDOM_OUTPUT_ROOT=~/Desktop/"Convert wall to 16x9 CGs"/<dir>` and calling `propose_preview`/`apply_preview`. Move the dir to the Trash afterwards.
- G1: `.venv/bin/python scripts/texture_repair_check.py g1 --out <scratch>/g1.json`.
- Worktree setup: `uv sync --frozen --all-extras --all-groups`. Symlink the main checkout's `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx`. For the 3.10 floor, use `UV_PROJECT_ENVIRONMENT=<dir> uv sync … --python 3.10`.
