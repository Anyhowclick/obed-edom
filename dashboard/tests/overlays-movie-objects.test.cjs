const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/overlays.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { movieObjectsAt, withoutRevealed, MOVIE_LABEL_FADE } = require(path.join(out, "overlays.js"));

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

function labelOpacityOf(objects, id) {
  const item = objects.find((o) => o.id === id);
  return item ? item.labelOpacity : undefined;
}

for (const transition of ["fade", "hold"]) {
  test(`movieObjectsAt (${transition}) label opacity fades source out over [0, MOVIE_LABEL_FADE]`, () => {
    const from = [pin("from-1")];
    const to = [pin("to-1")];
    assert.equal(labelOpacityOf(movieObjectsAt(from, to, 0, transition), "from-1"), 1);
    assert.ok(Math.abs(labelOpacityOf(movieObjectsAt(from, to, 0.1, transition), "from-1") - (1 - 0.1 / MOVIE_LABEL_FADE)) < 1e-9);
    assert.equal(labelOpacityOf(movieObjectsAt(from, to, 0.5, transition), "from-1"), 0);
    assert.equal(labelOpacityOf(movieObjectsAt(from, to, 0.9, transition), "from-1"), 0);
  });

  test(`movieObjectsAt (${transition}) label opacity fades destination in over [1 - MOVIE_LABEL_FADE, 1]`, () => {
    const from = [pin("from-1")];
    const to = [pin("to-1")];
    const belowWindow = transition === "hold" ? undefined : 0;
    assert.equal(labelOpacityOf(movieObjectsAt(from, to, 0, transition), "to-to-1"), belowWindow);
    assert.equal(labelOpacityOf(movieObjectsAt(from, to, 0.5, transition), "to-to-1"), belowWindow);
    assert.ok(Math.abs(labelOpacityOf(movieObjectsAt(from, to, 0.9, transition), "to-to-1") - (0.9 - (1 - MOVIE_LABEL_FADE)) / MOVIE_LABEL_FADE) < 1e-9);
    const atEnd = movieObjectsAt(from, to, 1, transition);
    const endId = transition === "hold" ? "to-1" : "to-to-1";
    assert.ok(Math.abs(labelOpacityOf(atEnd, endId) - 1) < 1e-9);
  });
}

test("movieObjectsAt fade marker opacity is unchanged from before by the labelOpacity addition", () => {
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

test("movieObjectsAt hold at t=0.9 keeps the destination marker hidden while its label fades in", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  const objects = movieObjectsAt(from, to, 0.9, "hold");
  const destItem = objects.find((o) => o.id === "to-to-1");
  assert.equal(destItem.opacity, 0);
  assert.ok(destItem.labelOpacity > 0);
});

test("movieObjectsAt hold at t=1 shows the destination marker at full opacity", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  const objects = movieObjectsAt(from, to, 1, "hold");
  const destItem = objects.find((o) => o.id === "to-1");
  assert.equal(destItem.opacity, 1);
});

test("movieObjectsAt hold marker opacity is unchanged from before by the labelOpacity addition", () => {
  const from = [pin("from-1")];
  const to = [pin("to-1")];
  for (const t of [0, 0.1, 0.5, 0.9]) {
    const objects = movieObjectsAt(from, to, t, "hold");
    const fromItem = objects.find((o) => o.id === "from-1");
    assert.equal(fromItem.opacity, 1);
    assert.ok(!objects.some((o) => o.id === "to-1"));
  }
  const atEnd = movieObjectsAt(from, to, 1, "hold");
  assert.deepEqual(atEnd.map((o) => o.id), ["to-1"]);
  assert.equal(atEnd[0].opacity, 1);
});
