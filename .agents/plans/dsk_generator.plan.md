---
name: DSK generator
overview: >-
  Automate the owner's hand-built FW→DSK lower-third workflow. Input: a finished
  LW/FW wall Keynote (7680×1080, centre panel 3840×1080 at x=1920). Output: an
  editable 1920×1080 DSK Keynote whose FW content sits in the lower-third band
  with a white 5pt border, plus an export folder of movies/PNGs for
  ProPresenter7, because Keynote can mask an image but not a movie and emits no
  alpha in live playback. Slides are classified offline (`iwa_builds.deck_builds`
  + kind counts), the operator confirms per slide in a review page (resizer/
  checker pairing pattern), and apply runs the movie-crop pipeline and the deck
  assembly. The movie-crop utility is shared so `maps_keynote.export_maps_job
  (export_dsk=True)` can stop leaving movies at wall geometry. All probe numbers
  below are measured 2026-09-10, read-only, without launching Keynote.
todos:
  - id: d0-probe-record
    content: "DONE (2026-09-10, read-only): sdef + template/sample band + border measured. See Probe results."
    status: completed
  - id: d1-classifier
    content: "Offline slide classifier (`dsk_plan.py`) over `iwa_builds.deck_builds` + offline kinds; no Keynote."
    status: pending
  - id: d2-band-affine
    content: "Read the DSK band rect from a reference DSK deck/template; contain-fit affine per item; no hardcoded band."
    status: pending
  - id: d3-movie-crop
    content: "Shared `dsk_movie_export.py`: scratch 3840×1080 centre-panel deck → QuickTime export → ffmpeg crop/scale."
    status: pending
  - id: d4-deck-assembly
    content: "Assemble the DSK deck by copy-and-transform of the FW deck (keeps builds), band affine, white 5pt stroke."
    status: pending
  - id: d5-pp7-export
    content: "Export folder for PP7: per-slide movie and/or PNG stages, deterministic naming."
    status: pending
  - id: d6-api-ui
    content: "Replace the `POST /api/dsk` 501 stub with propose→review→apply mirroring `/api/resize`; extend `DskTab.tsx`."
    status: pending
  - id: d7-insert-mode
    content: "Stretch: accept an existing incomplete DSK deck and choose insertion positions (MapsTab drag-drop pattern)."
    status: pending
  - id: d8-maps-reuse
    content: "Follow-up: point `maps_keynote.dsk_ops`/`dsk_item` movie items at the shared crop utility."
    status: pending
  - id: d9-open-questions
    content: "Get the owner's answers to the nine numbered Open questions before d3/d4 land."
    status: pending
---

## Context

The owner hand-builds the DSK (1920×1080, lower-third feed to ProPresenter7)
from the finished FW/LW wall deck. Images are shrunk with Keynote's image mask.
Movies cannot be masked, so the owner copies the FW content into a new Keynote,
exports it as a movie (which bakes the crop), imports that movie into the DSK
deck and applies a white border by hand. Keynote emits no alpha in live
playback, so build slides and movie slides must additionally be handed to PP7 as
pre-rendered assets rather than played live from Keynote.

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
  `format360p/540p/720p/1080p/2160p` and `native size` — and native size is
  documented as *"the same dimensions as the document, **up to 4096×2160**"*.
  A 7680×1080 document therefore cannot export at wall resolution; the scratch
  deck must be ≤4096 wide. This is the single hardest constraint on the movie
  path and the draft plan missed it.
- `movie codec` is documented as *"codec for movie exported **at native size**"* —
  the ProRes choices only apply to a `native size` export.
- `movie codecs`: h264, AppleProRes422/422LT/422HQ/422Proxy/4444, HEVC.
  `movie framerates`: 12/23.98/24/25/29.97/30 (and higher entries below).
- `slide` has `skipped` (`Kskp`) **rw** — per-slide export is achievable by
  toggling `skipped` on a scratch copy and exporting with `skipped slides:false`.
  There is no per-slide export command.
- `document` `width` (`sitw`) / `height` (`sith`) are **rw** and this is not
  theoretical: `maps_keynote.build_deck_script` (`:1262-1265`) already does
  `make new document` → `set width of theDoc to N` → `set height of theDoc to N`
  → save → close → reopen → bind `document 1` by stem. That is the answer to
  "how does maps_keynote build decks at a chosen size", and it removes the
  draft's "unverified/risky, treat as an open question" caveat.
- `image` exposes `file` (r), `file name` (rw), `opacity`, `rotation`,
  `reflection *` — **no stroke, no mask**. `movie` exposes `file name`,
  `movie volume`, `repetition method`, `opacity`, `rotation` — **no `file`
  property at all, no stroke, no mask**. Confirms SKILL.md: a border must come
  from the offline `Index/DocumentStylesheet.iwa` route or from a template
  object that already carries it.

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
mask images. Builds exist on 7 slides (5, 13, 14, 17, 26, 29, 30), so the
hand-built DSK **does keep some builds live in-deck**.

Media items taller than 150pt (the band content):

| slide | kind | x | y | w | h | aspect |
|---|---|---|---|---|---|---|
| 1 | image | 352 | 704 | 405 | 350 | 1.157 |
| 2 | image | 1315 | 704 | 579 | 350 | 1.654 |
| 4 | image | 1312 | 704 | 579 | 350 | 1.654 |
| 12 | image | 529 | 704 | 861 | 350 | 2.460 |
| **13** | **movie** | **258** | **670** | **1405** | **395** | **3.557** |
| 18 | image | 43 | 704 | 1832 | 350 | 5.234 |
| 31 | image | 1312 | 704 | 579 | 350 | 1.654 |
| 32 | image | 1516 | 704 | 376 | 350 | 1.074 |
| 33/34 | image | 26 | 788 | 1867 | 267 | 6.993 |
| 43 | image | 117 | 725 | 1685 | 326 | 5.169 |

Modal band: **y = 704, h = 350, bottom edge 1054** (7 of 12 items); bottom edge
is 1051–1065 for all of them, i.e. a ~26pt bottom margin. Height 350 is 32.4% of
1080 — a **lower third**, not the bottom half. Horizontal placement is editorial:
centred (cx 960, five items), right-anchored (x+w = 1891/1894, four items), or
full-bleed. Widths follow the source aspect at that height.

**Border, measured:** `iwa_write.card_styles` on the sample returns three white
`TSDSolidPattern` strokes of **width 5.0** — id `3812378` (9 refs, slides 1, 2,
4, 12, 18, 31, 32), `15185477` (3 refs, slides 19, 43), `15303898` (1 ref,
slide 13 = the movie). So the movie carries a **white, solid, 5.0pt** stroke,
same as the images.

**The movie's own numbers settle the "3840×1920" question.** The `TSD.MovieArchive`
has `naturalSize = 1920×540` and `mask = None`. 1920/540 = 3.5556 = 3840/1080
exactly: the exported clip is the FW **centre panel** at half scale, then placed
at 1405×395 (same aspect) in the DSK. So the owner's scratch deck is the centre
panel, not a 3840×1920 canvas; "3840×1920" is almost certainly a slip. Recorded
as Open question 1 rather than assumed.

### Cross-check against `maps_keynote.dsk_item` (`:689-698`)

`DSK_WIDTH=1920, DSK_HEIGHT=1080, DSK_SCALE=0.5, DSK_Y=540` maps the centre panel
to **1920×540 at y=540 — the bottom half**. That does not match the owner's DSK
(1868×350 envelope with a 1054 baseline), and it also *scales* every item rather
than masking anything: `_emit_item` (`:1104-1181`) only sets position/width/height.
So the claim that the Maps DSK export "masks images" is inaccurate — it scales
them, and the same scale is applied to movies, which is why a movie there shows
the whole (squashed-into-half-height) panel. Conclusion: **do not hardcode a band.
Read it from a reference DSK deck** (todo `d2-band-affine`), per memory
`template-size-source-style` — the template/reference gives size, the source gives
content and style.

### Build reality (correcting the draft)

`iwa_builds.plan_build_patch` is a **subset-and-reorder** patch: it keeps
`min(source_count, output_count)` builds per key from the **output's own**
`builds` list and drops the rest. It can never *create* a build, and Keynote's
sdef has no build class. Therefore a DSK deck **built fresh from a template can
never carry a build**. The only way to ship an editable DSK deck with builds
intact is the resizer's own route: **copy the FW deck and transform its objects
in place**, exactly as `remap_keynote` does (`ditto` at `:534`), then use
`restore_source_builds` (`remap_keynote.py:693`) to restore each slide's own
build set. This is the central architectural correction to the draft.

## Classification

One classifier, `src/obed_edom/dsk_plan.py`, offline only. Inputs per slide:
`iwa_builds.deck_builds(fw_deck)` (`{number: {slideId, builds, transition, ...}}`)
and the offline item kinds from `offline_inspect.offline_wall_payload`, filtered
to the centre panel with `map_remap.CENTRE_PANEL_RECT` /
`map_remap.is_side_panel_only`. Categories and default actions:

| category | test | default action |
|---|---|---|
| `empty` | no centre-panel item above the backdrop | skip (no DSK slide) |
| `static` | items, no `movie` kind, `builds == []` | **in-deck**: contain-fit into the band, white 5pt stroke. No export. |
| `built` | `builds != []`, no `movie` kind | **both**: in-deck copy with builds preserved via `restore_source_builds`, **and** exported for PP7 (movie or per-stage PNGs — Open question 2) |
| `movie` | any `TSD.MovieArchive` in the centre panel | **export-crop**: scratch-deck movie export → ffmpeg → insert the exported clip into the DSK deck, stroke 5pt, `builds` cleared on that DSK slide (the clip bakes the timing; transition ownership moves to PP7) |
| `mixed` | movie **and** builds/other content | treat as `movie` (the export bakes everything), flag in the review page for operator override |

Keep `deck_builds`'s per-slide-number dict as the primary key so
`restore_source_builds`' slide-number bookkeeping stays consistent downstream.
`built` is a genuine both-ways case: the owner's own sample keeps builds on 7
DSK slides, so "builds always become a movie" would be wrong.

## Movie-crop pipeline — options and decision

**(a) Scratch centre-panel deck → QuickTime export → ffmpeg.**
`ditto` the FW deck to a scratch copy under `output/` (never `/private/tmp`, never
the owner's deck). Set `width`/`height` to **3840×1080** on the open document and
translate every item by `-CENTRE_ORIGIN_X`, i.e. the centre panel becomes the
canvas — this is required, not cosmetic: `native size` export is capped at
4096×2160 so a 7680-wide document cannot be exported at wall resolution. Mark all
slides `skipped` except the target, then
`export theDoc to <file> as QuickTime movie with properties {movie format:native
size, movie codec:AppleProRes422HQ, movie framerate:FPS30, skipped slides:false}`.
Then `maps_movie.ffmpeg_exe()` → `scale`/`crop` to the band pixel size and
re-encode. Insert with `make new image with properties {file:…}` (the Keynote 15
quirk documented at `maps_keynote.py:1119`; `make new movie` no longer imports).
No alpha. This is exactly what the owner does by hand, and it is the recommendation
for the **first tranche**.

**(b) Difference matte over two QuickTime exports** (same slide rendered on a black
background and on a white one; solve `alpha = 1 - (white - black)`, `colour =
black/alpha`). Gives true alpha from a supported export, at 2× export cost, and
needs the scratch deck's slide background flipped twice. Encode with the existing
`maps_reveal._run_ffmpeg_stdin` ProRes 4444 pipe (`prores_ks -profile:v 4444
-pix_fmt yuva444p10le -vendor apl0`, `maps_reveal.py:303-330`) fed numpy RGBA.
**Stretch**, only if Open question 2 comes back "PP7 needs real alpha".

**(c) KPF/HTML export rendered headless.** The draft asserted this route "cannot
capture builds because `all stages` is not honoured". That conflates two things
and is wrong. `all stages` (`Kxpa`, cocoa key `KNPrintEachBuild`) is a **print-layout**
key; memory `resizer-operator-rules` measured 2026-09-08 that the **PDF and
slide-images** exporters ignore it. The HTML/KPF export is a different exporter:
per memory `keynote-alpha-output-via-kpf` (measured 2026-09-10) it ships Apple's
own KPF player (`assets/player/main.js`, pdf.js + WebGL) which **plays** builds
and **Magic Move exported fine on this very Lower-Thirds template**, with
`clearColor(0,0,0,0)` and per-object textures that already carry real alpha. The
player exposes `jumpToSlide(`, `advanceToNextBuild(`, `goBackToPreviousBuild(`.
So (c) genuinely can produce per-build-stage frames: export as HTML, strip the
baked full-slide fill op from page 1 of each slide PDF (the `q Q q /Cs1 cs R G B
sc 0 H m W H l W 0 l 0 0 l h f` prefix; pypdf is already a dependency,
`pyproject.toml:19`), patch the two black body styles, drive the player in headless
Chromium, and either screenshot per build stage (PNG stages for PP7) or capture the
transparent canvas frame-by-frame into `_run_ffmpeg_stdin` for a ProRes 4444 alpha
movie.
**Fidelity limits of (c):** the KPF player simplifies unsupported builds and
transitions; **movies are exported separately by KPF** and are therefore *not* in
the canvas capture — so (c) never replaces (a) for movie slides; it complements it
for build slides. It also adds a headless-Chromium/Playwright dependency the repo
does not have today (no `playwright` anywhere in `src/`).

**Decision.** First tranche: **(a)** for `movie` slides, plus **per-stage PNGs via
(c)** only if the owner answers Open question 2 with "stages, not video". Default
first-tranche behaviour for `built` slides is: keep the builds live in the DSK deck
(possible because the deck is a copy — see below) and export an **opaque** movie via
(a) as the PP7 fallback. (b) and full alpha video from (c) are **stretch**, gated on
Open question 2, and (c) is the better of the two if alpha is required because it is
alpha-native rather than matte-solved.

## DSK deck assembly

**Route: copy-and-transform, not build-from-template.** `ditto` the FW deck to
`output/<stem>/<stem>_DSK.key`, set `width`/`height` to 1920×1080 on the open
document (proven writable — `maps_keynote.build_deck_script:1263`), then move/scale
each kept centre-panel item into the band and delete everything else. Rationale:
builds cannot be created (`plan_build_patch` only subsets), text run styling cannot
be recreated (SKILL.md character-styling gap), and masks/media survive a copy for
free. The trade-off is deck size — a copied FW deck is large — so `d4` must delete
side-panel and dropped items before saving.

**Band affine (`d2`).** Read a band rect from a `--dsk-reference` deck (the sample,
or a future template slide) rather than hardcoding: take media items with h > 150pt,
use the **modal bottom edge** (1054 here) and **modal height** (350) as the band
baseline and height, and the observed min/max x as the width envelope
(26 … 1894). Per item: `s = band_h / src_h`, contain-fit to the envelope width,
horizontal anchor from the operator's per-slide choice (centre / left / right,
defaulting to centre — the sample's modal `cx = 960`). Refuse rather than guess if
the reference deck yields fewer than three band items.

**Do not point the CG resizer at this.** `map_remap` already takes its target size
from the template (`map_remap.py:1274-1275`), so a 1920×1080 DSK template is
accepted — but the resizer places content by **pairing against template objects at
their final size**, and the Lower-Thirds template has no band objects at all. A
dedicated affine (in the spirit of `maps_keynote.dsk_item`, but band-read rather than
`DSK_SCALE=0.5`) is the right tool; reuse `remap_keynote`'s copy/open/geometry-write
machinery, not `map_remap`'s planner.

**Border.** The sdef has no stroke on `image`/`movie`, and
`iwa_write.patch_stroke_widths` only rewrites `mediaProperties.stroke.width` on an
**existing own** stroke (it explicitly refuses inherited-only and missing styles,
`iwa_write.py:1098-1107`). Three options were considered:
1. a bordered placeholder in the DSK template that we replace — **not available
   today**: the template has zero white stroke styles (measured above);
2. a white rectangle shape behind the media via AppleScript — works with today's
   API (`make new shape`, `fill color`) but doubles item count and mis-renders on
   non-rectangular masks;
3. offline media-style patch.
**Chosen: (3), extended.** Because the DSK deck is a *copy of the FW deck*, its
`DocumentStylesheet.iwa` inherits the FW deck's media styles. Add a
`patch_media_stroke` sibling to `patch_stroke_widths` that can **set colour,
pattern and width** (not just width) on a media style archive, applied to the styles
referenced by the kept band media, selected by ref-count/colour exactly as
`match_card_stroke_styles` does — never by id (SKILL.md). Target value from the
measurement: white `TSDSolidPattern`, width **5.0**. If a kept item's style is
inherited-only, fall back to option (2) for that item and report it.

**Builds.** After geometry, run `restore_source_builds(dest, source, slides, say)`
with `slides` = the `built` category only, so each DSK slide reproduces **its own**
FW slide's builds/transition (its docstring, and memory
`reuse-target-builds-match-source`). `movie`-category slides get their builds
cleared instead. `restore_source_builds` must remain the **last** offline patch on a
slide (SKILL.md: a z-order reorder changes every kindIndex).

## Insert mode (stretch, `d7`)

Accept `--dsk-existing <deck.key>` — the reformatted verse slides the generator
already produced (Open question 9). Propose returns the existing deck's slide list
plus the new FW-derived slides; the operator drags each new slide to its position.
Reuse the interaction, not the model: `dashboard/src/tabs/MapsTab.tsx:752-789`
(`handleSlideDragStart` / `handleSlideDragOver` / `handleSlideDrop`, with the
`before/after` midpoint test and the `draggedIndex < toIndex ? toIndex-1` fix) and
the index math of `moveSlideTo` (`dashboard/src/maps/types.ts:345-362`), in a new
lighter component over a plain `{id, thumb, index}` array. **Do not** import
`MapsDocument` — its `restitchLinks` / `clearMovieFields` / `outgoingPairs`
machinery is Maps-specific. On apply, slides are spliced into the existing deck
live (`duplicate slide N to after slide M` / `move`), not by an offline slide-list
rewrite, since offline write is still default-off.

## API and UI

Mirror `/api/resize`'s three phases in `src/obed_edom/web/app.py`:

- `POST /api/dsk` — replaces the 501 stub at `:494`. Propose: classify offline,
  export FW thumbnails the way `_run_resize_propose` (`:1253`) does, return
  `{pages: [{index, thumb, category, buildCount, movieCount, action, anchor}]}`.
- `POST /api/dsk/{job_id}/review` — a `DskDecisionsBody` shaped like `FramingsBody`
  (`:115`, `{decisions: [{wallIndex, ...}]}`) and persisted the same way
  `save_resize_framings` (`:564`) does, so a re-propose keeps the answers.
- `POST /api/dsk/{job_id}/apply` — runs crop + assembly, polled through the existing
  `GET /api/jobs/{id}`; accepts a decisions body like `apply_resize` (`:592`).

Frontend: extend `dashboard/src/tabs/DskTab.tsx` (drop `stubDsk`,
`dashboard/src/api.ts:233`) with a **new lighter per-slide review list** — thumbnail,
category chip, build/movie counts, an action select (in-deck / export / both / skip),
a horizontal-anchor select, an include toggle. Do **not** reuse
`components/FramingReview.tsx` (1013 lines): its affine/anchor-pairing UI is
CG-specific. `cd dashboard && npm install && npm run build` after any
`dashboard/src/**` change (SKILL.md).

## Per-slide export mechanics and cost

One scratch document, opened once, N exports: toggle `skipped` (rw, sdef `:310`) so
only slide *i* is visible, export, repeat. `skipped slides:false` in the export
options keeps the others out. Every toggle is a document mutation, so the deck must
be saved (or at least left dirty and never re-opened) between exports; keep the
document open for the whole batch and close `saving no` at the end.

Cost is the real risk. Each QuickTime export renders the slide in real time or
slower; the FW deck is up to **6.7GB** (`Full_Report_Card_Wall.key`, 155 slides —
still UNMEASURED for whole-deck live work, memory `resizer-operator-rules`), and the
whole run is a **Keynote hands-off window**: the machine, not just Keynote, must be
untouched. Mitigations: (i) only `movie`/`mixed`/`built` slides are exported, which
is a small minority — the owner's own sample has **one** movie in 43 slides; (ii)
build the scratch deck by **deleting** the non-exported slides rather than skipping
them, so Keynote holds one small deck instead of the FW deck; (iii) batch — if K
target slides are non-adjacent, a single export of a scratch deck containing only
those K slides yields one movie that ffmpeg splits at known slide boundaries
(needs fixed per-slide durations; park until measured). Launch with `nohup … &` and
Monitor the log; background Bash is capped at 10 minutes.

Codec/framerate: `AppleProRes422HQ` + `FPS30` at `native size` for the crop source
(intermediate, ffmpeg re-encodes anyway); `h264` only if disk pressure demands it.
`native size` is mandatory for any codec choice to apply at all, hence the
3840×1080 scratch canvas.

## Phasing

Each tranche is a PR. "Offline" = no Keynote, testable in CI. "Live" = an
operator-run, hands-off Keynote window on a **copy**.

1. **`d1` classifier — offline.** Acceptance: on the sample DSK and on a fixed FW
   fixture, categories match a checked-in expectation; `deck_builds` on
   `Sermon_PK (DSK)_with mistakes.key` reports builds on slides
   {5, 13, 14, 17, 26, 29, 30} (measured); no Keynote process starts (assert in the
   test, per the `resizer-operator-rules` under-mocking trap).
2. **`d2` band affine — offline.** Acceptance: reading
   `Sermon_PK (DSK)_with mistakes.key` yields band `h = 350`, bottom `= 1054`,
   envelope `x ∈ [26, 1894]`; a 3840×1080 source item maps to a 1868×350-contained
   rect; a reference with <3 band items refuses.
3. **`d3` movie crop — live, feature-flagged.** Acceptance (operator): one FW movie
   slide → scratch 3840×1080 deck → exported `.mov` → ffprobe reports the expected
   dimensions/duration and QuickTime opens it; the crop matches the centre panel.
4. **`d4` deck assembly — live.** Acceptance: DSK deck opens; a `static` slide's
   media sits in the band; `card_styles` on the output reports the kept media styles
   as white/`TSDSolidPattern`/5.0; `restore_source_builds` reports 0 surplus and the
   `built` slides keep their build counts.
5. **`d5` PP7 export folder — offline (naming) + live (content).** Acceptance:
   deterministic names per Open question 8; a manifest JSON listing slide → asset.
6. **`d6` API/UI — offline.** Acceptance: propose/review/apply round-trips against a
   stubbed runner; `npm run build` clean; `POST /api/dsk` no longer returns 501.
7. **`d7` insert mode — offline UI + live splice.**
8. **`d8` maps reuse.** Acceptance: a Maps job with a movie item and `export_dsk=True`
   produces a cropped clip instead of a scaled full-panel one; image behaviour
   byte-identical to today.

## Open questions for the owner

1. "3840×1920" — the sample's exported clip is **1920×540** (= 3840×1080 at half
   scale, `naturalSize` measured). Is the scratch deck the 3840×1080 centre panel,
   and was 1920 a slip for 1080?
2. Does PP7 need **true alpha** movies, or are opaque movies (+ PNG stages for build
   slides) enough? This decides whether option (b)/(c) ships at all.
3. Border spec: measured **white, solid, 5.0pt** on the sample (including the movie).
   Confirm 5.0pt is the intended house value and not one deck's drift — two other
   white 5.0pt styles exist with slightly different white (0.99994, 0.99999, 0.99988).
4. Band spec: measured **h = 350, bottom = 1054, x envelope 26…1894**, horizontal
   anchor varying (centred, right-anchored, full-bleed). Should the DSK template gain
   a real band placeholder so the band stops being inferred from a sample?
5. The stat overlay ("1.9% Christians", top-right of the band) — is it FW wall content
   that should flow through automatically, or DSK-side text typed after import?
6. `built` slides: keep builds live in the DSK deck (as the owner's sample does on 7
   slides) **and** also export them, or export only?
7. Movie slides in the DSK deck: the sample holds the **exported** clip (aspect
   3.5556, no mask). Confirm the DSK deck should never hold the original FW movie —
   a scaled original would show the whole 3840-wide panel letterboxed into the band,
   which is what `maps_keynote.dsk_item` does today and is presumably wrong.
8. Export-folder naming for PP7 import: per slide number, per cue, or per outline
   point? Movie vs PNG suffix convention?
9. Do the DSK verse slides for insert mode come from this repo's existing
   `generate --dsk-template` output, or from a deck the owner builds separately?

## Risks

- **Export-time / hands-off window.** N QuickTime exports on a large FW deck is the
  dominant cost and cannot run while the operator uses the machine. Mitigated by
  category filtering and a slide-deleted scratch deck; the batching idea is unmeasured.
- **4096-wide export cap.** If a future FW layout needs content wider than the centre
  panel, `native size` export silently downsamples. Assert the scratch canvas ≤4096
  and refuse otherwise.
- **Media-style stroke write is new code.** `patch_stroke_widths` is proven for width
  only; setting colour/pattern is an untested extension of a probed-safe single-member
  patch. Gate it behind read-back verification and a per-item fallback to a white
  rectangle shape.
- **Deck size.** A copy-and-transform DSK deck starts at FW size (up to 6.7GB) until
  the dropped items are deleted; verify the saved output shrinks.
- **KPF fidelity (if (c) ships).** Unsupported builds/transitions are simplified by
  Apple's player, and movies are not in the canvas capture at all.
- **Offline write remains default-off** (`OBED_OFFLINE_WRITE`, W1 still RED). Every
  offline patch here (`restore_source_builds`, the stroke patch) is one of the
  already-unconditional stylesheet/build patches, not a geometry write — keep it
  that way, or the DSK generator inherits W1's blocker.
