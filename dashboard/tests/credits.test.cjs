const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { creditLine, creditLines, TERRAIN_ATTRIBUTION, OSM_ATTRIBUTION, MAPTILER_ATTRIBUTION } = require(path.join(out, "credits.js"));

test("creditLine plain positron", () => {
  assert.equal(creditLine("positron", false), OSM_ATTRIBUTION);
});

test("creditLine toner adds MapTiler", () => {
  assert.ok(creditLine("toner-lines", false).includes(MAPTILER_ATTRIBUTION));
});

test("creditLine terrain adds elevation attribution", () => {
  assert.ok(creditLine("positron", true).includes(TERRAIN_ATTRIBUTION));
});

test("creditLines unions and dedupes across views", () => {
  const lines = creditLines([{ style: "positron" }, { style: "toner", hillshade: true }, { style: "toner" }]);
  assert.deepEqual(lines, [OSM_ATTRIBUTION, MAPTILER_ATTRIBUTION, TERRAIN_ATTRIBUTION]);
});

test("creditLines of empty array is empty", () => {
  assert.deepEqual(creditLines([]), []);
});
