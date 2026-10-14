# Handover: Stage B implementation, Q7 fix round done, owner Q7 redo next (2026-10-14)

Read with the 2026-10-13 handover in this folder (history, Phase 0 detail) and the plan
`.agents/plans/keynote_live_continuity_stage_b.plan.md` (rev 3.5 + the "WS-F interfaces frozen after review r1" block).

## Resume here
1. **Owner redoes Q7** in managed OBS on worktree `.claude/worktrees/stage-b-q7` (detached `51ead0a8` = the fix round +
   main merge) with `stage-b-q7-runbook.md` (D7, D7s, edited Alpha). Look-fors: movies keep playing through each move
   with labels on top; labels stay on top after each move settles; feed-off freezes at the move-start frame, travels,
   resumes without a restart. Ask peer sessions to hold heavy jobs first ("need window"/"done").
2. Then Q2–Q6 (owner order: Q7 first). Before the PR: dashboard suites (ui, maps) on the merged branch.

## State
| Thing | State |
|---|---|
| Branch | `claude/stage-b-implementation` (local, not pushed, no PR) in worktree `s2-followups-dsk-deck-902af1`; main merged at `25849a82` (#277) in `4eb18cc2`. |
| Streams | D, R, H, G (reviews r1–r9, 0 major), F (feed module, reviews f-r1–f-r3, 0 findings), P (docs). Reviews in `.agents/reviews/stage-b/`. Session owner override: mediums/lows folded through r5. Q7 fix round (Sol high, Opus implementer): `review-q7-r1` 1 low · r2 0 · r3 2 major + 1 medium + 1 low · r4 1 major · r5 1 major · r6 no blocker/major. Main merge: `review-merge-r1` 1 medium · r2 0. All folded. |
| Suites | On the merge (`4eb18cc2`): 3.12 and 3.10 (lockfile venv) 11011 passed each + `test_the_settle_wait_never_sleeps_past_its_deadline`, which fails only under load and passes alone. Dashboard ui/maps last run at `f68ccf34` (323/323, 542+2); no dashboard change since. |
| Decks | D7/D7s authored + V4 passed; exports live ONLY in `~/Desktop/Convert wall to 16x9 CGs/Continuity/D7{,s}-html` (`run_gates` stages them via `QUAL_B_SOURCE`); never copy a real export under main `output/` (main's censuses scan it). Slide JSONs + plan pins in `tests/fixtures/live_continuity/qual_decks/D7{,s}`. Q7 fixtures `Continuity/q7-fixtures/{D7,D7s,Alpha}`; edited Alpha `bf1c093f…-p3-r1`, plan `c9e54655…`, ordinals 10→p8, 11→p9. |
| Phase 0 | Done: no first-feed stall (30 real-clock runs); paused-element upload = presented frame (no VideoFrame fallback); CEF 127 accepts direct video uploads (46/48 fed). Evidence main `output/evidence/stage-b-2026-10-13/{phase0,cef-step}/`. |
| Provisional | `ALPHA_POSTER_FLOOR` 2.5 (dSep), hold margins, `MAX_INTER_FEED_GAP_MS` 50 — re-bank from the first headless captures with the product module + instrument, before any gate verdict counts. |

## Q7 fix round (what changed)
Q7 attempt 1 (~17:46, managed OBS, D7: "labels aren't always on top"; evidence main
`output/evidence/stage-b-2026-10-13/q7-attempt1/`) had three stacked real-player bugs, all hidden by fakes. Each was
reproduced headless on the real D7 player, fixed, and re-measured. Headless D7 feed-on on the merged code (core
`00b9a823`, feed `554053b7`, plan `0e257092`): 6 claims, 0 stand-downs, 88–89 frames per leaf at normal load (~40 under
load ≥ 19), worst gap ≤ 47 ms; `noRiderAboveCanvas`, `labelsOverFeed`, `artworkAbove` (15/15 settled reads) green.
1. **Feed never armed.** At the D7 source idle the hash already reads `#atScene-1` while the player sits at
   `IdleAtFinalState` with `sceneId` one behind (automatic movie start on the slide). `idleAtSource` now matches the
   player's PENDING scene (`sceneId` at IdleAtInitialState, `nextSceneId` at IdleAtFinalState). The Node harness runs the
   REAL `live_runtime._INSTALL` snapshot over a controller in the measured shape (old module → 19/19 tests fail).
2. **Single-texture move (D7 boundary 3) stood down `binding-mismatch`.** The player draws it with its mix program,
   `mixFactor` looked up but never set (GL default 0). Owner decision: a from-only binding feeds when the LIVE uniform
   (`getUniform`) is 0; any other value still stands down.
3. **Labels under the movie after settle.** Two same-rect canvases per movie slot and a stale source layer on the
   re-homed decoder made every remount fall back to `#body` above all labels. `bindFacade`'s rehomed observer now stamps
   the destination stub's layer when the player appends it (current facade token only, validated against a same-rect
   canvas) and reschedules the remount. `findMovieCanvas` is unchanged from HEAD (an interim "same `-contents` → last
   canvas" rule was dropped: groups defeat it). The first remount still ties 2 ms before the stub arrives (≤ 1 frame).
Also: instrument/probe objectId comparisons are case-insensitive (facts lowercased, plan/player uppercase); the managed
`feed` arm's rows moved to `sampleRows` (sampler-row contract).
**Main merge (owner decision: #277 first):** transition-endpoint pairing, per-boundary R12 (excludes `under_artwork`
bridges), Σmin continuing_count; Stage B's ordering kept (overlap→under_artwork, `_crossing_carries`, glReplay, feed).
`51ead0a8` makes the R12 oracle a coherent, visible, non-crossing pair (`_add_wa0125_beside_the_carry_to_slide4`). D7/D7s/
Alpha plan pins unchanged.
Debug pattern (scratch only, not kept): a wrapper that monkeypatches `live_host.QUALIFIED_SNAP_MAJORS` to qualify 155 and
swaps module/core/instrument text, logging core notes, DOM chains and final parents into the instrument report; A/B the
HEAD core against the fix in the same wrapper.

## Open
- `feedLive` unreadable: `counterFromGl` decodes null at both orientations on the real player (instrument coordinate
  bug, not the feed).
- Chrome **155.0.8059.79** still unqualified (`QUALIFIED_SNAP_MAJORS = (154,)`); qualifying 155 is the owner's call.
  OBS (CEF) is unaffected.

## Open for the owner
1. `holdFrame` exactness: ~1/20 paused uploads land one frame newer than the instrument's last-rVFC target (Phase 0). Measure in the real move first, then decide tolerance (instrument scope: gate cost).
2. Two r7 lows not folded: sampler time base vs S3 bytes (equal by spec); frames skipped under `readyState < 2` at move start are paint-scored.
3. Qualification Q1–Q7 scheduling (heavy machine time, Q6 managed OBS, Q7 owner session); PR after or before qualification per owner.

## Machine / coordination
One heavy job machine-wide; message peers "need window"/"done" (active today: CEF/OBS placement, PDF page fix). Keynote osascript runs are classifier-blocked from this session (owner runs them). Codex implementers' sandbox blocks `pgrep`/loopback sockets: they weaken process-census tests to pass — reject that and run the real tests outside the sandbox. Under load ≥ ~19 headless frames-fed halves; recheck at load < 6 before reading a feed regression.
