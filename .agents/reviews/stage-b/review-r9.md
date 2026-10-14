# Stage B review r9 — Opus 5.5 high, commit 2f418b8b

Round 9: only blockers and majors fold. Scope: `git diff 060818da 2f418b8b`. Targeted suites green: 100 probe and
contract tests (GL interval, linger, instrument, feed, hold).

## r8 Major 1
**Closed.** The interval end is `min(closedAt, lastMoveFrameTime + 1.5 * period)`, and the null-`closedAt` fallback
uses the same factor (`mm_feed_instrument.py:525-527`).

The linger test now asserts end `2075.0` for 50 ms periods. A row with jittered frame time `2052` (last + 1.04 period),
carrying both an owner failure and a double painter, is exempt. The row at `2100` (last + 2 periods) is still scored:
it is the only owner mismatch and it is red on paint. That covers both the include-next-tick and exclude-second-tick
cases.

## Blocker
None.

## Major
None. The fold changes only the end factor and its test. The r6 branch sweep (WS-D/R/H/G) and the r7/r8 checks of the
interval start, `closedAt`, `canvasLingerMs` and the sampler time base still hold.

## Not folded (low, from r7, report only)
- Revert the sampler to the rAF `ts` so its bytes stay identical to S3. The values are equal by spec.
- Frames skipped at the start of a move under the decision-14 `readyState < 2` exemption are paint-scored. The interval
  should start at the move's first frame for them.

Verdict: no blocker or major remains in WS-D/R/H/G. Counts: blocker 0, major 0, not folded 2 (low).
