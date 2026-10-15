# F4 measurement: faststart remux and movie warm-up vs the Alpha slide-4 entry cold start (2026-10-15)

Measurement only. No product or instrument code changed. This answers proposal F4 in
`alpha-b3to4-stall-2026-10-15.md` (branch `claude/cool-shannon-0179e4`).
Results: `output/evidence/stage-b-2026-10-13/f4-faststart/`. Raw run JSONs were not kept.

## Answer

- **Faststart remux: no.** A lossless faststart (moov before mdat) leaves the slide-4 entry cold start unchanged:
  212 ms median on the original, 215 ms on the remux. Not-decoded frames are 13 vs 12.5.
- **Plain `ffmpeg -c copy -movflags +faststart` is not lossless on these files.** It rewrites the timing. The
  proposal's command must not be used. See the verification section below.
- **Warm-up: yes, large.** Loading any movie in a detached `<video preload=auto>` before slide 4 mounts cuts the cold
  start from ~200 ms to 20–30 ms (12 frames → 1–2). Warming a *different* file (WA0121.mp4) works as well as warming
  `Untitled-H264.mov` itself. So the cost is a one-time media-pipeline start per page, paid by the first movie that
  mounts. It is not file I/O and not moov placement.
  - This matches the stall session's OBS order effect: the second session in the same CEF decoded in 33 ms.

## Setup

- Code: detached scratch checkout of `16f6c9fa` (`claude/stage-b-implementation`, the code the stall A/B used).
  - Its `src/` diff to `claude/stage-b-arch` (`ed8e24e2`) is VP9-only: `live_host._codec_supported` and `web/live`.
  - Every Alpha movie is H.264, so that path is identical.
  - Wrapper: the stall session's `run_probe_ab.py`, unchanged.
- Fixture: `q7-fixtures/Alpha/html-player`, cloned twice into the session scratchpad (APFS clone). One clone was
  remuxed in place under the same filenames. `--original-index` is `Alpha/html-unmodified/index.html`.
- Instrument: `--mm-feed off` **and** the probe-only `NO_PREMOVE_CAPTURE=1` patch (the per-frame pre-move
  `capture()` is a no-op).
  - With the feed off, the probe does not run the paint check. So b3to4 scores True in every arm, and the cold start
    is read from the sample rows instead.
- Arm A only (`--skip-arms B,C,V,Voff,attach`). One headless Chrome at a time, sequential.
  - Batch 1: 6× original vs 6× qt-faststart, interleaved O Q / Q O.
  - Batch 2: 5× control vs 5× warm-same vs 5× warm-other, order rotated.
  - Load average 1.6–4.5 (`uptime.log`).
- Metric (`tools/coldstart.py`), per `<video>` mount (sampler video id), from per-rAF sample rows:
  - `cold`: mount → first readyState ≥ 2, in ms.
  - `nd`: rows from mount with readyState < 2. These are not-decoded frames; Keynote shows the poster while the video
    stays hidden.
  - `play`: mount → first currentTime > 0.

## Remux verification (`verify-*.json`, `tools/verify_remux.py`, `tools/boxdiff.py`)

Five distinct movies (11 files, with copies). `qt-faststart` (Homebrew ffmpeg 9.0.2 tools):

| movie | boxes before → after | size | fps (live_codec) | timing (timescale, samples, stts, elst, presented) | colour (range/space/trc/prim) | framemd5 (all streams) |
|---|---|---|---|---|---|---|
| Untitled-H264.mov (1920×540) | ftyp,wide,mdat,moov → ftyp,moov,wide,mdat | = 62 505 577 | = 29.9577 | = 15360, 1381, 708070, [(2029996, 1024, 1.0)], 46.0317 s | = tv/bt709/bt709/bt709 | = |
| DSK.001.01.h264.mov (3840×1080) | same reorder | = 69 570 882 | = 29.8552 | = | = | = |
| DSK.001.02.h264.mov (3836×1080) | same reorder | = 54 898 896 | = 29.8915 | = | = | = |
| WA0125.mp4 (1280×720) | ftyp,mdat,moov → ftyp,moov,mdat | = 17 048 508 | = 29.9778 | = 600, 1353, 27080, [(1990380, 0, 1.0)], 45.1333 s | = | = |
| WA0121.mp4 (1280×720) | same reorder | = 6 007 694 | = 29.9366 | = | = | = |

- Byte-level check: `ftyp`, `wide` and `mdat` are byte-identical, and `moov` has the same length.
  - Only bytes inside `stbl/stco` differ (127–400 bytes per file).
  - Geometry and the tkhd matrix are unchanged, as are all ffprobe stream fields and the edit lists.
  - The runtime plan SHA in every arm is `c9e546551300…` (= `ALPHA_DSK_PLAN_SHA256`).
- `ffmpeg -nostdin -i X -map 0 -c copy -map_metadata 0 -movflags +faststart` (same ffmpeg) is **not** lossless:
  - MOV: the elst segment is rewritten, so the presented duration grows by 2 frames (46.0317 → 46.0983 s;
    DSK.01 13.398 → 13.432; DSK.02 18.367 → 18.400).
  - MP4: the video mdhd timescale changes 600 → 19200; the stts and elst are rescaled.
  - MP4: 2 AAC packets are dropped (1946 → 1944, 680 → 678), so framemd5 differs. WA0121 also gets +1/600 s of duration.
  - Files grow by 3–23 KB (a `free` box and a new moov).
  - These would fail `preview_movies._verify`'s own timescale and half-frame duration checks.

## A/B cold start (`coldstart.jsonl`, `coldstart-warm.jsonl`)

`cold` median / max in ms (`nd` median / max frames). Slide-4 entry = id1, first movie mounted in the deck.

| mount | original ×6 | qt-faststart ×6 | control ×5 | warm Untitled ×5 | warm other file ×5 |
|---|---|---|---|---|---|
| **id1 Untitled, slide-4 entry (sc4)** | **212 / 217 (13/13)** | **215 / 231 (12.5/14)** | **198 / 215 (12/13)** | **30 / 34 (2/2)** | **20 / 34 (1/2)** |
| id1 mount → playing | 266 | 268 | 264 | 81 | 82 |
| id2 Untitled (sc6) | 32.5 / 34 (2/2) | 16 / 32 (1/2) | 17 / 34 (1/2) | 33 / 35 (2/2) | 32 / 34 (2/2) |
| id3 Untitled (sc8) | 17 / 18 (1/1) | 16.5 / 17 (1/1) | 17 / 19 (1/1) | 17 / 33 (1/2) | 17 / 18 (1/1) |
| id4 WA0125 (sc8) | 17 / 34 (1/2) | 16.5 / 17 (1/1) | 19 / 34 (1/2) | 18 / 34 (1/2) | 18 / 34 (1/2) |
| id5 WA0121 (sc12) | 29.5 / 32 (2/2) | 23 / 33 (1.5/2) | 16 / 31 (1/2) | 29 / 32 (2/2) | 30 / 31 (2/2) |
| id6 DSK.01 (sc16) | 33 / 49 (2/3) | 33 / 34 (2/2) | 33 / 34 (2/2) | 33 / 33 (2/2) | 33 / 34 (2/2) |
| id7 DSK.02 (sc16) | 50 / 50 (3/3) | 50 / 50 (3/3) | 49 / 50 (3/3) | 50 / 50 (3/3) | 50 / 51 (3/3) |

- Every later mount is 1–3 frames in every arm. That includes two fresh mounts of the same 62.5 MB Untitled file and
  the 3840-wide DSK movies.
- Faststart does not move any row beyond run-to-run noise (±1 frame).
- Verdicts: unchanged across arms. b5to6..b7to8 fail as known, and b4to5 failed once in each of original and warm
  (noise, both arms).

## Recommendation

1. **No faststart product change.**
   - It does not help the measured symptom. On a localhost server the moov-at-end costs only one extra range request.
   - If it is ever wanted for other reasons (remote serving, CEF network stack):
     - it belongs in `src/obed_edom/preview_movies.py` as a box-level move: rewrite `stco`/`co64` only, never an
       ffmpeg `-c copy` remux;
     - its verify must read back mdat byte-identical and `movie_timing`/`movie_fps`/`movie_geometry`/`movie_codec`
       unchanged.
   - What a faststart change would move:
     - **Served media bytes and file sha256.** Same size, but chunk offsets change.
     - **`movieConversion` manifest records** (`sha256`/`sourceSha256`), if it rides in that record. Its grouping key
       `_media_data_sha256` hashes mdat, so it is unchanged.
     - **Runtime plan pins: not moved.** The plan reads only codec + fps from movies.
       `ALPHA_DSK_PLAN_SHA256` was observed unchanged.
     - **Probe fixture identity: not moved.** `feed_fixture_identity` hashes `header.json` and the slide JSON only,
       never movie bytes. So a fixture whose movies were remuxed (or swapped) is indistinguishable by its recorded
       identity. That gap exists today, with or without F4.
     - Any "preserve untouched export bytes" expectation on movies would no longer hold for accepted H.264 movies.
       Today `preview_movies` leaves accepted movies untouched (`_accepted`).
2. **Warm-up is the effective lever, and it does not need to be per-slide.**
   - The ~170 ms saving comes from starting the media pipeline once per page. Any earlier movie load gives it.
   - A product version would be a one-shot warm-up at deck load: e.g. a hidden, muted, detached `<video>` on the
     first referenced movie with `preload=auto` (or `load()`), released after readyState ≥ 2.
   - This is an owner call. It changes runtime behaviour, not bytes. It needs a managed-OBS (CEF) A/B before
     adoption; this is headless-only evidence.
   - It would also shrink, but not remove, the remaining 1–2-frame entry gap that F3's `entryColdStart` would report.
   - Not measured:
     - warm-up at deck load vs. at the previous scene (this run warmed on hash `#3`, ~3.4 s before the slide-4 mount);
     - whether the warm-up survives a long idle gap;
     - a feed-on run with the paint verdict;
     - OBS.
3. **Note, unchanged:** `preview_movies._encode_argv` (H.264 re-encode for non-H.264 sources) omits
   `-movflags +faststart`. Every instrument movie generator sets it (`binary_counter_movie.py`, `dissolve_probe.py`,
   `generate_placement_probe.py`, `maps_movie.py`, `maps_reveal.py`, `html_alpha_probe.py`). For an encode (not a
   remux), adding it is harmless to timing. Given the result above, it has no measured benefit here.

## Repro

`output/evidence/stage-b-2026-10-13/f4-faststart/tools/`:
- `ab.sh NAME orig|qtfs`, with `INDEX=<warm index.html>` for the warm arms. Its paths point at this session's
  scratchpad and must be adapted.
- `coldstart.py *.json` prints the per-mount table input.
- The warm patches are `warm-index/index.html` and `warm-other/index.html`. Each is the unmodified index plus one
  inline script that starts a detached video load on the first `#3` hash.
