// Unit tests for the attrs-pass levers (remap_keynote.js, h-attrs-roundtrips (i)+(ii)):
// each kind collection is fetched once per slide via a cache, and specs with
// nothing to write skip applyGeom entirely. Pure JS — no Keynote, no Apple
// Events. Run with:
//
//     node tests/attrs_roundtrips.test.js
//
// Applied/missed counts must stay identical to pre-lever behaviour; only the
// number of collection fetches and object touches should drop.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A JXA-style item: `locked` is read as a function call and written as a plain
// assignment (mirrors Keynote's ObjC bridge). Reads/writes land in `c` so a
// test can assert exactly what touched the object and how often.
function makeItem(id, c) {
  const state = { locked: false };
  const obj = {};
  Object.defineProperty(obj, "locked", {
    get: function () {
      c.lockedReads += 1;
      return function () {
        return state.locked;
      };
    },
    set: function (v) {
      state.locked = v;
      c.writes.push(id + ".locked=" + v);
    },
  });
  Object.defineProperty(obj, "opacity", {
    set: function (v) {
      c.writes.push(id + ".opacity=" + v);
    },
  });
  obj.objectText = {};
  Object.defineProperty(obj.objectText, "font", {
    set: function (v) {
      c.writes.push(id + ".font=" + v);
    },
  });
  Object.defineProperty(obj.objectText, "size", {
    set: function (v) {
      c.writes.push(id + ".fontSize=" + v);
    },
  });
  Object.defineProperty(obj.objectText, "color", {
    set: function (v) {
      c.writes.push(id + ".color=" + v);
    },
  });
  return obj;
}

// A slide exposing named collections as JXA-style zero-arg calls; each call
// bumps c.fetch[name].
function makeSlide(collections, c) {
  const slide = {};
  Object.keys(collections).forEach(function (name) {
    slide[name] = function () {
      c.fetch[name] = (c.fetch[name] || 0) + 1;
      return collections[name];
    };
  });
  return slide;
}

function newCounters() {
  return { fetch: {}, lockedReads: 0, writes: [] };
}

test("writesAttrs matches applyGeom's attrs-mode writes", function () {
  const falsy = [{}, { locked: false }, { opacity: null }, { font: "" }, { fontSize: 0 }, { color: [1, 2] }];
  const truthy = [{ opacity: 0 }, { font: "A" }, { fontSize: 12 }, { color: [1, 2, 3] }, { locked: true }];
  falsy.forEach(function (spec) {
    assert.strictEqual(m.writesAttrs(spec), false, JSON.stringify(spec));
  });
  truthy.forEach(function (spec) {
    assert.strictEqual(m.writesAttrs(spec), true, JSON.stringify(spec));
  });
});

test("attrs pass fetches each collection once per slide and skips no-attr specs", function () {
  const c = newCounters();
  const shapes = [makeItem("s0", c), makeItem("s1", c), makeItem("s2", c)];
  const textItems = [makeItem("t0", c), makeItem("t1", c)];
  const slide = makeSlide({ shapes: shapes, textItems: textItems }, c);
  const specs = [
    { slide: 1, kind: "shape", kindIndex: 0 },
    { slide: 1, kind: "shape", kindIndex: 1 },
    { slide: 1, kind: "shape", kindIndex: 2, opacity: 0.5 },
    { slide: 1, kind: "text", kindIndex: 0 },
    { slide: 1, kind: "text", kindIndex: 1, font: "Helvetica" },
  ];
  const r = m.applyTransforms([slide], specs, null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 5, missed: 0 });
  assert.deepStrictEqual(c.fetch, { shapes: 1, textItems: 1 });
  assert.strictEqual(c.lockedReads, 2);
  assert.deepStrictEqual(c.writes, ["s2.opacity=0.5", "t1.font=Helvetica"]);
});

test("outside attrs mode there is no cache: every spec refetches its collection", function () {
  const c = newCounters();
  const shapes = [makeItem("s0", c), makeItem("s1", c), makeItem("s2", c)];
  const textItems = [makeItem("t0", c), makeItem("t1", c)];
  const slide = makeSlide({ shapes: shapes, textItems: textItems }, c);
  const specs = [
    { slide: 1, kind: "shape", kindIndex: 0 },
    { slide: 1, kind: "shape", kindIndex: 1 },
    { slide: 1, kind: "shape", kindIndex: 2, opacity: 0.5 },
    { slide: 1, kind: "text", kindIndex: 0 },
    { slide: 1, kind: "text", kindIndex: 1, font: "Helvetica" },
  ];
  m.applyTransforms([slide], specs, null, [], "pos");
  assert.deepStrictEqual(c.fetch, { shapes: 3, textItems: 2 });
});

test("misses: slide out of range and a missing item are counted with reasons", function () {
  const c = newCounters();
  const slide = makeSlide({ shapes: [] }, c);
  const missReasons = [];
  const r = m.applyTransforms(
    [slide],
    [
      { slide: 2, kind: "shape", kindIndex: 0 },
      { slide: 1, kind: "shape", kindIndex: 9, itemIndex: 9 },
    ],
    null,
    missReasons,
    "attrs"
  );
  assert.deepStrictEqual(r, { applied: 0, missed: 2 });
  assert.ok(/slide 2 out of range \(1\)/.test(missReasons[0]), missReasons[0]);
  assert.ok(/missing/.test(missReasons[1]), missReasons[1]);
});

test("misses: a kind with no matching collection falls through to itemIndex and still misses", function () {
  const c = newCounters();
  const slide = {}; // no shapes(), no iWorkItems()
  const r = m.applyTransforms([slide], [{ slide: 1, kind: "shape", kindIndex: 9, itemIndex: 9 }], null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 0, missed: 1 });
});

test("untyped specs (kind with no column) fall through to iWorkItems, cached once", function () {
  const c = newCounters();
  const a = makeItem("a", c);
  const b = makeItem("b", c);
  const slide = makeSlide({ iWorkItems: [a, b] }, c);
  const r = m.applyTransforms(
    [slide],
    [
      { slide: 1, kind: "table", itemIndex: 0 },
      { slide: 1, kind: "table", itemIndex: 1 },
    ],
    null,
    [],
    "attrs"
  );
  assert.deepStrictEqual(r, { applied: 2, missed: 0 });
  assert.deepStrictEqual(c.fetch, { iWorkItems: 1 });
});

test("locked: a no-attr spec on a locked item never touches the object", function () {
  const c = newCounters();
  const shapes = [makeItem("x", c)];
  shapes[0].locked = true;
  c.writes = []; // discard the setup write
  const slide = makeSlide({ shapes: shapes }, c);
  const r = m.applyTransforms([slide], [{ slide: 1, kind: "shape", kindIndex: 0 }], null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 1, missed: 0 });
  assert.strictEqual(c.lockedReads, 0);
  assert.deepStrictEqual(c.writes, []);
});

test("locked: a locked:true spec on an unlocked item reads once and writes the lock", function () {
  const c = newCounters();
  const shapes = [makeItem("x", c)];
  const slide = makeSlide({ shapes: shapes }, c);
  const r = m.applyTransforms([slide], [{ slide: 1, kind: "shape", kindIndex: 0, locked: true }], null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 1, missed: 0 });
  assert.strictEqual(c.lockedReads, 1);
  assert.deepStrictEqual(c.writes, ["x.locked=true"]);
});

test("locked: a font spec on a locked item unlocks, writes, relocks", function () {
  const c = newCounters();
  const shapes = [makeItem("x", c)];
  shapes[0].locked = true;
  c.writes = []; // discard the setup write
  const slide = makeSlide({ shapes: shapes }, c);
  const r = m.applyTransforms([slide], [{ slide: 1, kind: "shape", kindIndex: 0, font: "F" }], null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 1, missed: 0 });
  assert.strictEqual(c.lockedReads, 1);
  assert.deepStrictEqual(c.writes, ["x.locked=false", "x.font=F", "x.locked=true"]);
});

function groupOf(shapes, textItems, c) {
  const g = makeItem("g", c);
  g.shapes = function () {
    c.fetch.groupShapes = (c.fetch.groupShapes || 0) + 1;
    return shapes;
  };
  g.textItems = function () {
    c.fetch.groupTextItems = (c.fetch.groupTextItems || 0) + 1;
    return textItems;
  };
  return g;
}

test("groups: applyGroupChildren short-circuits in attrs mode, no child fetches", function () {
  const c = newCounters();
  const plate = makeItem("plate", c);
  const group = groupOf([plate], [], c);
  const spec = {
    kind: "group",
    opacity: 0.5,
    children: [{ kind: "shape", kindIndex: 0, x: 10, y: 10 }],
  };
  const ok = m.applyGeom(group, spec, "attrs");
  assert.strictEqual(ok, true);
  assert.deepStrictEqual(c.writes, ["g.opacity=0.5"]);
  assert.strictEqual(c.fetch.groupShapes, undefined);
  assert.strictEqual(c.fetch.groupTextItems, undefined);
});

test("groups: a resolved no-attr group spec skips applyGeom, never touches group children", function () {
  const c = newCounters();
  const plate = makeItem("plate", c);
  const group = groupOf([plate], [], c);
  const slide = makeSlide({ groups: [group] }, c);
  const spec = { slide: 1, kind: "group", kindIndex: 0, children: [{ kind: "shape", kindIndex: 0, x: 10, y: 10 }] };
  const r = m.applyTransforms([slide], [spec], null, [], "attrs");
  assert.deepStrictEqual(r, { applied: 1, missed: 0 });
  assert.deepStrictEqual(c.fetch, { groups: 1 });
  assert.strictEqual(c.lockedReads, 0);
  assert.strictEqual(c.fetch.groupShapes, undefined);
});

test("applyGroupChildren returns false immediately in attrs mode", function () {
  const c = newCounters();
  const plate = makeItem("plate", c);
  const group = groupOf([plate], [], c);
  const spec = { children: [{ kind: "shape", kindIndex: 0, x: 10, y: 10 }] };
  const ok = m.applyGroupChildren(group, spec, "attrs");
  assert.strictEqual(ok, false);
  assert.strictEqual(c.fetch.groupShapes, undefined);
});

test("applyNonReuseSlide attrs path: one opacity write, hides delete in (kind asc, kindIndex desc) order", function () {
  const c = newCounters();
  const shapes = [makeItem("s0", c), makeItem("s1", c), makeItem("s2", c)];
  const textItems = [makeItem("t0", c)];
  const slide = makeSlide({ shapes: shapes, textItems: textItems }, c);
  const doc = {
    slides: function () {
      return [slide];
    },
  };
  const Keynote = {
    delete: function (obj) {
      const inShapes = shapes.indexOf(obj);
      if (inShapes !== -1) {
        c.writes.push("delete:" + (inShapes === 0 ? "s0" : inShapes === 1 ? "s1" : "s2"));
        shapes.splice(inShapes, 1);
        return;
      }
      const inText = textItems.indexOf(obj);
      c.writes.push("delete:t" + inText);
      textItems.splice(inText, 1);
    },
  };
  const transforms = [
    { slide: 1, kind: "shape", kindIndex: 0, role: "text", opacity: 0.5 },
    { slide: 1, kind: "shape", kindIndex: 1, role: "hide" },
    { slide: 1, kind: "shape", kindIndex: 2, role: "hide" },
    { slide: 1, kind: "text", kindIndex: 0, role: "hide" },
  ];
  const missReasons = [];
  const r = m.applyNonReuseSlide(doc, Keynote, 1, transforms, null, missReasons, null, [1]);
  assert.deepStrictEqual(r, { applied: 4, missed: 0 });
  assert.deepStrictEqual(c.writes, ["s0.opacity=0.5", "delete:s2", "delete:s1", "delete:t0"]);
  // deleteHides has no cache of its own: each hide refetches its collection directly,
  // on top of the one cached fetch the attrs pass already made for "shapes".
  assert.deepStrictEqual(c.fetch, { shapes: 3, textItems: 1 });
  assert.strictEqual(c.lockedReads, 1);
});

console.log("\n" + passed + " passed");
