const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-conflict-freeze-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/commit.ts"), path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { commitCamera, shouldPublishThumb, shouldReconcileThumb } = require(path.join(out, "commit.js"));

const camera = { lat: 1, lon: 2, zoom: 8, bearing: 0, pitch: 0 };
const doc = (cg) => ({
  defaultStyle: "positron", crop: "center+cg", exportLw: true, exportCg: true, exportDsk: false, hiddenLayers: [], cachedCountries: [], assets: [], links: [],
  slides: [{
    id: "s1", title: "Old", style: "positron", camera: { lat: 0, lon: 0, zoom: 5, bearing: 0, pitch: 0 },
    highlights: [], churches: [], cgShiftX: 0, cgShiftY: 0, includeSidePanels: false,
    cg: cg ? { camera: { lat: 0, lon: 0, zoom: 5, bearing: 0, pitch: 0 }, style: "positron", highlights: [], churches: [] } : undefined,
  }],
});

test("commitCamera returns null while a conflict is pending", () => {
  const result = commitCamera(doc(false), "s1", "lw", camera, { frozen: true, previewing: false });
  assert.equal(result, null);
});

test("commitCamera returns null while previewing", () => {
  const result = commitCamera(doc(false), "s1", "lw", camera, { frozen: false, previewing: true });
  assert.equal(result, null);
});

test("commitCamera writes the cg camera when audience is cg and the slide has a cg view", () => {
  const result = commitCamera(doc(true), "s1", "cg", camera, { frozen: false, previewing: false });
  assert.ok(result);
  assert.deepEqual(result.slides[0].cg.camera, camera);
  assert.deepEqual(result.slides[0].camera, { lat: 0, lon: 0, zoom: 5, bearing: 0, pitch: 0 });
});

test("shouldPublishThumb rejects a thumbnail once the save conflict freezes the doc", () => {
  assert.equal(shouldPublishThumb({ frozen: true, tokenStillValid: true, sameJob: true, sameView: true }), false);
});

test("shouldPublishThumb rejects a stale capture whose token was superseded", () => {
  assert.equal(shouldPublishThumb({ frozen: false, tokenStillValid: false, sameJob: true, sameView: true }), false);
});

test("shouldPublishThumb rejects a capture whose slide navigated away underneath it", () => {
  assert.equal(shouldPublishThumb({ frozen: false, tokenStillValid: true, sameJob: true, sameView: false }), false);
});

test("shouldPublishThumb allows publishing when nothing changed underneath it", () => {
  assert.equal(shouldPublishThumb({ frozen: false, tokenStillValid: true, sameJob: true, sameView: true }), true);
});

test("shouldReconcileThumb allows reconciling a committed upload even after navigating away", () => {
  assert.equal(shouldReconcileThumb({ frozen: false, sameJob: true }), true);
});

test("shouldReconcileThumb rejects reconciling once the save conflict freezes the doc", () => {
  assert.equal(shouldReconcileThumb({ frozen: true, sameJob: true }), false);
});

test("shouldReconcileThumb rejects reconciling a job that is no longer current", () => {
  assert.equal(shouldReconcileThumb({ frozen: false, sameJob: false }), false);
});
