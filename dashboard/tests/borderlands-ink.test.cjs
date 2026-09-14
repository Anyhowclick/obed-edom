const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "borderlands-ink-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out,
  path.join(root, "src/maps/borderlandsGeometry.ts"),
  path.join(root, "src/maps/borderlandsProjection.ts"),
  path.join(root, "src/maps/borderlandsFacade.ts"),
  path.join(root, "src/maps/borderlandsInkPolicy.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);

const geo = require(path.join(out, "borderlandsGeometry.js"));
const proj = require(path.join(out, "borderlandsProjection.js"));
const { buildingExtents, planBuildingFacade, planBuildingsInk } = require(path.join(out, "borderlandsFacade.js"));
const { inkFragmentKey, inkRebuildKey, shouldReplaceInkMesh, inkWidthCssPx, buildingLayerActive } = require(path.join(out, "borderlandsInkPolicy.js"));

const M = 111320;
const suntec = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/borderlands-suntec.json"), "utf8"));

function toLngLat(lng, lat, e, n) {
  const cos = Math.max(Math.cos((lat * Math.PI) / 180), 0.2);
  return [lng + e / (M * cos), lat + n / M];
}

function closed(points) {
  return [...points, points[0]];
}

function rect(lng, lat, west, south, east, north) {
  return [closed([
    toLngLat(lng, lat, west, south),
    toLngLat(lng, lat, east, south),
    toLngLat(lng, lat, east, north),
    toLngLat(lng, lat, west, north),
  ])];
}

function densifyRect(lng, lat, west, south, east, north, perSide) {
  const corners = [
    toLngLat(lng, lat, west, south),
    toLngLat(lng, lat, east, south),
    toLngLat(lng, lat, east, north),
    toLngLat(lng, lat, west, north),
  ];
  const ring = [];
  for (let i = 0; i < 4; i++) {
    const a = corners[i];
    const b = corners[(i + 1) % 4];
    for (let s = 0; s < perSide; s++) {
      const t = s / perSide;
      ring.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
  }
  return [closed(ring)];
}

function circle(lng, lat, radiusM, n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const t = (i / n) * Math.PI * 2;
    pts.push(toLngLat(lng, lat, Math.cos(t) * radiusM, Math.sin(t) * radiusM));
  }
  return [closed(pts)];
}

function roundedRect(lng, lat, w, h, r, arc) {
  const pts = [];
  const corners = [
    [w / 2 - r, -h / 2 + r, 1.5 * Math.PI, 2 * Math.PI],
    [w / 2 - r, h / 2 - r, 0, 0.5 * Math.PI],
    [-w / 2 + r, h / 2 - r, 0.5 * Math.PI, Math.PI],
    [-w / 2 + r, -h / 2 + r, Math.PI, 1.5 * Math.PI],
  ];
  for (const [cx, cy, a0, a1] of corners) {
    for (let i = 0; i <= arc; i++) {
      const t = a0 + ((a1 - a0) * i) / arc;
      pts.push(toLngLat(lng, lat, cx + Math.cos(t) * r, cy + Math.sin(t) * r));
    }
  }
  return [closed(pts)];
}

function feature(coordinates, properties, extras = {}) {
  return {
    id: extras.id,
    source: extras.source || "openmaptiles",
    sourceLayer: extras.sourceLayer || "building",
    geometry: extras.type === "MultiPolygon" ? { type: "MultiPolygon", coordinates } : { type: "Polygon", coordinates },
    properties,
  };
}

function posts(segs) {
  return segs.filter((seg) => Math.abs(seg.a[0] - seg.b[0]) < 1e-12 && Math.abs(seg.a[1] - seg.b[1]) < 1e-12);
}

function roofs(segs) {
  return segs.filter((seg) => Math.abs(seg.a[2] - seg.b[2]) < 1e-9);
}

const SG = { lng: 103.84, lat: 1.27 };

test("skips footprints without a rendered extrusion height", () => {
  const square = feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), {});
  assert.equal(buildingExtents(square), null);
  assert.equal(planBuildingFacade({ ...square, properties: { height: 40, levels: 8 } }).length, 0);
  assert.equal(planBuildingFacade({ ...square, properties: { render_height: 0, height: 40 } }).length, 0);
});

test("uses rendered numeric heights only", () => {
  const square = feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), { render_height: 21, render_min_height: 0 });
  assert.equal(buildingExtents(square).top, 21);
  assert.equal(buildingExtents(feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), { render_height: "21" })), null);
  assert.equal(buildingExtents(feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), { levels: 4 })), null);
});

test("20x30 m rectangle keeps a roof contour and four corner posts", () => {
  const box = feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), { render_height: 40, render_min_height: 0 });
  const segs = planBuildingFacade(box);
  assert.equal(roofs(segs).length, 4);
  assert.equal(posts(segs).length, 4);
  assert.equal(segs.filter((seg) => Math.abs(seg.a[2] - seg.b[2]) < 1e-9 && seg.a[2] < 0.2).length, 0);
  assert.ok(posts(segs).every((seg) => seg.a[2] === 0 && seg.b[2] > 40));
});

test("densified rectangle matches the same canonical posts", () => {
  const simple = planBuildingFacade(feature(rect(SG.lng, SG.lat, 0, 0, 20, 30), { render_height: 40, render_min_height: 0 }));
  const dense = planBuildingFacade(feature(densifyRect(SG.lng, SG.lat, 0, 0, 20, 30, 12), { render_height: 40, render_min_height: 0 }));
  assert.equal(posts(simple).length, 4);
  assert.equal(posts(dense).length, 4);
  assert.equal(roofs(dense).length, 4);
});

test("smooth circles do not invent architectural posts", () => {
  const a = planBuildingFacade(feature(circle(SG.lng, SG.lat, 24, 96), { render_height: 40, render_min_height: 0 }));
  const b = planBuildingFacade(feature(circle(SG.lng, SG.lat, 24, 192), { render_height: 40, render_min_height: 0 }));
  assert.equal(posts(a).length, 0);
  assert.equal(posts(b).length, 0);
  assert.ok(roofs(a).length >= 16);
});

test("rounded rectangle posts only remain at sharp junctions", () => {
  const segs = planBuildingFacade(feature(roundedRect(SG.lng, SG.lat, 40, 24, 6, 16), { render_height: 30, render_min_height: 0 }));
  assert.ok(posts(segs).length <= 4);
  assert.ok(roofs(segs).length >= 4);
});

test("half-metre teeth do not become full-height posts", () => {
  const ring = [];
  for (let i = 0; i < 40; i++) {
    const tooth = i % 2 === 0 ? 0 : 0.5;
    ring.push(toLngLat(SG.lng, SG.lat, i, tooth));
  }
  ring.push(toLngLat(SG.lng, SG.lat, 40, 12));
  ring.push(toLngLat(SG.lng, SG.lat, 0, 12));
  const segs = planBuildingFacade(feature([closed(ring)], { render_height: 18, render_min_height: 0 }));
  assert.ok(posts(segs).length <= 6);
  assert.ok(posts(segs).length >= 2);
});

test("L-shaped recess keeps major corners and does not chord the mouth", () => {
  const ring = [closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 30, 0),
    toLngLat(SG.lng, SG.lat, 30, 15),
    toLngLat(SG.lng, SG.lat, 15, 15),
    toLngLat(SG.lng, SG.lat, 15, 30),
    toLngLat(SG.lng, SG.lat, 0, 30),
  ])];
  const segs = planBuildingFacade(feature(ring, { render_height: 22, render_min_height: 0 }));
  assert.ok(posts(segs).length >= 5);
  const xs = roofs(segs).flatMap((seg) => [seg.a[0], seg.b[0]]);
  const ys = roofs(segs).flatMap((seg) => [seg.a[1], seg.b[1]]);
  const mouth = toLngLat(SG.lng, SG.lat, 22, 22);
  const crossesMouth = roofs(segs).some((seg) => {
    const midX = (seg.a[0] + seg.b[0]) / 2;
    const midY = (seg.a[1] + seg.b[1]) / 2;
    return Math.abs(midX - mouth[0]) < 2e-5 && Math.abs(midY - mouth[1]) < 2e-5;
  });
  assert.equal(crossesMouth, false);
  assert.ok(Math.max(...xs) > toLngLat(SG.lng, SG.lat, 28, 0)[0]);
  assert.ok(Math.max(...ys) > toLngLat(SG.lng, SG.lat, 0, 28)[1]);
});

test("more than eight strong corners stay within the per-component cap", () => {
  const pts = [];
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    const r = i % 2 === 0 ? 18 : 10;
    pts.push(toLngLat(SG.lng, SG.lat, Math.cos(a) * r, Math.sin(a) * r));
  }
  const segs = planBuildingFacade(feature([closed(pts)], { render_height: 28, render_min_height: 0 }));
  assert.ok(posts(segs).length <= 8);
});

test("courtyard holes keep topology but receive no decorative ink", () => {
  const outer = closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 40, 0),
    toLngLat(SG.lng, SG.lat, 40, 40),
    toLngLat(SG.lng, SG.lat, 0, 40),
  ]);
  const hole = closed([
    toLngLat(SG.lng, SG.lat, 12, 12),
    toLngLat(SG.lng, SG.lat, 28, 12),
    toLngLat(SG.lng, SG.lat, 28, 28),
    toLngLat(SG.lng, SG.lat, 12, 28),
  ]);
  const built = geo.normalizeFeature(feature([outer, hole], { render_height: 16, render_min_height: 0 }));
  assert.equal(built.length, 1);
  assert.equal(built[0].holes.length, 1);
  const segs = planBuildingFacade(feature([outer, hole], { render_height: 16, render_min_height: 0 }));
  assert.equal(roofs(segs).length, 4);
  assert.equal(posts(segs).length, 4);
});

test("MultiPolygon members are independent budget units", () => {
  const members = [0, 1, 2].map((i) => rect(SG.lng + i * 0.001, SG.lat, 0, 0, 12, 12));
  const segs = planBuildingFacade(feature(members, { render_height: 14, render_min_height: 0 }, { type: "MultiPolygon" }));
  assert.equal(posts(segs).length, 12);
  assert.equal(roofs(segs).length, 12);
});

test("338-member feature is not one global eight-post object", () => {
  const members = [];
  for (let i = 0; i < 338; i++) {
    members.push(rect(SG.lng + (i % 20) * 0.0004, SG.lat + Math.floor(i / 20) * 0.0004, 0, 0, 8, 8));
  }
  const normalized = geo.normalizeFeature(feature(members, { render_height: 10, render_min_height: 0 }, { type: "MultiPolygon", id: "40399360" }));
  assert.equal(normalized.length, 338);
  const planned = geo.planNormalizedInk(normalized);
  assert.ok(planned.diagnostics.selectedPosts > 8);
  assert.ok(planned.diagnostics.selectedPosts <= 338 * 8);
});

test("large triangular buildings are kept; tiny scraps are not", () => {
  const large = feature([closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 40, 0),
    toLngLat(SG.lng, SG.lat, 0, 40),
  ])], { render_height: 20, render_min_height: 0 });
  const scrap = feature([closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 1, 0),
    toLngLat(SG.lng, SG.lat, 0, 1),
  ])], { render_height: 20, render_min_height: 0 });
  assert.ok(planBuildingFacade(large).length >= 4);
  assert.equal(planBuildingFacade(scrap).length, 0);
});

test("tall narrow volumes survive a small footprint", () => {
  const needle = feature(rect(SG.lng, SG.lat, 0, 0, 1.6, 1.6), { render_height: 40, render_min_height: 0 });
  assert.ok(planBuildingFacade(needle).length > 0);
});

test("invalid rings do not crash or become convex hulls", () => {
  const nanRing = feature([[[103.84, 1.27], [Number.NaN, 1.27], [103.84, 1.28], [103.84, 1.27]]], { render_height: 20 });
  const infRing = feature([[[103.84, 1.27], [Infinity, 1.27], [103.84, 1.28], [103.84, 1.27]]], { render_height: 20 });
  assert.equal(planBuildingFacade(nanRing).length, 0);
  assert.equal(planBuildingFacade(infRing).length, 0);
});

test("canonical winding and start index match", () => {
  const pts = [
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 20, 0),
    toLngLat(SG.lng, SG.lat, 20, 30),
    toLngLat(SG.lng, SG.lat, 0, 30),
  ];
  const a = planBuildingsInk([feature([closed(pts)], { render_height: 16, render_min_height: 0 })]);
  const b = planBuildingsInk([feature([closed(pts.slice().reverse())], { render_height: 16, render_min_height: 0 })]);
  const rotated = [pts[2], pts[3], pts[0], pts[1]];
  const c = planBuildingsInk([feature([closed(rotated)], { render_height: 16, render_min_height: 0 })]);
  assert.equal(a.signature, b.signature);
  assert.equal(a.signature, c.signature);
});

test("metric corner rules agree at Singapore and high latitude", () => {
  const sg = planBuildingFacade(feature(rect(103.84, 1.27, 0, 0, 20, 30), { render_height: 40, render_min_height: 0 }));
  const north = planBuildingFacade(feature(rect(10, 60, 0, 0, 20, 30), { render_height: 40, render_min_height: 0 }));
  assert.equal(posts(sg).length, posts(north).length);
  assert.equal(roofs(sg).length, roofs(north).length);
});

test("antimeridian-adjacent contours stay local", () => {
  const segs = planBuildingFacade(feature(rect(179.999, 1.27, 0, 0, 20, 30), { render_height: 18, render_min_height: 0 }));
  assert.ok(segs.length >= 8);
  for (const seg of segs) {
    assert.ok(Math.abs(seg.a[0] - seg.b[0]) < 1);
  }
});

test("Suntec hall keeps an outer contour and no panel grid", () => {
  const hall = suntec.features[0];
  const segs = planBuildingFacade(hall);
  assert.ok(roofs(segs).length >= 3);
  const panels = [];
  for (let i = 0; i < 71; i++) {
    panels.push(rect(103.857 + (i % 10) * 0.00005, 1.2934 + Math.floor(i / 10) * 0.00005, 0, 0, 4, 4));
  }
  const grid = planBuildingFacade(feature(panels, { render_height: 33, render_min_height: 28 }, { type: "MultiPolygon", id: "3930904030" }));
  assert.equal(grid.length, 0);
});

test("substantial elevated volumes stay eligible", () => {
  const tower = feature(rect(SG.lng, SG.lat, 0, 0, 20, 20), { render_height: 80, render_min_height: 20 });
  assert.equal(buildingExtents(tower).top, 80);
  assert.ok(planBuildingFacade(tower).length >= 8);
});

test("render_min_height 0 is not raised by min_height", () => {
  const box = feature(rect(SG.lng, SG.lat, 0, 0, 16, 16), { render_height: 24, render_min_height: 0, min_height: 12 });
  assert.equal(buildingExtents(box).base, 0);
});

test("identical fragments collapse; distinct clips and heights survive", () => {
  const west = feature(rect(SG.lng, SG.lat, 0, 0, 20, 20), { render_height: 20, render_min_height: 0 }, { id: 42 });
  const westCopy = feature(rect(SG.lng, SG.lat, 0, 0, 20, 20), { render_height: 20, render_min_height: 0 }, { id: 42 });
  const east = feature(rect(SG.lng, SG.lat, 20, 0, 40, 20), { render_height: 20, render_min_height: 0 }, { id: 42 });
  const tall = feature(rect(SG.lng, SG.lat, 0, 0, 20, 20), { render_height: 40, render_min_height: 20 }, { id: 42 });
  const planned = planBuildingsInk([west, westCopy, east, tall]);
  assert.equal(planned.components.length, 3);
  assert.notEqual(inkFragmentKey(42, west.geometry.coordinates), inkFragmentKey(42, east.geometry.coordinates));
});

test("sampled first/middle/last collision still keeps distinct rings", () => {
  const a = closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 8, 0),
    toLngLat(SG.lng, SG.lat, 16, 8),
    toLngLat(SG.lng, SG.lat, 8, 16),
    toLngLat(SG.lng, SG.lat, 0, 8),
  ]);
  const b = closed([
    toLngLat(SG.lng, SG.lat, 0, 0),
    toLngLat(SG.lng, SG.lat, 12, 1),
    toLngLat(SG.lng, SG.lat, 16, 8),
    toLngLat(SG.lng, SG.lat, 8, 16),
    toLngLat(SG.lng, SG.lat, 0, 8),
  ]);
  assert.equal(a.length, b.length);
  assert.notEqual(inkFragmentKey(7, [a]), inkFragmentKey(7, [b]));
});

test("shared coincident edges drop only the interior seam", () => {
  const left = feature(rect(SG.lng, SG.lat, 0, 0, 20, 20), { render_height: 16, render_min_height: 0 }, { id: "L" });
  const right = feature(rect(SG.lng, SG.lat, 20, 0, 40, 20), { render_height: 16, render_min_height: 0 }, { id: "R" });
  const planned = planBuildingsInk([left, right]);
  assert.equal(planned.diagnostics.sharedEdgesRemoved >= 1, true);
  assert.ok(roofs(planned.segs).length >= 6);
});

test("T-junction shared spans are omitted from the planned roof mesh", () => {
  const long = feature(rect(SG.lng, SG.lat, 0, 0, 60, 10), { render_height: 16, render_min_height: 0 }, { id: "LONG" });
  const stub = feature(rect(SG.lng, SG.lat, 20, 10, 30, 20), { render_height: 16, render_min_height: 0 }, { id: "STUB" });
  const { components } = geo.normalizeBuildings([long, stub]);
  const shared = geo.suppressSharedEdges(components);
  assert.ok(shared.keys.size >= 1);
  const blob = [...shared.keys].join("\n");
  const p = toLngLat(SG.lng, SG.lat, 20, 10);
  const q = toLngLat(SG.lng, SG.lat, 30, 10);
  assert.match(blob, new RegExp(p[0].toFixed(7).replace(".", "\\.")));
  assert.match(blob, new RegExp(q[0].toFixed(7).replace(".", "\\.")));
  const planned = planBuildingsInk([long, stub]);
  assert.ok(planned.diagnostics.sharedEdgesRemoved >= 1);
  const cos = Math.cos(SG.lat * Math.PI / 180);
  const seam = roofs(planned.segs).filter((seg) => {
    const e0 = (seg.a[0] - SG.lng) * M * cos;
    const e1 = (seg.b[0] - SG.lng) * M * cos;
    const n0 = (seg.a[1] - SG.lat) * M;
    const n1 = (seg.b[1] - SG.lat) * M;
    if (Math.abs(n0 - 10) > 1 || Math.abs(n1 - 10) > 1) return false;
    return Math.min(e0, e1) < 24 && Math.max(e0, e1) > 26;
  });
  assert.equal(seam.length, 0);
});

function touchingGrid(count, cols) {
  const features = [];
  for (let i = 0; i < count; i++) {
    const x = (i % cols) * 8;
    const y = Math.floor(i / cols) * 8;
    features.push(feature(rect(SG.lng, SG.lat, x, y, x + 8, y + 8), { render_height: 12, render_min_height: 0 }, { id: `g${i}` }));
  }
  return features;
}

test("shared-edge suppression stays near-linear on a touching grid", () => {
  const started = Date.now();
  const planned = planBuildingsInk(touchingGrid(400, 20));
  const ms = Date.now() - started;
  assert.ok(planned.diagnostics.sharedEdgesRemoved > 100, planned.diagnostics.sharedEdgesRemoved);
  assert.ok(ms < 120, `shared-edge suppression took ${ms}ms`);
});

test("seam application stays near-linear on a 1600-building grid", () => {
  const started = Date.now();
  const planned = planBuildingsInk(touchingGrid(1600, 40));
  const ms = Date.now() - started;
  assert.ok(planned.diagnostics.sharedEdgesRemoved > 500, planned.diagnostics.sharedEdgesRemoved);
  assert.ok(ms < 250, `seam application took ${ms}ms`);
});

test("bounds, not a centre radius, decide which buildings stay eligible", () => {
  const edge = feature(rect(SG.lng, SG.lat, 2000, 0, 2020, 20), { render_height: 20, render_min_height: 0 }, { id: "edge" });
  const cos = Math.cos(SG.lat * Math.PI / 180);
  const bounds = {
    west: SG.lng - 0.002,
    south: SG.lat - 0.002,
    east: SG.lng + 2020 / (M * cos),
    north: SG.lat + 0.002,
  };
  const planned = planBuildingsInk([edge], { bounds, padDeg: 0.002 });
  assert.ok(planned.segs.length > 0);
  assert.equal(planned.diagnostics.normalizedCount, 1);
});

test("raw-vertex budget is applied after volume sort, not query order", () => {
  const dense = feature(circle(SG.lng, SG.lat, 3, 80), { render_height: 8, render_min_height: 0 }, { id: "dense" });
  const keep = feature(rect(SG.lng, SG.lat, 80, 0, 140, 60), { render_height: 40, render_min_height: 0 }, { id: "keep" });
  const a = geo.normalizeBuildings([dense, keep], { maxRawVertices: 10 });
  const b = geo.normalizeBuildings([keep, dense], { maxRawVertices: 10 });
  assert.equal(a.components.length, 1);
  assert.equal(b.components.length, 1);
  assert.equal(a.components[0].identity, b.components[0].identity);
  assert.ok(a.components[0].areaM2 > 1000);
  assert.equal(a.diagnostics.budgetDropped, 1);
});

test("ink uses zero clip-space depth bias", () => {
  assert.equal(proj.INK_DEPTH_BIAS, 0);
  const ink = fs.readFileSync(path.join(root, "src/maps/borderlandsInk.ts"), "utf8");
  assert.match(ink, /INK_DEPTH_BIAS/);
  assert.doesNotMatch(ink, /uniform1f\(depthBiasLoc,\s*0\.00[1-9]/);
});

test("query order does not change the selected signature", () => {
  const a = feature(rect(SG.lng, SG.lat, 0, 0, 30, 30), { render_height: 40, render_min_height: 0 }, { id: "A" });
  const b = feature(rect(SG.lng, SG.lat, 80, 0, 92, 12), { render_height: 12, render_min_height: 0 }, { id: "B" });
  assert.equal(planBuildingsInk([a, b]).signature, planBuildingsInk([b, a]).signature);
});

test("rebuild key includes pitch, coverage, and uncapped zoom", () => {
  const base = { styleGeneration: 1, sourceRevision: 1, sourceReady: true, zoom: 16.8, lng: 103.841, lat: 1.276, bearing: 0, pitch: 0, viewportW: 800, viewportH: 400, buildingsVisible: true };
  assert.notEqual(inkRebuildKey(base), inkRebuildKey({ ...base, zoom: 18.2 }));
  assert.notEqual(inkRebuildKey(base), inkRebuildKey({ ...base, pitch: 60 }));
  assert.notEqual(inkRebuildKey(base), inkRebuildKey({ ...base, lng: 103.842 }));
});

test("authoritative empty snapshots replace; loading does not", () => {
  assert.equal(shouldReplaceInkMesh({ kind: "ok", features: [] }), true);
  assert.equal(shouldReplaceInkMesh({ kind: "loading" }), false);
  assert.equal(shouldReplaceInkMesh({ kind: "error" }), false);
  assert.equal(shouldReplaceInkMesh({ kind: "ok", features: [] }, 80, true), true);
});

test("building layer eligibility honours minzoom", () => {
  assert.equal(buildingLayerActive({ hasLayer: true, visibility: "visible", minzoom: 14, zoom: 13.9 }), false);
  assert.equal(buildingLayerActive({ hasLayer: true, visibility: "visible", minzoom: 14, zoom: 14 }), true);
  assert.equal(buildingLayerActive({ hasLayer: true, visibility: "none", minzoom: 14, zoom: 16 }), false);
});

test("width policy is full CSS px from authored zoom", () => {
  assert.equal(inkWidthCssPx(14, 0), 0.7);
  assert.equal(inkWidthCssPx(16, 0), 0.85);
  assert.equal(inkWidthCssPx(18, 0), 0.95);
  assert.equal(inkWidthCssPx(16, -2), inkWidthCssPx(18, 0));
  assert.equal(proj.halfWidthBufferPx(0.85, 2), 0.85);
  assert.equal(proj.halfWidthBufferPx(0.85, 0.5), 0.2125);
  assert.equal(proj.halfWidthBufferPx(0.85, 4), 1.7);
});

test("local-matrix rebase preserves other columns and only rewrites translation", () => {
  const matrix = new Float64Array([
    2, 0, 0, 0,
    0, 3, 0, 0,
    0, 0, 4, 0,
    5, 6, 7, 1,
  ]);
  const local = proj.composeLocalMatrix(matrix, { x: 0.788, y: 0.496, z: 0.001 });
  assert.equal(local[0], 2);
  assert.equal(local[5], 3);
  assert.equal(local[10], 4);
  assert.ok(Math.abs(local[12] - (2 * 0.788 + 5)) < 1e-6);
});

test("Singapore sub-metre endpoints stay distinct after local conversion", () => {
  const earth = 2 * Math.PI * 6378137;
  const mercX = (lng) => (180 + lng) / 360;
  const a = mercX(103.840000);
  const b = mercX(103.840008);
  const origin = mercX(103.841);
  const localA = a - origin;
  const localB = b - origin;
  const f32 = new Float32Array([localA, localB]);
  const meters = earth * Math.cos(1.27 * Math.PI / 180);
  assert.ok(Math.abs(f32[0] - f32[1]) * meters > 0.01);
});

test("a behind-camera endpoint is clipped instead of inverted", () => {
  const clipped = proj.clipBehindNear({ x: 1, y: 1, z: 1, w: -2 }, { x: 0, y: 0, z: 0, w: 4 });
  assert.ok(clipped);
  assert.ok(clipped.w > 0);
  assert.ok(Number.isFinite(clipped.x) && Number.isFinite(clipped.y));
  assert.equal(proj.clipBehindNear({ x: 1, y: 1, z: 1, w: -1 }, { x: 0, y: 0, z: 0, w: -2 }), null);
});
