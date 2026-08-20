---
name: sermon-slides
description: >-
  Generates separate LW (LED wall) and DSK Keynote decks from semantic-cue
  sermon/offering Word outlines, writes operator [LW]/[DSK] cues back into a
  copy of the outline, checks Bible references against Bible Gateway, and flags
  contrast issues. Use when the user mentions sermon slides, DSK, LW, FW, LED
  cues, Keynote templates, Offering JX.docx, Sermon BC.docx, TITLE/FILLER/VERSE
  /POINT/NUM-POINT cues, or running python -m sermon_slides generate.
---

# Sermon slides

## Command

From the repo root:

```bash
python -m sermon_slides generate "/path/to/outline.docx"
```

Local operator dashboard (generate, diff, DSK stub, CG resize stub):

```bash
python -m sermon_slides dashboard
```

Staff-only parse (no Keynote):

```bash
python -m sermon_slides generate "/path/to/outline.docx" --no-keynote
```

Writes `output/<stem>/`:

- `<stem>_LW.key` — from `Default Templates/Sermon_GW.key`
- `<stem>_DSK.key` — from `Default Templates/2026_Lower-Thirds (ENG).key`
- `<stem>_CUED.docx` — the outline with operator `[LW]` / `[DSK-…]` cues for show-call
- `review.pdf` — short checklist for the operator
- `previews/lw/` and `previews/dsk/` PNGs

Never overwrite files in `Default Templates/`. Never overwrite the source outline.

## When to run

- User drops a sermon / offering / testimony `.docx` with semantic layout cues
- Experiment files: `Sermon Outlines/Sermon BC.docx`, `Sermon Outlines/Offering JX.docx`

## Input cues (semantic)

Ignore highlight colour on these for now.

| Cue | Slides |
|---|---|
| `[TITLE]` | LW `TITLE` bumper only. Outline text is not placed on LW. |
| `[FILLER]` (sermon) | Same as TITLE. |
| `[FILLER]` (offering) | LW `BLANK` + DSK `Ways To Give QR Code` |
| `[FILLER-QR]` | LW `BLANK` + DSK QR |
| `[GIVING-OPTIONS]` | LW `BLANK` (paste graphic) + DSK credit-card giving layout |
| `[VERSE]` | LW `VERSES` + DSK verse layout; long passages split |
| `[POINT]` | Non-numbered PRE. If the next cue is `[VERSE]`, also POST (point + verse) with 1s Magic Move on PRE, then the usual standalone verse slides. Skip DSK POST when the point is too long for the lower-third column. |
| `[NUM-POINT]` | Numbered PRE / POST, same pairing rule. Word list numbering supplies the point number. |

`[Pray]`, `[Instructions]`, neighbour-turn lines → stage directions, not slides.

Do not invent extra layouts (images, etc.). Flag unknown cues instead of guessing.

## Later verse numbers need Accessibility

A multi-verse slide (`26 … 27 … 28 …`) needs every verse number raised as a cyan
superscript. Generate does this in two passes, and the second pass drives
Keynote's **Format > Font > Baseline > Superscript** menu through System Events.
That is why macOS asks for Accessibility for whatever launched generate
(Terminal, iTerm, or the dashboard app) in
*System Settings > Privacy & Security > Accessibility*.

**Why the menu is unavoidable.** Keynote's AppleScript dictionary exposes only
`font`, `color` and `size` on a character. Superscript is a separate attribute
that can be *inherited* — writing text through a character that already has it —
but never *created*. The template carries a superscript seed for the first verse
number only, so the first one works headlessly and later ones cannot.

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

Do not "simplify" pass 2 back into pure AppleScript, and do not reintroduce
placeholder Find tokens (`‡‡`): when the GUI step is skipped, tokens leak onto
the slide, whereas real digits just lose the raised styling. `tests/test_parse.py::test_later_verse_superscript_needs_the_format_menu`
locks all of this in.

If Accessibility is denied, generate flags it and the digits stay on the
baseline — the wording is still correct, so the deck is usable.

Other constraints worth keeping:

- Pass 1 exports the PNG previews *before* pass 2 raises the digits, so pass 2
  re-exports. Removing that leaves stale previews in the dashboard.
- GUI scripting must live in its own `tell application "System Events"` block.
  Inside `tell application "Keynote"`, `menu` resolves to a Keynote class and the
  script fails to compile.
- Keynote is driven from a script *file* via `osascript`, not stdin: from the
  dashboard's worker thread the clipboard/HIServices connection dies and
  Keynote's dictionary never loads.

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
6. Contrast: dark overlays may have been added on bright LW photos. **Do not auto-recolor text**; note leftovers for manual edit.
7. If mapping looks wrong, say which cue and expected master, then re-run generate.
