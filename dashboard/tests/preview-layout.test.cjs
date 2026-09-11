const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-preview-layout-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/types.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const {
  compensatedFov,
  previewLayout,
  objectBoxStyle,
  PREVIEW_NAV_MAX,
  exportScale,
  WALL_W,
  CENTRE_W,
  CG_W,
} = require(path.join(out, "types.js"));

test("compensatedFov: equal canvas/band is a no-op, doubled canvas widens per the tan formula, zero band falls back to base", () => {
  assert.equal(compensatedFov(540, 540), 36.87);
  const base = (36.87 * Math.PI) / 180;
  const expected = (2 * Math.atan(2 * Math.tan(base / 2)) * 180) / Math.PI;
  assert.ok(Math.abs(compensatedFov(1080, 540) - expected) < 1e-9);
  assert.equal(compensatedFov(1080, 0), 36.87);
});

test("previewLayout: tall window (frame taller than the band) widens innerH past the band for nav context", () => {
  const l = previewLayout(1920, 1080, 3840, 2);
  assert.equal(l.bandW, 1920);
  assert.equal(l.bandH, 540);
  assert.equal(l.innerW, 1920);
  assert.equal(l.k, 1);
  assert.equal(l.innerH, 1080);
  assert.equal(l.bandTop, 270);
  assert.ok(l.fov > 36.87);
  assert.ok(Math.abs(l.fov - compensatedFov(1080, 540)) < 1e-9);
});

test("previewLayout: frame that exactly fits the band has zero nav margin and base fov", () => {
  const l = previewLayout(3840, 1080, 3840, 2);
  assert.equal(l.innerH, 540);
  assert.equal(l.bandTop, 0);
  assert.ok(Math.abs(l.fov - 36.87) < 1e-9);
});

test("previewLayout: innerH clamps at PREVIEW_NAV_MAX times the band's own inner height", () => {
  const l = previewLayout(600, 4000, 7680, 4);
  assert.equal(l.innerH, (1080 / 4) * PREVIEW_NAV_MAX);
});

test("previewLayout: degenerate dims (zero/negative frame, surface, or scale) return an inert layout", () => {
  for (const args of [
    [0, 1080, 3840, 2],
    [1920, 0, 3840, 2],
    [1920, 1080, 0, 2],
    [1920, 1080, 3840, 0],
    [-1, 1080, 3840, 2],
  ]) {
    const l = previewLayout(...args);
    assert.deepEqual(l, { innerW: 0, innerH: 0, bandW: 0, bandH: 0, bandTop: 0, bandInnerH: 0, k: 1, fov: 36.87 });
  }
});

test("previewLayout: band-local invariants hold across FW/LW/CG surfaces and a spread of frame sizes", () => {
  const surfaces = [
    { surfaceWidth: WALL_W, scale: exportScale(WALL_W) },
    { surfaceWidth: CENTRE_W, scale: exportScale(CENTRE_W) },
    { surfaceWidth: CG_W, scale: exportScale(CG_W) },
  ];
  const frames = [
    [1920, 1080],
    [3840, 1080],
    [900, 1600],
    [2000, 300],
    [7680, 4320],
  ];
  for (const { surfaceWidth, scale } of surfaces) {
    for (const [frameW, frameH] of frames) {
      const l = previewLayout(frameW, frameH, surfaceWidth, scale);
      const bandInnerH = 1080 / scale;
      assert.ok(Math.abs(2 * l.bandTop + bandInnerH - l.innerH) < 1e-9);
      if (l.innerH < bandInnerH * PREVIEW_NAV_MAX - 1e-9) {
        assert.ok(Math.abs(l.innerH / bandInnerH - frameH / l.bandH) < 1e-9);
      }
      assert.equal(l.innerW, surfaceWidth / scale);
      assert.ok(Math.abs(l.k * l.innerW - l.bandW) < 1e-9);
    }
  }
});

test("objectBoxStyle: maps a band-local box to inner-local CSS px via k and bandTop", () => {
  const style = objectBoxStyle({ x: 400, y: 300, w: 80, h: 120 }, 0.25, 100);
  assert.deepEqual(style, { left: 100, top: 50, width: 20, height: 30 });
});
