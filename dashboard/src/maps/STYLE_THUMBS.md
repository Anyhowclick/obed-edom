# Style picker thumbnails

Every file under `dashboard/public/style-thumbs/` is a 480×240 centre crop of a Maps tab still, all captured at the same camera (`STYLE_THUMB_CAMERA` in `styles.ts`): Marina Bay, `lat 1.2864, lon 103.8604`, zoom 16.5, pitch 0, bearing 75, CG shift X 0.

## Recapture recipe

1. `cd dashboard && npm run dev`, open the Maps tab, **New map deck**.
2. Type `@1.2864,103.8604` in the search box (accepts `@lat,lng`).
3. In the inspector set Zoom `16.5`, Pitch `0`, Bearing `75`, and CG shift X `0`.
4. For each id in `STYLE_SWATCHES`, pick it in the style picker, let the still settle, and take the captured LW still from `output/.maps/<job>/`.
5. Centre-crop to 480×240 and overwrite `dashboard/public/style-thumbs/<id>.png`. `buildings3d` reuses the Liberty capture — at z16.5/pitch 0 no 3D buildings are visible, so keep the shared file unless that changes.
