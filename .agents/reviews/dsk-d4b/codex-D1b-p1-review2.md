REVISE

1. **MEDIUM — badge identification accepts unrelated overlays.** [src/obed_edom/dsk_assemble.py:542](/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom/b0fe5f66-5d53-46a1-ad2a-6074e9f6ea03/scratchpad/wt-d1b/src/obed_edom/dsk_assemble.py:542)

   Any short text sharing a rectangle with any non-circle shape is accepted, including stray text over a textless decorative shape; multiple such “badges” also pass. Once wired, this can falsely select the two-column layout.

   The measured GW 46/52 badge records contain identical text on both the `text` and `shape` records, so use that stronger identity without changing the known deck set.

   Concrete fix: allow at most one extra top-level text and require exactly one non-circle shape with a matching rectangle and identical normalized, non-empty text. Add tests for a stray text on a textless shape and multiple badge-like pairs.

2. **MEDIUM — numeral cardinality and geometric pairing remain permissive.** [src/obed_edom/dsk_assemble.py:529](/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom/b0fe5f66-5d53-46a1-ad2a-6074e9f6ea03/scratchpad/wt-d1b/src/obed_edom/dsk_assemble.py:529)

   Cardinality is checked only after filtering numerals by circle containment. Thus a second digit text elsewhere can survive as a “badge” when it matches another shape. Additionally, the expanded axis-aligned rectangle accepts a numeral centre at a circle corner or 1 pt outside it. Synthetic probes confirmed both cases.

   Concrete fix: first require exactly one all-digit candidate globally, then geometrically pair it. Prefer a radial check against the 81×81 circle’s centre, with at most a 1 pt radius tolerance. The measured GW numeral centres are more than 21 pt inside the horizontal edges, so this tightening preserves slides `{44,46,50,51,52,53}`. Add separated-second-numeral, corner, and just-outside regression tests.

The original long-text cardinality and fractional `fit_heading_pt` findings are closed. The geometry-only circle decision is documented correctly, and `plan_assembly` remains unwired.