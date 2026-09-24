// Unit tests for pass-1 offline hides (remap_keynote.js, Stream C of
// .agents/plans/pass1_hides_offline.plan.md). Pure JS — no Keynote, no Apple
// Events. Run with:
//
//     node tests/offline_hides.test.js
//
// A slide listed in plan.offlineHideSlides skips deleteHides: its hides stay in
// the deck for the offline IWA writer, and their count is returned as
// hidesDeferred. Unlisted slides keep the Keynote delete order exactly. The
// pass-1 zero-applied abort must not fire when hides were only deferred.

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

// JXA-style item: reads are calls, writes are assignments; every write lands in `log`.
function makeItem(id, log) {
  const obj = { id: id };
  obj.locked = function () {
    return false;
  };
  Object.defineProperty(obj, "opacity", {
    set: function (v) {
      log.push(id + ".opacity=" + v);
    },
  });
  return obj;
}

// One slide per entry of `bySlide` ({shapes: [...ids], textItems: [...ids]}).
// Keynote.delete removes the object from its collection, like the real app.
function fixture(bySlide) {
  const log = [];
  const slides = bySlide.map(function (cols) {
    const slide = {};
    Object.keys(cols).forEach(function (name) {
      const items = cols[name].map(function (id) {
        return makeItem(id, log);
      });
      slide[name] = function () {
        return items;
      };
    });
    return slide;
  });
  const Keynote = {
    delete: function (obj) {
      log.push("delete:" + obj.id);
      for (let s = 0; s < slides.length; s++) {
        const cols = bySlide[s];
        for (const name in cols) {
          const items = slides[s][name]();
          const i = items.indexOf(obj);
          if (i !== -1) {
            items.splice(i, 1);
            return;
          }
        }
      }
    },
  };
  const doc = {
    slides: function () {
      return slides;
    },
  };
  return { log: log, slides: slides, doc: doc, Keynote: Keynote };
}

const SLIDE1 = [
  { slide: 1, kind: "shape", kindIndex: 0, role: "text", opacity: 0.5 },
  { slide: 1, kind: "shape", kindIndex: 1, role: "hide" },
  { slide: 1, kind: "shape", kindIndex: 2, role: "hide" },
  { slide: 1, kind: "text", kindIndex: 0, role: "hide" },
];

function slide1Fixture() {
  return fixture([{ shapes: ["s0", "s1", "s2"], textItems: ["t0"] }]);
}

test("listed slide skips every delete and reports hidesDeferred", function () {
  const f = slide1Fixture();
  const r = m.applyNonReuseSlide(f.doc, f.Keynote, 1, SLIDE1, null, [], null, [1], [1]);
  assert.deepStrictEqual(r, { applied: 1, missed: 0, hidesDeferred: 3 });
  assert.deepStrictEqual(f.log, ["s0.opacity=0.5"]);
  assert.strictEqual(f.slides[0].shapes().length, 3, "hides stay in the deck");
  assert.strictEqual(f.slides[0].textItems().length, 1);
  assert.ok("hides" in m.STAGES, "hides stage key still recorded");
});

test("listed slide with TIMING set records no deleteHides buckets", function () {
  const timing = { buckets: {}, slow: [], slowMs: 120 };
  m.setTiming(timing);
  const f = slide1Fixture();
  m.applyNonReuseSlide(f.doc, f.Keynote, 1, SLIDE1, null, [], null, [1], [1]);
  assert.strictEqual(timing.buckets["phase:deleteHides:slide1"], undefined);
  assert.strictEqual(timing.buckets["deleteHide"], undefined);
  assert.strictEqual(timing.buckets["phase:attrsSuppressed:slide1"].n, 1);
});

test("unlisted slide keeps the delete order and the {applied, missed} shape", function () {
  const f = slide1Fixture();
  const r = m.applyNonReuseSlide(f.doc, f.Keynote, 1, SLIDE1, null, [], null, [1], [2, 3]);
  assert.deepStrictEqual(r, { applied: 4, missed: 0 });
  assert.deepStrictEqual(f.log, ["s0.opacity=0.5", "delete:s2", "delete:s1", "delete:t0"]);
});

test("null or absent offlineHideSlides behaves as before", function () {
  [null, undefined, []].forEach(function (off) {
    const f = slide1Fixture();
    const r = m.applyNonReuseSlide(f.doc, f.Keynote, 1, SLIDE1, null, [], null, [1], off);
    assert.deepStrictEqual(r, { applied: 4, missed: 0 });
    assert.deepStrictEqual(f.log, ["s0.opacity=0.5", "delete:s2", "delete:s1", "delete:t0"]);
  });
});

test("listed slide with no hides reports hidesDeferred 0", function () {
  const f = slide1Fixture();
  const r = m.applyNonReuseSlide(f.doc, f.Keynote, 1, [SLIDE1[0]], null, [], null, [1], [1]);
  assert.deepStrictEqual(r, { applied: 1, missed: 0, hidesDeferred: 0 });
});

// run() needs the JXA globals. readJSON goes through $.NSData/$.NSString and
// ObjC.unwrap; the stubs hand the plan object straight back as its JSON string.
function installJxa(plan, f) {
  const calls = [];
  global.ObjC = {
    unwrap: function (s) {
      return s;
    },
  };
  global.$ = {
    NSData: {
      dataWithContentsOfFile: function () {
        return JSON.stringify(plan);
      },
    },
    NSString: {
      alloc: {
        initWithDataEncoding: function (data) {
          return data;
        },
      },
    },
    NSUTF8StringEncoding: 4,
  };
  global.Path = function (p) {
    return p;
  };
  f.Keynote.open = function () {
    calls.push("open");
    return f.doc;
  };
  f.Keynote.save = function () {
    calls.push("save");
  };
  f.Keynote.close = function (doc, opts) {
    calls.push("close:" + opts.saving);
  };
  global.Application = function () {
    return f.Keynote;
  };
  return calls;
}

function uninstallJxa() {
  delete global.ObjC;
  delete global.$;
  delete global.Path;
  delete global.Application;
}

test("run: deferred-only hides do not abort; result carries hidesDeferred", function () {
  const f = fixture([{ shapes: ["s0", "s1"] }]);
  const plan = {
    dest: "/tmp/x.key",
    slides: [1],
    transforms: [
      { slide: 1, kind: "shape", kindIndex: 0, role: "hide" },
      { slide: 1, kind: "shape", kindIndex: 1, role: "hide" },
    ],
    suppressGeometry: [1],
    offlineHideSlides: [1],
  };
  const calls = installJxa(plan, f);
  try {
    const out = JSON.parse(m.run(["plan.json"]));
    assert.strictEqual(out.applied, 0);
    assert.strictEqual(out.missed, 0);
    assert.strictEqual(out.hidesDeferred, 2);
    assert.strictEqual(out.saved, true);
    assert.deepStrictEqual(calls, ["open", "save", "close:yes"]);
    assert.ok("hides" in out.stages);
    assert.deepStrictEqual(f.log, []);
  } finally {
    uninstallJxa();
  }
});

test("run: zero applied and nothing deferred still aborts without saving", function () {
  const f = fixture([{ shapes: [] }]);
  const plan = {
    dest: "/tmp/x.key",
    slides: [1],
    transforms: [{ slide: 1, kind: "shape", kindIndex: 0, role: "hide" }],
    suppressGeometry: [1],
  };
  const calls = installJxa(plan, f);
  try {
    const out = JSON.parse(m.run(["plan.json"]));
    assert.strictEqual(out.applied, 0);
    assert.strictEqual(out.missed, 1);
    assert.strictEqual(out.hidesDeferred, 0);
    assert.strictEqual(out.saved, false);
    assert.deepStrictEqual(calls, ["open", "close:no"]);
  } finally {
    uninstallJxa();
  }
});

test("run: mixed plan defers listed slides and deletes the rest", function () {
  const f = fixture([{ shapes: ["a0", "a1"] }, { shapes: ["b0", "b1"] }]);
  const plan = {
    dest: "/tmp/x.key",
    slides: [1, 2],
    transforms: [
      { slide: 1, kind: "shape", kindIndex: 1, role: "hide" },
      { slide: 2, kind: "shape", kindIndex: 0, role: "hide" },
      { slide: 2, kind: "shape", kindIndex: 1, role: "hide" },
    ],
    suppressGeometry: [1, 2],
    offlineHideSlides: [1],
  };
  const calls = installJxa(plan, f);
  try {
    const out = JSON.parse(m.run(["plan.json"]));
    assert.strictEqual(out.applied, 2);
    assert.strictEqual(out.hidesDeferred, 1);
    assert.deepStrictEqual(f.log, ["delete:b1", "delete:b0"]);
    assert.deepStrictEqual(calls, ["open", "save", "close:yes"]);
  } finally {
    uninstallJxa();
  }
});

console.log("\n" + passed + " passed");
