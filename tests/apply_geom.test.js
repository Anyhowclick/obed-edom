// Unit tests for applyGeom's group-child write path (remap_keynote.js, fix3).
// Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/apply_geom.test.js
//
// A Keynote 15.3.1 group resize is an aspect-locked uniform scale about the
// group's LIVE frame and permanently freezes an autosize text child at its
// wrapped height. A group holding an autosize text child must therefore be
// written child-by-child (width only for the autosize child), never resized
// as a group. These tests assert applyGeom takes that path and leaves the
// group's own width/height/position untouched when `spec.children` is set,
// while a plain group with no `children` still resizes as before.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A JXA-style stub: reading is a function call (`obj.width()`), writing is a
// plain assignment (`obj.width = v`) — exactly how the ObjC bridge exposes
// these properties. `writes` counts each setter invocation.
function stub(x, y, w, h) {
  const state = { x: x, y: y, w: w, h: h };
  const writes = { width: 0, height: 0, position: 0 };
  const obj = { _state: state, _writes: writes };
  Object.defineProperty(obj, "width", {
    get: function () {
      return function () {
        return state.w;
      };
    },
    set: function (v) {
      writes.width += 1;
      state.w = v;
    },
  });
  Object.defineProperty(obj, "height", {
    get: function () {
      return function () {
        return state.h;
      };
    },
    set: function (v) {
      writes.height += 1;
      state.h = v;
    },
  });
  Object.defineProperty(obj, "position", {
    get: function () {
      return function () {
        return [state.x, state.y];
      };
    },
    set: function (v) {
      writes.position += 1;
      if (Array.isArray(v)) {
        state.x = v[0];
        state.y = v[1];
      } else {
        state.x = v.x;
        state.y = v.y;
      }
    },
  });
  obj.locked = function () {
    return false;
  };
  return obj;
}

function groupOf(shapes, textItems) {
  const g = stub(0, 0, 0, 0);
  g.shapes = function () {
    return shapes;
  };
  g.textItems = function () {
    return textItems;
  };
  return g;
}

function childSpecs() {
  return [
    { kind: "shape", kindIndex: 0, x: 1700, y: 40, w: 273, h: 86 },
    { kind: "text", kindIndex: 0, x: 1704.8, y: 47.66, cy: 82.02, w: 263.4, h: 68.7, autosize: true },
  ];
}

test("applyGeom(full) on a group with children writes the children, never the group", function () {
  const plate = stub(4164, 39, 278, 88);
  const text = stub(4169, 47, 268, 66);
  const group = groupOf([plate], [text]);
  const spec = { kind: "group", w: 273, h: 86, x: 1700, y: 40, children: childSpecs() };
  const ok = m.applyGeom(group, spec, "full");
  assert.strictEqual(ok, true);
  assert.strictEqual(group._writes.width, 0);
  assert.strictEqual(group._writes.height, 0);
  assert.strictEqual(group._writes.position, 0);
  assert.strictEqual(plate._state.w, 273);
  assert.strictEqual(plate._state.h, 86);
  assert.deepStrictEqual([plate._state.x, plate._state.y], [1700, 40]);
  assert.strictEqual(text._state.w, 263.4);
  // Text height is left as Keynote's own (66 here, from the stub); position centres on it.
  assert.strictEqual(text._state.x, 1704.8);
  assert.strictEqual(text._state.y, 82.02 - 66 / 2);
});

test("applyGeom(pos) writes positions only; applyGeom(attrs) writes nothing", function () {
  const plate = stub(4164, 39, 278, 88);
  const text = stub(4169, 47, 268, 66);
  const group = groupOf([plate], [text]);
  const spec = { kind: "group", w: 273, h: 86, x: 1700, y: 40, children: childSpecs() };

  m.applyGeom(group, spec, "pos");
  assert.strictEqual(plate._state.w, 278); // size untouched
  assert.strictEqual(plate._state.h, 88);
  assert.deepStrictEqual([plate._state.x, plate._state.y], [1700, 40]); // position written
  assert.strictEqual(text._state.w, 268); // autosize width untouched in pos mode
  assert.strictEqual(text._state.y, 82.02 - 66 / 2); // still centred on its (unchanged) height

  const plate2 = stub(4164, 39, 278, 88);
  const text2 = stub(4169, 47, 268, 66);
  const group2 = groupOf([plate2], [text2]);
  const ok2 = m.applyGeom(group2, spec, "attrs");
  assert.strictEqual(ok2, false);
  assert.deepStrictEqual([plate2._state.x, plate2._state.y, plate2._state.w, plate2._state.h], [4164, 39, 278, 88]);
  assert.deepStrictEqual([text2._state.x, text2._state.y, text2._state.w, text2._state.h], [4169, 47, 268, 66]);
});

test("applyGeom(full) on a group with no children still resizes the group (old path intact)", function () {
  const group = stub(0, 0, 400, 300);
  const ok = m.applyGeom(group, { kind: "group", w: 120, h: 100 }, "full");
  assert.strictEqual(ok, true);
  assert.strictEqual(group._state.w, 120);
  assert.strictEqual(group._state.h, 100);
});

console.log("\n" + passed + " passed");
