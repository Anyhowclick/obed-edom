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

**Why the UI is unavoidable.** Keynote's scripting API cannot style a character at
all — superscript is not a character property, and only `font`, `color`, `size` are
exposed. The full statement, evidence table, and the resize side of the same limit
live under **[Keynote scripting limits → Character and run styling is NOT
scriptable](#keynote-scripting-limits-verified-on-1531)**. Every route was tried and
**each fails silently inside a `try`**, so a broken pass still looks like it
succeeded — verify the raised numbers on a rendered preview, not by the script
exiting cleanly.

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
| `scripts/probe_corner.js` | Dumps a shape's scriptable properties and resizes it: shows there is no corner-radius handle, so a rounded plate cannot be kept rounded across a resize. Builds its own throwaway deck. |

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

### The JXA/AppleScript split — most "limits" are JXA-only; re-test in AppleScript

**The single most important fact about scripting Keynote: JXA is crippled and
AppleScript is not.** Almost every "limit" first recorded here was probed in JXA
(`inspect_keynote.js`, `remap_keynote.js`, `scripts/probe_*.js`) and turns out to be a
**JXA marshalling artefact, not a Keynote limit** — the same feature works in
AppleScript. Systematically re-verified on 15.3.1 (throwaway decks + the real report-card
extracts). **Before ever recording a new "can't do X", test X in AppleScript.** The
codebase's inspect/remap are JXA, so they hit these walls and work around them; an
AppleScript path removes most of the walls.

| Capability | JXA | AppleScript | Genuine API? |
|---|---|---|---|
| Read a group's children (text, size, geometry), any depth | raises "Can't convert types" | **works** (`iWork items`/`text items`/`shapes of <group>`) | yes (elements in sdef) |
| Write a grouped child's position/width/height/font | can't reach | **works** in place | yes |
| `set selection of document to {objRef}` (target by reference) | raises | **works** | yes (`selection`, rw, on document) |
| Line `start point` / `end point` — read *and* write | null / collapses to 1u | **works** (endpoints stick, length recomputes) | yes (both rw in sdef) |
| `iWork items of slide` (the mixed collection) | raises | **enumerates, in *stacking order*** | yes |
| → **Z-order READ** (which object is in front) | impossible | **works** — read the `iWork items` order (front = last); Bring-to-Front moves an item to the end | via the collection |
| Per-character `font` / `color` / `size` write | flattens / partial | **works, isolated to that character** (setting char 1 leaves char 2 untouched) | yes — but only these three |
| `master slides` (create slide from a master) | raises | **works** | yes |
| `parent` of an item (its container) | — | **works** (readable) | yes (r) |
| Export slide images | always fails (`exportError`) | **works** (AppleScript `export … as slide images`) | yes |

**Genuine API gaps — absent from `Keynote.sdef`, so *neither* bridge can do them:**
- **Character styling beyond `font`/`color`/`size`** — no `baseline shift`, `superscript`,
  `underline`, `strikethrough`, `capitalization`/small-caps. Confirmed by sdef (rich text
  exposes only those three) and by AppleScript **failing to compile** an unknown property.
  *So the superscript verse-number raise still needs the GUI Copy/Paste-Style pass* — it
  is the baseline-shift that is unreachable, not the colour (colour is per-character
  settable). This is the one styling wall that is real.
- **Corner radius** — no property on `shape` in the sdef. Real in both bridges.
- **A settable z-order *property* / an arrange *command*** — none in the sdef. But z-order
  is still fully workable via AppleScript: **read** the `iWork items` order, **set** with
  GUI Bring-to-Front / Send-to-Back on a script-set selection, **verify** by re-reading
  the order. So "z-order can be neither read nor set" (below, kept for history) is
  **wrong for AppleScript** — it was a JXA statement.

The entries below were the original JXA findings; read them as "true in JXA" and see this
table for the AppleScript reality. `scripts/probe_gui_*.applescript` and
`probe_open_group_read.applescript` / `probe_group_tree.applescript` reproduce the
AppleScript results (local, `*.applescript` is gitignored).

### Driving Keynote by script — environment gotchas (osascript/AppleScript)

These are *environmental*, not logic, and each one fails in a way that looks like your code
is wrong. They cost hours to rediscover. Check them **before** any long-running Keynote
script — a 5-second smoke test on a tiny deck surfaces all of them before you pay the
~2-minute open of a real deck.

- **Keynote is sandboxed — it cannot open files under `/private/tmp` (or other non-user
  dirs).** `open POSIX file "/private/tmp/…"` fails *silently*: no document appears,
  `count of documents` stays 0, no error. Put working copies under `~/Desktop/…` or the repo
  (`output/` is gitignored) — a location the user's Keynote can read.
- **`open POSIX file …` returns `missing value`, not the document.** So `set doc to open …`
  gives you nothing. And do **not** blindly fall back to `front document`: with another deck
  open it binds the WRONG one, and your geometry writes / `save` then land on the user's deck
  — a real incident in this project. **The proven bind** (what `_build_superscript_fix_script`
  and the stat-finalize *reopen* path ship) is: `close (every document whose name is "<name>")
  saving no` to evict stale same-name decks, then `open POSIX file …`, `activate`, and
  `set theDoc to document 1` — after the close+open, `document 1` *is* the fresh copy. Verify
  `name of theDoc` before any write.
  - **Two Keynote-15 gotchas the earlier "just compare `POSIX path of (file of d)`" advice
    missed** (both cost a Stage B debugging round — see `scripts/diag_doc_bind.applescript`):
    (1) `name of document` comes back WITHOUT the extension (`cg_ON`, not `cg_ON.key`), so a
    name check must accept the stem. (2) `POSIX path of (file of d)` **throws -1700**
    ("Can't … into type Unicode text") — the file specifier must be coerced first:
    `POSIX path of (file of d as alias)`. Use the path compare only when you genuinely
    can't close-by-name first (e.g. a deck that must stay open, as Stage B's attach pass
    needs), and confirm the coercion on a real deck before trusting it for any write.
- **The default AppleEvent timeout is 120 s** (`-1712 "AppleEvent timed out"`). Any single
  call on a large deck — the open, a `count`, a batched write loop — that exceeds it aborts
  the whole script. Wrap the `tell` in `with timeout of 3600 seconds`.
- **A 1 GB+ deck takes ~2 min just to open.** Never iterate script logic against the big
  deck. Prototype on a throwaway `make new document` (opens instantly; note new docs carry
  master-slide *placeholders*, and JXA object creation there is unreliable — re-fetch by
  index after `push`). Then run once on the real deck, and reuse an already-open doc rather
  than re-opening.
- **Always work on a COPY and `close … saving no`** so the source is untouched; and never
  force-kill Keynote while it holds the user's deck (see "never addressed by name" below —
  a `pkill -9` mid-open once locked the deck with "Operation not permitted").

- **Character and run styling is NOT scriptable — only `font`, `color`, `size`,
  and the box-write of those flattens the whole box.** This one limit governs both
  the sermon generator and the CG resizer, so check it before any text-styling
  idea. Nothing else about a run or character can be read or written:
  - A character's `properties()` returns exactly `font, color, pcls, size`. Reading
    `superscript`, `baselineShift`, `capitalization` (small-caps), `underline` or
    `strikethrough` each raises "Can't convert types."
  - `objectText.attributeRuns()` raises too; `paragraphs()`, `characters()`,
    `words()` return plain strings carrying no style. (A string still answers
    `.bold()` — that is `String.prototype.bold()`, always truthy — so a probe can
    look like it works while reporting nonsense.) `grep -i style` on `Keynote.sdef`
    returns only `export style` and chart types.
  - The only writes are the three properties, and `objectText.font = "X"` sets the
    **whole box** to one face, wiping every bold/coloured run. There is no per-run
    or per-character write. Keynote can only *delete* a character — never insert or
    set one.
  - So anything needing real run style must come off a rendered preview.
    `scripts/probe_runs.js` reproduces it. Every scriptable route was tried and
    rejected by Keynote itself, **each failing silently inside a `try`** so a broken
    pass still looks like it succeeded:

  | Attempt | Keynote's response |
  |---|---|
  | `set character 37 to character 1` | Copies text only; size stays at the body size |
  | `duplicate` a text item | `Shapes can not be copied` |
  | `duplicate paragraph` / `word` | `Words can not be copied` |
  | `set size of character N to 46.67` | `size` is the *base* size; superscript renders it at 2/3, so this only shrinks the glyph onto the baseline |
  | Unicode `²⁷` / `²⁸` | Latin-1 `²³` and the superscripts block `⁴-⁹` are different code charts, so digits render mismatched |
  | Character Styles popup in the Format sidebar | An `AXButton` whose menu never opens under `click` or `AXPress` |

  - *Generate consequence.* Raising each cyan superscript verse number is impossible
    by script, so generate drives **Format > Font > Baseline > Superscript** (really
    Copy Style / Paste Style) through System Events — which is why it needs
    Accessibility. Operational detail in **[Later verse numbers need
    Accessibility](#later-verse-numbers-need-accessibility)**.
  - *Resize consequence — never re-assert or rewrite a verse box.* Re-asserting even
    the correct single inspected face flattens the runs, so the body branch leaves
    `font` unset (`font=None`, `197edfd`; colour was already left to the source) and
    just moves the box in place. And a whole-box rewrite cannot be undone by
    re-applying captured style, because only font/size/colour come back — a rewrite
    to strip a verse's wall-authored line breaks **lost the superscript numbers and
    the small-caps LORD** and was reverted. Since a break also can't be swapped for a
    space in place (delete-only merges the words), **leave verse boxes untouched;** a
    stray hard break is a source-deck fix. See memory
    `lw-text-keeps-source-font-colour`.
- **Z-order can't be read, and can't be set *from the dictionary* — but GUI scripting
  reorders it, deterministically.** Verified on 15.3.1 by `scripts/probe_zorder.js`
  (dictionary limits) and `scripts/probe_gui_zorder.applescript` (GUI reorder works).
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
    calling it gives "Message not understood." Reordering is GUI-only — **but it
    works, and deterministically.** `scripts/probe_gui_zorder.applescript` selects a
    buried shape *by object reference* (`set selection of document to {shape}` — works
    in AppleScript, raises in JXA) and clicks **Arrange ▸ Bring to Front** via System
    Events; the before/after PNG render confirms the shape moved to the front. So no
    Tab-cycling and no readable z-order are needed to *set* stacking — select the
    target by geometry and Bring to Front. (Needs Accessibility, like every GUI pass.)
  - *What is knowable:* per-type collections do enumerate in creation order
    (`slide.shapes()` returned the three probe shapes in the order they were made),
    so relative order **within** one class is recoverable. Cross-class is not, and
    that is the part stacking actually needs.
  - *Consequence for resize:* the resizer duplicates a slide and then moves, resizes
    and deletes the objects already on it via JXA, so it inherits the source deck's
    stacking untouched. It cannot *read* a bad stack, but it can now **repair** one
    with an added GUI z-order pass (select the buried object by geometry, Bring to
    Front). Generate, which creates objects, still controls stacking by creation order
    via the `role_order` sort in `plan_slide_transforms`; that sort's comment claims
    apply order *is* stacking order — true for generate, and for resize it is now a
    starting point a GUI pass can override rather than a hard ceiling.
  - *Seen in the wild:* on `Map_Extracted_Wall_1st` the map layers sit above the
    title badge in the source deck. The badge lands on its slot exactly — measured
    at `(17,37) 411x123` off the rendered preview, matching gold — and is still
    buried from x≈220 onward, where the map's white landmass begins. It reads as a
    clipped plate and a title truncated to "Glob". **This is now fixable in code** via
    a GUI Bring-to-Front pass on the badge (above) — no longer only a source-deck or
    template fix, though those remain simpler when the deck is being edited anyway.
- **A shape's corner radius can be neither read nor set.** Verified on 15.3.1 by
  `scripts/probe_corner.js`. A shape's entire scriptable property bag is `opacity,
  parent, pcls, reflectionShowing, backgroundFillType, position, objectText,
  width, rotation, reflectionValue, height, locked` — there is no `cornerRadius`
  (it raises "Can't convert types.") and no shape-type at all. So a rounded
  rectangle's rounding is invisible to the pipeline and cannot be restored after
  the fact.
  - *Consequence:* setting `width`/`height` on a rounded plate squares its corners
    — the rounding is a property we cannot carry across a resize. The only lever is
    whether we resize at all: a plate that is only *moved* keeps its rounding.
  - *What the resizer does:* a **corner label** — a plate with one word on it, no
    logo, bleeding off a corner (`badgePlateDst` crosses a frame edge) — is moved
    to the template's corner at its own wall size rather than resized into the
    template's slot, so a rounded plate stays rounded and a longer word (English in
    a slot cut for shorter text) still fits. See `_title_badge`'s corner-label
    branch in `plan_slide_transforms`. A **missions badge** (a plate with a logo)
    still takes the template slot as badge-affine intends; if such a plate were
    rounded it would lose its corners, and there is no script fix — the template or
    source deck is where that would be addressed.
- **`masterSlides()` is broken in JXA, but AppleScript `master slide` is fine.**
  `doc.masterSlides()` raises "Can't convert types." while `doc.slideLayouts()`
  returns all 9. In AppleScript the same collection answers perfectly: `count of
  master slides` gives 9, `master slide "MAP BLANK (16:9)"` resolves, and `make
  new slide with properties {base slide:…}` creates a slide with the right `base
  layout`. Generate depends on that AppleScript path and is unaffected — but it is
  why `keynote_jxa.js` must stay unused, since porting slide creation to JXA would
  fail on the very lookup it needs.
- **A group's children are readable in AppleScript, though `group.iWorkItems()`
  raises in JXA — the same split as `masterSlides()`.** `inspect_keynote.js` reads
  children via `group.iWorkItems()`, which raises "Can't convert types.", so every
  group inspects as `childCount:0` and its inner text/size look unreadable. In
  AppleScript the same group answers: `count of iWork items of <group>`, `text items
  of <group>`, `shapes of <group>`, and `object text` / `size of character 1` of a
  grouped text item all return real values *while still grouped* — verified by
  `scripts/probe_gui_ungroup.applescript` on a GUI-created group (`text items=1`,
  inner `text='hello' size=48.0`). So the `childCount:0` opacity is a JXA artefact,
  not a Keynote limit.
  - *Confirmed on the real source-deck groups*, not just an in-session one:
    `scripts/probe_open_group_read.applescript` (attach-only read of an already-open
    deck) dumped every stat block on `Map_Extracted_Wall_1st` slide 4 — the ones
    `inspect_keynote.js` reports as `childCount:0` — as `text items` with real content
    and size: `'269' size=300.0`, `'183'/'86'/'14' size=170.0`, `'44' size=70.0`,
    labels at 60.0. So the opacity is purely a JXA artefact.
  - *Consequence:* reading a stat block's inner "269" and its size does not require a
    GUI ungroup — an AppleScript group-inspection path exposes it. And a grouped
    child's geometry **is writable**: `scripts/probe_gui_write_child.applescript`
    (throwaway) set a grouped text child's `position`, `width`, and `size of character`
    (font size 48→24) in place, and a grouped shape child's `width` (200→90); only text
    `height` didn't stick because a text box autofits to content. So the resizer can
    read a grouped child, compute its CG target, and **write position/width/font-size
    straight onto the child** — no ungroup at all, even for resizing. (Setting a
    *group's* own width still doesn't scale its children — that limit is real and
    unchanged; the point is you address the children directly instead.) Writes were
    verified on an in-session group; the resizer operates on a copy, so exercising them
    on imported groups carries no risk to the source.
  - *Nesting, and a retired worry.* On `Map_Extracted_Wall_1st` slide 4 both JXA and
    AppleScript agree on **6 top-level groups** (`scripts/probe_group_tree.applescript`
    + a live JXA `slide.groups()` read); `slide.groups()` returns top-level only and does
    **not** flatten nested groups. Two of the six carry one level of nesting — the number
    (`183`, `44`) is a direct child, its label (`CHC Churches`, `Renovated Church
    Buildings`) sits in a nested sub-group — so a child read/write path must recurse one
    level. The plan's old "2 coincident duplicate groups / duplicate objects in the
    source deck" note came from a **stale cached inspect** (8 groups); the current deck
    has no duplicates, so that worry is retired, not real.
- **GUI ungroup / reorder is reachable, and can target objects by reference.** The
  dictionary has no group/ungroup/arrange command (confirmed in `Keynote.sdef` — only
  "move slide switcher backward"), so the *action* is GUI-only via System Events, like
  the superscript pass. Two facts make it deterministic rather than Tab-cycling:
  `selection` is a read-write `document` property, and **`set selection of document to
  {objRefs}` works in AppleScript** (raises "Can't convert types." in JXA); a
  script-set selection is a real UI selection that the Arrange menu acts on. Drive the
  action as a **menu-item click by name** (`click menu item "Ungroup" of menu "Arrange"
  of menu bar item "Arrange" of menu bar 1`) — **not** ⇧⌘G, which is *not* Ungroup
  (that is ⌥⇧⌘G). Two gotchas: a menu item's `enabled` state is stale for ~0.4s after
  `set selection` (query too soon and the click silently no-ops), and index-based
  object references go stale across a group/ungroup (re-fetch, don't hold them). Nested
  groups take one Ungroup round per level; the flatten terminal test is "0 groups" /
  "Ungroup disabled", never count-equality (nesting holds the count steady while
  progressing). `scripts/probe_gui_ungroup.applescript` reproduces all of this.
- **A text box is also a shape.** Keynote lists text-bearing shapes in both
  `textItems` and `shapes`; a third of text objects came back twice on a real
  wall deck. `inspect_keynote.js` marks the duplicate rather than dropping it,
  because objects are resolved by (collection, kindIndex) and those indices must
  keep matching Keynote's.
- **A line's endpoints are unreachable; its `width` is its length.**
  `startPoint` and `endPoint` read back `null` even on a line created with them,
  and *writing* them is worse than useless: it collapses the line to one unit
  long. `width` is the length whichever direction the line runs, and `height` is
  always 0 — a vertical rule 383px tall inspects as `w=383, h=0`. So a rule is
  placed by setting `width` and `position`, and it keeps the orientation it
  already had. Verified with `scripts/probe_line.js`:

  ```
  width=383 only ................. w=383
  width=383 then height=0 ........ w=383
  width=383 then position ........ w=383
  endpoints only ................. w=1
  w, h, start, end, position ..... w=1
  ```

  This is why a divider survived every check — planned correctly, applied without
  error, present in the deck — and still did not appear: the endpoint writes were
  undoing the size.
  - **AppleScript reads AND writes line endpoints correctly — this is JXA-only.**
    `scripts/probe_gui_zorder.applescript`-style probe: a line made with
    `{start point:{100,100}, end point:{400,300}}` reads back exactly that, and
    `set start point`/`set end point` stick (the line spans the new endpoints, `width`
    recomputes to the length). So the "endpoints unreachable" wall is a JXA artefact; a
    divider (or a node-graph's edges) can be placed by true endpoints in AppleScript,
    and edges can be re-routed to follow moved nodes. See the JXA/AppleScript table above.
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
