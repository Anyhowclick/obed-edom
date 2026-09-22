# DSK — the single plan of record

Supersedes `dsk_generator`, `dsk_content_rules`, `dsk_mint_media_style`, `dsk_pieceD`,
`dsk_pieceD1b`, `dsk_pieceD2b`, `dsk_layout_milestone`, `dsk_layout_split_engine`,
`dsk_template_style`, `dsk_d6_dashboard`, the `cue_palette_and_dsk_generator` DSK
placeholder, and every review/brief under `.agents/reviews/dsk-d4b|dsk-layout` and
`.agents/briefs/dsk-d4b`. Only still-live insight, numbers and TODOs are kept.

## 1. Status

- SHIPPED + merged to main: the FW(7680×1080)→DSK(1920×1080) image/movie path — `dsk-assemble
  --content-only` (skips `SlideClass.is_text`), `dsk-export-clips`, `dsk-export-stages`, the
  `/api/dsk` + `/api/dsk/export` propose→decisions→apply flow, and the DSK tab (Generator/Exporter
  sub-tabs). Plus pure per-movie clips behind live overlays, clip START timing written offline, and
  visual-order clip naming (contract in §2/§3). Live-verified P7 → r17 (movie chain end to end).
- ACTIVE (verse/text resumed 2026-09-17): the resizing engine (layouts L1–L4, split S1–S5, refit,
  D1/D1b two-column, style, pill) — code-complete + offline-tested + wired via `content_only=False`;
  the shipped call passes `content_only=True` so text slides are pre-filtered. §4 item 12 (multi-box
  split cap) merged; item 8 (pill z-order, LIVE-BROKEN in text-r1) + item 27 (joint-fit
  split-vs-shrink) are the open next slices.
- APPROVED FOR IMPLEMENTATION (2026-09-21): replace the Generator's grouped table with the
  composition editor specified in §4 "Dashboard composition editor" — source-order slide rail,
  16:9 output preview, compact inspector, explicit global/per-composition geometry, dashboard video
  masks, and Magic Move sequence folding. The approved visual prototype is
  `/Users/anyhowclick/.codex/visualizations/2026/09/21/01a0c358-4d90-7fc2-a893-0019fea75835/dsk-generator-mockup.html`.
- Deliverable contract: an EDITABLE DSK deck (operator finishes crops by hand) plus a flat
  PP7 asset folder; never a finished deck. (Merged-PR history + suite counts live in Git, not here.)

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
- 2026-09-19 (owner, Generator review step — LIVE-VERIFIED r18 2026-09-20, PR #176, on
  `claude/dsk-generator-alignment-options-97c5aa`): each slide takes an explicit left / centre /
  right alignment (the existing `anchor`, with bulk controls), and a slide with kept top-level
  movies may be set **videos only**: every non-movie object is dropped and the movie(s) are fitted
  to the STANDARD video band instead of `DEFAULT_BAND`, auto-anchored centre (no content/chain-head
  anchor). Movies STACKED on one another in the source (dissolving over each other; FRC Wall slide
  50) follow the SOURCE BUILD ORDER, not visual order; a pair counts as stacked only when its
  intersection covers more than `dsk_movie_export._MOVIE_STACK_OVERLAP` (owner, 2026-09-20: 0.9) of
  the smaller VISIBLE rect's area. The review list follows the CG resizer's
  classification flow (grouped by category, bulk per group).
- Keynote hands-off rule: work on a copy under `~/Desktop` or repo `output/` (never
  `/private/tmp`), one Keynote automation at a time, back up and quit the owner's documents.
- 2026-09-21 (owner, approved Generator redesign): the former out-of-scope "editing phase" is now
  IN SCOPE for content slides. The dashboard owns global width/height + alignment defaults,
  per-composition size/alignment overrides, an aspect-ratio lock, and per-video pan/zoom masks.
  Placement stays lower-third-only: vertical position is fixed to the safe baseline and horizontal
  movement snaps to left / centre / right. Source order is preserved; there is no reorder feature.
- 2026-09-21 (owner, UI vocabulary): the visible review controls are Include, left/centre/right
  alignment glyphs, size, Full slide / Video only, and LW / FW. `keepSide` remains an internal
  compatibility field only: LW means centre-wall crop (`keepSide=False`), FW means full-wall crop
  (`keepSide=True`). Category appears only as the slide-rail section heading; slide number and
  `action` are not operator controls. Movie clips are extracted from the source deck; the new UI has
  no manual clip picker.
- 2026-09-21 (owner, preview/masking): the preview is a real 1920x1080 coordinate space scaled into
  a 16:9 viewport. It shows final pixel dimensions at the content frame's top-left and resizes from
  the top-right. For a video mask, the frame stays fixed while the original video pans/zooms below
  it. Keynote has no live video-mask primitive, so the Generator bakes this crop into the pure-video
  intermediate; the inserted DSK clip remains editable for outer position/size.
- 2026-09-21 (owner, FRC Wall 108–110): a consecutive Magic Move sequence that builds a 1→2→3
  video composition is ONE review composition and ONE DSK slide. The terminal source slide supplies
  the final layout/static overlays; the chain supplies the union of movie assets; all three inserted
  clips start together. Identity and poster substitution must be proved from source/archive evidence,
  never guessed from filenames or visual proximity. An ambiguous chain stays explicit and warns.
- 2026-09-21 (owner, FRC Wall slide 50): 100%-overlap movies stay fully overlapped in the review
  preview and output. The frontend must not auto-tile or separate them. It exposes the ordered media
  layers for selection/mask editing while the existing backend source build order, dissolve and delay
  remain authoritative. Simultaneous timing is only for an explicitly qualified folded sequence.
- 2026-09-22 (owner, Alpha_Wall slides 2-4 and 7; live-verified): a group's children map through the
  SAME affine as the group's own fit -- from the group's VISIBLE origin (payload rect ∩ wall_rect),
  never its raw origin (the raw origin shifted children by the clipped overhang and turned the 3→4
  Magic Move downward). Axis-aligned dividers are trimmed along their own axis to the extent of
  their group level's non-line content (gold Alpha_DSK 9/10: divider = image height). A group
  caption writes at least 35 pt (`MIN_CAPTION_PT`, gold slide 10); its pill (smallest containing
  shape, clipped to the source canvas) and its text box grow by the same factor from the pill's
  top-left. Top-level lines/shapes/text rotated 90 deg write their UNROTATED width/height.
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

- STANDARD video band (measured 2026-09-20 from the hand-made gold `Alpha_DSK.key` slide 4, a
  3840×1080 centre-panel clip at (258, 670) 1405×395): bottom 1065.0, height 395.0, centred on 960
  → `dsk_assemble.STANDARD_VIDEO_BAND` = `Band(1065, 395, 43, 1877, 1)`; x margins SYMMETRIC about
  960 (DEFAULT_BAND's 43…1892 centres on 967.5 and would land the clip 7.5 pt right of gold)
  (UNMEASURED for left/right — gold 6/7/10 sit at x 198/181/181 with overlays; owner to confirm).
  Gold 16:9 clips keep the same ~1065–1066 bottom (slides 7–9) at hand-picked heights 327–463.
- FRC Wall slide 50 (stacked-movie reference): two 3840×2160 movies on the centre panel — movie 0
  (1920, −1079) `apple:movie-start` chunkOrder 0 referent True; movie 1 (1915, −163)
  `apple:dissolve` In chunkOrder 1 referent False; class `mixed`, 4 side `map BG.png` dropped.
  Visual order would put movie 1 first (x 1915 < 1920) — hence build order for overlapping movies.
  Clipped to the centre panel the VISIBLE rects are (1920, 0, 3840, 1080) and (1920, 0, 3835, 1080):
  the intersection is 100% of the smaller (movie 1 is 5 px narrower INSIDE movie 0), so slide 50
  clears the 0.9 stack threshold with room to spare. The FULL item rects only overlap ~0.58 —
  the mode is decided on the visible rects, never the item rects.
  Archive diff (offline, 2026-09-20): the two `KN.BuildArchive`s are IDENTICAL except
  `attributes.animationAttributes.effect` (`apple:movie-start` vs `apple:dissolve`) and the random
  seed — same `animationType In`, `duration 0.5`, `delivery All at Once`, `eventTrigger 1`. Movie
  1's chunk is `automatic True, referent False, delay 8.0` (With Build 1, 8 s after movie 0
  starts). So a build-in is a ONE-FIELD effect rewrite of the clip's auto movie-start build plus
  the source chunk `delay` — no build creation needed (unverified live).

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
- Peak RSS: 1.18–1.41 GB on a 242 MB deck, 1.83–2.3 GB on the 669 MB GW deck, **3.21 GB on the
  6.7 GB FRC Wall deck (r18, 2-slide generate; its export 1.50 GB)**; watchdog default 3.0 GB —
  the FRC deck BREACHES it, so launch the dashboard with `OBED_DSK_RSS_LIMIT_GB=8` (r18 used 8 on
  a 17 GB machine). A breach now names itself in the job error. `-600` = Keynote not running; `-1712` = AppleEvent timeout (retry re-copies the
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

### Dashboard composition editor — APPROVED 2026-09-21

**Implementation status (2026-09-21): COMPLETE OFFLINE.** UI, v2 review/compiler, occurrence-based
movie export, uniform assembly placement, source-mode filtering, optimistic concurrency, atomic
apply, and manifest provenance are implemented and covered by the gates below. A production
Keynote run remains a separate owner-supervised acceptance step because it opens the 6.7 GB deck.

#### Product surface

- Replace `dashboard/src/tabs/dsk/SlideReviewList.tsx` with a three-part
  `DskReviewWorkspace`: a source-order `SlideRail`, a 16:9 `OutputPreview`, and a compact
  `SlideInspector`. Ship only the approved focused-rail + inspector variants (prototype A+B); do
  not build the discarded third variant.
- The rail preserves GLOBAL source order. It inserts Movie / Mixed / Built / Static headings for
  contiguous category runs (a heading may therefore repeat); it never buckets/sorts all cards by
  category and never reorders them. A card shows its thumbnail, Include state, and meaningful
  media/build badges; category, action, and source slide numbers stay out of the normal operator
  surface.
- The preview is the editing surface. It uses one conversion between DOM pixels and the canonical
  1920x1080 output coordinates, supports pointer capture, snaps horizontal dragging to the three
  anchors, exposes a top-right resize handle, and shows the effective `W × H px` at top-left.
  Keyboard buttons/arrow nudges must provide the same operations without dragging.
- The inspector starts with Include, then compact Position and Size sections, then Full slide /
  Video only and colour-distinct LW / FW segmented controls. The mask section appears only for a
  mask-capable movie composition; a multi-movie composition adds an ordered media selector. A
  `mediaLayout=stacked` composition renders those layers at their overlapping slots (including 100%
  overlap) and selection edits one layer without moving the others. Use small accessible CSS
  alignment glyphs rather than adding an icon dependency solely for alignment.
- Give the global-default row a distinct tinted surface. It owns width, height, aspect lock and
  default alignment. A composition stores `inherit` until the operator overrides it; Reset deletes
  that override, so later global changes continue to flow through. Seed new jobs with 935×263,
  centre, ratio locked; keep the seed in one product constant.
- Keep live pointer edits local. Persist on pointer-up, debounce typed fields/toggles, and flush the
  latest state synchronously before Generate. Never POST on every pointer-move.

#### One deep review model

- Add a backend composition-planning seam (target module `src/obed_edom/dsk_review.py`) between raw
  deck inspection and both the HTTP/UI and apply phases. The UI must not infer sequences, media
  identity, export capability, or Keynote semantics. One inspection produces TWO explicit models:
  (1) the operator-facing ordered review compositions and prepared preview layers, and (2) a
  validated `CompiledComposition` consumed by export/assembly. The latter is the only place that
  resolves inherited defaults and source occurrences into concrete canvas geometry.
- Add schema version 2 rather than growing the current `{slide, include, action, anchor,
  keepSide, clip, videosOnly}` row. Read version-1 stored jobs through a one-way compatibility
  adapter; new saves emit version 2 only. Keep legacy names at the assembler boundary, not in the
  React model.
- A review payload owns one global `defaults` record and ordered `compositions`. A composition has a
  stable opaque `id`, `sourceSlides`, one `layoutSlide`, category/thumbnail/capability metadata,
  `mediaLayout` (`spatial|stacked`), ordered media descriptors, warnings, and one operator decision.
  Every media descriptor declares `sourceModes` (`lw`, `fw`, or both), so switching source view
  never exports a side-only occurrence into LW and never omits an FW-only occurrence.
  Layer order is source visual/build order as already resolved by the backend. Single-slide ids may be
  `slide:<n>`; folded ids may be `sequence:<first>-<last>`. Source order is the payload order, so no
  position/order field exists.
- The operator decision contains `include`, `alignment` (`inherit|left|centre|right`), nullable
  frame override `{width,height,aspectLocked}`, `source` (`lw|fw`), `contentMode`
  (`full|video`), and per-media mask overrides. A mask stores the fixed output frame and the media
  transform below it (`scale`, `offsetX`, `offsetY`) keyed by stable media id.
- Give each authored media occurrence a stable id from source slide + archive drawable id, and
  expose its embedded asset id separately. Never deduplicate occurrences by asset: two authored
  copies of the same movie are two media placements. `(kind, kindIndex)` remains an internal
  per-slide address only and cannot identify media across a Magic Move chain.
- `CompiledComposition` contains its id/source slides/layout slide/resolved output frame, the
  terminal slide used for copied overlays, and ordered explicit media placements. Each placement
  carries occurrence id, source slide + source item/archive address, asset id, target rect,
  viewport transform, style/playback provenance and requested timing. Earlier-slide media are
  exported from their actual source occurrence and inserted at their explicit target rect; they are
  never fabricated as terminal-slide `ItemId`s.
- Frozen pipeline boundary (names may map to dataclasses, semantics may not drift):
  `CompiledComposition{id, source_slides, layout_slide, overlay_slide, output_frame, alignment,
  source_mode, content_mode, media}` and
  `CompiledMedia{occurrence_id, source_slide, source_item, archive_id, asset_id, target_rect,
  viewport, playback, timing, preserve_stroke}`. `output_frame`/`target_rect` are 1920×1080 canvas
  pixels; `viewport` is the normalized zoom/pan contract below; `source_item` addresses the real
  occurrence on the real source slide. For terminal-slide media, assembly replaces the review's
  preview slot with the authoritative uniform `fit_slide` result for the resolved output frame, so
  movie clips and retained live overlays share one affine. Review JSON and compiled dataclasses have
  separate types.
- Bind every proposal to the existing source-deck digest/fingerprint. Save/apply refuses when the
  source changed. Decisions carry a monotonically increasing revision; saves are serialized and a
  stale `baseRevision` gets 409 rather than overwriting newer state.
- Frozen v2 write envelope: decisions POST
  `{review:{schemaVersion:2,sourceFingerprint,defaults,decisions:[...]},baseRevision}`; Apply accepts
  that same editable review plus `baseRevision` and `exportDir` atomically. A decision is keyed by
  composition `id` and contains editable fields only; source slides/media/layout/preview metadata
  remain server-authoritative. Responses carry the incremented revision. Version 1 keeps its
  existing `{decisions:[...]}` path.
- Duplicate API type declarations in `dashboard/src/api.ts` and `dashboard/src/dsk/decisions.ts`
  must collapse to one exported frontend contract and one pure reducer/selector module. The reducer
  owns selection, inheritance, reset, ratio math, mask edits and serialization; React components
  only render and dispatch.

#### Geometry and apply

- Extend the assembly decision with an explicit output VIEWPORT rather than mutating the global
  `DEFAULT_BAND` / `STANDARD_VIDEO_BAND`. Freeze one editor safe area for both sides of the contract:
  output 1920×1080, x 43…1877 and bottom 1065. The backend returns these bounds; the frontend never
  re-declares them. Left/right snap to those x edges and centre is geometric canvas centre.
- Width/height are the exact viewport bounds in canonical output units, not a promise to distort the
  contents to that aspect. Content always uses the existing uniform affine: full-slide content fits
  inside the viewport without stretching, and video fills its mask by crop/cover. Ratio lock is
  persisted editor behaviour; unlocked editing changes the viewport aspect only. The pixel chip
  labels the viewport. Non-uniform object distortion is explicitly out of scope for this slice.
- Media slots are composition-local normalized rects. A mask override is `{zoom, panX, panY}`:
  `zoom >= 1` multiplies the slot's aspect-fill scale; `panX/panY` are normalized −1…1 positions
  across the available post-zoom overflow (0 centred, ±1 clamped to an edge). Resizing/re-aligning
  the outer viewport therefore preserves the crop. Source/content switches retain an occurrence's
  mask only while that occurrence/capability remains valid, then re-clamp it; otherwise reset it
  with a visible warning.
- Keep current source behaviour behind the new names: `source=lw` clips/classifies against
  `CENTRE_PANEL_RECT`; `source=fw` includes the whole 7680×1080 wall. `contentMode=video` keeps the
  existing top-level-movie capability gate. Reject impossible or out-of-bounds frames in the review
  validator before Keynote launches.
- Extend `dsk_movie_export.export_slide_clips` with an explicit per-movie crop/viewport plan. Apply
  the dashboard mask on the scratch copy, export one isolated movie, and crop the resulting pure
  video to the mask frame. Preserve trim/playback, repetition, volume, visual/build order and the
  existing rollback/publish guarantees. Do not pretend the output Keynote contains a live video
  mask.
- The manifest stays keyed by DSK ordinal and records `composition_id`, `source_slides`,
  `layout_slide`, resolved frame, occurrence/media provenance, mask and published clip order.
  Preserve the ACTUAL existing compatibility field `source_slide=layout_slide` and ordered
  `srcClips`. Generator regeneration overwrites or removes all prior composition metadata for every
  regenerated ordinal; the Exporter retains provenance while removing `srcClips` as today.

#### Magic Move folding

- Detect only explicit outgoing `apple:magic-move*` transitions across consecutive SELECTED source
  slides. Build maximal candidate chains, then qualify them using occurrence identity, asset
  continuity and a proved mapping to intended terminal slots; never group merely adjacent movie
  slides, a pan/zoom sequence, a replacement sequence, or duplicated copies of one asset. Partial or
  non-contiguous selection never silently pulls an unselected chain member into the output.
- For a qualified chain, take static/live overlay layout from the terminal slide and the union of
  distinct movie assets from the chain. For each asset use its last proved placement in the chain;
  a terminal poster may stand in for a previous movie only when archive/export evidence proves that
  mapping. Otherwise return separate compositions plus a visible warning.
- Before promising folding, inspect the ORIGINAL named FRC Wall source, record its source digest and
  a minimal offline fixture for slides 108–110. The banked terminal copy currently proves only two
  movies + one still. If original evidence proves the stated 1→2→3 composition, acceptance is one
  rail card, `sourceSlides=[108,109,110]`, terminal layout 110, three occurrences and three pure
  clips on one DSK slide. Only this explicitly qualified folded composition overrides source delays:
  patch one `after_transition` plus two `with_build_1`, all delay 0 and
  `playsAcrossSlides=False`. Ordinary stacked/cascade timing remains unchanged.

#### Phase-zero source evidence (offline, 2026-09-21)

- Inspected the original
  `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key` without launching
  Keynote: 6,771,226,120 bytes, 155 slides, SHA-256
  `549343a6f95275e7ad458b1551b87cc32d0cc0e1b0cc091096ec85161776334b`.
- Slide 108 has one movie (`VID-20250608-WA0125.mp4`) and an outgoing Magic Move. Slide 109 has two
  movies (`...WA0125.mp4`, `...WA0121.mp4`) and an outgoing Magic Move. Slide 110 has those SAME two
  movies plus the 1280×1080 still `Japan Bible Study.png`; its outgoing transition is dissolve.
  Thus the named source proves a 1→2→(2 movies + 1 still) composition, NOT three distinct movie
  assets. The Generator may fold it into one concurrent mixed composition, but it must not label the
  still a video or synthesize a third clip. A real three-video 108–110 result remains blocked on the
  missing third movie asset or a different source deck; generic three-video folding is covered by a
  synthetic offline fixture meanwhile.

#### Delivery slices and safe parallel work

0. **Evidence + frozen contract:** inspect the original 108–110 source, freeze the checked-in v2 JSON
   fixture, `CompiledComposition`, preview-layer contract, mask equations, editor safe area, v1
   migration and manifest extension names. No parallel implementation starts before this closes.
1. **Contract + visual workspace:** add the v2 model/adapter and the React reducer/components. The
   frontend may use fixture payloads while the backend planner lands, but must integrate against the
   committed v2 contract before the slice closes.
2. **Resolved geometry:** wire global/default inheritance, per-composition size/alignment/source/
   content decisions into proposal, save, apply and assembly. This slice replaces every current
   table capability except masks/folding and removes the visible clip picker.
3. **Video masks:** implement preview pan/zoom plus per-movie scratch crop/export and insertion.
4. **Magic Move compositions:** implement qualified sequence folding and the 108–110 simultaneous
   output. This may develop beside slice 3 after the v2 media identity contract is fixed, but both
   touch apply/manifest integration and merge serially there.
5. **Hardening/live gate:** migration, capability/refusal UX, responsive/keyboard QA, full suites,
   then a dashboard-driven Keynote run on a COPY of `Full_Report_Card_Wall.key` slides 108–110.

Parallel ownership after the v2 contract is fixed: one agent owns `dashboard/**`; one owns the
review planner + `web/app.py` API; one owns assembly/movie-export/mask/timing. Shared API contract or
manifest changes are proposed in the plan first and integrated by the parent; agents must not make
overlapping edits to those boundary files without coordination.

#### Acceptance gates

- Pure frontend tests: inherited defaults, reset, aspect math, snap selection, mask transforms,
  stable sequence ordering and serialization. UI tests: rail selection, pixel readout, pointer +
  keyboard resize/nudge, LW/FW colours, Full/Video capability, media selection, no reorder control,
  no clip picker, and Generate flushing an in-flight edit.
- Backend tests: v1 migration, strict v2 validation, explicit-transition chain detection, rejection
  of ambiguous poster/media mapping, 108–110 aggregation, layout-slide choice, bounds checking and
  decision round-trip.
- The v1 adapter must preserve current output when the operator makes no edits: legacy `auto`
  anchoring, measured-band geometry and any manual clip override continue through the v1 apply path;
  a deliberate edit upgrades that composition. Reject unknown/duplicate composition or occurrence
  ids, non-finite geometry, invalid enums and unsupported rotated/grouped masks before Keynote.
- Export/assembly tests: exact output frame, all three anchors, independent per-video crops,
  three clips on one slide, simultaneous timing, deterministic clip/manifest order and transactional
  rollback. Every offline test continues to forbid a Keynote process.
- FRC Wall slide 50 acceptance keeps its two media slots 100% overlapped in the preview and compiled
  target geometry, permits independent mask selection, and preserves the existing source build
  order/dissolve/delay instead of applying folded-sequence simultaneous timing.
- Proposal/preview tests cover prepared poster + overlay layers from the same compiled geometry,
  preview-vs-generated placement within 1 output pixel, source strokes without double borders,
  masks surviving valid outer resize, LW/FW/content invalidation, and complete/partial/noncontiguous
  selections. Review preview is explicitly poster-based; do not expose a fake Play control.
- Save/API tests cover source-digest mismatch, stale revision 409, latest-state Generate, fresh
  regeneration dropping stale composition metadata/clips, and preservation of the workspace picker
  plus text-slide exclusion.
- Run focused Python tests, `dashboard` decision/UI tests, dashboard typecheck/build, then the full
  Python suite. The final live gate works from a safe copy, checks one output slide with three movie
  objects and correct masks/timing, and never mutates the owner's source deck.

### Shipped path — DONE (detail in Git + evidence dirs)
1–7. All FIXED + live-verified 2026-09-16 (r14–r16): propose quits its own preview Keynote (leaves
   an operator's open Keynote alone); the Exporter stages PNGs beside the deck; exporter verified on
   the hand-built + `..._with mistakes` decks; JobName rename on both sub-tabs; `content_only=True`
   refuses the text-only kwargs (`text_fit`, `min_text_pt`, `allow_split`, `split_overrides`); and
   the two-batch + pure-per-movie Generator→Exporter chains on `DSK_Gen_Export_Input.key` 11–13 (PRs
   #135/#138/#140/#143/#148). Evidence `~/Desktop/dsk-d4-work/evidence-r1[456]/`. Durable Keynote
   quirk found here: this build raises -1728 on `locked of group N` though the group deletes fine
   (tolerated, #148).

### Verse/text backlog (resumed 2026-09-17)
8. **Pill z-order — LIVE-BROKEN (text-r1, 2026-09-17).** On a group-verse slide (GW5) the pill pass
   refuses `badge <id> has no z-order anchor`: the group-child badge's `super.parent` is None, so
   `_z_order_anchor` (`dsk_pill.py:390`) can't walk badge → owning group (which IS the sole
   `ownedDrawables` entry). Fix: set the badge's `super.parent` to its group in assembly, OR resolve
   group membership via the group's children in `_z_order_anchor`. Blocks the live text pass.
   Evidence `~/Desktop/dsk-d4-work/evidence-text-r1/` (`DIAGNOSIS.md` + the `.refused.key`).
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
21. **d5c KPF preview / alpha pipeline** — implementation handoff and acceptance gates:
    [keynote_alpha.plan.md](keynote_alpha.plan.md). Ship on-demand dashboard build preview
    independently of transparent animation export. The 2026-09-12 probe disproved this item's
    old `global/shared.pdf` and public-player-method assumptions: HTML export has per-slide
    PDFs, and player methods are private. Alpha capture and deterministic per-click video
    segmentation remain unproven. Preserve the existing PNG and opaque-clip contracts until
    the new route passes its own gates; do not enable `overlay_bake` separation implicitly.
22. **d7 insert mode** (stretch) — `--dsk-existing`; reuse `MapsTab`'s drag interaction
    (`:752-789`) and `moveSlideTo`'s index math, NOT `MapsDocument`.
23. **d8 maps reuse** — point `maps_keynote.dsk_ops`/`dsk_item` at the shared crop utility
    (today it SCALES the panel ×0.5 to the bottom half, it does not mask); then hand the Maps
    DSK deck to the Exporter rather than growing a second export path.
24. **Both exporters share the placeholder-materialisation exposure** — UNMEASURED: only the
    assembly path deletes the prepended slot instances after `set base layout`.
25. **`Full_Report_Card_Wall.key` (6.7 GB, 155 slides)** — a 2-slide subset ran live in r18 (generate
    ~5 min incl. a 6.7 GB scratch copy per export, peak RSS 3.21 GB → needs
    `OBED_DSK_RSS_LIMIT_GB`); a WHOLE-deck run is still unmeasured.
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

28. **Stacked-clip build-IN — DONE, LIVE-VERIFIED r18 (2026-09-20).** `patch_clip_start_timing`
    rewrites the upper clip's auto `apple:movie-start` build `effect` to the source's
    `apple:dissolve` (allow-list) and carries the source chunk mode + `delay` through `ClipTiming`
    (`with_previous` / `after_previous` / `on_click`); plan order = chunk order on a build-in slide;
    build + chunk `duration` written only when the source differs. Unsupported effects, an
    `Out`-only build, or a relative build-in whose source predecessor is not the clip directly
    below (with exactly one source chunk) WARN and keep the plain cascade; two `In` candidates or
    a PARTIAL stack REFUSE. Live r18 on FRC 48 + 50 (videos-only, dashboard-driven): generated
    clips at (258, 670) 1404×395 = gold slide 4; slide 50 build chunks mirror the source (movie 0
    movie-start pos 0; movie 1 dissolve In pos 1, automatic True / referent False / delay 8.0);
    Keynote opens the patched deck, the Exporter renders A → cross-dissolve at ~8.25 s → B
    playing; an open + nudge + SAVE in Keynote leaves the builds IDENTICAL. Evidence
    `~/Desktop/dsk-d5-work/evidence-r18/` (`final50_strip.png`), outputs `…/r18-output/`.
29. **Stacked-clip intermediates exported BARE — DONE, LIVE-VERIFIED r18.** The upper stacked clip's
    scratch copy has its source build-in flipped to `apple:movie-start` / After Transition / delay 0
    (`iwa_movies.bare_source_build_ins`, scratch only, `_SlideJob.bare`). Live: movie 1's
    intermediate is 18.37 s (= 13.32 s source + the ~5 s hold, NO +8 s), plays from t=0.
30. **Codex r2/r3 writer hardening.** (a) cross-member build/chunk — MEASURED, KEEP REFUSING: 1,429
    builds + 1,429 chunks across FRC Wall, Alpha_DSK, DSK_Gen_Export_Input, Gold_Wall_Input and
    Sermon_PK (GW) — zero live outside their slide's member, zero drawables outside their build's
    member; no deck to test a cross-member write against, so the fail-closed refusal stays.
    (b) DONE — the timing write is ONE `_patch_archive_fields` commit (the chunk reorder is the
    slide archive's `buildChunks` field; it used to be a separate `patch_slide_builds` rewrite,
    streaming a multi-GB deck twice) and a failed read-back restores the touched members.
    (c) DONE — page key `stackedMoviesKeepSide`; the chip follows the row's Keep side.
    (d) DONE — bare-ness is now carried per clip: `ClipResult.bare` mirrors `_SlideJob.bare`,
    and `assemble_dsk_deck`/`plan_assembly` take `bare_clips[number] -> movie ids` (threaded
    like `clip_crops`; the dashboard fills it from `clip.bare`). An upper stacked clip not in
    `bare_clips` gets NO build-in and its own warn-only "not proven bare" warning (checked
    BEFORE the source candidates, so item 28's two-candidate refusal applies to proven-bare
    clips only — Codex r4), so a CALLER-SUPPLIED per-movie mapping (Python API only: CLI
    `--clip` is one path per slide, refused for several movies) can never be double-timed. The
    exporter bares every upper stacked clip while the assembler rebuilds only its supported
    subset — deliberate (unsupported = bare + warned, never double-timed).
    LEFT/RIGHT FLUSH — LIVE r19 PASS (2026-09-20, commit `393e475a`, dashboard-driven, FRC Wall
    48 left + 50 right, videos-only): slide 48 clip x 43 (w 1404); slide 50 clips x 473, right
    edge 1877 (upper clip w 1403 → 1876, the source's own 5 px); y 670 h 395 unchanged. The same run
    re-proved the 0.9 rule + item 30(d) live: slide 50 still `stackedMovies`, 1 build-in bared,
    upper clip dissolve With Previous delay 8.0; Exporter frames A@3 s / B@12 s. Peak RSS 3.07 GB.
    Source sha unchanged. Evidence `~/Desktop/dsk-d5-work/evidence-r19/` (`lr-strip.png`).
    Stack threshold SETTLED (owner, 2026-09-20): raised 0.5 → 0.9 — FRC 50's visible rects overlap
    100% of the smaller (movie 1 is 5 px narrower inside movie 0), so nothing real needed the
    loose bound and a row that merely clips can no longer be read as a stack.
31. **`wrapped_height` ignores paragraph styles — PLANNED (owner-banked 2026-09-22, option C).**
    Golden slide 33 (`test_wrapped_height_golden_slide_33_argentcf_bold`, xfail) is not a wrap
    error: nothing wraps; the text is five hard lines. The predictor prices every line at the
    item's 65 pt × 1.157 + 21 = 397.0 pt, but the autosize box's saved `naturalSize` is 229.8 pt
    (2.78 lines; +2.22 over). IWA: paragraphs 1–2 are ArgentCF-Bold 65 pt `lineSpacing` 0.7, the
    blank paragraph 10 pt (Caption parent), the citation 40 pt `lineSpacing` 0.7 under a Cyan Bold
    AzoSans char style (`Free Form` default: 45 pt, 0.8); `storage_runs` reports `size: None` for
    them because the size lives on the paragraph style. Faithful model: per-paragraph size from
    `tableParaStyle` (`iwa_runs.resolve_para_style`), paragraph `lineSpacing`, and the face's real
    ascent+descent (PIL: ArgentCF 1.215×, AzoSans 1.222×) instead of the fixed 1.157 — rough
    estimate ≈ 212 pt + inset vs 229.8 — calibrated against a Keynote measurement before it
    replaces anything. Paths: `dsk_plan.wrapped_height`/`wrapped_height_runs`/`line_count`/
    `wrap_line_spans`/`fit_heading_pt`, `iwa_runs.storage_runs`, the `dsk_assemble` slot/split
    fits (`~:816`, `~:2250`), and `iwa_text_shape.HEIGHT_MODEL` (its ArgentCF slope is
    single-line-only). Moves the DSK golden fits; never rewrites verse text to force reflow.
    Option B alone (per-paragraph size, no line spacing: 304.5 pt, +0.99 lines) was rejected: it
    clears the 1.0-line gate by 0.01 while still mis-modelling the line height.

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
