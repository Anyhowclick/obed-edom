---
name: Maps P2 leftovers
overview: After the six P2 film-route review bugs, finish OSM-stamped fly frames, pin-less movie slides, and optional pin-order routes. No remap retune, no path editor.
todos:
  - id: osm-stamp-frames
    content: Stamp OSM on each fly frame via one canvas toBlob JPEG (no JPEG decode/re-encode)
    status: completed
  - id: hide-pins-on-movie
    content: Skip _place_churches in build_slide_items when bg_movie is set; assert items length 1
    status: completed
  - id: route-model
    content: Pydantic MapsRoute extra=forbid; coerceHopKinds clears route; delete unused documentPayload
    status: completed
  - id: route-capture
    content: cameraAlongRoute by mercator distance; zero-length path falls back to lerp
    status: completed
  - id: pins-as-route
    content: Use pins as route + route point count in inspector; number FROM pins when hop is Movie
    status: completed
isProject: false
---

# Maps P2 leftovers

Bugs 1–6 are fixed on `feat/maps-tab-authoring`. This plan is **only** what Fable listed as not started, after [Keynote review](c36d2d8c-a66b-444f-b982-86c71a2f2a17) and [capture review](c6c04166-3e38-466d-b5f2-557268a56a94).

## Locks

- Do not edit [map_remap.py](src/obed_edom/map_remap.py), [keynote.py](src/obed_edom/keynote.py), [framing.py](src/obed_edom/framing.py), [cli.py](src/obed_edom/cli.py), or [score_resize.py](scripts/score_resize.py).
- Do **not** add another `is_backdrop` movie test — `test_movie_backdrop_is_recognized` already exists.
- No path-drawing tool, no GEOlayers timeline, no live globe, no Keynote easing write, no ffmpeg on the API thread.
- Fly frames stay JPEG. Movie filename stays `Map BG_<slide>.mov`. Encode stays in JobRunner.
- Style/highlight mismatch is Cut. Route cannot override that.
- After `dashboard/src/**`, `cd dashboard && npm run build`.
- Morph-then-movie is already a **cross-dissolve into the movie**, not a real Magic Move onto B (`duplicate` is false when `bg_movie` is set). Do not “fix” that transition in this pass.

## 1. OSM stamp on frames

Do **not** run `stampOsm(jpegBlob)` (decode + second lossy encode).

- Add `stampOsmOnCanvas(canvas, mime, quality)` that draws `map.getCanvas()` and does **one** `toBlob`. `mime` is **required** (call site passes `"image/jpeg"`, `0.95`).
- In [captureFly.ts](dashboard/src/maps/captureFly.ts), replace the raw `toBlob` with this helper. Stamp **every** frame.
- Keep [stampOsm.ts](dashboard/src/maps/stampOsm.ts) PNG path for stills/plates.

## 2. Hide pins during the fly

Capture already omits churches. The miss is Keynote.

Gate in `build_slide_items` only (do not change `_place_churches`):

```python
items = [mapped]
if bg_movie is None:
    items.extend(_place_churches(...))
```

Arrival slide (`to`) still gets pins.

Test: departing movie slide with a church → `len(items) == 1`, `kind == "movie"`, `map is True`.

## 3. Follow-route (minimal)

### Persist for real

- Nested Pydantic in [maps.py](src/obed_edom/web/maps.py): `MapsRoutePoint { lat, lon }` and `MapsRoute { points: list[MapsRoutePoint] }`, both `extra="forbid"`. `MapsLink.route: MapsRoute | None = None`.
- [coerceHopKinds](dashboard/src/maps/types.ts) / `coerce_link_kinds`: `delete route` whenever the hop is no longer `movie`.
- [documentPayload](dashboard/src/maps/types.ts) is unused and **drops `route`**. Delete it, or copy `route` like `plateId` and actually use it. Do not leave a fake sanitizer.

### Capture

- `route.points.length >= 2` **and** cumulative mercator length > 0 → walk the polyline by distance. Eased `t` is the hop easing. Zoom / pitch / bearing still lerp `from` → `to`. Per-segment antimeridian unwrap (same as `unwrapMercatorX`).
- Otherwise today’s A→B lerp.
- Server encode does not need the route.

### UI

- Movie hop: **Use pins as route** copies FROM churches in list order into `link.route.points`. Disabled when `< 2` pins.
- When `route` is set, inspector shows `Route: N pts` (snapshot, not live-bound to pins).
- When the outgoing hop is Movie, number the FROM pins in the map labels so order is visible before the button. No reorder UI this pass.
- Reset hop / explicit clear drops `route`.

Out of scope: freehand path, CSV waypoints, look-ahead bearing.

## 4. `score_resize.py`

Already satisfied by `is_backdrop(kind=="movie")` plus `test_movie_backdrop_is_recognized`. **No work.**

## Order

1 and 2 in parallel. 3 after (needs captureFly as the single interpolation entry). Skip 4.

## Done when

Leftover P2 (this plan):

- Fly JPEGs show the OSM bar, one encode per frame, always `.jpg`.
- A Movie departing slide with pins exports exactly one map movie item. Arrival still gets pins.
- A Movie hop with ≥2 FROM pins can write a validated `route.points` (`extra="forbid"`, `min_length=2`) and the fly follows it; zero-length or missing route uses lerp.
- `documentPayload` is gone. Non-movie hops drop `route` (and `easing`).

After [leftover review](3e545ec8-1474-44c5-a51a-e2480f6ad10f):

- Export locks the tab for the whole capture (`exporting` in `locked` + Working overlay), not only while JobRunner is queued/running. A second Export cannot `rmtree` frames mid-sequence.
- `encode_pending` raises via `require_contiguous_frames` when `meta.json` exists and the sequence is short or gapped. Soft-skip only if there is no meta.
- Play hop / Play from here uses the same `cameraAtHop` + easing as capture, so “Use pins as route” is visible before Export.
