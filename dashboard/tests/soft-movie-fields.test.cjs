const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-soft-movie-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { softMovieFields, appearanceMismatch } = require(path.join(out, "types.js"));

const baseCamera = { lat: 0, lon: 0, zoom: 4, bearing: 0, pitch: 0 };
function slide(overrides) {
  return {
    id: "s",
    title: "s",
    style: "positron",
    camera: baseCamera,
    highlights: [],
    churches: [],
    cgShiftX: 0,
    cgShiftY: 0,
    includeSidePanels: false,
    ...overrides,
  };
}

test("dest-isolated: isolate/highlights are soft", () => {
  const from = slide({});
  const to = slide({ highlights: ["FR"], isolate: { mode: "darken", strength: 0.6 } });
  const mismatch = new Set(appearanceMismatch(from, to));
  assert.ok(mismatch.has("isolate") && mismatch.has("highlights"));
  const soft = softMovieFields(from, to);
  assert.ok(soft.has("isolate") && soft.has("highlights"));
});

test("source-isolated: isolate/highlights are soft", () => {
  const from = slide({ highlights: ["FR"], isolate: { mode: "darken", strength: 0.6 } });
  const to = slide({});
  const mismatch = new Set(appearanceMismatch(from, to));
  assert.ok(mismatch.has("isolate") && mismatch.has("highlights"));
  const soft = softMovieFields(from, to);
  assert.ok(soft.has("isolate") && soft.has("highlights"));
});

test("style mismatch stays hard (not soft)", () => {
  const from = slide({ style: "positron" });
  const to = slide({ style: "liberty" });
  const mismatch = new Set(appearanceMismatch(from, to));
  assert.ok(mismatch.has("style"));
  const soft = softMovieFields(from, to);
  assert.ok(!soft.has("style"));
});
