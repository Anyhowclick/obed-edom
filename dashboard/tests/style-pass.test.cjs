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

const originalColors = new Set();
(function collect(value) {
  if (typeof value === "string") originalColors.add(value);
  else if (Array.isArray(value)) value.forEach(collect);
  else if (value && typeof value === "object") Object.values(value).forEach(collect);
})(darkStyle.layers);

// Every string the pass emits is an "rgba(r,g,b,a)" literal with finite parts;
// anything the pass left alone is passed through verbatim.
function assertNoNaN(value) {
  if (typeof value === "string") {
    if (originalColors.has(value)) return;
    assert.match(value, /^rgba\([^)]*\)$/, `${value} is not an emitted rgba literal`);
    for (const c of channels(value)) assert.ok(Number.isFinite(c), `${value} has a non-finite channel`);
    return;
  }
  if (Array.isArray(value)) value.forEach(assertNoNaN);
}

test("withBrighterDarkLines parses CSS Color 4 space, slash-alpha and percentage syntax without producing NaN", () => {
  const result = withBrighterDarkLines(darkStyle);
  for (const layer of result.layers) {
    for (const value of Object.values(layer.paint ?? {})) assertNoNaN(value);
  }

  const byId = (id) => result.layers.find((layer) => layer.id === id);
  // space-separated rgb() and comma rgb() of the same colour lift to the same result.
  assert.deepEqual(channels(byId("highway_minor_space").paint["line-color"]), [106, 106, 108, 1]);
  // slash alpha and comma alpha of the same colour lift to the same rgb channels.
  assert.deepEqual(
    channels(byId("highway_major_casing_slash").paint["line-color"]),
    channels(byId("highway_major_casing").paint["line-color"]),
  );
  assert.deepEqual(
    channels(byId("boundary_state_space").paint["line-color"]),
    channels(byId("boundary_state").paint["line-color"]),
  );

  // "80%" alpha is a fraction, not the number 80.
  assert.deepEqual(channels(byId("highway_major_casing_pct_alpha").paint["line-color"]), [120, 120, 120, 0.8]);
  // a bare "80" is out of [0,1] and is not a valid alpha: the colour is left alone.
  assert.equal(byId("highway_major_casing_bad_alpha").paint["line-color"], "rgb(60 60 60 / 80)");
  // percentage channels are 0-100 of 255, not raw 0-255 values.
  assert.deepEqual(channels(byId("highway_pct_channels").paint["line-color"]), [147, 147, 147, 1]);
  // fully transparent colours are skipped.
  assert.equal(byId("highway_transparent").paint["line-color"], "rgba(20,20,20,0)");
});

test("withBrighterDarkLines lifts grey line and label colours proportionally and keeps them strictly ordered", () => {
  const result = withBrighterDarkLines(darkStyle);
  const byId = (id) => result.layers.find((layer) => layer.id === id);

  assert.equal(byId("background").paint["background-color"], "rgb(12,12,12)");
  assert.equal(byId("water").paint["fill-color"], "rgb(27,27,29)");
  assert.equal(byId("building").paint["fill-color"], "rgb(10,10,10)");
  // fill-outline-color is dropped from TARGET_PROPS: the building outline stays untouched.
  assert.equal(byId("building").paint["fill-outline-color"], "rgb(27,27,29)");
  // halos are never a TARGET_PROP.
  assert.equal(byId("place_city").paint["text-halo-color"], "rgba(0,0,0,0.7)");

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

  // minor road (24) and motorway casing (60) stay separated after the lift.
  const minor = avg(byId("highway_minor").paint["line-color"]);
  const casing = avg(byId("highway_major_casing").paint["line-color"]);
  assert.equal(minor, 106);
  assert.equal(casing, 120);

  // the darkest band no longer collapses: 5 < 20 < 24 survives the lift.
  const track = avg(byId("highway_track").paint["line-color"]);
  const service = avg(byId("highway_service").paint["line-color"]);
  assert.deepEqual([track, service, minor], [98, 104, 106]);

  // labels are lifted too, and stay ordered.
  assert.equal(avg(byId("highway_name_motorway").paint["text-color"]), 134);
  assert.equal(avg(byId("place_city").paint["text-color"]), 136);

  // at and above the knee the colour is untouched, format included.
  assert.equal(byId("place_continent").paint["text-color"], "rgb(160,160,160)");
  assert.equal(byId("place_country").paint["text-color"], "rgb(200,200,200)");
});

test("withBrighterDarkLines is monotone across the whole grey ramp", () => {
  const layers = [];
  for (let x = 0; x <= 255; x += 1) {
    layers.push({ id: `grey_${x}`, type: "line", paint: { "line-color": `rgb(${x},${x},${x})` } });
  }
  const result = withBrighterDarkLines({ version: 8, sources: {}, layers });
  const lifted = result.layers.map((layer) => avg(layer.paint["line-color"]));

  for (let x = 1; x <= 255; x += 1) {
    assert.ok(lifted[x] >= lifted[x - 1], `grey ${x} (${lifted[x]}) must not fall below grey ${x - 1} (${lifted[x - 1]})`);
  }
  // the old curve inverted here: 69 jumped to 179 while 70 was skipped entirely.
  assert.ok(lifted[69] <= lifted[70], `69 -> ${lifted[69]} must not overtake 70 -> ${lifted[70]}`);
  assert.deepEqual([lifted[0], lifted[54], lifted[60], lifted[101], lifted[160], lifted[200]], [96, 118, 120, 136, 160, 200]);
});

test("withBrighterDarkLines is applied exactly once, so a second pass lifts further", () => {
  // styles.ts calls it once, on the freshly fetched Dark style; a strictly monotone
  // non-identity map cannot be idempotent, so this documents the single application.
  const once = withBrighterDarkLines(darkStyle);
  const twice = withBrighterDarkLines(once);
  const avgOf = (style) => avg(style.layers.find((l) => l.id === "highway_minor").paint["line-color"]);
  assert.ok(avgOf(twice) > avgOf(once));
});

test("withBrighterDarkLines recurses into expression outputs and leaves inputs, stops and labels alone", () => {
  const result = withBrighterDarkLines(darkStyle);
  const beforeOf = (id) => darkStyle.layers.find((l) => l.id === id).paint["line-color"];
  const afterOf = (id) => result.layers.find((l) => l.id === id).paint["line-color"];

  const before = beforeOf("highway_motorway_inner");
  const after = afterOf("highway_motorway_inner");
  assert.equal(after[0], "interpolate");
  assert.deepEqual(after[1], before[1]);
  assert.deepEqual(after[2], before[2]);
  assert.equal(after[3], before[3]);
  // the already-bright stop is left untouched; the dark #000 stop is brightened.
  assert.equal(after[4], before[4]);
  assert.equal(after[5], before[5]);
  assert.deepEqual(channels(after[6]), [96, 96, 96, 1]);

  // match: labels (even indices from 2) are opaque data even when they look like colours.
  const match = afterOf("highway_class_match");
  assert.equal(match[0], "match");
  assert.deepEqual(match[1], beforeOf("highway_class_match")[1]);
  assert.equal(match[2], "#181818");
  assert.equal(avg(match[3]), 109);
  assert.equal(match[4], "#000000");
  assert.equal(avg(match[5]), 102);
  assert.equal(avg(match[6]), 98);

  // step: the input and the numeric stops survive; every output is lifted.
  const step = afterOf("highway_zoom_step");
  assert.equal(step[0], "step");
  assert.deepEqual(step[1], ["zoom"]);
  assert.equal(avg(step[2]), 100);
  assert.equal(step[3], 10);
  assert.equal(avg(step[4]), 104);
  assert.equal(step[5], 14);
  assert.equal(avg(step[6]), 108);

  // case: conditions untouched, output and fallback lifted.
  const caseExpr = afterOf("highway_case");
  assert.equal(caseExpr[0], "case");
  assert.deepEqual(caseExpr[1], beforeOf("highway_case")[1]);
  assert.equal(avg(caseExpr[2]), 100);
  assert.equal(avg(caseExpr[3]), 104);
});

test("withBrighterDarkLines shifts every channel by the same delta, so chroma survives and nothing blows up", () => {
  const result = withBrighterDarkLines(darkStyle);
  const byId = (id) => result.layers.find((layer) => layer.id === id);

  // a near-black saturated red must not saturate to rgb(255,0,0): the lift is additive.
  assert.deepEqual(channels(byId("tint_rgb").paint["line-color"]), [97, 96, 96, 1]);

  // a tinted dark blue keeps its channel spread exactly.
  const before = [13, 26, 38];
  const after = channels(byId("tint_hsl").paint["line-color"]).slice(0, 3);
  assert.deepEqual(after, [94, 107, 119]);
  const deltas = after.map((c, i) => c - before[i]);
  assert.deepEqual(deltas, [deltas[0], deltas[0], deltas[0]]);
});

test("withBrighterDarkLines accepts 4- and 8-digit hex with a trailing alpha", () => {
  const result = withBrighterDarkLines(darkStyle);
  const byId = (id) => result.layers.find((layer) => layer.id === id);

  const eight = channels(byId("hex_8").paint["line-color"]);
  assert.deepEqual(eight.slice(0, 3), [96, 96, 96]);
  assert.ok(Math.abs(eight[3] - 0.5) < 0.01, `alpha ${eight[3]} should be ~0.5`);

  const four = channels(byId("hex_4").paint["line-color"]);
  assert.deepEqual(four.slice(0, 3), [86, 103, 120]);
  assert.ok(Math.abs(four[3] - 0.2) < 0.01, `alpha ${four[3]} should be ~0.2`);
});

test("withBrighterDarkLines lifts interpolate-hcl outputs and leaves its stops alone", () => {
  const result = withBrighterDarkLines(darkStyle);
  const after = result.layers.find((layer) => layer.id === "highway_hcl").paint["line-color"];

  assert.equal(after[0], "interpolate-hcl");
  assert.deepEqual(after[1], ["linear"]);
  assert.deepEqual(after[2], ["zoom"]);
  assert.equal(after[3], 5);
  assert.deepEqual(channels(after[4]), [96, 96, 96, 1]);
  assert.equal(after[5], 10);
  assert.equal(avg(after[6]), 102);
});
