const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-manual-rows-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/manualRows.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { blankRow, rowIsEmpty, validateManualRows } = require(path.join(out, "manualRows.js"));

function row(overrides) {
  return { ...blankRow(0), ...overrides };
}

test("blankRow starts empty with a dropPin kind", () => {
  const fresh = blankRow(3);
  assert.equal(fresh.key, "r3");
  assert.equal(fresh.kind, "dropPin");
  assert.equal(rowIsEmpty(fresh), true);
});

test("rowIsEmpty ignores the kind select", () => {
  assert.equal(rowIsEmpty(row({ kind: "dot" })), true);
  assert.equal(rowIsEmpty(row({ name: "  " })), true);
  assert.equal(rowIsEmpty(row({ lat: "1.3" })), false);
});

test("validateManualRows drops blank rows and numbers errors by posted position", () => {
  const rows = [row({ key: "a", name: "Singapore" }), blankRow(9), row({ key: "c", lat: "1.3" })];
  const { payload, errors } = validateManualRows(rows, "slides");
  assert.deepEqual(payload, []);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].key, "c");
  assert.equal(errors[0].index, 2);
  assert.match(errors[0].message, /^Row 2: /);
});

test("validateManualRows reports one error when every row is blank", () => {
  const { payload, errors } = validateManualRows([blankRow(0), blankRow(1)], "slides");
  assert.deepEqual(payload, []);
  assert.deepEqual(errors, [{ key: "", index: 0, message: "Add at least one entry." }]);
});

test("validateManualRows requires a name in slides mode", () => {
  const { errors } = validateManualRows([row({ place: "Bedok, Singapore" })], "slides");
  assert.deepEqual(errors.map((e) => e.message), ["Row 1: enter a name."]);
});

test("validateManualRows defaults the pin name to Pin when a locator is present", () => {
  const { payload, errors } = validateManualRows([row({ place: "Bedok, Singapore" })], "pins");
  assert.deepEqual(errors, []);
  assert.deepEqual(payload, [{ name: "Pin", place: "Bedok, Singapore", kind: "dropPin" }]);
});

test("validateManualRows rejects a pins row whose only locator is a link", () => {
  const { payload, errors } = validateManualRows([row({ url: "https://maps.app.goo.gl/x1Y2z3" })], "pins");
  assert.deepEqual(payload, []);
  assert.deepEqual(errors.map((e) => e.message), [
    "Row 1: enter a name, a place or coordinates — a link alone has nothing to name the pin with.",
  ]);
});

test("validateManualRows names the field that failed", () => {
  const noName = validateManualRows([row({ place: "Bedok, Singapore" })], "slides");
  assert.equal(noName.errors[0].field, "name");
  const halfPair = validateManualRows([row({ name: "X", lat: "1.3" })], "slides");
  assert.equal(halfPair.errors[0].field, "lon");
  const badLat = validateManualRows([row({ name: "X", lat: "86", lon: "10" })], "slides");
  assert.equal(badLat.errors[0].field, "lat");
  const badLon = validateManualRows([row({ name: "X", lat: "1", lon: "181" })], "slides");
  assert.equal(badLon.errors[0].field, "lon");
});

test("validateManualRows requires both a latitude and a longitude", () => {
  const { errors } = validateManualRows([row({ name: "X", lat: "1.3" })], "slides");
  assert.deepEqual(errors.map((e) => e.message), ["Row 1: enter both a latitude and a longitude."]);
});

test("validateManualRows rejects coordinates outside the Web Mercator range", () => {
  const high = validateManualRows([row({ name: "X", lat: "86", lon: "10" })], "slides");
  assert.match(high.errors[0].message, /latitude must be a number between -85.05 and 85.05/);
  const wide = validateManualRows([row({ name: "X", lat: "1", lon: "181" })], "slides");
  assert.match(wide.errors[0].message, /longitude must be a number between -180 and 180/);
  const text = validateManualRows([row({ name: "X", lat: "north", lon: "10" })], "slides");
  assert.equal(text.errors.length, 1);
});

test("validateManualRows keeps zero coordinates", () => {
  const { payload, errors } = validateManualRows([row({ name: "Null Island", lat: "0", lon: "0" })], "slides");
  assert.deepEqual(errors, []);
  assert.deepEqual(payload, [{ name: "Null Island", lat: 0, lon: 0 }]);
});

test("validateManualRows omits blank optional fields from the payload", () => {
  const { payload } = validateManualRows([row({ name: "Singapore" })], "slides");
  assert.deepEqual(payload, [{ name: "Singapore" }]);
  assert.deepEqual(Object.keys(payload[0]), ["name"]);
});

test("validateManualRows sends kind only in pins mode", () => {
  const entry = row({ name: "Bedok", kind: "dot" });
  assert.deepEqual(validateManualRows([entry], "slides").payload, [{ name: "Bedok" }]);
  assert.deepEqual(validateManualRows([entry], "pins").payload, [{ name: "Bedok", kind: "dot" }]);
});
