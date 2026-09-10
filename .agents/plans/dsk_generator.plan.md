---
name: DSK generator
overview: >-
  Automate the owner's hand-built FW→DSK lower-third workflow. Input: a finished
  LW/FW wall Keynote (7680×1080, centre panel 3840×1080 at x=1920). Output: an
  editable 1920×1080 DSK Keynote whose FW content sits in the lower-third band
  with a white 5pt border, plus an export folder of true-alpha (ProRes 4444)
  clips for ProPresenter7 — one clip per build step on built slides — because
  Keynote can mask an image but not a movie and emits no alpha in live
  playback. Slides are classified offline (`iwa_builds.deck_builds`
  + kind counts), the operator confirms per slide in a review page (resizer/
  checker pairing pattern), and apply runs the movie-crop pipeline and the deck
  assembly. The movie-crop utility is shared so `maps_keynote.export_maps_job
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
    content: "Read the DSK band rect from a reference DSK deck/template; contain-fit affine per item, clipped to the centre panel; no hardcoded band."
    status: pending
  - id: d3-movie-crop
    content: "Shared `dsk_movie_export.py`: scratch centre-panel deck (3840×1080) → native-size ProRes 4444 export → ffmpeg crop/scale; display-poke + RSS watchdog; includes the alpha probe and the (i)/(ii) mechanic decision."
    status: pending
  - id: d4-deck-assembly
    content: "Assemble the DSK deck by copy-and-transform of the FW deck (copy carries builds), live geometry, live deletes, CG-style layout import, white 5pt stroke."
    status: pending
  - id: d5-pp7-export
    content: "Export folder for PP7: true-alpha ProRes 4444, one clip per build step on `built` slides, Keynote slide-number naming, manifest."
    status: pending
  - id: d6-api-ui
    content: "Replace the `POST /api/dsk` 501 stub with propose→review→apply mirroring `/api/resize`; extend `DskTab.tsx`."
    status: pending
  - id: d7-insert-mode
    content: "Accept an existing incomplete DSK deck and choose insertion positions (MapsTab drag-drop pattern). Promoted toward core — see Open question 9."
    status: pending
  - id: d8-maps-reuse
    content: "Follow-up: point `maps_keynote.dsk_ops`/`dsk_item` movie items at the shared crop utility."
    status: pending
  - id: d9-open-questions
    content: "MOSTLY DONE (2026-09-10): owner answered Q1-Q6, Q8-Q12; folded into the body. STILL OPEN: (i) band placeholder in the DSK template — needs church staff; (ii) alpha-for-builds mechanics — pending the live probe."
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
so option (c) remains viable for this plan's slides.

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
`map_remap.is_side_panel_item(item, wall_w, wall_h)` (`map_remap.py:445`).
(There is no `is_side_panel_only`; the earlier name was wrong.
`CENTRE_ORIGIN_X` lives in `maps_geo.py:33`, not `map_remap`.)

| category | test | default action |
|---|---|---|
| `empty` | no centre-panel item above the backdrop | skip (no DSK slide) |
| `static` | items, no `movie` kind, `builds == []` | **in-deck**: contain-fit into the band, white 5pt stroke. No export. |
| `built` | `builds != []`, no `movie` kind | **both**: in-deck copy (builds ride along and stay live for editing) **and** one exported alpha clip **per build step** (on-click per animation) |
| `movie` | any `TSD.MovieArchive` in the centre panel | **export-crop**: scratch-deck movie export → ffmpeg → insert the exported clip into the DSK deck, stroke 5pt; the FW movie object is **deleted**, which clears its builds; the slide's own transition is set to `none` (the clip owns the timing) |
| `mixed` | movie **and** builds/other content | treat as `movie` (the export bakes everything), flag in the review page for operator override |

Side-panel items (outside the centre panel) are dropped unconditionally —
owner decision 2026-09-10; no per-slide whitelist as in the CG resizer.

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
off-canvas media for free, and quarters the intermediate file size. Import the
Lower-Thirds/black layout here too (see the layouts blocker). Then:
`export theDoc to <file> as QuickTime movie with properties {movie format:native
size, movie codec:AppleProRes422LT, movie framerate:FPS30, skipped slides:false}`.
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
**Stretch**, only if Open question 2 comes back "PP7 needs real alpha".

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

**Decision (revised after the owner's Q2/Q4/Q10 answers, 2026-09-10).**

PP7 assets are **true-alpha ProRes 4444 movies**, and on `built` slides there is
**one clip per build step**: asset *k* renders the animation of build *k* only, so
the PP7 operator clicks through the build. `built` slides **also stay live in the
DSK deck** — the `ditto` copy carries the builds for free, and the owner edits
them there. The alpha route is therefore **core, not stretch**; (b), the
difference matte, is dropped to a last resort.

Two candidate mechanics remain, and **both are pending the live probe below**:

**(i) Keynote native ProRes 4444 export.** `export … as QuickTime movie with
properties {movie format:native size, movie codec:AppleProRes4444, movie
framerate:FPS30, skipped slides:false}` from a scratch deck whose slide
backgrounds are set to **No Fill**. Keynote's *GUI* advertises a
transparent-background ProRes 4444 export — but the KPF measurement showed **No
Fill still emits an opaque black fill rect**, and the sdef carries **no
transparency key at all**, so alpha in the `.mov` is **UNVERIFIED**. Per-build
splitting would have to lean on the 5.0 s hold / 2.0 s build-delay defaults, or
on frame-diff cut detection — neither is deterministic.

**(ii) KPF/HTML export + fill strip + headless Chromium player.** Export as HTML,
strip the lead fill op (proven to yield real alpha on lower-third slides), drive
Apple's player **build by build** (`advanceToNextBuild(`) in headless Chromium,
capturing the transparent canvas per frame into
`maps_reveal._run_ffmpeg_stdin`'s ProRes 4444 pipe (`prores_ks -profile:v 4444
-pix_fmt yuva444p10le -vendor apl0`, `maps_reveal.py:303-330`). Segmentation is
**deterministic** — we own the clicks — but it needs a Playwright/Chromium
dependency the repo does not have, and inherits the KPF player's fidelity limits
(unsupported builds/transitions simplified).

**KPF exports embedded movies separately**, so they are absent from the canvas
capture: `movie` slides go through **(i)** (or the opaque QuickTime path) in
either world, and if alpha is needed *around* a movie it must be composited.

**Decision rule.** If probe (i) yields real alpha, **(i) is the movie-slide path**
and the fallback for builds. **(ii) is chosen for per-build segmentation** unless
(i) can be cut deterministically at build boundaries.

## Next live probe (alpha)

**Subject.** A copy of `~/Desktop/Diff-Checker/Sermon_PK (GW).key`, or (cheaper and
preferred) a synthetic **3840×1080** deck with two slides:
- slide A: background **No Fill**, one object with **2–3 builds** (an Appear and a
  Sparkle-like ramp, matching the builds already characterised in the live probe);
- slide B: an embedded movie.

**Export.** `export theDoc to POSIX file "…/alpha.mov" as QuickTime movie with
properties {movie format:native size, movie codec:AppleProRes4444, movie
framerate:FPS30, skipped slides:false}`. Operator rules apply in full: work dir
under `~/Desktop`, process lock, display poke (`caffeinate -u -t 2`), RSS watchdog.

**Measurements.**
1. `ffprobe -show_streams` → **`pix_fmt`**; expect **`yuva444p10le`** if alpha
   survived, `yuv444p10le` if it did not.
2. Per-frame alpha stats: decode `-pix_fmt rgba` raw frames and take numpy
   min/mean/max of the A channel, plus the fraction of fully-opaque pixels, on a
   background region and on the object region.
3. Build segmentation: per-frame diff over the object region; are there flat hold
   segments separable at the **2.0 s** build delay, with the 5.0 s slide hold at
   the ends?
4. Record what the **sdef** and the **GUI export sheet** actually say about
   "transparent background" — the sdef has **no transparency key**, so this is a
   GUI-only claim until measured.

**Acceptance.** Alpha is REAL if the background region's mean alpha is ≈0 across
all frames while the object region shows non-trivial alpha, and `pix_fmt` is
`yuva444p10le`. Builds are DETERMINISTICALLY CUTTABLE if the hold segments are
frame-exact at the 2.0 s delay across all builds on slide A.

**What each outcome decides.**
- **Alpha real + builds cuttable** → mechanic **(i)** for everything; no Chromium
  dependency; `d3`/`d5` are a scratch-deck export plus an ffmpeg split.
- **Alpha real + builds NOT cleanly cuttable** → **(i)** for `movie` slides,
  **(ii)** for per-build clips on `built` slides; Playwright/Chromium enters the
  dependency set.
- **Alpha NOT real** → **(ii)** is the only alpha route; `movie` slides fall back
  to the opaque QuickTime path plus compositing where alpha is needed around the
  movie, and this is escalated to the owner because it changes the PP7 handoff.

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

**Naming (owner Q12).** Assets are named **per slide number**, following Keynote's
own "export slide images with individual builds ticked" convention. The sdef does
**not** document that convention (`export options` has `image format`, `all
stages` and `skipped slides` but **no naming/prefix/numbering key**, and `slide
images` is listed with extension `N/A` — a folder destination). Assume
`<deckStem>.<NNN>.<ext>` zero-padded from `001`, one sequential index per build
stage; **verify against a real `as slide images … {all stages:true}` export in
`d5`** and correct this line.

**Codec.** ProRes 422HQ at 3840×1080/30fps runs roughly **5GB per 30 s**. Default
the intermediate to **AppleProRes422LT** or **h264**; 422HQ only on request.
`native size` is required for any codec choice to apply at all.

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

- `POST /api/dsk` — replaces the 501 stub at `:494`. **Propose is live,
  read-only and short**, not offline: `_run_resize_propose` (`:1266`) calls
  `acquire_wall_payload`, which combines the IWA read with a **bulk Keynote
  geometry pass**, and it renders live slide-image thumbnails. Only the
  **classification** step is offline. Label it that way in the UI and in the job
  log so the operator knows Keynote will open. Returns
  `{pages: [{index, thumb, category, buildCount, movieCount, action, anchor}]}`.
- `POST /api/dsk/{job_id}/review` — a `DskDecisionsBody` shaped like `FramingsBody`
  (`:115`, `{decisions: [{wallIndex, ...}]}`) and persisted the same way
  `save_resize_framings` (`:564`) does, so a re-propose keeps the answers.
- `POST /api/dsk/{job_id}/apply` — runs crop + assembly, polled through the existing
  `GET /api/jobs/{id}`; accepts a decisions body like `apply_resize` (`:592`).

Frontend: extend `dashboard/src/tabs/DskTab.tsx` (drop `stubDsk`,
`dashboard/src/api.ts:233`) with a **new lighter per-slide review list** — thumbnail,
category chip, build/movie counts, an action select (in-deck / export / both / skip),
a horizontal-anchor select, an include toggle, **and a stat-overlay select (bake into clip [default] / clip only)**. Do **not** reuse
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
   items refuses.
3. **`d3` movie crop — live, feature-flagged.** Acceptance (operator): one FW movie
   slide → scratch deck → exported `.mov` → **ffprobe reports the expected
   dimensions *and* a duration matching the model** (per-slide hold 5.0 s +
   build delay 2.0 s per build + the measured transition duration, or the embedded
   movie's own length where longer); QuickTime opens it; the crop matches the
   centre panel; the runner refuses on a locked display or pokes it; the RSS
   watchdog fires on a synthetic threshold; plus **the alpha probe result is recorded** (see "Next live probe (alpha)"):
   `pix_fmt`, per-frame alpha stats, and whether build boundaries are frame-exact
   at the 2.0 s delay. `d3` does not close until the mechanic (i)/(ii) decision is
   written into the plan. The probe + decision is its own small PR ahead of the
   export implementation.
4. **`d4` deck assembly — live.** Acceptance: DSK deck opens; a `static` slide's
   media sits in the band; **no kept slide's base layout is an FW/7680-wide
   layout**; `card_styles` on the output reports the kept media styles as
   white/`TSDSolidPattern`/5.0, and any style whose refs escape the kept band media
   is **refused and reported** rather than patched; `verify_builds` reports **0
   surplus** on kept slides; `movie` slides have transition `none`; presenter notes
   are present; a masked image's mask scales with its frame after the live
   width/height write (no content revealed or clipped);
5. **`d5` PP7 export folder — offline (naming) + live (content).** Acceptance:
   `built` slides yield **one clip per build step** (N builds → N clips, each
   showing only that animation, verified by frame-diff); clips are **ProRes 4444
   with real alpha** (`ffprobe pix_fmt = yuva444p10le`) via whichever mechanic
   `d3` selected; names follow the Keynote slide-images-with-individual-builds
   convention per slide number, **with the real pattern confirmed by one live
   `as slide images {all stages:true}` export** and this plan corrected if it
   differs from the assumed `<stem>.<NNN>.<ext>`; inserted clips carry the FW
   movie's `repetition method` and `movie volume`; the stat-overlay bake/no-bake
   choice from the review page is honoured; a manifest JSON lists
   slide → build index → asset. Per-build clip generation and the naming/manifest
   work are separate PRs.
6. **`d6` API/UI — offline.** Acceptance: propose/review/apply round-trips against a
   stubbed runner; `npm run build` clean; `POST /api/dsk` no longer returns 501.
7. **`d7` insert mode — offline UI + live splice.**
8. **`d8` maps reuse.** Acceptance: a Maps job with a movie item and `export_dsk=True`
   produces a cropped clip instead of a scaled full-panel one; image behaviour
   byte-identical to today.

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
   **Owner (2026-09-10):** "True alpha movies. Exporting as Apple ProRes 4444 is
   an option. Not sure how it works for builds, but it should be 'on-click' per
   animation." → plan change: alpha is **core, not stretch**; PP7 assets are
   ProRes 4444 with alpha, and `built` slides export **one clip per build step**.
   The mechanics stay **open pending the probe in "Next live probe (alpha)"**.
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
   adjusts the crop manually afterwards. Side panels are ignored entirely by this
   converter.
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

## Risks

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
- **KPF fidelity (if (c) ships).** Unsupported builds/transitions are simplified by
  Apple's player, movies are not in the canvas capture at all, and slides with a
  full-bleed background image stay opaque even after the lead-fill strip.
- **Offline write remains default-off** (`OBED_OFFLINE_WRITE`, W1 still RED). Every
  offline operation here (`verify_builds` read, the stroke patch) is a read or one of
  the already-unconditional stylesheet patches, not a geometry write — keep it
  that way, or the DSK generator inherits W1's blocker.
