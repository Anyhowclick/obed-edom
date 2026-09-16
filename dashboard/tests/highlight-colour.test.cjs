const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-highlight-colour-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/highlight.ts"), path.join(root, "src/maps/overlays.ts"), path.join(root, "src/maps/adminSync.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const {
  DEFAULT_HIGHLIGHT_COLOUR,
  HIGHLIGHT_NO_FILL,
  filledHighlights,
  highlightColourExpression,
  isHighlightNone,
  normaliseHighlightColour,
  parseHighlightColours,
  parseHighlightColourValue,
  pruneHighlightColours,
  highlightColoursKey,
  setHighlightColour,
  contrastInk,
} = require(path.join(out, "highlight.js"));
const { ensureAdmin0Highlights, applyHighlightColour } = require(path.join(out, "overlays.js"));

function fakeMap(layers = new Map()) {
  const sources = new Map();
  const calls = [];
  return {
    calls,
    layers,
    getSource: (id) => sources.get(id),
    addSource: (id, spec) => {
      calls.push(["addSource", id]);
      sources.set(id, { ...spec, setData: (data) => calls.push(["setData", id, data]) });
    },
    removeSource: (id) => {
      calls.push(["removeSource", id]);
      sources.delete(id);
    },
    getLayer: (id) => layers.get(id),
    addLayer: (spec) => {
      calls.push(["addLayer", spec]);
      layers.set(spec.id, spec);
    },
    removeLayer: (id) => {
      calls.push(["removeLayer", id]);
      layers.delete(id);
    },
    setPaintProperty: (id, prop, value) => calls.push(["setPaintProperty", id, prop, value]),
    setLayoutProperty: (id, prop, value) => calls.push(["setLayoutProperty", id, prop, value]),
    getStyle: () => ({ layers: [] }),
  };
}

global.fetch = async (url) => {
  if (url === "/api/maps/ne/admin0") {
    return { ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) };
  }
  return { ok: false, json: async () => null };
};

test("contrastInk uses WCAG luminance so default orange gets dark ink", () => {
  assert.equal(contrastInk("#e8772a"), "#0D1402");
  assert.equal(contrastInk("#000000"), "#FFFFFF");
  assert.equal(contrastInk("#ffffff"), "#0D1402");
});

test("normaliseHighlightColour accepts hex with or without #, rejects garbage", () => {
  assert.equal(normaliseHighlightColour("#0A84FF"), "#0a84ff");
  assert.equal(normaliseHighlightColour("0A84FF"), "#0a84ff");
  assert.equal(normaliseHighlightColour("#abc"), "#aabbcc");
  assert.equal(normaliseHighlightColour("nope"), DEFAULT_HIGHLIGHT_COLOUR);
  assert.equal(normaliseHighlightColour(""), DEFAULT_HIGHLIGHT_COLOUR);
  assert.equal(normaliseHighlightColour(undefined), DEFAULT_HIGHLIGHT_COLOUR);
});

test("ensureAdmin0Highlights paints admin0 layers with the current highlight colour", async () => {
  setHighlightColour("#0a84ff");
  const map = fakeMap();
  await ensureAdmin0Highlights(map, [], "positron");
  const fill = map.layers.get("admin0-fill");
  const line = map.layers.get("admin0-line");
  assert.equal(fill.paint["fill-color"], "#0a84ff");
  assert.equal(line.paint["line-color"], "#0a84ff");
  setHighlightColour(DEFAULT_HIGHLIGHT_COLOUR);
});

test("applyHighlightColour repaints only the layers that already exist", () => {
  const map = fakeMap(new Map([
    ["admin0-fill", { id: "admin0-fill" }],
    ["admin0-line", { id: "admin0-line" }],
  ]));
  applyHighlightColour(map, "#123456");
  const setPaintCalls = map.calls.filter((c) => c[0] === "setPaintProperty");
  assert.equal(setPaintCalls.length, 2);
  assert.deepEqual(setPaintCalls, [
    ["setPaintProperty", "admin0-fill", "fill-color", "#123456"],
    ["setPaintProperty", "admin0-line", "line-color", "#123456"],
  ]);
  setHighlightColour(DEFAULT_HIGHLIGHT_COLOUR);
});

test("highlightColourExpression is a plain colour without overrides", () => {
  assert.equal(highlightColourExpression("ADM0_A3", "#e8772a"), "#e8772a");
});

test("highlightColourExpression matches ADM0 codes and ignores admin-1 keys", () => {
  assert.deepEqual(
    highlightColourExpression("ADM0_A3", "#e8772a", { MYS: "#00aaff", "A1:MYS-1186": "#112233" }),
    ["match", ["get", "ADM0_A3"], "MYS", "#00aaff", "#e8772a"]
  );
});

test("highlightColourExpression strips the A1: prefix for admin-1", () => {
  assert.deepEqual(
    highlightColourExpression("adm1_code", "#e8772a", { MYS: "#00aaff", "A1:MYS-1186": "#112233" }),
    ["match", ["get", "adm1_code"], "MYS-1186", "#112233", "#e8772a"]
  );
});

test("parseHighlightColours accepts none and skips it in colour expressions", () => {
  assert.equal(isHighlightNone("none"), true);
  assert.equal(isHighlightNone("NONE"), true);
  assert.equal(parseHighlightColourValue("none"), HIGHLIGHT_NO_FILL);
  assert.deepEqual(parseHighlightColours({ MYS: "none", SGP: "#00AAFF" }), { MYS: "none", SGP: "#00aaff" });
  assert.deepEqual(filledHighlights(["MYS", "SGP"], { MYS: "none" }), ["SGP"]);
  assert.deepEqual(highlightColourExpression("ADM0_A3", "#e8772a", { MYS: "none", SGP: "#00aaff" }), [
    "match",
    ["get", "ADM0_A3"],
    "SGP",
    "#00aaff",
    "#e8772a",
  ]);
  assert.equal(highlightColoursKey({ MYS: "none", SGP: "#0A84FF" }), "MYS:none,SGP:#0a84ff");
});

test("pruneHighlightColours drops colours whose highlight was removed", () => {
  assert.deepEqual(pruneHighlightColours(["MYS"], { MYS: "#00aaff", SGP: "#112233" }), { MYS: "#00aaff" });
  assert.equal(pruneHighlightColours([], { MYS: "#00aaff" }), undefined);
});

test("highlightColoursKey is order-independent and normalises hex", () => {
  assert.equal(highlightColoursKey({ SGP: "#0A84FF", MYS: "#abc" }), "MYS:#aabbcc,SGP:#0a84ff");
  assert.equal(highlightColoursKey({ MYS: "#AABBCC", SGP: "0a84ff" }), "MYS:#aabbcc,SGP:#0a84ff");
  assert.equal(highlightColoursKey(undefined), "");
  assert.equal(highlightColoursKey({}), "");
});

test("applyHighlightColour paints match expressions when overrides are present", () => {
  const map = fakeMap(new Map([
    ["admin0-fill", { id: "admin0-fill" }],
    ["admin0-line", { id: "admin0-line" }],
  ]));
  applyHighlightColour(map, "#123456", { MYS: "#00AAFF" });
  const setPaintCalls = map.calls.filter((c) => c[0] === "setPaintProperty");
  assert.deepEqual(setPaintCalls, [
    ["setPaintProperty", "admin0-fill", "fill-color", ["match", ["get", "ADM0_A3"], "MYS", "#00aaff", "#123456"]],
    ["setPaintProperty", "admin0-line", "line-color", ["match", ["get", "ADM0_A3"], "MYS", "#00aaff", "#123456"]],
  ]);
  setHighlightColour(DEFAULT_HIGHLIGHT_COLOUR);
});

test("applyHighlightColour repaints all four layers once admin1 is also present", () => {
  const map = fakeMap(new Map([
    ["admin0-fill", { id: "admin0-fill" }],
    ["admin0-line", { id: "admin0-line" }],
    ["admin1-fill", { id: "admin1-fill" }],
    ["admin1-line", { id: "admin1-line" }],
  ]));
  applyHighlightColour(map, "#abcdef");
  const setPaintCalls = map.calls.filter((c) => c[0] === "setPaintProperty");
  assert.equal(setPaintCalls.length, 4);
  setHighlightColour(DEFAULT_HIGHLIGHT_COLOUR);
});
