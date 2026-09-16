const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-hop-kind-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const {
  appearanceMismatch,
  coerceHopKinds,
  inferHopKind,
  morphPlatePx,
  plateFitsMorph,
  suggestedHopKind,
} = require(path.join(out, "types.js"));

const camera = { lat: 0, lon: 0, zoom: 4, bearing: 0, pitch: 0 };
function slide(overrides) {
  return {
    id: "s",
    title: "s",
    style: "positron",
    camera,
    highlights: ["SGP"],
    churches: [],
    cgShiftX: 0,
    cgShiftY: 0,
    includeSidePanels: false,
    ...overrides,
  };
}

// Parity with tests/test_maps_geo.py::test_infer_hop_kind_cut_on_highlight_colours.
test("same region highlights with no colours stay a Morph", () => {
  const from = slide({});
  const to = slide({ id: "t" });
  assert.deepEqual(appearanceMismatch(from, to), []);
  assert.equal(inferHopKind(from, to), "morph");
});

test("same colours in different key order / hex form stay a Morph", () => {
  const from = slide({
    highlights: ["SGP", "MYS"],
    highlightColours: { SGP: "#abc", MYS: "#0A84FF" },
  });
  const to = slide({
    id: "t",
    highlights: ["SGP", "MYS"],
    highlightColours: { MYS: "0a84ff", SGP: "#AABBCC" },
  });
  assert.deepEqual(appearanceMismatch(from, to), []);
  assert.equal(inferHopKind(from, to), "morph");
});

test("same highlight IDs with different colours become a Cut", () => {
  const from = slide({ highlightColours: { SGP: "#00aaff" } });
  const to = slide({ id: "t", highlightColours: { SGP: "#ff0000" } });
  assert.deepEqual(appearanceMismatch(from, to), ["highlightColours"]);
  assert.equal(inferHopKind(from, to), "cut");
});

test("missing colours vs an override become a Cut", () => {
  const from = slide({});
  const to = slide({ id: "t", highlightColours: { SGP: "#00aaff" } });
  assert.deepEqual(appearanceMismatch(from, to), ["highlightColours"]);
  assert.equal(inferHopKind(from, to), "cut");
});

test("no-fill vs a colour becomes a Cut", () => {
  const from = slide({ highlightColours: { SGP: "none" } });
  const to = slide({ id: "t", highlightColours: { SGP: "#00aaff" } });
  assert.deepEqual(appearanceMismatch(from, to), ["highlightColours"]);
  assert.equal(inferHopKind(from, to), "cut");
});

test("missing colours vs an empty map stay a Morph", () => {
  const from = slide({});
  const to = slide({ id: "t", highlightColours: {} });
  assert.deepEqual(appearanceMismatch(from, to), []);
  assert.equal(inferHopKind(from, to), "morph");
});

test("3D style is a Movie only while the Buildings layer is on", () => {
  const hidden = ["roadnames", "arrows", "labels", "waternames", "boundaries", "buildings"];
  const on = slide({ style: "buildings3d" });
  const off = slide({ style: "buildings3d", hiddenLayers: hidden });
  assert.equal(inferHopKind(on, slide({ id: "t", style: "buildings3d" })), "movie");
  assert.equal(inferHopKind(off, slide({ id: "t", style: "buildings3d", hiddenLayers: hidden })), "morph");
  assert.equal(
    inferHopKind(
      slide({ style: "borderlands", hiddenLayers: hidden }),
      slide({ id: "t", style: "borderlands", hiddenLayers: hidden })
    ),
    "morph"
  );
});

test("pitch still forces Movie when buildings are hidden", () => {
  const hidden = ["roadnames", "arrows", "labels", "waternames", "boundaries", "buildings"];
  const from = slide({ style: "buildings3d", hiddenLayers: hidden });
  const to = slide({
    id: "t",
    style: "buildings3d",
    hiddenLayers: hidden,
    camera: { ...camera, pitch: 20 },
  });
  assert.equal(inferHopKind(from, to), "movie");
});

test("zoom delta above 2 stays a Morph", () => {
  const from = slide({ camera: { ...camera, zoom: 4 } });
  const to = slide({ id: "t", camera: { ...camera, zoom: 8 } });
  assert.equal(inferHopKind(from, to), "morph");
  assert.equal(suggestedHopKind(from, to), "morph");
});

test("a wide-wall pan that used to exceed 8192 still morphs on a fitted plate", () => {
  const world = 512 * 2 ** 8;
  const from = slide({
    includeSidePanels: true,
    camera: { lat: 3, lon: 101, zoom: 8, bearing: 0, pitch: 0 },
  });
  const to = slide({
    id: "t",
    includeSidePanels: true,
    camera: { lat: 3, lon: 101 + (800 * 360) / world, zoom: 8, bearing: 0, pitch: 0 },
  });
  assert.equal(inferHopKind(from, to), "morph");
  assert.equal(suggestedHopKind(from, to), "morph");
  assert.equal(plateFitsMorph(from, to), true);
  const plate = morphPlatePx(from.camera, to.camera, 7680, 7680);
  assert.ok(plate);
  assert.ok(plate.w <= 8192 + 1e-6);
  assert.ok(plate.h <= 8192 + 1e-6);
});

test("a bearing change stays a Morph", () => {
  const from = slide({ camera: { ...camera, bearing: 0 } });
  const to = slide({ id: "t", camera: { ...camera, bearing: 30 } });
  assert.equal(inferHopKind(from, to), "morph");
  assert.equal(suggestedHopKind(from, to), "morph");
});

test("a bearing change grows the shared plate", () => {
  const from = slide({ camera: { lat: 3, lon: 101, zoom: 8, bearing: 0, pitch: 0 } });
  const aligned = slide({ id: "t", camera: { lat: 3, lon: 101, zoom: 8, bearing: 0, pitch: 0 } });
  const turned = slide({ id: "t", camera: { lat: 3, lon: 101, zoom: 8, bearing: 30, pitch: 0 } });
  const same = morphPlatePx(from.camera, aligned.camera, 7680, 7680);
  const rotated = morphPlatePx(from.camera, turned.camera, 7680, 7680);
  assert.ok(same && rotated);
  assert.ok(rotated.w * rotated.h > same.w * same.h);
});

test("coerceHopKinds upgrades Movie to Magic Move once gates clear", () => {
  const hidden = ["roadnames", "arrows", "labels", "waternames", "boundaries", "buildings"];
  const on = slide({ id: "s1", style: "buildings3d" });
  const on2 = slide({ id: "s2", style: "buildings3d" });
  const off = slide({ id: "s1", style: "buildings3d", hiddenLayers: hidden });
  const off2 = slide({ id: "s2", style: "buildings3d", hiddenLayers: hidden });
  const movieLink = { from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: false, flight: "arc" };
  const prev = { slides: [on, on2], links: [movieLink] };
  const next = coerceHopKinds({ slides: [off, off2], links: [movieLink] }, prev);
  assert.equal(next.links[0].kind, "morph");
  assert.equal(next.links[0].flight, undefined);
});

test("coerceHopKinds keeps an explicit Movie when Magic Move was already available", () => {
  const a = slide({ id: "s1" });
  const b = slide({ id: "s2" });
  const movieLink = { from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: false, flight: "arc" };
  const prev = { slides: [a, b], links: [movieLink] };
  const next = coerceHopKinds({ slides: [a, b], links: [movieLink] }, prev);
  assert.equal(next.links[0].kind, "movie");
  assert.equal(next.links[0].flight, "arc");
});
