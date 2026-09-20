const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const out = require("./helpers/compiled.cjs").maps;
const { countryClipRings, highlightPieces, pieceBox, pieceClip } = require(path.join(out, "isolate.js"));

const MYS_50M = [[0, 0], [10, 0], [10, 10], [0, 0]];
const SABAH = [[6, 6], [10, 6], [10, 10], [6, 6]];
const SARAWAK = [[0, 0], [6, 0], [6, 6], [0, 0]];
const IDN_50M = [[0, -10], [10, -10], [10, 0], [0, -10]];
const IDN_KAL = [[0, -10], [5, -10], [5, 0], [0, -10]];

function admin0(code, ring) {
  return { properties: { ADM0_A3: code }, geometry: { type: "Polygon", coordinates: [ring] } };
}

function admin1(country, code, ring) {
  return {
    properties: { adm0_a3: country, adm1_code: code },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

const admin0Features = [admin0("MYS", MYS_50M), admin0("IDN", IDN_50M)];
const admin1Features = [admin1("MYS", "MYS-1186", SABAH), admin1("MYS", "MYS-1187", SARAWAK)];

const cases = [
  { name: "one A1:", highlights: ["A1:MYS-1186"], admin1: admin1Features },
  { name: "one bare code", highlights: ["MYS"], admin1: admin1Features },
  { name: "mixed", highlights: ["IDN", "A1:MYS-1186"], admin1: admin1Features },
  { name: "nested region", highlights: ["MYS", "A1:MYS-1186"], admin1: admin1Features },
  {
    name: "border-cut neighbour",
    highlights: ["IDN", "A1:MYS-1186"],
    admin1: [...admin1Features, admin1("IDN", "IDN-1", IDN_KAL)],
  },
  {
    name: "interleaved admin1 list",
    highlights: ["MYS", "A1:IDN-1"],
    admin1: [admin1("MYS", "MYS-1186", SABAH), admin1("IDN", "IDN-1", IDN_KAL), admin1("MYS", "MYS-1187", SARAWAK)],
  },
];

test("one A1: highlight yields a single A1:-prefixed piece", () => {
  const pieces = highlightPieces(admin0Features, ["A1:MYS-1186"], admin1Features);
  assert.deepEqual(pieces, [{ id: "A1:MYS-1186", rings: [SABAH] }]);
});

test("one bare code yields a single ADM0-coded piece", () => {
  const pieces = highlightPieces(admin0Features, ["MYS"], admin1Features);
  assert.deepEqual(pieces, [{ id: "MYS", rings: [MYS_50M] }]);
});

test("mixed country and region highlights are separate pieces in emission order", () => {
  const pieces = highlightPieces(admin0Features, ["IDN", "A1:MYS-1186"], admin1Features);
  assert.deepEqual(pieces, [
    { id: "IDN", rings: [IDN_50M] },
    { id: "A1:MYS-1186", rings: [SABAH] },
  ]);
});

test("a country whose region is also highlighted emits one piece keyed by the country code from its admin-1 rings", () => {
  const pieces = highlightPieces(admin0Features, ["MYS", "A1:MYS-1186"], admin1Features);
  assert.deepEqual(pieces, [{ id: "MYS", rings: [SABAH, SARAWAK] }]);
});

test("keepNestedRegions emits the country piece and the nested region as its own cutout", () => {
  const pieces = highlightPieces(admin0Features, ["MYS", "A1:MYS-1186"], admin1Features, {
    keepNestedRegions: true,
  });
  assert.deepEqual(
    pieces.map((p) => p.id),
    ["MYS", "A1:MYS-1186"]
  );
  assert.deepEqual(pieces[0].rings, [SABAH, SARAWAK]);
  assert.deepEqual(pieces[1].rings, [SABAH]);
});

test("border cut: a highlighted country beside a highlighted region is still its own piece", () => {
  const withIdn = [...admin1Features, admin1("IDN", "IDN-1", IDN_KAL)];
  const pieces = highlightPieces(admin0Features, ["IDN", "A1:MYS-1186"], withIdn);
  assert.deepEqual(pieces, [
    { id: "A1:MYS-1186", rings: [SABAH] },
    { id: "IDN", rings: [IDN_KAL] },
  ]);
});

test("interleaved admin1 features still fold into one piece per cut country, at its first appearance", () => {
  const withInterleave = [admin1("MYS", "MYS-1186", SABAH), admin1("IDN", "IDN-1", IDN_KAL), admin1("MYS", "MYS-1187", SARAWAK)];
  const pieces = highlightPieces(admin0Features, ["MYS", "A1:IDN-1"], withInterleave);
  assert.deepEqual(pieces, [
    { id: "MYS", rings: [SABAH, SARAWAK] },
    { id: "A1:IDN-1", rings: [IDN_KAL] },
  ]);
});

for (const c of cases) {
  test(`parity with countryClipRings: ${c.name}`, () => {
    const flattened = highlightPieces(admin0Features, c.highlights, c.admin1).flatMap((p) => p.rings);
    assert.deepEqual(countryClipRings(admin0Features, c.highlights, c.admin1), flattened);
  });
}

test("pieceBox expands by bleed and rounds outward to integers", () => {
  const box = pieceBox([[10.2, 10.8], [20.4, 20.1]], 100, 100, 1);
  assert.deepEqual(box, { x: 9, y: 9, w: 13, h: 13 });
});

test("pieceBox clamps to 0 and to width/height", () => {
  const box = pieceBox([[-5, -5], [105, 105]], 100, 100, 1);
  assert.deepEqual(box, { x: 0, y: 0, w: 100, h: 100 });
});

test("pieceBox returns null when fully offscreen", () => {
  assert.equal(pieceBox([[-10, -10], [-2, -2]], 100, 100, 1), null);
});

test("pieceBox on a sub-pixel polygon still has w/h of at least 1", () => {
  const box = pieceBox([[50, 50], [50.2, 50.2]], 100, 100, 0);
  assert.ok(box.w >= 1 && box.h >= 1);
});

test("pieceClip applies map.project x DPR - crop, and returns matching source/dest drawImage rectangles", () => {
  const rings = [[[10, 10], [30, 10], [30, 30], [10, 10]]];
  const project = ([lon, lat]) => ({ x: lon, y: lat });
  const dpr = 2;
  const cropX = 5;
  const cropY = 7;
  const clip = pieceClip(rings, project, dpr, cropX, cropY, 200, 200, 1);
  assert.ok(clip);
  const expectedRingsPx = [[[10 * dpr - cropX, 10 * dpr - cropY], [30 * dpr - cropX, 10 * dpr - cropY], [30 * dpr - cropX, 30 * dpr - cropY], [10 * dpr - cropX, 10 * dpr - cropY]]];
  assert.deepEqual(clip.ringsPx, expectedRingsPx);
  const expectedBox = pieceBox(expectedRingsPx.flat(), 200, 200, 1);
  assert.deepEqual(clip.box, expectedBox);
  assert.deepEqual(clip.source, { sx: cropX + expectedBox.x, sy: cropY + expectedBox.y, sw: expectedBox.w, sh: expectedBox.h });
  assert.deepEqual(clip.dest, { dx: expectedBox.x, dy: expectedBox.y, dw: expectedBox.w, dh: expectedBox.h });
});

test("pieceClip returns null when the projected piece is fully offscreen", () => {
  const rings = [[[-40, -40], [-30, -40], [-30, -30], [-40, -40]]];
  const project = ([lon, lat]) => ({ x: lon, y: lat });
  assert.equal(pieceClip(rings, project, 1, 0, 0, 100, 100, 1), null);
});

function pointInRing([px, py], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects = yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInRings(pt, rings) {
  return rings.some((ring) => pointInRing(pt, ring));
}

/** Minimal 2D-context stand-in: enough of the `translate`/`beginPath`/`moveTo`/`lineTo`/`clip`/
 * `fillRect` surface to reproduce captureExport.ts's draw calls and record which pixels a fill
 * actually touches, without a real canvas. */
class FakeCtx {
  constructor() {
    this.tx = 0;
    this.ty = 0;
    this.path = [];
    this.clipRings = null;
  }
  translate(dx, dy) {
    this.tx += dx;
    this.ty += dy;
  }
  beginPath() {
    this.path = [];
  }
  moveTo(x, y) {
    this.path.push([[x + this.tx, y + this.ty]]);
  }
  lineTo(x, y) {
    this.path[this.path.length - 1].push([x + this.tx, y + this.ty]);
  }
  closePath() {}
  clip() {
    this.clipRings = this.path.map((ring) => ring.slice());
  }
  fillRect(x, y, w, h) {
    const rx = x + this.tx;
    const ry = y + this.ty;
    const filled = [];
    for (let px = rx; px < rx + w; px++) {
      for (let py = ry; py < ry + h; py++) {
        const centre = [px + 0.5, py + 0.5];
        if (!this.clipRings || pointInRings(centre, this.clipRings)) filled.push(`${px},${py}`);
      }
    }
    return filled;
  }
}

// Covers clip coverage only (which pixels each piece's path admits); source/dest rect alignment
// against map pixels is checked separately by the pieceClip source/dest unit test.
test("composite parity: base + per-piece clips cover exactly the union of the old single-clip region", () => {
  const width = 40;
  const height = 30;
  const project = ([lon, lat]) => ({ x: lon, y: lat });
  const piecesInPlay = highlightPieces(admin0Features, ["MYS", "IDN"], []);
  assert.equal(piecesInPlay.length, 2);

  const oldCtx = new FakeCtx();
  oldCtx.beginPath();
  for (const piece of piecesInPlay) {
    for (const ring of piece.rings) {
      ring.forEach(([lon, lat], index) => {
        const px = lon;
        const py = lat;
        if (index === 0) oldCtx.moveTo(px, py);
        else oldCtx.lineTo(px, py);
      });
      oldCtx.closePath();
    }
  }
  oldCtx.clip();
  const oldFilled = new Set(oldCtx.fillRect(0, 0, width, height));

  const newFilled = new Set();
  for (const piece of piecesInPlay) {
    const clip = pieceClip(piece.rings, project, 1, 0, 0, width, height, 1);
    assert.ok(clip);
    const { box, ringsPx, dest } = clip;
    const ctx = new FakeCtx();
    ctx.translate(-box.x, -box.y);
    ctx.beginPath();
    for (const ring of ringsPx) {
      ring.forEach(([px, py], index) => {
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
    }
    ctx.clip();
    for (const key of ctx.fillRect(dest.dx, dest.dy, dest.dw, dest.dh)) {
      const [devX, devY] = key.split(",").map(Number);
      newFilled.add(`${devX + box.x},${devY + box.y}`);
    }
  }

  assert.deepEqual([...newFilled].sort(), [...oldFilled].sort());
  assert.ok(newFilled.size > 0);
});
