---
name: Maps region highlights
overview: Orange-highlight something larger or smaller than one country. Do not implement until the operator picks A or B. Peer [960f05c0] said do-not-build as first drafted.
todos:
  - id: decide-grain
    content: Operator picks A (states/provinces) or B (country packs like SEA). Default if they shrug is B.
    status: pending
  - id: namespaced-ids
    content: Keep existing ADM0_A3 strings; namespace any new highlight ids
    status: pending
  - id: pick-without-reframe
    content: Highlight pick must not change slide.camera. No zoom-banded grain.
    status: pending
  - id: export-parity
    content: Authoring, stills, plates, and fly frames paint the same highlights
    status: pending
isProject: false
---

# Maps region highlights

**Status: waiting on the operator.** Peer [960f05c0](960f05c0-42eb-4ef6-b1ec-9f46603a9880): **do-not-build** the first draft. Country click stays as shipped.

## What exists

- Orange fill is Natural Earth **admin-0** only. Local file is simplified 50m with `ADM0_A3` + `NAME` (~2 MB). CONTINENT / SUBREGION were stripped.
- Click toggles `slide.highlights: string[]`. Chip label is `admin0Name(code)`.
- Pick is **off at zoom ≥ 7** (`COUNTRY_PICK_MAX_ZOOM`) so a tap at Kallang does not paint Singapore. That no-op is deliberate, not a hole.
- Highlight mismatch forces **Cut**. Capture / export rasterise whatever MapLibre paints.
- `toggle_adm0` is test-only. The live toggle is `MapsTab.onToggleCountry`.
- Wrap is now on, with `minZoom = WORLD_MIN_ZOOM` so a 7680 export does not tile while the ~1920 preview looks clean.

## Two different “regions”

| Grain | What a click/chip selects | Data | Cost |
| --- | --- | --- | --- |
| **A. Subnational** | Sabah, California, Guangdong | NE admin-1 polygons | New geojson + pick layer |
| **B. Country pack** | Southeast Asia, Middle East | Static `ADM0_A3[]` table | No new polygons |

A is states. B is missions geography. They are not the same feature. Do not ship both in one pass.

## Peer verdict

- Do not key pick grain to zoom. Zoom is the authored camera; “zoom in to pick Sabah” silently rewrites the slide framing and the operator cannot see Malaysia at z≥7 on a SEA overview.
- `COUNTRY_PICK_MAX_ZOOM` stays. It is not a dead zone to fill.
- Default guess if the operator does not specify: **B**. Seed slide is a SEA overview; chips are country names; search resolves countries. “Regions” on this wall almost certainly means “paint Southeast Asia,” not “paint Sabah.”
- If A is chosen anyway: inspector control “Pick: Countries / Regions,” not a zoom band. Namespaced `A1:<adm1_code>`. Lazy-load admin-1 only when an `A1:` highlight exists. Chip names from `GET /ne/admin1-names`, not the full geojson. Drive fill with a MapLibre expression, not a 1,400-call `setFeatureState` loop. Validate `highlights` on `MapsSlide`. Confirm NE 50m actually has Sabah / Indonesian provinces / Myanmar states before downloading.

## If the operator picks B

- Add `REGION_PACKS` (SEA, East Asia, South Asia, Middle East, Africa, Europe, Americas) as ADM0 lists.
- Inspector “Add region…” unions those codes into `highlights`. Click stays country.
- No new geojson. No zoom-rule change. No `/ne/admin1`.

## If the operator picks A

Re-plan against the peer locks above before writing code. Files would include overlays, MapView, MapsTab, captureExport, layers SKIP, maps_geo load, `/ne/admin1` + `/ne/admin1-names`, `tests/test_maps_api.py` validator tests. There is no Vitest — carry a manual checklist. After `dashboard/src/**`: `cd dashboard && npm install && npm run build`, `git add -A dashboard/dist`, restart the dashboard.

Do **not** edit [map_remap.py](src/obed_edom/map_remap.py), [keynote.py](src/obed_edom/keynote.py), or [cli.py](src/obed_edom/cli.py).

## Out of scope either way

Nominatim polygons, custom “East Malaysia” / “Greater KL”, lasso draw, UN continent fills, live globe, IWA.
