---
name: Maps Toner low-zoom boundaries
overview: Toner / toner-lines / toner-background must show country AND province (admin_level 4) borders when a whole country fits the frame at authored z2-3. Today boundary_state is gated at minzoom 3 and boundary_country_z0-4 at minzoom 2, so both vanish and toner-lines renders pure white. Fix by overriding three boundary layers at load time in code. The vendored JSON is never edited.
todos:
  - id: overrides-module
    content: New dashboard/src/maps/tonerBoundaries.ts exporting withLowZoomBoundaries(layers) — pure, no fetch
    status: pending
  - id: wire-resolver
    content: Call it in resolveTonerStyle before the variant filter, after remapTonerFonts
    status: pending
  - id: tests
    content: Extend the toner test in dashboard/tests/camera-flight.test.cjs — minzooms, ids, untouched z5- layer, base-2 widths, per-variant presence
    status: pending
  - id: provenance
    content: One line in maptiler-toner-PROVENANCE.md recording the load-time boundary override
    status: pending
  - id: manual-qa
    content: Orchestrator checks a z2.5 country slide in preview and in a 7680 still export
    status: pending
isProject: false
---

# Maps Toner low-zoom boundaries

## Locks

- Do **not** edit `dashboard/src/maps/vendor/maptiler-toner-8688fbd.json` or `maptiler-toner-LICENSE.md`. All changes are load-time overrides.
- Do not touch `boundary_country_z5-`. Nothing above map zoom 5 changes.
- Layer ids stay `boundary_*` so `filterForLayer` ([layers.ts:35](dashboard/src/maps/layers.ts)) keeps mapping them to the **boundaries** toggle.
- Node for dashboard commands: `PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`. Tests `npm run test:maps`, build `npm run build`.
- Option 2 below is **parked**. Do not implement it.

## Why borders vanish

`previewZoomDelta` ([MapView.tsx:47](dashboard/src/maps/MapView.tsx)) = `log2(previewWidth / 7680)`; `mapZoomOf` (~:95) = authored + delta. A ~1000 px preview runs MapLibre **2.94 levels below** the authored zoom (1920 px → 2.0). Export ([captureExport.ts:155-170](dashboard/src/maps/captureExport.ts)) renders a 7680-wide canvas at `pixelRatio 1` with `camera.zoom = authored`. So at authored 2.5 the preview map sits at z-0.44 and the export at z2.5, while the vendored gates are `boundary_state` minzoom 3 and `boundary_country_z0-4` minzoom 2. Both are dark in the preview; provinces are dark in the export too.

Tile data floor (decoded OpenFreeMap planet 20260830): `admin_level` 2 exists from z0, `admin_level` 4 from **z1** (none at z0). MapLibre picks tiles with `floor(mapZoom)` clamped at 0, so provinces cannot draw below map zoom 1 no matter what the style says. See "Known limits".

## Design

Three edits, all in code:

| layer | zoom band | change |
| --- | --- | --- |
| `boundary_country_z0-4` | `[0, 5)` | `minzoom: 0` only. Paint untouched — the vendored `{base:1.1, stops:[[2,1],[22,20]]}` `line-width` clamps to 1 px below z2, which is fine. Filter, colour, maxzoom 5 unchanged. |
| `boundary_state_z1-4` | `[1, 5)` | **new** layer, inserted immediately before `boundary_state` (index 21, under the country lines), constant weight. |
| `boundary_state` | `[5, 14)` | `minzoom: 3 → 5` only. Paint/layout/filter byte-identical. |

Splitting the province layer by zoom band mirrors what the vendored style already does for countries (`boundary_country_z0-4` / `boundary_country_z5-`): a single layer cannot carry `minzoom: 1` below z5 and keep the vendored `{base:1.3, stops:[[5,1],[6,1.2],[7,1.6],[14,5]]}` curve above it.

**Continuity, not re-weighting.** The low layers must hand off cleanly to the vendored layers that resume at z5, so neither introduces its own zoom curve. `boundary_country_z0-4` keeps its vendored paint verbatim. `boundary_state_z1-4` gets a constant `line-width: 1.2` (no interpolation): the vendored `boundary_state` resumes at z5 with a 1 px grey `[1,1]` dash and steps to 1.2 px black `[1,2]` at z6, so a constant 1.2 px province from z1 hands off in character with that existing step, instead of the 32 px → 1 px cliff a custom growth curve produced.

**Colour and dash for `boundary_state_z1-4`.** Use `rgba(0, 0, 0, 1)` — the same black as the country line, since neither layer grows a colour hierarchy in this flat-weight band. Dash `[2, 2]`. Omit `line-cap` — the vendored `"round"` adds half a width at each dash end, which at `[2,2]` nearly closes the gaps; the `butt` default keeps the dash legible. Keep `"line-join": "round"`.

**`maritime` filter: not added.** At z1-4 every `admin_level` 4 feature carries `maritime: 0`; `maritime: 1` admin4 lines only appear at z5+, which is outside the new layer's band and inside the untouched vendored one. An `["!=", "maritime", 1]` clause would therefore change nothing and would needlessly diverge from the vendored filter. Revisit only if the low band is ever extended past z5.

## Code

New file `dashboard/src/maps/tonerBoundaries.ts` (separate module, mirroring `watercolourStyle.ts`, so the test can compile it standalone without the `?url` import stub):

```ts
export function withLowZoomBoundaries(layers: LayerSpecification[]): LayerSpecification[]
```

Pure: returns a new array; passes every other layer through by reference and in order; patches the two ids above and splices the new layer in before `boundary_state`. If an id is missing (re-vendoring), pass through unchanged rather than throwing — the test pins the ids.

Wire it in `resolveTonerStyle` ([styles.ts:72](dashboard/src/maps/styles.ts)), **before** the variant filter so all three variants benefit:

```ts
next.layers = withLowZoomBoundaries(remapTonerFonts(next.layers) as LayerSpecification[]).filter(…)
```

`styles.ts` is 182 lines and already carries the resolver plus `withHillshade`; the new module keeps it from growing a fourth concern. Minimal comments: one line on the base-2 rationale, nothing else.

## Tests

Two tests in [dashboard/tests/camera-flight.test.cjs](dashboard/tests/camera-flight.test.cjs) cover this.

`"pinned Toner variants …"` (extends the existing test, which already stubs `fetch` and the `?url` asset): vendored JSON stays at 37 layers; the resolved styles come out at 39 (`toner`), 13 (`toner-background`), 15 (`toner-lines`). All four boundary ids — `boundary_state`, `boundary_state_z1-4`, `boundary_country_z0-4`, `boundary_country_z5-` — are present in `toner-lines` and absent from `toner-background`.

`"withLowZoomBoundaries …"` (new, runs directly against the vendored layers, no fetch stub needed):

- `boundary_state_z1-4`: `minzoom 1`, `maxzoom 5`, constant `paint["line-width"] === 1.2` (no interpolation), filter deep-equal to vendored `boundary_state`'s filter.
- `boundary_country_z0-4`: `minzoom 0`; every other field — including paint — deep-equal to the vendored layer.
- `boundary_state`: `minzoom 5`; every other field deep-equal to the vendored layer.
- `boundary_country_z5-`: untouched, deep-equal to the vendored layer.
- Output has exactly one more layer than the vendored array; stripping `boundary_state_z1-4` out reproduces the vendored id order exactly, and the new layer sits immediately before `boundary_state`.

`npm run test:maps` then `npm run build` (runs `tsc`).

## Provenance

`maptiler-toner-PROVENANCE.md` already documents the load-time adaptations (OpenFreeMap endpoints, procedural fill patterns, no sprite). Add one sentence to that paragraph: the three boundary layers are re-gated and re-weighted at load time for low-zoom wall exports. The existing test asserts the commit hash and the raw URL are still present, so keep those lines intact.

## Manual QA (orchestrator)

1. Open a Maps deck, pick **Toner lines**, frame a country at authored 2.5 → the preview now shows black country outlines where it was pure white. Provinces will **not** appear in a ~1000 px preview at this zoom (see limits).
2. Same slide, authored 4 in a wide preview → provinces appear as grey dashes.
3. Export a still and inspect the 7680 PNG at authored 2.5: country ≈ 8.5 px, provinces ≈ 5.7 px dashed. This is the deliverable and the real acceptance check.
4. Repeat once on **Toner** and **Toner background** (background must be visually unchanged — it has no line layers).
5. The Claude Browser pane freezes MapLibre's rAF while hidden; drive `map.resize()` / redraw via `javascript_tool` if the pane is not visible.

## Known limits

- **Provinces cannot render below map zoom 1** — z0 tiles carry no `admin_level` 4 geometry. So a ~1000 px preview shows them only from authored ≈ 3.94 (1920 px: authored 3.0), while the export shows them from authored 1. At authored 2-3 the preview stays honest about countries and silent about provinces. Only parked option 2 can close this.
- Exports at authored z2-3 draw 1-1.2 px borders on the 7680 px wall (hairlines), because the vendored weights are screen-scale, not export-scale. Correcting export weight for every style, not just the two low-zoom Toner layers, is the parked option 2b below.
- Preview geometry is coarser than the export at the same authored zoom (lower tile zoom), so small islands and border detail differ. Unchanged by this work.
- Only the three Toner variants are touched. Positron / Liberty / Bright / Dark / Fiord keep their own low-zoom gates.
- Widths and the `rgba(60,60,60,1)` / `[2,2]` dash are tuned by eye against the numbers above; they are two lines in `tonerBoundaries.ts` to retune.
- Re-vendoring the Toner style must re-check the three layer ids and the z5 handover.

## Parked — option 2: make the preview honest for every style

Not in scope. Recorded so it can be picked up.

- **2a. Shift zoom gates by −previewZoomDelta** in a preview-only style transform: every layer `minzoom`/`maxzoom` and every zoom-driven value (legacy `{base, stops}`, `["interpolate"|"step", …, ["zoom"], …]`, nested inside `match`/`case`) offset by the delta. Risks: rewriting arbitrary expressions correctly (zoom expressions must stay top-level); symbol collision and label density change with zoom, so labels would re-flow between preview and export; object/pin preview scaling (`objectPreviewScale`) would need matching treatment; and it still cannot conjure province geometry, because the tiles requested are chosen by the real map zoom.
- **2b. Render the export the way the preview renders.** Give `captureExport` a ~1000 CSS-px container at `pixelRatio 7.68` (canvas still 7680) with `camera.zoom = authored + previewZoomDelta`, i.e. the preview camera. Preview and export then become pixel-identical up to scale for *every* style, and low-zoom line weight stops being 7.68× too thin across the board — which is the root cause this plan works around. Risks: glyph SDF and pattern quality at 7.68×, GPU memory and `maxCanvasSize`/texture cap interaction, raster tile resolution, and the fly-frame capture path shares this code.
