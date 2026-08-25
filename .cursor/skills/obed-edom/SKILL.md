---
name: obed-edom
description: >-
  Generates separate LW (LED wall) and DSK Keynote decks from semantic-cue
  sermon/offering Word outlines, writes operator [LW]/[DSK] cues back into a
  copy of the outline, checks Bible references against Bible Gateway.
  Use when the user mentions sermon slides, DSK, LW, FW, LED
  cues, Keynote templates, Offering JX.docx, Sermon BC.docx, TITLE/FILLER/VERSE
  /POINT/NUM-POINT cues, running python -m obed_edom generate, or changing
  the operator dashboard under dashboard/src. Also covers the CG resizer that
  crops wall decks to 16:9 (base asset templates, affine recipes, church-name
  list placement, scoring against a finished CG) and the verified limits of
  Keynote's scripting API for run styles, z-order and duplicate items.
---

# Obed-Edom

## Command

From the repo root:

```bash
python -m obed_edom generate "/path/to/outline.docx" \
  --lw-template "/path/to/Sermon_GW.key" \
  --dsk-template "/path/to/2026_Lower-Thirds (ENG).key"
```

Local operator dashboard (generate, diff, DSK stub, CG resize stub):

```bash
python -m obed_edom dashboard
```

That process serves the prebuilt SPA in `dashboard/dist`, not `dashboard/src`.
**Always rebuild** after any dashboard UI change (`dashboard/src/**`) before
considering the work done — do not leave a rebuild for the user:

```bash
cd dashboard && npm install && npm run build
```

Then restart `python -m obed_edom dashboard`. Vite `npm run dev` is only for
hot reload; the Python dashboard still needs a fresh `dashboard/dist`.

Staff-only parse (no Keynote):

```bash
python -m obed_edom generate "/path/to/outline.docx" --no-keynote
```

Writes `output/<stem>/`:

- `<stem>_LW.key` — from the dropped / `--lw-template` Keynote when an LW template is supplied
- `<stem>_DSK.key` — from the dropped / `--dsk-template` Keynote when a DSK template is supplied
- `<stem>_CUED.docx` — the outline with operator `[LW]` / `[DSK-…]` cues for show-call
- `review.pdf` — short checklist for the operator
- `previews/lw/` and `previews/dsk/` PNGs

Never overwrite the dropped templates. Never overwrite the source outline.

## When to run

- User drops a sermon / offering / testimony `.docx` with semantic layout cues, plus at least one Keynote template (LW, DSK, or both), in the dashboard
- CLI generate needs `--lw-template` and/or `--dsk-template` unless a matching file still exists under local `Default Templates/`
- Experiment files (local, gitignored): `Sermon Outlines/Sermon BC.docx`, `Sermon Outlines/Offering JX.docx`

## Input cues (semantic)

Ignore highlight colour on these for now.

| Cue | Slides |
|---|---|
| `[TITLE]` | LW `TITLE` bumper only. Outline text is not placed on LW. |
| `[FILLER]` (sermon) | Same as TITLE. |
| `[FILLER]` (offering) | LW `BLANK` + DSK `Ways To Give QR Code` |
| `[FILLER-QR]` | LW `BLANK` + DSK QR |
| `[GIVING-OPTIONS]` | LW `BLANK` (paste graphic) + DSK credit-card giving layout |
| `[VERSE]` | LW `VERSES` + DSK verse layout; long passages split. Never produces a point + verse slide, even straight after a point. |
| `[VERSE-CONTINUED]` | Rest of the previous verse (oral pause mid-verse). This slide shows the verse so far, with a leading verse number so body copy stays on the baseline. A `[VERSE]` with no verse number after a verse is treated the same. `[VERSE-FROM-PREVIOUS]` is a deprecated spelling: it still maps, but raises `cue.deprecated_alias`. |
| `[VERSE-AFTER-POINT]` | The point + verse slide, on the LW / DSK POST masters. Valid only directly after `[POINT]` or `[NUM-POINT]`; that point gets the 1s Magic Move into it. Skip DSK POST when the point is too long for the lower-third column (`dsk.point_post_max_chars`). Alias: `[VERSE AFTER POINT]`. Orphaned, it is flagged and falls back to a plain verse. |
| `[POINT]` | Non-numbered PRE. Magic Move only when the next cue is `[VERSE-AFTER-POINT]`. |
| `[NUM-POINT]` | Numbered PRE, same rule. Word list numbering supplies the point number. |

`[Pray]`, `[Instructions]`, neighbour-turn lines → stage directions, not slides.

Do not invent extra layouts (images, etc.). Flag unknown cues instead of guessing.

**One cue is one slide advance on that deck.** Nothing advances by itself, so the
`[LW…]` cue count equals the LW slide count and likewise for `[DSK…]`. The Sermon
Checker depends on this to catch a slide with no cue, or a cue with no slide. Do not
reintroduce an implicit slide: that is what `[VERSE-AFTER-POINT]` replaced.
`tests/test_parse.py::test_every_slide_has_exactly_one_cue` locks it in.

## Later verse numbers need Accessibility

A multi-verse slide (`26 … 27 … 28 …`) needs every verse number raised as a cyan
superscript. Generate does this in two passes, and the second pass drives
Keynote's **Format > Font > Baseline > Superscript** menu through System Events.
That is why macOS asks for Accessibility for whatever launched generate
(Terminal, iTerm, or the dashboard app) in
*System Settings > Privacy & Security > Accessibility*.

**What pass 2 does.** The template applies its verse-number character style to
the *first* verse number only — `SuperScript` in `Sermon_GW.key`, `Verse Number`
in `2026_Lower-Thirds (ENG).key`. Pass 2 selects that first number, runs
**Format > Copy Style**, then selects each later number and runs **Paste Style**.
That carries the named character style across, so no style name is hardcoded:
whatever the template puts on the first number is what the rest inherit.

**Why the UI is unavoidable.** Keynote's AppleScript dictionary has no style
support at all — `grep -i style` on `Keynote.sdef` returns only `export style`
and chart types. Superscript is not a character property either; `font`, `color`
and `size` are the only ones exposed.

Verified against Keynote 14.5. Every scriptable route was tried and rejected by
Keynote itself, and **each one fails silently inside a `try` block**, so a broken
pass still looks like it succeeded:

| Attempt | Keynote's response |
|---|---|
| `set character 37 to character 1` | Copies text only; size stays at the body size |
| `duplicate` a text item | `Shapes can not be copied` |
| `duplicate paragraph` / `word` | `Words can not be copied` |
| `set size of character N to 46.67` | `size` is the *base* size; superscript renders it at 2/3, so this only shrinks the glyph onto the baseline |
| Unicode `²⁷` / `²⁸` | Latin-1 `²³` and the superscripts block `⁴-⁹` are different code charts, so digits render mismatched |
| Character Styles popup in the Format sidebar | The control is an `AXButton` whose menu never opens under `click` or `AXPress` |

**Apply each anchor once per occurrence.** Find cycles through matches, and a
magic-move POST slide reuses the same verse box, so the Matthew passage lives on
two slides. Styling once fixes one instance and leaves the other on the baseline
— which reads as "the fix doesn't work" when it is really a miscount.

Do not "simplify" pass 2 back into pure AppleScript, do not swap Paste Style for
raw `Baseline > Superscript` (that skips the character style), and do not
reintroduce placeholder Find tokens (`‡‡`): when the GUI step is skipped, tokens
leak onto the slide, whereas real digits just lose the raised styling.
`tests/test_parse.py::test_later_verse_numbers_get_the_template_character_style`
and `::test_repeated_verse_box_is_styled_on_every_slide` lock this in.

If Accessibility is denied, generate flags it and the digits stay on the
baseline — the wording is still correct, so the deck is usable.

Other constraints worth keeping:

- Pass 1 saves but does **not** close, and defers its PNG export; pass 2 exports
  and closes. `open` in pass 2 is then a bring-to-front on the already-loaded
  document. Reinstating pass 1's export renders every slide twice and captures
  the verse numbers *before* they are styled.
- Because the deck stays open between passes, pass 1 first closes any document of
  the same name without saving. Python has already overwritten the file with a
  fresh template copy, so a document left open by an interrupted run is stale and
  `open` would hand that back — the rebuild then fails with `-10000`. Keep this
  guard: without it, one failed run poisons every later run until Keynote is
  quit. It only ever closes the deck being regenerated.
- `_collect_superscript_jobs` must only emit jobs pass 2 can act on (a seed
  anchor plus at least one anchored later verse), because a non-empty job list is
  what makes pass 1 hand the deck over. An unusable job would leave the deck
  open, unexported and never closed.
- GUI scripting must live in its own `tell application "System Events"` block.
  Inside the Keynote `tell`, `menu` resolves to a Keynote class and the script
  fails to compile. The System Events target is matched on bundle identifier, not
  `process "Keynote"` — see the section below for why the name is ambiguous.
- Keynote is driven from a script *file* via `osascript`, not stdin: from the
  dashboard's worker thread the clipboard/HIServices connection dies and
  Keynote's dictionary never loads.
- Debugging this is much easier with only the target deck open. With several
  documents open, `document 1` and the keystroke target can be different windows,
  which makes a working pass look broken.

## CG resizer (wall 7680×1080 → CG 1920×1080)

Copies the wall deck and moves objects in place, so builds survive. A 16:9
"base asset" Keynote teaches the target positions: objects are paired wall to
template, each pair implies a scale-and-offset, and pairs that agree form a
group that everything nearby inherits.

```bash
python -m obed_edom remap "Wall.key" --template "Base_CG_Assets.key" \
  --slides 2 --include-lists [--source-previews FOLDER]
```

### What goes in the base asset template

The one rule that matters: **every object must sit at its final CG size and
position.** Scale is derived from each pair, so an object left at wall-native
size teaches "translate, don't scale" — and if that contradicts the rest, the
gutters you made disappear.

| Put in | Why |
|---|---|
| One slide per wall layout, named `<wall layout name> (16:9)` | `applyCgLayouts` swaps layouts on an exact suffix match. `MAP BLANK` needs `MAP BLANK (16:9)`. |
| The map art at its final CG size | This is what sets the scale, and **the map's size decides how much room the name lists get.** Shrink it to create gutters. |
| One text swatch per character style | Font, size and colour are copied onto unpaired wall text. Needs real text in a real box; the wording is irrelevant. |
| The resized title plate | Gives the title cluster its own affine, separate from the map. |

**More anchors is better, not worse.** The affine is trusted in proportion to how
many objects agree on it: the deck that works well has 10 of 18 paired objects
agreeing, and that agreement is what picks the pairing strategy. A single anchor
gives one pair and no corroboration, so include the overlays and pins rather
than trimming to a minimum. What must not be there is anything at the *wrong*
geometry — wall-native sizes, or objects parked off-canvas.

One thing to keep out: a full-canvas 1:1 "cover" reference on a second slide
alongside a scaled layout, since the two teach contradictory transforms.

### One slide per framing you actually use

Template slides compete per wall slide, and selection is good at this: given the
20 framings harvested from a finished report deck, it picks the human's framing on
23 of 29 pages, and five of the six misses are the same map size shifted 120px.

Measured on Keynote 15.3.1, and re-measure with `scripts/try_multi_framing.py`
rather than trusting this figure — an earlier note here said 25 of 29 with four
misses, which no longer matched and briefly looked like an upgrade regression. It
is not: the report-card payloads read byte-identically on 14.5 and 15.3.1, so the
old number simply predated later changes to selection.

So a deck whose pages are framed differently — report cards, where each country
is cropped to suit — wants one template slide per framing. What it cannot do is
predict a framing it has never seen, and next week's countries are new. Pages
with no matching framing fall back to fitting their visible content into the
frame and are reported, so nothing is lost and the operator knows where to look.

### Before you run

- **Delete skipped slides.** They are read but never remapped, and Keynote
  reads and exports every slide regardless — on one gold CG they held 21% of
  all items. Deleting them is the cheapest speed-up available.
- **Delete side-panel content you do not want carried over.** Anything outside
  the centre 1920×1080 has nowhere to go after the crop.
- **Feed the original wall deck**, never a previous CG output. Generate refuses
  when it sees more than ten pins at (0,0), which is the usual symptom.
- **Quit Keynote between large runs.** It wedges after a few GB, and a document
  left open from an interrupted run is stale — `open` hands that copy back and
  the run fails with `-10000`.

### What happens to loose text

Text is sorted by what sits under it on the wall. Text overlapping artwork is
a label, so it keeps its position relative to that artwork. Text sitting on
bare background is free, so it is re-placed into whatever background the CG has
left, measured from a rendered wall slide rather than from rectangles — the map
image covers the whole frame while most of it is ocean.

Nothing is ever dropped. When there is no clean gap the box goes where it
covers least and is reported with an overlap percentage, for the operator to
break up by hand. Previews come from any earlier inspect of the same deck for
free; `--source-previews` overrides, and without either, packing falls back to
the old right-to-left fill.

### Judging a change

`scripts/score_resize.py` compares planned output to a finished CG deck offline,
from the inspect cache. Read `goldRmse` — our placement of an object versus
where the gold deck's own transform would put that same object. Zero means the
same layout was chosen.

Do not read a quality score into `list` or `title` rows. Lists get reflowed into
a different number of columns by hand, and `titleDst` is a deliberate override,
so in both cases there is no object-for-object correspondence to measure. For
lists, judge by whether every box was placed and by the overlap percentages.

`templateScore` in the remap result is a self-consistency check, not a quality
score: the recipe was learned from that same template, so anything other than
roughly zero means the planner failed to apply the affine it derived.

### Measuring without opening Keynote

Reading a wall deck costs minutes (a 6.8 GB deck took 11½, a 7.2 GB one 21), and
Keynote is single-instance, so iterating through it is painful. Everything below
runs from the cache root — `.cache/` at the repo root, moved with
`OBED_EDOM_CACHE_DIR` — in seconds. It sits outside `output/` deliberately: a
tidy-up of the output folder once threw away an hour of Keynote time.

| Script | Answers |
|---|---|
| `scripts/score_resize.py` | Placement error per slide and role against a finished CG deck. `--no-previews` compares against the old blind packing. |
| `scripts/try_free_space.py` | Where loose text would land, as a picture: mask, old positions, new positions. |
| `scripts/try_multi_framing.py` | Whether framing selection picks the framing a human chose, given several candidates. |
| `scripts/inspect_gold.py` | Warms the cache. `--template-only` after editing the template, which is the one deck whose digest changes. |
| `scripts/probe_runs.js` | Reproduces the unreachable-run-style result on demand. |
| `scripts/probe_zorder.js` | Reproduces both z-order results: the mixed collection will not enumerate, and no arrange command exists. Builds its own throwaway deck, so it needs no gold deck. |

Only warm the cache when a deck changes. Keep tests on the two `Map_Extracted`
pairs; `Full_Report_Card` is 158 and 207 slides and only worth running when
something specifically needs it.

### Metrics that mislead

Framing selection went through five rewrites in one session, each fixing a real
case and several creating the next. All four traps below looked obviously
correct when written:

- **Matching points by proximity.** 138 pins sit about 6px apart while a layout
  difference offsets everything by up to 190px, so each pin matches one about
  thirty places away and the error is noise. Both sides derive from the same wall
  objects, so compare by identity — project the wall through the gold's own
  transform. `score_against_gold` does this; `nearestRmse` is kept only as a
  reminder not to use it.
- **Scoring how much content stays inside the frame.** Maximised by shrinking:
  a framing that squeezed everything into a corner scored a perfect 1.0 and won
  every tie. Multiply by how much of the frame is filled, so neither shrinking
  nor overflowing wins.
- **Measuring fit over everything visible.** The side-panel name lists run about
  three times wider than the map, and they get relocated anyway, so a framing
  that kept the map at true size was punished for not containing them. Measure
  the artwork that paired into the affine.
- **Ranking on the raw template score.** It is agreement×100 plus a pair count,
  so one extra paired object outranked a fit two and a half times better. Rank on
  the agreement level and let fit settle ties within it.

One more of the same shape: the old blind packing was *hiding* a bug rather than
causing one. Every map label was being snapped to a single template position, and
the packing spread them out again afterwards. Deferring the packing revealed the
collapse. When two layout paths sit in front of each other, check whether the
outer one is masking the inner.

**The pattern matters more than the four instances.** Every fix was a genuine
improvement and most exposed the next problem. That is the signature of a metric
being asked to infer something the data does not contain: which crop of a map the
operator wants is an editorial choice, and no amount of pixel area encodes it. An
operator looking at two framings of the same 1364x947 map knew instantly which
was right; the geometry says nothing. So when framing selection needs another
exception, a sixth metric is the wrong move — asking is the right one.

This repo already has the pattern for asking. The Sermon Checker proposes slide
pairings, shows them, lets the operator correct them, and remembers the answer
across runs by content digest: `/api/diff/{id}/slots`, `save_pairing`, and the
slot remapping in `baseline.py`. Reuse it rather than inventing a confirmation
flow. Ask from the inspect alone, before remapping, so it costs no extra Keynote
pass, and keep the fit-to-frame fallback so an unconfirmed deck degrades instead
of breaking.

## LW deck facts worth knowing

- **Verses are duplicated across the centre panels.** The wall is long, so the
  same verse is set twice for readability. Any text extraction must collapse
  those, or every verse is counted twice.
- **Bilingual services can put English on one side and Chinese on the other.**
  So two same-size boxes side by side are not always a mirror: identical text is
  a mirror and should collapse, differing text is likely a translation pair and
  should be reported rather than silently halved.
- **Masters carry no cue information.** On a real finalised LW deck all 66
  slides were `BLANK`, `BLACK BLANK` or a filler master — there was no `VERSES`
  or `NUMBERED POINT PRE` anywhere. Font and size identify slide kinds instead
  (verse reference vs verse body vs point), which is why those live in
  `masters.yaml` rather than in code.

## Keynote 15.x only, and never addressed by name

**Supported: Keynote 15.x on macOS 26.** 14.x support was removed deliberately
once the staff machines were confirmed on 15.3.1, and there is no fallback to
another build — a missing Keynote fails naming the identifier it wanted.

**If something breaks in a way that smells like a scripting difference** — a
master not found, a collection that will not enumerate, an export that silently
produces nothing, a deck that will not open — **a 14.x machine is one of the first
things to rule out.** The fix is to restore a fallback in
`src/obed_edom/keynote_app.py`, not to work around it at the call site.

Keynote 15 installs as **`Keynote Creator Studio.app`** with bundle identifier
`com.apple.Keynote`; 14.x was `Keynote.app` / `com.apple.iWork.Keynote`. Both set
their bundle *name* to "Keynote", so with both installed:

- `tell application "Keynote"` resolved to **14.5**, not 15.
- `Application("Keynote")` in JXA did the same.
- `process "Keynote"` in System Events was equally ambiguous.

An upgrade therefore looks like a no-op: every script keeps driving the old app
while appearing to test the new one. Uninstalling 14.5 makes the name resolve to
15.3.1 again, which is exactly why the by-name habit is dangerous — it works until
someone has two builds. So `keynote_app.py` is the one place that decides,
everything addresses the app by bundle id (`tell application id "…"`,
`using terms from application id "…"`, `Application(bundleId)`, `open -b`), and
the JXA scripts take `bundleId` in their plan JSON.
`OBED_EDOM_KEYNOTE_BUNDLE_ID` drives a different build and partitions the cache
with it.

Resolution asks LaunchServices first — one targeted lookup that touches no other
app — and falls back to reading `Info.plist` off disk when that is unavailable, as
it is inside a sandbox. Keep that order: the scan is the only thing that reaches
third-party bundles, and malformed ones are common enough that one game in
`~/Applications` broke resolution in testing. The scan tries the names Keynote
ships under before enumerating, and skips any app whose plist will not parse.

`tests/test_keynote_app.py` locks the targeting and the cache split in.

## Keynote scripting limits (verified on 15.3.1)

Re-probed on macOS 26.6.2 against 14.5 and 15.3.1 side by side, driven by bundle
id, while both were still installed. **Every answer below was identical on the
two**, so the upgrade changed nothing we depend on. 14.5 has since been
uninstalled, so 15.3.1 is now the only version these hold for. Re-probe after the
*next* upgrade with `scripts/probe_runs.js` and `scripts/probe_layouts.js`, both
of which take a bundle id as their last argument.

- **Per-run character style is unreachable.** `objectText.attributeRuns()`
  raises "Can't convert types."; `paragraphs()`, `characters()` and `words()`
  return plain strings carrying no colour, size or font. A string also answers
  `.bold()` — that is `String.prototype.bold()`, always truthy — so a probe can
  look like it works while reporting nonsense. Anything needing per-character
  style must come off a rendered preview. `scripts/probe_runs.js` reproduces it.
- **Z-order can be neither read nor set.** Verified on 15.3.1 by
  `scripts/probe_zorder.js`; both halves are Keynote limits, not our bugs.
  - *Reading:* `slide.iWorkItems()` raises "Can't convert types.", so the one
    collection that would interleave classes in stacking order is unavailable.
    Earlier notes said it returned 0 on slides holding real objects; on macOS 26 it
    raises on both Keynote versions, so the version is not what changed it. No
    per-item substitute exists either — `zOrder`, `zOrderIndex`, `stackingOrder`
    and `layer` all raise, and `index` gives "Can't get object."
  - *Writing:* `Keynote.sdef` contains **no arrange vocabulary at all** — no
    bring-to-front, send-to-back or z-order property on `iWork item`, whose entire
    property list is height, locked, parent, position, width. JXA hands back a
    function for any name you ask for, so `app.bringToFront` looks like it exists;
    calling it gives "Message not understood." Reordering is GUI-only.
  - *What is knowable:* per-type collections do enumerate in creation order
    (`slide.shapes()` returned the three probe shapes in the order they were made),
    so relative order **within** one class is recoverable. Cross-class is not, and
    that is the part stacking actually needs.
  - *Consequence for resize:* the resizer duplicates a slide and then moves,
    resizes and deletes the objects already on it, so it inherits the source deck's
    stacking untouched. It cannot repair a bad stack, but it cannot break a good
    one. Only generate, which creates objects, controls stacking — by creation
    order, via the `role_order` sort in `plan_slide_transforms`.
- **`masterSlides()` is broken in JXA, but AppleScript `master slide` is fine.**
  `doc.masterSlides()` raises "Can't convert types." while `doc.slideLayouts()`
  returns all 9. In AppleScript the same collection answers perfectly: `count of
  master slides` gives 9, `master slide "MAP BLANK (16:9)"` resolves, and `make
  new slide with properties {base slide:…}` creates a slide with the right `base
  layout`. Generate depends on that AppleScript path and is unaffected — but it is
  why `keynote_jxa.js` must stay unused, since porting slide creation to JXA would
  fail on the very lookup it needs.
- **A text box is also a shape.** Keynote lists text-bearing shapes in both
  `textItems` and `shapes`; a third of text objects came back twice on a real
  wall deck. `inspect_keynote.js` marks the duplicate rather than dropping it,
  because objects are resolved by (collection, kindIndex) and those indices must
  keep matching Keynote's.
- **The JXA export always fails; the AppleScript fallback is what works.** Every
  payload that exported carries `exportError: "Keynote export as slide images
  failed."` alongside `exported: true`, on 14.5/macOS 14 as well as on both
  versions under macOS 26. So `exportImages()` in `inspect_keynote.js` has never
  produced the PNGs — `export_slide_images()` in `inspect.py` does, after the JXA
  attempt has already cost a pass. Pre-existing, not an upgrade regression, and
  worth cleaning up rather than reading as a failure when it appears in a payload.

### What 15.3.1 unblocks

- **A slide layout's contents are readable.** `doc.slideLayouts()` returns 9
  named layouts, and each answers `textItems()`, `images()` and `shapes()`, with
  `objectText()` on a layout's text item giving its placeholder wording ("Slide
  Title"). So the cue palette can read a dropped template's layouts and their
  placeholders rather than having them declared by hand in `masters.yaml`.
- **An image can be placed from a file path, in AppleScript.** This is the one
  that matters, because the deck builder in `keynote.py` is AppleScript, not JXA:

  ```applescript
  make new image with properties {file:POSIX file imgPath, position:{120, 140}, width:640}
  ```

  Verified end to end — built that way, saved, then read back by
  `inspect_keynote` at exactly `x=120 y=140 w=640`. **Set one dimension and the
  other follows**: a 1920x1080 source given `width:640` came back `h=360`, so
  aspect ratio is preserved for free and the cue only needs to specify a width.
  `Keynote.Image({file: …})` works in JXA too, but nothing needs it.

- **A movie is placed by creating an image and then reassigning its `file name`.**
  There is no direct route — `make new movie` cannot be handed a file by any key —
  but this works, verified end to end:

  ```applescript
  set mv to make new image with properties {file:POSIX file imgPath, position:{40, 40}, width:300}
  set file name of mv to POSIX file mp4Path
  ```

  Assigning a video to an image's `file name` **converts the object into a movie**:
  `images` drops to 0, `movies` rises to 1. It keeps the position and width it was
  given, recomputes height from the video's aspect ratio, and survives save and
  reload — `inspect_keynote` reads it back as `kind=movie`, `x=40 y=40 w=300
  h=169`, `file=clip.mp4`.

  **So video slides are fully generatable, with no GUI automation.** The practical
  consequence for templates: a master needs only a small *image* placeholder, not
  an embedded video, since the image is what gets converted. That keeps template
  files small.

  The route matters because the sdef misleads here. `movie` has **no `file`
  property at all**, and `image`'s `file` is `access="r"` — yet `make new image
  with properties {file: …}` works. Creation-time keys and settable properties are
  different sets. The writable door on both classes is `file name`
  (`access="rw"`, accepting a file *or* text).

  **Two silent failures worth knowing.** `make new movie with properties
  {file name: …}` reports success in both the `POSIX file` and plain-text forms
  while creating nothing: `count of movies` stays 0 and the returned reference is
  `missing value`. A probe that trusts the absence of an error will conclude
  movies work when they do not — check the collection count, not the error.

  Incidentally the movie media inside these decks is `.mp4`; `.mov` in this repo
  means Keynote's *export* format for a movie slide, a different thing worth not
  conflating.
- **The inspect cache is keyed by deck digest**, which says nothing about the
  reader that produced it. Two axes need handling. Bump `INSPECT_VERSION` in
  `baseline.py` when the payload shape changes, or old payloads are reused
  forever; and the file name carries a `.k<Keynote version>` tag, because a
  digest-keyed hit would otherwise hand one build's payload to a run of another.
  Payloads also record `keynoteBundleId` and `keynoteVersion`.

  Untagged payloads predate the tag, were produced by Keynote 14.5, and are no
  longer read. **Uninstalling a Keynote version orphans its partition**, which is
  worth knowing before the next upgrade: the offline scripts
  (`score_resize.py`, `try_free_space.py`, `try_multi_framing.py`) all read the
  cache, so they go quiet until the decks are read again on the new version.
  The 14.5 payloads and their score table have been deleted: re-reading all seven
  gold decks on 15.3.1 reproduced that table exactly, object for object, so the
  old set held nothing the current one does not.

## Operator outline (`_CUED.docx`)

Semantic cues are replaced with show-call tags:

- Cyan `[LW…]` → LED wall (Word highlight `cyan`, shown as Turquoise)
- Yellow `[DSK…]` → lower thirds
- One operator cue per generated verse *slide*, at that chunk’s start. If 26–27 fit on slide 1 and 28 starts slide 2: `[LW][DSK-PP] 26 … 27 … [LW][DSK-PP] 28 …`. Independent LW vs DSK splits still share a tag when both decks start at the same verse.
- PRE tags stay on the point line. POST does not add a second `[LW][DSK-PP]` on the verse.

## After generate

1. Open `review.pdf`. The **Please check** section is the to-do list.
2. Open both `.key` files in Keynote. Do not merge LW and DSK — they run on separate PCs.
3. On multi-verse slides, check every verse number is a raised cyan superscript. If
   the later ones sit on the baseline, grant Accessibility (see above) and re-run.
4. Hand the operator `<stem>_CUED.docx` for the show-call script.
5. Bible: outline wording stays on the slide. Bible Gateway NIV is an audit (MSG when the outline labels it).
6. Contrast: bright LW photos are flagged only. Darken the background in Keynote if needed. **Do not auto-recolor text**.
7. If mapping looks wrong, say which cue and expected master, then re-run generate.
