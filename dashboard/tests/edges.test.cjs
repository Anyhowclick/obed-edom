const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "wash-edges-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/watercolour/edges.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { sobelMagnitude, snapToEdge } = require(path.join(out, "edges.js"));

const W = 16;
const H = 8;

function halfSplitImage() {
  const rgba = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const value = x < W / 2 ? 0 : 255;
      const offset = (x + y * W) * 4;
      rgba[offset] = value; rgba[offset + 1] = value; rgba[offset + 2] = value; rgba[offset + 3] = 255;
    }
  }
  return rgba;
}

test("sobelMagnitude peaks on the boundary column and is near zero in flat interiors", () => {
  const rgba = halfSplitImage();
  const grad = sobelMagnitude(rgba, W, H);
  const midY = 4;
  const boundary = grad[(W / 2 - 1) + midY * W];
  const flatLeft = grad[2 + midY * W];
  const flatRight = grad[W - 2 + midY * W];
  assert.equal(boundary, 1);
  assert.ok(flatLeft < 0.01);
  assert.ok(flatRight < 0.01);
});

test("snapToEdge from a few pixels away returns the boundary column", () => {
  const rgba = halfSplitImage();
  const grad = sobelMagnitude(rgba, W, H);
  const [sx] = snapToEdge(grad, W, H, W / 2 - 1 - 5, 4, 8);
  assert.equal(sx, W / 2 - 1);
});

test("a point already on the edge stays put", () => {
  const rgba = halfSplitImage();
  const grad = sobelMagnitude(rgba, W, H);
  const [sx, sy] = snapToEdge(grad, W, H, W / 2 - 1, 4, 8);
  assert.equal(sx, W / 2 - 1);
  assert.equal(sy, 4);
});

test("radius clamps at the image bounds", () => {
  const rgba = halfSplitImage();
  const grad = sobelMagnitude(rgba, W, H);
  const [sx, sy] = snapToEdge(grad, W, H, 0, 0, 8);
  assert.ok(sx >= 0 && sx < W);
  assert.ok(sy >= 0 && sy < H);
});
