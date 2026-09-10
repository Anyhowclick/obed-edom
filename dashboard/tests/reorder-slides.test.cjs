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
const { reorderSlides, restitchLinks, restitchWithMemory, moveSlideTo, documentFromResult, coerceHopKinds } = require(path.join(out, "types.js"));

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

test("moveSlideTo away and back restores a displaced movie hop via retiredLinks", () => {
  const s1 = slide("s1");
  const s2 = slide("s2", { highlights: ["USA"], isolate: { mode: "darken", strength: 0.65 } });
  const s3 = slide("s3");
  const s4 = slide("s4");
  const links = [
    { from: "s1", to: "s2", kind: "movie", duration: 3.5, playWithoutClick: false, objectTransition: "fade" },
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: false },
    { from: "s3", to: "s4", kind: "cut", duration: 0, playWithoutClick: false },
  ];
  const d = doc([s1, s2, s3, s4], links);

  const away = moveSlideTo(d, "s4", 1); // s1, s4, s2, s3
  assert.equal(away.links.find((l) => l.from === "s1" && l.to === "s2"), undefined);
  assert.ok((away.retiredLinks || []).some((l) => l.from === "s1" && l.to === "s2" && l.kind === "movie"));

  const back = moveSlideTo(away, "s4", 3); // s1, s2, s3, s4
  const restored = back.links.find((l) => l.from === "s1" && l.to === "s2");
  assert.ok(restored);
  assert.equal(restored.kind, "movie");
  assert.equal(restored.duration, 3.5);
  assert.equal(restored.objectTransition, "fade");
  assert.ok(!(back.retiredLinks || []).some((l) => l.from === "s1" && l.to === "s2"));
});

test("moveSlideTo away and back survives a save/reload round-trip", () => {
  const s1 = slide("s1");
  const s2 = slide("s2", { highlights: ["USA"], isolate: { mode: "darken", strength: 0.65 } });
  const s3 = slide("s3");
  const s4 = slide("s4");
  const links = [
    { from: "s1", to: "s2", kind: "movie", duration: 3.5, playWithoutClick: false, objectTransition: "fade" },
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: false },
    { from: "s3", to: "s4", kind: "cut", duration: 0, playWithoutClick: false },
  ];
  const d = doc([s1, s2, s3, s4], links);
  const away = moveSlideTo(d, "s4", 1);
  const reloaded = documentFromResult(JSON.parse(JSON.stringify(away)));
  const back = moveSlideTo(reloaded, "s4", 3);
  const restored = back.links.find((l) => l.from === "s1" && l.to === "s2");
  assert.ok(restored);
  assert.equal(restored.kind, "movie");
  assert.equal(restored.duration, 3.5);
});

test("restitchWithMemory prunes retired entries naming a missing slide", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const prevRetired = [{ from: "s1", to: "gone", kind: "movie", duration: 2, playWithoutClick: false }];
  const { retired } = restitchWithMemory([s1, s2], [], prevRetired);
  assert.equal(retired.length, 0);
});

test("restitchWithMemory caps retired entries at 200, keeping the newest", () => {
  const prevRetired = [];
  const froms = [];
  const tos = [];
  for (let i = 0; i < 250; i++) {
    const from = `a${i}`;
    const to = `b${i}`;
    prevRetired.push({ from, to, kind: "cut", duration: 0, playWithoutClick: false });
    froms.push(slide(from));
    tos.push(slide(to));
  }
  // Put all `a*` slides before all `b*` slides so no (a_i,b_i) pair is ever adjacent in
  // `allSlides` — every retired pair stays unconsumed and eligible for the cap.
  const allSlides = [...froms, ...tos];
  const { retired } = restitchWithMemory(allSlides, [], prevRetired);
  assert.equal(retired.length, 200);
  assert.deepEqual(
    retired.map((l) => l.from),
    prevRetired.slice(50).map((l) => l.from)
  );
});

test("moveSlideTo does not leak retired memory across a different pair", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const s3 = slide("s3");
  const links = [
    { from: "s1", to: "s2", kind: "movie", duration: 3.5, playWithoutClick: false },
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: false },
  ];
  const d = doc([s1, s2, s3], links);
  const next = reorderSlides(d, "s2", 1); // -> s1, s3, s2; s1->s3 is a new pair
  const s1s3 = next.links.find((l) => l.from === "s1" && l.to === "s3");
  assert.ok(s1s3);
  assert.notEqual(s1s3.kind, "movie");
});

test("restitchWithMemory refreshes insertion order for a live link sharing an early retired key, so it survives the 200 cap", () => {
  const froms = [];
  const tos = [];
  const prevRetired = [];
  for (let i = 0; i < 201; i++) {
    const from = `a${i}`;
    const to = `b${i}`;
    prevRetired.push({ from, to, kind: "cut", duration: 0, playWithoutClick: false });
    froms.push(slide(from));
    tos.push(slide(to));
  }
  const liveLink = { from: "a0", to: "b0", kind: "movie", duration: 4.25, playWithoutClick: false, objectTransition: "hold" };
  // Put all `a*` slides before all `b*` slides so no (a_i,b_i) pair is ever adjacent —
  // every entry (retired or live) stays unconsumed and eligible for the cap.
  const allSlides = [...froms, ...tos];
  const { retired } = restitchWithMemory(allSlides, [liveLink], prevRetired);
  assert.equal(retired.length, 200);
  const survivor = retired.find((l) => l.from === "a0" && l.to === "b0");
  assert.ok(survivor, "live link sharing an early retired key must survive the cap");
  assert.equal(survivor.kind, "movie");
  assert.equal(survivor.duration, 4.25);
  assert.equal(survivor.objectTransition, "hold");
});

test("restitchWithMemory keys are collision-free across slide ids containing separator-like characters", () => {
  const sA = slide("a");
  const sBC = slide("b c");
  const prevRetired = [{ from: "a b", to: "c", kind: "movie", duration: 5, playWithoutClick: false }];
  // ("a b","c") and ("a","b c") must not collide even though naive concatenation
  // (e.g. joining with a separator character legal inside a slide id) would produce
  // the same key for both pairs.
  const { links } = restitchWithMemory([sA, sBC], [], prevRetired);
  const restored = links.find((l) => l.from === "a" && l.to === "b c");
  assert.ok(restored);
  assert.notEqual(restored.kind, "movie");
  assert.notEqual(restored.duration, 5);
});

test("documentFromResult round-trips flight, drops invalid values, leaves missing absent", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const links = [
    { from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: false, flight: "arc" },
  ];
  const d = doc([s1, s2], links);
  const kept = documentFromResult(JSON.parse(JSON.stringify(d)));
  assert.equal(kept.links[0].flight, "arc");

  const bogus = doc([s1, s2], [{ ...links[0], flight: "spiral" }]);
  const droppedBogus = documentFromResult(JSON.parse(JSON.stringify(bogus)));
  assert.equal(droppedBogus.links[0].flight, undefined);

  const missing = doc([s1, s2], [{ from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: false, easeIn: 0.3 }]);
  const stillMissing = documentFromResult(JSON.parse(JSON.stringify(missing)));
  assert.equal(stillMissing.links[0].flight, undefined);
  assert.equal(stillMissing.links[0].easeIn, 0.3);
});

const movieCamera = { ...baseCamera, bearing: 90 };

test("restitchLinks/restitchWithMemory default new movie links to flight arc, retired links keep their own", () => {
  const s1 = slide("s1");
  const s2 = slide("s2", { camera: movieCamera });
  const s3 = slide("s3", { camera: movieCamera });
  const links = restitchLinks([s1, s2, s3], []);
  assert.equal(links[0].flight, "arc");

  const s4 = slide("s4");
  const phasesLink = { from: "s1", to: "s2", kind: "movie", duration: 2, playWithoutClick: false, flight: "phases" };
  const d = doc([s1, s2, s3, s4], [
    phasesLink,
    { from: "s2", to: "s3", kind: "cut", duration: 0, playWithoutClick: false },
    { from: "s3", to: "s4", kind: "cut", duration: 0, playWithoutClick: false },
  ]);
  const away = moveSlideTo(d, "s4", 1); // s1, s4, s2, s3 — s1->s2 pair displaced
  assert.ok((away.retiredLinks || []).some((l) => l.from === "s1" && l.to === "s2" && l.flight === "phases"));
  const back = moveSlideTo(away, "s4", 3); // restores s1, s2, s3, s4
  const restored = back.links.find((l) => l.from === "s1" && l.to === "s2");
  assert.equal(restored.flight, "phases");
});

test("coerceHopKinds strips flight from any non-movie link", () => {
  const s1 = slide("s1");
  const s2 = slide("s2");
  const links = [{ from: "s1", to: "s2", kind: "cut", duration: 0, playWithoutClick: false, flight: "phases" }];
  const next = coerceHopKinds(doc([s1, s2], links));
  assert.equal(next.links[0].flight, undefined);
});

test("coerceHopKinds keeps flight on a link coerced from morph to movie", () => {
  const s1 = slide("s1");
  const s2 = slide("s2", { camera: movieCamera });
  const links = [{ from: "s1", to: "s2", kind: "morph", duration: 1, playWithoutClick: false, flight: "phases" }];
  const next = coerceHopKinds(doc([s1, s2], links));
  assert.equal(next.links[0].kind, "movie");
  assert.equal(next.links[0].flight, "phases");
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
