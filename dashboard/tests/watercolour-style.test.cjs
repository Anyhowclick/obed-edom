const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = require("./helpers/compiled.cjs").maps;
const { buildWatercolourStyle, WATERCOLOUR_PATTERN_IDS, SCRIBBLE_ORIENTS, scribbleStrokes, paperGrainPixels, paperGrainCss } = require(path.join(out, "watercolourStyle.js"));

const base = {
  version: 8,
  sources: { omf: { type: "vector", tiles: ["https://old/{z}/{x}/{y}.pbf"] } },
  layers: [
    { id: "background", type: "background", paint: { "background-pattern": "old" } },
    { id: "water", type: "fill", "source-layer": "water", paint: { "fill-pattern": "old" } },
    { id: "landcover_wood", type: "fill", "source-layer": "landcover" },
    { id: "park", type: "fill", "source-layer": "park", paint: {} },
    { id: "ice", type: "fill", "source-layer": "landcover", paint: {} },
    { id: "building", type: "fill", "source-layer": "building", paint: {} },
    { id: "highway_major_casing", type: "line", "source-layer": "transportation" },
    { id: "highway_major", type: "line", "source-layer": "transportation", paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 5, 2, 10, 4] } },
    { id: "railway", type: "line", "source-layer": "transportation", paint: { "line-width": 2 } },
    { id: "waterway", type: "line", "source-layer": "waterway", paint: { "line-width": 2 } },
    { id: "boundary", type: "line", "source-layer": "boundary", paint: {} },
  ],
};

const EXPECTED_ROAD_OPACITY = [
  "interpolate", ["linear"], ["zoom"],
  10, ["match", ["get", "class"], ["motorway", "trunk", "primary"], 0.75, ["secondary", "tertiary"], 0.3, 0],
  13, ["match", ["get", "class"], ["motorway", "trunk", "primary"], 0.8, ["secondary", "tertiary"], 0.65, 0.12],
  15.5, ["match", ["get", "class"], ["motorway", "trunk", "primary", "secondary", "tertiary"], 0.8, 0.55],
];
const EXPECTED_ROAD_COLOUR = [
  "match", ["get", "class"],
  "motorway", "#C8834A", "trunk", "#C8834A", "primary", "#C8834A",
  "secondary", "#D3A863", "tertiary", "#D3A863",
  "minor", "#CFBA92", "service", "#C9BAA2", "#CFBA92",
];

test("watercolour is semantic, pattern-free, and portable", () => {
  const { style } = buildWatercolourStyle(base, { sourceUrl: "https://tiles.example/planet", glyphsUrl: "https://fonts.example/{fontstack}/{range}.pbf" });
  assert.equal(style.sources.omf.url, "https://tiles.example/planet");
  assert.equal(style.sources.omf.tiles, undefined);
  assert.equal(style.glyphs, "https://fonts.example/{fontstack}/{range}.pbf");
  for (const layer of style.layers) {
    assert.equal(layer.paint?.["background-pattern"], undefined);
    const fillPattern = layer.paint?.["fill-pattern"];
    if (fillPattern !== undefined) assert.ok(WATERCOLOUR_PATTERN_IDS.includes(fillPattern));
  }
  const byId = Object.fromEntries(style.layers.map((layer) => [layer.id, layer]));
  assert.equal(byId.water.paint["fill-color"], "#DCEDF1");
  assert.equal(byId.water.paint["fill-outline-color"], "rgba(70,95,115,0.55)");
  assert.equal(byId.park.paint["fill-color"], "#E7EBCF");
  assert.notEqual(byId.ice.paint["fill-color"], byId.park.paint["fill-color"]);
  assert.equal(byId.building.paint["fill-color"], "#EAD8BE");
  assert.equal(byId.railway.paint["line-color"], "#9E968B");
  assert.equal(byId.waterway.paint["line-color"], "#3d86bd");
  assert.equal(byId.boundary.paint["line-color"], "#8C7A6B");
  assert.deepEqual(byId.boundary.paint["line-dasharray"], [3, 2]);
  assert.deepEqual(byId.highway_major.paint["line-width"], ["interpolate", ["linear"], ["zoom"], 5, 1, 10, 2]);
});

test("land fills are lifted above the hillshade anchor; water and roads stay below it", () => {
  const { style } = buildWatercolourStyle(base);
  const ids = style.layers.map((layer) => String(layer.id));
  const indexOf = (id) => ids.indexOf(id);
  // Mirrors withHillshade's anchor in styles.ts: hillshade splices immediately before the first source-layer "water" layer.
  const anchor = style.layers.findIndex((layer) => layer["source-layer"] === "water");
  assert.ok(anchor >= 0);
  for (const id of [
    "park", "park-scribble", "park-scribble-2", "park-scribble-3",
    "landcover_wood", "landcover_wood-scribble", "landcover_wood-scribble-2", "landcover_wood-scribble-3",
    "ice",
  ]) {
    assert.ok(indexOf(id) < anchor, `${id} should sit before the hillshade anchor`);
  }
  assert.equal(indexOf("water"), anchor);
  for (const id of ["water-scribble", "water-scribble-2", "water-scribble-3", "waterway", "building", "highway_major", "railway"]) {
    assert.ok(indexOf(id) > anchor, `${id} should sit after the hillshade anchor`);
  }
  assert.equal(indexOf("park-scribble"), indexOf("park") + 1);
  assert.equal(indexOf("park-scribble-2"), indexOf("park-scribble") + 1);
  assert.equal(indexOf("park-scribble-3"), indexOf("park-scribble-2") + 1);
  assert.equal(indexOf("landcover_wood-scribble"), indexOf("landcover_wood") + 1);
  assert.equal(indexOf("landcover_wood-scribble-2"), indexOf("landcover_wood-scribble") + 1);
  assert.equal(indexOf("landcover_wood-scribble-3"), indexOf("landcover_wood-scribble-2") + 1);
  assert.equal(indexOf("water-scribble"), indexOf("water") + 1);
  assert.equal(indexOf("water-scribble-2"), indexOf("water-scribble") + 1);
  assert.equal(indexOf("water-scribble-3"), indexOf("water-scribble-2") + 1);
});

test("scribble twins mirror their parent fill", () => {
  const { style } = buildWatercolourStyle(base);
  const byId = Object.fromEntries(style.layers.map((layer) => [layer.id, layer]));
  const twins = [
    ["water", "scribble", "scribble-water"],
    ["water", "scribble-2", "scribble-water-2"],
    ["water", "scribble-3", "scribble-water-3"],
    ["park", "scribble", "scribble-park"],
    ["park", "scribble-2", "scribble-park-2"],
    ["park", "scribble-3", "scribble-park-3"],
    ["landcover_wood", "scribble", "scribble-wood"],
    ["landcover_wood", "scribble-2", "scribble-wood-2"],
    ["landcover_wood", "scribble-3", "scribble-wood-3"],
  ];
  for (const [parentId, suffix, patternId] of twins) {
    const parent = byId[parentId];
    const twin = byId[`${parentId}-${suffix}`];
    assert.ok(twin, `${parentId}-${suffix} should exist`);
    assert.equal(twin.source, parent.source);
    assert.equal(twin["source-layer"], parent["source-layer"]);
    assert.deepEqual(twin.filter, parent.filter);
    assert.deepEqual(Object.keys(twin.paint).sort(), ["fill-opacity", "fill-pattern"]);
    assert.equal(twin.paint["fill-pattern"], patternId);
    assert.ok(WATERCOLOUR_PATTERN_IDS.includes(twin.paint["fill-pattern"]));
  }
});

test("transportation casing layers are dropped; the surviving road gets warm colour and blur", () => {
  const { style } = buildWatercolourStyle(base);
  const casings = style.layers.filter((layer) => layer["source-layer"] === "transportation" && /casing|outline/.test(String(layer.id)));
  assert.equal(casings.length, 0);
  const road = style.layers.find((layer) => layer.id === "highway_major");
  assert.deepEqual(road.paint["line-opacity"], EXPECTED_ROAD_OPACITY);
  assert.deepEqual(road.paint["line-color"], EXPECTED_ROAD_COLOUR);
  assert.equal(road.paint["line-blur"], 0.3);
});

test("cached Positron transforms without undefined style values", () => {
  const cached = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/positron-style-sample.json"), "utf8"));
  const { style } = buildWatercolourStyle(cached);
  const walk = (value) => {
    assert.notEqual(value, undefined);
    if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === "object") Object.values(value).forEach(walk);
  };
  walk(style);
  const ice = style.layers.find((layer) => /ice|glacier/.test(`${layer.id} ${layer["source-layer"] || ""}`));
  assert.equal(ice.paint["fill-color"], "#EEF1F2");
  assert.ok(style.layers.some((layer) => layer.id === "landcover_wood-scribble"));
  const ids = style.layers.map((layer) => String(layer.id));
  const anchor = style.layers.findIndex((layer) => layer["source-layer"] === "water");
  assert.ok(anchor >= 0);
  for (const id of ["park", "park-scribble", "park-scribble-2", "park-scribble-3", "landcover_ice_shelf", "landcover_glacier", "landuse_residential", "landcover_wood", "landcover_wood-scribble", "landcover_wood-scribble-2", "landcover_wood-scribble-3"]) {
    assert.ok(ids.indexOf(id) < anchor, `${id} should sit before the hillshade anchor`);
  }
});

test("scribble orients rotate and flip the spec angles", () => {
  const spec = { angles: [0.3], count: 500, length: 40, width: 2, alpha: 0.4, seed: 5, jitter: 0.08, orients: ["id", "rot90"] };
  const strokes = scribbleStrokes(spec);
  const wrap = (angle) => ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  const near = (target) => strokes.filter((stroke) => Math.abs(wrap(stroke.angle) - wrap(target)) < 0.12).length;
  assert.ok(near(0.3) > 20, "identity family missing");
  assert.ok(near(0.3 + Math.PI / 2) > 20, "rotated family missing");
});

test("water scribble stacks three pattern periods", () => {
  const src = fs.readFileSync(path.join(root, "src/maps/watercolourStyle.ts"), "utf8");
  assert.match(src, /id: "scribble-water"[\s\S]*orients: \[\.\.\.SCRIBBLE_ORIENTS\][\s\S]*size: 1024[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-water-2"[\s\S]*size: 512[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-water-3"[\s\S]*size: 256[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-park"[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-park-2"[\s\S]*size: 1024[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-park-3"[\s\S]*size: 256[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-wood"[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-wood-2"[\s\S]*size: 1024[\s\S]*patchContrast: 0/);
  assert.match(src, /id: "scribble-wood-3"[\s\S]*size: 256[\s\S]*patchContrast: 0/);
  assert.deepEqual(WATERCOLOUR_PATTERN_IDS, [
    "scribble-water",
    "scribble-water-2",
    "scribble-water-3",
    "scribble-park",
    "scribble-park-2",
    "scribble-park-3",
    "scribble-wood",
    "scribble-wood-2",
    "scribble-wood-3",
  ]);
  assert.deepEqual(SCRIBBLE_ORIENTS, ["id", "flipX", "flipY", "rot90", "rot180", "rot270"]);
});

test("patchContrast 0 keeps an even hatch", () => {
  const spec = { angles: [0], count: 80, length: 20, width: 1, alpha: 0.4, seed: 5, patchContrast: 0 };
  const strokes = scribbleStrokes(spec);
  assert.equal(strokes.length, spec.count);
});

test("scribbleStrokes is deterministic, seed-sensitive, and stays near the spec angles", () => {
  const spec = { angles: [0, Math.PI / 4], count: 200, length: 40, width: 2, alpha: 0.4, seed: 5 };
  const a = scribbleStrokes(spec);
  const b = scribbleStrokes(spec);
  assert.deepEqual(a, b);
  const c = scribbleStrokes({ ...spec, seed: 6 });
  assert.notDeepEqual(a, c);
  assert.ok(a.length <= spec.count);
  for (const stroke of a) {
    const nearest = Math.min(...spec.angles.map((angle) => Math.abs(stroke.angle - angle)));
    assert.ok(nearest <= 0.06 + 1e-9, `angle ${stroke.angle} not within jitter of a spec angle`);
  }
});

test("paperGrainPixels is deterministic, seed-sensitive, and seamless at the tile wrap", () => {
  const a = paperGrainPixels(128, 7);
  const b = paperGrainPixels(128, 7);
  assert.deepEqual(a, b);
  const c = paperGrainPixels(128, 8);
  assert.notDeepEqual(a, c);

  const n = 128;
  const red = (x, y) => a[(y * n + x) * 4];
  let interiorSumX = 0, seamSumX = 0;
  let interiorSumY = 0, seamSumY = 0;
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n - 1; x++) interiorSumX += Math.abs(red(x, y) - red(x + 1, y));
    seamSumX += Math.abs(red(n - 1, y) - red(0, y));
  }
  for (let x = 0; x < n; x++) {
    for (let y = 0; y < n - 1; y++) interiorSumY += Math.abs(red(x, y) - red(x, y + 1));
    seamSumY += Math.abs(red(x, n - 1) - red(x, 0));
  }
  const interiorMeanX = interiorSumX / (n * (n - 1));
  const seamMeanX = seamSumX / n;
  const interiorMeanY = interiorSumY / (n * (n - 1));
  const seamMeanY = seamSumY / n;
  assert.ok(seamMeanX <= interiorMeanX * 1.4, `x-wrap seam ${seamMeanX} exceeds 1.4x interior ${interiorMeanX}`);
  assert.ok(seamMeanY <= interiorMeanY * 1.4, `y-wrap seam ${seamMeanY} exceeds 1.4x interior ${interiorMeanY}`);
});

test("paperGrainPixels has no low-frequency mottle: block means barely vary vs per-pixel noise", () => {
  const n = 128;
  const pixels = paperGrainPixels(n, 7);
  const red = (x, y) => pixels[(y * n + x) * 4];
  const values = [];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) values.push(red(x, y));
  const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
  const pixelSpread = Math.sqrt(values.reduce((sum, v) => sum + (v - mean) * (v - mean), 0) / values.length);

  const block = 16;
  const blockMeans = [];
  for (let by = 0; by < n; by += block) {
    for (let bx = 0; bx < n; bx += block) {
      let sum = 0;
      for (let y = by; y < by + block; y++) for (let x = bx; x < bx + block; x++) sum += red(x, y);
      blockMeans.push(sum / (block * block));
    }
  }
  const blockMean = blockMeans.reduce((sum, v) => sum + v, 0) / blockMeans.length;
  const blockSpread = Math.sqrt(blockMeans.reduce((sum, v) => sum + (v - blockMean) * (v - blockMean), 0) / blockMeans.length);

  assert.ok(blockSpread < pixelSpread * 0.35, `block spread ${blockSpread} not well below pixel spread ${pixelSpread}`);
});

test("paperGrainCss scales the 1024 authored-px tile by the preview/authored ratio", () => {
  assert.deepEqual(paperGrainCss(7680, 7680), { backgroundSize: "1024px 1024px", backgroundPosition: "0px 0px" });
  assert.deepEqual(paperGrainCss(3840, 7680), { backgroundSize: "512px 512px", backgroundPosition: "0px 0px" });
  assert.deepEqual(paperGrainCss(1920, 1920), { backgroundSize: "1024px 1024px", backgroundPosition: "0px 0px" });
});

// Every export path (full wall, centre-only, CG crop) composites the grain onto its own output
// canvas starting at that canvas's local (0,0), regardless of the authored-space region it depicts.
// The preview must therefore always anchor at "0px 0px" too, never at an authored offset like
// CG_ORIGIN — only the tile's scale (ratio of preview to authored width) differs per surface.
test("paperGrainCss anchors at local (0,0) for full-wall, centre-only, and CG-crop surfaces alike", () => {
  const fullWall = paperGrainCss(7680, 7680);
  const centreOnly = paperGrainCss(3840, 3840);
  const cgCrop = paperGrainCss(1920, 1920);
  assert.equal(fullWall.backgroundPosition, "0px 0px");
  assert.equal(centreOnly.backgroundPosition, "0px 0px");
  assert.equal(cgCrop.backgroundPosition, "0px 0px");
  assert.equal(fullWall.backgroundSize, "1024px 1024px");
  assert.equal(centreOnly.backgroundSize, "1024px 1024px");
  assert.equal(cgCrop.backgroundSize, "1024px 1024px");
});
