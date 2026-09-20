const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").dsk;
const {
  buildDecisionsMap,
  bulkAnchor,
  bulkInclude,
  bulkKeepSide,
  bulkVideosOnly,
  groupPages,
  includedSlides,
  needsClip,
  setAnchor,
  setClip,
  setInclude,
  setKeepSide,
  setVideosOnly,
  toDecisionsPayload,
} = require(path.join(out, "decisions.js"));

// Shape matches `pages[]` from `_run_dsk_propose` in `web/app.py`.
const PAGES = [
  { slide: 3, category: "static", isText: false, needsClip: false, canVideosOnly: false, stackedMovies: false },
  { slide: 7, category: "movie", isText: false, needsClip: true, canVideosOnly: true, stackedMovies: true },
  { slide: 9, category: "mixed", isText: false, needsClip: true, canVideosOnly: true, stackedMovies: false },
  { slide: 13, category: "static", isText: true, needsClip: false, canVideosOnly: false, stackedMovies: false },
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

test("videosOnly defaults to false on every page, capable or not", () => {
  const map = buildDecisionsMap(PAGES);
  assert.equal(map[7].videosOnly, false);
  assert.equal(map[3].videosOnly, false);
});

test("a server decision missing videosOnly is seeded false rather than undefined", () => {
  const map = buildDecisionsMap([
    { slide: 7, category: "movie", isText: false, needsClip: true, canVideosOnly: true, decision: { slide: 7, include: true, action: "both", anchor: "auto", keepSide: false, clip: null } },
  ]);
  assert.equal(map[7].videosOnly, false);
});

test("setVideosOnly only takes on a page the backend marked canVideosOnly", () => {
  let map = buildDecisionsMap(PAGES);
  map = setVideosOnly(map, PAGES, 7, true);
  map = setVideosOnly(map, PAGES, 3, true);
  assert.equal(map[7].videosOnly, true);
  assert.equal(map[3].videosOnly, false);
});

test("setVideosOnly can be turned back off", () => {
  let map = buildDecisionsMap(PAGES);
  map = setVideosOnly(map, PAGES, 7, true);
  map = setVideosOnly(map, PAGES, 7, false);
  assert.equal(map[7].videosOnly, false);
});

test("bulkVideosOnly forces false on incapable pages in the same sweep", () => {
  let map = buildDecisionsMap(PAGES);
  map = bulkVideosOnly(map, PAGES, [3, 7, 9, 13], true);
  assert.equal(map[7].videosOnly, true);
  assert.equal(map[9].videosOnly, true);
  assert.equal(map[3].videosOnly, false);
  assert.equal(map[13].videosOnly, false);
});

test("bulkAnchor sets alignment for every listed slide, leaving the rest alone", () => {
  let map = buildDecisionsMap(PAGES);
  map = bulkAnchor(map, PAGES, [3, 7], "right");
  assert.equal(map[3].anchor, "right");
  assert.equal(map[7].anchor, "right");
  assert.equal(map[9].anchor, "auto");
});

test("includedSlides lists exactly the kept slides, so bulk align skips benched ones", () => {
  let map = buildDecisionsMap(PAGES);
  assert.deepEqual(includedSlides(map, PAGES), [3, 7, 9]);
  map = setInclude(map, PAGES, 7, false);
  assert.deepEqual(includedSlides(map, PAGES), [3, 9]);
});

test("groupPages buckets by category with text last and movies first", () => {
  const groups = groupPages(PAGES);
  assert.deepEqual(groups.map((g) => g.key), ["movie", "mixed", "static", "text"]);
  assert.deepEqual(groups.map((g) => g.pages.length), [1, 1, 1, 1]);
  assert.equal(groups[3].label, "Text — skipped");
});

test("groupPages keeps built ahead of static and every page appears once", () => {
  const pages = [
    { slide: 1, category: "static", isText: false, needsClip: false },
    { slide: 2, category: "built", isText: false, needsClip: false },
    { slide: 4, category: "static", isText: false, needsClip: false },
  ];
  const groups = groupPages(pages);
  assert.deepEqual(groups.map((g) => g.key), ["built", "static"]);
  assert.deepEqual(groups.flatMap((g) => g.pages.map((p) => p.slide)), [2, 1, 4]);
});

test("toDecisionsPayload carries videosOnly to the API", () => {
  let map = buildDecisionsMap(PAGES);
  map = setVideosOnly(map, PAGES, 9, true);
  const payload = toDecisionsPayload(map);
  assert.equal(payload.find((d) => d.slide === 9).videosOnly, true);
  assert.equal(payload.find((d) => d.slide === 3).videosOnly, false);
});
