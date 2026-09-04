// Length-guard + per-object-fallback unit tests for the slim bulk-geometry read
// (bulk_geometry.js). Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/bulk_geometry.test.js
//
// The guarantees mirrored from inspect_keynote.js's bulk path:
//   * a bulk array of the right length is used verbatim;
//   * an array that DRIFTS (wrong length) is discarded and that ONE property is
//     read per-object — never a short array zipped into shifted kindIndexes;
//   * a collection that cannot be evaluated at all is omitted (so the Python
//     caller falls back for just that slide/kind), and an empty one yields [].

const assert = require("assert");
const m = require("../src/obed_edom/bulk_geometry.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A single drawable: JXA exposes position()/width()/height() as functions.
function elem(x, y, w, h) {
  return {
    position: function () { return [x, y]; },
    width: function () { return w; },
    height: function () { return h; },
  };
}

// A collection specifier: `slide.images` is a function returning the evaluated
// array AND carrying .position/.width/.height sub-accessors for the bulk fetch
// off the UNEVALUATED specifier — exactly as JXA exposes it. `bulk` supplies the
// arrays those sub-accessors return; a key set to the string "throw" makes that
// bulk fetch raise (so the per-object path takes over for it).
function collection(elements, bulk) {
  bulk = bulk || {};
  const fn = function () { return elements; };
  ["position", "width", "height"].forEach(function (prop) {
    fn[prop] = function () {
      if (bulk[prop] === "throw") throw new Error("no bulk " + prop);
      if (bulk[prop] === undefined) throw new Error("no bulk " + prop);
      return bulk[prop];
    };
  });
  return fn;
}

test("full bulk => rows come straight from the bulk arrays", function () {
  const els = [elem(0, 0, 0, 0), elem(0, 0, 0, 0)];
  const col = collection(els, {
    position: [[10, 20], [30, 40]],
    width: [100, 300],
    height: [50, 70],
  });
  const rows = m.collectionGeom({ images: col }, "images");
  assert.deepStrictEqual(rows, [[10, 20, 100, 50], [30, 40, 300, 70]]);
});

test("drifted position array => per-object position, width/height still bulk", function () {
  const els = [elem(1, 2, 0, 0), elem(3, 4, 0, 0)];
  const col = collection(els, {
    position: [[10, 20]], // length 1 for a 2-element collection => discarded
    width: [100, 300],
    height: [50, 70],
  });
  const rows = m.collectionGeom({ images: col }, "images");
  // position fell back to the per-object elem() values; w/h stayed bulk.
  assert.deepStrictEqual(rows, [[1, 2, 100, 50], [3, 4, 300, 70]]);
});

test("all bulk throws => fully per-object, still correct", function () {
  const els = [elem(5, 6, 7, 8)];
  const col = collection(els, { position: "throw", width: "throw", height: "throw" });
  const rows = m.collectionGeom({ groups: col }, "groups");
  assert.deepStrictEqual(rows, [[5, 6, 7, 8]]);
});

test("empty collection => []", function () {
  const col = collection([], {});
  assert.deepStrictEqual(m.collectionGeom({ textItems: col }, "textItems"), []);
});

test("unreadable collection => null (caller falls back granularly)", function () {
  const slide = { movies: function () { throw new Error("cannot evaluate"); } };
  assert.strictEqual(m.collectionGeom(slide, "movies"), null);
});

test("slideGeom emits only the kinds present, keyed by kind", function () {
  const slide = {
    textItems: collection([elem(1, 1, 2, 2)], {
      position: [[1, 1]], width: [2], height: [2],
    }),
    images: collection([], {}),
    // no movies / groups collections at all
  };
  const geom = m.slideGeom(slide);
  assert.deepStrictEqual(Object.keys(geom).sort(), ["image", "text"]);
  assert.deepStrictEqual(geom.text, [[1, 1, 2, 2]]);
  assert.deepStrictEqual(geom.image, []);
});

test("xyFrom accepts a {x,y} accessor object too", function () {
  const p = { x: function () { return 9; }, y: function () { return 8; } };
  assert.deepStrictEqual(m.xyFrom(p), [9, 8]);
});

// --- error collection: every silently-swallowed failure is now reported ------------
//
// Every per-collection/bulk-property/item exception used to just vanish (the kind was
// omitted, "bulk-missing" carried no reason). These lock that each failure mode now
// lands in the module-level `errors` array with the (slide, kind, where) the caller
// needs to explain a "bulk unavailable" run after the fact.

test("unreadable collection reports a collection-level error", function () {
  m.resetErrors();
  const slide = { movies: function () { throw new Error("cannot evaluate"); } };
  assert.strictEqual(m.collectionGeom(slide, "movies"), null);
  const errors = m.getErrors();
  assert.strictEqual(errors.length, 1);
  assert.strictEqual(errors[0].kind, "movie");
  assert.strictEqual(errors[0].where, "collection");
  assert.ok(errors[0].error.indexOf("cannot evaluate") !== -1);
});

test("a bulk property that throws reports bulk:<prop> and still falls back per-item", function () {
  m.resetErrors();
  const els = [elem(5, 6, 7, 8)];
  const col = collection(els, { position: "throw", width: [100], height: [50] });
  const rows = m.collectionGeom({ images: col }, "images");
  assert.deepStrictEqual(rows, [[5, 6, 100, 50]]);
  const errors = m.getErrors();
  assert.strictEqual(errors.length, 1);
  assert.strictEqual(errors[0].kind, "image");
  assert.strictEqual(errors[0].where, "bulk:position");
});

test("a per-item fallback that itself throws reports item:<i>, row still emitted", function () {
  m.resetErrors();
  const badElem = {
    position: function () { throw new Error("item position boom"); },
    width: function () { return 7; },
    height: function () { return 8; },
  };
  // Bulk position DRIFTS (length 2 for a 1-element collection) -- discarded with no
  // exception (bulkArray returns null), so the per-item fallback runs and its own
  // throw is the ONLY error; width/height stay bulk (valid, length 1) so no bulk:
  // error fires for them either. The drift itself is a NOTE, not an error.
  const col = collection([badElem], { position: [[1, 1], [2, 2]], width: [100], height: [50] });
  const rows = m.collectionGeom({ groups: col }, "groups");
  assert.deepStrictEqual(rows, [[0, 0, 100, 50]]); // position fell back to [0, 0]
  const errors = m.getErrors();
  assert.strictEqual(errors.length, 1);
  assert.strictEqual(errors[0].kind, "group");
  assert.strictEqual(errors[0].where, "item:0");
  assert.ok(errors[0].error.indexOf("item position boom") !== -1);
  const notes = m.getNotes();
  assert.strictEqual(notes.length, 1);
  assert.strictEqual(notes[0].kind, "group");
  assert.strictEqual(notes[0].where, "bulk:position:length");
});

test("a drifted bulk array with no other failure reports ONLY a note, no error", function () {
  m.resetErrors();
  const els = [elem(1, 2, 0, 0), elem(3, 4, 0, 0)];
  const col = collection(els, {
    position: [[10, 20]], // length 1 for a 2-element collection => discarded
    width: [100, 300],
    height: [50, 70],
  });
  m.collectionGeom({ images: col }, "images");
  assert.deepStrictEqual(m.getErrors(), []);
  const notes = m.getNotes();
  assert.strictEqual(notes.length, 1);
  assert.strictEqual(notes[0].kind, "image");
  assert.strictEqual(notes[0].where, "bulk:position:length");
});

test("notes array is capped at 50, noteCount stays uncapped, independent of errors", function () {
  m.resetErrors();
  const els = [elem(1, 2, 0, 0)];
  const col = collection(els, { position: [[10, 20], [30, 40]], width: [1], height: [1] });
  for (let i = 0; i < 60; i++) {
    m.collectionGeom({ images: col }, "images");
  }
  assert.strictEqual(m.getNotes().length, 50);
  assert.strictEqual(m.getNoteCount(), 60);
  assert.strictEqual(m.getErrors().length, 0);
  assert.strictEqual(m.getErrorCount(), 0);
});

test("slideGeom tags every error with its own slide index", function () {
  m.resetErrors();
  const empty = collection([], {});
  const slide = {
    textItems: empty,
    images: empty,
    groups: empty,
    movies: function () { throw new Error("nope"); },
  };
  m.slideGeom(slide, 41);
  const errors = m.getErrors();
  assert.strictEqual(errors.length, 1);
  assert.strictEqual(errors[0].slide, 41);
  assert.strictEqual(errors[0].kind, "movie");
});

test("errors array is capped at 50, errorCount stays uncapped", function () {
  m.resetErrors();
  const slide = { movies: function () { throw new Error("nope"); } };
  for (let i = 0; i < 60; i++) {
    m.collectionGeom(slide, "movies");
  }
  assert.strictEqual(m.getErrors().length, 50);
  assert.strictEqual(m.getErrorCount(), 60);
});

test("an unreadable count (NaN/negative) reports a count error", function () {
  m.resetErrors();
  const badCol = function () { return { length: -1 }; };
  const rows = m.collectionGeom({ groups: badCol }, "groups");
  assert.strictEqual(rows, null);
  const errors = m.getErrors();
  assert.strictEqual(errors.length, 1);
  assert.strictEqual(errors[0].kind, "group");
  assert.strictEqual(errors[0].where, "count");
  assert.ok(errors[0].error.indexOf("-1") !== -1);
});

console.log("\n" + passed + " passing");
