const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-region-pick-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/regionPick.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { REGION_PREFETCH_MAX, admin1CodeFromHits, regionCountriesFromHits, uniqueAdmin0Codes } = require(path.join(out, "regionPick.js"));

const hit = (code) => ({ properties: { ADM0_A3: code } });

test("uniqueAdmin0Codes keeps first-seen order and drops empties", () => {
  assert.deepEqual(uniqueAdmin0Codes([hit("IDN"), hit("MYS"), hit("IDN"), { properties: {} }, hit("BRN")]), ["IDN", "MYS", "BRN"]);
});

test("a water-centred Borneo frame still loads every country on screen", () => {
  assert.deepEqual(
    regionCountriesFromHits([hit("MYS"), hit("IDN"), hit("BRN"), hit("SGP")], []),
    ["MYS", "IDN", "BRN", "SGP"]
  );
});

test("a world view keeps the camera country and caps the rest", () => {
  const visible = Array.from({ length: REGION_PREFETCH_MAX + 4 }, (_, i) => hit(`C${String(i).padStart(2, "0")}`));
  const got = regionCountriesFromHits(visible, [hit("C12")]);
  assert.equal(got.length, REGION_PREFETCH_MAX);
  assert.equal(got[0], "C12");
  assert.ok(!got.includes("C16"));
});

test("MapView queries the visible band, not the FOV-widened canvas", () => {
  const src = fs.readFileSync(path.join(root, "src/maps/MapView.tsx"), "utf8");
  assert.match(src, /\[\[0, L\.bandTop\], \[width, bottom\]\]/);
  assert.match(src, /bandInnerH/);
});

test("admin1CodeFromHits reads the top hit", () => {
  assert.equal(admin1CodeFromHits([{ properties: { adm1_code: "MYS-1186" } }]), "MYS-1186");
  assert.equal(admin1CodeFromHits([]), "");
});
