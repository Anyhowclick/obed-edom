# Stage B WS-F review r3 — Opus 5.5 high, commit fcb00330

Round 3 → fold all severities. Scope: `git diff cb352851 fcb00330`.
- Tests: `tests/test_live_mm_feed_js.py` 19/19 green.
- Pin: `js_sha256()` equals `PINNED_MM_FEED_SHA256` (`f1fe0dd6…`).
- Joint Node reproduction: the real `INSTRUMENT_JS` first, then the real module, re-run.

## r2 findings
| r2 | Status | Evidence |
|---|---|---|
| Low 1 `reached` before a `once` request | **closed** | `draw()` returns early unless the record is due to feed (`continuous`, or `onceRequested && !onceDone`), and only then marks `reached` and feeds (`live_mm_feed_js.py:513-517`). The late-request test case now finishes `held`/`exact` on the next frame. |
| Low 2 destination-scene contexts after the move | **closed** | `record.wrapped` is set on every record a context is wrapped for (`:451`) and cleared in `reset` (`:194`). The `atScene === scene` branch applies only while `!record.wrapped` (`:246-247`). Joint check below: a second `N-canvas` context created at the destination scene after the move causes no module stand-down, and the record stays `fed`. |

## Joint reproduction (fcb00330)
| Variant | Module state | GPU video uploads | Instrument `uploads` (frameN, ordinal) | Claims | Stand-downs |
|---|---|---|---|---|---|
| continuous, no lead-in | `fed`, 3 | 3 | (1,1) (2,1) (3,1) | 1, serial 1 | none |
| continuous, 2 zero-draw lead-ins | `fed`, 3 | 3 | (3,1) (4,1) (5,1) | 1, serial 1 | none |
| continuous, lead-ins, hash already at `atScene` | `fed`, 3 | 3 | (3,1) (4,1) (5,1) | 1 | none |
| once only, lead-ins, paused decoder | `held`/`exact`, 1 | 1 | (3,1) | none | none |
| once only, lead-ins, hash advanced | `held`/`exact`, 1 | 1 | (3,1) | none | none |
| continuous, lead-ins, then a later context at the destination scene | `fed`, 3 | 3 | (3,1) (4,1) (5,1) | 1 | none |

## New defects
None found. The fold only gates `reached` and feeding on the same `shouldFeed` predicate and adds the per-visit
`wrapped` flag. The binding checks, state restore, stand-down reasons, `once` semantics, warm-up, frozen interfaces and
host/probe wiring are unchanged since r1/r2.

Verdict: ready from the WS-F review side. Counts: blocker 0, major 0, medium 0, low 0.
