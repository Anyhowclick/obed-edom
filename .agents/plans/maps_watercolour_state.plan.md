---
name: Maps + Watercolour branch state
overview: State of branch codex/maps-watercolour-objects at HEAD 0644d97 (PR #63). Replaces maps-watercolour-handover-2026-09-08.md, whose "Remaining work" is mostly shipped. Records what landed on 2026-09-09, the limits those choices bake in, the QA the owner still owes, and the backlog that is genuinely still open.
todos:
  - id: owner-qa
    content: Owner runs the QA list below (Keynote checks especially); nothing here is owner-verified
    status: pending
  - id: review2
    content: Second Codex review of 6c4c62f...HEAD was still running at handover — collect its verdict and triage
    status: pending
  - id: backlog
    content: Pick the next bounded package from "Open backlog" and plan it before touching code
    status: pending
isProject: false
---

# Maps + Watercolour branch state

Branch `codex/maps-watercolour-objects`, HEAD `0644d97`, PR **#63**. Workspace `/Users/anyhowclick/Desktop/work/obed-edom-wt-maps-tab`. Never edit `/Users/anyhowclick/Desktop/work/obed-edom` (unrelated dirty branch).

## Shipped 2026-09-09

### Watercolour Studio
- `0666708` History for past batches, site controls, standard tiles — `WatercolourResultView.tsx`, `sessions.ts`, `api.ts`.
- `e1d19b6` / `b13d18d` Look section as live preview + stacked control cards — `WatercolourTab.tsx`, `styles.css`.
- `a538e2e` mask editor rework, sliders that visibly bite — `WatercolourTab.tsx`.
- `79a4b4e` pen, magnetic pen, wand, magnifier, compare slider — new `dashboard/src/watercolour/{edges,floodFill}.ts` + tests.
- `9c72c3a` icon-only mask tools; `c13961d` tools moved into the header row, cut-out card fixed tile.
- `169f10c` mask-spec validation, staging cleanup on cancel/failure, feather once — `web/watercolour.py`, `tests/test_watercolour.py`.
- `a63c38f` docked magnifier, cut-out card, undo/redo, wider formats — `watercolour/{history,loupe}.ts`.
- `49c57b6` re-edit past batches (`masks.json` sidecar + `GET …/items/{id}/spec`, "Edit again") — `web/watercolour.py`, `WatercolourResultView.tsx`.

### Maps styles / toner
- `26d44e7` low-zoom boundary overrides — new `maps/tonerBoundaries.ts`, wired in `styles.ts`.
- `9601383` provinces gated at authored zoom 4, drawn solid; preview offset via `applyBoundaryZoomOffset` — `MapView.tsx`.
- `3d94d9f` thinner toner road lines for all variants (`maps/tonerLines.ts`), downtown-Singapore default deck (`web/maps.py`).
- `e174ac0` style picker popover with thumbnails — `maps/StylePicker.tsx`, `maps/stylePickerNav.ts`.

### Isolate country + cut-out still + landing slide
- `b8416cc` isolate by darken or erase — `maps/isolate.ts`, `overlays.ts`, `captureExport.ts`, `captureFly.ts`.
- `6c1ccb3` darken-only (erase migrated away), country cut-out second still (`captureIsolatePair`, `_country_still_path`, `build_slide_items`), dissolve default, CG band fix.
- `fb4ff91` synthetic landing slide: `isolate_landing_slides` in `maps_keynote.py`, stills row in `maps_export_plan`, `split_cg_export_plan` `_landingFor`, `post_png` accepts `…__landing` ids.
- `9b53b57` soft pulsing warning for isolate/highlight movie differences — `MorphGates.tsx`.

### Objects: drag / resize / picker / reveal
- `49c57b6` drag-to-move + corner resize handle, magnifier on by default — `MapView.tsx`, new `maps/objects.ts`, `tests/objects.test.cjs`.
- `150d3af` object size cap raised to the 4000 UI range — `web/maps.py`.
- `970d509` landmark picker from watercolour batches (server ACK reconciled) — `MapsTab.tsx`, `api.ts`.
- `0644d97` paint-on brushstroke reveal — new `src/obed_edom/maps_reveal.py` (ProRes 4444 alpha via ffmpeg stdin), `_render_reveals`/`_place_churches` in `maps_keynote.py`, `reveal` field in `web/maps.py` + `types.ts`, UI in `MapsTab.tsx`.

### Slide reorder & transitions
- `970d509` `reorderSlides` / `restitchLinks` in `maps/types.ts`, `moveSlide` + ▲/▼ + Cmd-[ / Cmd-] in `MapsTab.tsx`, `tests/reorder-slides.test.cjs`.
- `a40a410` movie slides dissolve 1 s into the next slide; new hops default to 1 s.

### Save queue / CAS fixes
- `4e076c6` seeded `stateRevision`, hardened save queue, tidied Objects inspector — `saveQueue.ts` + `tests/saveQueue.test.cjs`.
- `6c4c62f` fixes for the first Codex review of PR #63 (queue ACK ordering, isolate paint refresh + thumbnail fingerprint, `flushAndSave` rejection, mask hydration/reset, watercolour path handling and mask size caps, toner country gates, movie mismatch rows, picker ARIA).

### Preview canvas = export band
- `f1aaabf` the MapLibre canvas is now the export band itself (`.maps-map-band`, `previewHostRect`), so pitched preview and export frame identically — `MapView.tsx`, `types.ts`, `styles.css`, `overlays.ts` (`icon-ignore-placement`), `tests/preview-host-rect.test.cjs`.

## Known limits / assumptions

- **Province tile floor.** `admin_level` 4 geometry starts at map z1; nothing renders provinces below it. Preview runs `previewZoomDelta` below authored, so low-zoom previews stay silent about provinces even though the 7680 export shows them.
- **Export hairlines.** Vendored line weights are screen-scale, so authored z2-3 exports draw 1-1.2 px borders on the wall. The real fix is parked **option 2b** in [maps_toner_lowzoom.plan.md](maps_toner_lowzoom.plan.md) (render the export through the preview camera at pixelRatio 7.68).
- **Keynote autoplay is not scriptable.** Reveal movies and drop-pin wave movies are emitted as plain movie items; whether they start automatically depends on Document ▸ Movies / build order. Owner must check.
- **Landmark picker is LW-only** — the server appends to `slide["churches"]` with no audience parameter; the watercolour choice is disabled in CG.
- **Style thumbnails are inconsistent**: Positron and Liberty were captured at z20, the rest at ≈18.5. No 3D/pitch-45 capture exists.
- **Blur isolate not built** — only `mode: "darken"`; `"erase"` is migrated to darken on load, any other mode 400s.
- **Wand / pen are not a live-wire.** Magnetic pen is gradient snap of auto-anchors (Photoshop magnetic lasso approximately); a Dijkstra live-wire was explicitly out of scope.
- **Mid-render cancellation deferred** (first review, finding 8): Watercolour cancellation is only checked between files, so one 24 MP GrabCut/render runs to completion while the job shows `running`.

## Owner QA owed

Nothing below has been owner-verified; the implementer was barred from Keynote.

1. Watercolour: ink slider at its extreme, and the darken look overall — does it read as intended?
2. Keynote: cut-out still stacking, the synthetic landing slide sequence (plain → 1 s dissolve → isolated), and the paint-on reveal (does it autoplay?). Check the `_CG.key` too.
3. Pitched preview vs export: same roads framed, landmark base at the same fraction of frame height; pitch 0 unchanged; FW / centre-only / CG-split alignment; window resize with no drift.
4. Slide reorder: ▲/▼ and Cmd-[ / Cmd-], gates and gutter badges recompute, order survives reload, movies re-render for the new pairs.
5. Objects: drag-to-move without hijacking pan, corner resize past the old 600 cap, slider/number agreement, and Keynote size matching preview.

## Open backlog

- **CAS atomic contract.** Mutations still do not share one atomic contract with job completion, CSV/export, history relocation, and the session status/commit window. Migrate remaining backend Maps writers, session/import and export-metadata paths through it; add rollback for failed atomic file/document publication.
- **Session assets/previews** are installed and backups removed before the document commit, so rollback is unreliable.
- **Conflict freeze is incomplete**: MapView gestures and callback paths stay live while form controls are locked.
- **Real concurrent-race tests**: Studio append vs stale state save, two appends, stale thumbnail writer after append, asset revision handoff, session import vs stale save, delete/edit conflict.
- **Keynote verification**: anchors, aspect ratio, world-copy/clipping, split CG output. Native Keynote opacity stays deferred — keep the derived PNG alpha path until separately approved. Never touch `A_PATCHED.key`.
- **Fly easing arc** and **3D terrain** remain unstarted.
- **Honest preview, options 2 / 2a / 2b** — see the toner plan. 2b also removes the export hairline problem.
- **Watercolour lifecycle leftovers**: mask JSON bounds/duplicate-filename semantics, running-cancellation retained results, Add-to-map ACK reconciliation and network-error/asset rollback, and an active-tab refresh for Maps destinations (Watercolour stays mounted while hidden).
- **Copy/paste target chooser** for multi-slide LW/CG destinations was never finished.

## Pointers

- **PR #63** carries this branch. First review: verdict REQUEST-CHANGES, 11 findings, all addressed in `6c4c62f`; report and the posted comment are in the session scratchpad (`codex-review.md`, `pr-comment.md`). A second review of `6c4c62f...HEAD` was briefed (`codex-review2-brief.md`) but had not produced a verdict at handover — **collect it before merging**.
- Shipped-plan details live in the session scratchpad as `mask-upgrades-plan.md`, `isolate-round2-plan.md`, `round3-plan.md`, `landing-plan.md`, `picker-reorder-plan.md`, `preview-band-plan.md`, `reveal-plan.md`.
- Memory: `maps-p2-film-route`, `browser-pane-maplibre-hidden` (a hidden Browser pane freezes MapLibre's rAF — drive `map.resize()` via `javascript_tool`; never use port 8765).
- Commands (dashboard needs the bundled Node): `PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`, then `npm run test:maps` and `npm run build` from `dashboard`. Python: `.venv/bin/python -m pytest tests/test_maps_api.py tests/test_maps_keynote.py tests/test_maps_reveal.py tests/test_watercolour.py -q`. Restart: `.venv/bin/python -m obed_edom dashboard --no-browser --port 8766`.
