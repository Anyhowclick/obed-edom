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
const { defaultLandmarkSize, defaultObjectSize, rebaseForPaste, resizeFromCorner, zoomSizeFactor, effectiveObjectSize } = require(path.join(out, "objects.js"));

test("defaultObjectSize matches DOT_SIZE/DROP_SIZE (maps_keynote.py) and the landmark default", () => {
  assert.equal(defaultObjectSize("dot"), 28);
  assert.equal(defaultObjectSize("dropPin"), 64);
  assert.equal(defaultObjectSize("landmark"), 120);
});

test("effectiveObjectSize falls back to the per-kind default when size is missing", () => {
  assert.equal(effectiveObjectSize({ kind: "dot" }, 6), 28);
  assert.equal(effectiveObjectSize({ kind: "dropPin" }, 6), 64);
  assert.equal(effectiveObjectSize({ kind: "landmark" }, 6), 120);
});

test("defaultLandmarkSize floors tiny assets at 240", () => {
  assert.equal(defaultLandmarkSize(10), 240);
});

test("defaultLandmarkSize caps huge assets at 1280 (1920 // 3 * 2)", () => {
  assert.equal(defaultLandmarkSize(1e6), 1280);
});

test("defaultLandmarkSize passes through a typical asset width", () => {
  assert.equal(defaultLandmarkSize(800), 800);
});

test("resizeFromCorner se: rightward drag matches the old edge-handle behaviour", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 1, "se"), 220);
});

test("resizeFromCorner sw: leftward drag grows the box", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: -50, y: 0 }, 120, 1, "sw"), 220);
});

test("resizeFromCorner ne: upward drag grows by |dy| / aspect", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 0, y: -50 }, 120, 1, "ne"), 170);
});

test("resizeFromCorner: aspect 2 halves the y contribution", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 0, y: -50 }, 120, 1, "ne", 2), 145);
});

test("resizeFromCorner picks the dominant axis", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 50, y: 5 }, 120, 1, "se"), 220);
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 5, y: 50 }, 120, 1, "se"), 170);
});

test("resizeFromCorner clamps to [24, 4000]", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: -1000, y: 0 }, 120, 1, "se"), 24);
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 10000, y: 0 }, 120, 1, "se"), 4000);
});

test("resizeFromCorner accounts for objectScale != 1", () => {
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 0.5, "se"), 320);
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 2, "se"), 170);
});

test("effectiveObjectSize is unchanged when scaleWithMap is off", () => {
  assert.equal(effectiveObjectSize({ size: 200, scaleWithMap: false, sizeZoom: 5 }, 6), 200);
});

test("effectiveObjectSize doubles for +1 zoom", () => {
  assert.equal(effectiveObjectSize({ size: 200, scaleWithMap: true, sizeZoom: 5 }, 6), 400);
});

test("effectiveObjectSize halves for -1 zoom", () => {
  assert.equal(effectiveObjectSize({ size: 200, scaleWithMap: true, sizeZoom: 5 }, 4), 100);
});

test("effectiveObjectSize has no floor", () => {
  assert.equal(effectiveObjectSize({ size: 1, scaleWithMap: true, sizeZoom: 20 }, 0), Math.pow(2, -20));
});

test("effectiveObjectSize is unchanged when sizeZoom is missing", () => {
  assert.equal(effectiveObjectSize({ size: 200, scaleWithMap: true }, 10), 200);
});

test("zoomSizeFactor matches effectiveObjectSize's ratio", () => {
  assert.equal(zoomSizeFactor(5, 7), 4);
});

test("resizeFromCorner with a zoom-inflated scale edits ground size", () => {
  const zoomFactor = zoomSizeFactor(5, 6);
  assert.equal(resizeFromCorner({ x: 0, y: 0 }, { x: 50, y: 0 }, 120, 1 * zoomFactor, "se"), 170);
});

test("rebaseForPaste leaves a non-scaling object untouched", () => {
  const church = { kind: "dropPin", size: 100, scaleWithMap: false, sizeZoom: 5 };
  assert.deepEqual(rebaseForPaste(church, 7, 10), church);
});

test("rebaseForPaste keeps the on-screen size when the source camera differs from sizeZoom", () => {
  // size 100 authored at sizeZoom 5, viewed on a source camera at zoom 7 -> 400 px on screen.
  const church = { kind: "dropPin", size: 100, scaleWithMap: true, sizeZoom: 5 };
  assert.equal(effectiveObjectSize(church, 7), 400);
  const pasted = rebaseForPaste(church, 7, 10);
  assert.equal(pasted.size, 400);
  assert.equal(pasted.sizeZoom, 10);
  assert.equal(effectiveObjectSize(pasted, 10), 400);
});

test("rebaseForPaste is a no-op on size when the source camera equals sizeZoom", () => {
  const church = { kind: "dropPin", size: 100, scaleWithMap: true, sizeZoom: 7 };
  const pasted = rebaseForPaste(church, 7, 3);
  assert.equal(pasted.size, 100);
  assert.equal(pasted.sizeZoom, 3);
  assert.equal(effectiveObjectSize(pasted, 3), 100);
});

test("copy-then-paste to many slides holds the source on-screen size at every target camera", () => {
  const sourceZoom = 7;
  const church = { kind: "dropPin", size: 100, scaleWithMap: true, sizeZoom: 5 };
  const onScreen = effectiveObjectSize(church, sourceZoom);
  // copySelectedPins materialises against the source camera; pasteObjects rebases per target.
  const clipboard = rebaseForPaste({ ...church }, sourceZoom, sourceZoom);
  for (const targetZoom of [3, 7, 10, 12.5]) {
    const pasted = rebaseForPaste(clipboard, clipboard.sizeZoom, targetZoom);
    assert.equal(pasted.sizeZoom, targetZoom);
    assert.equal(effectiveObjectSize(pasted, targetZoom), onScreen);
  }
});
