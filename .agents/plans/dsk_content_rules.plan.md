# DSK content rules (d4b) — plan (rev 2, owner answers folded in)

Worktree `.claude/worktrees/dsk-gen` @ 90bead0. All measurements offline from the IWA graph
(`_load_deck` / `offline_wall_payload` / `derive_kind_index` / `deck_builds`), PIL on the decks'
`Data/` members, and ffmpeg frames on the banked clip. No Keynote was opened.

Owner answers 2026-09-11: Q1 crop the image FILE and replace the media (no mask write);
Q2 a text slide that will not fit the band SPLITS into N DSK slides, one box per slide;
Q3 placement by COUNT (one item → right, more → centred); Q4 the wheelchair slide is GW 48;
Q5 dedupe survivor = lowest `kindIndex`.

---

## Facts (measured)

### F0. Decks

| deck | canvas | slides |
|---|---|---|
| `~/Desktop/dsk-d4-work/Sermon_PK (GW).key` (FW source) | 7680x1080 | 63 (18 `skipped`) |
| `~/Desktop/dsk-d4-work/out-r7/Sermon_PK_DSK.key` (current d4 out) | 1920x1080 | 4 (GW 8,13,17,32) |
| `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key` (golden) | 1920x1080 | 43 |

Golden band over its image/movie rects: bottom **1054**, height **350**, x **43..1892** — identical to
`dsk_assemble.DEFAULT_BAND` (`dsk_assemble.py:52`). Band width 1849.

### F1. Every asset in the GW deck is a MASKED image; the payload rect is the mask AABB

`_compose_record` (`iwa_geometry.py:331`, mask branch at :359) returns the mask AABB for
`TSD.ImageArchive`/`MovieArchive`, so `offline_wall_payload` item rects are **visible** rects, not
frames. Measured (frame / mask-local / naturalSize / originalSize):

| GW | item | frame | mask (local) | naturalSize (px) | originalSize |
|---|---|---|---|---|---|
| 3 | image0 `Yang Zheng_250408_YZ_0613.jpg` | (1920,−981.6,3840x2560) | (0,808,3840x1472) | 6000x4000 | 3840x2560 |
| 5 | image0 `WhatsApp…23.40.20.jpeg` | (1920,−1024.3,3840x2560.5) | (0,0,3840x2560.5) | 5120x3414 | 3840x2560.5 |
| 21 | image0 `Yang Zheng_YZ_0125.JPG` | (1870.6,−940.9,3938.9x2625.9) | (0,0,3938.9x2625.9) | 4608x3072 | 3938.9x2625.9 |
| 24 | image2 `1.png` | (1943.8,−14,503.6x1080) | (0,36.5,503.6x919.4) | 955x2048 | 503.6x1080 |
| any | side panel `SPIRITUALATMOSPHERE_PK.png` | (0,0,7680x1080) | (0,0,1920.3x1080) or (5760.1,0,1919.9x1080) | 7680x1080 | 7680x1080 |

Three invariants this pins down, all needed by the crop design:

- **`naturalSize` on an image/movie is the media's pixel size**, `originalSize` is the unmasked frame
  in points (`iwa_write.py:108-112`), the mask is expressed in **frame-local** points.
- **PIL agrees with `naturalSize` exactly** on every measured member (6000x4000, 5120x3414,
  4608x3072, 1600x1056, 955x2048), and EXIF orientation is absent or `1`. So
  `Image.open(member).size == naturalSize` is a usable precondition, and its failure is the signal
  for an EXIF-rotated asset.
- The side panels are **one** 7680-wide PNG masked twice, which is why `is_side_panel_item`
  (`map_remap.py:446`) sees 1920-wide items.

Data member paths carry a Keynote suffix: `fileName` `WhatsApp Image 2026-08-14 at 09.17.25.jpeg`
→ member `Data/WhatsApp Image 2026-08-14 at 09.17.25-76510.jpeg`. `_build_data_index`
(`offline_inspect.py:44`) throws the raw member name away; the crop planner needs the reverse map.

### F2. Text slides (>10 words in one box) and L/R duplicates

Every GW verse slide is authored as a **mirrored L/R pair** across x=3840. Measured pairs
(`kind`+`kindIndex`, sum of the two centre-x offsets about 3840):

| GW | verse | pair | offset sum |
|---|---|---|---|
| 7 | Genesis 1:1 | text0/1 ↔ text2/3 (+shape0 ↔ shape2) | 0 |
| 8,10 | Genesis 1:3 / 1:26 | text0/1 ↔ text2/3 | 0 |
| 17 | John 17:21 | text0/1/2 ↔ text3/4/5 | +15 |
| 18,19,20 | Acts 4:31/32/33 | text0/1 ↔ text2/3 (20 also text5 ↔ text4) | 0 |
| 24 | 2x2 photo compare | image2(`1.png`)↔image5; image3(`2.png`)↔image4 | +1 each |
| **48** | wheelchair jpeg twice | image2 ↔ image3 `WhatsApp…09.17.25.jpeg` (1381x921 @1954 / @4348) | **+3** |
| 50,51 | badge groups | group1 ↔ group0 | 0 |

Single-copy text slides: 11,12,13,14,28,29,30,35,36,37,38,46,49,52,57,59,60. Max observed
asymmetry 15 pt against a 7680 wall → an exact test.

### F3. Full-wall backdrops are dropped; the centre-panel scrim is not

`is_backdrop` (`map_remap.py:427`) needs `w >= 0.98 * 7680`, so the 7680-wide photo on every verse
slide already goes. The **3840-wide scrim shape survives** and forces the union to the whole panel:

| GW | kept scrim | effect |
|---|---|---|
| 28,29,30 | `shape0 (951,0,3840x1080)` | union 3840x1080 → fit scale 0.324 |
| 35,36,37,38 | `shape0 (1920,0,3840x1080)` | same |
| 57 | `shape0 (2530,0,4482x1080)` | same |
| 5 | `shape0 (1920,−508,4897x1807)` | same |

GW 13 (no scrim, no twin) is the owner's good reference: union 2087x354 → scale 0.886 → box
**1849x247** = the band width; confirmed live in `out-r7` slide 2 `text1 (43,807,1849x269)`.
`out-r7` slide 3 (GW 17) keeps **both** mirror copies → each fits to 721 wide, and live autosize
reflows them to `(43,874,721x348)` / `(43,957,721x429)` — 265 pt of overlap. The John 17 overflow
is the un-deduped mirror, not the text math.

### F4. The wheelchair slide is GW 48; golden 32 is its expected output (Q4)

GW 48 `image2/image3` are the same `WhatsApp Image 2026-08-14 at 09.17.25.jpeg` (member
`…-76510.jpeg`, 1600x1056 px) at (1954,27,1381x921) and (4348,27,1381x921), mirrored about 3840
(offset sum +3). Golden slide 32 keeps **one** copy: frame (1376.7,578.7,719.5x474.9), mask
(139.1,124.9,375.5x350) → visible **(1516,704,375.5x350)**, right edge **1892 == band.x_max**.
(The previous revision's open question 4 — "no wheelchair image in this deck" — was wrong and is
retracted; F1/F4 now agree.)

Other golden right-aligned singles: slide 2 `(1315,704,579x350)`, slide 4 `(1312,704,579x350)`,
slide 31 `(1312,704,579x350)` — right edges 1891..1894. Golden centred multiples: slide 1 (three
items, 352..1567), slide 12 `(529,704,861x350)` cx 959.5, slide 18 `(43,704,1832x350)`.

**The golden's crops are hand-made and are NOT our target size.** Every golden media item is the
whole file scaled to a frame and then masked to a window exactly 350 tall (579.4x350, 861x350,
1831.7x350, 375.5x350); golden 31 masks `Speaking in Tongues.png` at frame-local x 954.7/2488.8 =
0.384 of the width, which is not the LW window (0.25..0.75). Only the **right edge = 1892** and the
**count→placement** pattern are rule evidence.

### F5. Layout-owned media (R4)

Every GW theme layout is a full-wall `TSD.ImageArchive` at (0,0,7680x1080); **no layout owns a
movie**. Layout drawables never enter `offline_wall_payload`, so the classifier already ignores
them — R4 needs no classifier change, only a regression test. The purple "rain" the owner saw is
not a layout background at all (F7).

### F6. Builds on the candidate slides

`deck_builds`: GW 8,10,11,12,13,14,18,19,21,24,28,29,30,35,36,38,46,48,49,52 carry **0 builds**.
GW 17 carries 2 (`apple:dissolve character In` on text2 and on its mirror text5); GW 20 carries 2
(`KLNSparkle In` on text4/text5); GW 7 carries 4; GW 32/33 carry the movie's `apple:movie-start In`.
`build_identity` (`iwa_builds.py:21`) is **content-keyed** — `(kind, normalised text)` for
text/shape, `(kind, fileName)` for image/movie — so builds survive a slide duplication and a
kindIndex shift, but **not** a delete-and-reinsert of the media (the file name changes).

### F7. The "coal slide" bug — reproduced and root-caused (unchanged, still open)

The failing slide is **GW 32** (`306_TUJfMjAxOF8wNl8wMV9QSVpaQV83.mp4`, a charcoal grill,
3840x2160 h264, frame (1920,−762.9,3840x2160), no mask). GW 33 (`Charcoal Fire Loop.mp4`,
3840x1080 at (1920,0)) was not in the r7 run.

Banked clip `clips/Sermon_PK (GW).032.mov`: ProRes LT 3840x1080, 30 fps, 35.63 s, 533 MB. Frame at
t=1 s, exact non-black extents: all content inside the **top-left 1920x1080 quadrant**; grill at
x 0..~950, y 0..~935; a hard-edged **960x540** purple rectangle at x 960..1919, y 270..809.

The purple is `SPIRITUALATMOSPHERE_PK.png`, the LW **side panel** — a slide drawable, not layout
art. Arithmetic that reproduces both rectangles exactly, and nothing else does:

> `set width of theDoc to 3840` from 7680 (`dsk_movie_export.py:310`) makes Keynote **scale all
> content by 0.5**, x anchored at the origin, **re-centring vertically** in the unchanged 1080
> height (+270). The script then applies its `dx = −1920` translate (`scratch_canvas`
> `dsk_movie_export.py:161`, applied at :313-321) in **unscaled wall points** — it needed −960.

- side panel `image1` visible (5760,0,1920x1080) → ×0.5 → (2880,0,960x540) → +270 → dx −1920 →
  **(960,270,960x540)** ✓ the measured purple.
- movie (1920,−762.9,3840x2160) → ×0.5 → (960,−381.5,1920x1080) → +270 → dx −1920 →
  **(−960,−111.5,1920x1080)** → visible x 0..960, y 0..968.5 ✓ the grill column.

Two compounding defects in `_build_export_script`:
**B1 (geometry)** the canvas resize rescales content, the compensating translate does not account
for it; `_ffmpeg_process`'s raw-size assert (`dsk_movie_export.py:434`) passes because the *frame*
is 3840x1080 and it never checks the content. **B2 (leakage)** the scratch deck keeps every
drawable the classifier dropped (side panels, scrims, off-centre text); setting the base layout to
black removes layout art only.

Downstream, `out-r7` slide 4 places the clip at `movie0 (345,704,1244.4x350)` — arithmetically
correct for a 3840x1080 clip in a 1849x350 band (scale 0.324, centred). The band is under-filled
because a 3.56-aspect LW window cannot fill a 5.28-aspect band; that is expected under R2.

### F8. What a live `make new image {file:…}` insert produces (measured — this is the Q1 answer)

`out-r7` slide 4's clip was inserted by `_slide_lines` (`dsk_assemble.py:838-845`) as
`make new image with properties {file:… as alias}` followed by `set position/width/height`. Read
back offline from the saved package:

> `movie0 frame=(345,704,1244.4x350) mask=None naturalSize=3840x1080 originalSize=1244.4x350`
> `file=Sermon_PK (GW).032.mov member=Data/Sermon_PK (GW).032-77116.mov`

Keynote set `naturalSize` to the media's pixel size and `originalSize` to the frame we asked for,
with **no mask**, and copied the file into `Data/` itself. So a replaced image of a *different*
pixel size needs **no IWA media write, no `naturalSize`/`originalSize`/`mask` bookkeeping, and no
offline-writer fix** — the live insert is authoritative. (This retires the previous revision's
open question 1 and its dependency on the *offline-write render-fields defect* memory note.)

### F9. Text fit is predictable offline with real font metrics (the Q2 fit test)

Fonts resolve on this machine: `AzoSans-*` in `~/Library/Fonts` (file names prefixed
`Rui Abreu - `), `ArgentCF-*` in `/System/Library/Fonts`. A PIL `ImageFont.truetype`
greedy line-breaker at 8x size, honouring `\n`/` `/` ` and treating `\xa0` as
non-breaking, was validated against both decks with the laid-out-height model

> `h = lines * 1.157 * size + 21`  (21 pt = the shape's vertical padding)

- **Golden, boxes whose height varies with content** (slides 1,3-badge,4,5-8,9,10,21,23,25 …):
  predicted lines == observed to within 0.04 lines.
- **Golden verse boxes at a uniform 1838x177** are *fixed-height* (observed "lines" is a constant
  3.00 regardless of content) — not a predictor failure.
- **GW source boxes**: correct on 11 of 14 autosize verse boxes; the 3 misses (GW 8,9,10) are boxes
  whose source copy carries manual ` ` breaks the wrapped copy will not reproduce, and all 3
  err by exactly one line.

So the estimator is good to **±1 line**; the design carries a one-line safety margin and keeps the
existing live read-back (`_text_overflow_lines`, `dsk_assemble.py:748`) as the authority.

Running the estimator over every GW text slide (after mirror dedupe, band 1849x350, glyph floor
20 pt, 10 pt inter-box gap) gives the largest glyph scale `t ≤ 1` that fits:

| GW | long boxes | best t | GW | long boxes | best t |
|---|---|---|---|---|---|
| 7,11,14 | 1 | 1.00 | 12,18,19,20,35 | 1 | 0.81 |
| 8,10,13,30,37 | 1 | 1.00 | 36 | 1 | 0.98 |
| 28,29,46,52 | 1 | 1.00 | 38 | 1 | 0.58 |
| **17** | **2** | **0.91** | 49 | 1 | 0.39 |

**No slide in this deck needs a split at the default floor** — GW 17, the only two-box slide,
fits at t=0.91 (63.7 pt), which is also why golden 14 keeps both boxes. A split case therefore has
to be provoked: at `--min-text-pt 66` (t ≥ 0.943) GW 17 needs 173.7+173.7+10 = **357.4 > 350** and
must split; each part alone is 183 pt (badge 96 pt) at t=1.0, comfortably inside the band. That is
the live split case in Acceptance.

---

## Design

Architecture unchanged: offline-pure planning in `dsk_plan`/`plan_assembly`, one live agent per
live run, `visible_union` and the band affine reused.

### D0. Coal fix first (B1/B2) — `dsk_movie_export.py`

The banked clip is bad, so this lands before anything that consumes clips.

- **Export at the source wall size.** Delete `scratch_canvas` (`dsk_movie_export.py:161`) and the
  whole `set width/height of theDoc` + `dx` translate block (`:305-321`); always publish through
  the existing ffmpeg crop with `crop_rect = CENTRE_PANEL_RECT`, or
  `visible_union(include_side=True)` for a side-kept slide. `crop_filter`/`_clamp_crop`/
  `_normalize_even_crop` (`:187-223`) already do exactly this. Cost: the raw `.m4v` carries 2x the
  pixels; that buys the removal of a whole class of Keynote-resize behaviour.
- **Strip non-content drawables on the scratch slide** (B2): delete every id in
  `cls.dropped_side + cls.dropped_backdrop + cls.dropped_duplicate + excluded` before exporting,
  reusing `_delete_order` (descending `kindIndex` within a kind).
- **Content assert** after `_ffmpeg_process`: sample a frame ~1 s in and refuse when the non-black
  bbox is confined to a quadrant — `bbox.w <= 0.55 * width and bbox.h <= 0.95 * height`. This is
  the check that would have caught r7. An all-dark clip (empty bbox) warns instead of refusing.
- **Invalidate the banked clip**: move `clips/Sermon_PK (GW).032.mov` aside (not in the repo) and
  regenerate it in acceptance.

### D1. Classifier — `dsk_plan.py`

Additive filters inside/after `_filter_kept_items` (`dsk_plan.py:32`), in this order:

1. **`is_panel_backdrop(item, wall)`** — new, beside `is_backdrop` (`map_remap.py:427`). True for an
   `image`/`shape`/`movie` covering ≥ 98% of the **centre panel** in both axes (w ≥ 3763,
   h ≥ 1058) and carrying no text; drops the F3 scrims. Gate the drop on `len(kept) > 1` after the
   pass so a panel-sized item that is the slide's **only** content (GW 33's movie, 3840x1080 at
   (1920,0)) survives.
2. **`SlideClass.is_text`** — new field, `True` when some kept `text` item's content has
   `> --text-slide-words` (default 10) whitespace-separated words. Independent of `category`
   (a text slide may still be `built`). On a text slide additionally drop every kept
   `image`/`movie`; text-bearing shapes (chapter badges, e.g. GW 13 `shape0 "Genesis 11"`) stay.
3. **`mirror_duplicates(items, wall)`** — new pure function → `{dropped ItemId: kept ItemId}`.
   Group kept items by `(kind, content key)`; key = normalised text for `text`/text-bearing
   `shape`, `fileName` for `image`/`movie`, concatenated child text + fileNames for `group`. A
   2-member group is a mirror pair iff `abs((a.cx − 3840) + (b.cx − 3840)) <= 0.02 * wall_w`
   (153.6 pt; max measured 15) **and** sizes agree within 1 pt. **Survivor = lowest `kindIndex`**
   (Q5); its wall position is irrelevant because placement re-places it. Refuse on >2 identical
   members, or on an identical-content pair that fails the symmetry test.
4. **Layout-owned filter (R4)** — no code, regression test only (F5).

New `SlideClass` fields `dropped_backdrop` / `dropped_duplicate` (tuples) feed `plan.deletes` and
the review page.

### D2. Image content = a cropped FILE, not a mask (R2, Q1)

Rule: an image's DSK content is `frame ∩ mask ∩ LW window`. When that is a **proper subset** of
`frame ∩ mask`, the image is replaced by a cropped file; when it is not (GW 48, GW 24 — the whole
visible rect is already inside the panel), **nothing is replaced** and the source drawable keeps
its style, builds and z-order.

- **Offline (`dsk_plan.plan_crops` + `dsk_assemble`)**, per cropped image:
  - `member = data_member_index(zip_names)[data_id]` — new helper next to `_build_data_index`
    (`offline_inspect.py:44`) returning `{data id: raw member name}` (F1).
  - `px = Image.open(member).size`; **refuse** unless `px == naturalSize` and the EXIF orientation
    is absent or 1 (F1), and unless `item["rotation"] % 360 == 0` and the record's
    `needs_keynote` is not `rotated-masked` — the pixel mapping below is only valid axis-aligned.
  - visible `V = (frame ∩ mask_abs) ∩ CENTRE_PANEL_RECT` (or the full wall when `keep_side`);
    source-pixel crop box = `((V.x − frame.x) * px_w/frame.w, (V.y − frame.y) * px_h/frame.h, …)`,
    rounded outward to whole pixels and clamped to the image.
  - crop with PIL (`ImageOps.exif_transpose` first, then `.crop`), write to
    `--crop-dir` (default `<work dir>/crops`) as `<source stem>-lw<NNN>.<ext>`, format preserved
    (JPEG quality 95, PNG stays PNG so alpha survives).
  - record `plan.crops[number][ItemId] = CropSpec(path, source_file_name, fitted_rect)`.
- **Live (`_slide_lines`, `dsk_assemble.py:764`)**: put the source image id into
  `plan.deletes[number]`, then insert exactly as the clip path already does and as F8 measured —
  `make new image with properties {file:… as alias}`, then `set position/width/height` to the
  fitted rect. **No IWA media write, no offline writer, no mask.** Keynote sets `naturalSize` to
  the new pixel size and `originalSize` to the frame by itself (F8). Emit the insert in the same
  phase as the clip insert, after the deletes.
- **Refusals / fallbacks** (never guess):
  - a build targets the image → **do not replace**; keep the source drawable, fit it as today and
    emit an `OBED … LWCROP` operator note. A delete-and-reinsert changes the file name and
    `build_identity` is file-keyed (F6), so the build would be silently lost.
  - `px != naturalSize`, EXIF orientation ≠ 1, rotated frame/mask, or an unresolvable data member →
    same fallback + a warning.
  - the crop window is < 8 px on either axis → refuse the slide.
- **Style continuity**: a fresh insert has no card stroke. `_restore_stroke` (`dsk_assemble.py:997`)
  keys media by file name via `card_styles(out_objects, out_id_to_file)`, so register the cropped
  file under its **source** file name — pass `plan.crops`' `source_file_name` into the
  `out_id_to_file` mapping the stroke pass builds, and unit-test that a cropped image still
  receives the paired-stroke restore/grant.
- **Mask-aware content test**: after this, the item's content rect **is** the crop window, so
  everything downstream (fit, placement, the acceptance rect assertions) uses `V` and never the
  frame. Movies are unchanged: the clip file is already the LW-window render.

### D3. Placement by COUNT (R3, Q3)

In `plan_assembly` (`dsk_assemble.py:145`), let `n` = the number of kept **content** items after
D1 (images/movies/groups; text and text-bearing badge shapes excluded). When the operator gave no
explicit `--anchor` for the slide:

- `n == 1` → `anchor = "right"` (flush to `band.x_max`; `_place`, `dsk_plan.py:492`, already
  implements it);
- `n > 1` → `anchor = "centre"` (today's behaviour, unchanged).

No span threshold anywhere — this supersedes the previous revision's 0.98-of-panel test and its
open question. `--anchor N=…` always wins; the derived anchor is recorded in the plan and printed
in the run log.

### D4. Text: downscale, band stretch, and SPLIT (R1, Q2)

**Estimator** (new `dsk_plan.wrapped_height(text, font, size, width) -> float`, F9): resolve the
PostScript font name against a one-time index of `~/Library/Fonts` + `/System/Library/Fonts` +
`/Library/Fonts` built from each file's `ImageFont.getname()`; greedy wrap at 8x size honouring
`\n`/` `/` `, `\xa0` non-breaking; `h = lines * 1.157 * size + 21`. **Add one line of
margin** (`+1.157 * size`) to every estimate — the measured worst case is ±1 line. An unresolvable
font → warn and fall back to today's affine-only behaviour for that slide (no split decision).

**Fit test** for a text slide: long boxes `T1..Tn` (> word threshold) in source order (by `y`, then
`x`); short boxes and badges are not stacked and keep the slide affine. Search `t` from 1.00 down
in 0.01 steps for the largest `t` with

```
sum_i ( wrapped_height(text_i, font_i, size_i * t, band.width) ) + (n-1) * gap  <=  band.height
and  size_i * t >= --min-text-pt   for every i        (gap = 10 pt)
```

The slide **fits** at the first such `t`: each long box is then written at
`x = band.x_min, w = band.width`, glyph size `size_i * t`, stacked from `band.bottom − total`
downward; other kept items keep the affine.

**Split** when no `t` satisfies both constraints and `n >= 2`: the slide becomes `n` DSK slides,
**one long box each, in source order**, every part keeping the slide's short items (badge, chapter
label) and deleting the other long boxes. Re-run the fit test per part. If `n == 1` and no `t`
qualifies, or a single part still fails, **refuse** (`AssemblyRefusal`: "slide N box k does not fit
the band even alone") — never split a box mid-text.

**Ordinals and plumbing for one source slide → N outputs:**

- `AssemblyPlan` gains `parts: dict[int, int]` (default 1) and `ordinal_to_number: dict[int, int]`;
  `ordinals[n]` keeps its meaning as that slide's **first** ordinal, and
  `ordinal_map` becomes a running sum over `parts` instead of `enumerate` (`dsk_live.py:52` gains a
  `parts` argument rather than being replaced).
- Per-part payload lives in `plan.splits[number] = (SplitPart, …)` where `SplitPart` carries that
  part's `fits`, `deletes` and `text_sizes`. Non-split slides keep the existing single-part
  `fits`/`deletes`/`text_sizes` dicts untouched — no regression risk on the 1633-line emitter, and
  every existing test keeps its shape.
- Emitter: after the keep/delete pass and before the geometry pass, duplicate split slides in
  **descending** source order — `duplicate slide K to after slide K of theDoc`, proven at
  `maps_keynote.py:1245` — so earlier ordinals never shift under an already-emitted address. Then
  emit `_slide_lines` per (number, part) with `ordinal = plan.ordinals[number] + part`.
- `_verify_builds` (`dsk_assemble.py:1403`): build `inverse_ordinals` from `ordinal_to_number` and
  **merge** the parts' build records per source number (concatenate `builds`; require every part's
  transition to equal the source's). This is sound because `build_identity` is content-keyed (F6):
  a duplicated slide carries the same identities, the deleted boxes take their builds with them,
  and the union over parts equals the source minus the deletions — GW 17's `dissolve character`
  identity is shared by text2 and its mirror text5, so the dedupe shows up as one tolerated
  *missing*, exactly as a deletion does today.
- `_restore_stroke`'s `_rekey_slides` (`dsk_assemble.py:1037`) takes the same extended inverse map.

**Accepted residual risk:** the 15 pt safety headroom is measured against a worst estimator
divergence of −20 pt (GW 38) and a −10..−15 pt cluster elsewhere; `OVERFLOW` read-back remains the
authority over the estimate. The forced-split acceptance run now provokes the split at GW 17
with the floor at 66 (GW 13 still fits at t=0.91 and only refuses at 66; GW 28 still fits alone
at 66 and does not split).

### D5. Deletes

`deletes[number]` (`dsk_assemble.py:228`) additionally carries `cls.dropped_backdrop`,
`cls.dropped_duplicate` and every crop-replaced image id, in `_delete_order`.

`_merge_split_part_builds` (`dsk_assemble.py:1742`): each part's own long-box builds are always
summed. A short item's build is recognised as "repeated" only when its source id (recovered from
the part's staged kindIndex) sits in every part's own `fits` -- i.e. it is genuinely the same
shared item cloned onto every part, not a per-part-unique item that happens to share an
(effect, animationType, identity) key. A repeated key is counted only when every part's counter
for it agrees; a disagreement (e.g. one part dropped it) contributes nothing here, so the
shortfall surfaces as a missing build for `_verify_builds` to refuse or tolerate. A key that isn't
recognised as repeated is summed, as before. This can mis-classify a key shared between a genuine
repeated item and a per-part-unique one, or under-count a losing repeated item across both parts;
both err toward refusal rather than silent loss, which is the deliberate tradeoff.

### D6. Flags and refusals

New `dsk-assemble` CLI (`cli.py:113`):
`--text-slide-words N` (10), `--min-text-pt N` (default **24**; the golden's verse text is 45 pt and
its badges 40 pt, so 24 is a floor, not a target), `--no-dedupe`, `--no-auto-anchor`,
`--no-drop-panel-backdrop`, `--no-split`, `--split N=k` (operator override of the offline decision),
`--crop-dir PATH`, `--no-image-crop` (fall back to the LWCROP note everywhere).

`AssemblyRefusal` additions: >2 items sharing a content key on one slide; an identical-content pair
failing the mirror test; the panel-backdrop drop would empty a slide with no `--include-side`; a
single long box that cannot fit the band at the floor; a crop window under 8 px; a split requested
on a slide whose parts disagree on transition.

---

## Steps

1. **Coal fix (B1/B2) + clip content assert.** Remove `scratch_canvas`/resize/`dx`; always
   ffmpeg-crop; strip non-content drawables; add `_assert_clip_covers_frame` after
   `_ffmpeg_process`; move the bad banked clip aside.
   *Tests* `tests/test_dsk_movie_export.py::test_script_never_resizes_document` (no
   `set width of theDoc` in the emitted script), `::test_script_deletes_non_content_drawables`
   (delete lines for the GW-32 side-panel ids), `::test_crop_rect_defaults_to_centre_panel`
   (`crop=3840:1080:1920:0`), `::test_clip_content_assert_rejects_quadrant_clip` (feed the measured
   bad bbox (0,0,1920,1080) in a 3840x1080 frame → refusal), `::test_clip_content_assert_passes_full_frame`.
2. **`is_panel_backdrop` + wiring.** *Tests* `tests/test_dsk_plan.py::test_panel_backdrop_dropped_on_verse_slides`
   (fixtures shaped like GW 28 `(951,0,3840x1080)` and GW 57 `(2530,0,4482x1080)` land in
   `dropped_backdrop`), `::test_panel_backdrop_kept_when_sole_content` (GW 33's lone
   `(1920,0,3840x1080)` movie stays).
3. **Mirror dedupe.** `mirror_duplicates` + `dropped_duplicate`, survivor = lowest `kindIndex`.
   *Tests* `::test_mirror_duplicates_text_pair` (GW 17/18 geometry; the higher kindIndex goes),
   `::test_mirror_duplicates_image_pair` (GW 48 and both GW 24 pairs),
   `::test_mirror_duplicates_refuses_asymmetric`, `::test_mirror_duplicates_refuses_triplet`.
4. **Text-slide class + band stretch.** `is_text`, media drop, stacked band write.
   *Tests* `tests/test_dsk_assemble.py::test_text_slide_drops_media_keeps_badge`,
   `::test_text_slide_box_stretches_to_band` (GW 13 → `(43, …, 1849, …)`, glyph size ≤ source),
   `::test_john17_after_dedupe_does_not_overlap` (GW 17 geometry: the two kept boxes' rects do not
   intersect — the r7 regression).
5. **Wrap estimator.** `wrapped_height` + font index. *Tests*
   `tests/test_dsk_plan.py::test_wrapped_height_matches_golden_boxes` (the F9 golden rows whose
   height varies with content, ±1 line), `::test_wrapped_height_missing_font_warns`,
   `::test_fit_search_returns_measured_t` (GW 17 → t = 0.91; GW 38 → 0.58; GW 49 → 0.39).
   Skipped when the fonts are absent.
6. **Split.** `parts`/`ordinal_to_number`/`splits`, `ordinal_map` over parts, descending
   `duplicate slide`, per-part `_slide_lines`. *Tests*
   `::test_split_ordinals_shift_following_slides` (kept 13,17,21 with 17 split → ordinals
   1,2,(3,4),5... and `ordinal_to_number` maps 3 and 4 to 17),
   `::test_split_parts_one_long_box_each_keeps_badge`,
   `::test_split_script_duplicates_in_descending_order`,
   `::test_split_refused_when_single_box_cannot_fit`,
   `::test_no_split_when_fit_found` (GW 17 at the default floor stays one slide).
7. **Build verify across a split.** Merged `out_by_number`, extended inverse map. *Tests*
   `tests/test_dsk_assemble.py::test_verify_builds_merges_split_parts` (GW 17 shaped: source 2
   `dissolve character` identities, output parts contribute 1 → one tolerated missing, zero
   surplus), `::test_verify_builds_refuses_surplus_across_parts`.
8. **Image crop + replace.** `data_member_index`, `plan_crops`, delete+insert emission, stroke
   re-keying. *Tests* `tests/test_dsk_plan.py::test_crop_box_from_frame_mask_and_lw`
   (GW 3 geometry: frame (1920,−981.6,3840x2560) + mask (0,808,3840x1472) + panel →
   crop box in 6000x4000 pixels, checked by hand),
   `::test_no_crop_when_visible_inside_panel` (GW 48 → no replacement),
   `::test_crop_refused_on_rotation_or_exif`, `::test_crop_falls_back_to_note_when_build_targets_image`,
   `tests/test_dsk_assemble.py::test_crop_insert_lines_match_clip_idiom` (a `make new image` +
   position/width/height block and the source id in `deletes`),
   `::test_cropped_image_keeps_source_file_name_for_stroke`.
9. **Placement by count.** *Tests* `::test_single_content_item_right_aligned` (GW 48 after dedupe →
   right edge 1892.0, the golden-32 corroboration), `::test_two_items_centred` (GW 24 after dedupe),
   `::test_explicit_anchor_overrides_auto`, `::test_text_items_do_not_count_towards_placement`.
10. **Deletes + CLI + refusals.** *Tests* `::test_deletes_include_backdrop_duplicate_and_cropped`,
    `tests/test_cli.py::test_dsk_assemble_new_flags_parse`, `::test_min_text_pt_forces_split`,
    `tests/test_dsk_assemble.py::test_refusals_*`.
11. **Offline end-to-end on the real GW deck.** `classify_deck` + `plan_assembly` over
    `Sermon_PK (GW).key` for the acceptance set, asserting the rect table below. Marked
    `@pytest.mark.deck`, skipped when the deck is absent.
12. **Live acceptance** (last, one agent, hands-off): re-export clips for GW 32 and 33, then two
    `dsk-assemble` runs (default, and the forced-split run).

---

## Acceptance

**Offline** — full suite green, plus on `Sermon_PK (GW).key`:

| GW | rule | asserted |
|---|---|---|
| 13 | R1 single text | verse box `x=43, w=1849`, glyph size ≤ 70, no split |
| 17 | R1 dedupe + stretch | text3/4/5 in `dropped_duplicate`; two kept boxes, no overlap, t = 0.91 |
| 17 (`--min-text-pt 66`) | Q2 split | 2 parts, one long box each, badge on both, ordinals contiguous |
| 28 | R1 panel-backdrop drop | `shape0 (951,0,3840x1080)` in `dropped_backdrop`; fit scale > 0.8 |
| **48** | R1 image dedupe + Q3 right (wheelchair) | one image kept (`kindIndex` 2), fitted right edge **1892.0**, no crop file emitted |
| 24 | R1 dedupe + Q3 centred | 4 → 2 images; centred |
| 21 | R2 image crop | crop window = (1920,0,3790x1080) of the frame → pixel box in 4608x3072; replaced file emitted; single item → right-aligned |
| 5 | R2 image crop, vertical | crop window (1920,0,3840x1080) of a (1920,−1024.3,3840x2560.5) frame → 5120x2160-ish pixel box |
| 33 | R2 movie + backdrop exemption | movie kept as sole content; crop `3840:1080:1920:0` |
| 32 | coal fix | crop `3840:1080:1920:0`, no document resize, side panels deleted in the scratch script |
| 8 | regression | unchanged vs r7 with `--include-side 8` |

**Live** — one hands-off run:

1. `dsk-export-clips "Sermon_PK (GW).key" --slides 32,33 --out clips-r8`
   → both clips 3840x1080; the frame at t=1 s has a non-black bbox ≥ 95% of the frame width and no
   `SPIRITUALATMOSPHERE` magenta anywhere.
2. `dsk-assemble "Sermon_PK (GW).key" --slides 5,13,17,21,24,28,32,33,48 --out out-r8/… --clip 32=… --clip 33=…`
   → 9 slides; the rect table holds when the **saved package** is read back offline; the run log
   lists the derived anchor and any LWCROP note per slide; zero overflow warnings on 13 and 17;
   `builds` report clean.
3. `dsk-assemble "Sermon_PK (GW).key" --slides 13,17,21 --min-text-pt 66 --out out-r8-split/…`
   → **4** slides; ordinals 1=GW 13, 2 and 3 = GW 17 parts 1/2, 4 = GW 21; each part's box at
   `x=43, w=1849` at 70 pt with the "John 17" badge present; the `dissolve character` build lands on
   part 2 only; `_verify_builds` reports zero surplus.

That set covers every rule: R1 text/dedupe/backdrop-drop (13,17,28,48,24), Q2 split (17 forced),
R2 image crop (21,5) and movie (32,33), Q3 right-by-count (21,48) and centred (24), R4 (every
slide — layouts never appear), plus the coal fix (32).

---

## Open questions (design-changing)

None blocking. Two judgement calls recorded rather than asked, both reversible by a flag:

- `--min-text-pt` default **24**. Chosen as a floor below the golden's 45 pt verse / 40 pt badge
  (F4/F9); it makes the GW deck split-free, which matches the golden (no golden slide is a split of
  a GW slide). If the owner wants DSK text no smaller than, say, 45 pt, the default changes and
  GW 12,18,19,20,35,38,49 begin to split — the machinery is the same, only the default moves.
- Split parts each repeat the slide's **short** items (chapter badge). The alternative — badge on
  part 1 only — looks wrong on a projected wall, and the golden always shows the badge, so every
  part keeps it.
