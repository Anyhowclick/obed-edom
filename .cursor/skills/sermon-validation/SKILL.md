---
name: sermon-validation
description: >-
  House-style checks for sermon LW/DSK Keynotes and outlines: verse vs Bible
  Gateway, contrast, Trinity caps, book names, highlighted punctuation, en-dash
  dates, quote attributions, center-wall 3840x1080 bounds, and text overflow.
  Also the stable validation rule ids (text.*, photo.*, bible.*, style.*,
  bounds.*) and their severities. Diffs never rewrite .key files. Use when
  validating slides, running the dashboard ValidationPanel, tuning validation
  noise, or reviewing Keynote copy.
---

# Sermon validation

Never change Keynote files to “fix” a finding. Flag only. That extends to the
outline: a stale script is reported, never rewritten.

## Source of truth

Once staff have run the deck with the Pastor, **LW is the service**, so the
ranking is **LW → outline → DSK** and a script that disagrees with the wall is
out of date rather than right. Before sign-off the script still leads:
**outline → LW → DSK**. The Sermon Checker asks which it is (defaulting to
finalised) and passes `lw_final` through to `outline_check.corroborate`.

DSK is last in both orderings, so `outline.dsk_deviates` means the same thing
either way. Only the two verdicts that would otherwise accuse the wall change:
with a finalised wall they become `outline.dsk_stale` and `outline.stale`.

An outline carries one cue per slide advance, so cue counts can be compared
with the decks without reading a word — that check survives decks exported as
JPEGs or `.mov`s. Wording checks cannot, so on those they drop to `info`.

## Checks

a. The current checkers in place (ie. verse ref & colour contrast checkers)

b. Anything w.r.t Trinity must be caps (God, Father, Son) & associated words (My - if it's God speaking)

c. Psalm, not Psalms; Revelations not Revelation

d. General rule of thumb is to FOLLOW BIBLE GATEWAY text

e. Don’t highlight punctuation (should be default text size & colour)

f. Date period format, note the en dash, not single or em dash (Eg: 3–4 Jun, 1980–2012)

g. Quotes: If person is alive, should contain just the name; otherwise the D.O.B-D.O.D. Also verify the name online, flag if incorrectly spelt

h. Ideally, content should not exceed 3840 x 1080 (center wall)

i. Text overflow: if copy cannot fit the mapped Keynote box (character
   limit or estimated height vs box), raise a warning. Do not rewrite the
   deck. `[VERSE-CONTINUED]` that exceeds the lower-third is flagged, not split.

## Duplicated wall text is not a mistake

The wall is long, so a verse is set twice across the centre panels for
readability. Two same-size text boxes side by side are therefore normal, and
any check counting words or verses must collapse them or it double-counts.

Do not collapse them blindly, though. On bilingual services one side is English
and the other Chinese. Identical text is a readability mirror and should
collapse; text that differs is likely a translation pair and should be reported
rather than silently halved. Detect the difference by script (CJK vs Latin),
not by assuming the left or right copy wins.

## Style checks that cannot fire from deck data

`style.highlight` reads colour runs, and Keynote does not expose them —
`objectText.attributeRuns()` raises "Can't convert types." on every deck tried,
so highlighted-punctuation findings never fire from inspect data. Small caps hit
the same wall and were reimplemented on rendered previews (ink-height profiling
in `bible.py`); highlight needs the same treatment. Until then, treat a clean
`style.highlight` result as "not checked", not as "passed". See the obed-edom
skill for the full list of verified Keynote scripting limits.

## Rule ids

Every `Flag` carries a stable `rule` id, plus `slide`, `deck` and an optional
`evidence` PNG. Group and filter on `rule`; never parse the message prose.

| Rule | Fires when |
| --- | --- |
| `text.case` | Same words, different capitalisation ("(Plural)" vs "(plural)") |
| `text.symbol` | `&` vs "and", straight vs curly quotes, hyphen vs en dash |
| `text.reference` | Book, chapter or translation label differs ("Samuel 10", "(MSG)") |
| `text.word` | One or two words added or dropped ("Your Faith") |
| `text.major` | Anything larger; the only blunt copy warning left |
| `text.order` | Reference label sits above the body on one deck, below on the other |
| `text.verse_split` | The wall carries verses the paired DSK slide does not |
| `text.unreadable` | Neither extraction nor OCR found text on one side |
| `text.point_carry` | LW still shows the PRE point title on a verse slide; the paired DSK verse does not |
| `photo.source` | Paired photos come from different `fileName`s (dated or reshot image) |
| `photo.rotated` | `rotation` differs between the decks |
| `photo.flipped` | Mirror image, detected by flip hash |
| `photo.count` / `photo.differs` | Photo counts differ; pixel fallback when copy already matched |
| `photo.region` | Localised edit inside a pasted screenshot (blur patch, redrawn area) |
| `photo.marker` | Highlight box or circle added, moved or recoloured |
| `photo.framing` | Same picture, framed or cropped differently |
| `diff.count` / `diff.missing` / `diff.unmatched` / `diff.skip_mismatch` | Pairing |
| `bounds.straddles` | Object crosses a wall boundary, so it is visibly cut. Carries evidence |
| `bounds.offcanvas` | Object sits outside the canvas |
| `cue.lw_count` / `cue.dsk_count` | The outline's cue count for a deck disagrees with its slide count |
| `cue.uncued_slide` | A deck slide no cue accounts for |
| `cue.no_slide` | A cue with no slide left on that deck |
| `cue.hold` | A lone `[DSK…]` row: the wall holds while the lower third splits |
| `cue.unknown` | A bracketed token that is neither a cue nor a stage direction |
| `cue.deprecated_alias` | `[VERSE-FROM-PREVIOUS]`; write `[VERSE-CONTINUED]` |
| `outline.dsk_deviates` | DSK disagrees with both the outline and LW |
| `outline.dsk_stale` | Finalised wall only: LW moved past the outline and DSK, so the change never reached the lower third |
| `outline.stale` | Finalised wall only: the decks agree and the show-call script is behind them |
| `outline.lw_deviates` | Unfinalised wall only: LW departs from the script while DSK follows it |
| `outline.both_deviate` | Unfinalised wall only: both decks agree against the script |
| `outline.three_way` | Outline, LW and DSK all read differently |
| `bible.wrong_reference` | Wording matches a neighbouring chapter or book, not the cited one |
| `bible.mismatch` | Wording disagrees with Bible Gateway for the cited reference |
| `bible.unchecked` | Reference could not be fetched |
| `style.smallcaps` | Passage sets `LORD`, the slide renders "Lord" (measured on pixels) |
| `style.glossary` | Near-miss of a house proper noun ("First Loved Conference") |
| `style.trinity`, `style.book_name`, `style.date`, `style.quote`, `style.highlight` | Checks b, c, e, f, g above |
| `overflow.text` | Check i above |
| `ocr.unavailable` | macOS Vision could not run, so baked-in text went unchecked |

## Runtime

Python loads `src/obed_edom/validation_rules.yaml`, whose `rules:` map sets each
id to `off | info | warning | error` so noise can be retuned without code, and
whose `glossary:` list holds the house proper nouns. Text rules compare
`rendered_text` — extracted item text plus macOS Vision OCR of the preview — so
copy inside groups and images is checked too; on LW only the 3840x1080 center
wall is read.

The dashboard renders findings per slide through `SlideFindings`; info-level
findings are hidden behind the "Show info" toggle, and `evidence` images load
from `/api/jobs/{id}/evidence/{name}`.
