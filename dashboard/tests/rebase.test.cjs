const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-rebase-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/rebase.ts"), path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { rebaseMapsDocument } = require(path.join(out, "rebase.js"));

const camera = (zoom = 8) => ({ lat: 1, lon: 2, zoom, bearing: 0, pitch: 0 });
const church = (id, extra = {}) => ({ id, name: id, lat: 1, lon: 2, kind: "dot", color: "#fff", ...extra });
const slide = (overrides = {}) => ({
  id: "s1", title: "Old", style: "positron", camera: camera(), highlights: [], churches: [], cgShiftX: 0, cgShiftY: 0,
  includeSidePanels: false, ...overrides,
});
const doc = (overrides = {}) => ({
  defaultStyle: "positron", crop: "center+cg", exportLw: true, exportCg: true, exportDsk: false, hiddenLayers: [], cachedCountries: [],
  assets: [], links: [], slides: [slide()], ...overrides,
});

test("production rebase retains a remote church with a local same-slide camera edit", () => {
  const base = doc();
  const local = doc({ slides: [slide({ camera: camera(9) })] });
  const remote = doc({ slides: [slide({ churches: [church("p1")] })] });
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.equal(result.value.slides[0].camera.zoom, 9);
  assert.equal(result.value.slides[0].churches[0].id, "p1");
});

test("production rebase preserves disjoint CG and link edits", () => {
  const base = doc({ links: [{ from: "s1", to: "s2", kind: "movie", duration: 2, playWithoutClick: false }], slides: [slide(), slide({ id: "s2" })] });
  const local = structuredClone(base);
  local.slides[0].cg = { camera: camera(10), style: "positron", highlights: [], churches: [], cgShiftX: 0, cgShiftY: 0, includeSidePanels: false };
  const remote = structuredClone(base);
  remote.links[0].duration = 5;
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.equal(result.value.slides[0].cg.camera.zoom, 10);
  assert.equal(result.value.links[0].duration, 5);
});

test("production rebase accepts an unchanged remote when local deletes a base church", () => {
  const base = doc({ slides: [slide({ churches: [church("p1")] })] });
  const local = doc();
  const remote = structuredClone(base);
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.deepEqual(result.value.slides[0].churches, []);
});

test("production rebase reports a delete/edit conflict without losing the local candidate", () => {
  const base = doc({ slides: [slide({ churches: [church("p1")] })] });
  const local = doc();
  const remote = doc({ slides: [slide({ churches: [church("p1", { name: "Remote" })] })] });
  const result = rebaseMapsDocument(base, local, remote);
  assert.ok(result.conflicts.some((item) => item.includes("delete/edit")));
  assert.deepEqual(result.value.slides[0].churches, []);
});

test("production rebase rejects duplicate keyed arrays before equality shortcuts", () => {
  const invalid = doc({ slides: [slide(), slide()] });
  const result = rebaseMapsDocument(invalid, invalid, invalid);
  assert.ok(result.conflicts.some((item) => item.includes("duplicate key")));
});

test("assets are server-authoritative and dangling local landmark references conflict", () => {
  const base = doc();
  const local = doc({ slides: [slide({ churches: [church("p1", { kind: "landmark", assetId: "missing" })] })] });
  const remote = doc({ assets: [{ id: "a1", version: "v1", width: 10, height: 10 }] });
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.value.assets, remote.assets);
  assert.ok(result.conflicts.some((item) => item.endsWith("assetId")));
});

test("production rebase retains a local slide order when the remote order is unchanged", () => {
  const base = doc({ slides: [slide(), slide({ id: "s2" })] });
  const local = doc({ slides: [slide({ id: "s2" }), slide()] });
  const remote = structuredClone(base);
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.deepEqual(result.value.slides.map((item) => item.id), ["s2", "s1"]);
});

test("null remains distinct from a missing field", () => {
  const base = doc({ cachedCountries: [] });
  const local = doc({ cachedCountries: [] });
  local.slides[0].cg = null;
  const remote = structuredClone(base);
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.equal(result.value.slides[0].cg, null);
});

test("production rebase retains local appended slides, links, and churches during an ACK", () => {
  const base = doc();
  const local = doc({
    slides: [slide({ churches: [church("p1")] }), slide({ id: "s2" })],
    links: [{ from: "s1", to: "s2", kind: "cut", duration: 1, playWithoutClick: false }],
  });
  const remote = structuredClone(base);
  const result = rebaseMapsDocument(base, local, remote);
  assert.deepEqual(result.conflicts, []);
  assert.deepEqual(result.value.slides.map((item) => item.id), ["s1", "s2"]);
  assert.equal(result.value.slides[0].churches[0].id, "p1");
  assert.equal(result.value.links[0].to, "s2");
});
