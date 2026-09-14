# Style picker thumbnails

Every file under `dashboard/public/style-thumbs/` should be the CG viewport (the 1920×1080 centre box of the wall) downscaled to 480×240 — a 2:1 crop of the CG box's full height, centred, not a 1:1 centre crop of the still (that read two zoom levels tighter than the camera). Camera (`STYLE_THUMB_CAMERA` in `styles.ts`): Marina Bay, `lat 1.2864, lon 103.8604`, zoom 15.5, pitch 0, bearing 75, CG shift X 0.

Only `watercolour.png` has been recaptured this way so far; the other nine are still old downtown z16.7 crops.

## Recapture recipe

1. `cd dashboard && npm run dev`, open the Maps tab, **New map deck** — never the production deck.
2. Type `@1.2864,103.8604` in the search box (accepts `@lat,lng`).
3. In the inspector set Zoom `15.5`, Pitch `0`, Bearing `75`, and CG shift X `0`.
4. Pick a style, wait for tiles to settle.
5. Either grab the maplibre canvas via devtools and `drawImage` the CG box (full band height, 2:1 width centred on the box) onto a 480×240 canvas and save, or export a CG still and downscale it to 480×240 for a crisper result.
6. Overwrite `dashboard/public/style-thumbs/<id>.png`.
