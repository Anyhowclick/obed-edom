---
name: Maps + Watercolour branch state
overview: PR #63, #68, #79, #81, and #82 (feat/maps-save-status-snap-guide) are merged into main. Open, Codex-approved, owner-merge-owed: #86 (hop preview isolate fix), #88 (landmark scale-with-map), #90 (tolerant CSV + zoom ladder). Open, stacked, Codex-in-flight: #87 (CAS contract) → #91 (job names) → #92 (export destination). Records what landed on 2026-09-09, 2026-09-11, the backlog round, the 2026-09-11 evening round, and the 2026-09-12 round, the limits those choices bake in, the QA the owner still owes, and the backlog that is genuinely still open.
todos:
  - id: owner-qa
    content: "Done 2026-09-09: isolate sequence, paint-on reveal, objects, pitched framing, ink slider + darken all PASS; reorder revert bug FOUND and fixed in aac2807. Still owed: reveal-as-slide-movie, Keynote re-render of restored pairs, and honest preview 2b QA (toner lines, pitched downtown, movie hops across relief/province/CG-crop gates, morph plate slide, centre-to-FW mixed hop, side-panel toggle on centre-only slide)."
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
    content: "Shipped: the race-tests/conflict-freeze package (7 concurrent-race tests + F1/F2/F3 backend fixes + dashboard conflict freeze, see 'Shipped 2026-09-11 (backlog round)'). Owner made all five CAS decisions 2026-09-12; PR #87 implements the contract, Codex-approved round 3, open. Stacked on top: PR #91 (job names) and PR #92 (export destination), both Codex-in-flight. Merge order #87 → #91 → #92."
    status: pending
  - id: round-2026-09-12
    content: "Merged PR #82 (save-status pill + CG snap guide). Open, Codex-approved, owner-merge-owed: PR #86 (hop preview isolate fix), PR #88 (landmarks scale with map), PR #90 (tolerant CSV + zoom ladder). Open, stacked, Codex-in-flight: PR #87 → #91 → #92. Owner QA 2026-09-12: 1,2,4,5 PASS; 3,6-8 need the pill + two tabs (see QA items 23-27 below)."
    status: pending
isProject: false
---

# Maps + Watercolour branch state

PR **#63**, PR **#68**, PR **#79** (`feat/maps-ux-round`), and PR **#81** (`feat/maps-backlog-races`) are merged into `main` (`#81` merged as `1a4ee00`). Current branch `feat/maps-save-status-snap-guide`, off `1a4ee00`, PR not yet opened. Workspace `/Users/anyhowclick/Desktop/work/obed-edom-wt-maps-tab`. Never edit `/Users/anyhowclick/Desktop/work/obed-edom` (unrelated dirty branch).

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
- `69be4e7` watercolour lifecycle leftovers: cooperative cancellation (`WatercolourCancelled` at stage boundaries, GrabCut split into single `GC_EVAL` iterations with byte-identical output pinned by test), cancelled batches retain finished files and show muted cancelled tiles, mask specs keyed by photo index only + submit-time validation via `decode_image`, one atomic `append_landmark` shared by Studio add-to-map and the new `POST /{job}/slides/{slide}/landmark` (asset promoted before publish, `w<hex8>` ids, `stillPng` invalidated, client has no optimistic window, `churchId` returned), JobRunner hardening (per-job locks, unique temp files, `update_result` reverts on save failure, delete tombstones, submit never reuses an id). Six Codex passes (five REQUEST-CHANGES then APPROVE), full pytest suite 1693 passed.

- `8b4341a` honest preview option 2b: every surface renders as a 1920 CSS px screen magnified (FW 7680 scale 4, LW 3840 scale 2, CG 1920 scale 1 unchanged; camera `log2(scale)` below authored; output px == authored px; plates keep ceil/centred crop via `plateSurfaceWidth` from slideIds), preview pinned to the same inner element scaled to the band (`compensatedFov`/`previewHostRect` removed), zoom clamps/object scale/isolate projection/CG crop/prefetch/toner+relief gates follow the render camera (relief keyed off authored zoom everywhere), movie hops preview at `hopSurfaceWidth = max(from,to)` with MapView override restored on every exit path (`hopRestore`/`hopSeq`/`silentJump`); toner hairline limit resolved (toner plan updated). Reviews: Codex R1 5 findings → fix → opus 5 rounds (APPROVE-WITH-NITS ×3 with fixes applied) interleaved with Codex R2/R3 one High each → Codex R4 APPROVE. Known limits: tiles are fetched 1-2 zoom levels coarser than before on FW/LW (deliberate; dense downtown slides look softer; hillshade/NE2 raster upscaled), and `createExportMap` has no node test (Vite worker import).

## Shipped 2026-09-11

- `1fc4039` preview shows map above and below the band again; object controls draw over the crop overlay. Owner QA of honest preview 2b found two regressions that had happened before: (a) no map above/below the band for navigation (pinned inner = band only); (b) object box/handles hidden behind the CG/LW crop overlay. Fixed in `previewLayout(frameW, frameH, surfaceWidth, scale)` (`types.ts`): pinned-density inner element up to `PREVIEW_NAV_MAX = 3` bands tall, band centred via `translateY(-bandTop·k) scale(k)`, fov re-compensated (`compensatedFov` restored) so the band projects like the export, thumbnails/dissolve frames crop to the band; one `applyTransform` folds size/transform/fov/pixelRatio under suppress (MapLibre `resize`/`setPixelRatio`/`setVerticalFieldOfView` fire `moveend` synchronously); passthrough `transformConstrain` constructor option kept; new `BandOverlays.tsx` renders the crop overlay then a band-space object layer above it; nav margins z-index 3. Regression tests that fail on the old structure: `dashboard/tests/preview-layout.test.cjs` and `dashboard/tests/band-overlays.test.cjs` — any preview-surface rework must keep them green. Reviews: five opus rounds (one overturned a prior reviewer's band-height-constrain finding — the constructor option already bypassed the default constrain), Codex two passes → APPROVE.

## Shipped 2026-09-11 (backlog round)

- `9403888` seven concurrent-race tests (`tests/test_maps_api.py` end section): Studio append vs stale state save, two appends, stale thumbnail writer after append, asset revision handoff, session import vs stale save, delete/edit conflict.
- `a9fa873`/`c8a6d72`/`f95f23e`/`e31733e` **F1** stale thumbnail write moved under `_mutate_document` in `post_png`; optional `revision` query param; a stale write 409s with `{staleThumbnail, stateRevision}`, no document write and no revision bump.
- `5b64012` **F2** `load_session` status flip and publish now happen under one `_mutation_lock`, closing the window where a concurrent save could land between them.
- `9a6317d` **F3** `JobRunner.update_result` (`jobs.py`, shared by every job type) re-checks job membership under lock before writing a result.
- `f32c3b1`/`e3e00bd`/`e29a4a0`/`f84959c`/`a342705`/`2c111ae`/`835d812` dashboard conflict freeze: `applyLocalDoc` is the single choke point for local-doc writes (no-op during a conflict); `setLocalDoc` is a raw setter used only by the save queue's publish; `onConflict` sets `saveConflictRef` synchronously and bumps `thumbnailToken`; `captureThumb` re-checks `shouldPublishThumb` after every await; new pure `dashboard/src/maps/commit.ts` (`withSlideCamera`/`commitCamera`); thumbnail posts pass the acknowledged revision and retry a stale 409 once, only when the local acknowledged revision >= the server's; `MapsStaleThumbnailError` added to `api.ts`; `readError` now parses the response body once. Tests: `dashboard/tests/conflict-freeze.test.cjs`, additions to `saveQueue.test.cjs`.
- `24838e6` closed thumb-capture and session-import mutation races: shared `thumbnailFingerprint(slideId, audience, view, geometry)` in `maps/commit.ts`, used by both the effect and `captureThumb`, re-checked after `stampOsm`; `load_session`'s idle check and status flip now happen under one `_mutation_lock`, restored on `BaseException`; test `test_load_session_locks_idle_check_and_status_flip_together`.
- `9ea5eb5` survives a client disconnect mid-import, unifies the thumbnail fingerprint further, deflakes a lock test.
- `0af6bd9`/`63cefb3` a stale 409 now `await saveQueue.flush()`s before retrying; any flush failure stops the retry instead of retrying blind; `saveQueue` test pins that flush resolves after `base.revision` updates.
- `5f9791c` the stale-thumbnail retry is awaited before returning.
- `37e6e66` `sameView` in `shouldPublishThumb`: a capture aborts if the displayed slide/audience changed mid-flight.
- `c2ff6ee` `shouldReconcileThumb({frozen, sameJob})` gates the post-POST reconcile of a committed thumbnail upload after navigating away.
- `d09f52f`/`8de19ce` race tests made deterministic (lock-signal instead of timed joins), assertions tightened.
- Reviews: opus rounds throughout + Codex final gate ran 6 rounds on the whole branch (rebased on `main` `31f9dbe` after round 1 flagged it behind), each round one finding, all fixed. Codex round 7 APPROVED on `39f4a35`. Full pytest and dashboard suites run (jobs.py is shared).
- Declined: Codex's ask for a React harness for MapsTab (no such harness exists; owner decision to skip); opus's "thumbnail permanently stale when a bump doesn't touch the slide" (the existing thumbnail still matches the view; only a change that pops it changes the slide fingerprint).
- Known limit: the stale-thumbnail retry stops silently when the local doc is behind the server (see F1). The CAS/session-import atomic contract — F4, `post_png` writing into `previewDir` while `load_session` swaps it — is **not** fixed; a plan exists (see Open backlog).

## In progress 2026-09-11 (evening)

- `385a656` save-status pill in the Maps toolbar (Saved / Saving… / Unsaved / Paused / Save failed): `MapsSaveStatus`, a `status` getter + `onStatus` callback on `MapsSaveQueue`.
- `33f4edf` Keynote-style yellow centre guide (`.maps-snap-guide`, `--snap-guide`) shown while the CG crop snaps to centre.
- Opus review: REVISE, four fixes being applied — `MapsSaveBlockedError` must not set `lastError`/call `onError` in `drain`'s catch; `markDirty` moved to edit time in `scheduleSave`; the guide gated by `exportCg && !splitCg`; `aria-live` added to the pill. Codex gate not yet run.
- Note: two implementers stalled because a new saveQueue test looped forever (transport conflicting on every call through `keepMyChanges`) — always run `node --test` in the foreground with `timeout`.

### Owner QA results 2026-09-11 evening

Items 1, 2, 4, 5 (below) PASS. Items 3, 6, 7, 8 could not be observed: there was no save indicator, and the conflict banner only appears when another tab/Studio changed the job — the pill is the fix; re-test with two tabs.

### Owner decisions 2026-09-10
- No legacy/back-compat handling: old jobs/sessions without `retiredLinks` fail to save/load and should be recreated; the isolate 0.60→0.65 migration may be stripped later if the owner wants.

## Shipped/open 2026-09-12

- **PR #82** (`feat/maps-save-status-snap-guide`) merged.
- **PR #86** (`feat/maps-isolate-hop-preview`, open, Codex-approved, owner merges): hop preview follows the export's isolate behaviour — the fly renders the source slide's isolate throughout, lands plain, then dissolves into the destination's isolate via shared `crossfadeTo`; `isolateDissolveNeeded`/`plainIsolateTarget` helpers pick when a dissolve is needed; abort-safe; `playHop`/`playFromHere` now catch rejections. Fixes the "isolate darken inconsistent in hop preview" backlog item below.
- **PR #88** (`feat/maps-landmark-scale`, open, Codex-approved, owner merges): landmarks can scale with the map — `scaleWithMap` toggle + `sizeZoom`, exponential base-2 icon-size curve with `sizeZoomRef` folding in the surface scale, `_effective_size` as the single chokepoint in Keynote render and reveal; `revealMovie` cleared when the last painted landmark on a slide goes. Owner decision: shrink with no minimum.
- **PR #90** (`feat/maps-csv-zoom-ladder`, open, Codex-approved, owner merges): tolerant CSV import + zoom ladder — new `maps_csv.py`, header/headerless auto-detection, bounded (≤4-line) records with dialect-aware `_has_open_quote`, linear URL peel capped at 8 tokens, zoom ladder country 4.3 / state 6.8 / city 10.5 / town 13 / neighbourhood 15.5 / building 18, precedence explicit-zoom > URL > ladder > 13 fallback, geocoder gains `placeType` + `zoomFromUrl`, cache key bumped to v2, `clamp_lon` uses modulo. Owner decision: headerless CSV gets auto zoom; ladder city/district boundary still to be honed by eye.
- **PR #87 → #91 → #92** (stacked, Codex-in-flight, merge in this order):
  - **#87 CAS contract** (`feat/maps-cas-contract`): `maps_commit`/`MapsCommit` is the one write contract; every Maps writer migrated onto it; `_bump_state_revision` runs on export/bootstrap completion (previously missed); `_loop` reverts to error state on a failed save; the generic relocate endpoint now 409s for Maps jobs. Owner decisions baked in: frames are lock-only (not routed through the contract); relocate 409s rather than going through the contract; stills/plates commit with `bump=False`; a failed import leaves tiles in place. Known limit: `_clear_derived_maps_output` is unstaged inside the import commit. Codex APPROVED round 3.
  - **#91 job names** (`feat/job-names`): two-word `Job.name`, minted from a wordlist; rename now moves all six id-derived folders; `JobRunner.rename` + `PATCH /api/jobs/{id}/name`; Maps rename goes through `maps_commit(bump=False)` using plain `os.replace` with manual restore on failure (`stage_path`'s abort path deletes a moved source, so the contract's usual abort doesn't fit here); `_reserved_names` guards collisions; rename is taken under `_job_lock`; containment/symlink guards on the folder move. Opus reviewed ×3; Codex round 2 in flight. Owner decision: rename renames the folder.
  - **#92 export destination** (`feat/export-destination`): `defaultExportDir` setting, validated only on save; `export_destination(job)` resolves per-job with a fallback flag; dashboard gets a per-tab `ExportDestinationRow` + `useSessionPath`/`useDefaultExportDir`; generator exports go to `<dest>/<stem>/`, other job types stay flat; watercolour copies out to the resolved destination. Opus reviewed ×2; Codex in flight. Owner decision: export destination is a global default with a per-tab override.
- **Owner decisions 2026-09-12** (supersedes/extends 2026-09-10 decisions): CSV import is headerless-friendly with auto zoom; zoom ladder as above; session rename renames the folder; landmarks shrink with zoom, no minimum size; export destination = global default + per-tab override; all five CAS-contract recommendations from the plan accepted (frames lock-only, relocate 409, stills/plates `bump=False`, naming as implemented, failed import leaves tiles).
- **Owner QA 2026-09-12**: items 1, 2, 4, 5 PASS (carried from 2026-09-11 evening). Items 3 and 6-8 still need PR #82's pill plus two open tabs to observe. New QA items below (23-27) cover #86/#88/#90/#91/#92.

## Known limits / assumptions

- **Province tile floor.** `admin_level` 4 geometry starts at map z1; nothing renders provinces below it. Preview runs `previewZoomDelta` below authored, so low-zoom previews stay silent about provinces even though the 7680 export shows them.
- **Export hairlines resolved in `8b4341a`** via honest preview option 2b (render camera at `log2(scale)` below authored, output px == authored px); see toner plan for detail. Tiles now fetch 1-2 zoom levels coarser on FW/LW (deliberate trade-off; dense downtown slides look softer, hillshade/NE2 raster upscaled).
- **Keynote autoplay is not scriptable.** Movies start on slide arrival unless "Start movie on click" is set; whether that applies depends on Document ▸ Movies / build order. Owner must check.
- **Landmark picker is LW-only** — the server appends to `slide["churches"]` with no audience parameter; the watercolour choice is disabled in CG.
- **Reveal cache is fingerprinted** on asset, duration, opacity, strokes, seed, audience, algo v3.
- **Slide ids ending `__landing` are rejected.**
- **Blur isolate not built** — only `mode: "darken"`; `"erase"` is migrated to darken on load, any other mode 400s.
- **Wand / pen are not a live-wire.** Magnetic pen is gradient snap of auto-anchors (Photoshop magnetic lasso approximately); a Dijkstra live-wire was explicitly out of scope.
- **Cancellation lands at stage boundaries, not just between files**: GrabCut and render check the job's cancel flag between iterations/stages, so the worst uninterruptible chunk on a 24 MP photo is one GrabCut iteration or one large blur (~10-30 s), not the whole file.
- **Mask specs are keyed by photo index only** — the old filename-key fallback (a duplicate-filename hazard) is gone; `start_watercolour` 400s if a mask key isn't a valid in-range index.
- **Server-minted landmarks use the `w<hex8>` namespace** (`w` + first 8 hex chars of the asset id, deduped against a fallback random hex8) — disjoint from the client's `p<n>` namespace, so Studio-add and local-paste landmarks never collide on id.
- **`jobs.py` is shared by every job type** — run the full pytest suite when touching it.

## Owner QA owed

Round from 2026-09-09: isolate sequence PASS, paint-on reveal PASS ("looks amazing"), objects PASS, pitched framing PASS, ink slider + darken PASS (darken now +5%, i.e. the 0.65 default), reorder revert bug FOUND and fixed in `aac2807`. Still owed:

1. Reveal-as-slide-movie playback in Keynote. **PASS** (2026-09-11 evening).
2. Keynote re-render of restored (reordered) pairs. **PASS** (2026-09-11 evening).
3. Poster-frame probe: run `scripts/probe_movie_poster.py` (dump hand-set deck vs untouched export; patch; reopen) to learn whether Keynote regenerates the poster from `posterTime` or keeps cached `posterImageData`; only then flip `OBED_MAPS_POSTER_FRAME` on (see todo `poster-frame`). Not observed 2026-09-11 evening (no save indicator existed yet to confirm state).
4. Preview and export a long hop (e.g. SEA overview → downtown) under Arc, compare feel vs Zoom-out/move/zoom-in; check bearing changes on a pitched hop. **PASS** (2026-09-11 evening).
5. Cancellation latency on a real 24 MP photo (painted mask, and rect-only so GrabCut runs); if GrabCut per-iteration is the long pole, follow-up = GrabCut on a downscaled image (separate decision). **PASS** (2026-09-11 evening).
6. Cancelled-batch UX: finished tiles usable, cancelled tiles muted, no red banner, Download batch returns finished files only. Not observed 2026-09-11 evening (no save indicator existed to confirm state).
7. Add-to-map to a non-active Maps slide → Maps shows placeholder thumbnail, selecting recaptures with the landmark, objects list already lists it. Not observed 2026-09-11 evening (no save indicator existed to confirm state).
8. Race: Studio add while a Maps edit is pending → no conflict dialog, both present. Not observed 2026-09-11 evening — the conflict banner only appears when another tab/Studio changed the job; the save-status pill (`385a656`) is the fix, re-test with two tabs.
9. Honest preview 2b: toner-lines still at authored 2.5 vs preview.
10. Honest preview 2b: pitched downtown z16 still vs preview at 25%.
11. Honest preview 2b: a movie hop crossing a relief/province gate (scrub for popping).
12. Honest preview 2b: a CG-crop movie hop.
13. Honest preview 2b: a morph plate slide in Keynote.
14. Honest preview 2b: a centre→FW mixed movie hop preview vs export.
15. Honest preview 2b: "Show side panels" on a centre-only slide (density unchanged, CG frame aligned).
16. FW slide with the display toggle off shows the full wall with the CG frame aligned.

Round from 2026-09-11 (honest preview 2b owner QA): cut-out PASS, flight PASS, reorder PASS, darken PASS, add-to-map PASS. Toolbar/handles reported as regressed (hidden behind the CG/LW crop overlay) and no map above/below the band for navigation — both fixed in `1fc4039` (see Shipped 2026-09-11), re-check owed. Watercolour cancel not yet tested. Poster frame: reopen was run on an unpatched export — owner to rerun on the `_poster.key` copy. Add:

17. Navigation context visible above/below the band (post-`1fc4039`).
18. Object handles above the CG/LW frame (post-`1fc4039`).
19. Window resize does not dirty the document.
20. Save conflict: gestures stay live but nothing edits the document until Reload latest / Keep my changes; thumbnails not posted during a conflict.
21. Save-status pill shows Unsaved→Saving…→Saved on an edit, Paused on a conflict, never flips on resize/inspector toggle.
22. Yellow centre guide appears only while dragging the CG frame at snap.

Round from 2026-09-12 (add):

23. Hop preview A→B with isolate on B only, tried from A and from B (PR #86).
24. Landmark shrinks when zooming out; toggling `scaleWithMap` off keeps its on-screen size (PR #88).
25. Paste the three-line CSV sample end to end (PR #90).
26. Rename a Maps job from History — the folder follows and export still works (PR #91).
27. Set a default export folder, export a deck, then set a per-tab override once and export again (PR #92).

## Open backlog

- **CAS atomic contract** — owner made all five decisions 2026-09-12 (frames lock-only, relocate 409, stills/plates `bump=False`, naming as implemented, failed import leaves tiles); implemented in PR #87, Codex-approved round 3, open. See "Shipped/open 2026-09-12" above. Known limit carried into #87: `_clear_derived_maps_output` is unstaged inside the import commit.
- **Session assets/previews** are installed and backups removed before the document commit, so rollback is unreliable.
- **Keynote verification**: anchors, aspect ratio, world-copy/clipping, split CG output. Native Keynote opacity stays deferred — keep the derived PNG alpha path until separately approved. Never touch `A_PATCHED.key`.
- **3D terrain** unstarted; owner may want additional flight/animation types later — extend the `flight` enum.
- **Copy/paste target chooser** for multi-slide LW/CG destinations was never finished.
- **`selectSlide` unguarded thumbnail await.** `selectSlide` awaits `captureThumb(prev)` unguarded, and every caller does `void selectSlide(...)`, so a non-stale thumbnail POST failure on the first attempt silently prevents the slide switch (unhandled rejection) — asymmetric with the retry path, which surfaces via `setError`. Found in review; pre-existing, not introduced by this branch.
- **Isolate darken inconsistent in hop preview** — fixed by PR #86 (`feat/maps-isolate-hop-preview`, open, Codex-approved): preview now matches export's source-appearance-during-fly, plain-landing-then-dissolve behaviour via shared `crossfadeTo`. QA item 23 owed once merged.
- **CG "isolate off" doesn't persist**: `cgFromResult` drops an explicit `undefined` key, so turning isolate off on a CG slide doesn't stick; the Python landing-slide path also copies the CG override verbatim instead of accounting for this. Found 2026-09-12, not yet fixed.
- **`artifact_status`** doesn't report a `suggestedPath` for external-generator folders. Found 2026-09-12, not yet fixed.
- **Preview lacks the 20000 clamp / sub-1px drop** that scaled landmarks (PR #88) need — a very large or sub-pixel landmark can render oddly in preview even though export clamps it. Found 2026-09-12, not yet fixed.
- **`search_places` hard-codes `placeType: "city"`** regardless of what's actually found (PR #90's ladder supports finer place types but the search endpoint doesn't pass them through). Found 2026-09-12, not yet fixed.
- **Substring admin0 match** in the CSV/geocode path can mismatch country names that are substrings of one another. Found 2026-09-12, not yet fixed.

## Pointers

- **PR #63** (merged) and **PR #68** (merged) carried the earlier branch. PR #63 first review: verdict REQUEST-CHANGES, 11 findings, all addressed in `6c4c62f`; report and the posted comment are in the session scratchpad (`codex-review.md`, `pr-comment.md`). Second review (on `0644d97`): verdict REQUEST-CHANGES, 8 findings, 7 fixed in `290d4f7`, finding 2 rejected on purpose (country cut-out stays plain, no orange); see `codex-review2.md` in the scratchpad and the PR review comments.
- **PR #70** (open, `feat/maps-ux-round`) carries this state. Codex ran three passes on the UX round (`3a14021`): 2x REQUEST-CHANGES then APPROVE-WITH-NITS; four passes on the QA round (`aac2807`): 3x REQUEST-CHANGES then APPROVE. Reports in the session scratchpad `codex-review*.md`.
- **Forced full-wall display (shipped `40940b90`)**: an FW-authored slide now always previews the full wall regardless of the display toggle. `surfaceWidthOf` is the single source of truth; `MapView` derives `splitCg`/`fullWall` from it; the thumbnail fingerprint carries authored + displayed surface width. Codex ran 2 review rounds then APPROVE.
- **Poster-frame patch (shipped `89f9749`)**: Keynote AppleScript cannot set the movie's poster frame (movie class has no `poster` property), so the route is an offline IWA patch of `TSD.MovieArchive.posterTime` (field 5) via `src/obed_edom/iwa_movies.py` (`movie_archives` / `plan_movie_posters` / `patch_movie_posters`, one-to-one 1px frame match, refuse-not-guess), invoked from `_apply_poster_frames` in `maps_keynote.py` per deck after `_run_one_deck`, gated by env `OBED_MAPS_POSTER_FRAME=off|on|verify` (default off). Failures are contained: `OfflineWriteCorrupted` triggers deck regeneration unpatched and removal of the `.obedwrite.tmp` recovery file; `result["posterFrame"]` carries a per-deck record. Probe script `scripts/probe_movie_poster.py` (dump/patch/reopen, `--yes-open-keynote`, copies under `output/movie-poster-probe`, exact POSIX path check) is still owed a run before flipping the gate on — see Owner QA owed. `REVEAL_FPS=30` is now shared. `keynote-parser` (the `iwa` extra) is installed in `.venv` via `uv sync --extra iwa`. Two Codex passes: REQUEST-CHANGES then APPROVE-WITH-NITS, nit applied. Full original plan in the session scratchpad `qa-round-plan.md` Part A.
- Shipped-plan details live in the session scratchpad as `mask-upgrades-plan.md`, `isolate-round2-plan.md`, `round3-plan.md`, `landing-plan.md`, `picker-reorder-plan.md`, `preview-band-plan.md`, `reveal-plan.md`, `reveal2-plan.md`.
- Memory: `maps-p2-film-route`, `browser-pane-maplibre-hidden` (a hidden Browser pane freezes MapLibre's rAF — drive `map.resize()` via `javascript_tool`; never use port 8765).
- Commands (dashboard needs the bundled Node): `PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`, then `npm run test:maps` and `npm run build` from `dashboard`. Python: `.venv/bin/python -m pytest tests/test_maps_api.py tests/test_maps_keynote.py tests/test_maps_reveal.py tests/test_watercolour.py -q`. Restart: `.venv/bin/python -m obed_edom dashboard --no-browser --port 8766`.
