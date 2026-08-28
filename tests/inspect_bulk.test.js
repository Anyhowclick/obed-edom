// Byte-identity + length-guard unit tests for the bulk-read path in
// inspect_keynote.js. Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/inspect_bulk.test.js
//
// The central guarantee: for every object and every scenario (full bulk,
// partial bulk falling back per-property, file-less image, empty collection),
// describeItemBulk produces a record byte-identical to describeItem — same
// values AND same JSON key order. If that holds, OBED_BULK_READ=1 and =0 emit
// identical payloads, which is the whole safety contract.

const assert = require("assert");
const m = require("../src/obed_edom/inspect_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A JXA element stub: each property is a function; objectText is itself a
// function that also carries .size/.font/.color sub-accessors, exactly as JXA
// exposes it (obj.objectText() vs obj.objectText.size()).
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

// Build the full bulk-array object (single element) from the same values.
function fullBulk(vals, kind) {
  const b = {
    position: ["position" in vals ? vals.position : null],
    width: ["w" in vals ? vals.w : null],
    height: ["h" in vals ? vals.h : null],
    locked: ["locked" in vals ? vals.locked : null],
    rotation: ["rotation" in vals ? vals.rotation : null],
  };
  if (kind === "image" || kind === "movie") {
    b.fileName = ["fileName" in vals ? vals.fileName : null];
  }
  if (kind === "text" || kind === "shape") {
    b.text = ["text" in vals ? vals.text : null];
    b.size = ["size" in vals ? vals.size : null];
    b.font = ["font" in vals ? vals.font : null];
    b.color = ["color" in vals ? vals.color : null];
  }
  if (kind === "line") {
    b.start = ["start" in vals ? vals.start : null];
    b.end = ["end" in vals ? vals.end : null];
  }
  return b;
}

// The proof: same JSON (key order included) from both paths.
function assertIdentical(vals, kind, bulk) {
  const obj = stub(vals);
  const legacy = m.describeItem(obj, 7, kind);
  const bulked = m.describeItemBulk(stub(vals), 7, kind, bulk, 0);
  assert.strictEqual(
    JSON.stringify(bulked),
    JSON.stringify(legacy),
    "\n bulk:   " + JSON.stringify(bulked) + "\n legacy: " + JSON.stringify(legacy)
  );
}

// --- bulkArray length guard ------------------------------------------------

test("bulkArray accepts an array of the exact count", function () {
  assert.deepStrictEqual(m.bulkArray([1, 2, 3], 3), [1, 2, 3]);
});

test("bulkArray rejects a short array (the drift killer)", function () {
  assert.strictEqual(m.bulkArray([1, 2], 3), null);
});

test("bulkArray rejects a long array", function () {
  assert.strictEqual(m.bulkArray([1, 2, 3, 4], 3), null);
});

test("bulkArray rejects null / undefined", function () {
  assert.strictEqual(m.bulkArray(null, 3), null);
  assert.strictEqual(m.bulkArray(undefined, 3), null);
});

test("bulkArray rejects a scalar with no length", function () {
  assert.strictEqual(m.bulkArray(42, 1), null);
});

test("bulkArray accepts an empty array at count 0", function () {
  assert.deepStrictEqual(m.bulkArray([], 0), []);
});

// --- fileNameFrom (secondary-source special case) --------------------------

test("fileNameFrom uses a valid bulk string", function () {
  const obj = stub({ kind: "image" });
  assert.strictEqual(m.fileNameFrom({ fileName: ["pic.png"] }, 0, obj), "pic.png");
});

test("fileNameFrom falls back to fileNameOf when bulk element is null", function () {
  // file-less image: bulk returned missing value; per-object also finds nothing.
  const obj = stub({ kind: "image" });
  assert.strictEqual(m.fileNameFrom({ fileName: [null] }, 0, obj), "");
});

test("fileNameFrom falls back to obj.file() when bulk is empty", function () {
  const obj = stub({ kind: "image", file: "/tmp/x.mov" });
  assert.strictEqual(m.fileNameFrom({ fileName: [null] }, 0, obj), "/tmp/x.mov");
});

// --- byte-identity: full bulk ----------------------------------------------

test("text item — full bulk == per-object", function () {
  const vals = {
    kind: "text", position: [100, 200], w: 300, h: 120, locked: false,
    rotation: 0, text: "Hello", size: 48, font: "Helvetica", color: [1, 2, 3],
  };
  assertIdentical(vals, "text", fullBulk(vals, "text"));
});

test("shape item with color — full bulk == per-object", function () {
  const vals = {
    kind: "shape", position: [10, 20], w: 50, h: 60, locked: true,
    rotation: 90, text: "Box", size: 12, font: "Arial", color: [65535, 60000, 0],
  };
  assertIdentical(vals, "shape", fullBulk(vals, "shape"));
});

test("image with fileName — full bulk == per-object", function () {
  const vals = {
    kind: "image", position: [0, 0], w: 800, h: 600, locked: false,
    rotation: 0, fileName: "photo.png",
  };
  assertIdentical(vals, "image", fullBulk(vals, "image"));
});

test("file-less image — bulk null fileName == per-object empty", function () {
  const vals = {
    kind: "image", position: [5, 5], w: 100, h: 100, locked: false, rotation: 0,
  };
  const bulk = fullBulk(vals, "image");
  bulk.fileName = [null]; // Keynote returned missing value in-place.
  assertIdentical(vals, "image", bulk);
});

test("line — full bulk start/end == per-object", function () {
  const vals = {
    kind: "line", position: [1, 1], w: 0, h: 0, locked: false, rotation: 0,
    start: [10, 10], end: [90, 90],
  };
  assertIdentical(vals, "line", fullBulk(vals, "line"));
});

test("line with no endpoints — keys stay absent in both", function () {
  const vals = { kind: "line", position: [1, 1], w: 0, h: 0, locked: false, rotation: 0 };
  const bulk = fullBulk(vals, "line");
  bulk.start = [null];
  bulk.end = [null];
  assertIdentical(vals, "line", bulk);
});

// --- byte-identity: partial bulk (per-property fallback) -------------------

test("text with size/font/color bulk-missing — falls back per-object", function () {
  const vals = {
    kind: "text", position: [100, 200], w: 300, h: 120, locked: false,
    rotation: 0, text: "Hi", size: 24, font: "Times", color: [7, 8, 9],
  };
  const bulk = fullBulk(vals, "text");
  bulk.size = null; // drift on the nested size fetch only
  bulk.font = null;
  bulk.color = null;
  assertIdentical(vals, "text", bulk);
});

test("text with geometry bulk-missing — falls back to positionOf/sizeOf", function () {
  const vals = {
    kind: "text", position: [100, 200], w: 300, h: 120, locked: false,
    rotation: 0, text: "Hi", size: 24, font: "Times", color: null,
  };
  const bulk = fullBulk(vals, "text");
  bulk.position = null;
  bulk.width = null;
  bulk.height = null;
  assertIdentical(vals, "text", bulk);
});

test("empty bulk object — every property falls back == per-object", function () {
  const vals = {
    kind: "text", position: [100, 200], w: 300, h: 120, locked: true,
    rotation: 45, text: "Full fallback", size: 30, font: "Menlo", color: [1, 1, 1],
  };
  assertIdentical(vals, "text", {}); // all bulk arrays absent
});

test("image missing position/size individually still matches", function () {
  const vals = { kind: "image", w: 100, h: 50, locked: false, rotation: 0, fileName: "a.png" };
  // no position accessor -> positionOf returns [0,0] both paths
  const bulk = fullBulk(vals, "image");
  bulk.position = null;
  assertIdentical(vals, "image", bulk);
});

console.log("\n" + passed + " passed");
