const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { admin1Countries, admin1FeaturesInPlay, admin1Name, admin1PaintExpression, highlightedCountries, loadAdmin1 } = require(path.join(out, "overlays.js"));

function feature(country, code, name, type) {
  return { properties: { adm0_a3: country, adm1_code: code, name, type_en: type }, geometry: null };
}

/** `loadAdmin1` is the only way into the module's private cache, so seed through a stubbed fetch. */
async function seed(code, features) {
  global.fetch = async () => ({ ok: true, json: async () => ({ type: "FeatureCollection", features }) });
  await loadAdmin1(code);
}

test("the admin1 fill expression is an `in` over a literal id list, never feature-state", () => {
  const expression = admin1PaintExpression(["A1:MYS-1186", "A1:MYS-1187"], 0.4);
  assert.deepEqual(expression, ["case", ["in", ["get", "adm1_code"], ["literal", ["MYS-1186", "MYS-1187"]]], 0.4, 0]);
  assert.ok(!JSON.stringify(expression).includes("feature-state"));
});

test("a region still paints when its parent country is highlighted, so it can sit on top", () => {
  const expression = admin1PaintExpression(["MYS", "A1:MYS-1186", "A1:IDN-1"], 0.4);
  assert.deepEqual(expression[1][2], ["literal", ["MYS-1186", "IDN-1"]]);
});

test("the admin1 line expression carries the same ids at the line opacity", () => {
  const expression = admin1PaintExpression(["A1:MYS-1186"], 0.9);
  assert.deepEqual(expression, ["case", ["in", ["get", "adm1_code"], ["literal", ["MYS-1186"]]], 0.9, 0]);
});

test("bare country codes contribute no ids to the region expression", () => {
  assert.deepEqual(admin1PaintExpression(["MYS", "IDN"], 0.4)[1][2], ["literal", []]);
});

test("a repeated A1: id is not duplicated in the region expression", () => {
  assert.deepEqual(admin1PaintExpression(["A1:MYS-1186", "A1:MYS-1186"], 0.4)[1][2], ["literal", ["MYS-1186"]]);
});

test("no-fill admin1 ids are omitted from the paint list", () => {
  assert.deepEqual(
    admin1PaintExpression(["A1:MYS-1186", "A1:MYS-1187"], 0.4, { "A1:MYS-1186": "none" })[1][2],
    ["literal", ["MYS-1187"]]
  );
});

test("a no-fill country does not suppress its filled child regions", () => {
  assert.deepEqual(
    admin1PaintExpression(["MYS", "A1:MYS-1186"], 0.4, { MYS: "none" })[1][2],
    ["literal", ["MYS-1186"]]
  );
});

test("admin1Countries derives the country from the adm1_code prefix", () => {
  assert.deepEqual(admin1Countries(["A1:MYS-1186"]), ["MYS"]);
  assert.deepEqual(admin1Countries(["MYS", "IDN"]), []);
  assert.deepEqual(admin1Countries(["A1:MYS-1186", "A1:MYS-1187", "A1:IDN-1"]).sort(), ["IDN", "MYS"]);
});

test("admin1Countries handles the punctuated NE codes", () => {
  assert.deepEqual(admin1Countries(["A1:GAZ+00?"]), ["GAZ"]);
});

test("admin1Name resolves a loaded region and disambiguates a duplicate name with type_en", async () => {
  await seed("PHL", [
    feature("PHL", "PHL-1", "Cebu", "Province"),
    feature("PHL", "PHL-2", "Cebu", "Highly Urbanized City"),
    feature("PHL", "PHL-3", "Bohol", "Province"),
  ]);

  assert.equal(admin1Name("A1:PHL-1"), "Cebu (Province)");
  assert.equal(admin1Name("A1:PHL-2"), "Cebu (Highly Urbanized City)");
  assert.equal(admin1Name("A1:PHL-3"), "Bohol");
});

test("admin1Name falls back to the raw code for an unloaded region", () => {
  assert.equal(admin1Name("A1:ZZZ-9"), "ZZZ-9");
});

test("admin1FeaturesInPlay returns only the countries a highlight names, bare or A1:", async () => {
  await seed("MYS", [feature("MYS", "MYS-1186", "Sabah", "State")]);
  await seed("IDN", [feature("IDN", "IDN-1", "Aceh", "Province")]);

  const codes = admin1FeaturesInPlay(["A1:MYS-1186"]).map((f) => f.properties.adm1_code);
  assert.ok(codes.includes("MYS-1186"));
  assert.ok(!codes.includes("IDN-1"), "IDN is cached but not highlighted, so it must not appear");
});

test("admin1FeaturesInPlay ignores a country that is merely cached and not highlighted", async () => {
  await seed("PHL", [feature("PHL", "PHL-1", "Cebu", "Province")]);

  const codes = admin1FeaturesInPlay(["A1:MYS-1186"]).map((f) => f.properties.adm1_code);
  assert.ok(!codes.includes("PHL-1"));
});

test("admin1FeaturesInPlay includes a bare-highlighted country's cached admin-1, for border cuts", async () => {
  const codes = admin1FeaturesInPlay(["IDN", "A1:MYS-1186"]).map((f) => f.properties.adm1_code);
  assert.ok(codes.includes("IDN-1"), "IDN is cached (from an earlier seed) and bare-highlighted");
  assert.ok(codes.includes("MYS-1186"));
});

test("highlightedCountries names every country a highlight carries, bare or A1:, once", () => {
  assert.deepEqual(highlightedCountries(["IDN", "A1:MYS-1186"]).sort(), ["IDN", "MYS"]);
  assert.deepEqual(highlightedCountries(["MYS", "A1:MYS-1186"]), ["MYS"]);
});

test("IDN + A1:MYS: once IDN's admin-1 is loaded, admin1FeaturesInPlay pins IDN's own rings", async () => {
  await seed("IDN", [feature("IDN", "IDN-1", "Aceh", "Province")]);
  await seed("MYS", [feature("MYS", "MYS-1186", "Sabah", "State")]);

  const codes = admin1FeaturesInPlay(["IDN", "A1:MYS-1186"]).map((f) => f.properties.adm1_code);
  assert.deepEqual(codes.sort(), ["IDN-1", "MYS-1186"], "IDN gets its own admin-1 rings once loaded, matching highlightedCountries");
});
