# Handover — Alpha Keynote live continuity, state at 2026-09-22 (late evening)

Supersedes `keynote-live-continuity-2026-09-22-opacity.md` (its facts hold). Owner rules unchanged: no merge without an
explicit request; hands off Keynote unless told it is free; run the full local suites for every code PR (no CI).

## Where things are (verified after #208 merged, `ebe7e715`)
| Item | State |
|---|---|
| `main` | #206 **G1** `glReplay` derivation (flag-gated, two-sha allowlist) and #208 **G2** runtime module `src/obed_edom/live_gl_replay_js.py` merged 2026-09-22. Nothing imports the module yet; `live_continuity_js.py`, `live_host.py`, `CONTINUITY_VERSION` untouched. |
| Full suite | `uv run pytest tests/ -n auto --dist loadfile` ≈ 100–120 s; 5792 passed, 89 skipped, 1 xfailed with the real export symlinked (`output/p2-recovery/html-adversarial` → main checkout). `test:ui` 222, `test:maps` 2. |
| Worktree setup | New worktree: `uv sync --all-extras --all-groups`, `cd dashboard && npm ci`, symlink the P2 fixture. macOS has no `timeout`. Up to **three** headless Chromes at once (owner 2026-09-22). |
| Plans | `.agents/plans/keynote_live_gl_replay_arming.plan.md` (§11 = G1 as shipped), `keynote_live_gl_replay_g2.plan.md` rev 2 (module contract §2.0–§2.9, seam §2.6, gates §4), `keynote_live_gl_replay_opacity.plan.md` rev 2. |
| Gate evidence | `.agents/reviews/gl-replay-g2/s3-gates-r5.md` — all gates PASS on the pinned js sha `985afeb1…`, **stub seam**, 1920×1080. Harness copies under main checkout `output/live-visible-content/g2/` (git-ignored). |
| Owner decisions closed | Deck (i) plans `pin`; flag-gated derivation with two shas until G3; After Transition stays in the DSK generator, no operator warning; `greenRoi` plan-derived; G1b fields on the flag-on entry; `glReplayUnavailable` (no WebGL) vs `runtimeSeamAbsent` (missing/wrong-version seam) **split kept**. |
| Other worktrees | `dsk-generator-template-memory-9b60ba` belongs to another session — do not touch. |

## Next: G3 + G4 in ONE PR (recommended)
**G3** (`src/obed_edom/live_continuity_js.py` + `tests/test_live_continuity_js.py`, `src/obed_edom/p2_verdict.py`, `live_continuity.py` allowlist):
the `glReplay` zone as a THIRD state (split `preserveAllowedFor` into pool-allowed / mount-allowed; the carried movie is pooled by
`stash()` and never mounted while armed); the seam `window.__OBED_P2_PRESERVE__.glReplay = {version:1, carried(movieKey), movieKeyOf(v),
setKeepWarm(v,bool), release(movieKey,{rect}), note(kind,detail)}` exactly per G2 plan §2.6 (`carried` selects the INSTANCE by captured
rect vs the plan's source instance rect, ambiguous ⇒ null; `release` = retire same-asset siblings per instance + `tryRemount` with the
DESTINATION rect as `__obedRect`, arming §10 a/b); `retireBoundary`/`retireZoneEnd`/`inRetireZone` treat `glReplay` as retire-class for
DOM decisions; `CONTINUITY_VERSION` 4→5; **replace** `QUALIFIED_PLAN_SHA256` (both entries → the new shape), P2 injected plan
(`p2_verdict.build_continuity_plan`, `refusedCarry1to2` accepting `glReplay` with `fallback:"retire"`), pinned test literals, in one commit.
**G4** (`src/obed_edom/live_host.py` + `tests/test_live_host.py`): `OBED_LIVE_GL_REPLAY` env + `LiveOutputHost(gl_replay="off"|"auto")`, default
off; `auto` ⇒ `derive_plan(gl_replay=True)` and `gl_replay_script(plan)` appended after the continuity script (before `main.js`); never
injected unless `CONTINUITY_VERSION >= 5`; `continuity.glReplay` surface in `output()`; test that `off` serves byte-identical HTML.
**Gates after G3+G4 (real seam, product injection path):** G2 plan §4 gates 2 and 4, Q0b n=2 (counter monotonic across the stand-down, one
painting `<video>` after build 1, zero `remount-*` while LIVE), the full P2 adversarial harness (the injected plan changes), Q3 once more.
Then G5 (probe `armed1to2` flip) and G6 (P2 `glReplayCarry1to2`) per the arming plan, then full re-qualification.

## Recommended workflow adjustments for G3+G4 (from the G2 round)
1. **Re-weight from reviews to gates.** Four G2 review rounds yielded ~30 findings; the five defects that mattered (D1, N1–N4) all came from
   headless gates, each one reasoned past by the reviews. Start the gate runner on day one against the in-progress core; make the P2
   adversarial gate BLOCKING before any review round; two Opus reviews then Codex, not three.
2. **Fewer streams.** Two Opus implementers (JS core + Python allowlist/injected plan) plus the gate runner. G3 is one file plus tests.
3. **Two planner passes, second one narrow.** Fable HIGH for the plan; Fable MEDIUM critique limited to the zone semantics and the
   instance-selection rule (the two things the G2 stub approximated).
4. **Brief hygiene that paid off:** implementers stage only owned paths; every fix round ends with the reviewer's exact wording applied or a
   measured refutation; tests are proved RED against the pre-fix bytes before they count; the test author re-pins `js_sha256` last.
5. **Lessons to put in every brief:** force paths get FORCED, not grepped (N4: a "one site" helper refactor silently disabled a force arm);
   sandboxed JS must run in sloppy mode like a real `<script>` (three G2 rounds ran strict by accident); on the P2 frame only program 4
   reveals a missing `Opacity` write — target slot 4 and dirty the program first; `MutationRecord` has no timestamp; transition texture
   layers carry `objectID: None`, so `movieSlot` is positional.

## Pruned this round (PR: docs/handover-2026-09-22-g3)
Removed from the tree (all in git history): reviews for merged work no open plan cites (`dsk-clip-timing`, `dsk-template-optional`,
`gl-replay-g1`, `gl-replay-g2` except `s3-gates-r5.md`, `live-continuity-followups`, `live-continuity-i3`, `test-speed`), the uncited
brief, and two doubly-superseded handovers (09-20-night, 09-21). Kept because live docs cite them: `dsk-split-cap` (open item) and
`groups-census-2026-09-19` reviews (raw rounds of merged items pruned 2026-09-23); the 09-19/09-20 handovers (DeckLink runbook cites them); the
completed `cg_resizer`, `gate_verdict_seam`, `offline_text_middle_anchor` plans (checker/offline_groups/architecture-seams cite them).
**Candidates for the owner to confirm** (no status line, may be closed): `keynote_live_continuity.plan.md`, `keynote_live_visible_content.plan.md`,
`keynote_live_baseline.plan.md`, `keynote_live_continuity_generalisation.md`, `keynote-alpha.md`, `dsk.plan.md`; `status: pending` plans
`checker`, `cue_palette`, `dashboard_test_harness`, `maps`, `offline_groups` — pending since when?

## Still open elsewhere
go-to autoplay (other worktree, implemented) · `instanceCheck.painting` 1↔2 on slide 3 · freeze-control fixture refresh (owner-gated) ·
DeckLink venue test 2026-10-10 · D3: `writebackFailed` is a secondary stand-down reason by design (not forceable standalone).
