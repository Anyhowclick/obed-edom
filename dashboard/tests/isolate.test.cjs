const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-isolate-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/isolate.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { isolateMaskGeometry, countryClipRings } = require(path.join(out, "isolate.js"));

const compileTypes = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compileTypes.status, 0, compileTypes.stderr || compileTypes.stdout);
const { parseIsolate, DEFAULT_ISOLATE_STRENGTH } = require(path.join(out, "types.js"));

const WORLD_RING = [[-180, -85.05], [180, -85.05], [180, 85.05], [-180, 85.05], [-180, -85.05]];

function polygon(code, rings) {
  return { properties: { ADM0_A3: code }, geometry: { type: "Polygon", coordinates: rings } };
}

function multiPolygon(code, polygons) {
  return { properties: { ADM0_A3: code }, geometry: { type: "MultiPolygon", coordinates: polygons } };
}

test("empty highlights returns null", () => {
  const features = [polygon("USA", [[[0, 0], [1, 0], [1, 1], [0, 0]]])];
  assert.equal(isolateMaskGeometry(features, []), null);
  assert.equal(isolateMaskGeometry(features, ["  "]), null);
});

test("single Polygon produces world rect ring plus its own ring", () => {
  const ring = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const features = [polygon("USA", [ring])];
  const result = isolateMaskGeometry(features, ["usa"]);
  assert.equal(result.geometry.coordinates.length, 2);
  assert.deepEqual(result.geometry.coordinates[0], WORLD_RING);
  assert.deepEqual(result.geometry.coordinates[1], ring);
});

test("MultiPolygon with a hole contributes all rings", () => {
  const outerA = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const outerB = [[2, 2], [3, 2], [3, 3], [2, 2]];
  const outerHoleC = [[4, 4], [5, 4], [5, 5], [4, 4]];
  const holeC = [[4.1, 4.1], [4.5, 4.1], [4.5, 4.5], [4.1, 4.1]];
  const features = [
    multiPolygon("FRA", [[outerA], [outerB], [outerHoleC, holeC]]),
  ];
  const result = isolateMaskGeometry(features, ["fra"]);
  assert.equal(result.geometry.coordinates.length, 5);
  assert.deepEqual(result.geometry.coordinates[0], WORLD_RING);
  assert.deepEqual(result.geometry.coordinates.slice(1), [outerA, outerB, outerHoleC, holeC]);
});

test("unmatched country code returns null", () => {
  const features = [polygon("USA", [[[0, 0], [1, 0], [1, 1], [0, 0]]])];
  assert.equal(isolateMaskGeometry(features, ["GBR"]), null);
});

test("countryClipRings has no world ring", () => {
  const ring = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const features = [polygon("USA", [ring])];
  assert.deepEqual(countryClipRings(features, ["usa"]), [ring]);
});

test("countryClipRings collects all rings of a MultiPolygon", () => {
  const outerA = [[0, 0], [1, 0], [1, 1], [0, 0]];
  const outerB = [[2, 2], [3, 2], [3, 3], [2, 2]];
  const features = [multiPolygon("FRA", [[outerA], [outerB]])];
  assert.deepEqual(countryClipRings(features, ["fra"]), [outerA, outerB]);
});

test("countryClipRings returns empty on no match", () => {
  const features = [polygon("USA", [[[0, 0], [1, 0], [1, 1], [0, 0]]])];
  assert.deepEqual(countryClipRings(features, ["GBR"]), []);
  assert.deepEqual(countryClipRings(features, []), []);
});

test("parseIsolate falls back to the default strength when missing", () => {
  assert.equal(parseIsolate({ mode: "darken" }).strength, DEFAULT_ISOLATE_STRENGTH);
});

test("parseIsolate preserves an explicit strength", () => {
  assert.equal(parseIsolate({ mode: "darken", strength: 0.35 }).strength, 0.35);
});
