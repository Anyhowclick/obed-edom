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

// Shape matches `pages[]` from `_run_dsk_propose` in `web/app.py`.
const PAGES = [
  { slide: 3, category: "static", isText: false, needsClip: false },
  { slide: 7, category: "movie", isText: false, needsClip: true },
  { slide: 9, category: "mixed", isText: false, needsClip: true },
  { slide: 13, category: "static", isText: true, needsClip: false },
];

test("default decisions include everything except text slides", () => {
  const map = buildDecisionsMap(PAGES);
  assert.equal(map[3].include, true);
  assert.equal(map[7].include, true);
  assert.equal(map[9].include, true);
  assert.equal(map[13].include, false);
});

test("default action is 'both' only for clip-bearing categories", () => {
  const map = buildDecisionsMap(PAGES);
  assert.equal(map[3].action, "in_deck");
  assert.equal(map[7].action, "both");
  assert.equal(map[9].action, "both");
});

test("needsClip mirrors the page's own needsClip flag from the API", () => {
  assert.equal(needsClip(PAGES[0]), false);
  assert.equal(needsClip(PAGES[1]), true);
  assert.equal(needsClip(PAGES[2]), true);
  assert.equal(needsClip(PAGES[3]), false);
});

test("a page already carrying a server decision seeds the map from it verbatim", () => {
  const withDecision = [
    { slide: 3, category: "static", isText: false, needsClip: false, decision: { slide: 3, include: false, action: "in_deck", anchor: "left", keepSide: true, clip: null } },
  ];
  const map = buildDecisionsMap(withDecision);
  assert.equal(map[3].include, false);
  assert.equal(map[3].anchor, "left");
  assert.equal(map[3].keepSide, true);
});

test("a text slide can never be included, even if asked to", () => {
  let map = buildDecisionsMap(PAGES);
  map = setInclude(map, PAGES, 13, true);
  assert.equal(map[13].include, false);
});

test("bulkInclude respects the text-slide invariant across the set", () => {
  let map = buildDecisionsMap(PAGES);
  map = bulkInclude(map, PAGES, [3, 7, 9, 13], true);
  assert.equal(map[3].include, true);
  assert.equal(map[13].include, false);
  map = bulkInclude(map, PAGES, [3, 7, 9, 13], false);
  assert.equal(map[3].include, false);
  assert.equal(map[7].include, false);
});

test("bulkKeepSide toggles keepSide for every listed slide", () => {
  let map = buildDecisionsMap(PAGES);
  map = bulkKeepSide(map, PAGES, [3, 7], true);
  assert.equal(map[3].keepSide, true);
  assert.equal(map[7].keepSide, true);
  assert.equal(map[9].keepSide, false);
});

test("setClip and setAnchor update only the targeted slide", () => {
  let map = buildDecisionsMap(PAGES);
  map = setClip(map, PAGES, 7, "/tmp/clip.mov");
  map = setAnchor(map, PAGES, 9, "left");
  assert.equal(map[7].clip, "/tmp/clip.mov");
  assert.equal(map[9].anchor, "left");
  assert.equal(map[3].clip, null);
});

test("setKeepSide flips the flag for one slide", () => {
  let map = buildDecisionsMap(PAGES);
  map = setKeepSide(map, PAGES, 3, true);
  assert.equal(map[3].keepSide, true);
  assert.equal(map[7].keepSide, false);
});

test("toDecisionsPayload flattens the map to a slide-sorted LIST, matching the API contract", () => {
  const map = buildDecisionsMap(PAGES);
  const payload = toDecisionsPayload(map);
  assert.deepEqual(payload.map((d) => d.slide), [3, 7, 9, 13]);
  assert.equal(payload.find((d) => d.slide === 3).include, true);
  assert.equal(payload.find((d) => d.slide === 13).include, false);
});
