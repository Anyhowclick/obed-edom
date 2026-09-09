---
name: obed-edom
description: >-
  Generates LW (LED wall) and DSK Keynote decks from semantic-cue sermon,
  offering, or testimony Word outlines; writes [LW]/[DSK] show-call cues,
  audits Bible references, and resizes wall decks to 16:9 CG. Use for sermon
  slides, DSK, LW, FW, LED cues, Keynote templates, generate/remap/dashboard
  work, or Keynote automation in this repo.
---

# Obed-Edom

Obed-Edom turns a semantic-cue `.docx` into separate LW and DSK Keynote decks,
a cued operator outline, previews, and a review checklist. It also contains the
16:9 CG resizer and the Keynote/offline machinery it depends on.

## Commands

From the repo root:

```bash
python -m obed_edom generate "/path/to/outline.docx" \
  --lw-template "/path/to/Sermon_GW.key" \
  --dsk-template "/path/to/2026_Lower-Thirds (ENG).key"
```

Dashboard:

```bash
python -m obed_edom dashboard
```

After **any** `dashboard/src/**` change:

```bash
cd dashboard && npm install && npm run build
```

Then restart `python -m obed_edom dashboard`. `npm run dev` is only for hot
reload; the Python dashboard serves `dashboard/dist`.

Staff-only parse:

```bash
python -m obed_edom generate "/path/to/outline.docx" --no-keynote
```

CG resize:

```bash
python -m obed_edom remap "Wall.key" --template "Base_CG_Assets.key" \
  --slides 2 --keep-side-panels [SLIDES] [--source-previews FOLDER]
```

`--keep-side-panels` keeps content outside the centre wall band (church-name
side panels, badges); bare flag keeps it on every slide, `4,7` or `4-9` keeps
it only on those.

Generate writes `output/<stem>/` containing the LW/DSK decks, `_CUED.docx`,
`review.pdf`, and previews when applicable.

**Never overwrite the source outline or dropped Keynote templates.**

---

## Semantic cues

| Cue                   | Meaning                                                                       |
| --------------------- | ----------------------------------------------------------------------------- |
| `[TITLE]`             | LW `TITLE` bumper; outline text is not placed on LW                           |
| `[FILLER]` (sermon)   | Same as TITLE                                                                 |
| `[FILLER]` (offering) | LW `BLANK` + DSK `Ways To Give QR Code`                                       |
| `[FILLER-QR]`         | LW `BLANK` + DSK QR                                                           |
| `[GIVING-OPTIONS]`    | LW `BLANK` + DSK credit-card giving layout                                    |
| `[VERSE]`             | LW `VERSES` + DSK verse layout; long passages split                           |
| `[VERSE-CONTINUED]`   | continuation of the previous verse; leading verse number                      |
| `[VERSE-AFTER-POINT]` | POST slide after `[POINT]` / `[NUM-POINT]`; use only directly after the point |
| `[POINT]`             | non-numbered PRE                                                              |
| `[NUM-POINT]`         | numbered PRE; numbering comes from the Word list                              |

`[VERSE AFTER POINT]` is an accepted alias. `[VERSE-FROM-PREVIOUS]` is a
deprecated alias and should raise `cue.deprecated_alias`.

`[Pray]`, `[Instructions]`, and neighbour-turn lines are stage directions, not
slides.

Do not invent layouts for unknown cues; flag them.

### Cue/slide invariant

**One cue advances one slide on that deck.** There are no implicit slide
advances. Therefore `[LW…]` count must equal LW slide count and `[DSK…]`
count must equal DSK slide count.

`[VERSE-AFTER-POINT]` is the explicit replacement for the old implicit
point→verse behaviour.

---

## Verse-number styling

Multi-verse slides need every verse number styled as the template's cyan
superscript character style.

Keynote scripting cannot write the required baseline/superscript property.
Generate therefore uses two passes:

1. Create/save the deck.
2. In System Events, select the first styled verse number, `Format > Copy
   Style`, then paste that style onto each later verse number.

Do not replace this with raw `Baseline > Superscript`, a hardcoded character
style name, or placeholder Find tokens.

The GUI pass requires macOS Accessibility permission for the process launching
generate. If Accessibility is unavailable, generation should remain usable but
later verse numbers stay on the baseline.

A repeated verse box may occur on more than one slide. Apply each superscript
job to **each occurrence**, not merely each textual match.

The pass-1/pass-2 lifecycle matters:

* pass 1 saves and leaves the deck open;
* pass 2 brings it forward, applies styling, exports, and closes;
* do not reintroduce a pass-1 export or you capture the deck before styling.

Before a long run, guard against stale same-name documents. Never bind
blindly to `front document`.

---

## Keynote automation

### Version and targeting

The supported environment is **Keynote 15.x on macOS 26**; current verified
build is 15.3.1.

**Never address Keynote by name.** Keynote 15 and 14 can both resolve as
"Keynote". Always use the bundle identifier through the central
`keynote_app.py` machinery and pass the bundle id into JXA scripts.

Run/re-probe the automation assumptions after a Keynote upgrade.

### JXA vs AppleScript

The crucial rule is:

> **Before declaring a Keynote capability impossible, test it in AppleScript.**

Many apparent JXA limits are marshalling limitations, not Keynote API limits.
AppleScript can currently read/write grouped children, select objects by
reference, read the mixed `iWork items` collection, inspect z-order, manipulate
line endpoints, create slides from master slides, and export slide images.

The genuine scripting gaps are narrower:

* character styling beyond `font`, `color`, and `size`, including superscript,
  baseline shift, small-caps, underline, and strikethrough;
* shape corner radius;
* dictionary-level arrange/z-order commands;
* builds/animations — Keynote's sdef has **no build class at all**. `slide.builds()`
  never existed (an offline `attachBuildCounts` call on it always returns early with
  `buildCount: 0`). `transition properties` of a slide is the only scriptable piece,
  readable and writable; a transition record cannot be coerced `as string` — compare
  its enumerator fields explicitly instead.

GUI automation can bridge some of the latter, notably Bring to Front and
Ungroup.

### Environment traps

Before long Keynote runs:

* Work on a **copy**, never the user's source deck.
* Keynote cannot reliably open work under `/private/tmp`; use a user-readable
  location such as `~/Desktop` or repo `output/`.
* `open POSIX file ...` does not safely give you the document reference; use the
  proven close-by-name → open → activate → `document 1` pattern where possible.
* Treat a document's name as an extensionless stem when validating it.
* `POSIX path of (file of d)` needs coercion through `as alias`.
* Wrap long AppleScript calls in a sufficiently large `with timeout` block;
  the default 120 s is too short for large operations.
* Drive GUI scripting from a separate `tell application "System Events"` block.
* Prefer an AppleScript **file** executed by `osascript`, not stdin, for the
  dashboard worker path.
* Avoid debugging against several open decks. Another window can become the
  wrong `document 1` / keystroke target.
* Do not force-kill Keynote while it holds the user's deck.

---

## CG resizer

The resizer converts the 7680×1080 wall deck to a 1920×1080 CG deck by copying
the wall deck and transforming its existing objects in place.

A base CG asset template teaches the target geometry.

### Base-template rules

Every template object must be at its **final CG size and position**.

Include:

* one `<wall layout name> (16:9)` slide for each framing actually used;
* map artwork at its final CG size;
* one real text swatch per character style;
* the resized title plate;
* for photo-card grids, the card group **plus two adjacent copies** (one to the right, one
  below, at the intended spacing). One card carries size but no spacing; the resizer reads
  the grid pitch from adjacent template copies and only falls back to the wall's pitch
  (floored at stroke + 7pt clear) when the template has a single card.

Do not include a contradictory full-canvas 1:1 reference slide.

More correct anchors are useful: affine confidence comes from agreement between
paired objects. Do not trim overlays/pins merely to reduce anchor count.

### Framing

Different wall framings need separate template slides. The resizer cannot infer
an editorial crop it has never seen.

When no suitable framing exists, fall back to fitting visible content and report
the slide rather than silently losing it.

Framing is an editorial decision, not a metric problem. Do not keep adding
heuristics to infer a choice an operator can see immediately. Reuse the existing
Sermon Checker pairing/confirmation pattern where human confirmation is needed.

### Side panels and church-name rosters

`--keep-side-panels` is positional and per-slide: content outside the centre wall
band (`x ∈ [1920,5760]` on a 7680-wide wall) is dropped unless that slide is
whitelisted; content inside the band is a separate question. The owner's roster rule
(2026-09-05): a church-name roster is kept only on the church-list slide(s) — the
slide it first appears on, plus an immediately following slide that is purely that
roster's own re-layout — and there it is packed into the visible frame, not left at
its wall extent. Every later slide that still carries the roster as a wall leftover
hides it entirely, side band or centre band alike. Reuse must honour this on both the
donor and the target: a persisted item invisible on one side and visible on the other
needs an explicit add/remove job, not silent inheritance from whichever side reuse
happened to copy.

### Loose text

Classify wall text by what lies beneath it:

* text over artwork is a label and moves with that artwork;
* text on bare background is free and is packed into the remaining CG space.

Use rendered source previews when available because wall artwork can cover most
of the rectangular bounds while visually occupying much less of the frame.

**Never drop text.** If packing cannot find a clean position, place it at the
least-overlapping position and report the overlap for operator cleanup.

### Text styling during resize

**The template dictates size; the source dictates style.** `Base_CG_Assets.key`
exists to give matched objects their intended size (and position, where
appropriate) — that is the whole point of the affine recipes — and this includes
**text point sizes**: a caption matched to a template swatch takes the template's
size (9pt if that is what the template shows; never treat it as "hand-tuned").
Only size and position may change. Colour, font family/style, run formatting, and
each slide's builds/animations are always copied from the source, never from the
template.

For mixed-run text, do not set the font on the whole box: Keynote flattens the
box to one face and destroys run-level emphasis. See
`lw-text-keeps-source-font-colour`.

A photo-card caption takes the template swatch size, stepped down whole points while the
measured line exceeds the caption box minus twice its own `padding` (read from the shape
style; not `iwa_text_shape.TEXT_INSET`, which is the LW verse-box constant). The size
travels with the card's pass-2 job (`captionPt` → `leafPt`), never through the deck-wide
exact-text `size_map`: the same caption strings occur as roster-list leaves elsewhere.

Do not rewrite verse-box text to force reflow. Keynote cannot faithfully rebuild
all run styling, and rewriting can lose superscripts, small-caps, and authored
line breaks.

A Keynote 15.3.1 group resize is an aspect-locked uniform scale about the
group's LIVE frame and permanently freezes an autosize text child at its
wrapped height. Groups holding an autosize text box are therefore written
child-by-child (width only for the autosize child), never resized as a group.

### Offline-write A/B gate

`scripts/write_gate_ab.py` is the older one-slide, id-stable Map probe.
`scripts/offline_write_ab.py` is the active whole-deck W1 gate. For the Full
report, `Full_Report_Card_Wall.key` is `--source`, `Base_CG_Assets.key` is
`--template`, and `Full_Report_Card_CG.key` is a reference output, not the
template.

Run the Full gate on copies with `--mode verify --no-validate`; use
`--pass2-bar parity` only to expose and compare a known pre-existing pass-2
problem. Require Accessibility, refuse any already-open Keynote document, run
serially, and quit Keynote between A and B. This workflow is viable on the
16GB host when guarded this way; the memory caution is not a blanket ban on
full-deck work. Run it from an unlocked working copy of the deck — `ditto`
preserves Finder's `uchg` flag, and a locked copy breaks the gate's writes.
After any planner/driver change, also run `scripts/golden_plan.py` — a
Keynote-free apply-plan SHA-256 gate through the real `remap_keynote.remap_keynote`.

The 2026-09-07 Full bank under
`output/handover-2026-09-07/write-gate-full/` completed RED but is reusable:
both A/B decks and run records are present, so diagnose and re-run comparisons
Keynote-free before paying for another live gate. The surgical writer's own
consistency and live geometry verify passed at 0.00px, but pass-2 parity and 12
slides' identity geometry failed. Offline write therefore remains opt-in with
the default OFF.

A 2026-09-07 gate-integrity follow-up added a gating `group` bar (composed
child-union vs the planned rect, 2.5px) to the offline verify — it is expected
FAIL against today's writer (the known `sx = spec/reported` defect), not a new
regression, plus slide 36 `ki2..ki5` (≈139px), the separate never-written-spec
bug, which will keep this line RED after the writer fix — and a pre-comparison card-border
damage check (output card-border media-style ref count vs the source deck): re-gating the
2026-09-07 bank now ABORTs with "run A is DAMAGED" rather than running the geometry compare,
which is correct — that bank's arm A really did lose 44 report cards. The check reports the
shortfall as an observation only: D1's "stolen GUI interaction" cause was disproven by D6 and
the real defect was fixed in `f76e8d3`, so the RED line names that mechanism as a hypothesis
and points at the run log, not at a re-run. The untouched-machine operator rule still applies
to genuinely focus-dependent signatures (`front` z-order raises, pass-2 badge raises); it does
not explain this one.

---

## Scoring and validation

Use:

```bash
python scripts/score_resize.py ...
```

`goldRmse` measures placement error against the finished CG deck's own
transform; zero means the same layout was selected.

Do **not** interpret `goldRmse` for:

* `list` rows, which are intentionally reflowed;
* `title` rows, which use an explicit title override.

Judge lists by successful placement and overlap instead.

`templateScore` is a self-consistency check, not a quality score. A non-zero
value means the planner failed to reproduce the affine it derived.

Avoid these metric traps:

* proximity matching of repeated pins;
* rewarding frames merely for keeping content inside the canvas;
* measuring all visible content when only paired artwork determines the affine;
* ranking primarily by raw pair count.

When two candidate framings remain editorially ambiguous, ask rather than invent
another heuristic.

---

## Offline inspect / IWA

`.key` files contain `Index/*.iwa` archives. The optional IWA reader can recover
per-run character styling and grouped text without opening Keynote.

`src/obed_edom/iwa_runs.py` attaches:

```text
text, color, bold, italic, size, fontName,
superscript, capitalization, styleName
```

and may expose grouped text for checker text scoring.

Important boundaries:

* IWA run data is for inspection/verification; it does not make Keynote
  character styling writable.
* Keep grouped IWA text out of the resize fingerprint unless the relevant
  pipeline explicitly needs it.
* `kindIndex` is reconstructible offline.
* Geometry is only partly reconstructible offline.

For remap, use the **two-tier geometry read**:

1. derive addressing/styles/most geometry offline;
2. use a bulk Keynote geometry read where autosize text or ambiguous group
   geometry requires live layout.

PPTX export is a useful complementary geometry source, especially for autosize
text width, but lines and groups still need their specialised offline handling.

Round geometry to whole points where matching Keynote values; sub-pixel noise can
change affine fitting.

For AUTOSIZE text, Keynote's AppleScript/JXA `position` (read AND write) is always the
object's VISUAL TOP-LEFT — for every anchor, verified live 2026-09-06 (see
`output/handover-2026-09-06/anchor-diagnosis/diagnosis.md`). What varies is the IWA
STORED y: it is the visual top for a `kFrameAlignTop` autosize text box, the visual
CENTRE for a `kFrameAlignMiddle` one, and the visual BOTTOM for a `kFrameAlignBottom`
one. The anchor lives at `shapeProperties.verticalAlignment` on the box's own style
(`shape.super.style` → `TSWP.ShapeStyleArchive`) and is resolved up the style parent
chain (`super.super.parent`) exactly like `shape_padding` — archive-correct, though it
changes no composed value on this deck: 163 of the Gold wall deck's 179 autosize boxes
inherit the anchor from the parent style rather than setting it (all 163 resolve
Middle, the default arm), and the remaining 11 top-aligned boxes set verticalAlignment
on their own style. Enum codes: Top=0, Middle=1,
Bottom=2, Justify=3, emitted by keynote-parser as the NAME. `_autosize_rect`
(`iwa_geometry.py`) branches on it since 2026-09-06, so composed rects are the visual
truth for EVERY anchor, offline-only reads (no bulk splice) included; justify, unknown
and absent values keep the middle default. Practical rules: never add `±h/2` anchor
compensation on a write path — the planner's y and Keynote's `position` are already the
same visual top, so writing the planner's y straight through is correct (a compensation
once shipped on this basis was a pure write bug, reverted 2026-09-06); and never "fix" a
composed-vs-live disagreement at write time — by construction that is a read-model bug.
Text-content identity remains the robust way to address text items across a reuse copy.

### Offline writes

A whole-deck IWA decode/re-encode is unsafe.

A **surgical single-member patch** has been proven openable on a test deck, but
real large wall-deck validation is still environment-limited. Keep such writes
behind their explicit feature gate and read-back verification.

Load-bearing rules:

* locate the target IWA from `id_to_file[drawable_id]`, never by guessed slide
  filename;
* patch only the owning member;
* preserve every other ZIP member verbatim;
* preserve the existing file/inode metadata needed by Keynote's sandbox;
* for shape/line size, update both stored geometry size and
  `naturalSize`;
* line length comes from `naturalSize.width`;
* autosize text translation is safe only when its live geometry is known;
* masked-image and group write semantics require a live bulk geometry seed.
* image strokes (`TSD.MediaStyleArchive.mediaProperties.stroke.width`) live in the
  global `Index/DocumentStylesheet.iwa`, never in slide members; a single-member
  float patch there survives a Keynote open and save (probed 2026-09-02). Select
  styles by colour/pattern/ref-count, never by id;
* `drawablesZOrder` + `ownedDrawables` (kept identical) can be permuted offline;
  Keynote honours the order on open, keeps it on save, and the AppleScript
  per-kind collection order follows it (probed 2026-09-02). A reorder changes
  every kindIndex on the slide, so it must be the last patch on that slide.
* a stored `geometry.size` width or height of `0.0` on a text box is the AUTOSIZE
  sentinel: Keynote re-derives that dimension on open. Never write it — a written
  value freezes the box into a fixed frame (the whole-deck gate caught a 43pt-high
  frame on 2026-09-04). Move autosize text; leave a zero dimension zero.
* a text box with a stored width or height of `0.0` (autosize) is never patched offline:
  `naturalSize` is Keynote's render cache and only a live write refreshes it, so an
  offline byte-patch leaves it stale and Keynote re-shrink-wraps the box on open. Such
  boxes hard-miss to the AppleScript fallback, which writes them correctly.
* `KN.SlideArchive.builds` and `.buildChunks` are the **only** references to a build
  anywhere in a slide member. Shrinking/reordering those two lists and writing
  `.transition` on the same `SlideArchive` survives a Keynote 15.3.1 open + re-save with
  geometry and every other slide byte-identical (probed live 2026-09-05); orphaned
  `Build`/`BuildChunk` archives may be left behind unreferenced and are harmless. The
  patcher self-checks by archive id and header before writing and refuses rather than
  guess. `buildChunks` is the render timeline and `builds` an unordered owning set
  Keynote permutes on save, so never read `builds` order as reveal order (measured:
  chain-coherent 45/45 under `buildChunks` vs 13/45 under `builds` — D8).

---

## LW deck facts

* Wall verses may be duplicated across centre panels; collapse identical
  duplicates during extraction.
* In bilingual services, two same-size side-by-side text boxes may be a genuine
  translation pair. Collapse only when the text is actually identical.
* Finalised LW masters do not reliably identify semantic slide type. Infer slide
  roles from the actual object/font/size patterns and the configured
  `masters.yaml` rules.

---

## Operator handoff

Generate produces `_CUED.docx` with:

* cyan `[LW…]` show-call tags for LED wall;
* yellow `[DSK…]` tags for lower thirds;
* one cue per generated verse slide, at the start of that chunk;
* PRE tags on the point line;
* no extra POST cue on the following verse.

After generate:

1. Read `review.pdf`; the **Please check** section is the operator checklist.
2. Open LW and DSK separately; they run on different PCs.
3. Verify every later verse number is a raised cyan superscript.
4. Give the operator `<stem>_CUED.docx`.
5. Treat the Bible Gateway result as an audit; outline wording remains the slide
   wording.
6. Bright LW photos are flagged, not auto-darkened.
7. **Do not auto-recolour text.**
8. If mapping is wrong, identify the cue and expected master/layout before
   rerunning.

---

## Related skills

* `peer-reviewed-workflow` — required for non-trivial implementation changes.
* `allow-commits-no-prs` — commits are allowed at verified checkpoints; never
  open a PR unless explicitly asked.
* `lw-text-keeps-source-font-colour` — source styling invariant for wall→CG text.
* `template-size-source-style` — template gives size (incl. text pt), source gives
  colour/font/runs/builds.
