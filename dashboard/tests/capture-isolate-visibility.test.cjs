const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { isolatePairBaseVisibility, isolatePairCutoutVisibility, setHighlightOpacity } = require(path.join(out, "captureIsolateVisibility.js"));

function fakeMap(layers) {
  const calls = [];
  return {
    calls,
    getLayer: (id) => (layers.includes(id) ? { id } : undefined),
    setPaintProperty: (id, prop, value) => calls.push(["setPaintProperty", id, prop, value]),
    setLayoutProperty: (id, prop, value) => calls.push(["setLayoutProperty", id, prop, value]),
  };
}

const ALL_LAYERS = ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line", "isolate-fill"];

test("setHighlightOpacity(0) pins every present highlight layer flat, skipping absent ones", () => {
  const map = fakeMap(["admin0-fill", "admin0-line"]);
  setHighlightOpacity(map, 0, ["USA"]);
  assert.deepEqual(map.calls, [
    ["setPaintProperty", "admin0-fill", "fill-opacity", 0],
    ["setPaintProperty", "admin0-line", "line-opacity", 0],
  ]);
});

test("setHighlightOpacity(null) restores authored expressions, admin1 via admin1PaintExpression", () => {
  const map = fakeMap(ALL_LAYERS);
  setHighlightOpacity(map, null, ["A1:MYS-1186"]);
  assert.equal(map.calls.length, 4);
  const [admin0Fill, admin0Line, admin1Fill, admin1Line] = map.calls;
  assert.equal(admin0Fill[1], "admin0-fill");
  assert.ok(!JSON.stringify(admin0Fill[3]).includes("MYS-1186"), "admin0 opacity must not depend on adm1_code ids");
  assert.equal(admin1Fill[1], "admin1-fill");
  assert.deepEqual(admin1Fill[3][1][2], ["literal", ["MYS-1186"]]);
  assert.equal(admin1Line[1], "admin1-line");
  assert.deepEqual(admin1Line[3][1][2], ["literal", ["MYS-1186"]]);
});

test("isolatePairBaseVisibility always hides the highlight layers, isolate on or off", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairBaseVisibility(map, ["USA"]);
  const paint = map.calls.filter((c) => c[0] === "setPaintProperty");
  const layout = map.calls.filter((c) => c[0] === "setLayoutProperty");
  assert.deepEqual(
    paint.map((c) => c[1]),
    ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line"]
  );
  assert.ok(paint.every((c) => c[3] === 0));
  assert.deepEqual(
    layout.map((c) => [c[1], c[3]]),
    [
      ["admin0-fill", "none"],
      ["admin0-line", "none"],
      ["admin1-fill", "none"],
      ["admin1-line", "none"],
    ]
  );
});

test("cutout: isolate-fill is hidden first, then highlights restore to authored expressions", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairCutoutVisibility(map, ["A1:MYS-1186"]);
  assert.equal(map.calls[0][0], "setLayoutProperty");
  assert.equal(map.calls[0][1], "isolate-fill");
  const paint = map.calls.filter((c) => c[0] === "setPaintProperty");
  assert.deepEqual(
    paint.map((c) => c[1]),
    ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line"]
  );
});

test("cutout hides the basemap so the piece is highlight-only", () => {
  const extras = ["background", "water", "landcover", "boundary_state", "isolate-fill"];
  const map = fakeMap([...ALL_LAYERS, ...extras]);
  map.getStyle = () => ({ layers: extras.concat(["admin0-fill", "admin1-fill"]).map((id) => ({ id })) });
  isolatePairCutoutVisibility(map, ["A1:MYS-1186"]);
  const hidden = map.calls.filter((c) => c[0] === "setLayoutProperty" && c[3] === "none").map((c) => c[1]);
  for (const id of extras) assert.ok(hidden.includes(id), id);
  assert.equal(hidden.includes("admin0-fill"), false);
  assert.equal(hidden.includes("admin1-fill"), false);
  const bgOpacity = map.calls.find((c) => c[0] === "setPaintProperty" && c[1] === "background");
  assert.deepEqual(bgOpacity, ["setPaintProperty", "background", "background-opacity", 0]);
});

test("cutout restores highlight layer visibility after the base hid them", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairBaseVisibility(map, ["USA"]);
  isolatePairCutoutVisibility(map, ["USA"]);
  const visible = map.calls.filter((c) => c[0] === "setLayoutProperty" && c[3] === "visible");
  assert.deepEqual(
    visible.map((c) => c[1]),
    ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line"]
  );
});

test("cutout visibility is a no-op for isolate-fill when no isolate layer exists (bare admin0/admin1 slide)", () => {
  const map = fakeMap(["admin0-fill", "admin0-line"]);
  isolatePairCutoutVisibility(map, ["USA"]);
  assert.ok(!map.calls.some((c) => c[1] === "isolate-fill"));
  assert.deepEqual(
    map.calls.filter((c) => c[0] === "setPaintProperty").map((c) => c[1]),
    ["admin0-fill", "admin0-line"]
  );
});

test("full pair call order: base hide happens entirely before the cutout's isolate-fill hide", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairBaseVisibility(map, ["USA"]);
  const baseCalls = map.calls.length;
  isolatePairCutoutVisibility(map, ["USA"]);
  assert.equal(map.calls[baseCalls][0], "setLayoutProperty");
  assert.equal(map.calls[baseCalls][1], "isolate-fill");
});

test("cutout restore drops no-fill admin1 ids from the authored opacity expression", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairCutoutVisibility(map, ["A1:MYS-1186", "A1:MYS-1187"], { "A1:MYS-1186": "none" });
  const admin1Fill = map.calls.find((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill");
  assert.deepEqual(admin1Fill[3][1][2], ["literal", ["MYS-1187"]]);
});
