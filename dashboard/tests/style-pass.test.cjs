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

function channels(rgba) {
  const m = /rgba?\(([^)]+)\)/.exec(rgba);
  assert.ok(m, `${rgba} should be an rgb/rgba literal`);
  return m[1].split(",").map(Number);
}

function avg(rgba) {
  const [r, g, b] = channels(rgba);
  return (r + g + b) / 3;
}

function assertNoNaN(value) {
  if (typeof value === "string" && /^rgba?\(/i.test(value)) {
    for (const c of channels(value)) assert.ok(Number.isFinite(c), `${value} has a non-finite channel`);
    return;
  }
  if (Array.isArray(value)) value.forEach(assertNoNaN);
}

test("withBrighterDarkLines parses CSS Color 4 space and slash-alpha syntax without producing NaN", () => {
  const result = withBrighterDarkLines(darkStyle);
  for (const layer of result.layers) {
    for (const value of Object.values(layer.paint ?? {})) assertNoNaN(value);
  }

  const byId = (id) => result.layers.find((layer) => layer.id === id);
  // space-separated rgb() and comma rgb() of the same colour lift to the same result.
  assert.deepEqual(channels(byId("highway_minor_space").paint["line-color"]), [70, 70, 75, 1]);
  // slash alpha and comma alpha of the same colour lift to the same rgb channels.
  assert.deepEqual(
    channels(byId("highway_major_casing_slash").paint["line-color"]),
    channels(byId("highway_major_casing").paint["line-color"]),
  );
  assert.deepEqual(
    channels(byId("boundary_state_space").paint["line-color"]),
    channels(byId("boundary_state").paint["line-color"]),
  );
});

test("withBrighterDarkLines lifts grey line and label colours proportionally and preserves hierarchy", () => {
  const result = withBrighterDarkLines(darkStyle);
  const byId = (id) => result.layers.find((layer) => layer.id === id);

  assert.equal(byId("background").paint["background-color"], "rgb(12,12,12)");
  assert.equal(byId("water").paint["fill-color"], "rgb(27 ,27 ,29)");
  assert.equal(byId("building").paint["fill-color"], "rgb(10,10,10)");
  // fill-outline-color is dropped from TARGET_PROPS: the building outline stays untouched.
  assert.equal(byId("building").paint["fill-outline-color"], "rgb(27 ,27 ,29)");

  for (const [id, prop] of [
    ["waterway", "line-color"],
    ["highway_minor", "line-color"],
    ["highway_major_casing", "line-color"],
    ["railway", "line-color"],
    ["boundary_state", "line-color"],
    ["boundary_country_z0-4", "line-color"],
  ]) {
    const before = darkStyle.layers.find((layer) => layer.id === id).paint[prop];
    const after = byId(id).paint[prop];
    assert.notEqual(after, before, `${id}.${prop} should change`);
  }

  // minor road (24,24,24) and motorway casing (60,60,60) stay separated after the lift,
  // instead of the old affine band that mapped both close together.
  const minor = avg(byId("highway_minor").paint["line-color"]);
  const casing = avg(byId("highway_major_casing").paint["line-color"]);
  assert.ok(minor < casing, "hierarchy between minor road and motorway casing should be preserved");
  assert.ok(casing - minor >= 60, `separation should be substantial, got ${casing} - ${minor}`);

  assert.equal(byId("place_city").paint["text-halo-color"], "rgba(0,0,0,0.7)");
  // already-bright greys (mean >= the floor) are left untouched, format included.
  assert.equal(byId("place_city").paint["text-color"], "rgb(101,101,101)");
  assert.equal(byId("highway_name_motorway").paint["text-color"], "hsl(0,0%,37%)");
});

test("withBrighterDarkLines recurses into expression leaves and preserves non-colour structure", () => {
  const result = withBrighterDarkLines(darkStyle);
  const before = darkStyle.layers.find((l) => l.id === "highway_motorway_inner").paint["line-color"];
  const after = result.layers.find((l) => l.id === "highway_motorway_inner").paint["line-color"];

  assert.equal(after[0], "interpolate");
  assert.deepEqual(after[1], before[1]);
  assert.deepEqual(after[2], before[2]);
  assert.equal(after[3], before[3]);
  // the already-bright stop is left untouched; the dark #000 stop is brightened.
  assert.equal(after[4], before[4]);
  assert.equal(after[5], before[5]);
  assert.notEqual(after[6], before[6]);
  assert.deepEqual(channels(after[6]), [70, 70, 70, 1]);
});

test("withBrighterDarkLines is idempotent", () => {
  const once = withBrighterDarkLines(darkStyle);
  const twice = withBrighterDarkLines(once);
  assert.deepEqual(twice, once);
});
