const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-capture-isolate-visibility-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/captureIsolateVisibility.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
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
  assert.deepEqual(
    map.calls.map((c) => c[1]),
    ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line"]
  );
  assert.ok(map.calls.every((c) => c[3] === 0));
});

test("isolate-on cutout: isolate-fill is hidden, highlight opacity is left untouched", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairCutoutVisibility(map, ["USA"], true);
  assert.deepEqual(map.calls, [["setLayoutProperty", "isolate-fill", "visibility", "none"]]);
});

test("isolate-off cutout: isolate-fill is hidden first, then highlights restore to authored expressions", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairCutoutVisibility(map, ["A1:MYS-1186"], false);
  assert.equal(map.calls[0][0], "setLayoutProperty");
  assert.equal(map.calls[0][1], "isolate-fill");
  assert.deepEqual(
    map.calls.slice(1).map((c) => c[1]),
    ["admin0-fill", "admin0-line", "admin1-fill", "admin1-line"]
  );
});

test("cutout visibility is a no-op for isolate-fill when no isolate layer exists (bare admin0/admin1 slide)", () => {
  const map = fakeMap(["admin0-fill", "admin0-line"]);
  isolatePairCutoutVisibility(map, ["USA"], false);
  assert.ok(!map.calls.some((c) => c[1] === "isolate-fill"));
  assert.deepEqual(
    map.calls.map((c) => c[1]),
    ["admin0-fill", "admin0-line"]
  );
});

test("full pair call order: base hide happens entirely before the cutout's isolate-fill hide", () => {
  const map = fakeMap(ALL_LAYERS);
  isolatePairBaseVisibility(map, ["USA"]);
  const baseCalls = map.calls.length;
  isolatePairCutoutVisibility(map, ["USA"], true);
  assert.equal(map.calls[baseCalls][0], "setLayoutProperty");
  assert.equal(map.calls[baseCalls][1], "isolate-fill");
});
