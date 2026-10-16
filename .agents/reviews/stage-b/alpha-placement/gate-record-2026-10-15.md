# Gate record: Alpha b6to7/b7to8 hand-back placement fix (2026-10-15)

- **Branch:** `claude/friendly-stonebraker-16d950`.
- **Fix commit:** `48d8182e`. Base: merge of `claude/stage-b-arch` @ `769807b8`.
- **Spec:** `.agents/handovers/alpha-b6to8-placement-fix-2026-10-15.md`. Owner go relayed verbatim by the Stage B Restructure
  session.
- **Evidence (main checkout):** `output/evidence/stage-b-2026-10-13/alpha-placement/fix-ab/`
  - `ab-scores.txt`, `*.verdicts.json`, `*-dbg.pixels*.json`, `*-dbg.stack*.json`
  - `uptime.txt`, `p2-gl-replay.*`
  - briefs and reports, and `repro/`

## Roster
| Role | Model | Round | Result |
|---|---|---|---|
| Implementer | Codex GPT-5.6 Sol high (`-m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write`) | r0 | Spec diff verbatim, plus the new test row and 3 sha pins (core 7fd84c8e) |
| Reviewer | Opus 5.5 high (Agent) | r1 | **READY**, 3 lows: doc "poster or frame", test docstring sentence, the stale-layer edge case (no code; covered by the GL and D2/D5 runs) |
| Implementer | Codex Sol high | r1 fold | Doc and docstring folded, sha re-pinned → `838eeedf` |
| Reviewer | Opus 5.5 high | r2 | **READY**, 1 low (the doc line's two parentheticals in a row, optional, would move the sha again; **not folded**) + 2 evidence notes (both closed below) |

## Change
- `findMovieCanvas` (`src/obed_edom/live_continuity_js.py:1667-1705`):
  - The single in-tolerance candidate inside `v.__obedLayer` wins before distance ranking.
  - `layerMatches` reuses `own`.
- Core sha `302c218d…` → `838eeedf…`, re-pinned at `tests/test_live_continuity_js.py:34`, `tests/test_live_host.py:1781` and
  `scripts/detach_experiment.py:76`.
- Plan, mmFeed (`94e6b068`) and glReplay shas are unchanged.

## Unit
New row `pin-rounded-canvases`:
- **RED on 302c218d:** `landed` False, `1 failed, 5 passed`.
- **GREEN on the fix:** 6 passed. With the targeted `hidden_ride|find_movie_canvas` selection, 8 passed.
- **Full suites, 2026-10-16 at 91cfaf50 (machine load 34–65 from a macOS update, not from any test job):**
  - 3.12: `1 failed, 11230 passed, 38 skipped, 1 xfailed`. The single failure passed on `--lf`.
  - 3.10 floor: `1 failed, 11230 passed, 38 skipped, 1 xfailed`. The failure was
    `test_run_gates.py::test_the_settle_wait_never_sleeps_past_its_deadline` (a wall-clock check: 5.9 s against 4.5 s),
    which passed 3/3 when re-run alone. This fix does not touch `run_gates` or its tests.

## Headless A/B
Setup:
- Chrome 155, run in-process through `repro/run_dbg.py`, one Chrome at a time.
- Pre-move `capture()` disabled (observer-effect control). DOM recorder on every rAF.
- 10 clipped screenshots at 0.1 s intervals on each destination slide (pixel liveness = mean abs diff between consecutive
  frames).
- Arm A = 302c218d (`CORE_FILE`); arm B = the fix.
- Alpha plan `c9e54655`, D7 `0e257092`, D7s `3d1a0bd1`.

The first A/B ran on the r1 core 7fd84c8e. That core differs from 838eeedf only by a doc comment inside the served JS
string. `alpha-on-B2` re-ran on 838eeedf with identical results.

### Alpha (feed on / feed off)

| Arm | handbackContinuity b5/b6/b7a/b7b | artworkAbove | body#body ≤400 ms after a carry | Slide 8 / 9 pixel diff | Anchors |
|---|---|---|---|---|---|
| A on | T / **F / F / F** | T / **F / F / F** | (37435,12,4) (42855,14,4) (42855,14,7) | **0.0** / **0.06–0.18, 0.02–0.06** (frozen) | CF6BC171, F86E3188, 45AAEB5D |
| B on (7fd8) | T / T / T / T | T / T / T / T | none | 4.7–12.2 / 2.5–10.9 (moving) | C01CA56A, B75EFA5A |
| B on (838e) | T / T / T / T | T / T / T / T | none | 4.3–11.5 / moving | C01CA56A, B75EFA5A |
| A off | T / **F / F / F** | T / **F / F / F** | 3 rows | **0.0** / frozen | as A on |
| B off | T / T / T / T | T / T / T / T | none | 10.7–25.9 / 3.3–20.4 | C01CA56A, B75EFA5A |

Null controls, identical in A and B: slide-7 pixels (~22–28); `noRiderAboveCanvas` (b5to6 and b7to8-wa0121 False in every
arm); `labelsOverFeed` True; ambiguous ×4 / remount-done ×4 / departure-interim ×2 / interim-placed ×4.

### D7 / D7 feed-off / D7s
- Event signatures (remount, interim, departure, reuse, pin events, with canvasId and elId):
  - **identical A vs B, and across 3 repeats per arm** (D7 127 events, D7s 84);
  - every anchor is `C700B07C`.
- `artworkAbove`, `noRiderAboveCanvas` and `labelsOverFeed` are identical.
- The only differences are `handbackContinuity` "hand-back exceeded the source-frame tolerance" (3 source frames vs 2),
  always with perfect DOM:
  - arm A: 3 of 30 carries;
  - arm B: 1 of 30.

  This is timing variance, not placement.

### Red controls (on the fixed core 838eeedf)
| Control | Deck | Result |
|---|---|---|
| departure-early-hide | D7 | Red at event level: no `departure-interim` notes (fixed core: 2). No verdict scores departure exposure yet (instrument restructure scope). |
| interim-delay | D7 | Red: "a static poster was exposed during DOM hand-back" on 3 hand-backs |
| no-linger | D7 | Red: `handbackContinuity` False on all 6 |
| overlay-ride | Alpha | Red: `noRiderAboveCanvas` False on all carries, `labelsOverFeed` True (matches the registration) |
| d7-unrepaired | D7-unrepaired | Refused: "feed fixture refused … 242×58 leaf uses 800×225 texture 63683314" |

### Legacy and GL paths (the :2147 / :726 / :2112 callers flagged in r1 low 1)
- P2 `--wait-profile fast --gl-replay auto` on 838eeedf: **success True**, every finding True, including
  freezeControlCaughtByCounter.
- D2 and D5 positive host arms: **pass** on both A and B.

## Not done (resume here)
1. **Optional r2 low:** the doc line's two parentheticals in a row. It changes the sha; fold it only with another re-pin.
2. **Owner decision (spec step 5, untouched by this fix):** in every arm, decoders ride on body#body during the scene-9/13
   transitions, and `noRiderAboveCanvas` is False on b5to6 and b7to8-wa0121. The Restructure session is asking the owner.
3. **Live check by the owner in Q7 attempt 4:** the slide 8–9 videos keep moving and the labels stay on top.

## noRider headless A/B (2026-10-16, diagnosis only)
Owner go relayed by the Restructure session: "do the dedicated headless A/B before Q7 attempt 4".
Evidence: `output/evidence/stage-b-2026-10-13/norider-ab/` (`riders-summary.txt`, `riders-summary-fix-ab.txt`,
`*.verdicts.json`, `uptime.txt`, `repro/`).

**Setup**
- Harness: `repro/run_dbg.py`, run one Chrome at a time. Load was 1.8–3.1.
- `CAPTURE=on` leaves the pre-move `capture()` guard unpatched.
- Every arm ran with the feed on.
- The fix-ab artifacts from 2026-10-15 (capture off) were re-read with the same per-frame rider script.

**Rider offenders, as (move-frame index, GL draws in that frame)**

| Core | Capture | Alpha b5to6 / b7to8-wa0121 | D7 b0to1 a/b |
|---|---|---|---|
| 4c917be4 (pre-departure-fix, 03a35b28) | on | none / none | none |
| 4c917be4 | off | none / none | none |
| 302c218d | on | (0,0)(1,0) / (0,0)(1,0) | (0,0)(1,0) |
| 302c218d | off (fix-ab) | (0,0) / (0,0)(1,0) | (0,0)(1,0) |
| 838eeedf | on | (0,0)(1,0) / (0,0)(1,0) | (0,0)(1,0) |
| 838eeedf | off (fix-ab) | (0,0) / (0,0)(1,0) | (0,0) |
| departure-early-hide control | off | n/a | none |
| overlay-ride control | off | (0,0)(1,5)(2,5)… on every carry | n/a |

**Root cause: an instrument artefact around a designed behaviour; not a regression, not caused by capture, not caused by the placement fix.**
- Every offender is one of the first one or two move frames, and in each of them GL has drawn nothing yet (`draws=0`).
- In those frames the departure fix (af3edf73 + a538cf7f) holds the decoder visible in its source slot on purpose:
  - `deferDepartureHide`: `src/obed_edom/live_continuity_js.py:846`
  - `lingerFeed` sets opacity 1 while waiting for GL: `:1404-1408`
  - `finishDepartureHides` hides it after the first feed advance: `:857-879`
- The rider census counts any frame where the decoder is visible and overlaps the canvas. It doesn't check whether GL has
  painted that frame, or the stacking order: `collectRiders` in `scripts/mm_feed_instrument.py:395-397`, scored by
  `score_no_rider_above_canvas` at `:892-905`.
- Pre-move capture has no effect: the offenders are identical with capture on and off.
- The overlay-ride red control still separates: its offenders continue into frames where GL is drawing.

**The `#body` rides during the scene-9/13 transitions are invisible on the fixed core.**
- DOM-recorder rows on `body#body` (Alpha `*-dbg.json`) are at opacity 0 on 7fd84c8e and 838eeedf, for both feed on and off.
- The only visible `#body` rows are on 302c218d (scenes 12 and 14). That is the placement bug this fix removes.

**Run caveats**
- The Alpha capture-on runs were marked invalid: "1 unplanned loop wrap; retake". The rider census is complete.
- D7 b0to1 reads inconclusive:
  - on the departure-fixed cores, because of this same noRider False;
  - on 4c917be4, because `handbackContinuity` fails (the old core).

**Owner decision:** whether the census should exclude move frames before the entry's first GL draw, or score stacking
order. That is an instrument change; the product is unchanged.
