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

console.log("\n" + passed + " passing");
