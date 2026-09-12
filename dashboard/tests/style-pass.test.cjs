const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const runtime = process.env.CODEX_NODE || process.execPath;
const out = fs.mkdtempSync(path.join(os.tmpdir(), "style-pass-"));

function compile(file) {
  const compiled = spawnSync(runtime, [
    path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
    "--outDir", out, path.join(root, "src/maps", file),
  ], { cwd: root, encoding: "utf8" });
  assert.equal(compiled.status, 0, compiled.stderr || compiled.stdout);
}

compile("tonerBuildings.ts");
compile("darkContrast.ts");
const { withoutSolidBuildings } = require(path.join(out, "tonerBuildings.js"));
const { withBrighterDarkLines } = require(path.join(out, "darkContrast.js"));

const vendor = JSON.parse(fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-8688fbd.json"), "utf8"));

test("withoutSolidBuildings drops the solid fill and keeps the hatch at every other zoom", () => {
  const result = withoutSolidBuildings(vendor.layers);
  assert.equal(result.length, vendor.layers.length - 1);
  assert.ok(!result.some((layer) => layer.id === "building_fill"));
  const pattern = result.find((layer) => layer.id === "building_pattern");
  assert.deepEqual(pattern, vendor.layers.find((layer) => layer.id === "building_pattern"));
  const withoutFill = vendor.layers.filter((layer) => layer.id !== "building_fill");
  assert.deepEqual(result, withoutFill);
});

test("withoutSolidBuildings passes layers through unchanged when building_fill is missing", () => {
  const layers = vendor.layers.filter((layer) => layer.id !== "building_fill");
  assert.equal(withoutSolidBuildings(layers), layers);
});

const darkStyle = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/dark-style-sample.json"), "utf8"));

function avg(rgba) {
  const [r, g, b] = /rgba?\(([^)]+)\)/.exec(rgba)[1].split(",").map(Number);
  return (r + g + b) / 3;
}

test("withBrighterDarkLines lifts grey line and label colours toward white", () => {
  const result = withBrighterDarkLines(darkStyle);
  const byId = (id) => result.layers.find((layer) => layer.id === id);

  assert.equal(byId("background").paint["background-color"], "rgb(12,12,12)");
  assert.equal(byId("water").paint["fill-color"], "rgb(27 ,27 ,29)");
  assert.equal(byId("building").paint["fill-color"], "rgb(10,10,10)");

  for (const [id, prop] of [
    ["waterway", "line-color"],
    ["building", "fill-outline-color"],
    ["highway_minor", "line-color"],
    ["highway_major_casing", "line-color"],
    ["railway", "line-color"],
    ["boundary_state", "line-color"],
    ["boundary_country_z0-4", "line-color"],
    ["highway_name_motorway", "text-color"],
    ["place_city", "text-color"],
  ]) {
    const before = darkStyle.layers.find((layer) => layer.id === id).paint[prop];
    const after = byId(id).paint[prop];
    assert.notEqual(after, before, `${id}.${prop} should change`);
    assert.ok(avg(after) >= 140, `${id}.${prop} should be lifted above the brighten threshold`);
  }

  assert.equal(byId("place_city").paint["text-halo-color"], "rgba(0,0,0,0.7)");
  assert.deepEqual(byId("highway_motorway_inner").paint["line-color"], darkStyle.layers.find((l) => l.id === "highway_motorway_inner").paint["line-color"]);
});

test("withBrighterDarkLines is idempotent", () => {
  const once = withBrighterDarkLines(darkStyle);
  const twice = withBrighterDarkLines(once);
  assert.deepEqual(twice, once);
});
