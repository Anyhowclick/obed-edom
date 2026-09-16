Clean. No findings.

`"Blank Black"` is safely handled:

- `_applescript_string_list` preserves spaces; no special escaping is needed.
- The FW exporter resolves aliases offline and checks alpha safety before generating AppleScript.
- Candidate order only prioritizes the first alpha-safe match. If both `"BLACK BLANK"` and `"Blank Black"` exist, an unsafe earlier alias is skipped.
- The generated AppleScript receives only the resolved singleton alias, so deck layout order cannot override the safe offline choice.
- `layout_import_lines` likewise receives only that resolved alias.
- Stage export continues using the separate `DEFAULT_TRANSPARENT_LAYOUT_NAMES = ("Blank Black",)` unchanged.

The added positive and negative tests are adequate for this small alias-only change; existing tests cover unsafe layouts, donor importing, and exact-name matching.