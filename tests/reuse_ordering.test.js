// Unit tests for the reuse-chain pre-add ordering in applyReuse (remap_keynote.js).
//
// Pure JS — no Keynote, no Apple Events, no child_process. `applyReuse` reaches
// JXA-only globals (Application, ObjC, $, delay), so this file installs stubs for
// all of them BEFORE requiring the module. `doShellScript` below only records the
// AppleScript body text captured by the fake `$.NSString.stringWithString` and
// replays "duplicate slide N to before slide M" / "delete slide N" against an
// in-memory fake deck — it never shells out, and node has no JXA bridge to reach
// a real Keynote even if it tried.
//
// Run with:
//
//     node tests/reuse_ordering.test.js

const assert = require("assert");

let LAST_SCRIPT = null;
let DECK = null;
let OPS = [];
let DUP_CALL_COUNT = 0;
let FAIL_ON_DUP_CALL = null;
let COPIED_FROM = null;

function makeItem(id, x, y, w, h) {
  return {
    id: id,
    _x: x,
    _y: y,
    _w: w,
    _h: h,
    position: function () {
      return [this._x, this._y];
    },
    width: function () {
      return this._w;
    },
    height: function () {
      return this._h;
    },
    locked: function () {
      return false;
    },
  };
}

function cloneItem(it) {
  return makeItem(it.id, it._x, it._y, it._w, it._h);
}

function makeSlide(items) {
  const arr = items.slice();
  return {
    shapes: function () {
      return arr;
    },
    _arr: arr,
  };
}

function cloneSlide(slide) {
  return makeSlide(slide._arr.map(cloneItem));
}

function idsOf(slide) {
  return slide._arr.map(function (it) {
    return it.id;
  });
}

// -- doShellScript never executes anything: it parses LAST_SCRIPT (the exact body
// captured by $.NSString.stringWithString just before this call) and replays the
// two AppleScript shapes applyReuse ever issues against the in-memory DECK. --
function parseCommand(script) {
  let m;
  if ((m = /duplicate slide (\d+) to before slide (\d+)/.exec(script))) {
    return { kind: "duplicate", n: Number(m[1]), before: Number(m[2]) };
  }
  if ((m = /delete slide (\d+)/.exec(script))) {
    return { kind: "deleteSlide", n: Number(m[1]) };
  }
  return null;
}

function fakeDoShellScript() {
  const parsed = parseCommand(LAST_SCRIPT || "");
  if (!parsed) return;
  if (parsed.kind === "duplicate") {
    DUP_CALL_COUNT += 1;
    if (FAIL_ON_DUP_CALL != null && DUP_CALL_COUNT === FAIL_ON_DUP_CALL) {
      throw new Error("simulated AppleScript failure");
    }
    const src = DECK[parsed.n - 1];
    const clone = cloneSlide(src);
    const insertAt = Math.min(parsed.before - 1, DECK.length);
    DECK.splice(insertAt, 0, clone);
    OPS.push({ op: "duplicate", args: [parsed.n, parsed.before] });
    return;
  }
  if (parsed.kind === "deleteSlide") {
    const idx = parsed.n - 1;
    if (idx < 0 || idx >= DECK.length) {
      throw new Error("no such slide " + parsed.n);
    }
    DECK.splice(idx, 1);
    OPS.push({ op: "delete_slide", args: [parsed.n] });
    return;
  }
}

function ApplicationStub(id) {
  if (id === "System Events") {
    return {
      keystroke: function (cmd) {
        if (cmd === "c") {
          COPIED_FROM = DOC.currentSlide;
        } else if (cmd === "v") {
          const dest = DOC.currentSlide;
          if (COPIED_FROM && dest) {
            const items = COPIED_FROM._arr.map(cloneItem);
            for (let i = 0; i < items.length; i++) dest._arr.push(items[i]);
            OPS.push({ op: "paste" });
          }
        }
      },
    };
  }
  return {};
}
ApplicationStub.currentApplication = function () {
  return { includeStandardAdditions: false, doShellScript: fakeDoShellScript };
};

global.Application = ApplicationStub;
global.ObjC = {
  import: function () {},
  unwrap: function () {
    return "/tmp/";
  },
};
global.$ = {
  NSTemporaryDirectory: function () {
    return "tmp";
  },
  NSString: {
    stringWithString: function (s) {
      LAST_SCRIPT = s;
      return { writeToFileAtomicallyEncodingError: function () {} };
    },
  },
  NSUTF8StringEncoding: 4,
  NSFileManager: { defaultManager: { removeItemAtPathError: function () {} } },
};
global.delay = function () {};

// Requiring the module AFTER the stubs above are installed: its top-level
// `ObjC.import("Foundation")` runs at require time and needs global.ObjC to exist.
const m = require("../src/obed_edom/remap_keynote.js");

const DOC = {
  name: function () {
    return "TestDoc";
  },
  slides: function () {
    return DECK;
  },
  currentSlide: null,
};

const KEYNOTE = {
  activate: function () {},
  delete: function (obj) {
    for (let i = 0; i < DECK.length; i++) {
      const arr = DECK[i]._arr;
      const idx = arr.indexOf(obj);
      if (idx >= 0) {
        arr.splice(idx, 1);
        OPS.push({ op: "delete_obj", id: obj.id });
        return;
      }
    }
  },
};

function resetCtx(deck) {
  DECK = deck;
  DOC.currentSlide = null;
  COPIED_FROM = null;
  OPS = [];
  DUP_CALL_COUNT = 0;
  FAIL_ON_DUP_CALL = null;
  LAST_SCRIPT = null;
}

function opTypes() {
  return OPS.map(function (o) {
    return o.op;
  });
}

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

test("producer parks the next base before its adds", function () {
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 50, y: 50, w: 5, h: 5 }],
    strip: [],
    mutate: [],
    snapshotNext: 3,
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.deepStrictEqual(opTypes(), ["duplicate", "delete_obj", "delete_obj", "duplicate", "paste", "delete_slide"]);
  assert.deepStrictEqual(OPS[0].args, [1, 2]); // initial duplicate(from, to)
  assert.deepStrictEqual(OPS[3].args, [2, 4]); // snapshot duplicate(to, to+2)
  assert.deepStrictEqual(OPS[5].args, [3]); // delete slide (to+1)

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.duplicated, 1);
  assert.strictEqual(r.parked, true);

  assert.strictEqual(DECK.length, 3);
  assert.deepStrictEqual(idsOf(DECK[0]), ["kept1", "rmA", "rmB"]); // donor untouched
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta"]); // finished copy: removes gone, add pasted
  assert.deepStrictEqual(idsOf(DECK[2]), ["kept1"]); // parked base: removes applied, NOT the add
});

test("consumer with a placed base skips its duplicate", function () {
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("removeMe", 100, 100, 20, 20),
      makeItem("fallbackOnly", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  const job = {
    slide: 1,
    from: 1,
    remove: [{ kind: "shape", x: 100, y: 100, w: 20, h: 20 }],
    removeFallback: [{ kind: "shape", x: 200, y: 100, w: 20, h: 20 }],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 9, y: 9, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.strictEqual(opTypes().indexOf("duplicate"), -1); // no duplicate at all
  assert.deepStrictEqual(
    OPS.filter(function (o) {
      return o.op === "delete_obj";
    }),
    [{ op: "delete_obj", id: "removeMe" }]
  );
  assert.deepStrictEqual(
    OPS.filter(function (o) {
      return o.op === "delete_slide";
    }),
    [{ op: "delete_slide", args: [2] }]
  );

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.duplicated, 1);
  assert.strictEqual(r.parked, false);

  assert.strictEqual(DECK.length, 1);
  assert.deepStrictEqual(idsOf(DECK[0]).sort(), ["delta", "fallbackOnly", "kept1"]);
});

test("an unplaced base still deletes the fallback refs", function () {
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [],
    removeFallback: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  const deletedIds = OPS.filter(function (o) {
    return o.op === "delete_obj";
  }).map(function (o) {
    return o.id;
  });
  assert.deepStrictEqual(deletedIds.sort(), ["rmA", "rmB"]);

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.parked, false);
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta"]);
});

test("a failed snapshot duplicate leaves parked false", function () {
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  FAIL_ON_DUP_CALL = 2; // the snapshot duplicate is the second `duplicate` call
  const job = {
    slide: 2,
    from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 50, y: 50, w: 5, h: 5 }],
    strip: [],
    mutate: [],
    snapshotNext: 3,
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.parked, false);
  assert.strictEqual(missReasons.length, 1);
  assert.ok(/snapshot slide/.test(missReasons[0]));

  // The job otherwise completes exactly as a non-preadd job would: no stray
  // parked slide survives, the real original is consumed, the add lands.
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[0]), ["kept1", "rmA", "rmB"]);
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta"]);
});

test("chain of 3: the middle job is both a consumer (basePlaced) and a producer (snapshotNext)", function () {
  // This is the only path that exercises `nBefore + (basePlaced ? 1 : 2)`
  // (remap_keynote.js ~579) with basePlaced === true: job B consumes A's parked
  // base AND parks its own base for C. baseReady threading mirrors run()'s loop
  // (remap_keynote.js ~1106-1116) exactly, including the reuseBy[n].snapshotNext fix.
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta2", 0, 0, 5, 5)]),
    makeSlide([makeItem("delta3", 0, 0, 5, 5)]),
    makeSlide([makeItem("delta4", 0, 0, 5, 5)]),
  ]);
  const jobA = {
    slide: 2,
    from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 50, y: 50, w: 5, h: 5 }],
    strip: [],
    mutate: [],
    snapshotNext: 3,
  };
  const jobB = {
    slide: 3,
    from: 2,
    remove: [],
    add: [{ slide: 3, kind: "shape", kindIndex: 0, x: 60, y: 60, w: 5, h: 5 }],
    strip: [],
    mutate: [],
    snapshotNext: 4,
  };
  const jobC = {
    slide: 4,
    from: 3,
    remove: [],
    add: [{ slide: 4, kind: "shape", kindIndex: 0, x: 70, y: 70, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const reuseBy = { 2: jobA, 3: jobB, 4: jobC };
  const baseReady = {};
  const missReasons = [];

  const rA = m.applyReuse(DOC, KEYNOTE, jobA, missReasons, baseReady[2] === true);
  assert.strictEqual(rA.ok, true);
  assert.strictEqual(DECK.length, 5); // producer's own +1 dup, then +1 park (nBefore(4) + 2)
  if (rA.parked) baseReady[reuseBy[2].snapshotNext] = true;

  const rB = m.applyReuse(DOC, KEYNOTE, jobB, missReasons, baseReady[3] === true);
  assert.strictEqual(rB.ok, true);
  assert.strictEqual(DECK.length, 5); // basePlaced: no own dup, +1 park (nBefore(5) + 1)
  if (rB.parked) baseReady[reuseBy[3].snapshotNext] = true;

  const rC = m.applyReuse(DOC, KEYNOTE, jobC, missReasons, baseReady[4] === true);
  assert.strictEqual(rC.ok, true);
  assert.strictEqual(DECK.length, 4); // basePlaced, no snapshotNext: back to the base rhythm

  assert.strictEqual(rA.duplicated, 1);
  assert.strictEqual(rB.duplicated, 1);
  assert.strictEqual(rC.duplicated, 1);
  assert.strictEqual(rA.parked, true);
  assert.strictEqual(rB.parked, true); // the basePlaced-AND-snapshotNext path
  assert.strictEqual(rC.parked, false);
  assert.deepStrictEqual(missReasons, []);

  assert.deepStrictEqual(idsOf(DECK[0]), ["kept1", "rmA", "rmB"]); // donor untouched
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta2"]);
  assert.deepStrictEqual(idsOf(DECK[2]), ["kept1", "delta3"]);
  assert.deepStrictEqual(idsOf(DECK[3]), ["kept1", "delta4"]);
});

test("plain job (no basePreAdd/snapshotNext/removeFallback) issues the pre-change op sequence byte-for-byte", function () {
  // Dimension-4 pin: a job untouched by the pre-add optimisation must produce the
  // EXACT op sequence the code issued before basePreAdd/snapshotNext/removeFallback
  // existed — duplicate, deletes, paste, delete-orig — with no extra duplicate.
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 50, y: 50, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.deepStrictEqual(opTypes(), ["duplicate", "delete_obj", "delete_obj", "paste", "delete_slide"]);
  assert.deepStrictEqual(OPS[0].args, [1, 2]); // duplicate(from, to)
  assert.deepStrictEqual(OPS[OPS.length - 1].args, [3]); // delete slide (to+1), no snapshot in between

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.duplicated, 1);
  assert.strictEqual(r.parked, false);
  assert.strictEqual(missReasons.length, 0);

  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[0]), ["kept1", "rmA", "rmB"]);
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta"]);
});

console.log("\n" + passed + " passed");
