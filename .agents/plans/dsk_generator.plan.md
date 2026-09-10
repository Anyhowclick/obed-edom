---
name: DSK generator
overview: >-
  Automate the owner's hand-built FW→DSK lower-third workflow. Input: a finished
  LW/FW wall Keynote (7680×1080, centre panel 3840×1080 at x=1920). Output: an
  editable 1920×1080 DSK Keynote whose FW content sits in the lower-third band
  with a white 5pt border, plus an export folder of true-alpha assets
  for ProPresenter7 — one asset per build step on built slides — because
  Keynote can mask an image but not a movie, emits no alpha in live playback,
  and (measured 2026-09-10) emits no alpha in its ProRes 4444 movie export
  either, so the alpha route is an owner decision (Open question 13). Slides are classified offline (`iwa_builds.deck_builds`
  + kind counts), the operator picks which slides convert (the
  resizer's `range_from`/`range_to`/`slides` pre-filter plus per-slide include
  toggles in a review page — resizer/checker pairing pattern) and confirms each
  one, and apply runs the movie-crop pipeline and the deck assembly. Side-panel
  content is dropped by default but can be kept per slide, exactly like the
  resizer's `keepSideContent`. The dashboard tab becomes **DSK** with two
  sub-tabs: **Generator** (this FW→DSK flow) and **Exporter** (the d5 PP7-asset
  machinery exposed standalone, over any DSK deck — hand-built or generated). The movie-crop utility is shared so `maps_keynote.export_maps_job
  (export_dsk=True)` can stop leaving movies at wall geometry. Offline probe
  numbers are 2026-09-10 read-only; the live probe of the same date (Keynote
  15.3.1, owner's machine) is recorded separately and supersedes several
  offline inferences.
todos:
  - id: d0-probe-record
    content: "DONE (2026-09-10): sdef + template/sample band + border measured offline; QuickTime/KPF/builds behaviour measured live. See Probe results."
    status: completed
  - id: d1-classifier
    content: "Offline slide classifier (`dsk_plan.py`) over `iwa_builds.deck_builds` + offline kinds; no Keynote. Fixture: `Sermon_PK (GW).key`."
    status: pending
  - id: d2-band-affine
    content: "Read the DSK band rect from a reference DSK deck/template; contain-fit affine per item, clipped to the centre panel — or to the full 7680×1080 wall on slides the operator marks \"include side content\"; no hardcoded band."
    status: pending
  - id: d3-movie-crop
    content: "Shared `dsk_movie_export.py`: scratch centre-panel deck (3840×1080) → native-size export to a **`.m4v`** destination (`.mov` is rejected) → ffmpeg crop/scale; display-poke + RSS watchdog (>1.5GB). The alpha probe is DONE — mechanic (i) is dead; `d3` now carries only the opaque movie path plus the owner's chosen alpha route (Open question 13)."
    status: pending
  - id: d4-deck-assembly
    content: "Assemble the DSK deck by copy-and-transform of the FW deck (copy carries builds), live geometry, live deletes, CG-style layout import, white 5pt stroke."
    status: pending
  - id: d5-pp7-export
    content: "Export folder for PP7: one true-alpha asset per build step on `built` slides via the owner's chosen route (Open question 13) — stage PNGs (iii), difference-matte ProRes 4444 (iv), or KPF/Chromium (ii); opaque `.m4v` clips for `movie` slides and as fallback; slide attribution reconstructed from per-slide stage counts; manifest."
    status: pending
  - id: d5b-exporter
    content: "Standalone **Exporter**: classify ANY DSK deck offline, operator picks slides, emit the PP7 asset folder (per-build alpha assets, opaque movie clips, alpha stage PNGs) with d5's naming/manifest. Reuses `dsk_movie_export.py` + `dsk_plan.py`; no band affine, no scratch centre-panel deck."
    status: pending
  - id: d5c-kpf-alpha
    content: "KPF alpha pipeline (shared with alpha playback): export → strip → player driver → per-build capture → ProRes 4444; fidelity check vs build inventory."
    status: pending
  - id: d6-api-ui
    content: "Replace the `POST /api/dsk` 501 stub with propose→review→apply mirroring `/api/resize` (incl. `range_from`/`range_to`/`slides`), add `POST /api/dsk/export`; split `DskTab.tsx` into Generator/Exporter sub-tabs and rename the tab label to \"DSK\"."
    status: pending
  - id: d7-insert-mode
    content: "Accept an existing incomplete DSK deck and choose insertion positions (MapsTab drag-drop pattern). Promoted toward core — see Open question 9."
    status: pending
  - id: d8-maps-reuse
    content: "Follow-up: point `maps_keynote.dsk_ops`/`dsk_item` movie items at the shared crop utility."
    status: pending
  - id: d9-open-questions
    content: "MOSTLY DONE (2026-09-10): owner answered Q1-Q6, Q8-Q12; folded into the body. Q13 (alpha route choice) is now ANSWERED: (iii) stage PNGs ship first as automation of today's manual practice, (ii) KPF/Chromium is the strategic route shared with the alpha-playback app. STILL OPEN: (i) band placeholder in the DSK template — needs church staff."
    status: completed
---

## Context

The owner hand-builds the DSK (1920×1080, lower-third feed to ProPresenter7)
from the finished FW/LW wall deck. Images are shrunk with Keynote's image mask.
Movies cannot be masked, so the owner copies the FW content into a new Keynote,
exports it as a movie (which bakes the crop), imports that movie into the DSK
deck and applies a white border by hand. Keynote emits no alpha in live
playback, so build slides and movie slides must additionally be handed to PP7 as
pre-rendered assets rather than played live from Keynote.

Owner direction 2026-09-10: those pre-rendered assets must carry **true alpha**,
and a built slide is handed to PP7 as **one clip per animation**, so the PP7
operator clicks through the build exactly as they would in Keynote.

`dashboard/src/tabs/DskTab.tsx` (126 lines) already has the LW/DSK pickers and an
inspect flow and calls only `stubDsk` (`dashboard/src/api.ts:233`); `POST
/api/dsk` is a 501 stub at `src/obed_edom/web/app.py:494`. This plan supersedes
the `dsk-generator` todo in `.agents/plans/cue_palette_and_dsk_generator.plan.md`;
the cue-palette item there is unaffected.

## Probe results (measured 2026-09-10, read-only)

### sdef — `sdef "$(mdfind 'kMDItemCFBundleIdentifier == com.apple.Keynote' | head -1)"` (Keynote Creator Studio 15.3.1)

- `export format` (`Knef`) includes `HTML` (`com.apple.iWork.Keynote.exportHTML`),
  `QuickTime movie` (`exportQT`), `PDF`, `slide images`, `Keynote`, PowerPoint.
- `export options` (`Kxop`) carries `movie format` (`Kxmf`), `movie codec`
  (`Kxmc`), `movie framerate` (`Kxmr`), `all stages` (`Kxpa`), `skipped slides`
  (`Kxps`), `borders` (`Kxpb`), `rawKPF` (`Kxkf`), `image format`.
- **`movie export formats` has no free-form size.** The enumerators are
  `format360p/540p/720p/1080p/2160p` and `native size`; native size is
  *documented* as *"the same dimensions as the document, up to 4096×2160"*.
  **The live probe shows that note is not enforced at 7680×1080** — see below.
- `movie codec` is documented as *"codec for movie exported at native size"* —
  the ProRes choices only apply to a `native size` export.
- `movie codecs`: h264, AppleProRes422/422LT/422HQ/422Proxy/4444, HEVC.
  `movie framerates`: 12/23.98/24/25/29.97/30 (and higher entries below).
- **There are no duration keys in `export options`** — no per-slide hold, no
  per-build delay. Movie timing for click-advance builds is not scriptable; see
  the live probe and Risks.
- `slide` has `skipped` (`Kskp`) **rw** — per-slide export is achievable by
  toggling `skipped` on a scratch copy and exporting with `skipped slides:false`.
  There is no per-slide export command.
- `slide` names the transition property **`transition properties`** (code `strn`,
  type `transition settings`) at sdef `:328`, while the sdef's own example at
  `:548` writes `set the transition settings of the current slide to {…}`.
  The live probe used **`transition settings`** successfully from AppleScript;
  use that spelling and treat `:328` as the class/property-name mismatch it is.
- `document` `width` (`sitw`) / `height` (`sith`) are **rw** and this is not
  theoretical: `maps_keynote.build_deck_script` (`:1262-1265`) already does
  `make new document` → `set width of theDoc to N` → `set height of theDoc to N`
  → save → close → reopen → bind `document 1` by stem.
- `image` exposes `file` (r), `file name` (rw), `opacity`, `rotation`,
  `reflection *` — **no stroke, no mask**. `movie` exposes `file name`,
  `movie volume`, `repetition method`, `opacity`, `rotation` — **no `file`
  property at all, no stroke, no mask**. Confirms SKILL.md: a border must come
  from the offline `Index/DocumentStylesheet.iwa` route or from a template
  object that already carries it. **No mask property means no scripted crop.**

### DSK template — `~/Desktop/Default Templates/2026_Lower-Thirds (ENG).key` (exists, 130MB)

`offline_inspect.offline_wall_payload`: **1920×1080, 16 slides**, verse/lower-third
layouts only (verse text box, reference box, a `pasted-image.tiff` plate, a
shape). **No media band placeholder and no white stroke style at all** —
`iwa_write.card_styles` returns only `TSDEmptyPattern` black 1.0 entries. 16
transitions, **zero builds**. So "replace a bordered placeholder already in the
template" is not available today without editing the template.

### Hand-built DSK sample — `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key` (exists, 253MB)

1920×1080, 43 slides. Item census: 70 text, 36 image, 29 shape, 13 group,
**1 movie**. 131 of 181 media archives carry a `mask` — the owner really does
mask images, and **88 of those 131 masks are real crops** (mask rect ≠ image
natural size), not mere containers. Builds exist on 7 slides (5, 13, 14, 17, 26,
29, 30), so the hand-built DSK **does keep some builds live in-deck**.

Media items taller than 150pt (the band content):

| slide | kind | x | y | w | h | aspect |
|---|---|---|---|---|---|---|
| 1 | image | 352 | 704 | 405 | 350 | 1.157 |
| 2 | image | 1315 | 704 | 579 | 350 | 1.654 |
| 4 | image | 1312 | 704 | 579 | 350 | 1.654 |
| 4 | image | 396 | 894 | 1102 | 163 | 6.761 |
| 12 | image | 529 | 704 | 861 | 350 | 2.460 |
| **13** | **movie** | **258** | **670** | **1405** | **395** | **3.557** |
| 18 | image | 43 | 704 | 1832 | 350 | 5.234 |
| 31 | image | 1312 | 704 | 579 | 350 | 1.654 |
| 32 | image | 1516 | 704 | 376 | 350 | 1.074 |
| 33/34 | image | 26 | 788 | 1867 | 267 | 6.993 |
| 43 | image | 117 | 725 | 1685 | 326 | 5.169 |

(Slide 4 carries **two** band items — a 579×350 panel and a 1102×163 strip at
y=894. The earlier omission implied one item per slide; it is not.)

Modal band: **y = 704, h = 350, bottom edge 1054** (7 of 12 items); bottom edge
is 1051–1065 for all of them, i.e. a ~26pt bottom margin. Height 350 is 32.4% of
1080 — a **lower third**, not the bottom half. Horizontal placement is editorial:
centred (cx 960, five items), right-anchored (x+w = 1891/1894, four items), or
full-bleed. Widths follow the source aspect at that height **only for
whole-panel items**; the 405/579/861-wide items at h=350 are **cropped regions**
of a 3840-wide panel (a whole centre panel at h=350 would be 1244 wide), so
width is set by the owner's crop, not by the source aspect.

**Border, measured:** `iwa_write.card_styles` on the sample returns three white
`TSDSolidPattern` strokes of **width 5.0** — id `3812378` (9 refs across 7
slides: 1, 2, 4, 12, 18, 31, 32), `15185477` (3 refs, slides 19 and 43 — note
slide **19 has no band item**, so this style is shared with a non-band object),
and `15303898` (1 ref, slide 13 = the movie). So the movie carries a **white,
solid, 5.0pt** stroke, same as the images — but the styles are **shared across
objects we do not own** (see "Border" under DSK deck assembly).

**The movie's own numbers.** The `TSD.MovieArchive` has `naturalSize = 1920×540`
and `mask = None`. 1920/540 = 3.5556 = 3840/1080 exactly. The GW source movies
are 3840×2160 and 3840×1080, so a `native size` export of a 3840×1080 scratch
deck would have produced 3840×1080, not 1920×540. **1920×540 is the `1080p`
preset applied to a 3840×1080 document** (fit-width 1920 → 540 tall). So the
owner's scratch deck is the centre panel at 3840×1080 exported at the **1080p
preset**, not native size. This partially answers Open question 1 (the "1920"
in "3840×1920" is the *export width*, not a canvas dimension).

**Superseded by the owner (Q1, 2026-09-10):** the 1080p preset was the owner's
convenience, not a requirement. The pipeline exports the 3840×1080 scratch deck
at **`native size`** (which the live probe confirmed emits the document size
exactly) and does the DSK downscale afterwards. Native size is also **required
for `movie codec` to apply at all**, so it is a precondition of ProRes 4444.

### Cross-check against `maps_keynote.dsk_item` (`:689-698`)

`DSK_WIDTH=1920, DSK_HEIGHT=1080, DSK_SCALE=0.5, DSK_Y=540` maps the centre panel
to **1920×540 at y=540 — the bottom half**. That does not match the owner's DSK
(1868×350 envelope with a 1054 baseline), and it also *scales* every item rather
than masking anything: `_emit_item` (`:1104-1181`) only sets position/width/height.
So the claim that the Maps DSK export "masks images" is inaccurate — it scales
them, and the same scale is applied to movies. Conclusion: **do not hardcode a band.
Read it from a reference DSK deck** (todo `d2-band-affine`), per memory
`template-size-source-style`.

### Build reality (correcting the draft)

`iwa_builds.plan_build_patch` is a **subset-and-reorder** patch: it keeps
`min(source_count, output_count)` builds per key from the **output's own**
`builds` list and drops the rest. It can never *create* a build, and Keynote's
sdef has no build class. Therefore a DSK deck **built fresh from a template can
never carry a build**. The only route to an editable DSK deck with builds intact
is **copy the FW deck and transform its objects in place**, exactly as
`remap_keynote` does (`ditto` at `:534`).

**Correction to the draft's use of `restore_source_builds`.** That function
(`remap_keynote.py:693`) **REFUSES when the slide sets differ**
(`:721-726`: `if set(src_by_number) != set(out_by_number): … REFUSED`). This plan
drops `empty` slides from the DSK deck, so the sets always differ and the call
would always refuse. It is also **unnecessary**: a `ditto` copy already carries
each slide's own builds, and deleting an object live removes that object's
builds with it. So `restore_source_builds` is **not** part of `d4`; use
`iwa_builds.verify_builds(src_by_number, out_by_number)` as a **check** instead,
restricted to kept slides — it may legitimately report builds *missing* for
deleted objects, and must never report *surplus*.

Likewise, the draft's "clear builds on movie slides" patch is dropped: deleting
the FW movie object clears its builds as a side effect.

### Live probe results (2026-09-10)

Measured on the owner's machine, Keynote 15.3.1, evidence under
`/Users/anyhowclick/Desktop/mm-probe-work/` and scratchpad `.../scratchpad/mm-probe/`
(`mm2_bbox.csv`, `gw_kpf_json/`, `keynote.sdef`). The owner's open document was
unmodified: backed up (`backup-Sermon_PK (DSK)_with mistakes.key`) and quit cleanly.

**0. Lock screen stalls Keynote's movie and slide-image exports.** The same
single-slide export took **208 s** with the display locked versus **11 s**
awake, and resumed the instant the display was poked (`caffeinate -u -t 2`).
`caffeinate -dimsu` alone is **not** sufficient — the renderer needs a real
display wake, not just an idle assertion. HTML/KPF export is unaffected. Any
unattended run must poke the display periodically or refuse to start while
locked (see Operator rules and Risks).

**A. QuickTime export / Magic Move — CONFIRMED, with one sdef correction.**
`{movie format:native size, movie codec:h264, movie framerate:FPS30}` is
accepted, and the output is the **document size exactly**: a 3840×1080 synthetic
deck exported 3840×1080, and `Sermon_GW` at 7680×1080 exported **7680×1080**.
The sdef's "up to 4096×2160" note is therefore **not enforced at 7680×1080**.
Correct the earlier claim that this is "the single hardest constraint on the
movie path": it is not a constraint at 1080 height. The cap remains **unverified
above 2160 height**. The scratch centre-panel deck stays **preferred** (it bakes
the crop, halves the pixel count and keeps files sane) but is **no longer
mandatory** for export to succeed.
A rectangle's bbox interpolates smoothly with ease-in/out over exactly **2.0 s**
(`mm2_bbox.csv`, 571 frames at FPS30). On the real deck, transitions match the
offline table: dissolve 0.5 → 0.4 s, magic move 1.0 → 1.0 s, none → hard cut.
**Semantics: the transition on slide N plays when LEAVING N.**
Per-slide hold is **5.0 s** and build delay **2.0 s**, from the KPF
`header.json` (`autoplayTransitionDelay: 5`, `autoplayBuildDelay: 2`) — these
are Keynote's self-playing defaults, and **the export options carry no duration
keys to change them**.

**B. KPF — CONFIRMED, with corrections to the memory's model.**
Magic Move is present as an event `type:"transition"`,
`name:"apple:magic-move-implied-motion-path"`, `duration:1`, but with
`animations: []` — it is a **declaration only**; the player computes the object
matching at runtime. **There are no per-slide PDFs**: the export ships one
`global/shared.pdf` (44 pages) indexed by page number, not `assets/<id>.pdf` per
slide. The lead fill rect is confirmed verbatim —
`q Q q /Cs1 cs 0 0 0 sc 0 1080 m 7680 1080 l … h f Q`, opaque black — and
stripping it makes a fill-only page **100% transparent**; object textures are
separate pages that already carry real alpha (one measured at 40% transparent).
**But** a slide with a full-bleed background image stays **opaque** after
stripping. The strip is **necessary, not sufficient**: alpha falls out only for
slides with no full-bleed backing — which is exactly the DSK lower-third case,
so option (c) — route **(ii)** below — remains viable for this plan's slides.

**C. Builds and `skipped` — CONFIRMED.** Setting `skipped:true` on every slide
but one, plus `skipped slides:false` in the export options, yields a movie of
that slide alone. Builds animate (a Sparkle build ramps over ~1 s; an Appear
build is a single-frame jump at t=2.03 s, which is correct for Appear).
**`all stages` has no effect on the QuickTime exporter** — identical durations
and frame counts with it on and off; it remains a print-layout key.
An embedded movie plays through (53 s export = the movie's length; an AAC audio
track is added to the export). Peak Keynote RSS was **1.18 GB** on the 242MB
deck. Wall times: **11–18 s** per single-slide export; **60 s** for the 9-slide
7680-wide deck.

**Operational findings.**
- Keynote cannot reliably open decks under `/private/tmp`. Use a work dir under
  `~/Desktop` or the repo's `output/`.
- **Two concurrent Keynote scripts collide** — one script's
  `close every document` killed the other's export. All Keynote work here is
  **strictly serial**; take a process-level lock.

## Classification

One classifier, `src/obed_edom/dsk_plan.py`, offline only. Inputs per slide:
`iwa_builds.deck_builds(fw_deck)` (`{number: {slideId, builds, transition, ...}}`)
and the offline item kinds from `offline_inspect.offline_wall_payload`, filtered
to the centre panel with `map_remap.CENTRE_PANEL_RECT` (`map_remap.py:439`) and
`map_remap.is_side_panel_item(item, wall_w, wall_h)` (`map_remap.py:446`).
(There is no `is_side_panel_only`; the earlier name was wrong.
`CENTRE_ORIGIN_X` lives in `maps_geo.py:33`, not `map_remap`.)

| category | test | default action |
|---|---|---|
| `empty` | no centre-panel item above the backdrop | skip (no DSK slide) |
| `static` | items, no `movie` kind, `builds == []` | **in-deck**: contain-fit into the band, white 5pt stroke. No export. |
| `built` | `builds != []`, no `movie` kind | **both**: in-deck copy (builds ride along and stay live for editing) **and** one exported alpha **asset per build step** (on-click per animation). The asset is a stage PNG (route iii) or an animated ProRes 4444 clip (route iv/ii) — see Open question 13; an opaque per-build clip cut at the measured frame-61 boundaries is the fallback. |
| `movie` | any `TSD.MovieArchive` in the centre panel | **export-crop**: scratch-deck movie export (**opaque** QuickTime, `.m4v` destination — `.mov` is rejected by the exporter) → ffmpeg → insert the exported clip into the DSK deck, stroke 5pt; the FW movie object is **deleted**, which clears its builds; the slide's own transition is set to `none` (the clip owns the timing). Movie slides never take an alpha route: (ii) omits embedded movies from the canvas capture, and (iv) can only matte an opaque movie region. |
| `mixed` | movie **and** builds/other content | treat as `movie` (the export bakes everything), flag in the review page for operator override |

**Side-panel content (owner revision, 2026-09-10).** Side-panel items (outside
`map_remap.CENTRE_PANEL_RECT`, i.e. `is_side_panel_item(item, wall_w, wall_h)`
true at `map_remap.py:446`) are dropped **by default**, but the operator may keep
them **per slide**, exactly as the CG resizer's `keepSideContent` works
(`FramingReview.tsx:419` `toggleSideContent`, the bulk buttons at `:519`/`:528`,
the per-page checkbox at `:964`; server side `_side_content_slides_from_result`
at `app.py:1212`). The earlier "dropped unconditionally — no per-slide whitelist"
line is withdrawn.

Semantics, per memory `church-list-keep-side-panel-spec`: the **centre wall is
always kept**; off-centre objects appear **only** on slides explicitly marked,
per slide, and the mark is **never carried forward by reuse** or by neighbouring
slides. Scope is positional, not by object kind (text, image, shape, group all
count).

What "include side content" means for the DSK:

- **Band affine (`d2`).** The item's visible rect becomes
  `item_rect ∩ FULL_WALL_RECT` (0,0,7680,1080 — `map_remap.LW_WALL_SIZE` at
  `map_remap.py:438`) instead of `item_rect ∩ map_remap.CENTRE_PANEL_RECT`, and
  the contain-fit is computed over the **union** of the kept items' visible
  rects, so the whole composed group lands in the band at one scale (never
  per-item scales, which would break the relative layout).
- **Movie path (`d3`).** The scratch deck stays **7680×1080** for that slide
  rather than being cut to 3840×1080 — the live probe exported `Sermon_GW` at
  7680×1080 at `native size`, so the wall-width native export is proven — and
  **ffmpeg crops to the union rect** afterwards. Centre-only slides keep the
  cheaper 3840×1080 scratch deck, so the scratch-deck width is a **per-slide**
  property; a mixed run needs two scratch decks (or one 7680 deck with
  centre-only slides cropped by ffmpeg — measure before choosing).
- **Grouping edge case** (same memory): a group whose bbox straddles centre and
  side is deemed centre content. That is a **source-deck mistake**, already
  surfaced as a dashboard warning; the DSK generator must not auto-split it.

Keep `deck_builds`'s per-slide-number dict as the primary key so slide-number
bookkeeping stays consistent downstream. `built` is a genuine both-ways case:
the owner's own sample keeps builds on 7 DSK slides, so "builds always become a
movie" would be wrong.

**Fixture.** `~/Desktop/Diff-Checker/Sermon_PK (GW).key` (669MB, **7680×1080,
63 slides**) is the FW companion of the DSK sample and is the fixture for `d1`
and `d2`: builds on slides {2, 3, 5, 6, 7, 17, 20, 32, 33, 37, 44, 54}, movies
on 32 and 33, side-panel-only items on 62 of 63 slides, 21 groups.
Note the count mismatch: **63 FW slides → 43 DSK slides**. The DSK is *not* a
subset of the FW deck — it is FW-derived media **plus template verse slides**.
Insert mode (`d7`) stays stretch per the owner (Open question 9).

## Blocker: images are cropped, not scaled

The owner's DSK images are **real crops**: 88 of 131 masked media archives have
a mask rect smaller than the image, and the band widths (405 / 579 / 861 at
h=350, against 1244 for a whole centre panel at that height) show he is
selecting a *region* of the FW panel, not shrinking the panel.

This plan's band affine is a **pure contain-fit scale**, exactly like
`maps_keynote.dsk_item`. It does not crop, and it cannot:

- the sdef exposes **no mask property** on `image` or `movie` (probed above), so
  there is no scripted route;
- offline writes that create a real crop are refused — memory
  `offline-write-render-fields-defect` (render fields go stale and the
  offline writer refuses rather than corrupt them).

**What this plan therefore claims, precisely:** existing FW masks **survive the
`ditto` copy** and scale uniformly when the item's live width/height are written
(**one live probe still owed** — write w/h on a masked image and confirm the mask
scales with the frame rather than revealing or clipping content). **No new crops
are created.** Editorial cropping stays **operator work in the editable DSK
deck**, which is precisely why the deliverable is an editable deck and not a
finished one. If automatic cropping turns out to be essential, it is a
**separate workstream** (mask authoring via offline write, gated on
`OBED_OFFLINE_WRITE` and on the render-fields defect being fixed), not a
tweak to `d2`.

**Resolved by the owner (2026-09-10):** scale-only is the agreed contract.
The one live probe still owed (mask travels with a live width/height write)
becomes a `d4` acceptance line rather than an open design question.

## Blocker: off-canvas media

FW media is not guaranteed to lie inside the centre panel.
`~/Desktop/Diff-Checker/Sermon_PK (GW).key` slide 32 holds a **3840×2160 movie at
(1920, −763)** — it bleeds well above and below the 1080-tall canvas.
A naive `s = band_h / src_h` gives a **2× wrong scale** there, because `src_h` is
the item's declared height, not its visible height.

**Fix:** compute the fit from `item_rect ∩ map_remap.CENTRE_PANEL_RECT`, i.e. the
**visible** rect, never the declared rect. For the movie path this costs nothing
— the QuickTime export of the centre-panel scratch deck clips off-canvas content
for free, so the exported clip already *is* the visible rect. For static images
it needs a crop, which lands us back in the mask blocker above; for those,
contain-fit the intersection and flag the slide for operator review.

**Resolved by the owner (2026-09-10):** intentional — the top and bottom are
deliberately cropped framing. The scratch-deck export **bakes that crop**, so the
current design stands unchanged. The owner's wish to apply an image mask to the
movie beforehand is **future work under the crop workstream** (blocked today: the
sdef exposes no mask on `movie`).

## Blocker: layouts and masters

Never addressed in the draft. A `ditto` copy of the FW deck keeps the FW deck's
**7680-wide layouts and master artwork**. Setting `document width/height` to
1920×1080 does not rewrite them, so the DSK deck inherits background art sized
for the wall — and the same leak reaches the **scratch export deck**, where it
would be baked into every exported clip.

The CG resizer already solves this and the solution is reusable:
`importCgLayouts` (`remap_keynote.js:1111`), `applyCgLayouts` (`:1152`) and
`deleteTrailingSlides` (`:1171`), driven from `:1282-1284`.

**Fix (a `d4` deliverable, and applied to the scratch deck too):** import a
layout — from the Lower-Thirds template, or a plain black one — into both decks
and set the **base layout on every kept slide**. `d4` acceptance line: no kept
slide's base layout is an FW/7680-wide layout, and no exported clip shows wall
background art.

## Movie-crop pipeline — options and decision

**(a) Scratch centre-panel deck → QuickTime export → ffmpeg. (chosen)**
`ditto` the FW deck to a scratch copy under `output/` or `~/Desktop/…`
(**never `/private/tmp`** — Keynote cannot reliably open decks there), never the
owner's deck. Set `width`/`height` to **3840×1080** on the open document and
translate every item by `-maps_geo.CENTRE_ORIGIN_X`, so the centre panel becomes
the canvas. This is now a **preference, not a requirement** — the live probe
exported a 7680×1080 document at native size — but it bakes the crop, clips
off-canvas media for free, and quarters the intermediate file size.
**Exception: slides marked "include side content" keep the scratch deck at
7680×1080** with no translation (the wall-width native export is proven by the
live probe), and the crop to the kept-item union rect is done in ffmpeg instead
of by the canvas. Import the
Lower-Thirds/black layout here too (see the layouts blocker). Then:
`export theDoc to <file> as QuickTime movie with properties {movie format:native
size, movie codec:AppleProRes422LT, movie framerate:FPS30, skipped slides:false}`
— with `<file>` ending in **`.m4v`** (`.mov` is rejected, error `".mov" (6)`).
Then `maps_movie.ffmpeg_exe()` → `scale`/`crop` to the band pixel size and
re-encode. Insert with `make new image with properties {file:…}` (the Keynote 15
quirk documented at `maps_keynote.py:1119`; `make new movie` no longer imports).
No alpha. This is exactly what the owner does by hand, and it is the
recommendation for the **first tranche**.

**(b) Difference matte over two QuickTime exports** (same slide over black and
over white; solve `alpha = 1 - (white - black)`, `colour = black/alpha`). True
alpha from a supported export, at 2× export cost, needing the scratch deck's
slide background flipped twice. Encode with the existing
`maps_reveal._run_ffmpeg_stdin` ProRes 4444 pipe (`prores_ks -profile:v 4444
-pix_fmt yuva444p10le -vendor apl0`, `maps_reveal.py:303-330`) fed numpy RGBA.
**Promoted 2026-09-10:** with mechanic (i) dead, this *is* route **(iv)** in the
Decision below — no longer a stretch, but the leading candidate for animated
alpha, made scriptable by flipping `base layout` (the slide background itself is
not scriptable). Export to **`.m4v`**; see "Next live probe (difference matte)".

**(c) KPF/HTML export rendered headless.** The draft's claim that this "cannot
capture builds because `all stages` is not honoured" conflated two exporters and
was wrong; the live probe confirms `all stages` is inert for **QuickTime** too,
and that the KPF player animates builds. Live-probe corrections to the recipe:
there is **one `global/shared.pdf`, indexed by page number**, not a PDF per
slide; the lead fill op is confirmed verbatim and strips to full transparency;
Magic Move is a declaration (`animations: []`) the player resolves itself. The
route is: export as HTML, strip the lead fill op from the base-texture page of
each slide (pypdf is already a dependency, `pyproject.toml:19`), patch the two
black body styles, drive the player in headless Chromium
(`jumpToSlide(`, `advanceToNextBuild(`, `goBackToPreviousBuild(`), then either
screenshot per build stage (PNG stages for PP7) or capture the transparent
canvas frame-by-frame into `_run_ffmpeg_stdin` for a ProRes 4444 alpha movie.
**Fidelity limits:** the KPF player simplifies unsupported builds/transitions;
**movies are exported separately by KPF** and are not in the canvas capture, so
(c) never replaces (a) for movie slides; and **a slide with a full-bleed
background image does not go transparent even after the strip** — for the DSK
lower-third slides (no full-bleed backing) it does. It also adds a headless
Chromium/Playwright dependency the repo does not have (no `playwright` in `src/`).

**Decision (revised after the alpha probe, 2026-09-10).**

PP7 assets must carry **true alpha**, and on `built` slides there is **one asset
per build step** (owner Q2/Q4/Q10). `built` slides **also stay live in the DSK
deck** — the `ditto` copy carries the builds for free.

**Mechanic (i), Keynote's own ProRes 4444 export, is DEAD.** The probe above
shows the alpha plane is constant 255. Do not spend further effort on No Fill,
theme choice, or the images-only `AllowsSlideBackgroundAlpha` default.

The **opaque** QuickTime path (option (a)) is unaffected and still ships: it is
the route for **`movie`-category slides** — the clip inserted into the DSK deck —
and it is the PP7 **fallback** wherever alpha cannot be produced.

Three alpha routes remain. None is free; the choice changes the dependency set
and the fidelity of the PP7 handoff, so it is **ESCALATED to the owner as Open
question 13**.

**(ii) KPF/HTML + fill strip + headless Chromium capture.** Export as HTML, strip
the lead fill op from the base-texture page of `global/shared.pdf` (pypdf is
already a dependency), patch the two black body styles, drive Apple's player in
headless Chromium (`jumpToSlide(`, `advanceToNextBuild(`,
`goBackToPreviousBuild(`) and capture the transparent canvas frame-by-frame into
`maps_reveal._run_ffmpeg_stdin` (`prores_ks -profile:v 4444 -pix_fmt
yuva444p10le -vendor apl0`, `maps_reveal.py:303-330`).
*Gives:* animated builds, true alpha, **deterministic** per-build segmentation
(we own the clicks).
*Costs:* a Playwright/Chromium dependency the repo does not have; the KPF
player's fidelity limits (unsupported builds/transitions are simplified);
**KPF exports embedded movies separately**, so movie slides are never in the
canvas capture and always fall back to (a); slides with a full-bleed background
image stay opaque even after the strip.

**(iii) NEW — Keynote-native PNG build stages.** Run
`export … as slide images {image format:PNG, all stages:true}` on the scratch
deck. **Proven above** to emit one **RGBA 1920×1080 PNG per build stage** with
real alpha. PP7 then gets **one alpha PNG per click**, or a short ProRes 4444
still-clip per stage assembled by ffmpeg from that PNG.
*Gives:* zero new dependencies, **exact Keynote rendering**, real alpha, and the
cheapest possible route to "on-click per animation".
*Costs:* **stages, not animated builds** — the motion between stages is lost, and
Magic Move becomes two stills; a short cross-dissolve in PP7 approximates it.
Naming must be reconstructed from per-slide stage counts (see above).

**(iv) NEW — difference matte, made scriptable via `base layout`.** The slide
background is not scriptable (-1700), but `base layout` is. Import a **solid
black** and a **solid white** blank layout into the scratch deck; export the
target slides **twice**, once with each base layout applied, as ProRes 422LT (or
h264) `.m4v`. The probe showed exports are **frame-deterministic** — byte-identical
hold frames and a frame-exact build start at frame 61 on both build slides — so
the two passes align frame-for-frame. Then solve per pixel:
`alpha = 1 - (white - black)`, `colour = black / alpha` (premultiplied-over-black),
and encode via `maps_reveal._run_ffmpeg_stdin`'s ProRes 4444 pipe. Cut per build
at the measured boundaries.
*Gives:* **animated** builds with true alpha, rendered by **Keynote's own
renderer** (full fidelity), **no Chromium**.
*Costs:* 2× export cost; needs **its own probe** (frame alignment + matte
accuracy on anti-aliased edges) before it can be trusted; content that itself
depends on the background — **drop shadows, blend modes** — mattes imperfectly;
movies inside slides matte fine provided the movie region is opaque.

**Recommendation (owner decision, 2026-09-10 — see Open question 13).**

1. **(iii) ships in the first alpha tranche.** It is cheap and automates the
   owner's existing manual practice: stage PNGs, zero new dependencies,
   pixel-exact Keynote rendering. The owner loses in-build motion, which for a
   lower-third build is often acceptable.
2. **(ii) is the PRIMARY, strategic alpha route** — not a fallback. It is the
   *same* KPF pipeline as the alpha-playback app (see
   `keynote-alpha-output-via-kpf` memory / `ALPHA_KEYNOTE_PLAN.md` if present),
   so one build serves both the PP7 asset export here and live alpha playback
   there. Shared core: `export … as HTML` → strip the lead fill op in
   `global/shared.pdf` → patch the two black body styles → drive Apple's KPF
   player (`jumpToSlide(`, `advanceToNextBuild(`). From that shared core, PP7
   export does a headless per-build capture encoded to ProRes 4444 via
   `maps_reveal._run_ffmpeg_stdin`; live playback drives a transparent Electron
   host (fill+key sink).

   Shared caveats, solved once by the shared core:
   - **Player fidelity for unsupported builds** — needs a fidelity check against
     the deck's build inventory from `iwa_builds.deck_builds` (flag any build
     effect the player simplifies rather than silently shipping a degraded
     asset/playback).
   - **Movies are exported separately by KPF** — composite them back in, or hand
     them to PP7 as their own clip via the existing opaque path (a).
   - **Chromium dependency** — already implied by the alpha-playback app, so
     adopting it here adds no *new* project-level dependency, only a repo one
     (Playwright).
3. **(iv) difference matte is demoted to a fallback/footnote** — only pursued if
   (ii)'s player fidelity fails (see the renamed probe section below).

**The trade-off, stated plainly:** (iii) is cheap, exact, and still — ships now
as automation of current practice. (ii) is animated, true alpha, and shares one
build with the alpha-playback app, at the cost of a Chromium dependency and the
KPF player's own fidelity limits (checked against the build inventory). Movie
slides go through (a) in all worlds.

## Alpha probe results (2026-09-10)

Measured on the owner's machine, Keynote 15.3.1. Evidence:
`~/Desktop/mm-probe-work/alpha/` (decks, AppleScripts, `.m4v` exports, PNGs,
`measure.py`, `seg.py`) and scratchpad copies of the CSVs at
`.../scratchpad/mm-probe/alpha/*.csv`. Alpha was sampled by decoding each export
to raw `rgba` and taking numpy min/mean/max of the A channel over a background
region, a content region and the full frame.

| # | export / asset | subject | command | result |
|---|---|---|---|---|
| 1 | `alpha_white.m4v` | synthetic 3840×1080 deck, **Basic White** theme, blank slide + built object, background left at theme default | `as QuickTime movie {native size, AppleProRes4444, FPS30}` | `pix_fmt yuva444p12le`; A = **255 everywhere, every frame** (`alpha_white.csv`: bg/ct/full min=mean=max=255, `opaque_frac 1.0`) |
| 2 | `alpha_black.m4v` | same deck re-themed **Basic Black** | same | identical: `alpha_black.csv` all-255 |
| 3 | `pk13_alpha.csv` | `Sermon_PK (GW)` slide 13 (movie slide), 53 sampled frames | same | A = 255 in every frame, background region included |
| 4 | `pk14_seg.csv` | PK slide 14, **Appear** build, 212 frames | same | A = 255 throughout; segmentation usable (below) |
| 5 | `pk17_seg.csv` | PK slide 17, **Sparkle** build, 253 frames | same | A = 255 throughout; segmentation usable (below) |
| 6 | `pkimgs/pkimgs.00N.png` | PK slides 14 + 17, `as slide images {image format:PNG, all stages:true}` | AppleScript `export … as slide images` | **4 RGBA PNGs, 1920×1080, REAL alpha** — `png_alpha.csv` A mean ≈ 47.8, `opaque_frac` 0.014–0.022 |
| 7 | `pkimgs_nostages/` | same two slides, `all stages:false` | same | **2 PNGs** — so `all stages` is honoured by the slide-images exporter |

**Verdict: alpha via mechanic (i) is NOT real — settled.** Keynote's ProRes 4444
QuickTime export *allocates* an alpha plane (`pix_fmt yuva444p12le`) but fills it
with a **constant 255** in every frame, for Basic White and Basic Black alike,
and for PK slides whose **PNG slide-image export of the same pixels is
RGBA(0,0,0,0)**. The movie exporter flattens transparency to opaque black. The
GUI's "transparent background" claim does not reach the scripted movie exporter,
and the sdef has no transparency key (confirmed again here). Mechanic (i) is
closed.

**Corrections and operational facts.**

- **`all stages` memory correction.** The 2026-09-08 memory line "`all stages` is
  not honoured" is **wrong for the slide-images exporter** (rows 6/7 above: 4
  files with it on, 2 with it off, consecutive diffs confirming distinct stages).
  It remains inert for the **QuickTime** exporter, as measured in the earlier live
  probe. Treat the older measurement as wrong or deck-specific.
- **Naming.** Stage PNGs are `<basename>.NNN.png`, **flat 1-based sequential
  across the whole export**. The filename encodes **neither slide number nor
  stage index**. Attribution must be **reconstructed** from per-slide stage
  counts: `stage_count(slide) = build_count(slide) + 1`, with `build_count` from
  `iwa_builds.deck_builds`, walked in slide order over the non-`skipped` slides.
  This supersedes the assumed `<deckStem>.<NNN>.<ext>` "one index per build stage,
  keyed by slide number" line under "Naming (owner Q12)" — the index is global,
  not per slide, so the mapping is derived, and **the derivation must be verified
  against the stage counts on every export** (mismatch ⇒ refuse, do not guess).
- **Slide background is NOT scriptable.** `background of slide` and
  `background of document` both raise **-1700**, and the sdef's `slide` class has
  no `background` property. `base layout` **is** scriptable — the existing layout
  import in `d4`/`d3` is unaffected, and it is the only handle we have on what a
  slide sits on (this is what makes route (iv) below possible at all).
- **`defaults read com.apple.iWork.Keynote`** carries
  `KNMacExportImagesOptionsDefaultAllowsSlideBackgroundAlphaKey = 0`. It is an
  **images-only** key, and the PNG export produced real alpha anyway via script,
  so it does not gate us. **There is no movie counterpart.**
- **`.mov` destination is REJECTED** by the exporter — AppleScript error
  `".mov" (6)`. **`.m4v` works** and yields a `qt`-branded ProRes file. Use
  `.m4v` everywhere in `d3`/`d5`/`d5b`; rename after ffmpeg if a `.mov` extension
  is wanted downstream.
- **Build segmentation in the movie export is DETERMINISTICALLY CUTTABLE.**
  Frames 0–60 are **byte-identical** hold (2.000 s); the first differing frame is
  **61** on both build slides. Appear = **1 frame at t = 2.033**; Sparkle motion
  runs frames 61–~102 (≈1.4 s) then **exactly 150 frames (5.000 s)** of hold.
  Cut boundaries are unambiguous, which is what makes route (iv) viable and also
  means the *opaque* path can already be split per build.
- **Cost.** Wall times **6–21 s** per export; peak Keynote RSS **1.41 GB**
  (`rss.log`) — above the 1.18 GB seen earlier, so set the watchdog threshold
  with headroom over 1.5 GB.

## Fallback probe (difference matte) — only if (ii) fidelity fails

Gates route **(iv)** in the Decision above. Runs only if (ii)'s player fidelity
fails (Open question 13 owner decision, 2026-09-10). Operator rules apply in full: work dir
under `~/Desktop`, process lock, display poke (`caffeinate -u -t 2`), RSS
watchdog above 1.5 GB, always on a copy.

**Spec.** One scratch deck (3840×1080) built by `ditto` from
`~/Desktop/Diff-Checker/Sermon_PK (GW).key`, holding four slides:
- **A** — the Sparkle build slide (PK 17), anti-aliased text over nothing;
- **B** — the Appear build slide (PK 14);
- **C** — a slide carrying a **drop shadow** (the background-dependent worst case);
- **D** — a **Magic Move** pair (the transition the KPF player simplifies).

Import **two blank layouts**, one solid black and one solid white, into the deck
(`base layout` is scriptable; slide background is not — see the alpha probe).
Export the deck twice at `{movie format:native size, movie codec:AppleProRes422LT,
movie framerate:FPS30, skipped slides:false}` to **`.m4v`** (`.mov` is rejected),
setting every kept slide's `base layout` to black for pass 1 and to white for
pass 2, with nothing else changed between passes.

**Measurements.**
1. **Frame alignment.** Decode both passes to raw frames and byte-diff the known
   **hold** segments (frames 0–60, and the 150-frame post-Sparkle hold). Alignment
   holds if each pass's hold segments are internally byte-identical **and** start
   and end on the **same frame indices** across the two passes; report the first
   differing frame index per pass and require they match (61 on A and B, per the
   alpha probe).
2. **Matte residual on edges.** Compute `alpha = 1 - (white - black)` and
   `colour = black / alpha` per pixel, recomposite over black and over white, and
   report per-frame **max and 99.9th-percentile absolute error** against the
   corresponding source pass, split into an **interior** mask and a **1–3 px edge
   band** dilated from the alpha gradient.
3. **Anti-aliased edge quality.** On slide A, report the alpha histogram in the
   edge band: a good matte shows a smooth 0→255 ramp; a bad one shows clamping at
   0/255 or negative/`>1` alpha (count those pixels — they are the failure
   signature).
4. **Background-dependent content.** On slide C, report the same residual over the
   shadow region specifically. Expect this to be the worst number in the run.
5. **Magic Move.** On slide D, confirm the transition's motion frames align across
   passes (measurement 1 applied to the 1.0 s transition window) and report the
   residual there.

**Acceptance.**
- Alignment: **every** hold segment byte-identical within a pass and frame-index
  identical across passes; first-change frames equal. Any drift ⇒ (iv) fails
  outright.
- Matte: interior 99.9th-percentile error **≤ 1/255**; edge-band 99.9th-percentile
  error **≤ 4/255** with **zero** out-of-range alpha pixels after clamping is
  accounted for.
- Shadow region (slide C): reported, not gated — the number decides whether
  shadowed slides are routed to (iii)/(ii) per-slide rather than failing the run.

**What each outcome decides.**
- **Alignment + matte both pass** → **(iv) is the animated alpha path**, cut per
  build at the measured boundaries; no Chromium dependency ever enters the repo;
  `d5`/`d5b` gain a two-pass export plus a numpy matte stage feeding
  `maps_reveal._run_ffmpeg_stdin`.
- **Alignment passes, matte fails only on edges/shadows** → (iv) ships with a
  **per-slide guard**: slides whose measured residual exceeds the gate are routed
  to (iii) stills (or (ii) if the owner has funded it) and **reported**, never
  silently emitted.
- **Alignment fails** → (iv) is dead; **(ii)** becomes the animated route and the
  Playwright/Chromium dependency is accepted, with (iii) remaining the
  zero-dependency stills path.

## DSK deck assembly

**Route: copy-and-transform, not build-from-template.** `ditto` the FW deck to
`output/<stem>/<stem>_DSK.key`, then, in one live Keynote session, in this order:

1. **copy** (`ditto`) — carries builds, masks, media, presenter notes, styles;
2. set `width`/`height` to 1920×1080 (proven writable —
   `maps_keynote.build_deck_script:1263`);
3. **import + apply the DSK layout** on every kept slide (see the layouts blocker);
4. **live geometry writes** — band affine per kept item (below);
5. **live deletes** — dropped items (side panels, FW movie objects, non-band
   content) *and* the `empty` slides;
6. **offline check** — `iwa_builds.verify_builds` over the kept slides.

Order matters: geometry before deletes keeps item indices stable during the write
pass; deletes before the offline read so the check sees the final deck. Step 6 is
a **check, not a patch**: `restore_source_builds` is deliberately not used
(it refuses on differing slide sets, `remap_keynote.py:721-726`, and the copy
already carries the builds). `verify_builds` may report builds **missing** for
objects we deleted; it must never report **surplus**, and surplus is the failure
condition.

Rationale for copy-over-template: builds cannot be created
(`plan_build_patch` only subsets), text run styling cannot be recreated
(SKILL.md character-styling gap), and masks/media survive a copy for free. The
trade-off is deck size — see Risks.

**Band affine (`d2`).** Read a band rect from a `--dsk-reference` deck (the
sample, or a future template slide) rather than hardcoding: take media items with
h > 150pt, use the **modal bottom edge** (1054 here) and **modal height** (350) as
the band baseline and height, and the observed min/max x as the width envelope
(26 … 1894). Per item: compute the **visible** rect as
`item_rect ∩ map_remap.CENTRE_PANEL_RECT`, then `s = band_h / visible_h`,
contain-fit to the envelope width, horizontal anchor from the operator's
per-slide choice (centre / left / right, defaulting to centre — the sample's modal
`cx = 960`). Refuse rather than guess if the reference deck yields fewer than
three band items. **This is a scale, not a crop** — see the crop blocker.

**Include-side-content variant.** When the slide's review decision sets
`keepSideContent` (same field name and semantics as the resizer — see
Classification), the visible rect is `item_rect ∩ (0,0,7680,1080)` and the fit is
taken over the **union** of every kept item's visible rect: `s` is computed once
and applied to all of them, so their relative positions survive. A full-wall
union at h = 350 would be 2489pt wide — wider than the 26…1894 envelope — so the
fit is **width-bound** on those slides (`s = min(band_h/union_h,
envelope_w/union_w)`) and the result is shorter than the band. That is expected;
surface it in the review page so the operator can switch back to centre-only.

**Owner (2026-09-10):** accepted — an include-side slide is width-bound to the
full band envelope and therefore comes out shorter than the 350pt band height
(roughly 263pt for a full-wall union); the review page shows the resulting
height before apply.

**Owner (Q6, 2026-09-10):** a real band placeholder **should** exist in the DSK
template, but it must be agreed with church staff. Tracked as an **external
dependency**; until it lands, the measured values (h 350, bottom 1054, envelope
26…1894) are the **default placeholder** and the reference-deck read stays.

**Groups.** The GW fixture has **21 groups**. A Keynote 15.3.1 group resize is an
aspect-locked uniform scale about the group's live frame and permanently freezes
an autosize text child at its wrapped height (SKILL.md:285-288). Groups are
therefore written **child-by-child**, never resized as a group — reuse
`applyGroupChildren` (`remap_keynote.js:168`, and its guard comment at `:162-167`).

**Do not point the CG resizer at this.** `map_remap` already takes its target size
from the template (`map_remap.py:1274-1275`), so a 1920×1080 DSK template is
accepted — but the resizer places content by **pairing against template objects at
their final size**, and the Lower-Thirds template has no band objects at all. A
dedicated affine (in the spirit of `maps_keynote.dsk_item`, but band-read rather
than `DSK_SCALE=0.5`) is the right tool; reuse `remap_keynote`'s copy/open/
geometry-write/layout-import machinery, not `map_remap`'s planner.

**Border.** The sdef has no stroke on `image`/`movie`, and
`iwa_write.patch_stroke_widths` only rewrites `mediaProperties.stroke.width` on an
**existing own** stroke (it explicitly refuses inherited-only and missing styles,
`iwa_write.py:1098-1107`). Three options were considered:
1. a bordered placeholder in the DSK template that we replace — **not available
   today**: the template has zero white stroke styles (measured above);
2. a white rectangle shape behind the media via AppleScript — works with today's
   API (`make new shape`, `fill color`) but doubles item count, mis-renders on
   non-rectangular masks, **and needs a GUI z-order raise** (the sdef has no
   z-order write), which drags in Accessibility permission;
3. offline media-style patch.

**Chosen: keep the SOURCE object's stroke (owner, Q5, 2026-09-10).** The DSK deck
is a *copy* of the FW deck, so the LW image/movie's own stroke style travels with
it — preserve it untouched wherever it exists. Only where the source object has
**no** stroke do we apply the **house white `TSDSolidPattern` 5.0pt** via a
`patch_media_stroke` sibling to `patch_stroke_widths`, selected by
ref-count/colour exactly as `match_card_stroke_styles` does — never by id.

"Refuse" is no longer the primary behaviour, but the **shared-style guard
stays**: never recolour a style whose refs escape the kept band media. The sample
shows why — style `3812378` has 9 refs across 7 slides, and `15185477` covers
slide 19, which has no band item. In that case **duplicate the style for the kept
refs**, and only if that is not possible fall back to refuse-and-report. Option
(2), the white rectangle shape, stays rejected (it needs a GUI z-order raise).

**Transitions.** `movie`-category slides get their slide transition set to
**`none`** (via `set transition settings of slide N to {transition effect:none}`
— the working spelling per the live probe), because the exported clip owns the
timing and the transition on slide N fires when *leaving* N.

**Inserted clip behaviour (owner Q11, 2026-09-10).** The DSK deck holds the
**exported clip, never the original FW movie**. Golden rule: **keep to source deck
behaviour** — read `repetition method` and `movie volume` off the FW `movie`
object (both exposed in the sdef) and write the same values onto the inserted
clip. If the source loops, the clip loops; if the source plays at full volume, so
does the clip. The operator may copy anything else over by hand.

**Stat overlay (owner Q8, 2026-09-10).** The overlay ("1.9% Christians") is
**baked into the clip by default** — that matches the owner's own practice — but
the review page offers a per-slide choice: **"bake overlay into clip"** (default)
vs **"clip only, operator adds the text manually in PP7"**.

**Presenter notes** survive the `ditto` copy untouched; nothing to do, and
nothing is lost (unlike a KPF export, where notes are not exported).

## Per-slide export mechanics and cost

Pick **one** scratch deck holding only the target slides (build it by **deleting**
the non-targets, so Keynote holds a small deck), open it **once**, then per target
toggle `skipped` (rw, sdef `:310`) so only that slide is visible and export.
`skipped slides:false` in the export options keeps the others out.
**No save is needed between exports** (live probe) — keep the document open for
the whole batch and close `saving no` at the end.

**Serialisation.** Two concurrent Keynote scripts collide (a `close every
document` in one killed the other's export). Take a process-level lock; never run
`d3` alongside a resize or maps job.

**Display poke.** A locked display stalls the exporter (208 s vs 11 s). The runner
must either refuse to start while the screen is locked, or poke the display with
`caffeinate -u -t 2` on a timer for the duration of the batch. `caffeinate -dimsu`
alone is not enough.

**Watchdog.** Peak Keynote RSS was 1.18 GB on a 242MB deck; sample
`ps -o rss= -p <pid>` on a timer and abort the batch past a threshold.

**Cost.** Measured wall times are 11–18 s per single-slide export and 60 s for a
9-slide 7680-wide deck — far cheaper than the draft's "real time or slower"
assumption, but the FW deck can be up to **6.7GB** (`Full_Report_Card_Wall.key`,
155 slides — still UNMEASURED for whole-deck live work, memory
`resizer-operator-rules`), and the whole run is a **Keynote hands-off window**.
Mitigations: (i) only `movie`/`mixed`/`built` slides are exported, a small
minority — the owner's sample has **one** movie in 43 slides; (ii) the
slide-deleted scratch deck; (iii) batching K non-adjacent targets into one export
that ffmpeg splits at slide boundaries is now **computable** — per-slide hold is
5.0 s and build delay 2.0 s, plus the measured transition durations — but is
still unvalidated end-to-end; park it. Launch with `nohup … &` and Monitor the
log; background Bash is capped at 10 minutes.

**Naming (owner Q12) — MEASURED 2026-09-10.** The sdef documents no naming,
prefix or numbering key, and `slide images` is listed with extension `N/A` (a
folder destination). The live export settles it: files are
**`<basename>.NNN.png`, zero-padded from `001`, flat 1-based sequential across
the whole export**. The filename encodes **neither the slide number nor the stage
index**.

**Reconstruction rule (normative).** Attribution is derived, not read: walk the
exported slides in slide order, skipping any slide with `skipped:true`, and
consume `stage_count(slide) = build_count(slide) + 1` filenames per slide, with
`build_count` from `iwa_builds.deck_builds`. Emit PP7 names keyed by **Keynote
slide number** and stage ordinal. **Verify** that the total consumed equals the
number of files produced; on any mismatch **refuse and report** — never guess an
alignment. (The `+1` — one stage for the pre-build state plus one per build — was
confirmed on PK slides 14 and 17: 4 files with `all stages:true`, 2 with it off.)

**Destination extension.** Movie exports must target **`.m4v`**; a `.mov`
destination is rejected by the exporter with error `".mov" (6)`.

**Codec.** ProRes 422HQ at 3840×1080/30fps runs roughly **5GB per 30 s**. Default
the intermediate to **AppleProRes422LT** or **h264**; 422HQ only on request.
`native size` is required for any codec choice to apply at all.

## Exporter (standalone)

`d5b`. The **Exporter** is `d5`'s asset machinery pointed at a DSK deck instead of
at the generator's output — a first-class feature, because the owner has
hand-built DSK decks that never came from this pipeline and still need PP7 assets.

**Input.** Any 1920×1080 DSK Keynote — hand-built (e.g.
`~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key`) or produced by the
Generator, or by the Maps tab (`d8`).

**Output.** The same PP7 asset folder as `d5`: true-alpha ProRes 4444 clips
**one per build step** on `built` slides, a movie clip per `movie` slide, an
**alpha PNG** per `static` slide where the slide goes transparent (the KPF
lead-fill strip is proven to work only where there is no full-bleed backing — see
the live probe; slides that stay opaque are reported, not silently emitted), and
the same naming convention and manifest JSON as `d5`.

**What it reuses.** `dsk_plan.py`'s classifier (`d1`) runs unchanged — its inputs
are `iwa_builds.deck_builds` plus offline item kinds, neither of which cares about
canvas width — except that the centre-panel filter is **skipped**: a DSK deck is
not an LW wall, `map_remap.is_lw_wall(1920, 1080)` is false and
`is_side_panel_item` (`map_remap.py:446`) correctly returns `False` for every
item, so the whole slide is in scope. `dsk_movie_export.py` (`d3`) is reused for
the export batch, the `skipped`-toggle per-slide mechanic, the display poke, the
process lock and the RSS watchdog.

**What it does NOT do.** No band affine (`d2`) — the deck is already at DSK
geometry. No scratch centre-panel deck and no `-CENTRE_ORIGIN_X` translation —
the export deck is a plain **`ditto` copy with the non-selected slides deleted or
`skipped:true`**, which is strictly simpler than the generator's scratch deck. No
deck assembly (`d4`), no stroke patch, no layout import: the input deck's layouts
are already 1920-wide.

**Selection.** Same surface as the Generator: `range_from`/`range_to`/`slides`
as the pre-filter on propose, per-slide include toggles in the review page as the
authority.

**Relationship to `d8`.** The Maps tab's DSK export produces a DSK deck; once the
Exporter exists, `d8` can simply **hand that deck to the Exporter** for PP7
assets rather than growing its own export path. `d8`'s own scope stays the shared
movie-crop utility.

## Operator rules (live runs)

- Work dir under `~/Desktop` or repo `output/` — **never `/private/tmp`**.
- Back up and quit the owner's open documents before touching Keynote; verify the
  original is byte-unchanged afterwards.
- One Keynote automation at a time (process lock).
- Refuse to start while the display is locked, or poke it periodically.
- Watch RSS; abort on threshold.
- Always operate on a copy; never the owner's deck.

## Insert mode (stretch, `d7`)

**Owner (Q9, 2026-09-10):** the primary output is a **NEW DSK deck**. Verse slides
are produced manually (before or after) for now, and should eventually come from
the sermon generator. `d7` therefore **stays a stretch** — the "closer to core"
reading above is withdrawn. Accept `--dsk-existing <deck.key>` when it ships.

Propose returns the existing deck's slide list plus the new FW-derived slides;
the operator drags each new slide to its position. Reuse the interaction, not the
model: `dashboard/src/tabs/MapsTab.tsx:752-789` (`handleSlideDragStart` /
`handleSlideDragOver` / `handleSlideDrop`, with the `before/after` midpoint test
and the `draggedIndex < toIndex ? toIndex-1` fix) and the index math of
`moveSlideTo` (`dashboard/src/maps/types.ts:345-362`), in a new lighter component
over a plain `{id, thumb, index}` array. **Do not** import `MapsDocument` — its
`restitchLinks` / `clearMovieFields` / `outgoingPairs` machinery is Maps-specific.
On apply, slides are spliced into the existing deck live
(`duplicate slide N to after slide M` / `move`), not by an offline slide-list
rewrite, since offline write is still default-off.

## API and UI

Mirror `/api/resize`'s three phases in `src/obed_edom/web/app.py`:

- `POST /api/dsk` — replaces the 501 stub at `:494`. It takes the resizer's
  **slide-selection form fields verbatim**: `range_from: int | None = Form(None)`,
  `range_to: int | None = Form(None)`, `slides: str = Form("")`, resolved through
  `map_remap.resolve_slides(spec=slides or None, range_from=…, range_to=…)`
  (`map_remap.py:2953`) exactly as `resize_keynote` does (`app.py:506-531`), and
  persisted on the job result as `slideRange` so apply re-reads it the way
  `apply_resize` does (`app.py:607-608`). This is a **pre-filter only**: propose
  classifies just the selected slides, and the **review page's per-slide include
  toggles are authoritative** — apply converts exactly the slides whose decision
  says include, so the operator can drop a slide the range let through, but
  cannot add one the range excluded without re-proposing. **Propose is live,
  read-only and short**, not offline: `_run_resize_propose` (`:1266`) calls
  `acquire_wall_payload`, which combines the IWA read with a **bulk Keynote
  geometry pass**, and it renders live slide-image thumbnails. Only the
  **classification** step is offline. Label it that way in the UI and in the job
  log so the operator knows Keynote will open. Returns
  `{pages: [{index, thumb, category, buildCount, movieCount, action, anchor}]}`.
- `POST /api/dsk/{job_id}/review` — a `DskDecisionsBody` shaped like `FramingsBody`
  (`:115`, `{decisions: [{wallIndex, ...}]}`) and persisted the same way
  `save_resize_framings` (`:564`) does, so a re-propose keeps the answers. Each
  decision carries `{wallIndex, include, action, anchor, overlay, keepSideContent}`.
  `keepSideContent` **reuses the resizer's field name and semantics**; read it
  back with a `_side_content_slides_from_result` sibling (`app.py:1212`) so the
  per-slide whitelist is derived identically on both features.
- `POST /api/dsk/{job_id}/apply` — runs crop + assembly, polled through the existing
  `GET /api/jobs/{id}`; accepts a decisions body like `apply_resize` (`:592`).
- `POST /api/dsk/export` + `POST /api/dsk/export/{job_id}/review` +
  `POST /api/dsk/export/{job_id}/apply` — the **Exporter** (`d5b`), mirroring the
  three generator phases exactly: propose classifies the given DSK deck's slides
  (offline classify, live thumbnails, same `range_from`/`range_to`/`slides`
  pre-filter), review persists the per-slide include/action decisions, apply runs
  the export batch. Feature tag `dsk-export`, so History/sessions
  (`dashboard/src/sessions.ts:29`, `HistoryTab.tsx:38`) keep it separate from the
  generator's `dsk` runs.

**Dashboard tab: "DSK Generator" → "DSK", with two sub-tabs.** The label lives in
two places and both must change: `dashboard/src/App.tsx:24`
(`{ id: "dsk", label: "DSK Generator" }` in the `TABS` array) and
`dashboard/src/nav.ts:10` (`FEATURE_LABELS.dsk`); `nav.ts:20`
(`OPEN_IN_LABELS.dsk`, "Open in DSK Generator") becomes "Open in DSK". The
`FeatureId`/`TabId` union stays `"dsk"` (`nav.ts:3`) — this is a label and
sub-navigation change, not a new top-level tab, so `App.tsx:115`, `sessions.ts:29`
and `HistoryTab.tsx:38`/`:136` keep working.

**No sub-tab pattern exists in the tab registry** — `App.tsx`'s `TABS` array is
flat and neither `MapsTab` nor `SettingsTab` has sub-navigation. Use the repo's
existing **segmented control** instead, inside `DskTab.tsx`: a
`<div className="seg">` of `<button className={sub === "…" ? "on" : ""}>`, styled
by `dashboard/src/styles.css:901-911` and already used at
`components/GenerateResultView.tsx:91-103` and `tabs/MapsTab.tsx:2347`. Sub-tab
state is local `useState<"generator" | "exporter">("generator")`; persist the last
choice via `dashboard/src/prefs.ts` if that is cheap, otherwise default to
Generator. Split the current 126-line `DskTab.tsx` body into
`tabs/dsk/DskGenerator.tsx` and `tabs/dsk/DskExporter.tsx`, leaving `DskTab.tsx`
as the segmented shell.

Frontend: extend `dashboard/src/tabs/DskTab.tsx` (drop `stubDsk`,
`dashboard/src/api.ts:233`) with a **new lighter per-slide review list** — thumbnail,
category chip, build/movie counts, an action select (in-deck / export / both / skip),
a horizontal-anchor select, an include toggle, **a "keep side panels" checkbox
(default off, mirroring `FramingReview.tsx:964` and its bulk keep/drop buttons at
`:519`/`:528`)**, **and a stat-overlay select (bake into clip [default] / clip
only)**. Above the list, a range/slides input feeding `range_from`/`range_to`/
`slides` on the propose call. Do **not** reuse
`components/FramingReview.tsx` (1013 lines): its affine/anchor-pairing UI is
CG-specific. `cd dashboard && npm install && npm run build` after any
`dashboard/src/**` change (SKILL.md).

## Phasing

Each tranche is a PR. "Offline" = no Keynote, testable in CI. "Live" = an
operator-run, hands-off Keynote window on a **copy**.

1. **`d1` classifier — offline.** Acceptance: on `Sermon_PK (GW).key` the
   classifier reports builds on {2, 3, 5, 6, 7, 17, 20, 32, 33, 37, 44, 54} and
   `movie` on {32, 33} (measured); on `Sermon_PK (DSK)_with mistakes.key`,
   `deck_builds` reports builds on {5, 13, 14, 17, 26, 29, 30}; categories match a
   checked-in expectation; no Keynote process starts (assert in the test, per the
   `resizer-operator-rules` under-mocking trap).
2. **`d2` band affine — offline.** Acceptance: reading
   `Sermon_PK (DSK)_with mistakes.key` yields band `h = 350`, bottom `= 1054`,
   envelope `x ∈ [26, 1894]`, and finds **both** slide-4 items; a 3840×1080 source
   item maps to a 1868×350-contained rect; **`Sermon_PK (GW).key` slide 32's
   3840×2160 movie at (1920, −763) fits from its visible rect, not its declared
   rect** (the naive `band_h/src_h` answer is rejected); a reference with <3 band
   items refuses. **Side content:** with `keepSideContent` off (the default) a
   side-panel-only item contributes nothing to the fit; with it on for that slide
   only, the fit is taken over the union rect against the full 7680×1080 wall, the
   result is width-bound inside the 26…1894 envelope, every kept item shares one
   scale, and the neighbouring slides are **unchanged** (the whitelist does not
   propagate, per `church-list-keep-side-panel-spec`); the reported height for a
   full-wall union is < band height (width-bound).
3. **`d3` movie crop — live, feature-flagged.** The alpha probe is **done** (see
   "Alpha probe results"), so `d3` is now scoped to the **opaque** movie path plus
   the plumbing every alpha route needs. Acceptance (operator): one FW movie
   slide → scratch deck → exported **`.m4v`** (a `.mov` destination must be
   rejected by our own path check before Keynote sees it) → **ffprobe reports the
   expected dimensions *and* a duration matching the model** (per-slide hold 5.0 s
   + build delay 2.0 s per build + the measured transition duration, or the
   embedded movie's own length where longer); QuickTime opens it; the crop matches
   the centre panel; the runner refuses on a locked display or pokes it; the RSS
   watchdog fires on a synthetic threshold **and its default threshold is above
   the measured 1.41 GB peak**; and a per-build cut at the measured boundaries
   (first change at frame 61 / t = 2.033 s) reproduces on a `built` slide.
   `d3` does **not** implement an alpha route — that is gated on Open question 13,
   and route (iv) additionally on "Next live probe (difference matte)".
4. **`d4` deck assembly — live.** Acceptance: DSK deck opens; a `static` slide's
   media sits in the band; **no kept slide's base layout is an FW/7680-wide
   layout**; `card_styles` on the output reports the kept media styles as
   white/`TSDSolidPattern`/5.0, and any style whose refs escape the kept band media
   is **refused and reported** rather than patched; `verify_builds` reports **0
   surplus** on kept slides; `movie` slides have transition `none`; presenter notes
   are present; a masked image's mask scales with its frame after the live
   width/height write (no content revealed or clipped);
5. **`d5` PP7 export folder — offline (naming) + live (content).** Acceptance:
   `built` slides yield **one asset per build step** (N builds → N+1 stages → the
   route's asset count, each showing only that step, verified by frame- or
   pixel-diff); assets carry **real alpha** — route (iii) stage PNGs are RGBA with
   a non-trivial transparent fraction (measured 0.014–0.022 opaque on the probe
   slides), routes (ii)/(iv) produce ProRes 4444 with
   `ffprobe pix_fmt = yuva444p10le` **and a background region whose mean alpha is
   ≈0** (the plane existing is **not** sufficient — Keynote's own ProRes 4444
   passed the `pix_fmt` check while being fully opaque, so this acceptance line
   MUST assert alpha statistics, not the pixel format); `movie` slides yield an
   **opaque `.m4v`** clip and that is expected, not a failure; **slide/stage
   attribution is reconstructed by the normative rule above and the count check
   refuses on mismatch** (the exported `<basename>.NNN.png` names carry no slide
   number); inserted clips carry the FW movie's `repetition method` and
   `movie volume`; the stat-overlay bake/no-bake choice from the review page is
   honoured; a manifest JSON lists slide → build index → asset **and records which
   alpha route produced each one**. Per-build asset generation and the
   naming/manifest work are separate PRs, and the alpha route is not started until
   Open question 13 is answered.
6. **`d5b` Exporter — offline (classify/selection) + live (export).** Acceptance:
   pointed at `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key`, the
   classifier reports its **7 built slides {5, 13, 14, 17, 26, 29, 30}** and its
   **1 movie slide (13)** with no Keynote process started; selecting all of them
   yields **N assets for the build slides** (one per build step, N = the deck's
   total build count, cross-checked against the `stage_count = build_count + 1`
   reconstruction), **1 opaque `.m4v` movie clip**, and an alpha PNG per selected
   `static` slide (route (iii) gives this for free from the same
   `all stages:true` export; the KPF lead-fill strip remains the fallback and
   slides that stay opaque are reported, not silently emitted), plus the `d5`
   manifest; the
   export deck is a `ditto` copy with non-selected slides deleted/`skipped`, and
   **no band affine and no scratch centre-panel deck run at all** (assert in the
   test); the owner's input deck is byte-unchanged.
7. **`d5c` KPF alpha pipeline — live, shared with alpha playback.** Acceptance:
   on a copy of the PK DSK deck, the export → strip → player-driver → per-build
   capture pipeline produces **per-build clips for the 7 build slides** with real
   alpha statistics (background region mean alpha ≈ 0, per the `d5` acceptance
   rule — `pix_fmt` alone is not sufficient); the **Magic Move slide from
   Sermon_GW is captured with motion** (not two stills); a **fidelity report**
   lists any build effect the player simplified against `iwa_builds.deck_builds`
   for that deck; movie slides fall back to the opaque `.m4v` path (a); Playwright
   is pinned in an optional extra (matching the `iwa` extra in `pyproject.toml`),
   not a hard dependency.
8. **`d6` API/UI — offline.** Acceptance: propose/review/apply round-trips against a
   stubbed runner for **both** `/api/dsk` and `/api/dsk/export`; the
   `range_from`/`range_to`/`slides` pre-filter narrows the proposed page list and
   the review page's include toggles override it (a slide inside the range but
   toggled off is not converted); a per-slide "keep side panels" toggle
   round-trips through the decisions body and reaches the runner as a
   `side_content_slides`-style set; the tab reads **"DSK"** with working
   **Generator** / **Exporter** sub-tabs; `npm run build` clean; `POST /api/dsk`
   no longer returns 501.
9. **`d7` insert mode — offline UI + live splice.**
10. **`d8` maps reuse.** Acceptance: a Maps job with a movie item and `export_dsk=True`
   produces a cropped clip instead of a scaled full-panel one; image behaviour
   byte-identical to today. Once `d5b` has shipped, the Maps DSK deck is handed to
   the **Exporter** for PP7 assets rather than growing a second export path.

## Open questions for the owner

1. **"3840×1920" — partially answered.** The sample's clip is 1920×540, which is a
   3840×1080 centre-panel deck exported at the **1080p preset** (fit-width 1920),
   not at native size. Confirm the scratch deck is 3840×1080 and that "1920" was
   the export width. Should we keep the 1080p preset (matching the owner's current
   output) or move to native size for a sharper master?
   **Owner (2026-09-10):** "Yeah, 3840x1080 is LW, then scaled down. Exporting
   native size would be good." → plan change: the scratch deck is **3840×1080**
   and export is **`movie format:native size`**, not the 1080p preset; the
   downscale to the DSK band happens afterwards in ffmpeg/geometry.
2. Does PP7 need **true alpha** movies, or are opaque movies (+ PNG stages for build
   slides) enough? This decides whether option (b)/(c) ships at all.
   (Both did, in a sense: (b) became route (iv) and (c) route (ii) — see Q13.)
   **Owner (2026-09-10):** "True alpha movies. Exporting as Apple ProRes 4444 is
   an option. Not sure how it works for builds, but it should be 'on-click' per
   animation." → plan change: alpha is **core, not stretch**; `built` slides
   export **one asset per build step**.
   **ANSWERED by the alpha probe (2026-09-10): "ProRes 4444 is an option" is
   FALSE.** Keynote's own ProRes 4444 export carries **no alpha** — the plane is
   present (`yuva444p12le`) but constant 255 in every frame, on both Basic White
   and Basic Black, and on PK slides whose PNG export of the same pixels is
   RGBA(0,0,0,0). The remaining routes and the recommendation move to **Open
   question 13**.
3. **Slide 32 of `Sermon_PK (GW).key`** holds a 3840×2160 movie at (1920, −763),
   centre-cropped by the canvas. Intentional framing, or an accident to flag?
   **Owner (2026-09-10):** "Intentional. top & bottom are 'cropped'. would be
   nice to apply image mask for this beforehand I suppose, but damn Apple
   restriction, ugh." → plan change: off-canvas framing is deliberate; the
   scratch-deck export bakes the crop (current design unchanged). The wish for a
   pre-applied mask is logged as future work under the crop workstream.
4. **Timing.** QuickTime export has no duration keys; Keynote's self-playing
   defaults are 5.0 s per slide and 2.0 s per build. Is that the wanted pacing for
   PP7 assets, or should the pipeline re-time clips in ffmpeg — and to what
   seconds-per-build / seconds-per-slide?
   **Owner (2026-09-10):** "Links to (2)?" → plan change: yes — timing is
   subsumed by the per-build "on-click" answer. Each asset covers **one** build
   step, so Keynote's 5.0 s hold / 2.0 s build delay become **cut points**, not
   pacing to preserve; trailing/leading hold is trimmed in ffmpeg.
5. Border spec: measured **white, solid, 5.0pt** on the sample (including the movie).
   Confirm 5.0pt is the intended house value and not one deck's drift — two other
   white 5.0pt styles exist with slightly different white (0.99994, 0.99999, 0.99988).
   Also: slides whose stroke style is shared with non-band objects will be
   **refused and reported** — is manual bordering on those acceptable?
   **Owner (2026-09-10):** "Yes, house value. Instead of refusing, try keeping to
   source stroke style." → plan change: 5.0pt white is the house value, but the
   **primary behaviour is to keep the SOURCE object's stroke**; refuse is no
   longer the primary path (the shared-style guard survives).
6. Band spec: measured **h = 350, bottom = 1054, x envelope 26…1894**, horizontal
   anchor varying (centred, right-anchored, full-bleed). Should the DSK template gain
   a real band placeholder so the band stops being inferred from a sample?
   **Owner (2026-09-10):** "There should be, need church staff for this. note it
   as something to be tied down. assume current values as the default
   placeholder." → **STAYS OPEN** as an external dependency (church staff). The
   measured values (h 350, bottom 1054, x 26…1894) are the default placeholder
   until then.
7. **Cropping.** 88 of 131 masked images in the sample are real crops of the FW
   panel. The pipeline **cannot create crops** (no sdef mask, offline crop writes
   refused) — it will scale to the band and leave editorial cropping to you in the
   editable deck. Is that acceptable, or is auto-cropping essential enough to fund
   a separate mask-authoring workstream?
   **Owner (2026-09-10):** scale-only is acceptable. Copy the image together with
   its existing mask from the LW deck into the DSK deck and scale it; the operator
   adjusts the crop manually afterwards. (The same day, the owner **revised** the
   "side panels are ignored entirely" half of this answer: side content is dropped
   by **default**, with a per-slide "include side content" toggle mirroring the
   resizer's `keepSideContent` — see Classification.)
8. The stat overlay ("1.9% Christians", top-right of the band) — is it FW wall content
   that should flow through automatically, or DSK-side text typed after import?
   **Owner (2026-09-10):** "What I did was to bake it in together with the video.
   Flag it in the review stage, give operator both options (bake vs just video,
   manually add)." → plan change: the review page gains a per-slide overlay
   choice, defaulting to **bake**.
9. **Insert mode is closer to core than stretch**: 63 FW slides → 43 DSK slides,
   because the DSK is FW-derived media *plus* template verse slides. Do those verse
   slides come from this repo's existing `generate --dsk-template` output, or from a
   deck you build separately? Should `d7` move ahead of `d5`/`d6`?
   **Owner (2026-09-10):** "it should eventually come from the sermon generator,
   but now assume it will be done manually either before or after. (so might be
   creating a totally new deck)" → plan change: primary output is a **NEW DSK
   deck**; verse slides are manual for now; `d7` insert-mode stays stretch.
10. `built` slides: keep builds live in the DSK deck (as your sample does on 7
    slides) **and** also export them, or export only?
    **Owner (2026-09-10):** "live in the DSK deck for edits" → plan change:
    `built` slides are **both** — builds stay live in the DSK deck (the copy
    carries them) **and** per-build-step clips are exported for PP7.
11. Movie slides in the DSK deck: the sample holds the **exported** clip (aspect
    3.5556, no mask). Confirm the DSK deck should never hold the original FW movie.
    For inserted clips, what `movie volume` and `repetition method` do you want —
    muted/loop for a background plate, or full volume/none for a played-through
    clip? (The sample's clip carries an AAC track from the export.)
    **Owner (2026-09-10):** "Confirm. op can manually copy over if needed. golden
    rule is to keep to source deck behaviour. so if vid loops, loop. if full
    volume, follow." → plan change: the DSK deck holds only the exported clip, and
    `repetition method` + `movie volume` are **copied from the FW movie object**
    onto the inserted clip.
12. Export-folder naming for PP7 import: per slide number, per cue, or per outline
    point? Movie vs PNG suffix convention?
    **Owner (2026-09-10):** "per slide number, as per 'export as image with
    individual builds ticked option' keynote export" → plan change: names follow
    Keynote's slide-images-with-individual-builds convention, keyed by slide
    number. **sdef finding:** `export options` exposes `image format` (`Kxif`),
    `all stages` (`Kxpa`) and `skipped slides` (`Kxps`) but **no naming, prefix or
    numbering key**, and the `export` command's own table gives `slide images` the
    file extension **`N/A`** (the destination is a folder). The sdef therefore does
    **not** state the pattern. Assume `<deckStem>.<NNN>.<ext>` zero-padded from
    001, with each build stage emitted as its own sequential frame when
    `all stages:true` — **flagged for a one-minute live check in `d5`**.

13. **Alpha route choice — OPEN, escalated 2026-09-10.** The alpha probe closed
    mechanic (i): Keynote's ProRes 4444 export has no real alpha. Three routes
    remain (full detail under "Movie-crop pipeline — options and decision"):
    - **(ii) KPF/HTML + fill strip + headless Chromium capture** → ProRes 4444.
      Animated, true alpha, deterministic per-build via `advanceToNextBuild(`.
      Costs a Playwright/Chromium dependency the repo does not have, inherits the
      KPF player's fidelity limits, and never covers movie slides (KPF exports
      embedded movies separately).
    - **(iii) Keynote-native PNG build stages** — `as slide images {PNG, all
      stages:true}` on the scratch deck, one **RGBA** PNG per stage (proven), fed
      to PP7 as one alpha PNG per click, or as a short ProRes 4444 still-clip per
      stage via ffmpeg. **Zero new dependencies, exact Keynote rendering, real
      alpha.** Limitation: **stages, not animated builds** — Magic Move becomes two
      stills; a cross-dissolve in PP7 approximates the motion.
    - **(iv) Difference matte via `base layout`** — import solid-black and
      solid-white blank layouts, export each target slide twice as ProRes
      422LT/h264 `.m4v`, solve `alpha = 1 - (white - black)` and
      `colour = black / alpha`, encode ProRes 4444 through
      `maps_reveal._run_ffmpeg_stdin`, cut per build at the measured boundaries.
      The probe's frame-determinism (byte-identical holds, frame-exact build
      starts) is what makes the two passes alignable. Animated, true alpha,
      Keynote's own renderer, no Chromium. Costs 2× export, needs its own probe,
      and mattes **background-dependent effects (drop shadows, blend modes)**
      imperfectly.

    **Recommendation:** **(iii) for a first tranche** — it unblocks the PP7
    handoff with zero dependencies and exact rendering; **(iv) as the animated
    upgrade**, gated on "Next live probe (difference matte)"; **(ii) only as a
    fallback** if (iv)'s matte quality fails. The trade-off the owner is being
    asked to make: **stills now with no new dependencies (iii)**, vs **animation
    at 2× export cost and a matte that is imperfect on shadows (iv)**, vs
    **animation at the cost of a second renderer and a browser dependency (ii)**.
    Movie slides go through the opaque path in all three worlds.

    **Owner (2026-09-10):** (iii) is today's manual practice — automate it first.
    (ii) is the strategic route: it is the same KPF pipeline as the alpha-playback
    app, so one build serves both PP7 asset export and live alpha playback.

## Risks

- **`.mov` destination is rejected — use `.m4v`.** `export … as QuickTime movie`
  to a path ending `.mov` fails with error `".mov" (6)`; `.m4v` works and yields a
  qt-branded ProRes file. Any hardcoded `.mov` in `d3`/`d5`/`d5b` is a run-killer
  discovered only at export time, so validate the destination extension before
  handing the path to Keynote and rename after ffmpeg if a `.mov` is wanted.
- **`all stages` memory correction.** The 2026-09-08 memory recorded `all stages`
  as not honoured. That is now known to be **wrong for the slide-images
  exporter** (4 files with it on vs 2 with it off, distinct stages confirmed by
  consecutive diffs). It stays inert for the **QuickTime** exporter. Route (iii)
  depends entirely on the corrected reading, so re-confirm it on the real deck
  before building on it, and do not let the stale memory line be re-imported.
- **Alpha "present" is not alpha "real".** Keynote's ProRes 4444 export passes a
  naive `pix_fmt` check (`yuva444p12le`) while being fully opaque. Every alpha
  acceptance line in this plan must assert **per-frame alpha statistics on a
  background region**, never the pixel format alone.
- **Matte assumptions (route iv).** The matte solve assumes the two passes are
  **frame-aligned** and that content is composited **premultiplied over black**.
  Neither is guaranteed for **background-dependent effects — drop shadows, blend
  modes, translucent fills** — which will matte imperfectly, nor for embedded
  movies unless the movie region is opaque. Anti-aliased edges are the sharpest
  test. Gate the route on its own probe, and keep a per-slide fallback to (iii)
  for slides whose residual exceeds the gate rather than shipping a bad matte.
- **Locked display stalls Keynote's exporter.** 208 s vs 11 s on the same export;
  `caffeinate -dimsu` is insufficient, only a real display poke resumes it. An
  unattended overnight run will appear hung. Mitigation in Operator rules.
- **Concurrency.** Two Keynote scripts collide destructively (one's
  `close every document` killed the other's export). Strictly serial + a lock.
- **Non-scriptable movie timing.** No duration keys in `export options`; the
  5.0 s hold / 2.0 s build delay defaults are all we get from Keynote. If the
  owner wants different pacing it must be done in ffmpeg after the fact
  (Open question 4), which for click-advance builds means cutting on detected
  frame changes — unbuilt.
- **Cropping is out of scope** (see the blocker). If the owner's answer to
  Open question 7 is "essential", the plan's value proposition changes materially.
- **Off-canvas media** silently produces 2×-wrong scales unless the visible-rect
  intersection is used everywhere. Covered by a `d2` acceptance line.
- **Layout/master leakage** into both the DSK deck and every exported clip unless
  the CG layout-import step runs on both decks.
- **Export-time / hands-off window.** Measured at 11–18 s per slide, so far
  cheaper than feared, but the 6.7GB `Full_Report_Card_Wall.key` case is still
  unmeasured, and the machine must be untouched throughout.
- **Native-size cap is only partly known.** 7680×1080 exports fine, so the sdef's
  "up to 4096×2160" is not enforced there; behaviour **above 2160 height is
  unverified**. Assert and refuse on tall canvases rather than assume.
- **Media-style stroke write is new code.** `patch_stroke_widths` is proven for width
  only; setting colour/pattern is an untested extension of a probed-safe single-member
  patch. Gate it behind read-back verification, and refuse-and-report rather than
  fall back to the white-rectangle shape (which needs a GUI z-order raise).
- **Deck size.** A copy-and-transform DSK deck starts at FW size (up to 6.7GB).
  **"The saved output shrinks" is UNVERIFIED** — Keynote may not purge unreferenced
  `Data/` payloads on save. Measure the saved size after the deletes in `d4`; if it
  does not shrink, the only known remedy is *File → Reduce File Size*, which is
  **GUI-only** (no sdef command), so it becomes an operator step or an
  Accessibility-driven GUI pass.
- **KPF fidelity (if route (ii) ships).** Unsupported builds/transitions are simplified by
  Apple's player, movies are not in the canvas capture at all, and slides with a
  full-bleed background image stay opaque even after the lead-fill strip.
- **Offline write remains default-off** (`OBED_OFFLINE_WRITE`, W1 still RED). Every
  offline operation here (`verify_builds` read, the stroke patch) is a read or one of
  the already-unconditional stylesheet patches, not a geometry write — keep it
  that way, or the DSK generator inherits W1's blocker.
