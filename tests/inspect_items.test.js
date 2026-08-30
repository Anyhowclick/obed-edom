// Unit tests for the additive item-scoped read (plan.items) in inspect_keynote.js.
// Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/inspect_items.test.js
//
// Two guarantees:
//   1. FIELD PARITY — an item record from the item-scoped path is byte-identical
//      (same values AND JSON key order) to describeItem for the same object, so a
//      spliced item matches what a full inspect would have produced.
//   2. COUNT GUARD (DSK17) — a collection whose live count drifted from what the
//      offline payload expects, or an out-of-range kindIndex, marks the WHOLE slide
//      unreadable so the Python caller falls it back to the slide-level merge.

const assert = require("assert");
const m = require("../src/obed_edom/inspect_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A JXA element stub (same shape as inspect_bulk.test.js's).
function stub(vals) {
  const ot = function () {
    if ("text" in vals) return vals.text;
    throw new Error("no objectText");
  };
  ot.size = function () { return vals.size; };
  ot.font = function () { return vals.font; };
  ot.color = function () { return vals.color; };
  const thrower = function () { throw new Error("n/a"); };
  return {
    class: function () { return vals.kind; },
    position: "position" in vals ? function () { return vals.position; } : thrower,
    width: "w" in vals ? function () { return vals.w; } : thrower,
    height: "h" in vals ? function () { return vals.h; } : thrower,
    locked: "locked" in vals ? function () { return vals.locked; } : thrower,
    rotation: "rotation" in vals ? function () { return vals.rotation; } : thrower,
    fileName: "fileName" in vals ? function () { return vals.fileName; } : thrower,
    file: "file" in vals ? function () { return vals.file; } : thrower,
    objectText: ot,
    startPoint: "start" in vals ? function () { return vals.start; } : thrower,
    endPoint: "end" in vals ? function () { return vals.end; } : thrower,
  };
}

// A slide stub whose kind collections return the given object arrays.
function slideStub(collections) {
  const slide = {};
  const names = {
    textItems: "textItems", images: "images", shapes: "shapes",
    movies: "movies", groups: "groups", lines: "lines",
  };
  for (const name in names) {
    const arr = collections[name] || [];
    slide[name] = (function (a) { return function () { return a; }; })(arr);
  }
  return slide;
}

function docStub(slideList) {
  return { slides: function () { return slideList; } };
}

// --- field parity ----------------------------------------------------------

test("item record == describeItem for the same object (image)", function () {
  const vals = {
    kind: "image", position: [12, 34], w: 800, h: 600, locked: false,
    rotation: 0, fileName: "photo.png",
  };
  const doc = docStub([slideStub({ images: [stub(vals)] })]);
  const plan = { items: [{ slide: 1, kind: "image", kindIndex: 0 }] };
  const out = m.readPlanItems(doc, plan);
  const rec = out["0"].items[0];
  const legacy = m.describeItem(stub(vals), 0, "image");
  legacy.kindIndex = 0;
  assert.strictEqual(out["0"].unreadable, false);
  assert.strictEqual(JSON.stringify(rec), JSON.stringify(legacy));
});

test("item record == describeItem for a text box with size/font/color", function () {
  const vals = {
    kind: "text", position: [100, 200], w: 300, h: 120, locked: false,
    rotation: 0, text: "Hi", size: 24, font: "Times", color: [7, 8, 9],
  };
  const doc = docStub([slideStub({ textItems: [stub({ kind: "text" }), stub(vals)] })]);
  const plan = {
    items: [{ slide: 1, kind: "text", kindIndex: 1 }],
    counts: { "1": { text: 2 } },
    textPlaceholderSlack: 2,
  };
  const out = m.readPlanItems(doc, plan);
  const rec = out["0"].items[0];
  const legacy = m.describeItem(stub(vals), 1, "text");
  legacy.kindIndex = 1;
  assert.strictEqual(JSON.stringify(rec), JSON.stringify(legacy));
});

test("only the listed item is described, not the whole collection", function () {
  const a = stub({ kind: "image", position: [0, 0], w: 1, h: 1, locked: false, rotation: 0 });
  const b = stub({ kind: "image", position: [5, 5], w: 2, h: 2, locked: false, rotation: 0, fileName: "b.png" });
  const doc = docStub([slideStub({ images: [a, b] })]);
  const out = m.readPlanItems(doc, { items: [{ slide: 1, kind: "image", kindIndex: 1 }] });
  assert.strictEqual(out["0"].items.length, 1);
  assert.strictEqual(out["0"].items[0].kindIndex, 1);
  assert.strictEqual(out["0"].items[0].fileName, "b.png");
});

// --- count guard (DSK17) ---------------------------------------------------

test("exact-count kind: a drift marks the whole slide unreadable", function () {
  // offline expects 3 images, live collection has 2 -> a mid-list drop desynced
  // kindIndex; the slide must fall back whole, never splice.
  const imgs = [stub({ kind: "image", w: 1, h: 1, locked: false, rotation: 0 }),
                stub({ kind: "image", w: 1, h: 1, locked: false, rotation: 0 })];
  const doc = docStub([slideStub({ images: imgs })]);
  const plan = { items: [{ slide: 1, kind: "image", kindIndex: 1 }], counts: { "1": { image: 3 } } };
  const out = m.readPlanItems(doc, plan);
  assert.strictEqual(out["0"].unreadable, true);
  assert.deepStrictEqual(out["0"].items, []);
});

test("text kind tolerates trailing placeholders within slack", function () {
  // offline expects 1 text; live has 3 (2 trailing empty placeholders) -> within
  // slack, still readable, and kindIndex 0 addresses the real box.
  const boxes = [stub({ kind: "text", position: [1, 1], w: 10, h: 10, locked: false, rotation: 0, text: "T", size: 12, font: "F", color: null }),
                 stub({ kind: "text", position: [0, 0], w: 0, h: 0, locked: false, rotation: 0, text: "", size: 0, font: "", color: null }),
                 stub({ kind: "text", position: [0, 0], w: 0, h: 0, locked: false, rotation: 0, text: "", size: 0, font: "", color: null })];
  const doc = docStub([slideStub({ textItems: boxes })]);
  const plan = { items: [{ slide: 1, kind: "text", kindIndex: 0 }], counts: { "1": { text: 1 } }, textPlaceholderSlack: 2 };
  const out = m.readPlanItems(doc, plan);
  assert.strictEqual(out["0"].unreadable, false);
  assert.strictEqual(out["0"].items[0].text, "T");
});

test("text drift beyond slack marks the slide unreadable", function () {
  const boxes = [stub({ kind: "text", w: 0, h: 0, locked: false, rotation: 0, text: "", size: 0, font: "", color: null })];
  const doc = docStub([slideStub({ textItems: boxes })]); // live 1, expected 4 -> live < expected
  const plan = { items: [{ slide: 1, kind: "text", kindIndex: 0 }], counts: { "1": { text: 4 } }, textPlaceholderSlack: 2 };
  const out = m.readPlanItems(doc, plan);
  assert.strictEqual(out["0"].unreadable, true);
});

test("out-of-range kindIndex marks the slide unreadable", function () {
  const doc = docStub([slideStub({ images: [stub({ kind: "image", w: 1, h: 1, locked: false, rotation: 0 })] })]);
  const out = m.readPlanItems(doc, { items: [{ slide: 1, kind: "image", kindIndex: 5 }] });
  assert.strictEqual(out["0"].unreadable, true);
});

test("a slide number past the deck is unreadable, not a crash", function () {
  const doc = docStub([slideStub({})]);
  const out = m.readPlanItems(doc, { items: [{ slide: 9, kind: "image", kindIndex: 0 }] });
  assert.strictEqual(out["8"].unreadable, true);
});

test("no expected count => count guard is skipped (range check only)", function () {
  const doc = docStub([slideStub({ images: [stub({ kind: "image", w: 1, h: 1, locked: false, rotation: 0, fileName: "x.png" })] })]);
  const out = m.readPlanItems(doc, { items: [{ slide: 1, kind: "image", kindIndex: 0 }] });
  assert.strictEqual(out["0"].unreadable, false);
  assert.strictEqual(out["0"].items[0].fileName, "x.png");
});

console.log("\n" + passed + " passed");
