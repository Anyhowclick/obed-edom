const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { buildBorderlandsStyle } = require(path.join(out, "borderlandsStyle.js"));

const base = {
  version: 8,
  sources: { omf: { type: "vector", tiles: ["https://old/{z}/{x}/{y}.pbf"] } },
  layers: [
    { id: "background", type: "background", paint: { "background-pattern": "old" } },
    { id: "park", type: "fill", source: "omf", "source-layer": "park", paint: {} },
    { id: "landcover_wood", type: "fill", source: "omf", "source-layer": "landcover", paint: {} },
    { id: "landcover_grass", type: "fill", source: "omf", "source-layer": "landcover", paint: {} },
    { id: "road_area_pattern", type: "fill", source: "omf", "source-layer": "transportation", paint: { "fill-pattern": "old" } },
    { id: "water", type: "fill", source: "omf", "source-layer": "water", paint: {} },
    { id: "building", type: "fill", source: "omf", "source-layer": "building", paint: {} },
    {
      id: "building-3d",
      type: "fill-extrusion",
      source: "omf",
      "source-layer": "building",
      paint: { "fill-extrusion-color": "#ccc", "fill-extrusion-opacity": 0.8, "fill-extrusion-height": ["get", "render_height"] },
    },
    { id: "highway_major_casing", type: "line", source: "omf", "source-layer": "transportation", paint: { "line-width": 4, "line-blur": 0.4 } },
    { id: "highway_major", type: "line", source: "omf", "source-layer": "transportation", paint: { "line-width": 2, "line-blur": 0.3 } },
    { id: "boundary", type: "line", source: "omf", "source-layer": "boundary", paint: { "line-dasharray": [1, 1] } },
    { id: "label_city", type: "symbol", source: "omf", "source-layer": "place", layout: { "text-font": ["Noto Sans Regular"] }, paint: {} },
  ],
};

test("borderlands is cel-flat, inky, and keeps 3D extrusions", () => {
  const { style } = buildBorderlandsStyle(base, { sourceUrl: "https://tiles.example/planet", glyphsUrl: "https://fonts.example/{fontstack}/{range}.pbf" });
  assert.equal(style.sources.omf.url, "https://tiles.example/planet");
  assert.equal(style.sources.omf.tiles, undefined);
  assert.equal(style.glyphs, "https://fonts.example/{fontstack}/{range}.pbf");
  for (const layer of style.layers) {
    assert.equal(layer.paint?.["background-pattern"], undefined);
    assert.equal(layer.paint?.["fill-pattern"], undefined);
    assert.equal(layer.paint?.["line-blur"], undefined);
  }
  const byId = Object.fromEntries(style.layers.map((layer) => [layer.id, layer]));
  assert.equal(byId.background.paint["background-color"], "#E8E4D8");
  assert.equal(byId.water.paint["fill-color"], "#6B91A0");
  assert.equal(byId.park.paint["fill-color"], "#6A7B5C");
  assert.equal(byId.landcover_grass.paint["fill-color"], "#6A7B5C");
  assert.equal(byId.landcover_wood.paint["fill-color"], "#3F5346");
  assert.equal(byId.road_area_pattern.paint["fill-color"], "#E8E4D8");
  assert.equal(byId.road_area_pattern.paint["fill-pattern"], undefined);
  assert.equal(byId.building.paint["fill-outline-color"], undefined);
  assert.equal(byId["building-3d"].paint["fill-extrusion-color"], "#D5D0C6");
  assert.equal(byId["building-3d"].paint["fill-extrusion-opacity"], 1);
  assert.equal(byId["building-3d"].paint["fill-extrusion-vertical-gradient"], false);
  assert.deepEqual(byId["building-3d"].paint["fill-extrusion-height"], ["get", "render_height"]);
  assert.equal(byId["building-ink"], undefined);
  assert.equal(byId.highway_major_casing.paint["line-color"], "#141312");
  assert.equal(byId.highway_major.paint["line-color"], "#F3F1EB");
  assert.equal(byId.boundary.paint["line-dasharray"], undefined);
  assert.equal(byId.label_city.paint["text-color"], "#141312");
  assert.deepEqual(byId.label_city.layout["text-font"], ["Noto Sans Bold"]);
});

test("transportation casings stay black without ballooning at low zoom", () => {
  const { style } = buildBorderlandsStyle(base);
  const casing = style.layers.find((layer) => layer.id === "highway_major_casing");
  assert.equal(casing.paint["line-color"], "#141312");
  assert.equal(casing.paint["line-width"], 4.6);
});
