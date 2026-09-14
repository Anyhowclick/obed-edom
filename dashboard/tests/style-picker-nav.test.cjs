const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "style-picker-nav-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/stylePickerNav.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { nextGridIndex } = require(path.join(out, "stylePickerNav.js"));

const COUNT = 10;
const COLS = 3;

test("ArrowRight wraps from the last index to the first", () => {
  assert.equal(nextGridIndex(9, "ArrowRight", COUNT, COLS), 0);
});

test("ArrowLeft wraps from the first index to the last", () => {
  assert.equal(nextGridIndex(0, "ArrowLeft", COUNT, COLS), 9);
});

test("ArrowDown moves down a row when the row below exists", () => {
  assert.equal(nextGridIndex(0, "ArrowDown", COUNT, COLS), 3);
});

test("ArrowDown from the last row stays put (clamped, no wrap)", () => {
  assert.equal(nextGridIndex(9, "ArrowDown", COUNT, COLS), 9);
});

test("ArrowUp from the first row stays put (clamped, no wrap)", () => {
  assert.equal(nextGridIndex(1, "ArrowUp", COUNT, COLS), 1);
});

test("Home jumps to the first index", () => {
  assert.equal(nextGridIndex(5, "Home", COUNT, COLS), 0);
});

test("End jumps to the last index", () => {
  assert.equal(nextGridIndex(0, "End", COUNT, COLS), 9);
});

test("an unrecognized key is a no-op", () => {
  assert.equal(nextGridIndex(4, "PageDown", COUNT, COLS), 4);
});

test("StylePicker uses roving DOM focus, not aria-activedescendant, on its listbox", () => {
  const source = fs.readFileSync(path.join(root, "src/maps/StylePicker.tsx"), "utf8");
  assert.doesNotMatch(source, /aria-activedescendant/);
  assert.match(source, /role="listbox"/);
  assert.match(source, /tabIndex=\{index === focusIndex \? 0 : -1\}/);
  assert.match(source, /tileRefs\.current\[focusIndex\]\?\.focus\(\)/);
});

test("STYLE_THUMB_CAMERA records the Marina Bay camera every thumbnail is captured at", () => {
  const source = fs.readFileSync(path.join(root, "src/maps/styles.ts"), "utf8");
  assert.match(source, /lat:\s*1\.2864/);
  assert.match(source, /lon:\s*103\.8604/);
  assert.match(source, /zoom:\s*16\.5/);
  assert.match(source, /pitch:\s*0/);
  assert.match(source, /bearing:\s*75/);
  assert.match(source, /cgShiftX:\s*0/);
});

test("every STYLE_SWATCHES id has a 480x240 thumbnail in public/style-thumbs", () => {
  const source = fs.readFileSync(path.join(root, "src/maps/styles.ts"), "utf8");
  const ids = [...source.matchAll(/\{ id: "([^"]+)", label: "[^"]*", color: "[^"]*" \}/g)].map((m) => m[1]);
  assert.ok(ids.length > 0, "no STYLE_SWATCHES ids parsed");
  for (const id of ids) {
    const file = path.join(root, "public/style-thumbs", `${id}.png`);
    const buf = fs.readFileSync(file);
    const width = buf.readUInt32BE(16);
    const height = buf.readUInt32BE(20);
    assert.equal(width, 480, `${id}.png width`);
    assert.equal(height, 240, `${id}.png height`);
  }
});
