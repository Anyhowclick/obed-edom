# DSK — the single plan of record

Supersedes `dsk_generator`, `dsk_content_rules`, `dsk_mint_media_style`, `dsk_pieceD`,
`dsk_pieceD1b`, `dsk_pieceD2b`, `dsk_layout_milestone`, `dsk_layout_split_engine`,
`dsk_template_style`, `dsk_d6_dashboard`, the `cue_palette_and_dsk_generator` DSK
placeholder, and every review/brief under `.agents/reviews/dsk-d4b|dsk-layout` and
`.agents/briefs/dsk-d4b`. Only still-live insight, numbers and TODOs are kept.

## 1. Status

- SHIPPED: FW(7680×1080)→DSK(1920×1080) image/movie path — `dsk-assemble --content-only`
  (skips `SlideClass.is_text` slides), `dsk-export-clips` (FW-only), `dsk-export-stages`
  (any 1920×1080 deck), `/api/dsk` + `/api/dsk/export` propose→decisions→apply, DSK tab
  with Generator/Exporter sub-tabs. P7 live acceptance PASS 2026-09-15 (GW 21,24,32,33,48).
- BENCHED (owner pivot 2026-09-15, "bench the verse/text resizing, ship image/video first"):
  layouts L1–L4, split engine S1–S5, refit, D1/D1b grouped + two-column text, style pass,
  pill pass. All landed in-branch and tested; not exercised by the shipped `--content-only` path.
- Branch `feat/dsk-gen`, draft PR #72, squashed to b519f58 + follow-ups; pre-squash history
  at tag `backup/feat-dsk-gen-pre-squash-2026-09-15`; merged with `main` 2026-09-15 (0 behind).
  Suite after the merge: 3487 passed / 87 skipped / 1 xfailed / 3 failed (the 3 are main's own
  pre-existing maps failures).
- Deliverable contract: an EDITABLE DSK deck (operator finishes crops by hand) plus a flat
  PP7 asset folder; never a finished deck.

## 2. Contract / rules of record (owner decisions, each still governing)

- 2026-09-10: scratch deck is 3840×1080; export at `movie format:native size` (not the 1080p
  preset); downscale afterwards in ffmpeg/geometry.
- 2026-09-10: PP7 assets need TRUE ALPHA and a `built` slide is ONE asset per build step
  ("on-click per animation"); built slides ALSO stay live in the DSK deck for editing.
- 2026-09-10: alpha route (iii) Keynote-native stage PNGs ships first (it automates today's
  manual practice); (ii) KPF/Chromium is the strategic route shared with the alpha-playback
  app; (iv) difference matte is a demoted fallback. Movie slides always take the opaque path.
- 2026-09-10: off-canvas framing (GW 32's 3840×2160 movie at y=−763) is intentional; the
  scratch export bakes the crop.
- 2026-09-10: scale-only is the agreed contract — copy the image with its existing mask and
  scale; editorial cropping stays operator work. No new crops are created by geometry.
- 2026-09-10: border is house white `TSDSolidPattern` 5.0 pt, but the PRIMARY rule is KEEP
  THE SOURCE OBJECT'S STROKE; grant white 5 pt only where the source has none.
- 2026-09-10: inserted clips copy the FW movie's `repetition method` and `movie volume`
  ("keep to source deck behaviour"); the DSK deck never holds the original FW movie.
- 2026-09-10: stat overlay is BAKED into the clip by default, with a per-slide "clip only" choice.
- 2026-09-10: primary output is a NEW DSK deck; verse slides are produced manually for now;
  insert mode (d7) stays a stretch.
- 2026-09-10 (Q6, STILL OPEN external dependency): the DSK template SHOULD carry a real band
  placeholder — needs church staff. Until then the measured band is the default placeholder.
- 2026-09-11: a text slide = some kept text item (or group DFS child join) with >10 words
  (`--text-slide-words`); a text slide drops every kept image/movie.
- 2026-09-11: an image's DSK content is a cropped FILE (PIL crop + live re-insert), never a
  mask write; L/R mirror duplicates keep the survivor with the LOWEST `kindIndex`.
- 2026-09-11: a text slide that will not fit the band SPLITS into N DSK slides, one box per
  slide; never split a box mid-text.
- 2026-09-12: placement is by SHAPE, not count — auto anchor from the UNION of kept content
  rects clipped to the centre panel: union aspect ≥ 2.5 → centre; else 1–2 items → right
  (flush to `band.x_max`), ≥3 → centre. Explicit `--anchor` always wins.
- 2026-09-12: content = what is inside the 3840×1080 LW centre-panel framing; side-panel items
  are dropped by default with a per-slide `keepSideContent` toggle (resizer semantics: never
  carried forward by reuse, positional not by kind); layout-owned media is never content.
- Rotated: a rotated top-level image/movie is anchored from its exact transformed AABB; a
  rotated GROUP is refused (its group-union geometry is invalid for anchoring).
- 2026-09-14: GW 5 drops the photo (group-child verse makes it a text slide).
- 2026-09-14 (Q1): keep D1b's single-slide hand two-column (gold 29/30/34); do NOT adopt the
  template's `Num Point with Verse-Pre/-Post` split.
- 2026-09-14 (Q1 D1b): repeated headings are DROPPED — suppression requires the immediate
  non-empty predecessor to be itself heading+verse with identical heading text (a heading-only
  predecessor, e.g. GW 45 before GW 46, does NOT suppress).
- 2026-09-14 (Q2): a verse needing >3 lines SPLITS into two or more slides against the slot's
  own budget; never hand-place a 267-tall panel.
- 2026-09-14 (Q3): KEEP connection-line arrows — move them offline after the live pass with the
  sibling group's affine (geometry-only write preserves builds); refuse only if the slide's
  text would need resizing (character/line builds die on a size write).
- 2026-09-14: emphasis runs are CAPPED at gold's 50 pt on a 45 pt lead (do not carry the
  source 85/70 ratio).
- 2026-09-15: DSK style comes from the TEMPLATE via an offline `DocumentStylesheet.iwa` patch —
  white title-case badge (`kNoCaps`) on the rose pill, version suffix shown verbatim when the
  source carries one (no NIV synthesis, no `•` tagline), gold-yellow verse numbers
  `(0.99942404, 0.9855537, 0.0)`, emphasis left as `ArgentCF-Bold` yellow ≤50 pt. The
  point-column ref badge keeps CYAN but has its caps cleared.
- 2026-09-15 (d6 Q1): text slides are skipped SILENTLY — a log line per slide is enough.
- 2026-09-15 (d6 Q2): deck at `output/<FW stem>/dsk/<stem>_DSK.key`; clips, crops and stage
  PNGs go in ONE FLAT folder beside it, named to sort in slide/stage order.
- 2026-09-15 (d6 Q3): the Exporter runs stage PNGs on ANY 1920×1080 DSK deck (hand-built
  included); clip export stays FW-deck-only and the UI must say so.
- 2026-09-16 (owner, after viewing the real output of `DSK_Gen_Export_Input.key` slides 11–13,
  mixed movie + overlay + magic-move slides): a mixed slide stays ONE self-contained opaque
  clip with overlays and builds baked in and the magic move dropped; PP7 dissolves between
  clips. "Overlays live in the DSK deck over a bare clip, Keynote does the transitions" is
  the target only once Keynote alpha output exists (§4 item 21, `.agents/research/
  kpf_renderer_probe_2026-09-12.md`). `SlideDecision.overlay_bake` stays an unused field
  until then.
- 2026-09-16 (owner, after the r15 deck review): process is GENERATE → operator edits the live
  objects in the DSK deck → EXPORT. Each FW movie item becomes its own PURE-VIDEO clip (only
  that movie rendered, cropped to its rect ∩ centre panel) inserted at that item's fitted rect
  through the same affine as every other copied object, BEHIND the live overlays. Scale stays
  per slide (the source authors different sizes across a magic-move chain); consecutive FW
  slides linked by an outgoing magic move share the chain head's auto anchor (explicit anchor
  still wins). Clip slides get a DISSOLVE (interim: the Keynote-alpha work may later retain
  source transitions). The Generator's clips are intermediates under `output/<FW stem>/dsk/src/`
  (`<DSK stem>.NNN.MM.src.mov`), listed as `srcClips` in `manifest.json`; the Exporter ALWAYS
  re-renders movie/mixed slides (never reuses) and deletes the `src/` intermediates after a
  successful run. The DSK deck is retained. Supersedes the "one baked clip" rule above and the
  #138 reuse rule.
- Keynote hands-off rule: work on a copy under `~/Desktop` or repo `output/` (never
  `/private/tmp`), one Keynote automation at a time, back up and quit the owner's documents.
- Owner's open design item besides the band placeholder: the "editing phase" (d6b) — per-slide
  operator nudges of position/size/crop over the auto defaults — is explicitly out of scope.
- 2026-09-17 (owner, clip start timing + visual order — validated against the gold
  `Alpha_DSK.key` slides 6–8): every consumer orders a slide's movie items by VISUAL order
  (left-to-right by placed x, then y; refuse on an exact tie) via
  `dsk_movie_export.visual_movie_order`. That one order drives the clip index MM in
  `<stem>.NNN.MM(.src).mov`, the ClipResult / manifest `srcClips` order, the insertion order,
  and the build-chunk order; the publisher takes it from the assembler's `clips_inserted`,
  never recomputed from crop rects. Clip start timing is written OFFLINE (Keynote's auto
  movie-start timing is non-deterministic and AppleScript has no build API), keyed by the
  SOURCE movie's `playsAcrossSlides`: the leftmost continuity clip is After Transition at
  build-chunk position 0 (`automatic True, referent True, delay 0`), other continuity clips are
  With Build 1 (`automatic True, referent False`), distinct movies cascade After Previous in
  visual order, and a single-movie slide is After Transition. `playsAcrossSlides` is written
  False on every inserted clip; chunk `duration` is Keynote's own and is never touched. A clip
  slide is expected to carry only movie-start build chunks (the gold's overlays are static); a
  non-movie build chunk, a missing/duplicate/extra timing entry, an unknown mode, or more than
  one After Transition is REFUSED, never guessed.

## 3. Measured facts that must not be re-learned

- Keynote's movie insert is ASPECT-LOCKED: writing position, then width, then height re-derives
  the unwritten dimension from the media aspect and the growth goes rightwards (r15: requested
  622×350 came out 1244×350). Write size first, position LAST; the requested rect must match
  the clip media aspect (`clip_sizes` guard ±0.5%).
- `make new image/movie … with properties {file:…}` lands at the FRONT of `drawablesZOrder`;
  nothing raises the copied objects afterwards. `_restore_clip_zorder` (modelled on
  `_restore_crop_zorder`) moves inserted `TSD.MovieArchive` objects to the back offline.
- r15 (2026-09-16): the copied overlay objects on FW 12/13 were placed correctly (centre); the
  misplacement was the whole-panel clip sitting at ONE movie item's fitted rect.

### Band and slots
- Band (read from the hand-built DSK reference, `dsk_assemble.DEFAULT_BAND`):
  bottom 1054.0, height 350.0, x 43.0…1892.0, width 1849, sample_count 4. `read_band` skips
  `skipped` slides and backdrops/invisible items (that is why sample_count is 4, not 7, and
  x_max is 1892 = slide 32's 1516+376; the earlier x_min 26 was wrong).
- A full-wall (7680) union is width-bound at s = 1849/7680 ≈ 0.2408 → h ≈ 260.0 (not 263).
- GW 32's 3840×2160 movie at (1920,−763) fits from its VISIBLE rect to
  x ≈ 345.3, y 704.0, w ≈ 1244.4, h 350.0 (height-bound). The naive `band_h/src_h` is 2× wrong.
- Layout slot table (`dsk_assemble.LAYOUT_SLOTS`, re-measured from the template):
  - `Verse Standard (Variation 2)`: verse 53.6/866.4/1799.0×177.0 @45 pt left; badge
    63.1/785.8/933.1×82.1 @40 pt; pill 50.4/789.1; panel 25.5/840.4/1869×213 (inherited).
  - `Verse 1 Line (Variation 2)`: verse 53.6/967.0/1812.9×73.0 @45 pt; badge 63.1/878.4/945.9×77.0;
    pill 50.4/879.1; panel height 120.
  - `Point 3 Lines`: text 53.6/860.9/1812.9×177.0 @45 pt CENTRE; panel 213.
  - `Point (2 Lines)`: text 53.6/886.9/1812.9×177.0 @45 pt CENTRE; panel 163.
- Gold verse text is TOP-anchored (`kFrameAlignTop`) at the slot's own y on 1-, 2- and 3-line
  slides alike; raw stored height 0.0 with `naturalSize = (w, 177.0)`. Parts get slot x/w +
  `position = (slot.x, slot.y)`, no height write.
- D1b two-column constants (from gold 29/30/34): `HEADING_COL_W` 450.0, `COL_GUTTER` 8.0,
  `NUMBER_BADGE_PT` 46.0, `MAX_HEADING_PT` 80.0, `MAX_HEADING_BLOCK_PT` 140.0; left column
  [43, 493] centred on 268.0, right column [501, 1892] width 1391; badge x 245.0 is the
  load-bearing gold hit. Heading pt = `min(80, largest s with n_lines×1.157×s ≤ 140)`.
  Left block is vertically CENTRED on the right block (deltas ±14 pt vs ±51 pt bottom-aligned).
- Heading-only gold slides are 60 pt FLAT with a 46 pt badge; 2-line headings put the badge
  above centred on x=960, 1-line inline-left (pair centred on 960 either way).

### Pill mask law (`dsk_pill.write_pills`)
- The pill image drawable's own geometry NEVER varies with width (byte-identical across all 8
  measured widths); only the mask moves. Mask right edge pinned at **1832.5315**, `position.y`
  **50.9344**, `size.height` **75.52111**, `pathsource.scalarPathSource.naturalSize` tracks the
  mask size with constant `scalar` (corner radius) **15.0**, path type `kTSDRoundedRectangle`.
  Frame x 50.4, y 789.1 (standard) / 879.1 (1-line); pill data id 27859, natural 1887×136, 180°.
- Width law: `mask width = iwa_text_shape.shaped_width(badge string, AzoSans-Bold 40pt) +
  VERSE_BADGE_PAD_PT 54.85` (mean over gold 3/5/9/35/38, stdev 1.06). Gold 20 excluded (its
  badge text is itself a content defect); gold 23 keeps a genuine ~11 pt residual.
- `shaped_width` has no capitalization input, so the law is the TITLE-CASE law — leaving
  `kAllCaps` set makes the drawn pill under-run the rendered badge by 11–63 pt.
- Reuse requires the candidate to carry the layout pill's COMPLETE fingerprint and to own its
  mask exclusively (mask in the same member, `mask.super.parent == image`, no other image
  references it); a bare data-id match is not enough (gold 9/20/23/38 carry untagged overrides).
- Minting a pill must register the new ids in the SLIDE's own metadata component:
  `objectUuidMapEntries`, `dataReferences` per data id, and an `externalReferences` entry for a
  cross-member style id — discovered by diffing a real gold slide, documented nowhere else.

### Stylesheet
- A colour lives TWICE in `charProperties`: `fontColor` AND `tsdFill.color`. Keynote treats
  `tsdFill.color` as authoritative and resyncs `fontColor` from it on save — patch BOTH or the
  change reverts (measured: p2 round 1 reverted, round 2 passed). Readers must read `tsdFill.color`.
- `capitalization` is a paragraph-style property on the badge box (the badge carries NO
  `tableCharStyle` entries) and is in the AppleScript sdef gap — offline-only.
- Anonymous per-size paragraph-style variations are REGENERATED with new ids on save
  (17646732 → 17654928); never key verification off a style id across a save.
- Slot paragraph metrics: verse `TATvalue0` (left) / `kFrameAlignTop` / lineSpacing 0.8 /
  padding 4.0; badge `TATvalue0` / `kFrameAlignMiddle` / lineSpacing 0.9 / padding 4.0. Output
  boxes inherit padding 1.0 and sometimes `TATvalue2` from the wall — there is NO measured write
  path for paragraph alignment anywhere in `src/`.
- Style targeting is BY BOX ID (`plan.slot_badge_ids`), never by property predicate — a
  predicate over-reaches onto the point column. Refuse when a style's referrer set escapes the
  verse badges rather than recolouring shared refs.
- Minting a retained-object-specific media style (`iwa_write.mint_media_style`): a Keynote
  variation carries ONLY the overridden property, `overrideCount: 1`, header
  `objectReferences: [parent]`; register in the stylesheet root's `styles` and
  `parentToChildrenStyleMap` but NOT `identifierToStyleMap` and NOT the root header's
  `objectReferences`. New id = `Metadata.iwa` `lastObjectIdentifier` + 1 (a true high-water mark).

### Keynote scripting (learned here; AppleScript/sdef)
- `position` IS the live visual TOP-LEFT of an autosize box — no alignment compensation is ever
  needed (the r12 "+h/2" fix was wrong and was reverted).
- Every width / text-size write RE-AUTOSIZES around the centre and moves `y`, so the POSITION
  WRITE MUST BE LAST: emit `width → size/run sizes → character deletes → position`, height
  omitted for autosize text. `set height` on an autosize box is a no-op Keynote overrides on save.
- `delete characters` on a `kFrameAlignTop` box shrinks height with `position` y unchanged
  (385 → 281 → 177 on GW 38); deletes go tail-then-head, indexed against the pre-delete text.
- `size of object text` on a mixed-run box reports the SMALLEST run — a live read-back is not a
  size authority. The live `height of` read is the FRAME height pass 1 wrote, stale against the
  text's laid-out height, and stays stale across a poll, a re-read and a close+reopen.
- The TRUTH is the saved archive's `naturalSize` (offline read of the staging deck). Stacked
  boxes legitimately appear in `payload["_offline"]["soft_geometry"]` — that must NOT gate the read.
- A group resize is an aspect-locked scale that freezes an autosize child; groups are written
  CHILD BY CHILD, never resized as a group. There is no `ungroup` verb; in-place child
  addressing (`text item k of group g of slide N`) is the only route.
- Deleting an object removes its builds with it; `restore_source_builds` REFUSES on differing
  slide sets, so it is never used — `iwa_builds.verify_builds` is a CHECK (missing tolerated,
  surplus is the failure).
- `set base layout of slide N` PREPENDS the layout's materialized slot instances (verse text,
  badge text, pill image) ahead of the slide's real content, shifting every index — delete the
  text/image delta from the front immediately after each `set base layout`, before any other
  per-slide statement, and error by name if the counts do not return.
- Layout import via donor-slide `move` DEDUPES BY NAME, case-insensitively — importing `Blank`
  silently resolves to the deck's own opaque layout. Import `Blank Black` specifically and run
  the offline full-canvas-drawable gate on the RESOLVED layout.
- The 7680→1920 canvas width write scales all content ×0.25 — geometry lands within 1 pt, but
  STROKE WIDTH scales too (1.0 → 0.25). The stroke gate decides by PATTERN: `TSDEmptyPattern` →
  grant house white 5 pt; a real pattern → restore the pre-shrink width.
- The same resize scales IMPORTED LAYOUT artwork ×0.25 about the final canvas centre (960, 540)
  (x' = 0.25x + 720, y' = 0.25y + 405 — the mid-canvas "dark bar" of r13); slide content is
  re-positioned by explicit writes, layout drawables are not → resize the canvas BEFORE
  importing/assigning layouts (measured 2026-09-15, fixed).
- Canvas groups must be processed WIDEST-FIRST (document width only shrinks between exports).
  Slide addressing after a deletion uses POST-DELETION ordinals.
- `.mov` is REJECTED as an export destination (error `".mov" (6)`); export to `.m4v`, remux
  after. ProRes cannot be stream-copied into the `.m4v`/ipod muxer.
- `all stages:true` is honoured by the SLIDE-IMAGES exporter (RGBA PNGs with real alpha) and
  inert for the QUICKTIME exporter. Keynote's own ProRes 4444 export allocates `yuva444p12le`
  but fills alpha with a constant 255 — assert alpha STATISTICS, never `pix_fmt`.
- Stage PNGs are `<basename>.NNN.png`, flat 1-based across the whole export — attribution is
  DERIVED (`stage_count(slide) = build_count(slide) + 1` over non-skipped slides in order) and
  a count mismatch must REFUSE, never guess.
- Slide/document background is NOT scriptable (-1700); `base layout` is. `skipped` is rw, so
  per-slide export is a `skipped` toggle plus `skipped slides:false`.
- A locked display stalls the exporter (208 s vs 11 s); `caffeinate -dimsu` is insufficient —
  poke the display (`caffeinate -u -t 2`). Sandboxed shells cannot launch Keynote.
- Two concurrent Keynote scripts collide destructively; hold an `fcntl.flock` for the batch.
  Detect the process by `CFBundleExecutable` (`Keynote`), not the app name.
- Peak RSS: 1.18–1.41 GB on a 242 MB deck, 1.83–2.3 GB on the 669 MB GW deck; watchdog default
  3.0 GB. `-600` = Keynote not running; `-1712` = AppleEvent timeout (retry re-copies the
  pristine scratch, so NEVER retry a pass ≥ 2 — it would run against an unwritten deck).
- Keynote does NOT purge unreferenced `Data/` on save: the DSK output was 94.7% of the 669 MB
  source. *File → Reduce File Size* is GUI-only; it stays an operator step.
- Movie timing is not scriptable: 5.0 s per-slide hold and 2.0 s build delay are Keynote's
  self-playing defaults with no export keys. Build cuts are deterministic (frames 0–60
  byte-identical hold, first change at frame 61 / t = 2.033).

### Reader / offline facts
- `_compose_record` returns the MASK AABB for image/movie, so payload item rects are VISIBLE
  rects, not frames. `naturalSize` = media pixel size, `originalSize` = unmasked frame in
  points, mask is frame-local. PIL agrees with `naturalSize` exactly (EXIF orientation absent
  or 1) — its failure is the signal for a rotated asset.
- `Data/` members carry a Keynote suffix (`…-76510.jpeg`); the crop planner needs the reverse
  map (`data_member_index`), which `_build_data_index` throws away.
- Rotated payload contract: `x`/`y` are the ROTATED frame's AABB top-left, `w`/`h` are the
  UNROTATED size. Derive only the extents (`w' = |w·cosθ|+|h·sinθ|`), never re-rotate `x`/`y`
  (that error was off by (300,−300) on the worked 400×1000 @ (2220,0) rot-90 case). Snap
  exact multiples of 90° to a swap/no-op — float residue reads 400.00000000000006.
- `GroupChildId = ("groupchild", group_ki, child_kind, child_kindIndex)` — the kind is
  load-bearing, since `kindIndex` is per-kind INSIDE the group and a text-bearing shape consumes
  both counters. A dual `text`+`shape` child is labelled `shape`; fixed-frame long grouped text
  is REFUSED (no `set height` emission exists for a stacked child).
- `build_identity` is content-keyed — `(kind, normalised text)` for text/shape, `(kind,
  fileName)` for image/movie — so builds survive duplication and kindIndex shifts but NOT a
  delete-and-reinsert of media. A group build's identity embeds its children's text, so a split
  part's clone narrows to a contiguous SLICE of the source identity.
- `duplicateOf` badge twin: the verse badge is a matched top-level text+shape pair; the badge
  predicate requires that match (a lone extra text is ambiguous and must not be taken).
- `_staged_id_for` / `_staged_kind_ranks` invert staged→source indexes; a HIDDEN (undeletable)
  placeholder still occupies a slot, so `retained = (fits − deleted) | (deleted & hidden)`.
- `TSD.ConnectionLineArchive` is absent from `KIND_ORDER`, so `deck_builds` drops its builds;
  `dsk_plan` counts them as `connection_line_builds` and folds them into `build_count`
  unconditionally as centre content. GW payload 7 carries 2 free-standing curved arrows.
- Layout alpha is decided by a FULL-CANVAS DRAWABLE on the layout, never by
  `slideProperties.fill`/`backgroundIsNoFillOrColorFillWithAlpha`. `Blank Black` has zero
  drawables → transparent; every `Blank`/`BLANK` in all three probed decks is opaque.
- `_WRAP_MARGIN = 0.02` (wrap at `width × 0.98`) — the smallest margin clearing every measured
  box; below it GW 17 text:2 and GW 28 text:1 under-predict by a full line.
- The wrap estimator errs BOTH ways by up to ~36 pt (half a line): it plans windows, it is not
  the authority. `h = Σ 1.157 × max_size_per_line + 21` (padding); it over-predicts headings
  (159.84 vs Keynote's measured 130).

### Clip / export facts
- Never resize the scratch document: the canvas resize scales all content ×0.5 and re-centres
  vertically (+270), which the wall-point `dx` translate did not account for — that is the
  "coal slide" bug. Always export at the source wall size and ffmpeg-crop
  (`crop = CENTRE_PANEL_RECT`, or `visible_union(include_side=True)`).
- Strip every non-content drawable from the scratch slide before exporting (side panels leaked
  a hard-edged 960×540 purple rectangle into the GW 32 clip); a black base layout removes only
  layout art.
- A published clip is content + 5.0 s hold + the outgoing transition (movie slides: movie
  length + 5.63 s). Movie slides get transition `no transition effect` — the clip owns timing.
- A live `make new image with properties {file: …mov}` DOES create a movie object; Keynote sets
  `naturalSize` to the media pixel size and `originalSize` to the requested frame, with no mask,
  and copies the file into `Data/` itself — so a replaced image needs NO IWA media write.
- Stage export needs an alpha-safe base layout (`verify_staged_layouts_alpha_safe`); `--layout
  preserve` risks opaque PNGs. `d5` does NOT rewrite `base layout`.
- Builds cannot be CREATED (`plan_build_patch` only subsets, the sdef has no build class) —
  hence copy-and-transform, never build-from-template. Character-level builds
  (`apple:dissolve character`, ` word` suffixes, `KLNSparkle`) DIE on a size write, so a split
  box carrying one is refused; whole-object and group builds survive size writes and are cloned
  per part (tolerated surplus exactly `len(parts) − 1`).
- ProRes 422HQ at 3840×1080/30 is ~5 GB per 30 s — default `AppleProRes422LT` or h264.
  `native size` is required for any codec choice to apply. 7680×1080 exports fine; behaviour
  above 2160 height is UNVERIFIED — assert and refuse on tall canvases.
- Build-chunk flag encoding (read offline from `Alpha_DSK.key` slides 6–8 and the r16 generated
  deck): a `KN.BuildChunkArchive`'s `automatic False, referent True` = On Click; `automatic
  True, referent True` at `buildChunks` position 0 = After Transition, at pos>0 = After Build N;
  `automatic True, referent False` = With Build N; `delay` is seconds. On both the hand-made
  gold and the generator output, overlay shapes carry NO build chunks (static), so every
  clip-slide build chunk is a movie-start and the leftmost clip's chunk sits at position 0
  naturally. The offline writer `iwa_movies.patch_clip_start_timing` front-loads the planned
  movie chunks and reads back `(automatic, referent, delay, chunkPos, playsAcrossSlides)` per
  movie, refusing on mismatch.

## 4. Open bugs / TODOs

### Shipped path (blocking polish)
1. FIXED + LIVE-VERIFIED 2026-09-16 (r14): propose quits the Keynote it launched for preview
   export (`_dsk_preview_thumbs`, both Generator and Exporter); a Keynote the operator already
   had open is left alone. Exporter propose → `pgrep -x Keynote` empty → apply 200 (no 409);
   Generator propose on GW 21,24 likewise. Evidence `~/Desktop/dsk-d4-work/evidence-r14/`
   (server.out, manifest.json; export job f6106641, generator job bc071de3).
2. FIXED + LIVE-VERIFIED 2026-09-16 (r14): the Exporter writes stage PNGs beside the deck it
   exports (`path.parent`). For a generated deck that is the flat asset folder
   `output/<FW stem>/dsk/` next to the `.mov` clips (owner Q2); for a hand-built deck it is
   the deck's own folder, so run it on a copy in a scratch folder.
3. DONE 2026-09-16 (r14, owner Q3): Exporter run on a copy of
   `Sermon_PK (DSK)_with mistakes.key` (slides 1–3 → 1 and 3 exported, 2 empty). Both PNGs
   1920×1080 RGBA, `alpha_ok`, `bg_alpha_max` 0, peak RSS 0.82 GB. Source fingerprint unchanged.
4. DONE 2026-09-16 (r14): UI clicked through in the in-app browser — Exporter propose → Export
   → JobName rename, and Generator propose review table. Not clicked: Generator apply (P7
   covered it via the API). Observation: the JobName edit committed on blur, not on the
   automated Enter keypress; unconfirmed whether a real keyboard Enter commits (shared
   component, not DSK-specific).
5. FIXED 2026-09-16: both DSK sub-tabs render `JobName` with rename wiring (live-verified r14).
6. FIXED 2026-09-16: `assemble_dsk_deck(content_only=True, …)` refuses `text_fit="shrink"`,
   a non-default `min_text_pt`, `allow_split=False` and `split_overrides`, matching the CLI.
7a. LIVE-VERIFIED 2026-09-16 (r16, PR #143 + #148) on `DSK_Gen_Export_Input.key` 11–13 (14-slide
   revision: FW 12 now one movie, FW 13 two): Generator made 4 pure per-movie clips into
   `src/`, assembled 3 slides in 287 s (peak RSS 2.0 GB); offline read-back: slide 3's two
   clips at x 345 and 968 (622 wide each, centred band), every inserted movie at the BACK of
   `drawablesZOrder`, 0.5 s dissolve on all clip slides, builds intact, slides 12/13 share
   the chain anchor. Exporter re-rendered 3 clips in 61 s and deleted the 4 intermediates;
   manifest carries `clip` + `source_slide` only. Keynote quit itself after every step.
   Found live: `locked of group N` raises -1728 on this Keynote build (fix #148). Evidence
   `~/Desktop/dsk-d4-work/evidence-r16/`.
7. LIVE-VERIFIED 2026-09-16 (r15, PR #138 + #140): the two-batch Generator job (clip export
   then assemble) on `DSK_Gen_Export_Input.key` 11–13 with the "Blank Black" alias; the
   Exporter's `isStageDeck` gate, its `.mov` path on the hand-built deck (slide 13 → 53 s
   ProRes), and Generator-clip reuse (3 reused, 0 exported, manifest byte-identical).
   Evidence `~/Desktop/dsk-d4-work/evidence-r15/`.

### Benched path (before the verse/text work resumes)
8. **Pill z-order fix is live-unverified.**
9. **GW 44/50 heading heights vs the D1b rects** — Keynote lays a 60 pt two-line heading at 130,
   the estimator predicts 159.84 (+23%); recalibrate before trusting heading budgets.
10. **Two-column badge sits above the panel** — D1b rect y 719.4 vs panel top 840.
11. **Point-layout ordinals are verified against the D1b PLAN rects, not the slot table**
    (temporary, logged as such). L5 must reconcile the two.
12. **FIXED 2026-09-17** (Codex L3 review 5, both gaps): the generic multi-box slot split and the
    one-part fallback now go through `_slot_one_part_fit`, which builds the 50pt-capped `Run`
    objects once and uses them for BOTH the wrap height and the emitted sizes, gating through
    `_pack_split_lines`'s own ≤3-line/`_SPLIT_TOL` budget (not a raw height compare); a box whose
    capped 45pt text still exceeds the slot REFUSES rather than shrinking below the slot lead;
    `SplitPart` gained per-part `scale`+`slot_capped` so the `--text-fit shrink` refit uses the
    part's own scale and preserves the 50pt cap. Claude high-effort was not used; Claude planned,
    Sonnet implemented, GPT-5.6 Sol r1/r2 under `.agents/reviews/dsk-split-cap/`. (a) MAJOR latent
    emphasis-cap/scale gap + (b) MINOR one-part height both closed; offline only, full suite green.
13. **C5: split is never re-run after a refit** — a part's geometry is corrected, never
    re-windowed live; enforced explicitly in `_build_refit_round`.
14. **Fixed-frame grouped text is refused, not supported** — needs `set height` emission for a
    non-autosize stacked child and a real deck to test against (none exists in GW).
15. **L5 not started** — heading-only (60 pt flat, 46 pt badge) and point classes; drop the
    retired 0.75 badge scale; recalibrate `wrapped_height` for headings (159.84 → ~130) WITHOUT
    touching the size-chooser rule `n_lines × 1.157 × s ≤ 140`, which reproduces gold exactly.
16. **L6 not started** — connection lines: add `TSD.ConnectionLineArchive` to `iwa_kindindex`,
    dedupe the GW 7 +2446.70 mirror pair, and move the 2 arrows offline with the sibling group's
    affine (owner decision: keep, do not refuse). Payload 7 also carries a `LineDraw` build.
17. **Legacy non-slot placement is still bottom-stacked** — top anchoring is gated on a
    selected/recorded slot layout.
18. **`dsk-export-clips` still calls `visible_union`/`classify_deck` with DEFAULT
    dedupe/backdrop flags**, so it disagrees with a `dsk-assemble --no-dedupe` run on two flags.
19. **Native mask crop is impossible today** (no sdef mask property) — a mask-authoring
    workstream gated on `OBED_OFFLINE_WRITE` if the owner ever funds it.
20. **d6b editing phase** — per-slide operator nudges need (a) an override map threaded through
    `plan_assembly` → `build_assembly_script`, (b) a canvas-accurate browser preview, (c) a
    persistence story like `framing.save_framings`. Its own plan.
21. **d5c KPF alpha pipeline** — export → strip the lead fill op in `global/shared.pdf` → patch
    the two black body styles → drive the player (`jumpToSlide(`, `advanceToNextBuild(`) →
    per-build capture → ProRes 4444, plus a fidelity report against `deck_builds`. Playwright
    pinned as an optional extra. Caveats: KPF exports movies separately; a full-bleed background
    stays opaque after the strip; the player simplifies unsupported builds.
22. **d7 insert mode** (stretch) — `--dsk-existing`; reuse `MapsTab`'s drag interaction
    (`:752-789`) and `moveSlideTo`'s index math, NOT `MapsDocument`.
23. **d8 maps reuse** — point `maps_keynote.dsk_ops`/`dsk_item` at the shared crop utility
    (today it SCALES the panel ×0.5 to the bottom half, it does not mask); then hand the Maps
    DSK deck to the Exporter rather than growing a second export path.
24. **Both exporters share the placeholder-materialisation exposure** — UNMEASURED: only the
    assembly path deletes the prepended slot instances after `set base layout`.
25. **`Full_Report_Card_Wall.key` (6.7 GB, 155 slides) is still unmeasured** for whole-deck live work.
26. **`saveToken` and the minted media style's inherited picture `frame`** are open questions on
    `mint_media_style` — no offline evidence either way.
27. **Joint slot fit shrinks a too-long verse instead of splitting** (owner-banked 2026-09-17, from
    the item-12 Codex r2). The JOINT slot candidate is measured with UNCAPPED runs (`~:1838/:1877`),
    so a natural over-long verse fits jointly at a tiny scale and takes the shrink path (`~:1924`)
    rather than splitting: natural GW17 (no `--split`) emits stack_t 0.39 → 27.3pt lead / 33.1pt
    emphasis, never reaching the item-12 multi-box split. This means the §2:67 "a verse needing >3
    lines SPLITS" rule is not honoured for natural content — the fix landed in item 12 only bites
    forced (`--split`) splits. Next slice: cap the joint-fit measurement and route a failed joint
    slot candidate to per-box splitting (slot-authoritative 45pt) instead of `fit_text_stack`; it
    moves the acceptance decks and needs a live text run. Pre-existing; beyond item 12's scope.

## 5. Live-run recipe

1. Run from the pinned detached worktree `.claude/worktrees/dsk-gen` (branch `feat/dsk-gen`);
   always `PYTHONPATH=src` with the repo `.venv`.
2. Use the unsandboxed launcher — a sandboxed shell cannot start Keynote.
3. `pgrep -x Keynote` must be empty; quit and back up the owner's open documents first.
4. Work on a FRESH PRISTINE COPY of the GW deck under `~/Desktop/dsk-d<N>-work/` — never
   `/private/tmp`, never the owner's deck; verify the source fingerprint afterwards.
5. `--rss-limit-gb 4` (measured peaks 1.83–2.3 GB on the 669 MB deck); the machine stays
   hands-off for the whole window.
6. Launch with `nohup … &` and follow the log with Monitor — background Bash caps at 10 minutes.
7. Read back with `~/Desktop/dsk-d4-work/accept13.py [out_key] [evidence_dir] [--slides …]`;
   it asserts the GW→ordinal map rather than deriving it, then cross-checks against the output
   deck's own slide count and each split's part count — a disagreement FAILs loudly.
8. Evidence goes to `~/Desktop/dsk-d4-work/evidence-r<N>/` (`run.out`, `png/`, `acceptance<N>.csv`).
9. On refusal the staged deck is kept as `<out>.refused.key` (`.failed.key` for a non-refusal
   exception); `out_path` is never written with an unverified deck.
10. Cleanup rule: delete superseded work decks and evidence dirs once the next round supersedes
    them (each GW copy is ~670 MB and each output ~1.7 GB).
11. Pure-clip round is DASHBOARD-driven (not the CLI in item 1): start the dashboard UNSANDBOXED
    with `PYTHONPATH=<detached-worktree>/src <repo>/.venv/bin/python -m obed_edom dashboard
    --no-browser` (the `.venv` editable-installs from the MAIN checkout, so the PYTHONPATH
    override is required to exercise the worktree's code; the framework python3 lacks cv2). Drive
    the HTTP API: `POST /api/dsk` (propose) → `/api/dsk/<id>/apply` (generate; writes the offline
    clip timing) → `POST /api/dsk/export` → `/api/dsk/export/<id>/apply` (renders final clips).
    Poll `GET /api/jobs/<id>`.
12. KEYNOTE NEW-PRESENTATION DIALOG (found live r17, this "Keynote Creator Studio" build): every
    Keynote launch pops a theme/new-presentation chooser that BLOCKS the automation AND the quit —
    it caused a ~38-min preview hang and a reproducible "Keynote is already running (strictly
    serial)" refusal (the intermediate export's Keynote never quit). Fix: Keynote → Settings →
    General → "For New Documents: Use theme <specific>" so no dialog pops; otherwise dismiss it
    each launch. This is an environment/harness issue, not a code bug.
13. Clip-timing acceptance = build-chunk inspection of the generated DSK deck, then re-inspect
    after the Export's Keynote round-trip and confirm IDENTICAL: per clip slide exactly one
    `apple:movie-start` per clip, leftmost After Transition at `buildChunks[0]` (automatic True,
    referent True, delay 0), others With Build 1 (True, False, 0), `playsAcrossSlides` False. Live
    r17 (2026-09-17, PR #151) PASSED on `DSK_Gen_Export_Input.key` 11–13; evidence
    `~/Desktop/dsk-d4-work/evidence-r17/`.

## 6. Test gates

- `tests/test_dsk_assemble.py` 455 (9 deck-marked), `test_dsk_plan.py` 127,
  `test_dsk_movie_export.py` 105, `test_dsk_pill.py` 53, `test_dsk_stage_export.py` 52,
  `test_iwa_write_mint_media_style.py` 50, `test_dsk_content_rules_acceptance.py` 21 (all
  deck-marked), `test_dsk_live.py` 20, `test_dsk_style.py` 13, `test_dsk_dashboard_api.py` 10,
  `test_dsk_content_only.py` 5. Full suite 2715 passed / 86 skipped / 1 xfailed at c749cb9.
- Deck-marked tests skip when `~/Desktop/Diff-Checker/Sermon_PK (GW).key` /
  `Sermon_PK (DSK)_with mistakes.key` are absent; they are the only tests that read a real deck.
- `tests/test_dsk_assemble.py`'s `no_keynote` fixture forbids `subprocess.run`/`Popen` — every
  offline test must run under it so no Keynote process can start in CI.
- Dashboard tests use the repo's compile-and-`require` pattern
  (`dashboard/tests/*.test.cjs`, `npm run test:maps`); there is NO Vitest and no `tests-ui/` in
  this worktree. `cd dashboard && npm install && npm run build` (includes `tsc --noEmit`) after
  any `dashboard/src/**` change.
- Acceptance scripts live OUTSIDE the repo under `~/Desktop/dsk-d4-work/`: `accept9.py`,
  `accept11b.py`, `accept11p.py`, `accept12.py`, `accept13.py` (current; CSV
  `check,expected,actual,result`).
