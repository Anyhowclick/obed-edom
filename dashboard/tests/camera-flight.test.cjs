const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const Module = require("node:module");

const root = path.resolve(__dirname, "..");
const runtime = process.env.CODEX_NODE || process.execPath;
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-flight-"));
const stubRoot = path.join(out, "node_modules", "maplibre-gl");
fs.mkdirSync(stubRoot, { recursive: true });
fs.writeFileSync(path.join(stubRoot, "index.js"), `exports.MercatorCoordinate=class { constructor(x,y,z){this.x=x;this.y=y;this.z=z} static fromLngLat(p){const r=Math.PI/180,s=Math.sin(p.lat*r);return new this((p.lng+180)/360,.5-Math.log((1+s)/(1-s))/(4*Math.PI),0)} toLngLat(){const n=Math.PI-2*Math.PI*this.y;return {lng:this.x*360-180,lat:180/Math.PI*Math.atan(.5*(Math.exp(n)-Math.exp(-n)))}}}; exports.Map=class {}; exports.setWorkerUrl=()=>{};`);
const workerStub = path.join(out, "worker-stub.js");
fs.writeFileSync(workerStub, "module.exports = '';\n");
const assetStub = path.join(out, "asset-stub.js");
fs.writeFileSync(assetStub, "exports.default = 'toner-vendor';\n");
const resolve = Module._resolveFilename;
Module._resolveFilename = function(request, parent, main, options) {
  if (request.includes("maplibre-gl-worker.mjs?worker&url")) return workerStub;
  if (request.includes("maptiler-toner-8688fbd.json?url")) return assetStub;
  return resolve.call(this, request, parent, main, options);
};
spawnSync(runtime, [path.join(root, "node_modules/typescript/bin/tsc"), "--noEmit", "false", "--noEmitOnError", "false", "--module", "commonjs", "--moduleResolution", "node", "--target", "ES2020", "--skipLibCheck", "true", "--outDir", out, path.join(root, "src/maps/captureFly.ts")], { cwd: root, stdio: "ignore" });
const flight = require(path.join(out, "captureFly.js"));
const KL = { lat: 3.139, lon: 101.6869, zoom: 8, bearing: 0, pitch: 0 };
const LA = { lat: 34.0522, lon: -118.2437, zoom: 8, bearing: 0, pitch: 0 };

test("van Wijk uses start-zoom pixels and exact fixture arc", () => {
  assert.ok(Math.abs(flight.hopDistancePx(KL, LA) - 52403.45645966809) < 1e-6);
  assert.ok(Math.abs(flight.cameraAtHop(KL, LA, .25, { width: 3840, easing: "linear" }).zoom - 5.657449273653497) < 1e-9);
  assert.ok(Math.abs(flight.cameraAtHop(KL, LA, .5, { width: 3840, easing: "linear" }).zoom - 4.213933809899869) < 1e-9);
  assert.ok(Math.abs(flight.cameraAtHop(KL, LA, .75, { width: 3840, easing: "linear" }).zoom - 5.657449273653497) < 1e-9);
});

test("samples are deterministic, exact at endpoints, and route-aware", () => {
  const route = [{ lat: 20, lon: 20 }, { lat: 28, lon: -40 }];
  const opts = { width: 1920, easing: "linear", routePoints: route };
  assert.deepEqual(flight.cameraAtHop(KL, LA, 0, opts), KL);
  assert.deepEqual(flight.cameraAtHop(KL, LA, 1, opts), LA);
  assert.deepEqual(flight.cameraAtHop(KL, LA, .43, opts), flight.cameraAtHop(KL, LA, .43, opts));
  assert.ok(flight.hopDistancePx(KL, LA, route) > flight.hopDistancePx(KL, LA));
});

test("same-center zoom, antimeridian, duplicate routes, and surface widths stay finite", () => {
  const zoomed = { ...KL, zoom: 12 };
  const dateA = { lat: 0, lon: 179.9, zoom: 8, bearing: 170, pitch: 20 };
  const dateB = { lat: 0.1, lon: -179.9, zoom: 9, bearing: -170, pitch: 35 };
  for (const [from, to, route] of [
    [KL, zoomed, undefined],
    [dateA, dateB, [{ lat: 0, lon: 179.9 }, { lat: 0, lon: 179.9 }, { lat: .05, lon: -180 }]],
  ]) for (const width of [1920, 3840, 7680]) {
    const samples = [.8, .1, .65, .25, .5].map((t) => flight.cameraAtHop(from, to, t, { width, easing: "linear", routePoints: route }));
    for (const camera of samples) for (const value of Object.values(camera)) assert.ok(Number.isFinite(value));
    assert.deepEqual(flight.cameraAtHop(from, to, 0, { width, routePoints: route }), from);
    assert.deepEqual(flight.cameraAtHop(from, to, 1, { width, routePoints: route }), to);
    assert.deepEqual(flight.cameraAtHop(from, to, .25, { width, easing: "linear", routePoints: route }), samples[3]);
  }
});

test("pinned Toner variants keep local patterns, OpenFreeMap endpoints, and attribution", async () => {
  const vendor = JSON.parse(fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-8688fbd.json"), "utf8"));
  const source = fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-PROVENANCE.md"), "utf8");
  assert.equal(vendor.layers.length, 37);
  assert.match(source, /8688fbd46e1918cae2e9c3d36e607b9d994badfe/);
  assert.match(source, /raw.githubusercontent.com/);
  const oldFetch = global.fetch;
  global.fetch = async (url) => ({ ok: true, json: async () => String(url) === "toner-vendor" ? vendor : ({ version: 8, glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf", sources: { omf: { type: "vector", tiles: ["https://tiles.openfreemap.org/planet/{z}/{x}/{y}.pbf"] } }, layers: [] }) });
  try {
    const styles = require(path.join(out, "styles.js"));
    assert.deepEqual(styles.remapTonerFonts({ nested: ["Nunito Regular", "Nunito SemiBold", "Noto Sans Bold Italic"] }), { nested: ["Noto Sans Regular", "Noto Sans Bold", "Noto Sans Italic"] });
    const [full, background, lines] = await Promise.all([styles.resolveOpenFreeMapStyle("toner"), styles.resolveOpenFreeMapStyle("toner-background"), styles.resolveOpenFreeMapStyle("toner-lines")]);
    assert.equal(full.layers.length, 39);
    assert.equal(background.layers.length, 13);
    assert.equal(lines.layers.length, 15);
    for (const style of [full, background, lines]) {
      assert.equal(style.sprite, undefined);
      assert.equal(style.sources.openmaptiles.attribution, "© OpenStreetMap contributors · © MapTiler");
      assert.match(style.sources.openmaptiles.tiles[0], /openfreemap/);
      assert.match(style.glyphs, /openfreemap/);
    }
    const boundaryIds = ["boundary_state", "boundary_state_z1-4", "boundary_country_z0-4", "boundary_country_z5-"];
    const lineIds = new Set(lines.layers.map((layer) => layer.id));
    const backgroundIds = new Set(background.layers.map((layer) => layer.id));
    for (const id of boundaryIds) {
      assert.ok(lineIds.has(id), `toner-lines is missing ${id}`);
      assert.ok(!backgroundIds.has(id), `toner-background unexpectedly has ${id}`);
    }
  } finally { global.fetch = oldFetch; }
});

test("withLowZoomBoundaries re-gates only the three toner boundary layers, weights stay vendored", () => {
  const vendor = JSON.parse(fs.readFileSync(path.join(root, "src/maps/vendor/maptiler-toner-8688fbd.json"), "utf8"));
  const { withLowZoomBoundaries } = require(path.join(out, "tonerBoundaries.js"));
  const byId = (layers, id) => layers.find((layer) => layer.id === id);
  const vendorState = byId(vendor.layers, "boundary_state");
  const vendorCountryLow = byId(vendor.layers, "boundary_country_z0-4");
  const vendorCountryHigh = byId(vendor.layers, "boundary_country_z5-");

  const next = withLowZoomBoundaries(vendor.layers);
  assert.equal(next.length, vendor.layers.length + 1);

  const low = byId(next, "boundary_state_z1-4");
  assert.equal(low.minzoom, 1);
  assert.equal(low.maxzoom, 5);
  assert.equal(low.paint["line-width"], 1.2);
  assert.deepEqual(low.filter, vendorState.filter);

  const countryLow = byId(next, "boundary_country_z0-4");
  assert.equal(countryLow.minzoom, 0);
  assert.deepEqual({ ...countryLow, minzoom: vendorCountryLow.minzoom }, vendorCountryLow);

  const state = byId(next, "boundary_state");
  assert.equal(state.minzoom, 5);
  assert.deepEqual({ ...state, minzoom: vendorState.minzoom }, vendorState);

  assert.deepEqual(byId(next, "boundary_country_z5-"), vendorCountryHigh);

  const nextIds = next.map((layer) => layer.id);
  const vendorIds = vendor.layers.map((layer) => layer.id);
  assert.deepEqual(nextIds.filter((id) => id !== "boundary_state_z1-4"), vendorIds);
  assert.equal(nextIds.indexOf("boundary_state_z1-4"), nextIds.indexOf("boundary_state") - 1);
});
