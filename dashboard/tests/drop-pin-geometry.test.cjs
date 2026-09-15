const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-drop-pin-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/overlays.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { DROP_PIN_HEAD_PX, DROP_PIN_TOTAL_PX, DROP_PIN_ASPECT, DROP_PIN_SELECTED_SCALE, dropPinSelectionBox, selectedDragScale } = require(path.join(out, "overlays.js"));
const { resizeFromCorner } = require(path.join(out, "objects.js"));

// `dropPinImage` needs a DOM canvas, which node has no implementation of here, so these
// assert the exported geometry the raster is drawn from and the maths derived off it.

test("drop pin total height matches Keynote's PIN_ASPECT", () => {
  assert.equal(DROP_PIN_TOTAL_PX / DROP_PIN_HEAD_PX, DROP_PIN_ASPECT);
});

test("the raster is an integral number of device px at pixelRatio 2", () => {
  assert.equal((DROP_PIN_HEAD_PX * 2) % 1, 0);
  assert.equal((DROP_PIN_TOTAL_PX * 2) % 1, 0);
  assert.equal(DROP_PIN_HEAD_PX * 2, 100);
  assert.equal(DROP_PIN_TOTAL_PX * 2, 145);
});

test("icon-size = size / DROP_PIN_HEAD_PX renders a head of exactly `size` CSS px", () => {
  for (const size of [28, 64, 120]) {
    const iconSize = size / DROP_PIN_HEAD_PX;
    assert.ok(Math.abs(DROP_PIN_HEAD_PX * iconSize - size) < 1e-9);
    assert.ok(Math.abs(DROP_PIN_TOTAL_PX * iconSize - size * DROP_PIN_ASPECT) < 1e-9);
  }
});

test("the selection box tracks the selected pin's rendered head and aspect", () => {
  const box = dropPinSelectionBox(64);
  assert.equal(box.w, 64 * DROP_PIN_SELECTED_SCALE);
  assert.ok(Math.abs(box.h / box.w - DROP_PIN_TOTAL_PX / DROP_PIN_HEAD_PX) < 1e-9);
});

test("selectedDragScale only inflates drop pins", () => {
  assert.equal(selectedDragScale("dropPin", 2), 2 * DROP_PIN_SELECTED_SCALE);
  assert.equal(selectedDragScale("dot", 2), 2);
  assert.equal(selectedDragScale("landmark", 2), 2);
});

test("a drag that returns the se handle to its start leaves a selected drop pin's size alone", () => {
  const layoutScale = 1.5;
  const startSize = 200;
  const targetSize = 320;
  const aspect = DROP_PIN_TOTAL_PX / DROP_PIN_HEAD_PX;
  const scale = selectedDragScale("dropPin", layoutScale);
  // The se handle sits at half the rendered box width, right of the anchor.
  const handleX = (size) => dropPinSelectionBox(size * layoutScale).w / 2;

  const grown = resizeFromCorner({ x: handleX(startSize), y: 0 }, { x: handleX(targetSize), y: 0 }, startSize, scale, "se", aspect);
  assert.equal(grown, targetSize);

  const back = resizeFromCorner({ x: handleX(targetSize), y: 0 }, { x: handleX(startSize), y: 0 }, grown, scale, "se", aspect);
  assert.equal(back, startSize);
});

test("dropPinImage no longer strokes a rim around the pin", () => {
  const source = fs.readFileSync(path.join(root, "src/maps/overlays.ts"), "utf8");
  const start = source.indexOf("function dropPinImage(");
  assert.notEqual(start, -1);
  const nextExport = source.indexOf("export function", start);
  const body = source.slice(start, nextExport === -1 ? source.length : nextExport);
  assert.ok(!/stroke\(/.test(body));
  assert.ok(!/strokeStyle/.test(body));
});

test("a dot's handle drag needs no selection scale", () => {
  const layoutScale = 1.5;
  const handleX = (size) => (size * layoutScale) / 2;
  const grown = resizeFromCorner({ x: handleX(100), y: 0 }, { x: handleX(180), y: 0 }, 100, selectedDragScale("dot", layoutScale), "se");
  assert.equal(grown, 180);
});
