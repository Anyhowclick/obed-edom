# Stage B review r7 — Opus 5.5 high, commit b1264033

Round 7: only blockers and majors fold. Scope: `git diff 51749efc b1264033`, plus the sampler time-base question.
Targeted suites green: 393 probe/contract/detach-experiment tests (GL interval, instrument, feed, hold, sampler, paint,
detach).

## r6 Major
**Partially closed.**
- GL frames carry `frameTime` (`mm_feed_instrument.py:31,210`); contexts carry `closedAt` (`:288`).
- The interval runs from the first fed frame's tick (`:514-520`), and only for usable, bound contexts.
- Sampler rows carry the tick time. Exemption and paint segmentation use `sample_frame_time` (`probe:2605,2699-2701,2756-2764`).
- Gap rows stay paint-scored and are reported as `hiddenGapFrames` (`probe:2497-2498,2787`).
- New test `test_gl_interval_exempts_same_tick_edges_but_counts_a_real_hidden_gap`.

The interval's **end**, though, follows my r6 wording (`closedAt`). That wording was wrong for one case; Major 1 below
corrects it.

## Sampler time-base change: can it alter P2, p2-loop or D1–D6?
No verdict change follows.
- **The value is the same.** `frameTs` changed from the rAF callback argument to `document.timeline.currentTime`
  (`probe:615`). In HTML's "update the rendering", the document timeline's current time is set to the frame's `now` in
  "update animations", before "run the animation frame callbacks" receives the same `now`. So within an rAF callback
  the two values are the same frame time. Chromium follows this.
- **Where the value flows:** row `ts` (paint periods, coverage gaps, `unpaintedMs` deltas in `score_paint`), `meta.lastTs`
  (self-check staleness against `stoppedAt`, and `rows[-1].ts == lastTs`), `ctl.tick` / `prepaint.toggle` (paint
  controls), and detach-experiment `rafTs` (anchors still match, the factory builds). Each consumer receives the same
  number as before.
- **The new code paths are inert for these decks.** P2, p2-loop and D1–D6 have no under-artwork carry, so
  `gl_interval` is None. `in_gl` / `sample_frame_time` / `carry_paint_outside_gl` never run, and the `end >= start`
  relaxations apply only to GL intervals. `track_by_id` only adds a `ts` field.
- **No pin is affected.** No sha pins `SAMPLER_JS`.
- **Residual (not folded):** the equality is a spec guarantee rather than something measured here. Keeping the rAF
  argument would leave the sampler byte-identical to S3. See the not-folded list.

## Blocker
None.

## Major
1. **(recurring class: an exemption window that outlives its evidence; corrects my r6 fix wording)**
   `mm_feed_instrument.py:516-520`. The interval end is the context's `closedAt`, which `finishContext` sets in three
   cases (`:286-288`):
   - the next move's context is created with another `atScene` (`:181`);
   - the canvas is found disconnected on a rider tick (`:345`);
   - the context is lost.

   The two failure modes:
   - **The canvas lingers.** If the player keeps the transition canvas connected after the move (hidden or reused), the
     interval extends through the whole settled dwell, up to the next move. Owner and paint checks are then skipped
     (`probe:2611-2627`, post-GL paint segment empty) for the settled decoder. That contradicts §5.3 ("Missing GL
     interval evidence cannot exempt DOM checks"), and a settle failure that rect and `artworkAbove` don't catch (a
     double or substitute painter at the slot) would score green.
   - **The canvas is never closed.** If `closedAt` stays null, the interval is None, every hidden-ride frame is
     paint-scored, and every fed carry goes red.

   Whether the player disconnects the canvas at move end is unmeasured.
   Fix: bound the end by the GL evidence.
   - `end = min(closedAt, lastMoveFrameTime + period)` when `closedAt` is finite.
   - `end = lastMoveFrameTime + period` when `closedAt` is null.
   - `period` is the median of consecutive move `frameTime`s, or 1000/60 when there are fewer than two.
   - `lastMoveFrameTime` is the last frame of the move context, fed or not.
   - Report `closedAt - lastMoveFrameTime` as `canvasLingerMs`, so Phase 0 shows which case holds.
   - Add one test: a context with `closedAt` 2 s after the last frame exempts only up to `last + period`, and a later
     settled row with a double painter fails.

## Not folded (medium/low, report only)
- (low) Revert the sampler to the rAF `ts` argument (`probe:615`), so its bytes and evidence stay identical to S3. The
  instrument's `document.timeline.currentTime` at `clear` equals that value by spec.
- (low) A continuous move whose first frames skip the feed under the decision-14 `readyState < 2` exemption starts its
  interval at the first fed frame. The earlier hidden frames are then paint-scored (red) rather than excused like the
  gap rule. Start at the move's first frame when the skipped frames are readyState-exempt.

Verdict: one major (interval end bounded by context lifetime instead of GL evidence). Counts: blocker 0, major 1,
not folded 2 (low).
