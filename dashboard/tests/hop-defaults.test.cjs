const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-hop-defaults-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { isolateDissolveDefault } = require(path.join(out, "types.js"));

const isolate = { mode: "darken", strength: 0.6 };

test("isolated destination after a movie hop defaults to dissolve 1s", () => {
  const from = { isolate };
  const incoming = { kind: "movie" };
  assert.deepEqual(isolateDissolveDefault(from, incoming), { kind: "dissolve", duration: 1 });
});

test("isolated destination after a dissolve hop has no default", () => {
  const from = { isolate };
  const incoming = { kind: "dissolve" };
  assert.equal(isolateDissolveDefault(from, incoming), null);
});

test("non-isolated destination after a movie hop has no default", () => {
  const from = {};
  const incoming = { kind: "movie" };
  assert.equal(isolateDissolveDefault(from, incoming), null);
});

test("isolated destination with no incoming hop has no default", () => {
  const from = { isolate };
  assert.equal(isolateDissolveDefault(from, undefined), null);
});
