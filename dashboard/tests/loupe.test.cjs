const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "wash-loupe-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/watercolour/loupe.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { loupeCorner } = require(path.join(out, "loupe.js"));

const W = 400;
const H = 200;

test("cursor in each quadrant docks the loupe to the opposite corner", () => {
  assert.equal(loupeCorner(10, 10, W, H), "br");
  assert.equal(loupeCorner(W - 10, 10, W, H), "bl");
  assert.equal(loupeCorner(10, H - 10, W, H), "tr");
  assert.equal(loupeCorner(W - 10, H - 10, W, H), "tl");
});

test("exact centre ties toward the top-left quadrant's opposite corner", () => {
  assert.equal(loupeCorner(W / 2, H / 2, W, H), "br");
});
