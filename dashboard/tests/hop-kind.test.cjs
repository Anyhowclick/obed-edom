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
  churchLabelColor,
  coerceHopKinds,
  inferHopKind,
  morphPlateNativePx,
  morphPlatePx,
  plateFitsMorph,
  suggestedHopKind,
} = require(path.join(out, "types.js"));
const { highlightMismatch } = require(path.join(out, "highlight.js"));

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

test("a two-stop zoom still morphs", () => {
  const from = slide({ camera: { ...camera, zoom: 6 } });
  const to = slide({ id: "t", camera: { ...camera, zoom: 8 } });
  assert.equal(inferHopKind(from, to), "morph");
  assert.equal(suggestedHopKind(from, to), "morph");
  assert.equal(plateFitsMorph(from, to), true);
});

test("a four-stop zoom is a Movie — the Keynote object would be ~61k pt", () => {
  const from = slide({ camera: { ...camera, zoom: 4 } });
  const to = slide({ id: "t", camera: { ...camera, zoom: 8 } });
  assert.equal(inferHopKind(from, to), "morph");
  assert.equal(plateFitsMorph(from, to), false);
  assert.equal(suggestedHopKind(from, to), "movie");
  const native = morphPlateNativePx(from.camera, to.camera, 3840, 3840);
  assert.ok(native);
  assert.ok(Math.max(native.w, native.h) > 16384);
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

test("a bearing change pads the shared plate to the LW circumcircle", () => {
  const from = slide({ camera: { lat: 3, lon: 101, zoom: 8, bearing: 0, pitch: 0 } });
  const turned = slide({ id: "t", camera: { lat: 3, lon: 101, zoom: 8, bearing: 30, pitch: 0 } });
  const rotated = morphPlatePx(from.camera, turned.camera, 7680, 7680);
  assert.ok(rotated);
  // hypot(7680/2, 1080/2) * 2 ≈ 7756 — enough to cover the frame after Keynote rotation.
  assert.ok(rotated.h >= 7700);
  assert.ok(rotated.w >= 7700);
});

test("a zoom-only hop keeps the camera AABB instead of a circumcircle square", () => {
  const from = slide({ camera: { lat: 3, lon: 101, zoom: 6, bearing: 0, pitch: 0 } });
  const to = slide({ id: "t", camera: { lat: 3.2, lon: 101.2, zoom: 8, bearing: 0, pitch: 0 } });
  const plate = morphPlatePx(from.camera, to.camera, 3840, 3840);
  assert.ok(plate);
  assert.ok(plate.w / plate.h > 2, `zoom-only plate should stay wide, got ${plate.w}x${plate.h}`);
});

test("highlightMismatch lists only the regions and colours that differ", () => {
  const from = slide({
    highlights: ["IDN", "A1:IDN+KA"],
    highlightColours: { IDN: "#0a84ff", "A1:IDN+KA": "#f5d90a" },
  });
  const to = slide({
    id: "t",
    highlights: ["IDN", "A1:IDN+SB"],
    highlightColours: { IDN: "#e8772a", "A1:IDN+SB": "#f5d90a" },
  });
  const pills = highlightMismatch(from, to);
  assert.deepEqual(pills.leave.map((item) => item.code), ["A1:IDN+KA"]);
  assert.deepEqual(pills.join.map((item) => item.code), ["A1:IDN+SB"]);
  assert.equal(pills.recolour.length, 1);
  assert.equal(pills.recolour[0].code, "IDN");
  assert.equal(pills.recolour[0].from.hex, "#0a84ff");
  assert.equal(pills.recolour[0].to.hex, "#e8772a");
});

test("isolate on vs off is a Cut", () => {
  const from = slide({});
  const to = slide({ id: "t", isolate: { mode: "darken", strength: 0.65 } });
  assert.deepEqual(appearanceMismatch(from, to), ["isolate"]);
  assert.equal(inferHopKind(from, to), "cut");
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

test("churchLabelColor defaults to gold-red and normalises a custom hex", () => {
  assert.equal(churchLabelColor(undefined), "#ee220c");
  assert.equal(churchLabelColor({}), "#ee220c");
  assert.equal(churchLabelColor({ labelColor: "#112" }), "#111122");
  assert.equal(churchLabelColor({ labelColor: "AABBCC" }), "#aabbcc");
});
