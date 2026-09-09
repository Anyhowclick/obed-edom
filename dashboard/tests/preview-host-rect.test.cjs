const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-preview-host-rect-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { previewHostRect } = require(path.join(out, "types.js"));

test("previewHostRect centres a width-limited frame (frame narrower than the authored aspect)", () => {
  const rect = previewHostRect(1200, 420, 3840);
  assert.equal(rect.width, 1200);
  assert.equal(rect.height, 337.5);
  assert.equal(rect.x, 0);
  assert.equal(rect.y, 41.25);
});

test("previewHostRect centres a height-limited frame (frame wider than the authored aspect)", () => {
  const rect = previewHostRect(2000, 300, 1920);
  assert.equal(rect.height, 300);
  assert.ok(Math.abs(rect.width - 533.3333) < 1e-3);
  assert.ok(Math.abs(rect.x - 733.3333) < 1e-3);
  assert.equal(rect.y, 0);
});

test("previewHostRect keeps the authored aspect for both FW and CG surface widths", () => {
  for (const surfaceWidth of [7680, 1920]) {
    const rect = previewHostRect(1600, 900, surfaceWidth);
    assert.ok(rect.width > 0 && rect.height > 0);
    assert.ok(Math.abs(rect.height / rect.width - 1080 / surfaceWidth) < 1e-9);
  }
});

test("previewHostRect is all zero when either frame dimension is zero", () => {
  assert.deepEqual(previewHostRect(0, 500, 3840), { x: 0, y: 0, width: 0, height: 0 });
  assert.deepEqual(previewHostRect(500, 0, 3840), { x: 0, y: 0, width: 0, height: 0 });
});
