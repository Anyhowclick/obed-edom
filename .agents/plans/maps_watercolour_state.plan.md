---
name: Maps + Watercolour branch state
overview: PR #63 and PR #68 are merged into main. New branch feat/maps-ux-round (PR #70, open, HEAD aac2807) carries the UX round and the reorder-memory/isolate-default follow-up. Records what landed on 2026-09-09, the limits those choices bake in, the QA the owner still owes, and the backlog that is genuinely still open.
todos:
  - id: owner-qa
    content: "Done 2026-09-09: isolate sequence, paint-on reveal, objects, pitched framing, ink slider + darken all PASS; reorder revert bug FOUND and fixed in aac2807. Still owed: reveal-as-slide-movie and Keynote re-render of restored pairs."
  - id: review2
    content: "Done: PR #63 review round 2 (on 0644d97) returned REQUEST-CHANGES with 8 findings; 7 fixed in 290d4f7, finding 2 rejected on purpose (country cut-out stays plain, no orange). PR #63 and #68 both merged into main."
    status: done
  - id: pr70-reviews
    content: "Done: PR #70 Codex reviews — UX round 3a14021 got 2x REQUEST-CHANGES then APPROVE-WITH-NITS; QA round aac2807 got 3x REQUEST-CHANGES then APPROVE. Reports in the session scratchpad codex-review*.md."
    status: done
  - id: poster-frame
    content: "Shipped in 89f9749: offline IWA patch of TSD.MovieArchive.posterTime via src/obed_edom/iwa_movies.py (movie_archives / plan_movie_posters / patch_movie_posters, one-to-one 1px frame match, refuse-not-guess), wired into maps_keynote.py's _apply_poster_frames per deck after _run_one_deck, gated OBED_MAPS_POSTER_FRAME=off|on|verify (default off). Probe script scripts/probe_movie_poster.py (dump/patch/reopen). Owner QA owed: run the probe to learn whether Keynote regenerates the poster from posterTime or keeps cached posterImageData; only then flip the gate on."
    status: probe owed
  - id: backlog
    content: Pick the next bounded package from "Open backlog" and plan it before touching code
    status: pending
isProject: false
---

# Maps + Watercolour branch state

PR **#63** and PR **#68** are merged into `main`. Current branch `feat/maps-ux-round`, PR **#70** (open), HEAD `aac2807`. Workspace `/Users/anyhowclick/Desktop/work/obed-edom-wt-maps-tab`. Never edit `/Users/anyhowclick/Desktop/work/obed-edom` (unrelated dirty branch).

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

### Codex review-2 fixes / reveal / reorder / nav margins
- `290d4f7` review-2 fixes: reveal paths export-only + per-audience fingerprint; ffmpeg output to files; raster upload caps + magic check + atomic write; landing id suffix reserved; mask flush/undo-per-photo/hydration guard; CG frame yields pointer events to objects.
- `a0518b8` drag-and-drop slide reorder — `moveSlideTo` in `maps/types.ts`; arrow buttons removed, Cmd-[ / Cmd-] kept.
- `627cd66` AppleScript movie fallback now places the landmark still — the `shape type` record was failing whole exports.
- `69c8da6` stroke-based paint-on reveal + "Reveal as slide movie" — background movie built from the still plus the reveal (`render_slide_reveal_movie`).
- `0aa585e` Strokes control (default 4, fewer = broader strokes), reveal render ~12× faster (≈3 s per 1600 px landmark), nav margins restored via `compensatedFov` in `maps/types.ts` (full-frame canvas, fov widened so the band projects like the export), style thumbnails recaptured at downtown SG z16.7 bearing 52, deck default reverted to the SEA overview.

### PR #70 (feat/maps-ux-round): UX round + reorder memory
- `3a14021` UX round: "+" dropdown, icon-only objects toolbar, label-off glyph replaces "Hidden", bounding box + four corner handles (`resizeFromCorner` in `maps/objects.ts`), CG frame snap-to-centre (`snapCgShift`), paper grain at 1024px without mottle anchored to the band (`paperGrainCss`), revealed landmarks excluded from hop movies unless the destination is a movie source (`withoutRevealed` / `hasOutgoingMovie` mirrors Python `build_slide_items`).
- `aac2807` `retiredLinks` memory for reorders (`restitchWithMemory`, `MAX_RETIRED_LINKS` 200, persisted through state/`.obedmaps`/export plan); isolate darken default 0.65 with a one-shot legacy bump keyed by manifest `isolateDefaultVersion`; also fixes the reorder revert bug found in owner QA.
- `ee1494f` fixed the Watercolour band rendering opaque white: the grain overlay had been nested in `.maps-map-band`, whose stacking context isolated the multiply blend; now a sibling of the host, band-sized via the same CSS formula.
- `89f9749` shipped the poster-frame route (see todo `poster-frame` and Pointers below); two Codex passes (REQUEST-CHANGES then APPROVE-WITH-NITS, nit applied); tests `test_iwa_movies.py`, `test_probe_movie_poster.py`; the `iwa` extra (`keynote-parser`) is now installed in `.venv` via `uv sync --extra iwa`.
- `8edaed3` "painted keep mask is the cut-out": owner reported the cut-out kept the HDB flats behind the building even though the green overlay was tight; cause was `grabcut_mask` using `keepMask`/`removeMask` only as GrabCut seeds. Now a painted keep mask (any pixel > 127) defines the alpha directly minus the remove mask, bilinear-upscaled so the feather grows with the upscale factor; GrabCut only runs when nothing is painted, and rect is optional on that path; validation happens before mode selection; `_fill_hidden` weights by alpha. Codex REQUEST-CHANGES then APPROVE. Poster probe result (owner ran dump/patch 2026-09-10): a manual poster set changes only `posterTime` 0.00→1.20 (= endTime), no image fields; offline patch applied to 3 archives; reopen step is still pending (must be run on the `_poster.key` copy). Owner QA still owed: re-render the cut-out after restart.
- `462f0cd` flight profile for hop movies: `flight: "arc" | "phases"` on `MapsLink` (missing ⇒ arc, no legacy inference by owner decision); new `maps/flight.ts` van Wijk closed form (asinh-stable r0/r1, w0-relative pure-zoom guard, exact endpoints, rho = existing `curve`); arc defaults to linear easing (constant perceived velocity across uniform 30 fps frames); bearing/pitch follow progress; routes still honoured under arc; inspector gets a "Flight" select (phases controls + HopTimeline only shown under phases; "Curve" scrub shown under arc); Reset hop no longer forces ease-in-out; server Literal validation + non-movie strip; phases branch pinned by baked fixtures. Two Codex passes: REQUEST-CHANGES then APPROVE.

### Owner decisions 2026-09-10
- No legacy/back-compat handling: old jobs/sessions without `retiredLinks` fail to save/load and should be recreated; the isolate 0.60→0.65 migration may be stripped later if the owner wants.

## Known limits / assumptions

- **Province tile floor.** `admin_level` 4 geometry starts at map z1; nothing renders provinces below it. Preview runs `previewZoomDelta` below authored, so low-zoom previews stay silent about provinces even though the 7680 export shows them.
- **Export hairlines.** Vendored line weights are screen-scale, so authored z2-3 exports draw 1-1.2 px borders on the wall. The real fix is parked **option 2b** in [maps_toner_lowzoom.plan.md](maps_toner_lowzoom.plan.md) (render the export through the preview camera at pixelRatio 7.68).
- **Keynote autoplay is not scriptable.** Movies start on slide arrival unless "Start movie on click" is set; whether that applies depends on Document ▸ Movies / build order. Owner must check.
- **Landmark picker is LW-only** — the server appends to `slide["churches"]` with no audience parameter; the watercolour choice is disabled in CG.
- **Reveal cache is fingerprinted** on asset, duration, opacity, strokes, seed, audience, algo v3.
- **Slide ids ending `__landing` are rejected.**
- **Blur isolate not built** — only `mode: "darken"`; `"erase"` is migrated to darken on load, any other mode 400s.
- **Wand / pen are not a live-wire.** Magnetic pen is gradient snap of auto-anchors (Photoshop magnetic lasso approximately); a Dijkstra live-wire was explicitly out of scope.
- **Cancellation lands at stage boundaries, not just between files**: GrabCut and render check the job's cancel flag between iterations/stages, so the worst uninterruptible chunk on a 24 MP photo is one GrabCut iteration or one large blur (~10-30 s), not the whole file.
- **Mask specs are keyed by photo index only** — the old filename-key fallback (a duplicate-filename hazard) is gone; `start_watercolour` 400s if a mask key isn't a valid in-range index.
- **Server-minted landmarks use the `w<hex8>` namespace** (`w` + first 8 hex chars of the asset id, deduped against a fallback random hex8) — disjoint from the client's `p<n>` namespace, so Studio-add and local-paste landmarks never collide on id.

## Owner QA owed

Round from 2026-09-09: isolate sequence PASS, paint-on reveal PASS ("looks amazing"), objects PASS, pitched framing PASS, ink slider + darken PASS (darken now +5%, i.e. the 0.65 default), reorder revert bug FOUND and fixed in `aac2807`. Still owed:

1. Reveal-as-slide-movie playback in Keynote.
2. Keynote re-render of restored (reordered) pairs.
3. Poster-frame probe: run `scripts/probe_movie_poster.py` (dump hand-set deck vs untouched export; patch; reopen) to learn whether Keynote regenerates the poster from `posterTime` or keeps cached `posterImageData`; only then flip `OBED_MAPS_POSTER_FRAME` on (see todo `poster-frame`).
4. Preview and export a long hop (e.g. SEA overview → downtown) under Arc, compare feel vs Zoom-out/move/zoom-in; check bearing changes on a pitched hop.
5. Cancellation latency on a real 24 MP photo (painted mask, and rect-only so GrabCut runs); if GrabCut per-iteration is the long pole, follow-up = GrabCut on a downscaled image (separate decision).
6. Cancelled-batch UX: finished tiles usable, cancelled tiles muted, no red banner, Download batch returns finished files only.
7. Add-to-map to a non-active Maps slide → Maps shows placeholder thumbnail, selecting recaptures with the landmark, objects list already lists it.
8. Race: Studio add while a Maps edit is pending → no conflict dialog, both present.

## Open backlog

- **CAS atomic contract.** Mutations still do not share one atomic contract with job completion, CSV/export, history relocation, and the session status/commit window. Migrate remaining backend Maps writers, session/import and export-metadata paths through it; add rollback for failed atomic file/document publication.
- **Session assets/previews** are installed and backups removed before the document commit, so rollback is unreliable.
- **Conflict freeze is incomplete**: MapView gestures and callback paths stay live while form controls are locked.
- **Real concurrent-race tests**: Studio append vs stale state save, two appends, stale thumbnail writer after append, asset revision handoff, session import vs stale save, delete/edit conflict.
- **Keynote verification**: anchors, aspect ratio, world-copy/clipping, split CG output. Native Keynote opacity stays deferred — keep the derived PNG alpha path until separately approved. Never touch `A_PATCHED.key`.
- **3D terrain** unstarted; owner may want additional flight/animation types later — extend the `flight` enum.
- **Honest preview, options 2 / 2a / 2b** — see the toner plan. 2b also removes the export hairline problem.
- **Copy/paste target chooser** for multi-slide LW/CG destinations was never finished.

## Pointers

- **PR #63** (merged) and **PR #68** (merged) carried the earlier branch. PR #63 first review: verdict REQUEST-CHANGES, 11 findings, all addressed in `6c4c62f`; report and the posted comment are in the session scratchpad (`codex-review.md`, `pr-comment.md`). Second review (on `0644d97`): verdict REQUEST-CHANGES, 8 findings, 7 fixed in `290d4f7`, finding 2 rejected on purpose (country cut-out stays plain, no orange); see `codex-review2.md` in the scratchpad and the PR review comments.
- **PR #70** (open, `feat/maps-ux-round`) carries this state. Codex ran three passes on the UX round (`3a14021`): 2x REQUEST-CHANGES then APPROVE-WITH-NITS; four passes on the QA round (`aac2807`): 3x REQUEST-CHANGES then APPROVE. Reports in the session scratchpad `codex-review*.md`.
- **Poster-frame patch (shipped `89f9749`)**: Keynote AppleScript cannot set the movie's poster frame (movie class has no `poster` property), so the route is an offline IWA patch of `TSD.MovieArchive.posterTime` (field 5) via `src/obed_edom/iwa_movies.py` (`movie_archives` / `plan_movie_posters` / `patch_movie_posters`, one-to-one 1px frame match, refuse-not-guess), invoked from `_apply_poster_frames` in `maps_keynote.py` per deck after `_run_one_deck`, gated by env `OBED_MAPS_POSTER_FRAME=off|on|verify` (default off). Failures are contained: `OfflineWriteCorrupted` triggers deck regeneration unpatched and removal of the `.obedwrite.tmp` recovery file; `result["posterFrame"]` carries a per-deck record. Probe script `scripts/probe_movie_poster.py` (dump/patch/reopen, `--yes-open-keynote`, copies under `output/movie-poster-probe`, exact POSIX path check) is still owed a run before flipping the gate on — see Owner QA owed. `REVEAL_FPS=30` is now shared. `keynote-parser` (the `iwa` extra) is installed in `.venv` via `uv sync --extra iwa`. Two Codex passes: REQUEST-CHANGES then APPROVE-WITH-NITS, nit applied. Full original plan in the session scratchpad `qa-round-plan.md` Part A.
- Shipped-plan details live in the session scratchpad as `mask-upgrades-plan.md`, `isolate-round2-plan.md`, `round3-plan.md`, `landing-plan.md`, `picker-reorder-plan.md`, `preview-band-plan.md`, `reveal-plan.md`, `reveal2-plan.md`.
- Memory: `maps-p2-film-route`, `browser-pane-maplibre-hidden` (a hidden Browser pane freezes MapLibre's rAF — drive `map.resize()` via `javascript_tool`; never use port 8765).
- Commands (dashboard needs the bundled Node): `PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`, then `npm run test:maps` and `npm run build` from `dashboard`. Python: `.venv/bin/python -m pytest tests/test_maps_api.py tests/test_maps_keynote.py tests/test_maps_reveal.py tests/test_watercolour.py -q`. Restart: `.venv/bin/python -m obed_edom dashboard --no-browser --port 8766`.
