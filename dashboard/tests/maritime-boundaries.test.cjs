const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-maritime-boundaries-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/maritimeBoundaries.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { NO_MARITIME, NO_MARITIME_LEGACY, isLegacyFilter, filterExcludesMaritime, withoutMaritimeBoundaries } = require(path.join(out, "maritimeBoundaries.js"));

test("filterExcludesMaritime recognises expression and legacy maritime checks", () => {
  assert.equal(filterExcludesMaritime(["!=", ["get", "maritime"], 1]), true);
  assert.equal(filterExcludesMaritime(["!=", "maritime", 1]), true);
  assert.equal(
    filterExcludesMaritime(["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]]),
    true
  );
  assert.equal(filterExcludesMaritime(["==", ["get", "admin_level"], 2]), false);
  assert.equal(filterExcludesMaritime(["!=", ["get", "maritime"], 0]), false);
  assert.equal(filterExcludesMaritime(["!=", "maritime", 0]), false);
  assert.equal(filterExcludesMaritime(undefined), false);
});

test("withoutMaritimeBoundaries wraps maritime != 0 instead of treating it as already excluded", () => {
  const style = {
    version: 8,
    sources: {},
    layers: [
      {
        id: "boundary_country",
        type: "line",
        "source-layer": "boundary",
        filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 0]],
        paint: {},
      },
      {
        id: "boundary_legacy",
        type: "line",
        "source-layer": "boundary",
        filter: ["!=", "maritime", 0],
        paint: {},
      },
    ],
  };
  const next = withoutMaritimeBoundaries(style);
  assert.deepEqual(next.layers[0].filter, [
    "all",
    ["==", ["get", "admin_level"], 2],
    ["!=", ["get", "maritime"], 0],
    NO_MARITIME,
  ]);
  assert.deepEqual(next.layers[1].filter, ["all", ["!=", "maritime", 0], NO_MARITIME_LEGACY]);
});

test("withoutMaritimeBoundaries wraps Dark/Fiord country filters and leaves Positron alone", () => {
  const dark = {
    version: 8,
    sources: {},
    layers: [
      { id: "water", type: "fill", "source-layer": "water", paint: {} },
      {
        id: "boundary_country_z0-4",
        type: "line",
        "source-layer": "boundary",
        filter: ["all", ["==", ["get", "admin_level"], 2], ["!", ["has", "claimed_by"]]],
        paint: {},
      },
      {
        id: "boundary_country_z5-",
        type: "line",
        "source-layer": "boundary",
        filter: ["==", ["get", "admin_level"], 2],
        paint: {},
      },
      {
        id: "boundary_2",
        type: "line",
        "source-layer": "boundary",
        filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
        paint: {},
      },
    ],
  };
  const next = withoutMaritimeBoundaries(dark);
  assert.equal(next.layers[0].filter, undefined);
  assert.deepEqual(next.layers[1].filter, [
    "all",
    ["==", ["get", "admin_level"], 2],
    ["!", ["has", "claimed_by"]],
    NO_MARITIME,
  ]);
  assert.deepEqual(next.layers[2].filter, ["all", ["==", ["get", "admin_level"], 2], NO_MARITIME]);
  assert.equal(next.layers[3], dark.layers[3]);
  assert.equal(withoutMaritimeBoundaries(next).layers[1].filter.length, next.layers[1].filter.length);
});

test("withoutMaritimeBoundaries keeps Toner filters in legacy syntax so MapLibre will load the style", () => {
  assert.equal(isLegacyFilter(["==", "admin_level", 2]), true);
  assert.equal(isLegacyFilter(["all", ["==", "admin_level", 4], ["!has", "claimed_by"]]), true);
  assert.equal(isLegacyFilter(["==", ["get", "admin_level"], 2]), false);
  const toner = {
    version: 8,
    sources: {},
    layers: [
      {
        id: "boundary_country_z5-",
        type: "line",
        "source-layer": "boundary",
        filter: ["==", "admin_level", 2],
        paint: {},
      },
      {
        id: "boundary_country_z0-4",
        type: "line",
        "source-layer": "boundary",
        filter: ["all", ["==", "admin_level", 2], ["!has", "claimed_by"]],
        paint: {},
      },
    ],
  };
  const next = withoutMaritimeBoundaries(toner);
  assert.deepEqual(next.layers[0].filter, ["all", ["==", "admin_level", 2], NO_MARITIME_LEGACY]);
  assert.deepEqual(next.layers[1].filter, ["all", ["==", "admin_level", 2], ["!has", "claimed_by"], NO_MARITIME_LEGACY]);
  assert.ok(isLegacyFilter(next.layers[0].filter));
  assert.ok(isLegacyFilter(next.layers[1].filter));
});

test("vendored Toner boundary layers stay all-legacy after the maritime wrap", () => {
  const vendor = JSON.parse(fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-8688fbd.json"), "utf8"));
  const next = withoutMaritimeBoundaries(vendor);
  for (const layer of next.layers) {
    if (layer["source-layer"] !== "boundary" && !String(layer.id).startsWith("boundary")) continue;
    assert.ok(layer.filter, layer.id);
    assert.ok(isLegacyFilter(layer.filter), `${layer.id} mixed expression into a legacy filter`);
    assert.equal(filterExcludesMaritime(layer.filter), true, layer.id);
  }
});

test("Toner lines (background + line only) still drops maritime country borders", () => {
  const vendor = JSON.parse(fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-8688fbd.json"), "utf8"));
  const lines = {
    ...vendor,
    layers: vendor.layers.filter((layer) => layer.type === "background" || layer.type === "line"),
  };
  const next = withoutMaritimeBoundaries(lines);
  const country = next.layers.filter((layer) => String(layer.id).startsWith("boundary_country"));
  assert.ok(country.length >= 2);
  for (const layer of country) {
    assert.ok(isLegacyFilter(layer.filter), layer.id);
    assert.equal(filterExcludesMaritime(layer.filter), true, layer.id);
  }
});
