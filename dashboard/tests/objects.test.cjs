const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-objects-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/objects.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { defaultLandmarkSize, resizeFromHandle } = require(path.join(out, "objects.js"));

test("defaultLandmarkSize floors tiny assets at 240", () => {
  assert.equal(defaultLandmarkSize(10), 240);
});

test("defaultLandmarkSize caps huge assets at 1280 (1920 // 3 * 2)", () => {
  assert.equal(defaultLandmarkSize(1e6), 1280);
});

test("defaultLandmarkSize passes through a typical asset width", () => {
  assert.equal(defaultLandmarkSize(800), 800);
});

test("resizeFromHandle grows with a rightward drag", () => {
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 1), 220);
});

test("resizeFromHandle shrinks with a leftward drag", () => {
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: -20, y: 0 }, 120, 1), 80);
});

test("resizeFromHandle clamps to [24, 4000]", () => {
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: -1000, y: 0 }, 120, 1), 24);
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: 10000, y: 0 }, 120, 1), 4000);
});

test("resizeFromHandle accounts for objectScale != 1", () => {
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 0.5), 320);
  assert.equal(resizeFromHandle({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 2), 170);
});
