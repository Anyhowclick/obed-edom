const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-export-surface-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const {
  exportScale,
  exportZoomDelta,
  exportSurface,
  exportCamera,
  EXPORT_REF_WIDTH,
  plateSurfaceWidth,
  surfaceWidthOf,
  hopSurfaceWidth,
  cgDragDx,
  clampMapZoom,
  ML_MIN_ZOOM,
  ML_MAX_ZOOM,
  WALL_W,
  CENTRE_W,
  CG_W,
} = require(path.join(out, "types.js"));

test("exportScale is per-surface: FW/LW/CG each render as a 1920-CSS-px screen", () => {
  assert.equal(EXPORT_REF_WIDTH, 1920);
  assert.equal(exportScale(7680), 4);
  assert.equal(exportScale(3840), 2);
  assert.equal(exportScale(1920), 1);
  // 6151 sits between 1920*2 and 1920*4; log2(6151/1920) = 1.68 rounds to 2, so scale snaps to 4.
  assert.equal(exportScale(6151), 4);
});

test("exportZoomDelta is -log2(scale) per surface", () => {
  assert.equal(exportZoomDelta(7680), -2);
  assert.equal(exportZoomDelta(3840), -1);
  assert.equal(exportZoomDelta(1920), 0);
  assert.equal(2 ** -exportZoomDelta(7680), exportScale(7680));
});

test("exportSurface: FW 7680x1080 -> css 1920x270 at pixelRatio 4, no crop", () => {
  const s = exportSurface(7680, 1080);
  assert.deepEqual(s, { cssWidth: 1920, cssHeight: 270, pixelRatio: 4, canvasWidth: 7680, canvasHeight: 1080, cropX: 0, cropY: 0 });
});

test("exportSurface: LW 3840x1080 -> css 1920x540 at pixelRatio 2, no crop", () => {
  const s = exportSurface(3840, 1080);
  assert.deepEqual(s, { cssWidth: 1920, cssHeight: 540, pixelRatio: 2, canvasWidth: 3840, canvasHeight: 1080, cropX: 0, cropY: 0 });
});

test("exportSurface: CG 1920x1080 -> css 1920x1080 at pixelRatio 1, no crop", () => {
  const s = exportSurface(1920, 1080);
  assert.deepEqual(s, { cssWidth: 1920, cssHeight: 1080, pixelRatio: 1, canvasWidth: 1920, canvasHeight: 1080, cropX: 0, cropY: 0 });
});

test("exportSurface: odd morph plate at the FW surface's scale gets a centred sub-scale crop", () => {
  const s = exportSurface(6151, 1731, 7680);
  assert.equal(s.pixelRatio, 4);
  assert.equal(s.cssWidth, 1538);
  assert.equal(s.cssHeight, 433);
  assert.equal(s.canvasWidth, 6152);
  assert.equal(s.canvasHeight, 1732);
  assert.equal(s.cropX, 0);
  assert.equal(s.cropY, 0);
});

test("exportSurface: the crop is CENTRED, not left/top-anchored (2-3 surplus px, not 0-1)", () => {
  // width 6149 at scale 4: cssWidth = ceil(6149/4) = 1538, canvasWidth = 6152, surplus = 3.
  // A left-anchored implementation (cropX always 0) would fail floor(3/2) === 1.
  const s = exportSurface(6149, 1729, 7680);
  assert.equal(s.canvasWidth - 6149, 3);
  assert.equal(s.cropX, 1);
  assert.equal(s.canvasHeight - 1729, 3);
  assert.equal(s.cropY, 1);
});

test("exportSurface: canvas is never smaller than the authored output, and the crop is sub-scale", () => {
  for (let w = 1; w <= 200; w++) {
    for (const surfaceWidth of [1920, 3840, 7680]) {
      const s = exportSurface(w, w + 7, surfaceWidth);
      assert.ok(s.canvasWidth >= w);
      assert.ok(s.canvasHeight >= w + 7);
      assert.ok(s.canvasWidth - w < s.pixelRatio);
      assert.ok(s.canvasHeight - (w + 7) < s.pixelRatio);
    }
  }
});

test("exportCamera shifts zoom by -log2(scale) for the given surface width, other fields pass through", () => {
  const camera = { lat: 1.5, lon: 103.8, zoom: 2.5, bearing: 12, pitch: 0.2 };
  assert.equal(exportCamera(camera, 7680).zoom, 0.5);
  assert.equal(exportCamera(camera, 3840).zoom, 1.5);
  assert.equal(exportCamera(camera, 1920).zoom, 2.5);
  const shifted = exportCamera(camera, 7680);
  assert.equal(shifted.lat, camera.lat);
  assert.equal(shifted.lon, camera.lon);
  assert.equal(shifted.bearing, camera.bearing);
  assert.equal(shifted.pitch, camera.pitch);
});

test("exportSurface for CG plates: scale comes from the passed surfaceWidth (1920), not the plate dims", () => {
  const s = exportSurface(2400, 1080, 1920);
  assert.equal(s.pixelRatio, 1);
  assert.equal(s.cssWidth, 2400);
  assert.equal(s.canvasWidth, 2400);
});

test("plateSurfaceWidth: an FW morph plate (a slide with includeSidePanels) selects scale 4, a centre-only plate selects scale 2", () => {
  const slidesById = new Map([
    ["s1", { includeSidePanels: false }],
    ["s2", { includeSidePanels: true }],
    ["s3", { includeSidePanels: false }],
  ]);
  const fwPlateWidth = plateSurfaceWidth(["s1", "s2"], slidesById);
  assert.equal(fwPlateWidth, WALL_W);
  assert.equal(exportScale(fwPlateWidth), 4);

  const centrePlateWidth = plateSurfaceWidth(["s1", "s3"], slidesById);
  assert.equal(centrePlateWidth, CENTRE_W);
  assert.equal(exportScale(centrePlateWidth), 2);
});

test("plateSurfaceWidth falls back to CENTRE_W for missing/empty slideIds with no plateW hint", () => {
  assert.equal(plateSurfaceWidth([], new Map()), CENTRE_W);
  assert.equal(plateSurfaceWidth(["missing"], new Map()), CENTRE_W);
});

test("plateSurfaceWidth falls back from plate.plateW when slideIds don't resolve", () => {
  assert.equal(plateSurfaceWidth([], new Map(), CENTRE_W), CENTRE_W);
  assert.equal(plateSurfaceWidth(["missing"], new Map(), CENTRE_W), CENTRE_W);
  assert.equal(plateSurfaceWidth([], new Map(), WALL_W), WALL_W);
  assert.equal(plateSurfaceWidth(["missing"], new Map(), CENTRE_W + 1), WALL_W);
});

test("surfaceWidthOf: displayed width is driven by the toggle, independent of authoredWidth (density)", () => {
  // The toggle alone decides the DISPLAY extent (WALL_W with it on, CENTRE_W without) — the
  // slide's own authoredWidth (density) plays no part except deciding the CG-split boundary.
  assert.equal(surfaceWidthOf(CENTRE_W, false), CENTRE_W);
  assert.equal(surfaceWidthOf(CENTRE_W, true), WALL_W);
  // Even an FW-authored slide (authoredWidth === WALL_W) only widens the DISPLAY when the toggle
  // is on — with it off, the display still narrows to CENTRE_W while density stays FW.
  assert.equal(surfaceWidthOf(WALL_W, false), CENTRE_W);
  assert.equal(surfaceWidthOf(WALL_W, true), WALL_W);
  // CG split always shows just the CG crop regardless of the toggle.
  assert.equal(surfaceWidthOf(CG_W, true), CG_W);
});

test("clampMapZoom: FW authored zoom 1 renders at -1 (exportZoomDelta(7680) === -2), unclamped", () => {
  const renderZoom = 1 + exportZoomDelta(WALL_W);
  assert.equal(renderZoom, -1);
  assert.equal(clampMapZoom(renderZoom), -1);
  assert.equal(ML_MIN_ZOOM, -2);
  assert.equal(ML_MAX_ZOOM, 22);
  assert.equal(clampMapZoom(ML_MIN_ZOOM - 1), ML_MIN_ZOOM);
  assert.equal(clampMapZoom(ML_MAX_ZOOM + 1), ML_MAX_ZOOM);
});

test("hopSurfaceWidth: mixed-surface hops render at the wider of the two endpoints' own surfaces", () => {
  const centre = { includeSidePanels: false };
  const fw = { includeSidePanels: true };
  assert.equal(hopSurfaceWidth(centre, fw, "lw"), WALL_W);
  assert.equal(hopSurfaceWidth(fw, centre, "lw"), WALL_W);
  assert.equal(hopSurfaceWidth(centre, centre, "lw"), CENTRE_W);
});

test("hopSurfaceWidth: a CG-audience hop always renders at the CG surface (1920)", () => {
  const cgSlide = { includeSidePanels: true, cg: { camera: {}, style: "positron", highlights: [], churches: [] } };
  assert.equal(hopSurfaceWidth(cgSlide, cgSlide, "cg"), CG_W);
});

test("cgDragDx converts a client-px drag using the DISPLAYED surface width, not authoredWidth", () => {
  // A centre-authored (3840) slide shown in the 7680 full-wall context: the band is bandWidth
  // client px wide but represents surfaceWidth (7680) authored px, not authoredWidth (3840) —
  // using authoredWidth here would move the CG crop at half speed.
  const bandWidth = 960;
  const surfaceWidth = WALL_W;
  assert.equal(cgDragDx(96, surfaceWidth, bandWidth), 768);
  assert.equal(cgDragDx(96, CENTRE_W, bandWidth), 384);
  assert.equal(cgDragDx(10, surfaceWidth, 0), 0);
});
