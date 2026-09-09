# Watercolour vector style

`watercolourStyle.ts` is an original, extractable MapLibre style transformer. It takes an OpenMapTiles-compatible base style and returns semantic turquoise water, peach land, sage parks, warm road and label colours. The host may replace every vector source with its own TileJSON URL and set its own glyph URL.

The module also generates its own seeded pencil-scribble fill patterns and a paper-grain tile — all original procedural output with no third-party assets. A host must install the patterns (`installPatterns`/`watercolourPatterns`) and composite the grain (`compositePaperGrain`) itself; the transformer only emits `fill-pattern` references and does not touch the DOM.

The host currently supplies OpenFreeMap network assets. OpenStreetMap attribution remains required. This module contains no copied raster illustration or third-party style JSON; a future public package needs its own licence choice and a complete attribution notice for its chosen base style.
