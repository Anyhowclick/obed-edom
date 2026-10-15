# Handover: Stage B Q7 round 2 — hand-back fixed, move-start snap + Alpha stall next (2026-10-15)

Read with `stage-b-implementation-2026-10-14.md` (history, Q7 fix round) and the plan
`.agents/plans/keynote_live_continuity_stage_b_q7_handback.plan.md` (owner-approved option A).

## Resume here
Worktree `.claude/worktrees/stage-b-impl` (branch `claude/stage-b-implementation`, pushed, HEAD `1c95d5f1`; extras + `npm ci` synced,
`output/{fixtures,evidence,bank}` linked). Reports/briefs/reviews: `output/evidence/stage-b-2026-10-13/q7-round2/impl/` (`R-dep-*`, `M-merge287*`).
1. **Departure snap fix — REVIEWED (Opus 5.5 high r1 NOT READY → fold → r2 READY → L1 note).** `af3edf73` + `a538cf7f` + `adad9570`:
   the carried decoder stays in its source slot (or an interim anchor above the static movie canvas, below labels) until the feed
   advances or stands down, then moves to `#body` hidden; refused one-shots / stood-down feeds hide at once; `departure-interim`
   note records the placement. Core `302c218d…`. Red control `departure-early-hide`. Record `impl/R-dep-reviews.md` (theoretical
   T-a..T-c await owner evidence). Not yet run live or headless.
2. **Main merged (#278–#287) — `1f728371`, merge review r1 clean, folds `1c95d5f1`.** MM feed's Chrome renderer stays keyed on
   `QUALIFIED_SNAP_MAJORS` (now 154/155). #284 qualified only the freeze, so **Q3/Q5 headless feed arms must pass on Chrome
   155.0.8059.79 (record browserVersion) BEFORE any Q7 external-attach Chrome arm** (plan WS-H). Record `impl/M-merge287-review.md`.
3. **`47bc3698` instrument gaps — UNREVIEWED, DO NOT MERGE AS IS.** Report `impl/G-gaps-report.md`. Disputed by the Alpha-stall
   session: (a) slow settled cadence must INVALIDATE a run (observer effect: per-frame `capture()` while hash == atScene-1,
   callbackCostP95 41 OBS / 114 headless), never be excused, AND capture cost cut; (b) keep the slide-4 ENTRY cold start
   (readyState 1 for 150–340 ms) a readable finding. Revision waits on the Alpha-stall A/B (new feed on/off, old feed on, new with
   pre-move capture disabled) and its proposed thresholds. The departure-exposure verdict (no rider above labels from ride start to
   first draw) goes into the same revision.
4. **Alpha product issues** (pre-existing): b6to7 and both b7to8 fed carries read artworkAbove false; the second hand-back frame has
   the decoder on `#body` before it returns. Alpha-stall session (`Investigate Alpha 3→4 decoder stall (feed on)`) owns the stall;
   coordinate before fixing.
5. Then: Q3/Q5 feed arms on 155 headless → Q7 attempt 4 (owner; all three decks; wait for placement to leave `probing` before the
   first advance in dashboard managed-OBS sessions) + step 3 (dashboard D1, Alpha to the end + press past end), Q2–Q6, full suites
   (3.12 + 3.10 lockfile venv + dashboard ui/maps; known #278 load flake), PR. The `stage-b-q7` worktree (@`03a35b28`, read-only by
   the Alpha-stall session) must be rebuilt at the new HEAD before Q7 attempt 4.
6. Stage T gate exports live in `~/Desktop/Convert wall to 16x9 CGs/Continuity/stage-t-exports/` (main repointed in #286).

## What this round did (commits on `claude/stage-b-implementation`)
| Commit | What |
|---|---|
| `24b1c91d` | plan r3 (Astra planner ×3, Opus critic ×3), owner answers: tolerance ≤ 2 source frames; feed-off held+1 report-only; pixel/lossless deferred |
| `1df31c33` | option A: core rAF wrapper (installs on bridge OR feed) re-runs the attributed final `fB.animate` per rAF through Keynote's ~300 ms post-animation linger while `feed.linger(token)` admits; interim sibling placement of carried decoders before the first post-swap paint; instrument `handbackContinuity`, departure attribution, Stage T fixture precondition; `no-linger` / `interim-delay` controls. No player patch (`SUPPORTED_PLAYERS` unchanged). |
| `ca39b819` | review r1 fold: core holds an uncarried under-artwork decoder hidden when a +2000 ms remount retry lands at its destination scene before the root exists (it was appended to `#body` above labels at D7 b0to1 — real, pre-existing, exposed by the new census); instrument adjacency only for continuous, rVFC/fps duration, hidden post-closure frames, aggregate controls |
| `dd16db52` | review r2 fold: mid-move stand-down pause attribution regression fixed; definitive failures before unreadable |
| `03a35b28` | review r3: a hand-back passes only with a known source fps (`durationSource == "fps"`) |
Core sha `4c917be4…`, feed `94e6b068…`. Reviews: Opus 5.5 high r1–r3 (r3: no ≥ medium open). Targeted suites green (3443).

Fixtures: Q7 D7 and gate copy `D7-html` were Stage-T-repaired in place (`repair_textures`, D4 `63683314 → 3C2EF32B`, slide-3 sha1
`1d960ca5…`); originals kept as `q7-fixtures/D7-unrepaired` and `Continuity/D7-html-unrepaired` (refusal control). D7_PLAN_SHA256 not
re-derived yet — check whether the derived plan changed.

## Results
- Spike (headless + hidden OBS, scratch only): hand-back 9–11 source frames → 1–2; linger covered (last upload adjacent to removal);
  DOM poster exposure 5/6 → 0; controls red as expected. Evidence `q7-round2/spike/`.
- Headless on `03a35b28` (Chrome 155 qualified in-process via `q7-round2/repro/run_probe.py`): D7 feed-on all six hand-backs 1–2,
  noRider/labels/artwork green; D7s green; `no-linger` red 8–11; `interim-delay` b0to1 exposure; D7-unrepaired refused. Verdicts
  `q7-round2/headless/`.
- **Owner Q7 attempt 3** (managed OBS, `stage-b-q7` worktree at `03a35b28`; runs `q7-attempt3/{D7,D7s,Alpha}`): hand-back fixed
  (owner: labels on top; D7 hand-back 1–2 frames, both arms, three D7 runs). Two new owner observations:
  1. **"very brief snap to frame 0 just before the MM transitions"** — root cause: the core hides the carried source decoder
     (hidden ride) 1–3 frames BEFORE the transition's first GL draw (feed: video hidden 4313 → first draws 4425; same every move;
     feed-off ~20–30 ms), exposing the static poster canvas. Stock player hides source layers only after the first GL draw. →
     R-departure (in flight).
  2. **Alpha "transiting from 1 video to 3, the first video stops playing… jittery… fell back to the poster frame"** — Alpha b3to4
     `untitled-h264.mov` overlay bridge (not fed): feed session paint "12 unpainted frames (not-decoded)", longestStall 0.24 s;
     feed-off session clean. Pre-existing: headless on old `51ead0a8` also stalls (0.15 s). Not caused by this round.

## Open
- **Alpha b3to4 decoder stall in feed-on** (owner: follow up in a new session). Hypothesis: decoder contention when the 3-video
  destination starts while the carried decoder rides; something in mm_feed=on makes it worse (feed-off clean). Evidence: owner run
  `q7-attempt3/Alpha/runs/feed-20261015-150437.json` (sessions feed vs feed-off, `feedVerdicts["b3to4:…"]` paint/motion), headless
  `q7-round2/headless/alpha-feed{,-HEAD}.verdicts.json`.
- **Alpha verdicts all unreadable**: evidence contract rejects `mmFeed.context.atScene` / `mmFeed.frame.atScene` on Alpha
  (contractErrors in the owner run) — an instrument bug (G-gaps scope; tell it if its report misses this).
- **Feed-off arm never green headless** (pre-existing on old code): holdFrame "held target reads missing", posterHold "first
  post-resume callback dropped" (the known 1-frame resume drop, plan §5, report-only), footprint-owner mismatches around move start
  and the linger. G-gaps scope.
- `feedLive` unreadable (`counterFromGl`) — unchanged Open item.
- Plan §5 feed-off 1-frame resume drop: not addressed (report-only per owner).
- Declined lows (reviewer agreed): #15 residual hold (interim refused + no carry → hidden, poster shows); `lingerWhy` ordering.

## Machine / coordination
Peers today: OBS run restructuring (placement pair after chrome-requal), MM duplicate-maps fix (PR #284 owner-passed; Chrome 155
re-qualification PR sets `QUALIFIED_SNAP_MAJORS=(154,155)` in `live_host.py:77` — merge conflict-free with Stage B except tests),
chrome-requal, alpha-movie. MM-fix also re-pins `SUPPORTED_PLAYERS`/`REAL_*_SHA256` and `detach_experiment.py` `SERVED_SHA256`/`L2_SERVED_SHA256`
on main: Stage B re-pins serially when it merges main. One heavy job machine-wide; "need window"/"done".
