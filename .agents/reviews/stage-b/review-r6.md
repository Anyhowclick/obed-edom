# Stage B review r6 — Opus 5.5 high, commit 51749efc

Round 6: only blockers and majors fold from here.
Scope:
- the r5 fold (`git diff 3ee6f7f9 51749efc`);
- a blocker/major sweep of the whole Stage B branch (`git diff 26ab2213^ 51749efc`, WS-D/R/H/G; WS-F/P not started).

Targeted suites green: 95 probe feed/hold/instrument/GL-interval tests.

## r5 findings
| r5 | Status | Evidence |
|---|---|---|
| Med 1 fake hides retention | **closed** | The fake `texImage2D` snapshots `__obedPresentedFrames` at upload. The new mid-move stand-down case (claim at idle, fed 71/72, decoder presents 73, stand-down + pause, unfed frames, resume) asserts `holdFrame True`, `posterHold True`, `resumptionDiscontinuity 1`, `exactHeldPlusOne False`, `feedLive False`. |
| Low 1 after-feed gating | **closed** | Polling is keyed to a live, unclosed target context and only that context's uploads (`mm_feed_instrument.py:316-318`). The rVFC trigger no-ops after failure or context closure (`:322`). |
| Low 2 chain ids | **closed** | The chain uses distinct ids per hop (`alpha → alpha-hop → alpha-final → alpha-end`). Claims now happen at `atScene-1` and the hash moves to `atScene` before the context opens, so both hash timings are covered. |

## Blocker
None.

## Major
1. **(branch sweep, likely false red: the GL interval stops short of what it exempts)**
   `mm_feed_instrument.py:479-480` with `probe:2602-2603,2741-2765` and `paint_instrument.score_paint`.

   The interval that exempts an under-artwork carry from DOM paint/owner checks is
   `{start: first fed row t, end: last fed row t}`. Each row's `t` is that GL frame's `clear` time.

   Sampler rows carry their own rAF-callback `performance.now()`, so they fall just outside these bounds:
   - In the tick of the first GL frame, if the sampler's rAF runs before the player's, its row has `t < start`.
   - In the tick after the last GL frame, its row has `t > end`.
   - So does any tick between hidden-ride start (departure, before the move's context exists) and the first clear.
   - So does any tick between the last frame and the settle re-home.

   In all of those, the carried decoder is at the hidden ride's `opacity 0`, so `score_paint` classifies the frame
   `unpainted`. "On complete evidence any violating frame fails" (`paint_instrument.py:830-850`). The pre or post paint
   segment then fails and `score_carry` turns the carry red, whatever the GL verdicts say.

   With either rAF ordering, at least one edge tick is outside the interval. So a correctly working fed or held carry
   very likely scores red on its first real capture. This is fail-visible, not a false green, but it blocks every
   under-artwork positive arm. The only GL-interval test (`test_gl_interval_splits_paint_without_waiving_a_pre_move_failure`)
   uses synthetic samples.

   Fix:
   - Tick-align the bounds. Record the frame time of each GL frame (`document.timeline.currentTime` read at `clear`;
     the same value every rAF callback in that tick sees). Record `closedAt` in `finishContext`. Have the sampler record
     its row's frame time the same way. Exempt a sampler row when its frame time lies in
     `[first fed frame's tick, closedAt]` of a context that is not lost and whose bindings are bound.
   - Report the remaining pre-move gap (hidden-ride start → first GL tick) and the post-move gap
     (`closedAt` → re-home) as measured `hiddenGapFrames` in the carry record, and keep scoring them with paint. Once the
     bounds are tick-aligned, an unpainted frame there is a real one-frame blink, so red is the correct verdict.
   - Phase 0's first headless capture must confirm the gap counts before any gate run.
   - Add one synthetic-sample test: a sampler row in the same tick as the first and last GL frame, on the "wrong" side
     of `clear`, is exempt.

## Not folded (medium/low, report only)
None new. The earlier provisional constants (`ALPHA_POSTER_FLOOR`, hold margins, `MAX_INTER_FEED_GAP_MS`) still await
their Phase 0 re-bank, as documented at the constants.

## Branch sweep — other areas checked, no blocker or major
- **WS-D** (`lc`): settle-into-DOM lift, R11 precedence, crossing before the glReplay attempt, `feed` binding from the
  served repaired JSON, probe facts keyed by scene/toPlayer; full-fixture pin `c9e54655…`.
- **WS-R** (`js`, `live_runtime`):
  - hidden ride and the poster-hold flag at every play site;
  - stand-down before departure drops the claim, and departure then holds + `once`;
  - seam v1 and the `take` hook at the D4 site with MM opacity on/off;
  - variants anchor on the current bytes; core sha `6c687c47…` consistent.
- **WS-H** (`host`):
  - renderer resolved before script selection, OBS/CEF checked before Chrome and pinned to qualified majors;
  - continuous and once eligibility resolved separately;
  - frozen builder signature; module-absent output without version/sha;
  - `pre_navigation_scripts` registered before the placement channel and navigation.
- **WS-G**:
  - every scorer's missing/partial/unattributed path is None;
  - the producer contract is validated per entry;
  - attribution holds when claims, stand-downs and departures occur at their real times, under both hash timings;
  - a registered control that cannot be applied scores `unavailable`.

Verdict: one major remains (GL-interval bounds versus same-tick sampler rows). Counts: blocker 0, major 1, medium 0
(not folded: none), low 0.
