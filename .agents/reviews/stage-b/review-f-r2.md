# Stage B WS-F review r2 — Opus 5.5 high, commit cb352851

Round 2 → fold all severities. Scope: `git diff 65c15ab4 cb352851`.

Checks run:
- `tests/test_live_mm_feed_js.py`: 19/19 green.
- My joint Node reproduction: the real `INSTRUMENT_JS` installed first, then the real `MM_FEED_JS`, on one fake GL
  context. I ran it against the new module in five variants.

## r1 findings
| r1 | Status | Evidence |
|---|---|---|
| Blocker: zero-draw frames stand the feed down | **closed** | Per-frame `reached` set in `draw()` when the record's draw index is reached with a ready decoder (`live_mm_feed_js.py:509-510`). `finishFrame` stands down `no-feed` only for `reached && !fed` (`:405`). New test `test_no_feed_requires_a_ready_draw_reached_in_that_frame`; zero-draw lead-ins in the joint test. Joint reproduction below. |
| Med 1 hash already advanced | **closed** | `activeRecords` accepts `atScene - 1 === scene || atScene === scene` (`:243-245`); parametrised test for continuous and once; joint run below. Residual: Low 2. |
| Med 2 fake fidelity | **closed** | G2-style wrapper before the module; zero-draw lead-ins; fed leaf in the middle of the draw order; joint test with the real instrument (`test_real_instrument_observes_module_uploads_after_zero_draw_frame`). |
| Low 1 re-arm and re-claim after stand-down | **closed** | `stoodDownThisIdle` blocks re-arming until `reset` (`:148,:192,:196`). The core's `once` path still re-arms a pre-departure stand-down, by design. |

## Joint reproduction (new module)
| Variant | Module state | GPU video uploads | Instrument `uploads` (frameN, ordinal) | Claims |
|---|---|---|---|---|
| continuous, no lead-in | `fed`, framesFed 3 | 3 | (1,1) (2,1) (3,1) | 1, serial 1 |
| continuous, 2 zero-draw lead-in frames | `fed`, framesFed 3 | 3 | (3,1) (4,1) (5,1) | 1, serial 1 |
| continuous, lead-in, hash already at `atScene` | `fed`, framesFed 3 | 3 | (3,1) (4,1) (5,1) | 1 |
| once only, lead-in, paused decoder | `held` / `exact`, framesFed 1 | **1** | (3,1) | **none** |
| once only, lead-in, hash advanced | `held` / `exact`, framesFed 1 | 1 | (3,1) | none |

No stand-downs in any variant. The one-shot fires exactly once, at the first frame with draws, and never claims. The
instrument sees every module upload with the right frame and ordinal.

## Blocker
None.

## Major
None.

## Medium
None.

## Low
1. **(edge)** `draw()` adds a record to `reached` whenever its draw is reached with a ready decoder, even in `once` mode
   before `once()` was requested (`:509-510`).
   - **Effect:** a `once` request that arrives after the leaf's draw but before the frame closes stands the entry down
     with `no-feed` / `baked` when the next `clear` closes that frame. The next frame would have uploaded. The second case
     of `test_no_feed_requires_a_ready_draw_reached_in_that_frame` asserts this.
   - **Likelihood:** frames complete inside one player rAF callback, and the core's request arrives in another task, so
     this is theoretical.
   - **Fix:** add to `reached` only when the record is due to feed at that draw
     (`record.public.mode === 'continuous' || record.onceRequested && !record.onceDone`). Change that test case to
     expect `held` after the next frame.
2. **(edge, telemetry noise)** Accepting `atScene === scene` also lists a record whose own move has finished for any
   later GL context created while the hash reads `atScene`. A destination-slide build would qualify, if the player draws
   builds through a `N-canvas` context. In that context the record's draw index hits another texture, giving a
   `decoder-mismatch` or `binding-mismatch` stand-down. That calls `seam.onStandDown(src)` on a claim the core still
   holds. The core's `hasDeparted` guard keeps it from pausing the settled decoder, so the effect is a spurious
   `stoodDown` in the telemetry.
   Fix: record `record.wrapped = true` when a context is wrapped for it (cleared in `reset`), and accept
   `atScene === scene` only for records not yet wrapped in this visit.

Verdict: the r1 blocker and mediums are closed and verified end to end with the real instrument. Two theoretical
lows remain. Counts: blocker 0, major 0, medium 0, low 2.
