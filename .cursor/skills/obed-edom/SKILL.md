---
name: obed-edom
description: >-
  Generates separate LW (LED wall) and DSK Keynote decks from semantic-cue
  sermon/offering Word outlines, writes operator [LW]/[DSK] cues back into a
  copy of the outline, checks Bible references against Bible Gateway, and flags
  contrast issues. Use when the user mentions sermon slides, DSK, LW, FW, LED
  cues, Keynote templates, Offering JX.docx, Sermon BC.docx, TITLE/FILLER/VERSE
  /POINT/NUM-POINT cues, or running python -m obed_edom generate.
---

# Obed-Edom

## Command

From the repo root:

```bash
python -m obed_edom generate "/path/to/outline.docx"
```

Local operator dashboard (generate, diff, DSK stub, CG resize stub):

```bash
python -m obed_edom dashboard
```

Staff-only parse (no Keynote):

```bash
python -m obed_edom generate "/path/to/outline.docx" --no-keynote
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
| `[VERSE-CONTINUED]` | Rest of the previous verse (oral pause mid-verse). This slide shows the verse so far, with a leading verse number so body copy stays on the baseline. Alias: `[VERSE-FROM-PREVIOUS]`. A `[VERSE]` with no verse number after a verse is treated the same. |
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
