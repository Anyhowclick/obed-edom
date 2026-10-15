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
| **F2 scoping** (other transitions/builds on fill-less DSK) | Plan `.agents/plans/keynote_live_f2_transitions_builds.plan.md` rev 5 and evidence `.agents/reviews/f2/` are on **local, unpushed** branch `claude/alpha-keynote-parallel-cd09de` (`ecdbdb43` plus a Step 0 record commit). Owner decisions: small increments; increment 1 is Twist, Flop, Iris and Revolve transitions plus Sparkle, Anvil and Iris builds; GL is in scope for those names. The owner authored `~/Desktop/Convert wall to 16x9 CGs/F2.key` (9 slides) and Step 0 passed: every effect name was exported. The product-path eye step has not run yet (§3). |
| **PR [#280](https://github.com/Anyhowclick/obed-edom/pull/280)** (texture image grafts) | **Merged 2026-10-15** (`acda6b9e`); its raw review rounds were pruned at merge. Stage T D2 now repairs MM-zoomed PDF images using source-deck identity. Plan `.agents/plans/keynote_export_texture_identity.plan.md`, gate record `.agents/reviews/texture-mm-image-graft/gates-r1.md`. G1 passed and the full suites are green on 3.13 and the 3.10 floor; G3 owner eye passed the map repair. **Its G1 F2 pin is now stale:** the owner set the Asia map to 2 % after the pin, so F2.key is now `f99a68ef…` against the pinned `6fea812c…` and the F2 row will be INCONCLUSIVE. **Done in #281** (merged 2026-10-15): only the 357×235 map collides now (D2×1); G1 PASS. A flaky test from #278, `test_live_host.py::test_managed_probe_state_machine_renews_suppresses_and_stops`, failed 2 of 3 branch full runs under load and 0 of 2 on main; it passes alone. Tell the CEF/placement owner. |
| **MM 3→4 duplicate small maps** | **Fixed: #282 merged 2026-10-15** (`2bd0811b`). A proved zero ancestor now absorbs in `__obedChainOpacity`. Plan `keynote_live_mm_opacity_unmatched_hidden.plan.md` (review log §9); gate record `.agents/reviews/mm-opacity-unmatched-hidden/gates-r1.md` (UH-0/1/2 and owner eye PASS). Stage B re-pins (6 player pins plus `detach_experiment` served SHAs) and re-runs UH-3 on its rebase. The owner's current F2 (`f99a68ef…`) no longer has these leaves; the old export in `F2-evidence-2026-10-14/` is the only positive evidence. Eye copies must be built from the **texture-repaired** export (the raw one shows Asia on slide 4). |
| **Dissolve 7→8 movie frame jump** | Owner keeps the **current-frame freeze** (#262 decision stands), but sees "still a frame jump" on F2 7→8 when advancing mid-movie. First establish where it was seen: the G3 copies the owner watched ran the **stock** player (frame 0 is stock behaviour), the `-patched` copy ran the Build Preview player, and #262's freeze is admitted only on the host-launched qualified Chrome (CEF since #278). Reproduce on the product path. Context: `.agents/plans/keynote_live_dissolve_crossfade.plan.md`, `.agents/handovers/keynote-live-dissolve-crossfade-followups.md`. F2 slide 7 → 8 is a Dissolve 1.5 s; slide 7 carries `shutterstock_3637941261.mp4` (H.264, play-across). **2026-10-15:** the owner sees the jump in the Build Preview player (`patch_rendering`, served from the MM eye copy). That player has no freeze take by design (#278 O1), so a jump there is expected. Still open: reproduce on the product path. |

## 2. Next session (owner request 2026-10-15): fix the MM duplicate, then the Dissolve frame jump

Run them in **one** session and in order. Both change the shared `live_runtime.py` replacement tuple and the on/rendering SHA pins, so they must be composed and re-pinned serially.
1. Opus 5.5 high critique of the MM plan (≤3 rounds). Then owner review, Sol implementation and Opus review.
   - Gates: headless reproduction on the persisted old export with positive and negative controls, the existing MM/fade/hand-back regressions, full suites, and owner eye on old F2 3→4.
   - Coordinate with Stage B: it owns `live_continuity_js.py`, the MM feed and `live_gl_replay_js.py` hooks (plan §5).
2. Dissolve frame jump: investigate and reproduce on the product path, then plan per the roster.

## 3. Other open items from the owner's F2 eye check (2026-10-15)

- **Twist 6→7:** its animation covers the whole slide, and its alpha on fill/key is unverified. The owner is unlikely to use it, so it is deferred (F2 plan's unused-failure rule).
- **Slide 8 `PIN DROP WAVE.mov`:** ProRes 4444 with real alpha (`yuva444p12le`). Browsers can't play it, and prepare refuses real-alpha movies by name. It needs an H.264 version or a future alpha path.
- **G2 live F2 prepare refused** on a per-character Twist & Scale text glyph (`slide 4 (33×135 text)`). Text D1 can't bind per-letter glyphs, so this needs a text-identity design. Separate.
- **F2 increment 1's product-path eye step** (Alpha Keynote, HDMI Chrome + managed-OBS Keyer, beside native) is still pending. It needs a deck that prepares (see the item above).

## 4. Commands

- Raw export (owner Terminal, Keynote quit first):
  `cd ~/Desktop/work/obed-edom && OBED_DSK_RSS_LIMIT_GB=8 .venv/bin/python -c 'from pathlib import Path; from obed_edom.html_preview import export_html; d=Path.home()/"Desktop/Convert wall to 16x9 CGs"; export_html(d/"F2.key", d/"F2-html")'`
- Live prepare from a branch, with the cache outside `output/`: run from the branch worktree, setting `OBED_EDOM_OUTPUT_ROOT=~/Desktop/"Convert wall to 16x9 CGs"/<dir>` and calling `propose_preview`/`apply_preview`. Move the dir to the Trash afterwards.
- G1: `.venv/bin/python scripts/texture_repair_check.py g1 --out <scratch>/g1.json`.
- Worktree setup: `uv sync --frozen --all-extras --all-groups`. Symlink the main checkout's `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx`. For the 3.10 floor, use `UV_PROJECT_ENVIRONMENT=<dir> uv sync … --python 3.10`.
