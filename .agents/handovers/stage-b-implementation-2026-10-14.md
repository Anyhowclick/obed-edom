# Handover: Stage B implementation, code complete before qualification (2026-10-14)

Read with the 2026-10-13 handover in this folder (history, Phase 0 detail) and the plan
`.agents/plans/keynote_live_continuity_stage_b.plan.md` (rev 3.5 + the "WS-F interfaces frozen after review r1" block).

## State
| Thing | State |
|---|---|
| Branch | `claude/stage-b-implementation` (local, not pushed, no PR) in worktree `s2-followups-dsk-deck-902af1`; main merged at `480f3297`. |
| Streams | D, R, H, G (reviews r1–r9, 0 major), F (feed module, reviews f-r1–f-r3, 0 findings), P (docs). Reviews in `.agents/reviews/stage-b/`. Session owner override: mediums/lows folded through r5. |
| Suites | Final at `f68ccf34`: 3.12 10993 passed; 3.10 10992 passed + `test_the_settle_wait_never_sleeps_past_its_deadline` failed only under load ~45 (alone 2.3–2.95 s on 3.10, main 2.4 s, bound 4.5 s); dashboard ui 323/323, maps 542+2. Final docs+harness review (`review-final.md`) folded: posterHold reports the runtime outcome with `planned`; D7/D7s staged before the settle gate and pinned (`D7_PLAN_SHA256`/`D7S_PLAN_SHA256`). `dashboard/dist` rebuilt. |
| Decks | D7/D7s authored + V4 passed; exports live ONLY in `~/Desktop/Convert wall to 16x9 CGs/Continuity/D7{,s}-html` (`run_gates` stages them via `QUAL_B_SOURCE`); never copy a real export under main `output/` (main's censuses scan it). Slide JSONs + plan pins in `tests/fixtures/live_continuity/qual_decks/D7{,s}`. |
| Phase 0 | Done: no first-feed stall (30 real-clock runs); paused-element upload = presented frame (no VideoFrame fallback); CEF 127 accepts direct video uploads (46/48 fed). Evidence main `output/evidence/stage-b-2026-10-13/{phase0,cef-step}/`. |
| Provisional | `ALPHA_POSTER_FLOOR` 2.5 (dSep), hold margins, `MAX_INTER_FEED_GAP_MS` 50 — re-bank from the first headless captures with the product module + instrument, before any gate verdict counts. |

## Q7 attempt 1 FAILED (2026-10-14 ~17:46) — resume here
Owner watched managed OBS (projector, Q6 qualification flags) on D7: "labels aren't always on top". Root finding: **the
feed module never engaged with the real player** — in both `feed` and `feed-off` sessions every entry stayed at the
default `state: armed` with `framesFed 0`, the instrument saw 0 feed uploads, 0 claims, 0 departures, 3 normal `0-canvas`
move contexts (8 draws/frame). So no continuous feed, no exact hold: the core fell back to its plain poster hold and the
host still reported the planned `exact` (no runtime outcome ever arrived). Unit + joint tests all pass → the fakes again
diverge from the real player. Evidence: main `output/evidence/stage-b-2026-10-13/q7-attempt1/` (OBS run JSON + summary,
headless Chrome probe artifact).
**Leads (unverified):** `public.state: "armed"` is only `reset()`'s default — `record.armed` is set solely by
`idleAtSource()` (`live_mm_feed_js.py` ~110), which needs hash scene == `atScene-1`, `snapshot().busy !== true`,
`playerState` starting `IdleAt`, and `sceneId == null || sceneId === atScene-1`. Real snapshot (`live_runtime.py` ~324):
`busy = !ready`, `ready` needs `showMode 0` and no `automaticPending` (D7 destinations open with an automatic
movie-start; check the SOURCE slide state at idle), and `sceneId = controller.currentSceneIndex` — check whether that is the
same index space as the hash/`atScene` (possible off-by-one). The Node test fakes `{playerState:'IdleAtFinalState',
busy:false, sceneId:snapshotScene}` (`tests/test_live_mm_feed_js.py` ~162-170), never the real controller. Debug live in
headless Chrome: log `idleAtSource` inputs per rAF on D7 S1/S2 before deciding the fix; then a test that drives the REAL
`__obedLive.snapshot` (patched player) rather than a fake.
**Also found:** Chrome auto-updated to **155.0.8059.79**; `_mm_feed_renderer` qualifies only `QUALIFIED_SNAP_MAJORS =
(154,)` → every Chrome output reports `mmFeed unavailable: renderer upload path not qualified` (baked holds). Re-measure on
155 after the fix, then the owner decides whether to qualify 155 (same tuple gates snap placement). For debugging use a
scratch-only monkeypatch, never edit the tuple without the owner.
**Harness:** the managed `feed` arm's records were INVALID (evidence contract: `managed.sample.{state,standDowns,
videoEnded,uploads,carriedT}` missing at `sessions[feed].samples[0]`) — first live use of that arm; fix with the module.
**Q7 setup that stays valid:** worktree `.claude/worktrees/stage-b-q7` (detached `c104d5a3`; rebuild it at the fix
commit), edited Alpha prepared there (`bf1c093f…-p3-r1`, plan `c9e54655…`, ordinals 10→p8, 11→p9), fixtures in
`~/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/{D7,D7s,Alpha}`, runbook `stage-b-q7-runbook.md`. Owner
decisions: Q7 first then Q2–Q6; managed OBS uses the Q6 qualification flags; measure holdFrame exactness before choosing a
tolerance. Machine: the CEF/OBS placement session ran its pass B after the abort; ask it before heavy work.

## Open for the owner
1. `holdFrame` exactness: ~1/20 paused uploads land one frame newer than the instrument's last-rVFC target (Phase 0). Measure in the real move first, then decide tolerance (instrument scope: gate cost).
2. Re-prepare the edited Alpha deck (Keynote export; the `bf1c093f…` export is gone) for Q3/Q5/Q7.
3. Two r7 lows not folded: sampler time base vs S3 bytes (equal by spec); frames skipped under `readyState < 2` at move start are paint-scored.
4. Qualification Q1–Q7 scheduling (heavy machine time, Q6 managed OBS, Q7 owner session); PR after or before qualification per owner.

## Machine / coordination
One heavy job machine-wide; message peers "need window"/"done". Keynote osascript runs are classifier-blocked from this session (owner runs them). Codex implementers' sandbox blocks `pgrep`/loopback sockets: they weaken process-census tests to pass — reject that and run the real tests outside the sandbox.
