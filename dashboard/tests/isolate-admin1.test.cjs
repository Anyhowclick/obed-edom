const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { countryClipRings, isolateMaskGeometry } = require(path.join(out, "isolate.js"));

const MYS_50M = [[0, 0], [10, 0], [10, 10], [0, 0]];
const SABAH = [[6, 6], [10, 6], [10, 10], [6, 6]];
const SARAWAK = [[0, 0], [6, 0], [6, 6], [0, 0]];
const IDN_50M = [[0, -10], [10, -10], [10, 0], [0, -10]];
const IDN_KAL = [[0, -10], [5, -10], [5, 0], [0, -10]];

function admin0(code, ring) {
  return { properties: { ADM0_A3: code }, geometry: { type: "Polygon", coordinates: [ring] } };
}

function admin1(country, code, ring) {
  return {
    properties: { adm0_a3: country, adm1_code: code },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

const admin0Features = [admin0("MYS", MYS_50M), admin0("IDN", IDN_50M)];
const admin1Features = [admin1("MYS", "MYS-1186", SABAH), admin1("MYS", "MYS-1187", SARAWAK)];

test("an A1: id selects its admin-1 rings by adm1_code", () => {
  assert.deepEqual(countryClipRings(admin0Features, ["A1:MYS-1186"], admin1Features), [SABAH]);
});

test("a bare code still selects admin-0 rings", () => {
  assert.deepEqual(countryClipRings(admin0Features, ["MYS"], admin1Features), [MYS_50M]);
});

test("mixed country and region highlights concatenate", () => {
  const rings = countryClipRings(admin0Features, ["IDN", "A1:MYS-1186"], admin1Features);
  assert.deepEqual(rings, [IDN_50M, SABAH]);
});

test("a region whose country is also highlighted is dropped as redundant, but forces that country onto its admin-1 rings", () => {
  const rings = countryClipRings(admin0Features, ["MYS", "A1:MYS-1186"], admin1Features);
  assert.deepEqual(
    rings,
    [SABAH, SARAWAK],
    "the region is nested in its own country and dropped, but MYS still uses its loaded admin-1 rings, not the 50m outline"
  );
});

test("border cut: a highlighted country beside a highlighted region comes from its admin-1 rings", () => {
  const withIdn = [...admin1Features, admin1("IDN", "IDN-1", IDN_KAL)];
  const rings = countryClipRings(admin0Features, ["IDN", "A1:MYS-1186"], withIdn);
  assert.ok(!rings.includes(IDN_50M), "IDN must not keep its 50m outline while a region is in play");
  assert.deepEqual(rings, [SABAH, IDN_KAL]);
});

test("border cut leaves countries without loaded admin-1 on their admin-0 rings", () => {
  const rings = countryClipRings(admin0Features, ["IDN", "A1:MYS-1186"], admin1Features);
  assert.deepEqual(rings, [IDN_50M, SABAH]);
});

test("with no A1: id the result is identical to the admin-0-only result", () => {
  const withAdmin1 = countryClipRings(admin0Features, ["MYS", "IDN"], admin1Features);
  const without = countryClipRings(admin0Features, ["MYS", "IDN"]);
  assert.deepEqual(withAdmin1, without);
  assert.deepEqual(without, [MYS_50M, IDN_50M]);
});

test("an unknown A1: id yields no rings", () => {
  assert.deepEqual(countryClipRings(admin0Features, ["A1:MYS-9999"], admin1Features), []);
});

test("adm1_code is matched verbatim, never case folded", () => {
  const features = [admin1("MYS", "MYS-a1", SABAH)];
  assert.deepEqual(countryClipRings([], ["A1:MYS-a1"], features), [SABAH]);
  assert.deepEqual(countryClipRings([], ["A1:MYS-A1"], features), []);
});

test("isolateMaskGeometry forwards admin-1 into the world-ring holes", () => {
  const mask = isolateMaskGeometry(admin0Features, ["A1:MYS-1186"], admin1Features);
  assert.equal(mask.geometry.coordinates.length, 2);
  assert.deepEqual(mask.geometry.coordinates[1], SABAH);
});
