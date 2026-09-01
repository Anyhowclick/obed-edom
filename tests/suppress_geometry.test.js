// Branch-decision unit test for the OBED_SUPPRESS_GEOMETRY knob (Piece 1). Pure
// JS — no Keynote, no Apple Events. Run with:
//
//     node tests/suppress_geometry.test.js
//
// applyNonReuseSlide itself needs a live Keynote `doc`/`Keynote` app object, so it
// is not Node-harnessable; the correctness lynchpin — that a SUPPRESSED slide takes
// NEITHER geometry branch — lives in the pure `geometryPathForSlide` it dispatches
// on, which IS testable. These tests pin every branch of that decision.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");
const geometryPathForSlide = m.geometryPathForSlide;

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

test("suppressed slide => attrs (neither AS nor JXA geometry)", function () {
  // n is in suppressGeometry: attrs-only regardless of asGeom.
  assert.strictEqual(geometryPathForSlide(9, null, [9]), "attrs");
});

test("suppression WINS over an AppleScript body for the same slide", function () {
  // Even with an asGeom body present for slide 9, suppression forces attrs-only —
  // this is the whole point: an empty-asGeom slide must not fall through to JXA,
  // and a bodied one must not silently take the AS geometry branch.
  const asGeom = { 9: "tell slide 9 ... end tell" };
  assert.strictEqual(geometryPathForSlide(9, asGeom, [9]), "attrs");
});

test("non-suppressed slide with an AppleScript body => as", function () {
  const asGeom = { 9: "tell slide 9 ... end tell" };
  assert.strictEqual(geometryPathForSlide(9, asGeom, [1, 2]), "as");
});

test("non-suppressed slide with no body => jxa", function () {
  assert.strictEqual(geometryPathForSlide(9, { 8: "body" }, [1]), "jxa");
  assert.strictEqual(geometryPathForSlide(9, null, [1]), "jxa");
});

test("null/empty suppress list never suppresses", function () {
  const asGeom = { 9: "body" };
  assert.strictEqual(geometryPathForSlide(9, asGeom, null), "as");
  assert.strictEqual(geometryPathForSlide(9, asGeom, []), "as");
  assert.strictEqual(geometryPathForSlide(9, null, []), "jxa");
});

console.log("\n" + passed + " passing");
