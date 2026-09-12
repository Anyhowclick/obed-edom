const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { createExpression, validateStyleMin } = require("@maplibre/maplibre-gl-style-spec");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-icon-size-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/objects.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { zoomScaledStops } = require(path.join(out, "objects.js"));

function stopValues(stops) {
  assert.equal(stops[0], "interpolate");
  assert.deepEqual(stops[1], ["exponential", 2]);
  assert.deepEqual(stops[2], ["zoom"]);
  return { z0: stops[4], z22: stops[6] };
}

test("zoomScaledStops folds a non-scaling feature to the same value at both stops", () => {
  const { z0, z22 } = stopValues(zoomScaledStops(["get", "base"]));
  assert.deepEqual(z0, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", 0, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
  assert.deepEqual(z22, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", 22, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
});

function evaluateIconSize(base, properties) {
  const expr = zoomScaledStops(base);
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const feature = { properties };
  return (zoom) => parsed.value.evaluate({ zoom }, feature);
}

test("zoomScaledStops is exactly geometric (base 2) for a scaleWithMap feature", () => {
  const base = 40;
  const sizeZoomRef = 5;
  const evaluate = evaluateIconSize(base, { sizeZoomRef, scaleWithMap: true });
  assert.equal(evaluate(3), base * 0.25);
  assert.equal(evaluate(5), base * 1);
  assert.equal(evaluate(6), base * 2);
  assert.ok(Math.abs(evaluate(7.3) - base * Math.pow(2, 2.3)) < 1e-9);
  assert.equal(evaluate(22), base * 131072);
});

test("zoomScaledStops as icon-size validates with the real maplibre style spec", () => {
  const style = {
    version: 8,
    name: "x",
    sources: { src: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
    layers: [
      { id: "l", type: "symbol", source: "src", layout: { "icon-image": "x", "icon-size": zoomScaledStops(["get", "base"]) } },
    ],
  };
  assert.deepEqual(validateStyleMin(style), []);
});

test("zoomScaledStops holds a scaleWithMap:false feature constant at every zoom", () => {
  const base = 40;
  const evaluate = evaluateIconSize(base, { scaleWithMap: false });
  for (const zoom of [3, 5, 6, 7.3, 22]) {
    assert.equal(evaluate(zoom), base);
  }
});

const overlaysOut = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-icon-size-full-"));
const overlaysCompile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", overlaysOut, path.join(root, "src/maps/overlays.ts"), path.join(root, "src/maps/objects.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(overlaysCompile.status, 0, overlaysCompile.stderr || overlaysCompile.stdout);
const { churchesGeo, churchesLayers } = require(path.join(overlaysOut, "overlays.js"));

test("churchesLayers (churches-dots/-drops/-landmarks) validates with the real maplibre style spec", () => {
  const style = {
    version: 8,
    name: "x",
    sources: { churches: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
    layers: churchesLayers(),
  };
  assert.deepEqual(validateStyleMin(style), []);
});

test("churchesGeo folds sizeZoom and log2(objectScale) into sizeZoomRef", () => {
  const church = { id: "a", name: "a", lat: 0, lon: 0, kind: "landmark", color: "#fff", scaleWithMap: true, sizeZoom: 5 };
  const geo = churchesGeo([church], null, false, 4);
  assert.equal(geo.features[0].properties.sizeZoomRef, 5 + 2);
  assert.equal(geo.features[0].properties.scaleWithMap, true);
});

test("churches-dots circle-radius is exactly geometric (base 2) for a scaleWithMap dot and validates with the style spec", () => {
  const expr = zoomScaledStops(["*", 0.5, ["get", "size"], ["get", "objectScale"]], 1024);
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const evaluate = (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
  const size = 28;
  const sizeZoomRef = 8;
  assert.equal(evaluate(8, { size, objectScale: 1, scaleWithMap: true, sizeZoomRef }), 0.5 * size);
  assert.equal(evaluate(11, { size, objectScale: 1, scaleWithMap: true, sizeZoomRef }), 0.5 * size * 8);
  assert.equal(evaluate(5, { size, objectScale: 1, scaleWithMap: true, sizeZoomRef }), 0.5 * size * 0.125);
  assert.equal(evaluate(11, { size, objectScale: 1, scaleWithMap: false, sizeZoomRef }), 0.5 * size);
  // Past the clamp threshold (0.5*size*2^(z-ref) > 1024) the radius flattens at 1024.
  assert.equal(evaluate(20, { size, objectScale: 1, scaleWithMap: true, sizeZoomRef }), 1024);

  const style = {
    version: 8,
    name: "x",
    sources: { src: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
    layers: [{ id: "l", type: "circle", source: "src", paint: { "circle-radius": expr } }],
  };
  assert.deepEqual(validateStyleMin(style), []);
});

test("churches-drops icon-size scales geometrically off the drop-pin head px and validates with the style spec", () => {
  const DROP_PIN_HEAD_PX = 17;
  const expr = zoomScaledStops(["*", ["case", ["boolean", ["get", "sel"], false], 1.08, 1], ["get", "size"], ["get", "objectScale"], 1 / DROP_PIN_HEAD_PX]);
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const evaluate = (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
  const size = 64;
  const sizeZoomRef = 8;
  const base = size / DROP_PIN_HEAD_PX;
  assert.equal(evaluate(8, { size, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }), base);
  assert.equal(evaluate(9, { size, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }), base * 2);
  assert.equal(evaluate(8, { size, objectScale: 1, sel: true, scaleWithMap: true, sizeZoomRef }), base * 1.08);
  assert.equal(evaluate(9, { size, objectScale: 1, sel: false, scaleWithMap: false, sizeZoomRef }), base);

  const style = {
    version: 8,
    name: "x",
    sources: { src: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
    layers: [{ id: "l", type: "symbol", source: "src", layout: { "icon-image": "x", "icon-size": expr } }],
  };
  assert.deepEqual(validateStyleMin(style), []);
});
