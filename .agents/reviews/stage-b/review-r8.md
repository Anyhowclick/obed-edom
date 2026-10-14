# Stage B review r8 — Opus 5.5 high, commit 060818da

Round 8: only blockers and majors fold. Scope: `git diff b1264033 060818da`. Targeted suites green: 100 probe and
contract tests (GL interval, linger, instrument, feed, hold).

## r7 Major 1
Closed as specified.
- `end = min(closedAt, lastMoveFrameTime + median period)`, falling back to `lastMoveFrameTime + period` when `closedAt`
  is null (`mm_feed_instrument.py:516-528`).
- The period falls back to 1000/60 when there are fewer than two frames.
- An incomplete set of frame times gives no interval.
- `canvasLingerMs` is reported and validated by the contract (`contract:847-851,875-877`).
- The test covers a 2 s lingering canvas: the settled owner failure and the double painter score red, and the
  null-`closedAt` fallback gives the same bounds.

The residual is in how the end is extrapolated (Major 1 below).

## Blocker
None.

## Major
1. **(edge of the r6/r7 fix: the extrapolated end has no jitter tolerance)** `mm_feed_instrument.py:524-525`.

   The interval exists so that the tick after the last GL frame (canvas still up, decoder still hidden until the
   re-home) is exempt. Its end is `lastMoveFrameTime + median(period)`, compared inclusively with the sampler row's
   frame time (`probe:2605,2758`).

   Real frame times are vsync-derived and coarsened, so consecutive intervals scatter around the median. The next
   tick's frame time therefore exceeds `last + median` about half the time. That tick is then paint-scored, and if the
   decoder is still hidden there it scores `unpainted` and turns the carry **red**. The same coin flip applies to
   `closedAt` when it is detected on that next tick and lands after `last + median`.

   This is a false red on correct runs, intermittent across the ≥ 10 real-clock dev-loop runs. It is the failure the
   r6 fix was meant to remove. The new test uses exact 50 ms periods, so it cannot show it.

   Fix:
   - Use a half-period tolerance: `end = min(closedAt, lastMoveFrameTime + 1.5 * period)` (and the same `1.5 * period`
     in the null-`closedAt` fallback). This always includes the first tick after the last GL frame and never the
     second. It mirrors the `(CARRY_COVER_MAX_GAP_FRAMES + 0.5) * ref` convention the paint coverage check already uses.
   - Add one test row whose frame time is `last + 1.04 * period` (exempt) and one at `last + 2 * period` (scored).

## Not folded (medium/low, report only)
- The r7 lows still stand: reverting the sampler to the rAF `ts`, and the readyState-exempt first frames.

## Remaining blocker/major check
Apart from Major 1 there is nothing else at major or above. The earlier WS-D/R/H/G sweep (r6) still holds, and this
fold touches only the interval end, `canvasLingerMs`, and their contract and tests.

Verdict: one small major. Counts: blocker 0, major 1, not folded 2 (low, from r7).
