const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { isolateDissolveNeeded, plainIsolateTarget, movieAppearanceMismatch } = require(path.join(out, "types.js"));

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

test("isolateDissolveNeeded is false when the destination has isolate but no highlights", () => {
  const from = slide("a");
  const to = slide("b", { isolate: { mode: "darken", strength: 0.65 } });
  assert.equal(isolateDissolveNeeded(from, to), false);
});

test("isolateDissolveNeeded is false when the source is already isolated", () => {
  const iso = { mode: "darken", strength: 0.65 };
  const from = slide("a", { highlights: ["FR"], isolate: iso });
  const to = slide("b", { highlights: ["FR"], isolate: iso });
  assert.equal(isolateDissolveNeeded(from, to), false);
  assert.equal(movieAppearanceMismatch(from, to), false);
});

test("movieAppearanceMismatch is false when only isolate/highlights differ", () => {
  const from = slide("a");
  const to = slide("b", { highlights: ["FR"], isolate: { mode: "darken", strength: 0.65 } });
  assert.equal(movieAppearanceMismatch(from, to), false);
});

test("plainIsolateTarget drops highlightColours with the highlight set", () => {
  const to = slide("b", {
    highlights: ["FRA"],
    highlightColours: { FRA: "#00aaff" },
    isolate: { mode: "darken", strength: 0.65 },
  });
  const plain = plainIsolateTarget(to);
  assert.deepEqual(plain.highlights, []);
  assert.equal(plain.isolate, undefined);
  assert.equal(plain.highlightColours, undefined);
});

test("movieAppearanceMismatch is false for dest-isolated FRA with a custom colour", () => {
  const from = slide("a");
  const to = slide("b", {
    highlights: ["FRA"],
    highlightColours: { FRA: "#00aaff" },
    isolate: { mode: "darken", strength: 0.65 },
  });
  assert.equal(movieAppearanceMismatch(from, to), false);
});

test("movieAppearanceMismatch is true when style also differs", () => {
  const from = slide("a");
  const to = slide("b", { style: "buildings3d", highlights: ["FR"], isolate: { mode: "darken", strength: 0.65 } });
  assert.equal(movieAppearanceMismatch(from, to), true);
});
