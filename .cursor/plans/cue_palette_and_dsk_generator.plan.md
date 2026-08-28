---
name: Cue palette and DSK generator
overview: "Split out of cue_palette_and_outline_editor_ef103304.plan.md (2026-08-28) so that plan can focus on the CG resizer + its speed work. This holds the two dashboard/authoring features that are independent of the resizer: the cue-first palette (show the operator the layouts a template actually has and let them insert the cue that produces one) and the DSK generator (unchanged from the superseded plan, including its four corrections). Neither is started. The outline editor, image cues, stat-drift, and recipe-library stay in the resizer plan for now."
todos:
  - id: cue-palette
    content: "Cue-first palette in the dashboard, inverting masters.yaml cue maps, with adjacency and context rules enforced. Pending — design below."
    status: pending
  - id: dsk-generator
    content: "DSK generator, unchanged from the superseded plan including its four corrections. Pending — detail lives in the superseded plan; carry it forward when this is picked up."
    status: pending
---

## Decision: live preview is dropped, cue discovery replaces it

A preview is only worth building if it answers faster than editing the document
does. A Keynote round trip cannot, and a browser overlay would still be an
approximation. Editing the outline and typing a cue is faster, so the preview is cut.

The real problem was never "does this copy fit" — it is that the cue vocabulary is
invisible. Nine semantic cues today, with adjacency rules and context variants, and
it grows. So the work becomes: **show the operator the layouts the template actually
has, and let them insert the cue that produces one.**

## The palette: layout and cue are many-to-many

Mirroring Keynote's "Choose a Layout" panel one-for-one would be wrong.
From `src/obed_edom/masters.yaml`:

- `BLANK` backs `[FILLER-QR]`, `[GIVING-OPTIONS]`, and offering-context `[FILLER]`.
- `VERSES` backs both `[VERSE]` and `[VERSE-CONTINUED]`.
- The four POST layouts have no cue of their own — they come from
  `[VERSE-AFTER-POINT]`, valid only directly after `[POINT]`/`[NUM-POINT]`, which
  also drives the 1s Magic Move.
- `TITLE` backs `[TITLE]` and sermon-context `[FILLER]`.
- DSK adds selection by length, not cue: `Verse 1 Line (Variation 2)` vs
  `Verse Standard (Variation 2)` is decided by `verse_char_one_line`.

So the palette is **cue-first**, each entry carrying the layout thumbnail(s) that cue
can produce, the context that picks between them, and its adjacency rule. That
inverts the existing `lw.cues` / `dsk.cues` maps rather than adding a second source
of truth.

## Layout thumbnails: derive per template, cache by digest

`Default Templates/` is empty and gitignored, so templates are always dropped and
thumbnails cannot be pre-baked. Keynote's `export` works on documents, not layouts:

1. Copy the dropped template to a scratch path (never touch the original).
2. Enumerate layouts — `remap_keynote.js` has the pattern (`doc.slideLayouts()`,
   `layoutNames()`, ~lines 543-567).
3. Append one empty slide per layout with `{base slide: theMaster}`, as
   `keynote.py` ~line 792 does.
4. Export slide images, keep one PNG per layout name, discard the scratch deck.
5. Cache under `<cache root>/layouts/{template_digest}/`, reusing `deck_digest()` and
   the `INSPECT_VERSION` discipline in `baseline.py`. Cache root is `.cache/` at the
   repo root now, not under `output/`.

New endpoint `GET /api/template-layouts` taking a template path, returning layout
names, thumbnail URLs, and the cues each layout is reachable from. Layouts no cue
reaches are returned as unmapped — that list is the honest answer to "what can the
template do that the tool cannot ask for". Both capabilities were probed on 15.3.1
and are present (`doc.slideLayouts()` works; `doc.masterSlides()` raises in JXA but
AppleScript's `master slide` is fine, which is why `keynote_jxa.js` stays unused).

## DSK generator

Unchanged from the superseded plan, including its four corrections. Detail was not
duplicated here; pull it forward from the superseded plan when this is picked up.
