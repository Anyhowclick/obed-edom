const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "dsk-decisions-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/dsk/decisions.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const {
  buildDecisionsMap,
  bulkInclude,
  bulkKeepSide,
  needsClip,
  setAnchor,
  setClip,
  setInclude,
  setKeepSide,
  toDecisionsPayload,
} = require(path.join(out, "decisions.js"));

const SLIDES = [
  { number: 3, class: "static", skipped: false },
  { number: 7, class: "movie", skipped: false },
  { number: 9, class: "mixed", skipped: false },
  { number: 13, class: "verse", skipped: true },
];

test("default decisions include everything except skipped text slides", () => {
  const map = buildDecisionsMap(SLIDES);
  assert.equal(map[3].include, true);
  assert.equal(map[7].include, true);
  assert.equal(map[9].include, true);
  assert.equal(map[13].include, false);
});

test("needsClip is true only for movie/mixed classes", () => {
  assert.equal(needsClip(SLIDES[0]), false);
  assert.equal(needsClip(SLIDES[1]), true);
  assert.equal(needsClip(SLIDES[2]), true);
  assert.equal(needsClip(SLIDES[3]), false);
});

test("a skipped slide can never be included, even if asked to", () => {
  let map = buildDecisionsMap(SLIDES);
  map = setInclude(map, SLIDES, 13, true);
  assert.equal(map[13].include, false);
});

test("bulkInclude respects the skipped invariant across the set", () => {
  let map = buildDecisionsMap(SLIDES);
  map = bulkInclude(map, SLIDES, [3, 7, 9, 13], true);
  assert.equal(map[3].include, true);
  assert.equal(map[13].include, false);
  map = bulkInclude(map, SLIDES, [3, 7, 9, 13], false);
  assert.equal(map[3].include, false);
  assert.equal(map[7].include, false);
});

test("bulkKeepSide toggles keepSide for every listed slide", () => {
  let map = buildDecisionsMap(SLIDES);
  map = bulkKeepSide(map, [3, 7], true);
  assert.equal(map[3].keepSide, true);
  assert.equal(map[7].keepSide, true);
  assert.equal(map[9].keepSide, undefined);
});

test("setClip and setAnchor update only the targeted slide", () => {
  let map = buildDecisionsMap(SLIDES);
  map = setClip(map, 7, "/tmp/clip.mov");
  map = setAnchor(map, 9, "left");
  assert.equal(map[7].clip, "/tmp/clip.mov");
  assert.equal(map[9].anchor, "left");
  assert.equal(map[3].clip, undefined);
});

test("setKeepSide flips the flag for one slide", () => {
  let map = buildDecisionsMap(SLIDES);
  map = setKeepSide(map, 3, true);
  assert.equal(map[3].keepSide, true);
  assert.equal(map[7].keepSide, undefined);
});

test("toDecisionsPayload maps slide numbers to string keys, matching the API contract", () => {
  const map = buildDecisionsMap(SLIDES);
  const payload = toDecisionsPayload(map);
  assert.deepEqual(Object.keys(payload.slides).sort(), ["13", "3", "7", "9"]);
  assert.equal(payload.slides["3"].include, true);
  assert.equal(payload.slides["13"].include, false);
});
