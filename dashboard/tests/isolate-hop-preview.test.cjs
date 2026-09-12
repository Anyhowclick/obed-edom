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
  "--outDir", out, path.join(root, "src/maps/commit.ts"), path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { hopPreviewViews } = require(path.join(out, "commit.js"));

const camera = (lat) => ({ lat, lon: 0, zoom: 5, bearing: 0, pitch: 0 });
const slide = (id, overrides) => ({
  id, title: id, style: "positron", camera: camera(0),
  highlights: [], churches: [], cgShiftX: 0, cgShiftY: 0, includeSidePanels: false,
  ...overrides,
});

test("hopPreviewViews: during is the source view, landing is the destination view", () => {
  const from = slide("a", { camera: camera(1) });
  const to = slide("b", { camera: camera(2), isolate: { mode: "darken", strength: 0.65 } });
  const { during, landing } = hopPreviewViews(from, to, "lw");
  assert.equal(during.id, "a");
  assert.equal(landing.id, "b");
  assert.equal(during.isolate, undefined);
  assert.equal(landing.isolate.mode, "darken");
});

function renderedIsolate(renderedView, active) {
  return renderedView ? renderedView.isolate : active.isolate;
}

test("a previewed view without isolate never inherits the selected slide's isolate", () => {
  const active = slide("active", { isolate: { mode: "darken", strength: 0.65 } });
  const renderedView = slide("during", {});
  assert.equal(renderedIsolate(renderedView, active), undefined);
});

test("with no previewed view, the selected slide's isolate is used", () => {
  const active = slide("active", { isolate: { mode: "darken", strength: 0.65 } });
  assert.equal(renderedIsolate(null, active).mode, "darken");
});
