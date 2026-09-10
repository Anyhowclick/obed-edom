const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-cg-band-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { showCgBand, snapCgShift, hasOutgoingMovie } = require(path.join(out, "types.js"));

test("showCgBand is true unless the slide itself is the CG slide", () => {
  assert.equal(showCgBand({}), true);
  assert.equal(showCgBand({ cg: undefined }), true);
  assert.equal(showCgBand({ cg: true }), false);
});

test("snapCgShift snaps to 0 within the threshold", () => {
  assert.equal(snapCgShift(0), 0);
  assert.equal(snapCgShift(10), 0);
  assert.equal(snapCgShift(-10), 0);
  assert.equal(snapCgShift(24), 0);
  assert.equal(snapCgShift(-24), 0);
});

test("snapCgShift leaves values outside the threshold alone", () => {
  assert.equal(snapCgShift(25), 25);
  assert.equal(snapCgShift(-25), -25);
  assert.equal(snapCgShift(200), 200);
});

test("snapCgShift honours a custom threshold", () => {
  assert.equal(snapCgShift(5, 10), 0);
  assert.equal(snapCgShift(11, 10), 11);
});

test("hasOutgoingMovie mirrors _outgoing: the first outgoing link's kind, not any outgoing link", () => {
  const cutThenMovie = [
    { from: "a", to: "b", kind: "cut" },
    { from: "a", to: "c", kind: "movie" },
  ];
  assert.equal(hasOutgoingMovie(cutThenMovie, "a"), false);

  const movieFirst = [
    { from: "a", to: "b", kind: "movie" },
    { from: "a", to: "c", kind: "cut" },
  ];
  assert.equal(hasOutgoingMovie(movieFirst, "a"), true);

  assert.equal(hasOutgoingMovie([], "a"), false);
  assert.equal(hasOutgoingMovie([{ from: "x", to: "y", kind: "movie" }], "a"), false);
});
