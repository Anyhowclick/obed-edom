# C3 gate record: arm-wide phases, one carry window per spec (2026-10-16)

Branch `claude/stage-b-c3-adadcc` (local, not pushed). Plan r3 §5, gate 5 (offline) plus fresh runs.
Implementer: Codex GPT-5.6 Sol high (streams V and P, then folds). Reviewer: Opus 5.5 high (lenses with executed repros;
execution served as the adversarial verification), plus a coordinator fresh-capture differential.

## What C3 does
- `paint_instrument.read_phases(rows, plan)` runs once per arm. It produces per-mount lifecycles, keyed by (element id,
  canonical asset), and `entryColdStart` = per mount: first seen, first decoded, duration, rows, visible-undecoded
  rows/duration, missing endpoints.
- `score_arm` publishes `entryColdStart` as **REPORT only**: it is never in a verdict, `combine()`, status, validity or
  `paintCensus`.
- `paint_instrument.carry_window` + `window_bounds` give one carry window per spec, and every carry path consumes it
  (`score_continuity`, `forced_window`, force-wrap). `continuity_window`, `paint_start` and `carry_window_clip` are deleted;
  callers no longer reconstruct scenes.
- **The start rule** (closing rule after review r3):
  - The base window is the pre-C3 legacy window: crossing, grounding, forced floor, chain clip; force-wrap has no clip.
    Candidate selection on it is unchanged.
  - Legacy clock checks AND paint share one start = min(legacy start, old `paint_start`), the union of what the two old
    checks scored.
  - Only the chosen decoder's initial cold-start prefix is skipped: present, connected, readable non-zero rect,
    readyState < 2, never decoded before. The prefix must be followed by a settled decoded source row before the cut;
    otherwise the result is INCONCLUSIVE.
  - Never decoded before the crossing → INCONCLUSIVE.
- Absent rows inside an evidenced under-artwork `glInterval` are excused (`glExcusedMissing`). A decode loss
  (readyState < 2) after the start is red, except inside GL.
- `SAMPLER_JS` rows carry `nextSceneId`. The evidence contract accepts it optionally (null or a count); historical rows
  without it stay valid. Both clocks are kept (sampler `scene`, page `hash`); nothing subtracts one from the other globally.

**Deviation from the plan's literal start ("first settled source row where the carried decoder is decoded").** Applying it
literally (r1/r2) excluded rows the old code scored: build-in scenes, earlier visits, replacements, hidden preloads. Review
rounds 1–3 kept finding that class. The closing rule keeps the old coverage and excludes only the initial cold start, which
satisfies the plan's acceptance ("initial cold start is REPORT, no later failure disappears"). Owner/coordinator: confirm.

## Review
| Round | Scope | Result | Record |
|---|---|---|---|
| r1 | all severities, 3 lenses + fresh differential | 3 blockers (incl. registered reds → None), majors; folded | c3-review-r1.md |
| r2 | all, 2 lenses | blocker + major (visibility class); folded | c3-review-r2.md |
| r3 | all, 2 lenses | same class again → replaced by the closing rule; 3 weakened r2 tests reverted | c3-review-r3.md |
| r4 | major/blocker | 4 majors + 3 test-pinning majors; folded | c3-review-r4.md |
| r5 | major/blocker | 3 majors; folded | c3-review-r5.md |
| r6 | major/blocker | 1 theoretical major (hidden decode on a busy entry row); folded | c3-review-r6.md |
| r7 | major/blocker | no code defect; 1 test-gap major (unpinned no-common shared window), test-only fold `d1484cba`, mutant verified failing | c3-review-r7.md |

The loop stops at r7: its only major was test-only and is closed by a pin verified against the mutant.

## Acceptance evidence
Every reviewer repro and fixture: NEW == OLD (1a421de2) except
(a) the initial cold-start prefix, (b) GL-excused absence, (c) never decoded → None, (d) decode loss after the start,
(e) union start (stricter).

**Fresh captures.** 13 headless captures, 2026-10-16:
- 17:43–17:48 on base code (load 3–10, a peer's suites overlapped, so differential evidence only, no timing claims);
- 18:17–18:19 on C3 code (rows carry `nextSceneId`, 288/288).

Arms:
- reds: D2/D3/D5 no-pin-hold, D1 strip bridge@2, D2 strip pin@6, D3 strip bridge@6, and a later-decode-loss injection
  (`v.load()` 700 ms into a settled decoded source);
- nulls: D1, D7 feed-on, P2 host.

Each capture was rescored by base and C3 `score_arm` on identical rows: 95 verdicts.
- **Every registered red is preserved.** The later-decode-loss red stays False.
- Only 4 verdicts change, all D7 feed-on b1to2 (both counters): False → None, class (b). OLD's False came only from 50
  missing samples entirely inside the evidenced glInterval. The verdict is None because feedLive is unreadable (the known
  C1/F4 `coveredByLaterDraw` item).

**Alpha C1-matrix artifact.** Arm A b6to7/b7to8 wa0125 go False → True, class (b). OLD's misses are entirely inside the
glInterval, drop 0, paint ok, underArtwork True. This resolves the coordinator's reported missingSamples-in-GL issue.

**Stored attempt-3 replay.** 10 sessions, 60 verdicts, 0 changed. The Alpha slide-4 entry cold start is now visible as
REPORT: 339.7 ms, 17 rows, scene 4. This closes F4's A3.

**Pre-C6 drift** (C6 record): C3 changes none of the 60 stored verdicts, so it neither hides nor adds to that drift.

## Tests
- One parameterized C3 fixture (`test_c3_score_arm_uses_one_decoder_grounded_carry_window`) through `score_arm`/
  `score_carry`, plus one compact `read_phases`/`carry_window` case.
- Private-window tests are replaced, the dark-source paint test restored, and the r2 weakenings reverted.

Full suites on C3 `d9ec04df` merged with `claude/stage-b-arch` `dfd3856f` (clean merge, scratch commit `5e767c4b`),
2026-10-16 22:10, with fixtures and Sermon Outlines symlinked:

| Interpreter | Passed | Skipped | xfailed |
|---|---|---|---|
| 3.13 | 11382 | 38 | 1 |
| 3.10 floor | 11382 | 38 | 1 |

Final branch head `ada4fed5`: `d1484cba` (the r7 test row) merged with `claude/stage-b-arch` `ab2553ea` (docs only on top of
`dfd3856f`). Code is identical to the suite tree; the only difference is the 11-line test row. Targeted rerun on the final
tree (paint, contract, probe, mm_feed_instrument, live_run_validity), single process: 2259 passed.

## Open / follow-ups
- Medium/theoretical, recorded not folded (no hidden observations in 29,912 corpus rows):
  - a hidden preload, then a visible cold entry, is stricter (True → False);
  - a decoder decoded but disconnected or zero-rect on every pre-cut row → None;
  - `decode_loss` is unpinned for paint-off captures.
- The D7/D7s feedLive None (`coveredByLaterDraw`) is unchanged; it belongs to F/C1.
