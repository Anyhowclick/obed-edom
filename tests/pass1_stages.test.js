// Unit tests for the always-on pass-1 stage timer (remap_keynote.js, m1-stage-timer).
// Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/pass1_stages.test.js
//
// STAGES accumulates elapsed ms per stage name via _stage(name, t0), so a stage
// hit once per slide (attrs, hides) sums across slides. It is independent of the
// opt-in TIMING/_trec buckets: it must fill whether TIMING is null or set.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");

let passed = 0;
function test(name, fn) {
  m._resetStages();
  m.setTiming(null);
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

function spin(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {}
}

// A JXA-style shape: reads are calls, writes are assignments. locked() spins
// so each object access costs measurable wall time.
function shape() {
  return {
    locked: function () {
      spin(3);
      return false;
    },
  };
}

// One slide with two shapes; Keynote.delete removes the object from the
// slide's shapes, like the real app.
function fixture() {
  const shapes = [shape(), shape()];
  const slide = {
    shapes: function () {
      return shapes;
    },
  };
  const doc = {
    slides: function () {
      return [slide];
    },
  };
  const Keynote = {
    delete: function (obj) {
      spin(3);
      shapes.splice(shapes.indexOf(obj), 1);
    },
  };
  const transforms = [
    { slide: 1, kind: "shape", kindIndex: 0, role: "text" },
    { slide: 1, kind: "shape", kindIndex: 1, role: "hide" },
  ];
  return { doc: doc, Keynote: Keynote, transforms: transforms, shapes: shapes };
}

function drive(f) {
  return m.applyNonReuseSlide(f.doc, f.Keynote, 1, f.transforms, {}, [], null, [1]);
}

// AS path: runAppleScript reads doc.name() (stubbed to spin 20 ms) and then
// fails on the missing ObjC bridge, so no osascript runs; runSlideGeomScript
// catches that into missReasons. All that time must land in asScript.
function driveAs(f, missReasons) {
  f.doc.name = function () {
    spin(20);
    return "deck";
  };
  return m.applyNonReuseSlide(f.doc, f.Keynote, 1, f.transforms, {}, missReasons, { 1: "noop" }, null);
}

// JXA path: "full" then "pos" pass. Each pass reads locked() on the text shape
// (3 ms), so two passes put at least 6 ms into attrs.
function driveJxa(f, missReasons) {
  return m.applyNonReuseSlide(f.doc, f.Keynote, 1, f.transforms, {}, missReasons, null, null);
}

test("_stage accumulates across calls", function () {
  let t0 = Date.now();
  spin(5);
  m._stage("x", t0);
  const first = m.STAGES.x;
  assert.ok(first >= 5, "first call recorded " + first);
  t0 = Date.now();
  spin(5);
  m._stage("x", t0);
  assert.ok(m.STAGES.x >= first + 5, "second call added: " + m.STAGES.x);
  assert.deepStrictEqual(Object.keys(m.STAGES), ["x"]);
});

test("_resetStages clears in place (exported reference stays live)", function () {
  const ref = m.STAGES;
  m._stage("y", Date.now());
  m._resetStages();
  assert.deepStrictEqual(m.STAGES, {});
  assert.strictEqual(m.STAGES, ref);
});

test("applyNonReuseSlide attrs path fills attrs and hides with TIMING null", function () {
  const f = fixture();
  const r = drive(f);
  assert.deepStrictEqual(r, { applied: 2, missed: 0 });
  assert.strictEqual(f.shapes.length, 1, "hide deleted");
  assert.ok(m.STAGES.attrs >= 3, "attrs " + m.STAGES.attrs);
  assert.ok(m.STAGES.hides >= 3, "hides " + m.STAGES.hides);
  assert.deepStrictEqual(Object.keys(m.STAGES).sort(), ["attrs", "hides"]);
});

test("attrs and hides sum across slides", function () {
  drive(fixture());
  const a1 = m.STAGES.attrs;
  const h1 = m.STAGES.hides;
  drive(fixture());
  assert.ok(m.STAGES.attrs >= a1 + 3, "attrs summed: " + m.STAGES.attrs);
  assert.ok(m.STAGES.hides >= h1 + 3, "hides summed: " + m.STAGES.hides);
});

test("AS path: runSlideGeomScript time lands in asScript, not attrs", function () {
  const f = fixture();
  const miss = [];
  const r = driveAs(f, miss);
  assert.deepStrictEqual(r, { applied: 2, missed: 0 });
  assert.strictEqual(f.shapes.length, 1, "hide deleted");
  assert.ok(/AppleScript geometry failed/.test(miss[0]), "script stub failed: " + miss[0]);
  assert.ok(m.STAGES.asScript >= 20, "asScript " + m.STAGES.asScript);
  assert.ok(m.STAGES.attrs < 20, "attrs excludes the script: " + m.STAGES.attrs);
  assert.ok(m.STAGES.hides >= 3, "hides " + m.STAGES.hides);
});

test("JXA path: both apply passes add to attrs; hide deleted after geometry", function () {
  const f = fixture();
  const order = [];
  Object.defineProperty(f.shapes[0], "position", {
    set: function () {
      order.push("pos");
    },
    get: function () {
      return function () {
        return [0, 0];
      };
    },
  });
  const del = f.Keynote.delete;
  f.Keynote.delete = function (obj) {
    order.push("delete");
    del(obj);
  };
  const t = f.transforms[0];
  t.x = 10;
  t.y = 20;
  const r = driveJxa(f, []);
  // Same counts as HEAD before the timer: the bare stub has no width/height, so
  // the "full" pass reports the text shape missed; the hide still applies.
  assert.deepStrictEqual(r, { applied: 1, missed: 1 });
  assert.strictEqual(f.shapes.length, 1, "hide deleted");
  assert.ok(m.STAGES.attrs >= 6, "attrs from both passes: " + m.STAGES.attrs);
  assert.strictEqual(m.STAGES.asScript, undefined);
  assert.strictEqual(order[order.length - 1], "delete");
  assert.ok(order.filter(function (o) { return o === "pos"; }).length >= 2, "two position passes: " + order);
});

test("applyNonReuseSlide with TIMING set fills both STAGES and TIMING", function () {
  const timing = { buckets: {}, slow: [], slowMs: 120 };
  m.setTiming(timing);
  const f = fixture();
  const r = drive(f);
  assert.deepStrictEqual(r, { applied: 2, missed: 0 });
  assert.ok(m.STAGES.attrs >= 3, "attrs " + m.STAGES.attrs);
  assert.ok(m.STAGES.hides >= 3, "hides " + m.STAGES.hides);
  assert.strictEqual(timing.buckets["phase:attrsSuppressed:slide1"].n, 1);
  assert.strictEqual(timing.buckets["phase:deleteHides:slide1"].n, 1);
  assert.strictEqual(timing.buckets["deleteHide"].n, 1);
});

console.log(passed + " passed");
