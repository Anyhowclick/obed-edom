const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-isolate-hop-preview-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { isolateDissolveNeeded, plainIsolateTarget } = require(path.join(out, "types.js"));

const camera = (lat) => ({ lat, lon: 0, zoom: 5, bearing: 0, pitch: 0 });
const slide = (id, overrides) => ({
  id, title: id, style: "positron", camera: camera(0),
  highlights: [], churches: [], cgShiftX: 0, cgShiftY: 0, includeSidePanels: false,
  ...overrides,
});

test("isolateDissolveNeeded is true when the destination is isolated with highlights", () => {
  const from = slide("a");
  const to = slide("b", { highlights: ["FR"], isolate: { mode: "darken", strength: 0.65 } });
  assert.equal(isolateDissolveNeeded(from, to), true);
  const plain = plainIsolateTarget(to);
  assert.deepEqual(plain.highlights, []);
  assert.equal(plain.isolate, undefined);
});

test("isolateDissolveNeeded is false when the destination has no isolate", () => {
  const from = slide("a");
  const to = slide("b", { highlights: ["FR"] });
  assert.equal(isolateDissolveNeeded(from, to), false);
});
