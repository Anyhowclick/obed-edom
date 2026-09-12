const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-icon-size-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/objects.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { iconSizeStops } = require(path.join(out, "objects.js"));

function stopValues(stops) {
  assert.equal(stops[0], "interpolate");
  assert.deepEqual(stops[1], ["linear"]);
  assert.deepEqual(stops[2], ["zoom"]);
  return { z0: stops[4], z22: stops[6] };
}

test("iconSizeStops folds a non-scaling feature to the same value at both stops", () => {
  const { z0, z22 } = stopValues(iconSizeStops(["get", "base"]));
  assert.deepEqual(z0, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", 0, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
  assert.deepEqual(z22, ["case", ["boolean", ["get", "scaleWithMap"], false], ["*", ["get", "base"], ["^", 2, ["-", 22, ["get", "sizeZoomRef"]]]], ["get", "base"]]);
});

test("iconSizeStops values are geometric in ratio 2^22 for a scaling feature", () => {
  const sizeZoomRef = 5;
  const base = 40;
  const evalCase = (z) => Math.pow(2, z - sizeZoomRef) * base;
  assert.equal(evalCase(22) / evalCase(0), Math.pow(2, 22));
});

const overlaysOut = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-icon-size-full-"));
const overlaysCompile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", overlaysOut, path.join(root, "src/maps/overlays.ts"), path.join(root, "src/maps/objects.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(overlaysCompile.status, 0, overlaysCompile.stderr || overlaysCompile.stdout);
const { churchesGeo } = require(path.join(overlaysOut, "overlays.js"));

test("churchesGeo folds sizeZoom and log2(objectScale) into sizeZoomRef", () => {
  const church = { id: "a", name: "a", lat: 0, lon: 0, kind: "landmark", color: "#fff", scaleWithMap: true, sizeZoom: 5 };
  const geo = churchesGeo([church], null, false, 4);
  assert.equal(geo.features[0].properties.sizeZoomRef, 5 + 2);
  assert.equal(geo.features[0].properties.scaleWithMap, true);
});
