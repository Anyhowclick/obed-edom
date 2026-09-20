const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { movieObjectsAt, withoutRevealed } = require(path.join(out, "overlays.js"));

function pin(id) {
  return { id, kind: "pin", name: id, lat: 0, lon: 0 };
}

function revealedLandmark(id) {
  return { id, kind: "landmark", name: id, lat: 0, lon: 0, reveal: { duration: 2 } };
}

test("withoutRevealed drops landmarks with a reveal, keeps everything else", () => {
  const list = [pin("a"), revealedLandmark("b"), { id: "c", kind: "landmark", name: "c", lat: 0, lon: 0 }];
  assert.deepEqual(withoutRevealed(list).map((c) => c.id), ["a", "c"]);
});

test("movieObjectsAt fade omits a revealed destination landmark at t=0", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 0, "fade");
  assert.ok(!objects.some((o) => o.id === "to-to-2"));
});

test("movieObjectsAt fade omits a revealed destination landmark at t=0.5", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 0.5, "fade");
  assert.ok(!objects.some((o) => o.id === "to-to-2"));
  assert.ok(objects.some((o) => o.id === "to-to-1"));
});

test("movieObjectsAt fade omits a revealed destination landmark at t=1", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 1, "fade");
  assert.ok(!objects.some((o) => o.id === "to-to-2"));
  assert.ok(objects.some((o) => o.id === "to-to-1"));
});

test("movieObjectsAt hold at t=1 omits a revealed destination landmark", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 1, "hold");
  assert.deepEqual(objects.map((o) => o.id), ["to-1"]);
});

test("movieObjectsAt keeps a source-side revealed landmark", () => {
  const from = [pin("from-1"), revealedLandmark("from-2")];
  const to = [pin("to-1")];
  const objects = movieObjectsAt(from, to, 0, "fade");
  assert.ok(objects.some((o) => o.id === "from-2"));
});

test("movieObjectsAt keeps a revealed destination landmark when the destination will not paint it (A to B movie, B to C movie)", () => {
  // Three-slide chain A -> B -> C, both movie hops. B carries an outgoing movie link, so
  // maps_keynote.build_slide_items never places B's revealed landmark on B's own slide
  // (bg_movie is not None). The A->B hop must therefore keep it, or it never appears at all.
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 1, "fade", false);
  assert.ok(objects.some((o) => o.id === "to-to-2"));
});

test("movieObjectsAt drops a revealed destination landmark when the destination will paint it (A to B movie, B to C cut)", () => {
  // Same chain, but B's outgoing hop is a cut: B places the landmark itself via its paint-on
  // reveal movie, so the incoming A->B hop must not also carry it (no double paint-on/pop-in).
  const from = [pin("from-1")];
  const to = [pin("to-1"), revealedLandmark("to-2")];
  const objects = movieObjectsAt(from, to, 1, "fade", true);
  assert.ok(!objects.some((o) => o.id === "to-to-2"));
});

test("movieObjectsAt opacity ramps are unaffected for plain objects", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  const atStart = movieObjectsAt(from, to, 0.25, "fade");
  const fromItem = atStart.find((o) => o.id === "from-1");
  assert.equal(fromItem.opacity, 0.5);
  const atMid = movieObjectsAt(from, to, 0.75, "fade");
  const toItem = atMid.find((o) => o.id === "to-to-1");
  assert.equal(toItem.opacity, 0.5);
});

for (const transition of ["fade", "hold"]) {
  test(`movieObjectsAt (${transition}) strips labels from every hop object`, () => {
    const from = [{ ...pin("from-1"), showLabel: true }];
    const to = [{ ...pin("to-1"), showLabel: true }];
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      for (const item of movieObjectsAt(from, to, t, transition)) {
        assert.equal(item.showLabel, false);
      }
    }
  });
}

test("movieObjectsAt fade marker opacity is unchanged from before by stripping labels", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  for (const t of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
    const objects = movieObjectsAt(from, to, t, "fade");
    const fromItem = objects.find((o) => o.id === "from-1");
    const toItem = objects.find((o) => o.id === "to-to-1");
    assert.equal(fromItem.opacity, Math.max(0, 1 - 2 * t));
    assert.equal(toItem.opacity, Math.max(0, 2 * t - 1));
  }
});

test("movieObjectsAt hold does not introduce destination objects until t=1", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  const mid = movieObjectsAt(from, to, 0.9, "hold");
  assert.deepEqual(mid.map((o) => o.id), ["from-1"]);
  assert.equal(mid[0].showLabel, false);
  const atEnd = movieObjectsAt(from, to, 1, "hold");
  assert.deepEqual(atEnd.map((o) => o.id), ["to-1"]);
  assert.equal(atEnd[0].opacity, 1);
  assert.equal(atEnd[0].showLabel, false);
});

test("movieObjectsAt hold marker opacity is unchanged from before by stripping labels", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  for (const t of [0, 0.1, 0.5, 0.9]) {
    const objects = movieObjectsAt(from, to, t, "hold");
    const fromItem = objects.find((o) => o.id === "from-1");
    assert.equal(fromItem.opacity, 1);
    assert.ok(!objects.some((o) => o.id === "to-1" || o.id === "to-to-1"));
  }
  const atEnd = movieObjectsAt(from, to, 1, "hold");
  assert.deepEqual(atEnd.map((o) => o.id), ["to-1"]);
  assert.equal(atEnd[0].opacity, 1);
});
