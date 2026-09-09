const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-reorder-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { reorderSlides, restitchLinks, moveSlideTo } = require(path.join(out, "types.js"));

const baseCamera = { lat: 0, lon: 0, zoom: 4, bearing: 0, pitch: 0 };
function slide(id, overrides) {
  return {
    id,
    title: id,
    style: "positron",
    camera: baseCamera,
    highlights: [],
    churches: [],
    cgShiftX: 0,
    cgShiftY: 0,
    includeSidePanels: false,
    ...overrides,
  };
}

function doc(slides, links) {
  return {
    defaultStyle: "positron",
    crop: "center+cg",
    exportLw: true,
    exportCg: true,
    exportDsk: false,
    hiddenLayers: [],
    cachedCountries: [],
    assets: [],
    slides,
    links,
  };
}

test("moveSlide down swaps the pair and preserves slide bodies", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const d = doc([s1, s2, s3], restitchLinks([s1, s2, s3], []));
  const next = reorderSlides(d, "s1", 1);
  assert.deepEqual(next.slides.map((s) => s.id), ["s2", "s1", "s3"]);
  assert.deepEqual(next.slides[1], s1);
  assert.equal(next.slides[2], s3);
});

test("moveSlide up swaps the pair and preserves slide bodies", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const d = doc([s1, s2, s3], restitchLinks([s1, s2, s3], []));
  const next = reorderSlides(d, "s3", -1);
  assert.deepEqual(next.slides.map((s) => s.id), ["s1", "s3", "s2"]);
});

test("delta past either end returns doc unchanged", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const d = doc([s1, s2], restitchLinks([s1, s2], []));
  assert.equal(reorderSlides(d, "s1", -1), d);
  assert.equal(reorderSlides(d, "s2", 1), d);
});

test("unknown id returns doc unchanged", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const d = doc([s1, s2], restitchLinks([s1, s2], []));
  assert.equal(reorderSlides(d, "nope", 1), d);
});

test("surviving link keeps its object and fields, disappeared pairs dropped, new pairs get defaults", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const links = [
    { from: "s1", to: "s2", kind: "movie", duration: 3.5, playWithoutClick: false },
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: true },
  ];
  const d = doc([s1, s2, s3], links);
  const next = reorderSlides(d, "s2", 1); // swap s2/s3 -> s1, s3, s2
  assert.equal(next.links.length, next.slides.length - 1);
  for (const link of next.links) {
    assert.ok(next.slides.some((s) => s.id === link.from));
    assert.ok(next.slides.some((s) => s.id === link.to));
  }
  // s2->s3 pair still exists as s3->s2 is a new pair, not the same (from,to); s1->s2 pair vanished (now s1->s3)
  const s1s3 = next.links.find((l) => l.from === "s1" && l.to === "s3");
  assert.ok(s1s3);
  assert.notEqual(s1s3.kind, "movie");
  assert.equal(s1s3.duration, 1.0);
  const s3s2 = next.links.find((l) => l.from === "s3" && l.to === "s2");
  assert.ok(s3s2);
  assert.equal(s3s2.duration, 1.0);
});

test("a link surviving under the same (from,to) keeps its exact object", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const s5 = slide("s5");
  const survivor = { from: "s2", to: "s3", kind: "movie", duration: 3.5, playWithoutClick: false };
  const links = [
    { from: "s1", to: "s2", kind: "cut", duration: 0, playWithoutClick: false },
    survivor,
    { from: "s3", to: "s4", kind: "cut", duration: 0, playWithoutClick: false },
    { from: "s4", to: "s5", kind: "cut", duration: 0, playWithoutClick: false },
  ];
  const d = doc([s1, s2, s3, s4, s5], links);
  const next = reorderSlides(d, "s1", 1); // swap s1/s2 -> s2, s1, s3, s4, s5; (s2,s3) pair vanishes
  const found = next.links.find((l) => l.from === "s2" && l.to === "s3");
  assert.equal(found, undefined);

  const d2 = doc([s1, s2, s3, s4, s5], links);
  const next2 = reorderSlides(d2, "s4", 1); // swap s4/s5 -> s1, s2, s3, s5, s4; (s2,s3) pair untouched
  const kept = next2.links.find((l) => l.from === "s2" && l.to === "s3");
  assert.equal(kept, survivor);
});

test("movieMov/movieDuration cleared on swapped slides and the predecessor, retained elsewhere", () => {
  const s1 = slide("s1", { movieMov: "s1.mov", movieDuration: 2 });
  const s2 = slide("s2", { movieMov: "s2.mov", movieDuration: 2 });
  const s3 = slide("s3", { movieMov: "s3.mov", movieDuration: 2 });
  const s4 = slide("s4", { movieMov: "s4.mov", movieDuration: 2 });
  const d = doc([s1, s2, s3, s4], restitchLinks([s1, s2, s3, s4], []));
  const next = reorderSlides(d, "s3", 1); // swap s3/s4 -> predecessor is s2
  const byId = Object.fromEntries(next.slides.map((s) => [s.id, s]));
  assert.equal(byId.s1.movieMov, "s1.mov");
  assert.equal(byId.s2.movieMov, undefined);
  assert.equal(byId.s2.movieDuration, undefined);
  assert.equal(byId.s4.movieMov, undefined);
  assert.equal(byId.s3.movieMov, undefined);
});

test("movieMov cleared on cg override too", () => {
  const cg = { camera: baseCamera, style: "positron", highlights: [], churches: [], movieMov: "cg.mov", movieDuration: 1 };
  const s1 = slide("s1", { cg: { ...cg } });
  const s2 = slide("s2", { cg: { ...cg } });
  const d = doc([s1, s2], restitchLinks([s1, s2], []));
  const next = reorderSlides(d, "s1", 1);
  const byId = Object.fromEntries(next.slides.map((s) => [s.id, s]));
  assert.equal(byId.s1.cg.movieMov, undefined);
  assert.equal(byId.s2.cg.movieMov, undefined);
});

test("moveSlideTo first to last", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const d = doc([s1, s2, s3, s4], restitchLinks([s1, s2, s3, s4], []));
  const next = moveSlideTo(d, "s1", 3);
  assert.deepEqual(next.slides.map((s) => s.id), ["s2", "s3", "s4", "s1"]);
});

test("moveSlideTo last to first", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const d = doc([s1, s2, s3, s4], restitchLinks([s1, s2, s3, s4], []));
  const next = moveSlideTo(d, "s4", 0);
  assert.deepEqual(next.slides.map((s) => s.id), ["s4", "s1", "s2", "s3"]);
});

test("moveSlideTo middle to arbitrary index", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const s5 = slide("s5");
  const d = doc([s1, s2, s3, s4, s5], restitchLinks([s1, s2, s3, s4, s5], []));
  const next = moveSlideTo(d, "s2", 3);
  assert.deepEqual(next.slides.map((s) => s.id), ["s1", "s3", "s4", "s2", "s5"]);
});

test("moveSlideTo clamps out-of-range indices", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const d = doc([s1, s2, s3], restitchLinks([s1, s2, s3], []));
  const overshoot = moveSlideTo(d, "s1", 99);
  assert.deepEqual(overshoot.slides.map((s) => s.id), ["s2", "s3", "s1"]);
  const undershoot = moveSlideTo(d, "s3", -99);
  assert.deepEqual(undershoot.slides.map((s) => s.id), ["s3", "s1", "s2"]);
});

test("moveSlideTo is identity when the index does not change or the id is unknown", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const d = doc([s1, s2, s3], restitchLinks([s1, s2, s3], []));
  assert.equal(moveSlideTo(d, "s2", 1), d);
  assert.equal(moveSlideTo(d, "nope", 0), d);
});

test("moveSlideTo restitches links, preserving surviving (from,to) pairs", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const survivor = { from: "s3", to: "s4", kind: "movie", duration: 3.5, playWithoutClick: false };
  const links = [
    { from: "s1", to: "s2", kind: "cut", duration: 0, playWithoutClick: false },
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: false },
    survivor,
  ];
  const d = doc([s1, s2, s3, s4], links);
  const next = moveSlideTo(d, "s1", 3); // -> s2, s3, s4, s1; (s3,s4) pair untouched
  assert.equal(next.links.length, next.slides.length - 1);
  const kept = next.links.find((l) => l.from === "s3" && l.to === "s4");
  assert.equal(kept, survivor);
});

test("moveSlideTo clears movieMov exactly on slides whose outgoing pair changed", () => {
  const s1 = slide("s1", { movieMov: "s1.mov", movieDuration: 2 });
  const s2 = slide("s2", { movieMov: "s2.mov", movieDuration: 2 });
  const s3 = slide("s3", { movieMov: "s3.mov", movieDuration: 2 });
  const s4 = slide("s4", { movieMov: "s4.mov", movieDuration: 2 });
  const s5 = slide("s5", { movieMov: "s5.mov", movieDuration: 2 });
  const d = doc([s1, s2, s3, s4, s5], restitchLinks([s1, s2, s3, s4, s5], []));
  const next = moveSlideTo(d, "s2", 3); // -> s1, s3, s4, s2, s5
  const byId = Object.fromEntries(next.slides.map((s) => [s.id, s]));
  // s1->s2 becomes s1->s3: s1 changed
  assert.equal(byId.s1.movieMov, undefined);
  // s2->s3 becomes s2->s5: s2 changed
  assert.equal(byId.s2.movieMov, undefined);
  // s3->s4 stays s3->s4: unchanged
  assert.equal(byId.s3.movieMov, "s3.mov");
  // s4->s5 becomes s4->s2: s4 changed
  assert.equal(byId.s4.movieMov, undefined);
  // s5 had no outgoing pair before or after: unchanged
  assert.equal(byId.s5.movieMov, "s5.mov");
});

test("links.length is always slides.length - 1 and endpoints exist", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const s4 = slide("s4");
  const d = doc([s1, s2, s3, s4], restitchLinks([s1, s2, s3, s4], []));
  const next = reorderSlides(d, "s2", 1);
  assert.equal(next.links.length, next.slides.length - 1);
  const ids = new Set(next.slides.map((s) => s.id));
  for (const link of next.links) {
    assert.ok(ids.has(link.from));
    assert.ok(ids.has(link.to));
  }
});
