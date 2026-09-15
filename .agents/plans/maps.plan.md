---
name: Maps — active backlog and retained contracts
overview: >-
  Consolidated 2026-09-15 from the Maps/Watercolour state, P2 leftovers, Toner low-zoom,
  and region-highlight plans. Those feature plans are shipped or superseded; this file keeps
  only verified open work and the non-obvious contracts that future changes must preserve.
todos:
  - id: poster-frame-live-probe
    content: >-
      Run scripts/probe_movie_poster.py on a copy, reopen in Keynote, and confirm posterTime
      regenerates the visible poster before considering OBED_MAPS_POSTER_FRAME=on by default.
    status: pending
  - id: native-label-background
    content: >-
      Replace exported label-pill images with editable rounded-rectangle shapes through a
      per-shape offline style variation; never mutate a shared stylesheet style.
    status: pending
  - id: thumbnail-navigation-failure
    content: >-
      A non-stale captureThumb failure in selectSlide must not prevent navigation or escape as
      an unhandled rejection; surface the error consistently with the retry path.
    status: pending
  - id: bootstrap-default-style
    content: >-
      Decide whether manually/CSV-created slides inherit document.defaultStyle instead of the
      current hard-coded positron value, then cover both entry paths.
    status: pending
  - id: cg-isolate-off
    content: >-
      Preserve an explicit CG isolate-off override through documentFromResult and the Python
      landing-slide path.
    status: pending
  - id: place-matching
    content: >-
      Preserve real place types from the local dataset and replace substring country matching
      with an unambiguous rule.
    status: pending
  - id: session-rollback
    content: >-
      Make imported session assets/previews participate in the document commit or otherwise
      provide reliable rollback when import fails.
    status: pending
---

# Maps — active backlog and retained contracts

## Shipped; do not re-plan

- P2 movie routes are complete: optional pin-order route snapshots, Mercator-distance
  interpolation, pin-free departing movie slides, capture/playback parity, and contiguous-frame
  refusal.
- OSM attribution now defaults to an end-credits slide. Optional stamped mode still marks stills
  and fly frames in the canvas's single encode; never restore a JPEG decode/re-encode pass.
- Toner low-zoom boundaries and honest preview/export scaling are implemented in
  `dashboard/src/maps/tonerBoundaries.ts` and the authored-zoom gate path. The vendored Toner
  JSON remains immutable; adjustments happen at load time.
- Region highlighting is implemented for admin-0 and namespaced admin-1 ids, including isolate,
  per-highlight colours, cut-out export, hops, thumbnails, and lifecycle/race handling. Picking
  a region must not rewrite the authored camera.
- Pin/label sizing, Watercolour hatches, 3D ink, water-name scrubbing, save-panel export, and
  no-fill isolate are later shipped work. The September 9–13 branch diary is no longer a useful
  plan of record.

## Open work

### Poster frames

`src/obed_edom/iwa_movies.py` patches `TSD.MovieArchive.posterTime`; the export integration is
present but `OBED_MAPS_POSTER_FRAME` still defaults to `off`. A successful byte-level patch is
not enough: the live probe must establish that Keynote regenerates the visible poster rather
than retaining cached image data. Work only on copies and keep failure non-fatal to export.

### Editable label backgrounds

The current label pill is a rendered image. The desired Keynote-native result is editable text
over an editable rounded rectangle. The viable route is a surgical `TSD.ShapeInfo` write with a
per-shape `TSWP.ShapeStyleArchive` variation. Reusing or mutating a shared stylesheet style can
change unrelated objects and is forbidden. Gate and read back the patch like the other offline
writers.

### Correctness backlog

- `MapsTab.selectSlide` awaits the previous slide's thumbnail before changing selection. Only a
  stale-thumbnail error is expected; any other failure currently prevents navigation. Catch,
  report, and continue.
- `_row_slide` in `src/obed_edom/web/maps.py` still writes `style: "positron"`. Any inheritance
  change must cover both CSV and manual bootstrap rather than splitting their output.
- `cgFromResult` omits isolate when parsing yields no value, so an explicit off override cannot
  be distinguished from inheritance. Define a serialised off state before changing either side.
- `search_places` labels every local dataset hit as `city`; `_admin0_match(..., exact=False)`
  accepts substring country names. Preserve source classification and refuse ambiguous matches.
- Session import installs assets/previews before the document commit. Bring those writes under a
  recoverable transaction or leave enough staging state to roll them back reliably.

## Retained implementation contracts

- Preview and export use the same authored camera and surface-scale model. Do not repair a style
  issue with a preview-only zoom offset.
- A route is a snapshot of ordered points and is cleared when a hop stops being a movie; it is
  not live-bound to later pin edits.
- Fly frames stay JPEG and encoding remains in the background job, never on the API thread.
- Style/highlight mismatch forces Cut. A route cannot override that transition rule.
- Keep the raw vendored map styles and licence files unchanged; transformations belong in small,
  testable load-time modules.
