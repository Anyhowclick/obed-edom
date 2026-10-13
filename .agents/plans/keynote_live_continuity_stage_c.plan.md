# Live continuity, Stage C: convert movies to H.264 at prepare time, and partial continuity

Status: **DRAFT rev 2 (2026-10-13). Planning only; awaiting owner review.** Critique r1 (Opus HIGH): duplicates are grouped by media data, because Keynote's per-slide copies differ in `moov` timestamps (§1.1, §2.1); the timing check compares the presented (edit-list) timeline, so an edit-listed source is no longer falsely refused (§2.1); no decoder is held into an unmeasured transition, which replaces the "treat it as a cut" branch and keeps §3.2's "no new plan shapes" true (§3.1); the order section states S3's own probe round and B's lost allowlist oracle (§3.4, OQ-C2); factual fixes to the gate-fixture encoding claim (§6), the in-place-upgrade rejection (§2.1) and G5 (Keyer output). Read-only against `claude/s2-followups-dsk-deck-902af1` (main `93963f4c` + `87ab7240` + `e6649cc6`). It implements the owner's decisions of 2026-10-13: (1) convert movies when the deck is prepared, and (2) carry the moves that qualify instead of switching continuity on or off for the whole deck.

Related plans: `keynote_live_continuity_stage_b.plan.md` (rev 2, not approved) and `keynote_live_continuity_generalisation.plan.md` (S3 = OQ-8).

Citation prefixes:

| Prefix | File |
|---|---|
| `lc` | `src/obed_edom/live_continuity.py` |
| `js` | `src/obed_edom/live_continuity_js.py` |
| `host` | `src/obed_edom/live_host.py` |
| `hp` | `src/obed_edom/html_preview.py` |
| `wl` | `src/obed_edom/web/live.py` |
| `LP` | `dashboard/src/live/LivePresenter.tsx` |

**Goal.** A hand-authored deck plays in every live output (headless or visible Chrome, OBS attach, managed OBS), whatever codecs its movies use. A continuity problem never stops a deck from playing: the moves that qualify carry, and every other move is named in the dashboard.

**Owner decisions that still govern (not reopened):**
- Pin hold is accepted.
- R9.
- A runtime carry refusal lasts until the next go-to.
- Main freeze bracket option A.
- Decision 14.
- Instrument scope: catch what the owner's eyes can catch.
- Asset matching stays exact and canonical.
- Runtime identity is objectID only.
- New: the dashboard gate (handover open item 4, "owner: keep") is **superseded**.

## 1. Evidence (offline)

### 1.1 Codecs and prepare, today
- **Codec probe.** The host probes codecs on every session: `codec_report` (`lc:1987-2022`) uses the box reader in `src/obed_edom/live_codec.py` (no ffprobe).
  - Warning text: "X (codec) may not play in this output" (`host:852-866`).
  - `_codec_supported` (`host:101-111`): H.264 plays everywhere; HEVC only in a visible (headful) launch; everything else fails closed.
- **Codec gate.** If any movie named in the runtime plan's `movies` table (assets with only retire entries included) fails `_codec_supported`, the whole deck's continuity becomes `unsupported` (`host:883-893`). The movie still does not play: Chrome never decodes ProRes, and HEVC is not decoded in headless Chrome or in OBS's browser (CEF).
- **UI.** "Some movies may not play in this output" (`LP:37-48,355`). README:239-245 says "The original movie file is never transcoded."
- **Prepare.**
  - `apply_preview` runs Keynote's export into `output/.html-preview/{digest}-p3-r1/html` (cache key `hp:184-186`; export `hp:1033-1038`) and writes `manifest.json` last (`hp:1039-1046`). On any exception it deletes the export (`hp:1047-1050`).
  - `load_cached` reuses a cache after checking only the manifest and the `main.js` digest. It never reads movie bytes (`hp:871-891`).
  - Starting a live session checks `main.js` against `SUPPORTED_PLAYERS` and the manifest's player digest (`wl:114-116`).
- **Export layout (measured).** Every slide folder holds its own copy of each movie: `assets/<uuid>/assets/<Name.ext-start-end.ext>`. Copies are separate files with the same size and the same `mdat` bytes, but their `moov` timestamps differ, so their file sha256 differ: Untitled's 6 copies give 5 distinct sha256, and each ProRes pair first differs inside `mvhd`.
- **What reads movie files (checked).** `derive_plan` reads only slide JSON and file names (`lc:1816-1939`). The manifest's `assetPaths` hold folder, payload and thumbnail only (`hp:507-519`); `playerDigest` hashes `main.js` only. Registry `bytes` is `tree_bytes` taken after the export (`hp:929-932`). The host serves each file with its live size (`host:383`), and reads `fps` from `mdhd`/`stts`. The player takes `startTime`/`endTime` (e.g. 46.0333) from the slide JSON.

  | Export | Movie | Codec / size | Copies |
  |---|---|---|---|
  | Minimal Alpha_DSK (`59cb220d…`) | `Untitled.mov` | HEVC Main 10 (bt709, SDR) 1920×540, timescale 30, B-frames | 6 |
  | | `clip-10-1000001.mov` | ProRes LT (`apcs`) 1922×1080, timescale 15360 | 2 |
  | | `clip-10-1000002.mov` | ProRes LT (`apcs`) 1282×1080 | 2 |
  | | `WA0125.mp4` | H.264 | 1 |
  | Alpha_DSK (`3b9019f0…`) | all three assets | H.264 (`avc1`) | — |

  Every movie has AAC audio and sample-entry depth 24, so none has an alpha channel.
- **Tooling and scratch checks (measured).** The bundled ffmpeg is imageio-ffmpeg **7.1** (`maps_movie.ffmpeg_exe`, `:42-48`). It includes libx264, and there is no ffprobe next to it. Checks on 60-frame cuts of the Minimal clips:
  - libx264 (crf 18, preset fast, yuv420p) with `-video_track_timescale <source timescale>` keeps the timescale, the stts sample count and the stts total exactly. Example: the HEVC clip at timescale 30 gives (60, 60). Without the flag, ffmpeg switches to timescale 15360.
  - libx264's output is High profile with B-frames, so it always carries an edit list whose `media_time` is the B-frame shift (2 ticks at timescale 30, 1024 at 15360). ffprobe reads the first presented frame at pts 0 for both source and output, so the `currentTime` origin does not move. Alpha_DSK's own `untitled-h264.mov` already has this shape.
  - A source with a non-identity edit list (a stream-copy cut of the HEVC clip: 61 samples, 2.03 s of stts, edit list presents 1.667 s) converts to 47 samples whose edit list presents 1.667 s. The presented timeline matches; the raw stts does not.
  - `-noautorotate` keeps a 90° display matrix. With the default autorotate, the frame becomes 180×320.
  - `alphaextract,format=gray,signalstats` reads a minimum alpha of 255 on a constant-alpha ProRes 4444 and 0 on one with real alpha. Both have sample-entry depth 32.
  - Keynote's own ProRes 4444 export fills alpha with a constant 255 (`dsk.plan.md:305`).
  - ffmpeg 7.1 cannot decode HEVC's alpha layer.
- **Gate fixtures never pass through `apply_preview`.** The probe copies fixture trees straight into the preview root (`scripts/live_continuity_probe.py:1019`). P2 and D-deck movies are already libx264 in `.mov` (Baseline, no B-frames, no audio; `scripts/binary_counter_movie.py:106-108`), and they play headless, attached and in managed OBS.

### 1.2 Deck gating, refusals and UI, today
- **Start gate.** `_deck_qualification` derives the runtime plan (with GL replay first under Keyer). `start` refuses any `Unsupported` (`wl:67-74,261-263`), even when started with `continuity: "off"` (`tests/test_live_api.py:694`).
- **Every real deck is blocked by the allowlist alone.** Offline:
  - Alpha_DSK derives with 4 `overlap` refusals.
  - Minimal Alpha_DSK derives with 2 `overlap` refusals (at 0→1 and 5→6).
  - Both then fail `QUALIFIED_PLAN_SHA256` in `to_runtime` (`lc:654-668,831-832`), so neither can start today.
- **Per-move refusals already exist end to end:**
  - `MovieContinuity.refusal`/`code` becomes a `retire refused` entry (`lc:872-873`).
  - `ContinuityPlan.refusals` (`lc:775,1929-1938`).
  - The host turns them into `notCarried` (`host:920-939,1001-1002`).
  - The dashboard shows them under the badge: the first 3 plus "+N more", **without the movie name** (`LP:24-33`).

## 2. Part 1: convert movies at prepare time

### 2.1 Design. Recommendation: convert inside the fresh-export path, verify, record; a cache is reused only when every movie it references is H.264
**New `src/obed_edom/preview_movies.py`, `convert_movies(export_root, slides, *, log) -> dict`.**
- **Which files.** Every `.mov`/`.mp4`/`.m4v` referenced by a movie node, found with `lc._referenced_movies` (`lc:1954-1984`). The suffix filter excludes image movies; web movies have no file. Only files whose `codec_family(movie_codec(path))` is not `h264` are converted.
- **Duplicates.** Files are grouped by the sha256 of their `mdat` payload plus equal timing and geometry readings (file sha256 never groups Keynote's copies, §1.1): one encode per group. The other copies are hardlinked (copy as fallback) and swapped in with `os.replace`. Copies whose media data differ are encoded separately.
- **Checks before encoding.** A failure refuses the movie by name and writes nothing:
  - **Real alpha.** If ffmpeg decodes the movie to a pixel format with alpha (read from `ffmpeg -i` stderr, the same pattern as `dsk_movie_export._ffprobe`), run one decode pass with `alphaextract,format=gray,signalstats`. Any frame with a minimum alpha below 255 is refused ("has transparency; H.264 has none"). HEVC with sample-entry depth 32 is refused as "transparency cannot be checked". The pixel-format name is never trusted on its own.
  - **Odd width or height:** refused, because 4:2:0 needs even sizes.
  - **Source timing unreadable:** refused.
- **Encode.** argv: `ffmpeg -nostdin -y -v error -noautorotate -i SRC -map 0:v:0 -map 0:a? -c:v <_crop_encoder_args("h264")> -fps_mode passthrough -video_track_timescale <source mdhd timescale> -c:a aac -b:a 192k -progress pipe:1 -nostats TMP`.
  - The video arguments are `dsk_movie_export._crop_encoder_args("h264")` (`:140-146`): libx264, crf 14 (owner 2026-10-13: extra headroom), preset fast, yuv420p.
  - TMP is a hidden sibling file with the same extension, so ffmpeg picks the right muxer.
  - Progress goes to the job log about every 5 s: "Converting untitled.mov to H.264 · 12 / 46 s". `LiveDeckInput` already shows the last log line.
- **Verify.** Box reads only, no ffprobe. The output must be `avc1`, and these must equal the source's: coded size, mdhd timescale, the tkhd matrix, and the **presented** video duration (the video track's edit-list duration, or its mdhd duration when it has no edit list) to within half a frame. The stts sample count must also match when the source's edit list is absent or the identity (one entry, `media_time` 0). Raw stts totals are not compared: libx264 always writes a B-frame edit list, and an edit-listed source legitimately loses its skipped samples (§1.1). A dropped frame still fails. Only then `os.replace`. Any failure raises `PreviewError` naming the movie and the reason; the temp file is removed and the original is untouched.
- **`live_codec.py`** gains two readers, `movie_timing` (timescale, stts totals, and the video edit list's entries and duration) and `movie_geometry` (sample-entry size and depth, plus the tkhd matrix). They are built on `_probe_video_trak`, `_mdhd_timescale` and `_stts_totals`.

**Changes in `hp`:**
- **`apply_preview`:** after `manifest_from_export` and before `write_manifest`, set `manifest["movieConversion"] = convert_movies(html, manifest["slides"], log=log)`. The manifest stays the commit point. On failure, the existing `except` deletes the export.
- **`load_cached`:** also returns None when any referenced video file is not H.264 (`preview_movies.unconverted(html, slides)`). Effects:
  - An old cache that holds ProRes or HEVC re-exports once (Minimal).
  - An all-H.264 cache is reused (Alpha_DSK).
  - `MANIFEST_VERSION`, `PARSER_VERSION`, `RENDERER_CONTRACT_VERSION` and the `-p3-r1` key stay, so fixture paths are unchanged.
- **Imports:** import `preview_movies` inside these two functions. `lc` imports `hp` (`lc:30`), so a top-level import would be circular.
- **Not touched:** the `.key`, Keynote, `main.js` (so `SUPPORTED_PLAYERS` and `playerDigest` still hold), slide JSON, and file names. The trim suffix and `_TRIM_SUFFIX_RE` canonical keys are unchanged, so `derive_plan` reads identical inputs and the continuity plan is byte-identical before and after conversion.
- **Claims and disk:**
  - Conversion runs inside the existing export window. `claim_export` is unchanged (`hp:823-837,932`).
  - Disk use falls for ProRes and roughly doubles for HEVC. There is one temp file at a time, and a full disk fails closed.

**UI.** The qualification response carries `convertedMovies`, built from `result.manifest.movieConversion` and deduplicated by asset. The prepare panel says "Converted 3 movies to H.264 for playback: untitled.mov (HEVC), …". This replaces the "may not play" warning, which is now empty for every prepared deck.

**Rejected:**
- Converting at host start: minutes of work just before the show, and it would touch gate fixtures.
- Upgrading old caches in place: a second code path for a one-time event. The cost of the chosen path is one Keynote export per old non-H.264 cache (owner's go). Neither path is safer for a live session: `export_html` deletes the old tree first (`hp:769-770`), the existing hazard in §9.
- `h264_videotoolbox`: faster, but the owner approved libx264 crf quality, the same encoder as the DSK converter.
- Flattening alpha onto black: the owner said refuse, never silently flatten.
- A manifest version bump: it would force a Keynote re-export of every cached deck, while the content check re-exports only the ones that need it.

### 2.2 The host codec gate stays
`host:101-111,852-866,883-893` stay as they are. After C1, every movie in a prepared deck is H.264, or the prepare was refused. So the deck-wide codec gate can no longer fire from the dashboard; it remains as defence for direct `LiveOutputHost` runs (probe, fixtures). Rejected: scoping it per movie, because no reachable case remains.

## 3. Part 2: partial continuity

### 3.1 Classification of every deck-wide refusal
**Becomes scoped.** The affected entries become `retire refused` with a named reason. There is one new code, **R11** ("unmeasured export shape"); its reason text names the exact check.

| Site | Where | Stage C scope |
|---|---|---|
| A movie layer outside the measured vocabulary: possible mask or unrecognised encoding; rotation, affine or anchor; ≠1 video sub-layer; animated geometry; not contained; unreadable rect; unmeasured `loopMode` (Back and Forth) | `_slide_movie_instances` (`lc:1382-1388`); raised in `lc:1054-1176,1359-1367`; returned at `lc:1858-1859` | **That asset, at the Magic Moves into and out of that slide.** Every readable outgoing instance gets R11. The unmeasured instance gets a refusal *record* only: no runtime entry, it is never carried and plays raw. |
| Destination draw order unreadable for one carry | `_draw_slots`/`_movie_slot_index`/`_overlap_refusal` (`lc:1198,1207,1213,1225,1237,1247`), reached through `_carry_refusal` (`lc:1732`), returned at `lc:1904-1905` | That (boundary, instance): R11 |
| Unmeasured transition kind (anything but Magic Move, Dissolve, none), or an unreadable transition name | `lc:1893-1894,1903` | **No decoder is held into it.** Every pin, bridge or glReplay carry *into* the slide whose outgoing transition is unmeasured gets R11 ("the next transition '<name>' is unmeasured") at that earlier boundary, a measured retire at a Magic Move (D6 S4→S5 shape). The unmeasured boundary itself then has no entries: nothing is held (a Dissolve `restart` holds only through its own transition), and every movie plays as the export plays it. Rejected: retiring held decoders *at* the unmeasured transition. `markTransition` is transition-agnostic (`js:779-786`), but a hand-back against Push, Cube and the other renderers is unmeasured, and S3's gate would put it live without a probe. |
| A bridge with no positive duration | fails deck-wide in `to_runtime` (`lc:887-888`); R10 skips it (`lc:1587-1589`) | That carry: R10 at derivation |

**Stays deck-wide.** Continuity goes off; the deck still plays, and the reason is shown.

| Site | Where | Why it stays deck-wide |
|---|---|---|
| Unreadable header, slide list or slide JSON; no events | `lc:1827,1836,1839,1851,1853` | The scene indices of later slides cannot be known |
| Movie node without an asset id or objectID | `lc:1378,1381` | objectID-only identity cannot name it |
| R5 | `lc:1866` | The identity premise itself fails |
| More than one transition on a slide; R3 | `lc:1425,1427` | The `atScene` convention is unproven for that deck; never observed (S0 V2) |
| "More than one movie changes geometry" | `lc:1779-1780` | Stage B deletes it; C leaves it alone |
| `to_runtime`: no boundaries, missing scene, unnamed instance, more than one glReplay, R6, allowlist | `lc:802,811,870,881,821,824,832` | Integrity checks (a failure is a derivation bug), or binary by design (the allowlist until S3) |
| glReplay entry errors | `lc:909-918` | Flag-on only, and they already fall back to the flag-off derivation (`host:910-912`, `wl:72-73`) |
| Host: stage gate, runtime install, codec gate, `OBED_LIVE_CONTINUITY=off` | `host:941-993`, §2.2 | Runtime-level |

**Allowlisted plans stay byte-identical.** Every scoped site used to return `Unsupported`, so any deck that derives today never reaches the new branches.

**Code shape (`lc` only):**
- `_Slide` gains `unmeasured: {asset: [(objectId, reason)]}`.
- `_slide_movie_instances` catches `_Refuse` per movie node, for the shape checks only.
- `_magic_move_movies` gets an unmeasured-asset branch before pairing, and a `try/except _Refuse` around `_carry_refusal` that turns it into R11.
- `derive_plan` reads every slide's outgoing transition in a pre-pass (the deck-wide R3/multi-transition refusals keep their behaviour). `_magic_move_movies` R11-refuses each carry whose destination's outgoing transition is unmeasured, and an unmeasured boundary appends an empty movie list.
- `derive_plan` merges the record-only refusals into `refusals`.
- R5 also counts objectIDs of unmeasured instances.
- `slide_instances`, `slide_rects` and `loop_instances` leave out unmeasured instances, because their rect cannot be trusted.

### 3.2 Runtime safety without any JS change
- **No new plan shapes.** A scoped plan uses only entry kinds the core already runs: per-instance `retire refused`, carries before and after it, and `retire ends`. Schema 2 is unchanged and there are no new keys. Every R11 retire sits at a Magic Move boundary, and no held decoder ever meets an unmeasured transition (§3.1).
- **Unmeasured instances play untouched.** No entry names them, so they are never pooled (`poolable`, `js:761-764`), like D5's unplanned movies. A GL replay `instanceId` index cannot shift from leaving them out of `slide_instances`, because their whole asset is refused at both of that slide's Magic Moves.
- **A retire touches only its own instance:**
  - It acts only on decoders stamped with its `src` (`zoneVictims`, `js:1583-1593`).
  - It opens at the transition once the player has torn the instance down, or at `atScene` (`js:445-450`).
  - It hands back a held decoder at the transition start (`markTransition`, `js:779-786`) or via the sweep (`js:1566-1577`).
  - It needs no end (`js:443`).
  - A decoder is pooled only when its instance's next entry is a carry (`poolable`, `js:761-764`).
- **R6 still runs on the final entry list** (`lc:932-958`), and any broken chain turns continuity off for the deck. Scoping only removes carries, or ends them with a retire that names the held instance, so every carried `dst` is still continued or ended.
- **Held decoder across a refused boundary.** D6 S4→S5 (an R4 retire of a held pin) passed Q3, Q5 and Q7 in S2. Node coverage: `tests/test_live_continuity_js.py:1436` (retired at teardown or by the sweep) and `:1855` (a retire leaves other movies alone).
- **A chain that starts after a refusal.** P2 (retire@2, restart@6, bridge@8; Q2), plus Node `:1559` and `:1583`.
- **Go-to.** `clear()` drops the pool and the held set for each generation, and Pass G passed on P2 and D1–D6. The rule that a refusal lasts until the next go-to (`refusedAt` per generation, `js:358-363`) is unchanged.
- **Loop.** The per-entry `loop` and the `loopMismatch` check are unchanged.
- **Conclusion:** the core does not change, so nothing needs re-qualifying (§6).

### 3.3 Dashboard. Recommendation: never gate start on continuity, and show it instead
**`wl`:**
- Delete the start gate (`:261-263`).
- `_deck_qualification` returns a `continuity` object instead of a blocking reason:
  - `off` when the env switch is set;
  - `unsupported` with its reason;
  - `qualified` with `notCarried`, from `host.not_carried(plan, slides)`. That function is extracted from `host:920-939`, and the host keeps calling it.
- The playability checks in `prepared_deck` still block: player digest, 16:9, manual mode, web video, no slides (`wl:106-128`).

**`LP`:**
- **Start:** enabled for any prepared, playable deck (`:78,284`).
- **Prepare panel:** "Deck ready", then one continuity line:
  - on;
  - on, with N moves not carried, listed as "Slide 6 → 8 · vid-20250608-wa0125.mp4 · <reason>";
  - off for this deck, with the reason;
  - plus the converted-movies note from §2.1.
- **Session badge:** "On" (with "· N not carried"), or "Off for this deck".
- **Not-carried lines:** they name the movie (`:31`), and entries beyond 3 go into an expandable list.
- **Copy:** rewrite the allowlist wording at `:313` and README:58-63.

Rejected: keeping the gate with an override button. The owner said never block.

### 3.4 How S3 fits in, and the order
- **Partial continuity is invisible on real decks until S3.** The allowlist is binary per deck, so every deck not on it reports continuity off until S3 deletes it.
- **Un-gating start pays off on its own.** Alpha_DSK and Minimal start today with continuity off instead of being refused.
- **S3 is not needed for C to be correct.** C does change S3's inputs: the negative corpus gains R11, and C's tests are those entries. OQ-8 (iv) is already met by Alpha_DSK "with named refusals" (4× `overlap`).
- **Recommended order: C (WS M, S and U in parallel) → S3 → B.**
  - C and S3 are Python and TypeScript only, with no JS bytes, so neither needs re-qualification. **Cost:** S3 still has its own gate (the probe on P2 and D1–D6 with S2-equal verdicts, plus the real-deck dry run), so this order runs one more headless probe round than B → S3, where S3 reuses B's round (Stage B §6).
  - After S3, Alpha_DSK carries its 3→4 move and names its 4 `overlap` moves.
  - B then adds carries under artwork, with its own full re-qualification.
  - Stage B §6 put B first so that S3's corpus would match B's code set. That costs at most one corpus entry here: write S3's `overlap` entry on a click-driven destination, which B still refuses. The one-bridge guard is deck-wide, not a code. See **OQ-C2**.
- **If B is approved first and already in flight:** run WS M and WS U beside it. They share no files with B except README/SKILL and the re-pin lines in `tests/test_live_host.py`. Hold WS S until B merges.
- **Notes for B:** its Alpha_DSK fixture and expected plan must come from the new export, which adds a boundary and is converted by C1. After S3 there is no allowlist, so B's regression oracle becomes the plan-sha tests (the probe's `DECK_PLAN_SHA256`, the P2 plan-sha tests) passing unedited, and its gate commit registers no allowlist entries. B's WS D rebases onto C's `_magic_move_movies`/`_carry_refusal` edits.

## 4. Tests: the fewest new tests for the most coverage
**WS M**
1. New `tests/test_preview_movies.py` (real bundled ffmpeg; lavfi clips at 320×180, at most 30 frames, under 1 s each): `test_converts_every_non_h264_copy_in_place_with_identical_timing`. The tree holds:
   - ProRes LT with AAC, in two slide folders with identical `mdat` and different `mvhd` timestamps (Keynote's copies);
   - HEVC with a 90° matrix at timescale 30, cut by stream copy so its edit list skips samples;
   - ProRes 4444 with constant alpha 255 (Keynote's case);
   - one H.264 file.

   Asserts:
   - names are unchanged and every file is `avc1`;
   - presented duration, timescale, coded size and matrix equal the source's;
   - the H.264 file is byte-identical and not recorded;
   - the ProRes pair is encoded once (`st_nlink == 2`);
   - the record has the contract fields.
2. Same file: `test_refuses_by_name_and_leaves_the_export_untouched`, parametrised over real alpha, odd width, and a dropped frame (a monkeypatched argv adds `-frames:v`). Asserts: the `PreviewError` names the asset, every original sha256 is unchanged, and no temp file is left.
3. `tests/test_html_preview.py`: `test_apply_records_conversions_and_reuse_needs_h264`. A fake export with one ProRes movie: `apply` records 1 entry; `propose` then reuses the cache without calling `convert_movies`; putting a ProRes file back makes `load_cached` return None. Existing tests are untouched, because the fake export has no movies.

**WS S** (`tests/test_live_continuity.py`)

4. Move the shape parameters of `test_refuses_the_deck` (`:358`: transform and draw-slot cases) and the mask, clipping and malformed tests (`:1366-1545`) onto one helper. It asserts:
   - the plan derives;
   - the affected asset's boundaries hold `retire` R11 with today's reason text;
   - every other boundary equals the unmutated plan's.

   This is mostly a helper edit (`_mask_reason_plan` returns the R11 reason).
5. `test_a_mask_object_on_the_bridge_movie_cannot_qualify` (`:1373`) keeps its safety claim in scoped form: with the signature check monkeypatched out, no pin, bridge or glReplay entry names the masked instance.
6. Flip `:3717` and `:2989` (unknown or unreadable transition): the carry into that slide retires with R11, the unmeasured boundary has no entries, and every other boundary is unchanged. Flip `:559`: R10 now refuses at derivation.

   **Regression oracle, left unedited:** the allowlist and plan-sha tests (`:1070,1863,2653,3115,3130`), `tests/test_live_continuity_decks.py`, and the D-deck shas.

**WS U**

7. Flip `tests/test_live_api.py:681,694,707`:
   - the new qualification shape;
   - a continuity `Unsupported` never blocks start, under `auto` or `off`;
   - `notCarried` and `convertedMovies` are reported.
8. Flip `dashboard/tests-ui/live-presenter.ui.test.tsx:618`: a deck with continuity off starts and shows the reason. Also check that the not-carried line names the movie (`:181`) and that the converted note appears.

## 5. Frozen contract (set before the streams launch)
1. **`manifest.movieConversion`** (optional; absent means nothing was converted):
   - `encoder`: `"libx264 crf14 fast yuv420p; aac 192k"`;
   - `converted`: a list of entries, each with `path`, `asset`, `sourceCodec`, `sourceSha256`, `sha256` and `bytes`.
2. **`preview_movies` functions:**
   - `convert_movies(export_root, slides, *, log) -> dict`, which raises `PreviewError` naming every refused asset;
   - `unconverted(export_root, slides) -> list[str]`.

   `lc._referenced_movies` keeps its signature.
3. **Refusal code `R11`.** Records use the existing `refusals` keys. A record's `objectId` may name an instance that has no runtime entry.
4. **`live_host.not_carried(plan, slides) -> list[dict]`**, returning today's keys.
5. **Qualification response:**
   - `previewJobId`, `name`, `sourceDigest`, `slides`;
   - `qualified: true` (the deck is playable);
   - `continuity: {mode: "qualified" | "unsupported" | "off", reason, notCarried}`;
   - `convertedMovies: [{asset, sourceCodec}]`.

## 6. Gates
**No re-qualification is needed:**
- C changes no byte of `PRESERVE_CORE_JS` (`PINNED_CORE_SHA256`, `tests/test_live_continuity_js.py:34`), of G2 (`10a5b36a…`), of the `live_runtime` player patches, or of the injected plan script.
- Every gate deck's runtime plan stays byte-identical: the allowlist and plan-sha tests pass unedited.
- Gate fixtures never pass through `apply_preview`.
- So the rule "any core byte change re-opens Q2–Q6" is not triggered. The only runtime-visible change is movie bytes in dashboard-prepared caches, converted to libx264 High with B-frames and AAC. That is not the gate fixtures' shape (Baseline, no B-frames, no audio, `binary_counter_movie.py:106-108`), but it is the shape of Alpha_DSK's `untitled-h264.mov`, which S3's real-deck probe carries at 3→4. G4 covers playback before then.

| G | Run | Pass | When |
|---|---|---|---|
| G1 | `uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps` | Green, with the oracle tests unedited | Machine free |
| G2 | `convert_movies` on a copy of the Minimal Alpha_DSK export in a scratch preview root | 3 encodes (6 + 2 + 2 copies, grouped by media data), every check passes, wall time recorded; `derive_plan` on the copy equals the original (`as_dict()` and `refusals`) | Offline (ffmpeg) |
| G3 | Same on Alpha_DSK (`3b9019f0…`) | No-op, `converted: []` | Offline |
| G4 | Smoke test, not a re-qualification: headless `LiveOutputHost` on the converted copy, stepping through every slide; then start Alpha_DSK through the API | Every `<video>` has no `error`, `readyState ≥ 2`, and `currentTime` advances; Alpha_DSK starts with continuity `unsupported` (allowlist) and its reason, and no 409 | Chrome free |
| G5 | Owner prepares the new Alpha_DSK in the dashboard (Keynote export; owner's go). Its last slide has two stacked ProRes LT 3840×1080 clips. | "Converted 2 movies to H.264"; encode time logged; by eye, in screen output and in the Keyer output (the first real-deck Keyer run with no continuity script injected; transparency then comes only from `host:423-430`), the two clips play one after the other | Owner |

After S3 (outside C): the probe on the partial Alpha_DSK plan, plus the owner's eye.

## 7. Work streams (Opus MEDIUM, disjoint files, one message; then one Astra/Codex review of the combined diff)

| WS | Files (exclusive) | Work |
|---|---|---|
| M | new `src/obed_edom/preview_movies.py`, `src/obed_edom/live_codec.py`, `src/obed_edom/html_preview.py`, new `tests/test_preview_movies.py`, `tests/test_html_preview.py`, `tests/test_live_codec.py` | §2.1; tests 1–3 |
| S | `src/obed_edom/live_continuity.py`, `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py` (only if needed) | §3.1; tests 4–6 |
| U | `src/obed_edom/web/live.py`, `src/obed_edom/live_host.py` (`not_carried` extraction only), `tests/test_live_api.py`, `tests/test_live_host.py`, `dashboard/src/live/{api.ts,LivePresenter.tsx,live.css}`, `dashboard/tests-ui/live-presenter.ui.test.tsx` | §3.3 plus the converted note; tests 7–8 |
| P | `README.md` (live section, codec report, refusal codes, "never transcoded"), `.agents/skills/obed-edom/SKILL.md` (contract: R11; scoping is not relaxing; the deck-wide list), the handover (open item 4 superseded) | Docs |

## 8. Owner questions (recommendation first)
1. **OQ-C1: a movie with real transparency, or an HEVC movie whose transparency cannot be read.**
   - **Recommended (a):** the prepare fails, naming each such movie and the fix ("replace it with an opaque movie"). Web video already blocks a deck the same way (`wl:126-127`).
   - (b) The prepare succeeds, but that movie stays as it is and is listed as "will not play in this output".
2. **OQ-C2: order.**
   - **Recommended:** C → S3 → B (§3.4). Real decks get partial continuity after two cheap stages, and B re-qualifies on its own schedule. It costs one extra headless probe round (S3's own gate).
   - Alternative: B → S3, as in Stage B §6: S3 reuses B's round, and real decks wait for B's re-qualification.

## 9. Residuals (to go in the README)
- H.264 High 10 or 4:2:2 passes through unconverted, and Chrome cannot decode it. Add a profile check if one ever appears.
- HDR HEVC (PQ/HLG) becomes 8-bit SDR without tone mapping.
- Encoding runs at about realtime at 3840×1080, so long clips add minutes to a prepare.
- Movies with odd dimensions are refused.
- There is a quality-generation loss at crf 14 (visually transparent: crf 16 measured 45–46 dB average PSNR). Audio is re-encoded to AAC 192k (live output is muted anyway).
- `slide_instances` leaves out R11 instances, so the probe's stray check would flag them; no gate deck has one.
- Two concurrent prepares of the same deck can make each other fail. This fails closed: the manifest is written last, and reuse requires H.264.
- Re-preparing a deck while a live session serves its cache is an existing hazard. C makes it reachable once more per old non-H.264 cache (its first re-prepare re-exports).
- A carry into a slide whose outgoing transition is unmeasured is refused (R11), so that slide restarts its movie where it might have carried.
