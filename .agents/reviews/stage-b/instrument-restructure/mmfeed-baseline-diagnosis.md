# MM-FEED baseline failures: diagnosis, 2026-10-16

Tree: `claude/stage-b-arch` @ `dfd3856f` (C1 merged; scripts/src identical to `0f010ea9`). Chrome 155.0.8059.80 headless.
Both causes are tree-independent: the same symptoms on pre-C1 `69c84865`. Neither is Chrome .80 or a stage-b-arch
regression. No gate log on record has any MM-FEED arm green (C1 gate 2, F4 acceptance `39b32de9` ×2).
Results: `output/evidence/stage-b-2026-10-13/mmfeed-diag/`.

## Cause 1: Alpha_DSK runs on a fixture with no movie files
`run_gates.sh` stages `fixture("alpha-dsk-textures")/html-unmodified`, repairs it into `<outdir>/alpha-dsk-repaired` and
runs every Alpha MM-FEED arm on it (`mm_feed_fixture`, :726). That fixture was registered by Stage T as "JSON, PDF and
pdfp, no movies" (`keynote_export_texture_repair_stage_t.plan.md` OQ-T5); it has zero `.mov`/`.mp4` files. So
`codec_report` reads every movie as unreadable, `movie_codec_refusal` returns "movie codec is not playable in this
output: untitled-h264.mov (unreadable)", continuity is `unsupported` and `mmFeed` `notApplicable`. Every carry is then
inconclusive: "movie never decoded" (untitled-h264) and "the core feed seam did not identify a feed or departure mode"
(the rest, whose feed seam never armed). The q7 Alpha fixture is a different, complete export.

Controls:
- Offline (`alpha-codec-control.txt`), the host's own `derive_plan` + `codec_report` + `movie_codec_refusal`:
  gate fixture: 5 movies missing, refused (null). q7 fixture: all avc1, not refused. Gate fixture + the 5 movies copied
  by file name from q7: all avc1, not refused (positive).
- Live, feed-on-1920 (`live-controls.txt`). Before (C1 gate round): continuity `unsupported`, all 6 carries None.
  After (the same repaired fixture with the 5 movies restored): continuity `qualified`, `mmFeed` injected, `feedLive`
  True (0.25/0.5/0.75 all ok) on all 4 feed carries; b3to4 carry and b4to5 restart True. The only reds are carry=False
  on wa0125 b6to7/b7to8 from 109/107 `missingSamples` inside the glInterval: the known C3 fold, not a feed verdict.

## Cause 2: D7/D7s labels cover the counter strip, so the GL counter never decodes
The binary counter strip is in the movie's top-left (source rect 0,0,688,48; `binary_counter_movie.STRIP_RECT`). C1 reads
it at `binary_counter_movie.layout()["blockRects"]`, passed as `config.counterLayout` (probe :1970, :2002), for the GL read,
the decoder reference and `counterSafe`. Both decks author a label over each movie's top-left corner, in every layout:
D7 dst movies at (320,700)/(960,700) 640×180 with 202×49 labels at (300,684)/(940,684); src movies at (160,300)/(960,300)
800×225 with 242×58 labels at (140,280)/(940,280). The labels are the later draws 6 and 7 (draw 7 `labelBoxOpacity` 0.61).

The coverage test is correct and the read point is the problem:
- Recomputing `counterSafe` from the recorded quads (`cover.py`) agrees with the instrument on every row (pre-C1: 288/288
  D7, 424/424 D7s): blocks 0–12 (or 0–13) of 17 lie under draw 6 (counter-a) or 7 (counter-b).
- C1's own reads show it: `counterLevels` are a flat 66.7 (the label) for blocks 0–12 and match the reference
  (0,0,0,255) for blocks 13–16; `counterReason` `marker`, so `feedLive` None ("a feed patch is … covered by a later draw").
- The same strip moved to source x 616–768 (top or bottom row) is clear on 100% of rows of every D7/D7s artifact
  (1600/1920/2560, from-only); the current site is clear on 0% (`d7-strip-coverage.txt`, `strip_sites*.py`).
- Live, D7 feed-on-1920 (`live-controls.txt`), each arm on the same instrument code:
  - before (C1 gate round): 644/644 GL counter reads covered, `counterReason` `marker`; `feedLive` None on all 6 carries;
  - positive: counter movies given a copy of their own strip at source x=616 (`strip2.sh`) and `counterLayout`
    blockRects shifted +616 (scratch patch to probe :1970/:2002): 640/640 reads clear and decoded; `feedLive` True on
    all 6 carries (every read within 1 of the decoder);
  - null (shifted layout, original movies, no strip at the new site): reads clear, but the decoder reference has no
    counter there, so the instrument falls back to `kind: alpha` reads (638/638) and b2to3 scores `feedLive` False at
    0.75. So decoding needs the strip at the read site, and the counter path is what scores D7 correctly.
  (The control's x=616 copy overlapped the original strip's last two blocks; the control reads only the copy. The fix
  below uses x=704, clear of the original and still clear of every later draw on 100% of rows: `strip_sites2.py`.)

The b1to2/b2to3 D7 carry=False in the C1 round is separate: 107 `missingSamples` (detached) inside the glInterval, the
known C3 fold. `check_mm_feed` flags only `feedLive` there.

Side finding (null control): when the decoder reference has no counter, a counter deck is silently scored with Alpha
distances on a moving grating, which produced one spurious `feedLive` False. Worth a refusal (counter decks must read
`kind: counter`) when C4 touches stream F; not needed for this fix.

## Proposed fixes (not implemented; for the coordinator)
1. Alpha (owner call on which):
   a. register a complete Alpha export (movies included) as the MM-FEED fixture and keep `alpha-dsk-textures` for Stage T
      only; or
   b. in the run_gates Alpha staging heredoc, restore the movies from a registered complete export of the same deck
      by file name before the repair, and refuse the run if `codec_report` still has an unreadable movie.
   Either way add the codec check to staging so a movie-less fixture can never reach a timed run again.
2. D7/D7s: give the counter movies a second, identical strip at source x=704 (top row; clear of the original 0–688), and
   read that one: a per-deck `counterLayout` (blockRects +704) for D7/D7s, everything else unchanged. Then re-export
   D7/D7s from Keynote with the new movies, so the poster images carry the second strip (holdMatch/poster separation
   uses the poster counter). Swapping only the movie files in the export leaves posters without the strip. Movie
   regeneration is offline (`binary_counter_movie.py` gets an optional second strip); the re-export needs Keynote, so
   it is the owner's call. Re-pin `D7_PLAN_SHA256`/`D7S_PLAN_SHA256` only if the plan changes (it should not).
