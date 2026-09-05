// Unit tests for the reuse-donor geometry matcher (remap_keynote.js, Part B2).
// Pure JS — no Keynote, no Apple Events. Run with:
//
//     node tests/reuse_geometry.test.js
//
// A reuse-donor copy's collection order DRIFTS from wall order (the donor was
// built by a select-all paste that appends, then deletes), so a removal can no
// longer be addressed by the wall kindIndex. Python attaches each removed donor
// object's OUTPUT rect to its remove ref (map_remap.py, Part B1) and `deleteRefs`
// resolves it by geometry here. These tests mirror that:
//   * getItemByGeom picks the right object out of a drifted/append-ordered set;
//   * the tie rule deletes-all only when the live match count equals the number
//     of same-geometry refs, and flags (never guesses) a split;
//   * geometry-less refs still use the index path unchanged.

const assert = require("assert");
const m = require("../src/obed_edom/remap_keynote.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

// A drawable exposing JXA-style position()/width()/height() accessors.
function elem(x, y, w, h, id) {
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
  };
}

// A slide is a bag of typed collections; each `slide.<name>()` returns the live
// array, exactly as JXA exposes `slide.groups()` etc. The array is indexable and
// has .length, which is all countOf/itemAt/collectionNamed need.
function slideOf(kind, arr) {
  const name =
    kind === "group"
      ? "groups"
      : kind === "image"
      ? "images"
      : kind === "shape"
      ? "shapes"
      : kind === "text"
      ? "textItems"
      : kind + "s";
  const slide = {};
  slide[name] = function () {
    return arr;
  };
  return slide;
}

// A Keynote stub whose delete() removes the object from the backing array (so a
// deletion count and the surviving collection are both observable).
function keynoteFor(arr) {
  return {
    delete: function (obj) {
      const i = arr.indexOf(obj);
      if (i >= 0) arr.splice(i, 1);
    },
  };
}

function rect(x, y, w, h) {
  return { x: x, y: y, w: w, h: h };
}

test("getItemByGeom picks the right object from a drifted/append-ordered set", function () {
  // Wall order would put the target first; the donor copy appended it LAST.
  const arr = [
    elem(3563, 255, 11, 11, "pinA"),
    elem(3576, 255, 11, 11, "pinB"),
    elem(100, 100, 50, 50, "target"), // drifted to the end by the paste
  ];
  const slide = slideOf("group", arr);
  const obj = m.getItemByGeom(slide, "group", rect(100, 100, 50, 50), 4);
  assert.strictEqual(obj.id, "target");
});

test("getItemByGeom tolerates spec +/-<=2px landing but excludes the next grid cell", function () {
  const arr = [
    elem(102, 98, 51, 49, "landed"), // 2px off in every axis — a real setPos landing
    elem(140, 100, 50, 50, "neighbour"), // one grid cell over
  ];
  const slide = slideOf("group", arr);
  assert.strictEqual(m.getItemByGeom(slide, "group", rect(100, 100, 50, 50), 4).id, "landed");
  // A far object is never matched.
  assert.strictEqual(m.getItemByGeom(slide, "group", rect(900, 900, 50, 50), 4), null);
});

test("deleteRefs (geom): a unique-rect ref deletes exactly its object under drift", function () {
  const arr = [
    elem(3563, 255, 11, 11, "pin"),
    elem(100, 100, 50, 50, "gone"),
    elem(200, 200, 60, 60, "kept"),
  ];
  const slide = slideOf("group", arr);
  const flags = [];
  const n = m.deleteRefs(keynoteFor(arr), slide, [{ kind: "group", x: 100, y: 100, w: 50, h: 50 }], flags);
  assert.strictEqual(n, 1);
  assert.deepStrictEqual(arr.map((e) => e.id).sort(), ["kept", "pin"]);
  assert.strictEqual(flags.length, 0);
});

test("deleteRefs tie rule: two same-geom refs + two matches => delete both", function () {
  // The D2 co-located pair: both twins are removed, both present on the copy.
  const arr = [
    elem(100, 100, 50, 50, "twinA"),
    elem(3563, 255, 11, 11, "pin"),
    elem(100, 100, 50, 50, "twinB"),
  ];
  const slide = slideOf("group", arr);
  const flags = [];
  const refs = [
    { kind: "group", x: 100, y: 100, w: 50, h: 50 },
    { kind: "group", x: 100, y: 100, w: 50, h: 50 },
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, flags);
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(
    arr.map((e) => e.id),
    ["pin"]
  );
  assert.strictEqual(flags.length, 0);
});

test("deleteRefs tie rule: split (2 matches, 1 ref) is flagged and deletes NOTHING", function () {
  // One twin persists, one is removed — the matcher cannot tell them apart, so it
  // must fail loud and keep BOTH rather than guess a survivor away.
  const arr = [
    elem(100, 100, 50, 50, "removeMe"),
    elem(100, 100, 50, 50, "keepMe"),
  ];
  const slide = slideOf("group", arr);
  const flags = [];
  const n = m.deleteRefs(keynoteFor(arr), slide, [{ kind: "group", x: 100, y: 100, w: 50, h: 50 }], flags);
  assert.strictEqual(n, 0);
  assert.strictEqual(arr.length, 2); // nothing deleted
  assert.strictEqual(flags.length, 1);
  assert.ok(/geom split/.test(flags[0]));
});

test("deleteRefs tie rule: fewer matches than refs is also flagged, no delete", function () {
  const arr = [elem(100, 100, 50, 50, "only")];
  const slide = slideOf("group", arr);
  const flags = [];
  const refs = [
    { kind: "group", x: 100, y: 100, w: 50, h: 50 },
    { kind: "group", x: 100, y: 100, w: 50, h: 50 },
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, flags);
  assert.strictEqual(n, 0);
  assert.strictEqual(arr.length, 1);
  assert.strictEqual(flags.length, 1);
});

test("deleteRefs: geometry-less refs still take the wall-index path unchanged", function () {
  // No x/y/w/h => today's getItem(kindIndex) behaviour; the highest index goes
  // first so lower live indices stay valid.
  const arr = [
    elem(0, 0, 10, 10, "g0"),
    elem(0, 0, 10, 10, "g1"),
    elem(0, 0, 10, 10, "g2"),
  ];
  const slide = slideOf("group", arr);
  const refs = [
    { kind: "group", kindIndex: 0 },
    { kind: "group", kindIndex: 2 },
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, []);
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(
    arr.map((e) => e.id),
    ["g1"]
  );
});

test("deleteRefs: geom and index refs coexist in one call", function () {
  const arr = [
    elem(0, 0, 10, 10, "idx0"), // deleted by index ref
    elem(500, 500, 30, 30, "geom"), // deleted by geometry ref
    elem(0, 0, 10, 10, "idx1"), // kept
  ];
  const slide = slideOf("group", arr);
  const refs = [
    { kind: "group", kindIndex: 0 },
    { kind: "group", x: 500, y: 500, w: 30, h: 30 },
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, []);
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(
    arr.map((e) => e.id),
    ["idx1"]
  );
});

test("deleteRefs (geom): each object's geometry is read at most once per call — no per-group rescans", function () {
  // The whole point of the batch fix. Many distinct-rect groups of ONE kind must
  // NOT trigger one full-collection scan PER group: a single O(N) snapshot backs
  // every group's filter. Before the fix, itemsByGeom re-scanned all N objects for
  // each of the G groups, so every object's position() was read G (=N here) times.
  // Now it is read exactly once. The snapshot reads position AND size once each, so
  // count position()/width()/height() reads and assert each is <=1 per object.
  const reads = {};
  function counted(x, y, w, h, id) {
    const e = elem(x, y, w, h, id);
    reads[id] = { pos: 0, w: 0, h: 0 };
    e.position = function () {
      reads[id].pos += 1;
      return [this._x, this._y];
    };
    e.width = function () {
      reads[id].w += 1;
      return this._w;
    };
    e.height = function () {
      reads[id].h += 1;
      return this._h;
    };
    return e;
  }
  const arr = [];
  const refs = [];
  const N = 40;
  for (let i = 0; i < N; i++) {
    arr.push(counted(i * 100, 0, 50, 50, "g" + i)); // distinct rect per object
    refs.push({ kind: "group", x: i * 100, y: 0, w: 50, h: 50 });
  }
  const slide = slideOf("group", arr);
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, []);
  assert.strictEqual(n, N); // all N unique-rect groups deleted their object
  assert.strictEqual(arr.length, 0);
  Object.keys(reads).forEach(function (id) {
    assert.ok(reads[id].pos <= 1, id + " position() read " + reads[id].pos + " times (expected <=1)");
    assert.ok(reads[id].w <= 1, id + " width() read " + reads[id].w + " times (expected <=1)");
    assert.ok(reads[id].h <= 1, id + " height() read " + reads[id].h + " times (expected <=1)");
  });
});

test("deleteRefs (geom): batched matcher honours the tie rule across many groups from one snapshot", function () {
  // A mix in a single call: unique-rect groups delete; a co-located pair (2 refs, 2
  // matches) deletes both; a split (1 ref, 2 matches) flags and deletes nothing —
  // all resolved off ONE snapshot, proving the batch path preserves the semantics.
  const arr = [
    elem(0, 0, 20, 20, "uA"),
    elem(300, 0, 20, 20, "pairA"),
    elem(300, 0, 20, 20, "pairB"),
    elem(600, 0, 20, 20, "splitKeep"),
    elem(600, 0, 20, 20, "splitGone"),
    elem(900, 0, 20, 20, "uB"),
  ];
  const slide = slideOf("group", arr);
  const flags = [];
  const refs = [
    { kind: "group", x: 0, y: 0, w: 20, h: 20 }, // unique -> delete uA
    { kind: "group", x: 300, y: 0, w: 20, h: 20 }, // pair (2 refs)
    { kind: "group", x: 300, y: 0, w: 20, h: 20 },
    { kind: "group", x: 600, y: 0, w: 20, h: 20 }, // split: 1 ref vs 2 matches
    { kind: "group", x: 900, y: 0, w: 20, h: 20 }, // unique -> delete uB
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, flags);
  assert.strictEqual(n, 4); // uA + pairA + pairB + uB
  assert.deepStrictEqual(arr.map((e) => e.id).sort(), ["splitGone", "splitKeep"]);
  assert.strictEqual(flags.length, 1);
  assert.ok(/geom split/.test(flags[0]));
});

test("deleteRefs (geom): a deleted snapshot entry never matches a later distinct-rect group within tol", function () {
  // Change 1 guard. Group A and group B have DISTINCT rounded rects (x 100 vs 104)
  // but sit within tol=4 of a shared object S (|100-104|=4). Group A deletes S. B's
  // own object T (x=108) matches B but NOT A (|108-100|=8>4). Without the guard the
  // snapshot still holds the deleted S, so B would see {S,T} = 2 matches vs 1 ref
  // and wrongly FLAG a split; with the guard S is skipped, B sees {T} = 1 == 1 and
  // deletes T cleanly.
  const S = elem(100, 100, 50, 50, "shared");
  const T = elem(108, 100, 50, 50, "bOwn");
  const arr = [S, T];
  const slide = slideOf("group", arr);
  const flags = [];
  const refs = [
    { kind: "group", x: 100, y: 100, w: 50, h: 50 }, // group A -> deletes S
    { kind: "group", x: 104, y: 100, w: 50, h: 50 }, // group B (distinct round) -> deletes T
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, flags);
  assert.strictEqual(n, 2); // S by A, T by B — no false split
  assert.strictEqual(arr.length, 0);
  assert.strictEqual(flags.length, 0);
});

// --- kind-aware matching: text/line never compare on height ---------------------
// A Keynote text box is AUTOSIZE: its live height is the laid-out height, never
// the planner's `h`, and its live width can differ when the planner wrote none.
// x/y (and w, when the ref carries one) stay load-bearing; h never is.

test("deleteRefs (geom): a text ref matches even when the live autosized height drifts >4px", function () {
  const arr = [elem(100, 100, 50, 92, "grown")]; // live height 92 vs the ref's planned h=30
  const slide = slideOf("text", arr);
  const flags = [];
  const n = m.deleteRefs(keynoteFor(arr), slide, [{ kind: "text", x: 100, y: 100, w: 50, h: 30 }], flags);
  assert.strictEqual(n, 1);
  assert.strictEqual(arr.length, 0);
  assert.strictEqual(flags.length, 0);
});

test("deleteRefs (geom): two co-located text refs with different planned h both delete", function () {
  // The grouping key must ignore h for text/line, same as matchesRect — otherwise
  // these land in two separate 1-ref groups, each seeing both live objects as a
  // "2 matches vs 1 ref" split, and neither one deletes.
  const arr = [elem(100, 100, 50, 60, "a"), elem(100, 100, 50, 90, "b")];
  const slide = slideOf("text", arr);
  const flags = [];
  const refs = [
    { kind: "text", x: 100, y: 100, w: 50, h: 30 },
    { kind: "text", x: 100, y: 100, w: 50, h: 954 },
  ];
  const n = m.deleteRefs(keynoteFor(arr), slide, refs, flags);
  assert.strictEqual(n, 2);
  assert.strictEqual(arr.length, 0);
  assert.strictEqual(flags.length, 0);
});

test("deleteRefs (geom): two same-position texts differing only in width still trip the count-equals-refs guard", function () {
  // Width IS compared for text (unlike height), but it is only one more tolerance
  // band, not a disambiguator: two live boxes whose widths both land within tol of
  // the ref's w are still an unresolved split, and the guard must still refuse.
  const arr = [elem(100, 100, 50, 30, "narrow"), elem(100, 100, 54, 30, "wide")];
  const slide = slideOf("text", arr);
  const flags = [];
  const n = m.deleteRefs(keynoteFor(arr), slide, [{ kind: "text", x: 100, y: 100, w: 52, h: 30 }], flags);
  assert.strictEqual(n, 0);
  assert.strictEqual(arr.length, 2);
  assert.strictEqual(flags.length, 1);
  assert.ok(/geom split/.test(flags[0]));
});

// --- V: fail-loud remove verification ------------------------------------------
// deleteRefs tallies the per-kind deleted count; removeShortfallOf turns that plus
// the expected `remove` refs into a structured, uncapped per-kind shortfall. The
// known bug (a group remove that silently deleted nothing) must surface here.

test("deleteRefs populates the per-kind tally for removed objects", function () {
  const arr = [elem(0, 0, 10, 10, "g0"), elem(0, 0, 10, 10, "g1")];
  const slide = slideOf("group", arr);
  const tally = {};
  const n = m.deleteRefs(
    keynoteFor(arr),
    slide,
    [{ kind: "group", kindIndex: 0 }, { kind: "group", kindIndex: 1 }],
    [],
    tally
  );
  assert.strictEqual(n, 2);
  assert.strictEqual(tally.group, 2);
});

test("deleteRefs tally: a geom split deletes nothing and tallies nothing", function () {
  const arr = [elem(100, 100, 50, 50, "a"), elem(100, 100, 50, 50, "b")];
  const slide = slideOf("group", arr);
  const tally = {};
  const n = m.deleteRefs(keynoteFor(arr), slide, [{ kind: "group", x: 100, y: 100, w: 50, h: 50 }], [], tally);
  assert.strictEqual(n, 0);
  assert.deepStrictEqual(tally, {});
});

test("removeShortfallOf: a group remove that deleted nothing surfaces group shortfall", function () {
  const refs = [
    { kind: "group", kindIndex: 0 },
    { kind: "group", kindIndex: 1 },
    { kind: "image", x: 0, y: 0, w: 10, h: 10 },
  ];
  // The tally is what deleteRefs actually removed: the image only, no groups.
  const short = m.removeShortfallOf(refs, { image: 1 });
  assert.strictEqual(short.group.expected, 2);
  assert.strictEqual(short.group.removed, 0);
  assert.strictEqual(short.group.shortfall, 2); // the bug, now loud
  assert.strictEqual(short.image.shortfall, 0);
});

test("removeShortfallOf: fully-removed refs report zero shortfall", function () {
  const short = m.removeShortfallOf(
    [{ kind: "shape", kindIndex: 0 }, { kind: "shape", kindIndex: 1 }],
    { shape: 2 }
  );
  assert.strictEqual(short.shape.expected, 2);
  assert.strictEqual(short.shape.shortfall, 0);
});

test("removeShortfallOf: empty remove list yields an empty record", function () {
  assert.deepStrictEqual(m.removeShortfallOf([], {}), {});
});

console.log("\n" + passed + " passed");
