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
  assert.equal(stops[3], -2);
  assert.equal(stops[5], 22);
  assert.equal(stops.length, 7);
  return { zMin: stops[4], zMax: stops[6] };
}

test("zoomScaledStops folds a non-scaling feature to the same value at both stops", () => {
  const { zMin, zMax } = stopValues(zoomScaledStops(["get", "base"]));
  assert.deepEqual(zMin, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", -2, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
  assert.deepEqual(zMax, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", 22, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
});

test("zoomScaledStops keeps a per-integer clamped ramp over the whole -2..22 range", () => {
  const stops = zoomScaledStops(["get", "base"], 1024);
  assert.equal(stops[3], -2);
  assert.equal(stops[stops.length - 2], 22);
  assert.equal(stops.length, 3 + 2 * 25);
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

test("zoomScaledStops stays exact at the wall-export zoom -2", () => {
  // Wall (7680) exports render at authored zoom + exportZoomDelta(7680) === -2.
  const base = 40;
  const sizeZoomRef = 3;
  const evaluate = evaluateIconSize(base, { sizeZoomRef, scaleWithMap: true });
  assert.ok(Math.abs(evaluate(-2) - base * Math.pow(2, -2 - sizeZoomRef)) < 1e-9);
  assert.ok(Math.abs(evaluate(-1.5) - base * Math.pow(2, -1.5 - sizeZoomRef)) < 1e-9);
  assert.ok(Math.abs(evaluate(-0.5) - base * Math.pow(2, -0.5 - sizeZoomRef)) < 1e-9);
});

test("a default scaling dot at wall-export zoom -2 renders its analytic size, not the zoom-0 value", () => {
  // objectScale 0.25 with sizeZoomRef adjusted by log2(objectScale) (see churchesGeo).
  const objectScale = 0.25;
  const size = 28;
  const sizeZoom = 0;
  const sizeZoomRef = sizeZoom + Math.log2(objectScale);
  const expr = zoomScaledStops(["*", 0.5, ["get", "size"], ["get", "objectScale"]], 1024);
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const props = { size, objectScale, scaleWithMap: true, sizeZoomRef };
  const analytic = (z) => 0.5 * size * objectScale * Math.pow(2, z - sizeZoomRef);
  for (const z of [-2, -1.5, -1, 0]) {
    assert.ok(Math.abs(parsed.value.evaluate({ zoom: z }, { properties: props }) - analytic(z)) < 1e-9, `z=${z}`);
  }
  // Rendered radius at the export zoom, versus the 4x value a zoom-0 first stop would clamp to.
  assert.ok(Math.abs(parsed.value.evaluate({ zoom: -2 }, { properties: props }) - 0.5 * size * objectScale) < 1e-9);
  assert.ok(Math.abs(analytic(0) - 4 * analytic(-2)) < 1e-9);
});

test("landmark icon-size at zoom >= 0 is unchanged by the widened stop range", () => {
  const base = ["/", ["*", ["coalesce", ["get", "size"], 120], ["get", "objectScale"]], ["max", 1, ["get", "assetRenderWidth"]]];
  const parsed = createExpression(zoomScaledStops(base), { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const props = { size: 480, objectScale: 1, assetRenderWidth: 960, scaleWithMap: true, sizeZoomRef: 6 };
  for (const z of [0, 1, 5.5, 6, 12, 22]) {
    const expected = (480 / 960) * Math.pow(2, z - 6);
    assert.ok(Math.abs(parsed.value.evaluate({ zoom: z }, { properties: props }) - expected) < 1e-9, `z=${z}`);
  }
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
const { churchesGeo, churchesLayers, labelPillBucket, labelPillCssSize, LABEL_FONT_PX, LABEL_GAP_EMS, LABEL_CHAR_W_PX, LABEL_PILL_BUCKETS, DROP_PIN_SELECTED_SCALE } = require(path.join(overlaysOut, "overlays.js"));
const { defaultLandmarkSize, ICON_SIZE_PACK_MAX } = require(path.join(overlaysOut, "objects.js"));

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
  const DROP_PIN_HEAD_PX = 50;
  const expr = churchesLayers().find((item) => item.id === "churches-drops").layout["icon-size"];
  assert.equal((expr.length - 3) / 2, 25, "one stop per integer zoom so MapLibre cannot pack z=22 into the 255 ceiling");
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const evaluate = (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
  const size = 100;
  const sizeZoomRef = 8;
  const base = size / DROP_PIN_HEAD_PX;
  assert.equal(evaluate(8, { size, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }), base);
  assert.equal(evaluate(9, { size, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }), base * 2);
  assert.equal(evaluate(8, { size, objectScale: 1, sel: true, scaleWithMap: true, sizeZoomRef }), base * 1.08);
  assert.equal(evaluate(9, { size, objectScale: 1, sel: false, scaleWithMap: false, sizeZoomRef }), base);
  assert.ok(evaluate(8, { size: 200, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }) > evaluate(8, { size, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef }));
  assert.ok(evaluate(22, { size: 4000, objectScale: 1, sel: false, scaleWithMap: true, sizeZoomRef: 0 }) <= ICON_SIZE_PACK_MAX);

  const style = {
    version: 8,
    name: "x",
    sources: { src: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
    layers: [{ id: "l", type: "symbol", source: "src", layout: { "icon-image": "x", "icon-size": expr } }],
  };
  assert.deepEqual(validateStyleMin(style), []);
});

test("churches-landmarks icon-size is pack-safe like drops, so a scaleWithMap slider stays live", () => {
  const expr = churchesLayers().find((item) => item.id === "churches-landmarks").layout["icon-size"];
  assert.equal((expr.length - 3) / 2, 25);
  const parsed = createExpression(expr, { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  const evaluate = (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
  const props = { size: 480, objectScale: 1, assetRenderWidth: 960, scaleWithMap: true, sizeZoomRef: 6 };
  assert.ok(evaluate(6, props) < evaluate(6, { ...props, size: 960 }));
  assert.ok(evaluate(22, { ...props, size: 4000, sizeZoomRef: 0 }) <= ICON_SIZE_PACK_MAX);
});

test("churches-labels bake the name into a measured pill, not icon-text-fit", () => {
  const layer = churchesLayers().find((item) => item.id === "churches-labels");
  assert.equal(layer.layout["text-field"], "");
  assert.equal(layer.layout["icon-text-fit"], "none");
  assert.deepEqual(layer.layout["icon-image"], ["get", "labelPill"]);
  assert.ok(layer.layout["icon-offset"]);
  assert.ok(!layer.layout["text-offset"]);
});

test("labelPillCssSize matches Keynote's 13px-per-char box plus pads", () => {
  const box = labelPillCssSize("CHC Medan", 1);
  assert.equal(box.w, LABEL_CHAR_W_PX * "CHC Medan".length + 12);
  assert.equal(box.h, 32 + 4);
  const cathedral = labelPillCssSize("Cathedral of Immaculate Conception", 1);
  assert.equal(cathedral.w, 420 + 12);
});

test("churchesGeo emits labelScale and one labelOffset per integer zoom", () => {
  const church = { id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size: 128 };
  const geo = churchesGeo([church], null, false, 1);
  const props = geo.features[0].properties;
  assert.equal(typeof props.labelScale, "number");
  for (let zoom = -2; zoom <= 22; zoom++) {
    const offset = props[`labelOffset${zoom}`];
    assert.ok(Array.isArray(offset), `labelOffset${zoom}`);
    assert.equal(offset.length, 2);
    assert.equal(offset[0], 0);
    assert.ok(offset[1] < 0);
  }
});

test("churchesGeo defaults labelOpacity to opacity, and the labels layer reads labelOpacity", () => {
  const withOpacity = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dot", color: "#fff", opacity: 0.4 }], null, false, 1);
  assert.equal(withOpacity.features[0].properties.labelOpacity, 0.4);
  const withBoth = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dot", color: "#fff", opacity: 0.4, labelOpacity: 0.7 }], null, false, 1);
  assert.equal(withBoth.features[0].properties.labelOpacity, 0.7);
  const layer = churchesLayers().find((item) => item.id === "churches-labels");
  assert.deepEqual(layer.paint["icon-opacity"], ["coalesce", ["get", "labelOpacity"], 1]);
  assert.ok(!layer.paint["text-opacity"]);
});

test("a church with no showLabel is showLabel: false in churchesGeo", () => {
  const church = { id: "a", name: "a", lat: 0, lon: 0, kind: "dot", color: "#fff" };
  const geo = churchesGeo([church], null, false, 1);
  assert.equal(geo.features[0].properties.showLabel, false);
});

test("labelOffset in icon pixels clears a non-scaling dropPin of either authored size", () => {
  const small = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size: 64 }], null, false, 1);
  const large = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size: 256 }], null, false, 1);
  const iconSize = labelIconSize();
  for (const geo of [small, large]) {
    const props = geo.features[0].properties;
    const size = props.size;
    const screen = -props.labelOffset0[1] * iconSize(0, props);
    assert.ok(props.labelOffset0[1] < 0);
    assert.ok(screen > size * 1.45);
  }
});

test("a grouped pin and dot at the same size share labelScale so text and pill match", () => {
  const size = 84;
  const pin = churchesGeo([{ id: "p", name: "Pin", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size }], null, false, 1);
  const dot = churchesGeo([{ id: "d", name: "Dot", lat: 0, lon: 0, kind: "dot", color: "#fff", size }], null, false, 1);
  assert.equal(pin.features[0].properties.labelScale, size / 64);
  assert.equal(dot.features[0].properties.labelScale, pin.features[0].properties.labelScale);
  assert.equal(pin.features[0].properties.labelBucket, dot.features[0].properties.labelBucket);
});

test("a landmark's labelScale is 1 at the size it is created at, defaultLandmarkSize(assetWidth)", () => {
  const baseline = defaultLandmarkSize(600);
  const one = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "landmark", color: "#fff", assetWidth: 600, size: baseline }], null, false, 1);
  const two = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "landmark", color: "#fff", assetWidth: 600, size: baseline * 2 }], null, false, 1);
  assert.equal(one.features[0].properties.labelScale, 1);
  assert.equal(two.features[0].properties.labelScale, 2);
});

test("a size-less landmark labels at 1x, so the preview matches _pin_size on the export side", () => {
  const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "landmark", color: "#fff", assetWidth: 600 }], null, false, 1);
  assert.equal(geo.features[0].properties.labelScale, 1);
});

test("labelOffset clears a non-scaling marker past the icon-size clamp", () => {
  const size = 64 * 16;
  const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size }], null, false, 1);
  const props = geo.features[0].properties;
  assert.equal(props.labelScale, 8);
  const screen = -props.labelOffset0[1] * labelIconSize()(0, props);
  assert.ok(screen > size * 1.45);
});

function labelIconOffset() {
  const layer = churchesLayers().find((item) => item.id === "churches-labels");
  const parsed = createExpression(layer.layout["icon-offset"], {
    type: "array",
    value: "number",
    length: 2,
    "property-type": "data-driven",
    expression: { interpolated: true, parameters: ["zoom", "feature"] },
  });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  return (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
}

// A scaleWithMap marker keeps growing with zoom while icon-size clamps at 8x the bake bucket,
// so the label's icon-pixel offset has to grow with it. Marker top, pill bottom and the gap
// are all in screen px above the feature's anchor (offset * icon-size).
test("the label pill clears a scaleWithMap marker at and past the 8x icon-size clamp", () => {
  const ref = 8;
  const iconSize = labelIconSize();
  const offsetAt = labelIconOffset();
  const cases = [
    { kind: "dot", church: { size: 28 }, markerPx: 28 / 2 },
    { kind: "dropPin", church: { size: 100 }, markerPx: 100 * 1.45 },
    { kind: "landmark", church: { size: 480, assetWidth: 600, assetHeight: 300 }, markerPx: 480 * (300 / 600) },
  ];
  for (const { kind, church, markerPx } of cases) {
    const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, color: "#fff", kind, scaleWithMap: true, sizeZoom: ref, ...church }], null, false, 1);
    const props = geo.features[0].properties;
    for (const zoom of [ref, ref + 3, ref + 3.5, ref + 4]) {
      const size = iconSize(zoom, props);
      const markerTop = markerPx * Math.pow(2, zoom - ref);
      const pillBottom = -offsetAt(zoom, props)[1] * size;
      assert.ok(pillBottom >= markerTop - 1e-9, `${kind} z=${zoom}: pill bottom ${pillBottom} < marker top ${markerTop}`);
      const clearance = pillBottom - markerTop;
      const textPx = size * LABEL_FONT_PX;
      assert.ok(clearance >= LABEL_GAP_EMS * textPx - 1e-9, `${kind} z=${zoom}: clearance ${clearance}`);
      assert.ok(clearance <= LABEL_GAP_EMS * textPx + 0.05 * markerTop + 1, `${kind} z=${zoom}: clearance ${clearance}`);
    }
  }
});

test("a non-scaling label keeps one offset at every zoom", () => {
  const offsetAt = labelIconOffset();
  const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size: 100 }], null, false, 1);
  const props = geo.features[0].properties;
  for (const zoom of [-2, 0, 8, 14, 22]) {
    assert.ok(Math.abs(offsetAt(zoom, props)[1] - offsetAt(0, props)[1]) < 1e-9, `z=${zoom}`);
  }
});

function labelIconSize() {
  const layer = churchesLayers().find((item) => item.id === "churches-labels");
  const parsed = createExpression(layer.layout["icon-size"], { type: "number" });
  assert.equal(parsed.result, "success", JSON.stringify(parsed.value));
  return (zoom, properties) => parsed.value.evaluate({ zoom }, { properties });
}

test("churches-labels icon-size clamps the total scale to 0.5x..8x", () => {
  const evaluate = labelIconSize();
  const props = { labelScale: 1, objectScale: 1, scaleWithMap: true, sizeZoomRef: 8 };
  assert.equal(evaluate(8, props), 1);
  assert.equal(evaluate(9, props), 2);
  assert.equal(evaluate(6, props), 0.5);
  assert.equal(evaluate(12, props), 8);
});

test("churches-labels icon-size clamps a non-scaling feature's authored size too", () => {
  const evaluate = labelIconSize();
  assert.equal(evaluate(8, { labelScale: 0.25, objectScale: 1, scaleWithMap: false, sizeZoomRef: 0 }), 0.5);
  assert.equal(evaluate(8, { labelScale: 16, objectScale: 1, scaleWithMap: false, sizeZoomRef: 0 }), 8);
});

test("labelPillBucket snaps to the nearest registered variant in log2, bounding the error at sqrt(2)", () => {
  assert.equal(labelPillBucket(0.5), 0.5);
  assert.equal(labelPillBucket(0.9), 1);
  assert.equal(labelPillBucket(1), 1);
  assert.equal(labelPillBucket(1.4), 1);
  assert.equal(labelPillBucket(1.5), 2);
  assert.equal(labelPillBucket(1.9), 2);
  assert.equal(labelPillBucket(3.5), 4);
  assert.equal(labelPillBucket(8), 8);
});

test("churchesGeo emits a labelBucket naming a registered pill image", () => {
  for (const [size, bucket] of [[16, "0.5"], [64, "1"], [200, "4"], [4000, "8"]]) {
    const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size }], null, false, 1);
    assert.equal(geo.features[0].properties.labelBucket, bucket);
    assert.ok(LABEL_PILL_BUCKETS.map(String).includes(geo.features[0].properties.labelBucket));
    assert.match(geo.features[0].properties.labelPill, /ee220c$/);
  }
});

test("churchesGeo folds objectScale into labelBucket, halving it on a 0.5x wall-width surface", () => {
  const church = { id: "a", name: "a", lat: 0, lon: 0, kind: "dropPin", color: "#fff", size: 64 };
  const unscaled = churchesGeo([church], null, false, 1);
  const halved = churchesGeo([church], null, false, 0.5);
  assert.equal(unscaled.features[0].properties.labelBucket, "1");
  assert.equal(halved.features[0].properties.labelBucket, "0.5");
});

// The offsets only guarantee clearance if the analytic per-segment dip is exact, so sweep the
// rendered geometry finely rather than at the handful of zooms the clamp knee happens to land on.
function assertPillClears(church, markerHeightPx, zooms, ref) {
  const iconSize = labelIconSize();
  const offsetAt = labelIconOffset();
  const geo = churchesGeo([{ id: "a", name: "a", lat: 0, lon: 0, color: "#fff", scaleWithMap: true, sizeZoom: ref, ...church }], null, false, 1);
  const props = geo.features[0].properties;
  for (const zoom of zooms) {
    const size = iconSize(zoom, props);
    const markerTop = markerHeightPx * Math.pow(2, zoom - ref);
    const pillBottom = -offsetAt(zoom, props)[1] * size;
    const textPx = size * LABEL_FONT_PX;
    assert.ok(pillBottom >= markerTop - 1e-9, `${church.kind} z=${zoom}: pill bottom ${pillBottom} < marker top ${markerTop}`);
    assert.ok(pillBottom - markerTop >= LABEL_GAP_EMS * textPx - 1e-9, `${church.kind} z=${zoom}: clearance ${pillBottom - markerTop}`);
  }
}

test("the label pill clears the marker when the text-size clamp lands mid-segment", () => {
  const ref = 8;
  // totalScale * 2^(z-ref) === 8 at z === ref + knee, i.e. totalScale === 2^(3 - knee).
  for (const knee of [3.25, 3.5, 3.75]) {
    const scale = Math.pow(2, 3 - knee);
    const zooms = [];
    for (let step = 0; step <= 500; step++) zooms.push(ref + step / 100);
    assertPillClears({ kind: "dropPin", size: 64 * scale }, 64 * scale * 1.45, zooms, ref);
    assertPillClears({ kind: "dot", size: 28 * scale }, (28 * scale) / 2, zooms, ref);
  }
});

test("the label pill clears a tall portrait landmark across a dense zoom sweep", () => {
  const ref = 8;
  const size = defaultLandmarkSize(100);
  const zooms = [];
  for (let step = 0; step <= 500; step++) zooms.push(ref + step / 100);
  assertPillClears({ kind: "landmark", size, assetWidth: 100, assetHeight: 600 }, (size * 600) / 100, zooms, ref);
});

test("the label pill clears dot, dropPin and landmark at every 0.01 zoom step over ref..ref+5", () => {
  const ref = 8;
  const zooms = [];
  for (let step = 0; step <= 500; step++) zooms.push(ref + step / 100);
  assertPillClears({ kind: "dot", size: 28 }, 28 / 2, zooms, ref);
  assertPillClears({ kind: "dropPin", size: 100 }, 100 * 1.45, zooms, ref);
  assertPillClears({ kind: "landmark", size: 480, assetWidth: 600, assetHeight: 300 }, 480 * (300 / 600), zooms, ref);
});

// A selected drop pin's icon is enlarged by DROP_PIN_SELECTED_SCALE (see churchesLayers'
// churches-icons icon-size), so its rendered marker top is DROP_PIN_SELECTED_SCALE taller than
// an unselected pin's. markerHeightPx must fold that into the label offset or the pill sits over
// the enlarged marker once the text-size clamp is crossed.
function assertSelectedPillClears(church, markerHeightPx, zooms, ref) {
  const iconSize = labelIconSize();
  const offsetAt = labelIconOffset();
  const id = "selected";
  const geo = churchesGeo([{ id, name: "a", lat: 0, lon: 0, color: "#fff", scaleWithMap: true, sizeZoom: ref, ...church }], id, false, 1);
  const props = geo.features[0].properties;
  assert.equal(props.sel, true);
  for (const zoom of zooms) {
    const size = iconSize(zoom, props);
    const markerTop = markerHeightPx * DROP_PIN_SELECTED_SCALE * Math.pow(2, zoom - ref);
    const pillBottom = -offsetAt(zoom, props)[1] * size;
    const textPx = size * LABEL_FONT_PX;
    assert.ok(pillBottom >= markerTop - 1e-9, `z=${zoom}: pill bottom ${pillBottom} < marker top ${markerTop}`);
    assert.ok(pillBottom - markerTop >= LABEL_GAP_EMS * textPx - 1e-9, `z=${zoom}: clearance ${pillBottom - markerTop}`);
  }
}

test("the label pill clears a selected drop pin's enlarged marker across the text-size clamp", () => {
  const ref = 8;
  const zooms = [];
  for (let step = 0; step <= 500; step++) zooms.push(ref + step / 100);
  assertSelectedPillClears({ kind: "dropPin", size: 100 }, 100 * 1.45, zooms, ref);
  // Also sweep a knee landing mid-segment, as with the unselected clamp test above.
  for (const knee of [3.25, 3.5, 3.75]) {
    const scale = Math.pow(2, 3 - knee);
    assertSelectedPillClears({ kind: "dropPin", size: 64 * scale }, 64 * scale * 1.45, zooms, ref);
  }
});
