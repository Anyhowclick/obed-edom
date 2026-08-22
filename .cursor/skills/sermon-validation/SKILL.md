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

Never change Keynote files to “fix” a finding. Flag only.

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
