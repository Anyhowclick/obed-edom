---
name: Cue palette and outline editor
overview: The Keynote 15.x migration, the resizer's framing confirmation and the badge placement are done. What remains is the number block in the CG resizer, then the cue-first palette built from the dropped template's real layouts, the in-dashboard outline editor that writes semantic cues into the source .docx, image cues, and the DSK generator.
todos:
  - id: text-placement
    content: "CG resizer: the 183 / 86 / 14 / 269 number block renders as overlapping fragments. The badge and the date are resolved; the badge is now buried by map art rather than misplaced, which is a source-deck problem"
    status: pending
  - id: badge-cluster
    content: "Badge-as-cluster placement in the CG resizer. H18 confirmed: the badge affine came from the title text box, so logo and plate landed short. They now take the template's own rects and match gold exactly"
    status: completed
  - id: layout-thumbs
    content: "Layout thumbnail extraction: scratch copy, one slide per layout, export, cache by template digest, serve via GET /api/template-layouts with cue mapping"
    status: pending
  - id: cue-palette
    content: Cue-first palette in the dashboard, inverting masters.yaml cue maps, with adjacency and context rules enforced
    status: pending
  - id: outline-editor
    content: Editable outline view extending OutlineResultView, with LibreOffice page-view toggle, in-place surgical writes to the source .docx and timestamped backups
    status: pending
  - id: image-cues
    content: Image cues, as an asset slot count and shape per cue rather than N placements. Both capabilities probed and present
    status: pending
  - id: dsk-generator
    content: DSK generator, unchanged from the superseded plan including its four corrections
    status: pending
  - id: title-structural
    content: "Find the title structurally instead of by wording. is_title_item matches masters.yaml title_phrases, so any series not on that list gets no titleDst and no badgeSlots and the badge machinery silently does nothing. Blocks recipe-library"
    status: pending
  - id: recipe-library
    content: "Recipes as browsable artefacts: learn from pages that pair, save under a label, apply to pages that do not pair. Replaces offering template slides to pages where no template slide can help"
    status: pending
  - id: stat-drift
    content: "Validation rule slide.stat_drift: a figure that changes between adjacent slides and then holds at the new value. A missions wall read 11 Renovated Church Buildings on one page and 44 on every page after it. False positives acceptable"
    status: pending
  - id: keynote-15-migration
    content: "Keynote 15.x migration: bundle-id targeting, version-tagged cache, 14.5 A/B comparison, 14.5 deleted, gold decks re-warmed, 15.x-only decision. Findings are in the skill doc"
    status: completed
  - id: framing-confirm
    content: "Framing confirmation for map slides: two-phase resize job, grouped review by framing with projected wall previews, drag-select, decisions remembered by digest"
    status: completed
  - id: map-affine-fixes
    content: "Three planner defects fixed and verified: cluster choice for large objects, junk pairings dropped, non-uniform pairs rejected. Gold scores 933 to 503 and 376 to 317"
    status: completed
isProject: false
---

# Cue palette and outline editor

Supersedes `keynote_file_format_spike_6b4ae4c2.plan.md`. Everything in that plan
still stands except item 3 (live preview), which is dropped for the reasons below.

**Read `.cursor/skills/obed-edom/SKILL.md` first.** Every durable finding from the
Keynote 15 migration now lives there — bundle-id targeting, the verified scripting
limits, cache versioning, the template contract. This plan holds only what is
still to be done and the reasoning a new agent would otherwise have to rediscover.

## Where things stand

**Done and verified.** The tool is Keynote 15.x only, addressed by bundle id
through the single resolver in `src/obed_edom/keynote_app.py`. The resizer's
framing confirmation ships: `/api/resize` is a two-phase job (propose, then apply
after the operator confirms), reviewed in `dashboard/src/components/FramingReview.tsx`
grouped by framing rather than by page, each candidate shown as the actual wall
preview under a CSS transform derived from the planner's own affine. Three planner
defects were found and fixed with runtime evidence; gold scores improved on both
pairs (933 → 503, 376 → 317) rather than trading one against the other.

**The warm cache moved out of `output/`.** It is `.cache/` at the repo root now,
overridable with `OBED_EDOM_CACHE_DIR`. It costs about an hour of Keynote time to
rebuild and it used to live inside the folder people clear, which is how that hour
got lost once. `output/` is otherwise disposable — clearing it is safe.

## Immediate: the number block in the CG resizer

The map geometry is correct as of `cd83162`. Of the three text defects recorded
against `Map_Extracted_Wall_1st.key` slide 4, one remains:

**The 183 / 86 / 14 / 269 number block renders as overlapping fragments.** The
cause is not a text bug. Those figures live in groups, and `plan_slide_transforms`
parks every left-column group at `x = 16` while restoring its *wall* size, because
the map affine would otherwise throw it off the left edge and setting a group's
width does not scale its children. Five groups therefore land in one column with
heavily overlapping y ranges — planned rects `(16, 175, 537x271)`,
`(16, 326, 496x383)`, `(16, 388, 199x258)`, `(16, 584, 237x258)` — which is what
the fragments are. This is the negative-space problem the branch is named for:
the groups need packing against each other, not a shared left margin.

H15 and H16 below still stand for loose text items that are *not* inside groups;
they were never the explanation for this block.

**Resolved, do not re-investigate:**

- *The badge was H18, confirmed.* It was classified `other` and took the title
  affine, which is derived from the title **text box** — 537 wide against the
  template's 271, so `s = 0.505`. That put the 124px logo at 63px and the 767px
  plate at `387x87`. The template's badge is not a uniform shrink of the wall's:
  plate, logo and title each moved by their own ratio, so no single affine
  reproduces it. Badge objects now land on the template's own rects, verified
  against the rendered preview at `(17,37) 411x123` and `(31,59) 80x80` — which is
  also exactly what last year's five finished pages carry.
- *The badge still looks clipped, and no code can fix it.* The map layers sit
  above it in the source deck, and Keynote exposes no way to restack. See the
  skill doc. It is a source-deck or template fix.
- *"Oct 2024 – Sep 2025" is no longer truncated.*

**Two hypotheses still open, for loose text only.** Both are answerable from one
instrumented planning run, since planning the whole deck takes 0.17s off the warm
cache and needs no Keynote.

- **H15 — the `TEXT_DOWN_SCALE` clamp sizes text boxes at a different scale than
  the one that positions them.** In `_style_text_box`
  (`src/obed_edom/map_remap.py:1520-1525`) an unstyled text item takes
  `scale = min(aff.s, TEXT_DOWN_SCALE)` with `TEXT_DOWN_SCALE = 0.42` (line 37)
  for its width, height and font, while its top-left corner comes from
  `aff.apply_rect(...)` at the full `aff.s` — 0.8547 on this deck. Box and font
  shrink together, so text ought still to fit, but every unstyled box lands about
  half the size the rest of the layout uses, anchored by a corner computed at
  roughly twice that scale. *Evidence:* log `aff.s`, the clamped `scale`, and src
  versus mapped rect for each text item, and check whether the clamp bound.
- **H16 — `match_character_style` finds nothing for these items, so they fall into
  H15's path instead of using the template's real font size.** The styled branch
  (lines 1512-1519) scales by `ratio = dst_size / wall_font`, which is the intended
  behaviour; the clamp is only the no-style fallback. *Evidence:* log the matched
  style or `None`, plus `dst_size`, per text item.
- **H19 — Keynote reflows text on the size pass and the position pass cannot
  correct it.** `applyGeom` deliberately runs full-then-position-only because
  setting width or height yanks an object to (0,0), but setting `objectText.size`
  can trigger Keynote's own autofit and the second pass restores position without
  re-checking size. Needs a real Keynote pass: log requested versus read-back
  width, height and position per text item after both passes. Worth raising up the
  order — the same shape of defect turned out to be real for lines, where the
  endpoint writes silently undid the size that had just been set.

  H17 is answered: the block is groups sharing a left margin, not text items
  snapped onto one `listDst`. H18 is answered and fixed; see above. The stacking
  caveat that used to sit here is settled and lives in the skill doc — apply order
  is stacking order for generate and not for resize.

## Keynote cannot read or set z-order — both halves verified

Asked and settled on 15.3.1 via `scripts/probe_zorder.js`; full detail is in the
skill doc. Reading fails because `slide.iWorkItems()`, the one collection that
would interleave classes in stacking order, raises "Can't convert types.", and no
per-item substitute exists. Writing is impossible because `Keynote.sdef` contains
no arrange vocabulary at all — JXA hands back a function for any name you ask for,
so `app.bringToFront` *looks* like it exists, but calling it gives "Message not
understood." Reordering is GUI-only.

Per-type collections do enumerate in creation order, so relative order within one
class is recoverable; cross-class is not, and that is the part stacking needs.

## Decision: live preview is dropped, cue discovery replaces it

A preview is only worth building if it answers faster than editing the document
does. A Keynote round trip cannot, and a browser overlay would still be an
approximation of the thing it is approximating. Editing the outline and typing a
cue is faster, so the preview is cut.

The real problem was never "does this copy fit" — it is that the cue vocabulary is
invisible. Nine semantic cues today, with adjacency rules and context variants, and
it grows. So the work becomes: **show the operator the layouts the template
actually has, and let them insert the cue that produces one.**

## What the palette must get right: layout and cue are many-to-many

Mirroring Keynote's "Choose a Layout" panel one-for-one would be wrong.
From `src/obed_edom/masters.yaml`:

- `BLANK` backs `[FILLER-QR]`, `[GIVING-OPTIONS]`, and offering-context
  `[FILLER]` — three cues, one layout.
- `VERSES` backs both `[VERSE]` and `[VERSE-CONTINUED]`.
- The four POST layouts have no cue of their own. They come from
  `[VERSE-AFTER-POINT]`, which is valid only directly after `[POINT]` or
  `[NUM-POINT]`, and which also drives the 1s Magic Move.
- `TITLE` backs `[TITLE]` and sermon-context `[FILLER]`.
- DSK adds selection by length, not by cue: `Verse 1 Line (Variation 2)` versus
  `Verse Standard (Variation 2)` is decided by `verse_char_one_line`.

So the palette is **cue-first**, each entry carrying the layout thumbnail(s) that
cue can produce, the context that picks between them, and its adjacency rule. That
inverts the existing `lw.cues` / `dsk.cues` maps rather than adding a second source
of truth.

## Layout thumbnails: derive per template, cache by digest

`Default Templates/` is empty and gitignored, so templates are always dropped and
thumbnails cannot be pre-baked. Keynote's `export` works on documents, not layouts,
so:

1. Copy the dropped template to a scratch path (never touch the original).
2. Enumerate layouts. `remap_keynote.js` already has the pattern —
   `doc.slideLayouts()` and `layoutNames()` at lines 543-567.
3. Append one empty slide per layout with `{base slide: theMaster}`, the way
   `src/obed_edom/keynote.py` line 792 onward already does.
4. Export slide images, keep one PNG per layout name, discard the scratch deck.
5. Cache under `<cache root>/layouts/{template_digest}/`, reusing `deck_digest()`
   and the versioning discipline of `INSPECT_VERSION` in
   `src/obed_edom/baseline.py`. Note the cache root is now `.cache/` at the repo
   root, not under `output/`.

One Keynote pass per template, once. New endpoint `GET /api/template-layouts`
taking a template path, returning layout names, thumbnail URLs, and the cues each
layout is reachable from. Layouts that no cue reaches are returned as unmapped —
that list is itself useful, since it is the honest answer to "what can the template
do that the tool cannot ask for".

**Both capabilities this needs were probed on 15.3.1 and are present.**
`doc.slideLayouts()` returns 9 named layouts and each answers `textItems()`,
`images()` and `shapes()`. But `doc.masterSlides()` raises "Can't convert types."
in JXA while AppleScript's `master slide` is fine, which is why `keynote_jxa.js`
must stay unused.

## Outline editor in the dashboard

The operator views and edits the outline in the dashboard, and picks cues from the
palette instead of typing them.

**Editing surface: HTML rendered from the .docx.** `load_paragraphs` in
`src/obed_edom/parse_outline.py` already returns per-run `bold`, `highlight`,
`superscript` and `color`, and `ListNumberResolver` (line 365 onward) resolves Word
auto-numbering. `OutlineResultView` already renders paragraphs with cue chips at
exact character offsets via its `segments()` helper — that component is the starting
point, made editable. This gives a real caret, exact paragraph index and character
offset, and instant saves.

**Page view: LibreOffice.** A toggle converts the current file with
`soffice --headless --convert-to pdf` and shows the rendered pages for a
true-to-Word visual check. Read-only, cached until the next save, and absent
LibreOffice the toggle is simply disabled rather than an error.

**Writes go to the source .docx, in place.** This reverses the skill doc's "never
overwrite the source outline" rule, scoped to the generator's editor only; the
Sermon Checker stays read-only, and the `_CUED.docx` output path is unchanged. Two
safeguards:

- A timestamped backup per save under `output/.outline-backups/{stem}/`, so a bad
  edit is recoverable.
- **Surgical edits only.** Apply an operation list against the paragraphs the
  operator actually touched, in the manner of `_apply_ops` / `_make_run` in
  `src/obed_edom/annotate.py`. Never re-serialise the whole document: tables,
  images, comments and numbering definitions that the model does not represent must
  survive untouched.

**Semantic cues in, operator cues out.** The editor writes `[TITLE]`, `[VERSE]` and
so on. Conversion to `[LW]` / `[DSK-…]` stays where it is, in `annotate_outline` at
generate time. Nothing about the generated artefacts changes.

**Validation as you type.** The palette can enforce what the parser already knows:
`[VERSE-AFTER-POINT]` offered only directly after a point, `[FILLER-QR]` and
`[GIVING-OPTIONS]` marked offering-only, and `[VERSE-FROM-PREVIOUS]` absent from
the palette entirely since it raises `cue.deprecated_alias`. This is also where the
invariant is cheapest to hold: one cue is one slide advance.

## Image cues: design for these, build later

Probing settled the two questions that gated this. An image places from AppleScript
with `position` and `width`, height following from aspect ratio. **A movie is
placed by creating an image and then assigning the video to its `file name`**,
which converts the object and keeps the geometry — so video slides are generatable
with no GUI automation, and a template needs only a small image placeholder rather
than an embedded video.

The taxonomy, read off the real deck at `~/Desktop/Diff-Checker/Sermon_PK (GW).key`:

- **Centre-panel photo set** (slide 18): two photos filling the centre 3840x1080;
  side panels keep the background. Two assets, fixed frames.
- **Mirrored single set** (slide 20): one image set repeated left and right, the
  same duplication the verses use. One asset, placed twice.
- **Full-centre media** (slides 25 and 26): one image or movie across the whole
  centre. Both generatable, per above.
- **Design-authored collage** (slide 1): the series opener, dozens of cut-outs on a
  custom background. Not operator-buildable and should not pretend to be — the cue
  for these is "drop in the supplied graphic", which `[GIVING-OPTIONS]` already
  does with its flag.
- **Grid cases** (the mission photo wall, the missions-map infographic): tens of
  images on a laid-out grid. These want a count and a grid spec, not N placements.

The implication: an image cue is a cue plus an **asset slot count and shape**, and
picking it should open a drop target for that many files, in order, with the frames
named. Custom backgrounds are the norm on these slides, so the cue must allow a
background asset distinct from the content assets.

## Stat drift across adjacent slides

A missions wall read "11 Renovated Church Buildings" on one page and "44" on every
page after it. No rule fires, because nothing on either page is wrong on its own —
it is only visible by reading two pages side by side. The source deck was correct
everywhere except that one page, so this is a source defect the checker should
have caught rather than anything the resizer did.

The tell is that a caption which persists unchanged across a run of slides changes
exactly once. Compare text objects across adjacent slides, matching on position
and on wording with the digits removed, and flag a page whose number disagrees
with the run either side of it.

Ships at `warning`, not `error`: a figure that genuinely steps per slide will trip
it, and the operator has said that is the cheaper mistake. Rule name and severity
are stubbed in `src/obed_edom/validation_rules.yaml`.

## Find the title structurally, not by wording

`is_title_item` matches the text against `masters.yaml -> cg.title_phrases`
("Global Missions", "全球使命", "Missions Update", "宣教近况"). Any series whose
title is not on that list gets no `titleDst` and no `badgeSlots`, so the whole
badge path — plate, logo, title size and colour — silently does nothing. Measured
on `Extracted_Wall/CG_3rd`, whose pages are titled "CHC Kuching":

```
titleDst      = MISSING
badgeSlots    = MISSING
titleFontSize = MISSING
listFontSize  = 60.0      <- the title mistaken for a church-name list sample
```

Adding `CHC` to the phrase list is not the fix: every label on the missions map
is "CHC …", so a hundred list entries would classify as titles.

**Keep the phrase match as the first signal** — that is what the missions decks
use today and it must not regress — and fall back to structure when it misses:

- **plate** = the non-pin, non-backdrop shape of largest area *among those whose
  rect contains the centre of at least one text item*
- **title** = the largest text whose centre lies inside that plate

The containment clause is what makes it work rather than "largest shape": on
`Extracted_Wall_3rd` slide 2 the side panel `(4261,205) 398x710` is larger than
the plate `(1961,-65) 485x197`, and holds no text. Checked against all four decks
in the warm cache; the rule picks the right object on each:

| deck / slide | plate | title |
| --- | --- | --- |
| missions wall 4 | `(1953,28) 767x173` | Global Missions |
| Base_CG_Assets 12 | `(17,37) 411x123` | Global Missions |
| Extracted_Wall_3rd 2 | `(1961,-65) 485x197` | CHC Kuching |
| Extracted_CG_3rd 2 | `(20,-65) 359x160` | CHC Kuching |

*Shape of the change.* A new `slide_title_item(slide)` holding both signals;
`template_title_item` delegates to it. The awkward part is `classify_item`, which
asks `is_title_item(item)` per item — role `title` has to come from the one
chosen title instead, so the identity `_title_badge` already computes needs
threading into classification rather than being re-derived. `is_title_item` stays
as the phrase predicate the new function calls.

*Watch for.* A caption on a coloured shape could be read as a title on a page
with no real badge. Prefer the topmost candidate when more than one plate holds
text, and record the choice in the framing report so a wrong pick is visible
rather than mysterious.

## Recipes as browsable artefacts

The framing review browses **template slides**, and a template slide only helps if
something *pairs*. `Map_Extracted_Wall_2nd` slide 3 is chrome plus a movie —
`is_pairable_image` requires `kind == "image"`, so nothing pairs, `pairQuality`
is 0, and every candidate previews identically because they all degrade to
fit-to-frame. The review offers more of the thing that cannot help.

What transfers instead is the **recipe**. Measured: taking the finished
`Extracted_CG_3rd` slide 2 as the template, all four wall pages learn the same
transform and each page's own photo lands where the finished CG has it.

```
wall slide 2: pairQuality=2  s=1.0000 tx=-2844.0  photo -> (-924,-1) 3840x1080
wall slide 3: pairQuality=1  s=1.0000 tx=-2844.0  photo -> (-924,-1) 3840x1080
wall slide 4: pairQuality=1  s=1.0000 tx=-2844.0  photo -> (-924,-1) 3840x1080
wall slide 5: pairQuality=1  s=1.0000 tx=-2844.0  photo -> (-924,-1) 3840x1080
```

`tx = -2844` shows wall `2844..4764` — dead centre of the 1920–5760 panel, which
is the right answer for any full-bleed centre panel, including the movie on
`Map_Extracted_Wall_2nd` slide 3 that pairs with nothing.

Note what this does *not* do. `Extracted_CG_3rd` slides 4 and 5 use different
image files at different sizes (`Layer 14.png` 2355x1766, `Layer 31.png`
2013x1133) than the wall pages they came from. Someone re-cropped and re-exported
those. No transform reproduces a different asset, and the tool should not try.

*The split.* Two questions rather than one: pages with `pairQuality > 0` choose a
framing, as today; pages with `pairQuality == 0` choose a **recipe**.

*Portable subset.* `destWidth/Height`, `groups[].s/tx/ty`, `badgeSlots`,
`lineSlots`, `titleDst` and its font, size and colour, `listFontSize`,
`listSample`, `characterStyles`, `minPin`, `pinSizeScale`. Dropped as
source-specific: `mapSrc`, `groups[].src`, `groups[].dst`, `templateSlide`,
`pairQuality`, `source`, `framingPinned`.

*Constraint for v1: single-group recipes only.* `_group_for_item` assigns objects
to a cluster by the wall-side `src` rects, which mean nothing on another page.
With one group every object takes it regardless, which is exactly the case worth
having. Multi-group reuse needs a rule for re-anchoring and is out of scope.

*Plumbing is one branch.* `plan_payload_transforms` already re-learns per slide
keyed by `framing_overrides[number]`. Add `recipe_overrides: dict[int, dict]`
beside it; where a slide has one, it replaces the learn step. The fit-to-frame
guard stays, so a reused recipe that throws content off-canvas degrades the same
way an automatic choice does.

*Storage.* A curated asset like a template, not a cache — a tracked `recipes/`
folder of small JSON files, each with a label an operator would recognise
("full-bleed centre panel, from Extracted_CG_3rd slide 2"). Not `.cache/`, which
reads as disposable.

*Preview costs nothing new.* "Where objects land" and "as it will look" are both
derived from the plan, so a recipe picker reuses them unchanged.

*Order within this item:* portable subset + `recipe_overrides` + headless tests
first, then persistence, then the picker. The first step is testable with no
Keynote and no UI.

## Order of work

1. Structural title detection. Cheap, self-contained, and a prerequisite for
   recipes carrying anything but artwork.
2. Recipes as browsable artefacts.
3. The number block in the CG resizer, above.
4. Cue palette and outline editor.
5. Image cues.
6. DSK generator, unchanged from the superseded plan including its four corrections.

Stat drift is independent of all six and can land whenever.

## Still parked

- **The "natural upgrade" idea.** Noted as a nice improvement, deliberately not now.
- **The JXA export has never worked.** Every exporting payload carries
  `exportError` while still succeeding, because `export_slide_images()` picks up
  after `exportImages()` fails. Pre-existing, true on 14.5/macOS 14 as well. Worth
  cleaning up, not urgent.
- **PNG export fidelity.** The two Keynote versions' exports differ by 117 pixels
  on one slide at a maximum channel delta of 2/255 — renderer rounding, not a
  dropped object. This is a negative result rather than a clearance: the original
  symptom appeared on a full sermon deck mid-service, far more complex than the
  3-slide template it was tested against. Keep watching.

## One standing caution about confirmation

Measured offline: overrides are honoured, every candidate asked for is the one
used. But **fit-to-frame still overrules them on pages where nothing in the
template describes the page** — on `Full_Report_Card_Wall` slide 1 all three
candidates fell back, and agreement was 1 on every candidate, meaning almost
nothing corroborated the affine. Falling back there is correct.

The consequence is not cosmetic: on those pages a confirmation changes nothing and
the operator must be told so per page rather than in a footnote, or the flow lies.
The UI does this now via `wouldFallBack`. Keep it if that code is touched — it is
the specific failure the step was written to rule out. The deeper point is that
confirmation only bites when the template has a framing worth picking, so the count
of pages with no candidate at all is the prompt to add template slides, which is
the real fix rather than a per-page override.
