---
name: sermon-validation
description: >-
  House-style checks for sermon LW/DSK Keynotes and outlines: verse vs Bible
  Gateway, contrast, Trinity caps, book names, highlighted punctuation, en-dash
  dates, quote attributions, center-wall 3840x1080 bounds, and text overflow. Diffs never
  rewrite .key files. Use when validating slides, running the dashboard
  ValidationPanel, or reviewing Keynote copy.
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

## Runtime

Python loads `src/obed_edom/validation_rules.yaml`. The dashboard `ValidationPanel` displays `Flag` objects from generate, inspect, and diff jobs.
