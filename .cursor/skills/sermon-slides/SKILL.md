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

## Operator outline (`_CUED.docx`)

Semantic cues are replaced with show-call tags:

- Cyan `[LW…]` → LED wall (Word highlight `cyan`, shown as Turquoise)
- Yellow `[DSK…]` → lower thirds
- One operator cue per generated verse *slide*, at that chunk’s start. If 26–27 fit on slide 1 and 28 starts slide 2: `[LW][DSK-PP] 26 … 27 … [LW][DSK-PP] 28 …`. Independent LW vs DSK splits still share a tag when both decks start at the same verse.
- PRE tags stay on the point line. POST does not add a second `[LW][DSK-PP]` on the verse.

## After generate

1. Open `review.pdf`. The **Please check** section is the to-do list.
2. Open both `.key` files in Keynote. Do not merge LW and DSK — they run on separate PCs.
3. Hand the operator `<stem>_CUED.docx` for the show-call script.
4. Bible: outline wording stays on the slide. Bible Gateway NIV is an audit (MSG when the outline labels it).
5. Contrast: dark overlays may have been added on bright LW photos. **Do not auto-recolor text**; note leftovers for manual edit.
6. If mapping looks wrong, say which cue and expected master, then re-run generate.
