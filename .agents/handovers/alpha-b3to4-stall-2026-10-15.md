# Handover: Alpha b3to4 "stall" diagnosis (2026-10-15)

Diagnosis only. No product or instrument code changed. A fix needs the owner's go (proposal below).
Read with `stage-b-implementation-2026-10-15.md` on `claude/stage-b-implementation`.
Evidence: `output/evidence/stage-b-2026-10-13/q7-round2/alpha-stall/` holds `ab-summary.jsonl` (results), the repro wrapper
`run_probe_ab.py` + `ab.sh`, and `compare.py`/`timeline.py`. Raw run JSONs were not kept.

## Owner observation (Q7 attempt 3, managed OBS, Alpha)
"when it's transiting from 1 video to 3, the first video stops playing. looks very jittery actually. think it fell back to the
poster frame". The instrument flagged b3to4 (feed: paint "12 unpainted frames (not-decoded)", stall 0.24 s; feed-off clean).

## Findings
The b3to4 verdict and the owner's jitter are two different effects. Neither one is a decoder stall of the carried movie during the move.

1. **The b3to4 fail is the slide-4 ENTRY cold start, not the carry.** The `Untitled-H264.mov` element is mounted when slide 4
   builds in, then sits at readyState 1 for ~200–340 ms. The video stays hidden, so Keynote's poster shows. This happens
   ~1.7 s BEFORE the 4→5 move. `continuity_window` grounds the carry window at the from-slide's first settled sample, so the
   cold start is scored inside the carry verdict. During the move, the carried decoder rides on `body#body` and its
   `currentTime` advances without a stall in every run.
   - Cold start ≈ 200 ms headless in every arm (old/new code, feed on/off, capture on/off). It is not caused by mm_feed.
   - The OBS feed-off session decoded it in 33 ms only because it ran SECOND in the same CEF (an order effect). Its frame rate
     was also 30 Hz vs 50 Hz.
   - Contributing factor: every Alpha fixture movie is moov-at-end, i.e. not faststart (`ftyp,wide,mdat,moov`). Untitled is
     62.5 MB at 10.8 Mbit/s, 1920×540 H.264 High.
2. **The jitter is an observer effect of our own feed instrument, introduced in `1df31c33`.**
   - Symptom: on the static slides before each fed move (sampler scenes 8/10/12 = slides 6/7/8, where the deck goes
     1 → 2 → 3 tiles), browser frames collapse to 100–233 ms (4–10 fps) headless. In OBS it was 67–100 ms, in both arms.
   - Collapse onset in OBS: 29219, just after the hash flips to atScene-1 (29163).
   - Mechanism: `scripts/mm_feed_instrument.py` `armDecoder`'s rVFC callback runs `capture()` on every video frame while
     `scene() === atScene-1`. That is 21 `drawImage` calls from the 1080p video into a `willReadFrequently` 2D canvas, plus
     `getImageData`. `callbackCostP95Ms` is ~113 ms.
   - Production does not load this instrument. It only runs in probe/qualify runs, which is what the owner watched.

   | run (headless Chrome 155, fresh profile, back-to-back, idle machine) | cost p95 | sc 8/10/12 frame median |
   |---|---|---|
   | new 03a35b28 feed on ×2 / feed off | 113 / 113 / 112 ms | 100/100/200 ms |
   | new, pre-move `capture()` disabled (probe-only patch) | 2.4 ms | 33/17/33 ms |
   | old 51ead0a8 feed on ×2 | 2.9 / 2.5 ms | 33/17/33 ms |
   | new scripts + old src / old scripts + new src | 110 / 2.5 ms | collapsed / normal |
   | new scripts with old `INSTRUMENT_JS` | 2.6 ms | normal |
   | `INSTRUMENT_JS` at 1df31c33 / ca39b819 / dd16db52 | 128 / 127* / 125* ms | collapsed |

   \* Ran while a peer's full suites were loading the machine (from 17:50); timings suspect. Not needed for the conclusion:
   1df31c33 (clean, finished 17:49:51) is slow, its parent's instrument equals 51ead0a8's (fast), and 03a35b28 is slow in
   clean runs.

   - So the cause sits in the instrument JS from `1df31c33` on (`24b1c91d` = old cost). It does not come from the core, the
     feed product or `live_continuity_probe.py`.
   - The `capture()` body and its call site are byte-identical to the old code. What 1df31c33 added on that path is
     `riderTick` → `decoderForEntry()` → `armDecoder()` for every entry on every rAF (old: armed only at configure/claim).
   - The exact costly line is not isolated. A timing split around `capture()`'s `drawImage`/`getImageData` in one run will
     settle it.
3. **Does the instrument catch it?**
   - Cold start: caught as a readable paint fail, but mis-attributed to the carry.
   - Frame-rate collapse: caught by no verdict. `callbackCostP95Ms` is recorded but not gated. The coverage check only
     sometimes turns it into "inconclusive" (new-off: "frame gap 116.6 ms").
   - The Alpha fed moves (b5to6..b7to8) are unreadable (contract `atScene` errors), so nothing scored the moves the owner
     described.
   - Sol's G-gaps WIP (`47bc3698`, DO NOT MERGE) would rescore b3to4 to True and make slow settled cadence report-only. The
     first change fixes the attribution but drops the cold start unscored. The second would excuse this observer effect.

## Fix proposal (owner review)
- **F1 instrument cost (needed; instrument only).** Make the pre-move capture cheap and bounded:
  - root-cause the 1df31c33 regression;
  - capture from one downscaled `drawImage` of the whole frame into a small canvas, then sample patches from it;
  - capture only as many frames as the 18-frame ring needs, not every frame for the whole slide.

  Acceptance on Alpha headless: `callbackCostP95Ms` ≤ ~4 ms, and settled-scene frame medians back to old-code levels
  (≤ 33 ms) in sampler scenes 8/10/12.
- **F2 instrument validity gate (needed).**
  - A run is INVALID (never excused) when `callbackCostP95Ms` exceeds a budget (proposal: 8 ms), or when settled-scene
    browser cadence exceeds 2× the qualified period outside GL intervals.
  - Red control: the current 1df31c33 instrument. Null control: the fixed one.
  - Revise 47bc3698's "slow settled cadence report-only" into this gate.
- **F3 scoring (needed).**
  - Keep the carry window from the decoded source (Sol's fix).
  - Add a separate readable `entryColdStart` finding per decoder mount: not-decoded/poster frames from mount to first
    readyState ≥ 2 while the slide is visible. Red: Alpha slide 4 (~200 ms, 6–12 frames).
  - Owner to decide whether it fails or reports. Stock Keynote HTML has the same cold start.
- **F4 product, optional (owner call; measure first).** Reduce the entry cold start:
  - lossless faststart remux (`-c copy -movflags +faststart`) of exported movies in the preview pipeline;
  - and/or warm the next slide's movie (`preload`/early `load()`) during the previous slide.

  Measure the cold-start delta on Alpha before deciding. It changes served media bytes, so check the export/byte contracts first.
- Also seen, separate: Sol's product finding on b6to7/b7to8 (artworkAbove false; transient `#body` placement on hand-back
  frame 2). No link to this stall was found.

## Open / next
- After F1 lands, re-run Alpha in managed OBS. The owner then re-checks the slides 6→9 jitter by eye.
- Ask the owner whether "1 video to 3" meant slides 7→8→9 (matches the jitter) or the slide-4 entry poster (matches the b3to4 fail).
