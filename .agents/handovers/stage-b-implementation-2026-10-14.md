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

## Q7 fix round (2026-10-14 evening) — resume here
Q7 attempt 1 (~17:46, managed OBS, D7: "labels aren't always on top") had three stacked real-player bugs, all hidden by
fakes; each was reproduced headless on the real D7 player, fixed, and re-measured. Headless D7 feed-on with the final
code (core `00b9a823`, feed `554053b7`): 6 claims, 0 stand-downs, every leaf fed 87–89 frames (worst gap ≤ 47 ms) on all
three boundaries; `noRiderAboveCanvas`, `labelsOverFeed` and `artworkAbove` (15/15 settled reads) green.
1. **Feed never armed.** At the D7 source idle the hash already reads `#atScene-1` while the player sits at
   `IdleAtFinalState` with `sceneId` one behind (automatic movie start on the slide). `idleAtSource` now matches the
   player's PENDING scene (`sceneId` at IdleAtInitialState, `nextSceneId` at IdleAtFinalState). The Node harness now runs
   the REAL `live_runtime._INSTALL` snapshot over a controller in the measured shape (old module → 19/19 tests fail).
2. **Single-texture move (D7 boundary 3) stood down `binding-mismatch`.** The player draws it with its mix program,
   `mixFactor` looked up but never set (GL default 0). Owner decision: a from-only binding feeds when the LIVE uniform
   (`getUniform`) is 0; any other value still stands down.
3. **Labels under the movie after settle.** The core's re-home found two same-rect canvases per movie slot (sibling layers
   of one `layerNN-contents`) and the decoder's recorded layer is its source slide's, so every remount fell back to
   `#body` above all labels (HEAD core: final parent `#body`). Fix (review r4): `bindFacade`'s rehomed observer stamps
   the destination stub's layer when the player appends it (measured: the stub lands beside one of the two canvases) and
   reschedules the remount; the existing exact layer tie-break then resolves. `findMovieCanvas` is unchanged from HEAD
   (an interim owner-approved "same `-contents` → last canvas" rule was dropped after r3/r4 showed groups defeat it).
   The first remount still ties 2 ms before the stub arrives (root for ≤ 1 frame), then lands.
Also: instrument/probe objectId case (facts lowercased, plan/player uppercase → every claim unattributed, artwork facts
never attached) fixed case-insensitively; the managed `feed` arm's rows moved to `sampleRows` (sampler-row contract).
Reviews: Sol (gpt-5.6-sol high) r1–r6, r6 no blocker/major (implementer Opus 5.5). Full suite (3.12) on the final code:
11007 passed + the known load-only `test_the_settle_wait_never_sleeps_past_its_deadline` (passes alone); the 3.10 floor and
dashboard suites are not rerun yet (do before the PR). Raw runs: session scratchpad only (not evidence).
**Open (next):**
- **Main merged (owner decision: #277 first):** `4eb18cc2` merges main `25849a82` (#277 deck refusal rules):
  transition-endpoint pairing, per-boundary R12 (excludes `under_artwork` bridges), Σmin continuing_count; Stage B's
  ordering kept (overlap→under_artwork, `_crossing_carries`, glReplay, feed). `51ead0a8` makes the R12 oracle a
  coherent, visible, non-crossing pair (`_add_wa0125_beside_the_carry_to_slide4`). Sol merge review r1 (1 medium,
  folded) → r2 no findings. D7/D7s/Alpha plan pins unchanged. Suites on the merge: 3.12 and 3.10 11011 passed each +
  the load-only deadline test. Headless D7 recheck on the merge: plan `0e257092` unchanged, 6 claims, 0 stand-downs,
  88–89 frames per leaf at normal load, artworkAbove 15/15 (frames drop to ~40 per leaf under load ≥ 19).
- `feedLive` unreadable: `counterFromGl` decodes null at both orientations on the real player (instrument coordinate bug).
- Chrome **155.0.8059.79** still unqualified (`QUALIFIED_SNAP_MAJORS = (154,)`): headless runs used a scratch-only wrapper;
  qualifying 155 stays the owner's call.
**Q7 setup that stays valid:** worktree `.claude/worktrees/stage-b-q7` (detached at `51ead0a8`, the fix plus
the main merge), edited Alpha prepared there (`bf1c093f…-p3-r1`, plan `c9e54655…`, ordinals 10→p8, 11→p9), fixtures in
`~/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/{D7,D7s,Alpha}`, runbook `stage-b-q7-runbook.md`. Owner
decisions: Q7 first then Q2–Q6; managed OBS uses the Q6 qualification flags; measure holdFrame exactness before choosing a
tolerance. Attempt-1 evidence: main `output/evidence/stage-b-2026-10-13/q7-attempt1/`. Machine: coordinate with the
CEF/OBS placement session ("need window"/"done").

## Open for the owner
1. `holdFrame` exactness: ~1/20 paused uploads land one frame newer than the instrument's last-rVFC target (Phase 0). Measure in the real move first, then decide tolerance (instrument scope: gate cost).
2. Re-prepare the edited Alpha deck (Keynote export; the `bf1c093f…` export is gone) for Q3/Q5/Q7.
3. Two r7 lows not folded: sampler time base vs S3 bytes (equal by spec); frames skipped under `readyState < 2` at move start are paint-scored.
4. Qualification Q1–Q7 scheduling (heavy machine time, Q6 managed OBS, Q7 owner session); PR after or before qualification per owner.

## Machine / coordination
One heavy job machine-wide; message peers "need window"/"done". Keynote osascript runs are classifier-blocked from this session (owner runs them). Codex implementers' sandbox blocks `pgrep`/loopback sockets: they weaken process-census tests to pass — reject that and run the real tests outside the sandbox.
