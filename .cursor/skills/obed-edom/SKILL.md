---
name: obed-edom
description: >-
  Generates separate LW (LED wall) and DSK Keynote decks from semantic-cue
  sermon/offering Word outlines, writes operator [LW]/[DSK] cues back into a
  copy of the outline, checks Bible references against Bible Gateway, and flags
  contrast issues. Use when the user mentions sermon slides, DSK, LW, FW, LED
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
  Inside `tell application "Keynote"`, `menu` resolves to a Keynote class and the
  script fails to compile.
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

Leave out: anything you are not teaching. Stray leftovers only add noise. Also
avoid keeping a full-canvas 1:1 "cover" reference on a second slide alongside a
scaled layout — the two teach contradictory transforms.

Overlays and pins sitting near an anchor inherit its affine, so they need not
all be present. Sparse is fine; wrong-sized is not.

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

## Keynote scripting limits (verified, do not re-litigate)

- **Per-run character style is unreachable.** `objectText.attributeRuns()`
  raises "Can't convert types."; `paragraphs()`, `characters()` and `words()`
  return plain strings carrying no colour, size or font. A string also answers
  `.bold()` — that is `String.prototype.bold()`, always truthy — so a probe can
  look like it works while reporting nonsense. Anything needing per-character
  style must come off a rendered preview. `scripts/probe_runs.js` reproduces it.
- **Z-order is unreadable.** `slide.iWorkItems()` reports 0 on slides holding 19
  real objects. Stacking is therefore a deliberate policy — the `role_order`
  sort in `plan_slide_transforms` — not something recovered from the deck.
- **A text box is also a shape.** Keynote lists text-bearing shapes in both
  `textItems` and `shapes`; a third of text objects came back twice on a real
  wall deck. `inspect_keynote.js` marks the duplicate rather than dropping it,
  because objects are resolved by (collection, kindIndex) and those indices must
  keep matching Keynote's.
- **The inspect cache is keyed by deck digest**, which says nothing about the
  code that produced it. Bump `INSPECT_VERSION` in `baseline.py` when the
  payload shape changes, or old payloads are reused forever.

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
