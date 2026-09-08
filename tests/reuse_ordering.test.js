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
let FAIL_ON_DELETE_SLIDE = false;
let COPIED_FROM = null;

// -- add-paste verification gate stubs (item 1/2/3 of the applyReuse paste fix) --
//
// PASTEBOARD stays null by default: `$.NSPasteboard` is then undefined,
// `pasteboardChangeCount()` catches the resulting throw and returns null, and the
// gate takes its "unavailable" degrade path — Cmd-V presses exactly as it did
// before this change. That is why the six pre-existing tests above/below need no
// edits: they never opt into PASTEBOARD, so they never leave that degrade path.
//
// Set PASTEBOARD = { count: N } to opt a test into the changeCount gate.
// Set COPY_FAILS_FOR_ATTEMPTS = K to make the fake Cmd-C a no-op (does not bump
// PASTEBOARD.count, does not update COPIED_FROM) for the first K "c" keystrokes,
// then behave normally — simulating a Cmd-C that silently failed to commit.
let PASTEBOARD = null;
let COPY_FAILS_FOR_ATTEMPTS = 0;
let COPY_ATTEMPT_COUNT = 0;

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

// A real Keynote slide always implements every collection accessor (possibly
// empty) — textItems/images/movies/groups/lines read 0, never "unreadable",
// unless a test deliberately overrides one to model a genuine AE failure (see
// the B1/B2 tests below). Only `shapes` carries this harness's live items.
function makeSlide(items) {
  const arr = items.slice();
  return {
    shapes: function () {
      return arr;
    },
    textItems: function () {
      return [];
    },
    images: function () {
      return [];
    },
    movies: function () {
      return [];
    },
    groups: function () {
      return [];
    },
    lines: function () {
      return [];
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
    if (FAIL_ON_DELETE_SLIDE) {
      throw new Error("simulated AppleScript delete-slide failure");
    }
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
          COPY_ATTEMPT_COUNT += 1;
          if (COPY_ATTEMPT_COUNT <= COPY_FAILS_FOR_ATTEMPTS) {
            return; // simulated silent Cmd-C failure: COPIED_FROM/PASTEBOARD untouched
          }
          COPIED_FROM = DOC.currentSlide;
          if (PASTEBOARD) PASTEBOARD.count += 1;
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
  // A live getter, not a plain property: PASTEBOARD is reassigned per test (null by
  // default), so `$.NSPasteboard` must reflect whatever the CURRENT test set it to.
  // Left at the default null, `$.NSPasteboard` is undefined and
  // `pasteboardChangeCount()` catches the resulting throw — the "unavailable"
  // degrade path every pre-existing test below relies on.
  get NSPasteboard() {
    if (!PASTEBOARD) return undefined;
    return { generalPasteboard: { changeCount: PASTEBOARD.count } };
  },
};
// ON_DELAY lets a test observe/react to a specific delay() call by its argument —
// used to pin that `beforeAdd` is captured once outside the retry loop: the
// inter-attempt backoff `delay(0.5 * (attempts - 1))` is the only call site that
// ever passes exactly 0.5, so it marks "attempt 2 is starting" unambiguously.
let ON_DELAY = null;
global.delay = function (s) {
  if (ON_DELAY) ON_DELAY(s);
};

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
    const slideIdx = DECK.indexOf(obj);
    if (slideIdx >= 0) {
      DECK.splice(slideIdx, 1);
      OPS.push({ op: "delete_slide_obj" });
      return;
    }
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
  FAIL_ON_DELETE_SLIDE = false;
  LAST_SCRIPT = null;
  PASTEBOARD = null;
  COPY_FAILS_FOR_ATTEMPTS = 0;
  COPY_ATTEMPT_COUNT = 0;
  ON_DELAY = null;
  delete KEYNOTE.frontmost;
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

// --- W1: verified add-delta paste, conditional delete ---------------------------
//
// `to` = job.slide. After the initial duplicate, `copy` = slides[to-1] (the fresh
// donor clone) and `orig` = slides[to] (the pre-existing slide that carries the
// job's unique add-delta — the payload the Cmd-A/Cmd-C/Cmd-V burst must move onto
// `copy` before `orig` is deleted as "slide to+1"). These tests drive that burst
// through the fake pasteboard/Cmd-C stubs above; none of them touch a real Keynote.

test("a verified paste still issues delete slide (to+1) and reports one attempt", function () {
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
    ]),
    makeSlide([makeItem("payload1", 0, 0, 5, 5), makeItem("payload2", 10, 10, 5, 5)]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [{ kind: "shape", x: 100, y: 100, w: 20, h: 20 }],
    add: [
      { slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 },
      { slide: 2, kind: "shape", kindIndex: 1, x: 2, y: 2, w: 5, h: 5 },
    ],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "paste" || o === "delete_slide"; }),
    ["paste", "delete_slide"]
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.addFailure, null);
  assert.ok(r.addReport);
  assert.strictEqual(r.addReport.ok, true);
  assert.strictEqual(r.addReport.attempts, 1);
  assert.strictEqual(r.applied, 2);
  assert.strictEqual(r.missed, 0);
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[1]).sort(), ["kept1", "payload1", "payload2"]);
});

test("a stale paste with no pasteboard API does NOT delete the original slide", function () {
  // The headline regression test. D6's arm-A bug: Cmd-C silently no-ops (here,
  // for every attempt — COPY_FAILS_FOR_ATTEMPTS exceeds the 3-attempt budget) and
  // there is no pasteboard changeCount API to detect it (PASTEBOARD stays null),
  // so Cmd-V keeps firing and keeps pasting a STALE clipboard left over from a
  // previous job (primed here as a single stray item) instead of this job's real
  // 3-shape add. The measured delta is non-zero (+1) but deficient against the
  // expected 3 — item 1's post-paste verification must refuse the delete.
  resetCtx([
    makeSlide([
      makeItem("kept1", 0, 0, 10, 10),
      makeItem("rmA", 100, 100, 20, 20),
      makeItem("rmB", 200, 100, 20, 20),
    ]),
    makeSlide([
      makeItem("payload1", 0, 0, 1, 1),
      makeItem("payload2", 1, 1, 1, 1),
      makeItem("payload3", 2, 2, 1, 1),
    ]),
  ]);
  COPY_FAILS_FOR_ATTEMPTS = 99;
  COPIED_FROM = makeSlide([makeItem("staleFromPrevJob", 9, 9, 1, 1)]);
  const job = {
    slide: 2,
    from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [
      { slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 1, h: 1 },
      { slide: 2, kind: "shape", kindIndex: 1, x: 2, y: 2, w: 1, h: 1 },
      { slide: 2, kind: "shape", kindIndex: 2, x: 3, y: 3, w: 1, h: 1 },
    ],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.ok(opTypes().indexOf("paste") >= 0);
  assert.strictEqual(opTypes().indexOf("delete_slide"), -1);

  assert.strictEqual(r.ok, true); // never flipped false — run() must not route to applyNonReuseSlide
  assert.ok(r.addFailure);
  assert.strictEqual(r.addFailure.slide, 2);
  assert.deepStrictEqual(r.addFailure.shortfall, { shape: 2 }); // expected 3, got 1
  assert.strictEqual(r.applied, 0);
  assert.strictEqual(r.missed, 3);

  // orig — DECK[2], the pre-existing slide holding the real payload — still exists
  // with all three payload objects intact. Nothing was deleted.
  assert.strictEqual(DECK.length, 3);
  assert.deepStrictEqual(idsOf(DECK[2]).sort(), ["payload1", "payload2", "payload3"]);
});

test("a stuck pasteboard withholds Cmd-V entirely, then a clean retry completes the job", function () {
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([makeItem("payload1", 0, 0, 5, 5)]),
  ]);
  PASTEBOARD = { count: 0 };
  COPY_FAILS_FOR_ATTEMPTS = 1; // the FIRST Cmd-C silently no-ops; the second commits
  const job = {
    slide: 2,
    from: 1,
    remove: [],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.deepStrictEqual(opTypes().filter(function (o) { return o === "paste"; }), ["paste"]);
  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "delete_slide"; }),
    ["delete_slide"]
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.addFailure, null);
  assert.strictEqual(r.addReport.attempts, 2);
  assert.strictEqual(r.addReport.gates[0].pasteboard, "stuck");
  assert.strictEqual(r.addReport.gates[0].pastedCmdV, false);
  assert.strictEqual(r.addReport.gates[1].pasteboard, "advanced");
  assert.strictEqual(r.addReport.gates[1].pastedCmdV, true);
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "payload1"]);
});

test("a pasteboard that never advances never presses Cmd-V and leaves the original intact", function () {
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([makeItem("payload1", 0, 0, 5, 5)]),
  ]);
  PASTEBOARD = { count: 0 };
  COPY_FAILS_FOR_ATTEMPTS = 99; // every Cmd-C, all 3 attempts, silently no-ops
  const job = {
    slide: 2,
    from: 1,
    remove: [],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.strictEqual(opTypes().indexOf("paste"), -1);
  assert.strictEqual(opTypes().indexOf("delete_slide"), -1);
  assert.strictEqual(r.ok, true);
  assert.ok(r.addFailure);
  assert.strictEqual(r.addFailure.attempts, 3);
  r.addFailure.gates.forEach(function (g) {
    assert.strictEqual(g.pasteboard, "stuck");
    assert.strictEqual(g.pastedCmdV, false);
  });
  assert.strictEqual(DECK.length, 3);
  assert.deepStrictEqual(idsOf(DECK[2]), ["payload1"]);
});

test("a surplus paste (an object the strip missed) still deletes the original", function () {
  // The false-positive guard: `job.strip` names an index deleteRefs cannot resolve
  // (kindIndex 99, out of bounds), so a stray object rides Cmd-A/Cmd-C/Cmd-V along
  // with the two real add specs. The measured delta (3) exceeds expected (2) —
  // pure surplus, no shortfall — and must NOT block the delete.
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([
      makeItem("payload1", 0, 0, 5, 5),
      makeItem("payload2", 10, 10, 5, 5),
      makeItem("strayNotStripped", 20, 20, 5, 5),
    ]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [],
    add: [
      { slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 },
      { slide: 2, kind: "shape", kindIndex: 1, x: 2, y: 2, w: 5, h: 5 },
    ],
    strip: [{ kind: "shape", kindIndex: 99 }],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "paste" || o === "delete_slide"; }),
    ["paste", "delete_slide"]
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.addFailure, null);
  assert.strictEqual(r.addReport.ok, true);
  assert.deepStrictEqual(r.addReport.surplus, { shape: 1 });
  assert.deepStrictEqual(r.addReport.shortfall, {});
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(
    idsOf(DECK[1]).sort(),
    ["kept1", "payload1", "payload2", "strayNotStripped"]
  );
});

test("a job with no adds is untouched by the paste gate", function () {
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10), makeItem("rmA", 100, 100, 20, 20)]),
    makeSlide([makeItem("delta", 0, 0, 5, 5)]),
  ]);
  const job = {
    slide: 2,
    from: 1,
    remove: [{ kind: "shape", x: 100, y: 100, w: 20, h: 20 }],
    add: [],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.strictEqual(opTypes().indexOf("paste"), -1);
  assert.strictEqual(r.addReport, null);
  assert.strictEqual(r.addFailure, null);
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "delete_slide"; }),
    ["delete_slide"]
  );
});

test("the pre-add chain of 3 still completes with the gate active", function () {
  // Same chain as "chain of 3" above, run through the new verified-paste code path.
  // Every job's paste is clean (no PASTEBOARD/COPY_FAILS opt-in), so every job must
  // still complete in one attempt with no addFailure and no stranded parked slide.
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
    slide: 2, from: 1,
    remove: [
      { kind: "shape", x: 100, y: 100, w: 20, h: 20 },
      { kind: "shape", x: 200, y: 100, w: 20, h: 20 },
    ],
    add: [{ slide: 2, kind: "shape", kindIndex: 0, x: 50, y: 50, w: 5, h: 5 }],
    strip: [], mutate: [], snapshotNext: 3,
  };
  const jobB = {
    slide: 3, from: 2, remove: [],
    add: [{ slide: 3, kind: "shape", kindIndex: 0, x: 60, y: 60, w: 5, h: 5 }],
    strip: [], mutate: [], snapshotNext: 4,
  };
  const jobC = {
    slide: 4, from: 3, remove: [],
    add: [{ slide: 4, kind: "shape", kindIndex: 0, x: 70, y: 70, w: 5, h: 5 }],
    strip: [], mutate: [],
  };
  const reuseBy = { 2: jobA, 3: jobB, 4: jobC };
  const baseReady = {};
  const missReasons = [];

  const rA = m.applyReuse(DOC, KEYNOTE, jobA, missReasons, baseReady[2] === true);
  if (rA.parked) baseReady[reuseBy[2].snapshotNext] = true;
  const rB = m.applyReuse(DOC, KEYNOTE, jobB, missReasons, baseReady[3] === true);
  if (rB.parked) baseReady[reuseBy[3].snapshotNext] = true;
  const rC = m.applyReuse(DOC, KEYNOTE, jobC, missReasons, baseReady[4] === true);

  [rA, rB, rC].forEach(function (r) {
    assert.strictEqual(r.ok, true);
    assert.strictEqual(r.addFailure, null);
    assert.strictEqual(r.addReport.ok, true);
    assert.strictEqual(r.addReport.attempts, 1);
  });
  assert.deepStrictEqual(missReasons, []);
  assert.deepStrictEqual(idsOf(DECK[0]), ["kept1", "rmA", "rmB"]);
  assert.deepStrictEqual(idsOf(DECK[1]), ["kept1", "delta2"]);
  assert.deepStrictEqual(idsOf(DECK[2]), ["kept1", "delta3"]);
  assert.deepStrictEqual(idsOf(DECK[3]), ["kept1", "delta4"]);
});

test("an unverified paste reports zero applied and every add spec missed", function () {
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([
      makeItem("payload1", 0, 0, 5, 5),
      makeItem("payload2", 1, 1, 5, 5),
    ]),
  ]);
  PASTEBOARD = { count: 0 };
  COPY_FAILS_FOR_ATTEMPTS = 99;
  const job = {
    slide: 2,
    from: 1,
    remove: [],
    add: [
      { slide: 2, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 },
      { slide: 2, kind: "shape", kindIndex: 1, x: 2, y: 2, w: 5, h: 5 },
    ],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, false);

  assert.strictEqual(r.applied, 0);
  assert.strictEqual(r.missed, 2);
  assert.ok(r.addFailure);
});

test("a per-kind negative delta from an unreadable-collection glitch must not retry (B1: sum-vs-per-kind)", function () {
  // The retry decision must be per-kind, not a summed total. `images` here models
  // a kind unrelated to this job's add (2 pre-existing images) whose count reads
  // fine three times, then glitches to 0 on exactly the post-paste (afterAdd)
  // read — a transient Apple Event failure, not a real removal. The real add
  // target (shape) landed cleanly (+1 = expected). Summing (1 + -2 = -1 <= 0)
  // would wrongly signal "nothing landed, retry" and fire a second Cmd-V,
  // doubling the real payload. Per-kind, shape's own delta is nonzero: no retry.
  let imagesCallCount = 0;
  // beforeCounts, afterCounts, beforeAdd, afterAdd(glitches) — 4, not 5: the
  // post-paste settle poll (nit 1) now checks only the expected kinds' own
  // columns directly and no longer calls collectionCounts (hence no `images` read).
  const IMAGES_FAIL_ON_CALL = 4;
  const copySlide = makeSlide([makeItem("kept1", 0, 0, 10, 10)]);
  copySlide.images = function () {
    imagesCallCount += 1;
    if (imagesCallCount === IMAGES_FAIL_ON_CALL) return [];
    return [{}, {}];
  };
  resetCtx([copySlide, makeSlide([makeItem("payload1", 0, 0, 5, 5)])]);
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.deepStrictEqual(opTypes().filter(function (o) { return o === "paste"; }), ["paste"]);
  assert.strictEqual(opTypes().indexOf("delete_slide"), -1);
  assert.strictEqual(r.ok, true);
  assert.ok(r.addReport);
  assert.strictEqual(r.addReport.attempts, 1);
  assert.deepStrictEqual(r.addReport.pasted, { text: 0, image: -2, shape: 1, movie: 0, group: 0, line: 0 });
  assert.deepStrictEqual(r.addReport.shortfall, { image: 2 });
  assert.ok(r.addFailure);
  assert.strictEqual(r.addFailure.attempts, 1);
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[0]).sort(), ["kept1", "payload1"]); // exactly one paste, not doubled
});

test("a wholly-unreadable target collection blocks the gate — halts, does not delete (B2, corrected)", function () {
  // `shapes` on the destination throws on BOTH access forms (collectionNamed's
  // contract for "unmeasured"), simulating a wholesale-unreadable copy. `shape`
  // is the very kind this job added, so the paste against it can never be
  // verified either way — unresolved, not a pass: `ok` blocks and the delete is
  // skipped. (An earlier version of this test asserted the opposite — that an
  // unmeasured add-kind always proceeds — which is exactly the P3 data-loss
  // path pinned below: a misread baseline must never look like a clean pass.)
  const copySlide = makeSlide([makeItem("kept1", 0, 0, 10, 10)]);
  Object.defineProperty(copySlide, "shapes", {
    get: function () {
      throw new Error("AE: element not readable");
    },
  });
  resetCtx([copySlide, makeSlide([makeItem("payload1", 0, 0, 5, 5)])]);
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.strictEqual(r.ok, true);
  assert.ok(r.addFailure);
  assert.ok(r.addReport);
  assert.strictEqual(r.addReport.ok, false);
  assert.strictEqual(r.addReport.unmeasuredNamed, true);
  assert.ok(r.addReport.unmeasured.indexOf("shape") >= 0);
  assert.strictEqual(r.addReport.attempts, 1); // non-retryable, not the usual 3
  assert.deepStrictEqual(r.addReport.shortfall, {});
  assert.strictEqual(r.applied, 0);
  assert.strictEqual(r.missed, 1);
  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "paste" || o === "delete_slide"; }),
    ["paste"]
  );
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[1]), ["payload1"]); // orig (the payload) survives intact
  // nit 5: the remove-side -1 (same permanently-throwing `shapes`, read before any
  // add processing) was previously collected into missReasons but never asserted.
  assert.ok(missReasons.indexOf("slide 1 shape count failed, drop not measured") >= 0);
});

test("P3: a single transient failure on the beforeAdd read must not read as a false 0 and delete the payload", function () {
  // A real Keynote slide's element-specifier property read never throws (it is
  // local, no Apple Event) — the actual AE failure lands inside the count read
  // itself. Modeled here as a `shapes()` call that throws on exactly the ONE
  // occasion that is the `beforeAdd` snapshot (call 3: beforeCounts, afterCounts,
  // beforeAdd), while every other read — including afterAdd — succeeds normally.
  // `copy` already holds 3 real shapes unrelated to this job. Cmd-C is made to
  // silently no-op, so the paste fails entirely: nothing lands on `copy`, and
  // afterAdd correctly reads the true 3. Pre-fix, the misread baseline landed as
  // a false 0 (countOf's degrade), so 3 - 0 = 3 >= expected(1) read as a pure
  // surplus — ok, no shortfall — and the delete fired with nothing pasted.
  // Post-fix, the misread baseline is -1 ("unmeasured"), `shape` is named in
  // `expected`, so `ok` blocks and the halt is non-retryable.
  let shapesCallCount = 0;
  const BEFORE_ADD_CALL = 3;
  const preExisting = [
    makeItem("preA", 0, 0, 5, 5),
    makeItem("preB", 1, 1, 5, 5),
    makeItem("preC", 2, 2, 5, 5),
  ];
  const copySlide = makeSlide(preExisting);
  copySlide.shapes = function () {
    shapesCallCount += 1;
    if (shapesCallCount === BEFORE_ADD_CALL) {
      return {
        get length() {
          throw new Error("AE: transient failure");
        },
      };
    }
    return preExisting;
  };
  resetCtx([copySlide, makeSlide([makeItem("payload1", 0, 0, 5, 5)])]);
  COPY_FAILS_FOR_ATTEMPTS = 99; // Cmd-C always silently no-ops: the paste fails entirely
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.strictEqual(r.ok, true);
  assert.ok(r.addFailure);
  assert.ok(r.addReport);
  assert.strictEqual(r.addReport.ok, false);
  assert.strictEqual(r.addReport.unmeasuredNamed, true);
  assert.ok(r.addReport.unmeasured.indexOf("shape") >= 0);
  assert.strictEqual(r.addReport.attempts, 1); // not retried
  assert.strictEqual(opTypes().indexOf("paste"), -1); // Cmd-C never committed: nothing landed
  assert.strictEqual(opTypes().indexOf("delete_slide"), -1);
  assert.strictEqual(DECK.length, 2);
  assert.deepStrictEqual(idsOf(DECK[1]), ["payload1"]); // payload slide preserved
});

test("no slide dies when the AppleScript delete throws while addFailure is set", function () {
  // Guards against hoisting the `runAppleScript("delete slide"...)` catch's
  // fallback `deleteObj(Keynote, leftover)` out of the `if (!addFailure)` guard.
  // FAIL_ON_DELETE_SLIDE + the slide-aware KEYNOTE.delete stub make that fallback
  // observable (delete_slide_obj) if it ever fires; a prior mutation that hoisted
  // it survived all tests because the stub could not see a slide-level delete.
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([makeItem("payload1", 0, 0, 5, 5)]),
  ]);
  PASTEBOARD = { count: 0 };
  COPY_FAILS_FOR_ATTEMPTS = 99; // pasteboard never advances: stuck every attempt, addFailure
  FAIL_ON_DELETE_SLIDE = true;
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.ok(r.addFailure);
  assert.strictEqual(opTypes().indexOf("paste"), -1);
  assert.strictEqual(opTypes().indexOf("delete_slide"), -1);
  assert.strictEqual(opTypes().indexOf("delete_slide_obj"), -1);
  assert.strictEqual(DECK.length, 2);
});

test("beforeAdd is captured once outside the retry loop, not recomputed per attempt", function () {
  // Attempt 1 is withheld (stuck pasteboard); between attempts 1 and 2, an
  // out-of-band drift (unrelated to this job) adds one shape directly to the
  // destination's live array — modeling something like a Keynote-side change
  // landing between attempts. Attempt 2 then pastes for real. If `beforeAdd`
  // were (re)captured inside the loop, attempt 2's baseline would already
  // include the drift, and the drift + the real paste would net out to exactly
  // `expected`, hiding the drift as if it were never there. Captured once
  // (correct), the drift shows up as a surplus of 1 on top of the real add.
  const copySlide = makeSlide([makeItem("kept1", 0, 0, 10, 10)]);
  resetCtx([copySlide, makeSlide([makeItem("payload1", 0, 0, 5, 5)])]);
  PASTEBOARD = { count: 0 };
  COPY_FAILS_FOR_ATTEMPTS = 1; // first Cmd-C silently no-ops; second commits
  let drifted = false;
  ON_DELAY = function (s) {
    if (s === 0.5 && !drifted) {
      drifted = true;
      copySlide._arr.push(makeItem("driftedExtra", 5, 5, 5, 5));
    }
  };
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.addFailure, null);
  assert.strictEqual(r.addReport.attempts, 2);
  assert.strictEqual(r.addReport.pasted.shape, 2); // drift(1) + real paste(1), against the ORIGINAL baseline
  assert.deepStrictEqual(r.addReport.surplus, { shape: 1 });
  assert.deepStrictEqual(r.addReport.shortfall, {});
  assert.deepStrictEqual(
    opTypes().filter(function (o) { return o === "paste" || o === "delete_slide"; }),
    ["paste", "delete_slide"]
  );
  assert.strictEqual(DECK.length, 1);
  assert.deepStrictEqual(idsOf(DECK[0]).sort(), ["driftedExtra", "kept1", "payload1"]);
});

test("Keynote.frontmost gate records both a true read and a timed-out false read", function () {
  // Every other test leaves `KEYNOTE.frontmost` absent, so `waitUntil` takes the
  // throw->null path on every call and the gate is never actually exercised —
  // deleting either frontmost check left all other tests green. Wire it here to
  // pin real true/false gate records without changing production behaviour.
  resetCtx([
    makeSlide([makeItem("kept1", 0, 0, 10, 10)]),
    makeSlide([makeItem("payload1", 0, 0, 5, 5)]),
  ]);
  KEYNOTE.frontmost = function () {
    return DOC.currentSlide === DECK[1]; // true only while `orig` is current (the "at A" check)
  };
  const job = {
    slide: 1,
    from: 1,
    remove: [],
    add: [{ slide: 1, kind: "shape", kindIndex: 0, x: 1, y: 1, w: 5, h: 5 }],
    strip: [],
    mutate: [],
  };
  const missReasons = [];
  const r = m.applyReuse(DOC, KEYNOTE, job, missReasons, true);

  assert.strictEqual(r.addReport.gates[0].frontmostAtA, true);
  assert.strictEqual(r.addReport.gates[0].frontmostAtV, false);
});

console.log("\n" + passed + " passed");
