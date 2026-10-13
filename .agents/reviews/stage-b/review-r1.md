# Stage B review r1 — Opus 5.5 high, commit 999e32a6 (WS-D/R/H/G first pass)

Not yet folded (owner paused after one round, 2026-10-13). Round 1 → fold all severities.
Reviewer confirmed: targeted suites green (747 incl. corpus/decks/variants/contract/probe feed+hold); S3 corpus unchanged;
core sha/version/player digest re-pins consistent; P2/D1–D6 runtime plans gain no keys (D3 x-separated).

## Blocker
- **B1 (new class)** `scripts/mm_feed_instrument.py:263,269,297` — the in-page producer never emits the reads `feedLive`,
  `holdFrame`, `artworkAbove` score (`reads: []`, `continuousCoverage: False`, `artwork.reads: []`; `INSTRUMENT_JS` lacks the
  same-task reference canvas, counter decode / Alpha dV/dP, patchInside/coveredByLaterDraw, rVFC last-presented target,
  decoded-source frame matching). Every under-artwork carry is inconclusive; no registered control (feed-off, kill switch,
  from-only, ordinal, after-feed, settle-on-stage) can go red; scorer tests pass only on synthetic records.
  Fix: implement §5.3 in-frame reads in `INSTRUMENT_JS`; add one test feeding a real `report()`-shaped payload through
  `verdict_records` so scores are not None.

## Major
- **M1 (new)** `mm_feed_instrument.py:66-69,246,275` — rows/riders/labels/media not scoped to the entry's own move
  (draw-index match across all contexts; `pauses[-1]`). Alpha @6 (draw 3) collects rows from @2/@6/@8/@10 → interval spans
  moves → `score_continuity` skips pre/post DOM checks (`probe:2606-2629`) — fail-open once B1 lands; media tagged by
  `__obedMmFeedObjectId` (updates only on GL frames) attributes the @8 pause to @6; every label read hits every entry.
  Fix: key rows/riders/labels/media to the move (context serial + `atScene`) and the decoder `__obedInstance`; score per move.
- **M2 (new)** `mm_feed_instrument.py:184` — `report()` finishes each context's last frame at report time → `frame:t
  decreasing` contract failure on ≥ 2 moves; every verdict None; late frames take rider census/`getError` at report time.
  Fix: finish the previous context's open frame on new-context creation (or next rAF); sort by `t`.
- **M3 (new)** `probe:1637` — `_probe_fact_for_spec` tries `toPlayer` before `atScene` and matches rows lacking keys:
  D7 @4 gets `feed_draws[2]` (@2's table); Alpha overlay b0to1 gets @6's. Fix: `plan.feed_draws[spec["atScene"]]` and
  `plan.artwork_above[spec["toPlayer"]]` filtered by `dstObjectId`; drop the generic matcher.
- **M4 (contract vs F)** `probe:1725` vs `host:1119` — `--feed-tamper ordinal` tampers only the in-page continuity plan;
  host passes the untampered runtime to `mm_feed_script(runtime, ...)`. Fix: freeze ONE binding source for F (F reads
  `window.__OBED_CONTINUITY__`, or the probe tampers the runtime handed to the builder).

## Medium
1. (closed class) `mm_feed_instrument.py:428,433` — held+1 counts `presentedFrames` with 50 ms tolerance; a one-frame skip
   passes. Fix: require `firstAfter.mediaTime − pause.mediaTime` = one frame (± half), clock tolerance < half a frame.
2. `score_feed_live` checks read completeness (`:310`) before the explicit continuous expectation → feed-off arm scores None,
   not red. Fix: check the continuous expectation first.
3. (edge) `js:2300` `onStandDown` pauses unconditionally: a stand-down after claim but before departure freezes a visible
   movie on the source slide, and the later ride early-returns (`__obedPosterBoundary === boundary`) so `once` never runs.
   Fix: if `!hasDeparted(instanceOf(v))`, drop the claim + record; departure does pause + `once`.
4. Interfaces assumed for F but not frozen: builder `mm_feed_script(runtime, continuous=, once=)` (`host:1119`); take hook
   `__OBED_MM_FEED__.take(controller, scene)` (`live_runtime.py:58`, not in §2.1's fields); telemetry
   `entries[objectId].{mode,state,framesFed,stoodDown(bool),maxInterFeedGapMs,maxInterFeedGapLimitMs,hold,posterHold,
   lastUploadedFrame}` (§2.1 says `stoodDown(reason)`); `mm_feed_variants` guessed across 3 names × 3 call conventions
   swallowing `TypeError` (`probe:1747`). Fix: freeze these in F's brief; one frozen API; static import like G2 (`host:39`).
5. `ALPHA_POSTER_FLOOR = 6.0` (`mm_feed_instrument.py:8`) lacks the §5.3 provenance (re-score `run2-cmp/direct`, all 9 reads
   green/inconclusive). Fix: do the re-score, cite it at the constant.

## Low
- `js:2295` stand-down keyed on `stoodDown.departure === departure` → re-claimable after a re-departure without go-to; key on
  generation only (like `refusedHere`).
- `js:1162` redundant `if (boundary.underArtwork)`.
- `host:1144` `to_player = atScene - 1` fallback mixes units → keep None; `host:1181` `_mm_feed_info` reports version 1/sha None
  when the module is absent → report absent.
- `host:165` `_mm_feed_renderer`: any non-OBS Chromium counts as qualified Chrome; consider pinning the recorded major
  (`QUALIFIED_SNAP_MAJORS`).
- D row 2 lift test lacks an R11 case (now load-bearing: `_overlap_refusal` scans past the first overlap so a later R11 wins).
- R test (1b) "held plain-bridge overlay → underArtwork bridge lands in layer" missing (only pin hand-off (5) tested).
- Take test's `VideoFrame` capture/release exercises only the test's fake; product proves call order only.
- `ALPHA_DSK_PLAN_SHA256` pinned but no test ties it to the repaired full fixture.
- Probe indirection: `feed_host_kwargs` via `inspect.signature`; six one-line `score_*` wrappers; `verdict_records` infers
  `"armed"` as continuous (mislabels once-armed).
- `_crossing_carries`: a crossing-refused carry on a click-driven destination is decided after the glReplay attempt → no
  glReplay attempt / `glReplayReason` under `gl_replay`.

Verdict: not ready. Counts: blocker 1, major 4, medium 5, low 10.
