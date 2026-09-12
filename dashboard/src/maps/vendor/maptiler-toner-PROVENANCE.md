# MapTiler Toner GL style provenance

`maptiler-toner-8688fbd.json` is the upstream `style.json` from
https://github.com/openmaptiles/maptiler-toner-gl-style at commit
`8688fbd46e1918cae2e9c3d36e607b9d994badfe`:

https://raw.githubusercontent.com/openmaptiles/maptiler-toner-gl-style/8688fbd46e1918cae2e9c3d36e607b9d994badfe/style.json

The accompanying upstream licence is retained as `maptiler-toner-LICENSE.md`.
The style is adapted at runtime to use OpenFreeMap vector and glyph endpoints,
local procedural replacements for the four required fill patterns, and no
external sprite endpoint. Captured and interactive maps retain the required
OpenStreetMap and MapTiler attribution. The three boundary layers are
re-gated and re-weighted at load time for low-zoom wall exports. The solid
`building_fill` layer is dropped at load time so the `building_pattern`
hatch is the only building paint at every zoom.
