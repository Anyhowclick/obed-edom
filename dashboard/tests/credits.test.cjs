const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "credits-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/credits.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
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
