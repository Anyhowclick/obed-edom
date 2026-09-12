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
const { DROP_PIN_HEAD_PX, DROP_PIN_TOTAL_PX, dropPinSelectionBox } = require(path.join(out, "overlays.js"));

// `dropPinImage` needs a DOM canvas, which node has no implementation of here, so these
// assert the exported geometry the raster is drawn from and the maths derived off it.

test("drop pin total height is Keynote's head + tail (0.68 offset + 0.4 tall)", () => {
  assert.equal(DROP_PIN_TOTAL_PX / DROP_PIN_HEAD_PX, 0.68 + 0.4);
});

test("the raster is an integral number of device px at pixelRatio 2", () => {
  assert.equal((DROP_PIN_HEAD_PX * 2) % 1, 0);
  assert.equal((DROP_PIN_TOTAL_PX * 2) % 1, 0);
  assert.equal(DROP_PIN_HEAD_PX * 2, 100);
  assert.equal(DROP_PIN_TOTAL_PX * 2, 108);
});

test("icon-size = size / DROP_PIN_HEAD_PX renders a head of exactly `size` CSS px", () => {
  for (const size of [28, 64, 120]) {
    const iconSize = size / DROP_PIN_HEAD_PX;
    assert.ok(Math.abs(DROP_PIN_HEAD_PX * iconSize - size) < 1e-9);
    assert.ok(Math.abs(DROP_PIN_TOTAL_PX * iconSize - size * 1.08) < 1e-9);
  }
});

test("the selection box tracks the selected pin's rendered head and 1.08 aspect", () => {
  const box = dropPinSelectionBox(64);
  assert.equal(box.w, 64 * 1.08);
  assert.equal(box.h / box.w, DROP_PIN_TOTAL_PX / DROP_PIN_HEAD_PX);
});
