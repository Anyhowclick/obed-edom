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
spawnSync(runtime, [path.join(root, "node_modules/typescript/bin/tsc"), "--noEmit", "false", "--noEmitOnError", "false", "--module", "commonjs", "--moduleResolution", "node", "--target", "ES2020", "--skipLibCheck", "true", "--outDir", out, path.join(root, "src/maps/flight.ts")], { cwd: root, stdio: "ignore" });
const arcModule = require(path.join(out, "flight.js"));
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

test("flight \"arc\" is identical to omitting flight", () => {
  for (const t of [0, .1, .25, .5, .75, 1]) {
    const withFlight = flight.cameraAtHop(KL, LA, t, { width: 3840, flight: "arc" });
    const omitted = flight.cameraAtHop(KL, LA, t, { width: 3840 });
    assert.deepEqual(withFlight, omitted);
  }
});

test("endpoints are exact at t=0/1 for both flight profiles, with and without a route", () => {
  const route = [{ lat: 20, lon: 20 }];
  for (const opts of [{ width: 3840 }, { width: 3840, flight: "phases" }, { width: 3840, routePoints: route }, { width: 3840, flight: "phases", routePoints: route }]) {
    assert.deepEqual(flight.cameraAtHop(KL, LA, 0, opts), KL);
    assert.deepEqual(flight.cameraAtHop(KL, LA, 1, opts), LA);
  }
});

test("KL to LA zoom dips then climbs, bottoming out well below either endpoint", () => {
  const samples = Array.from({ length: 200 }, (_, i) => flight.cameraAtHop(KL, LA, i / 199, { width: 3840, easing: "linear" }).zoom);
  let minIndex = 0;
  for (let i = 1; i < samples.length; i++) if (samples[i] < samples[minIndex]) minIndex = i;
  for (let i = 1; i <= minIndex; i++) assert.ok(samples[i] <= samples[i - 1] + 1e-9);
  for (let i = minIndex + 1; i < samples.length; i++) assert.ok(samples[i] >= samples[i - 1] - 1e-9);
  assert.ok(samples[minIndex] < Math.min(KL.zoom, LA.zoom) - 1);
});

test("arc holds constant perceived velocity; phases does not", () => {
  const fps = 30, duration = 3, n = fps * duration;
  function maxMinRatio(opts) {
    const cams = Array.from({ length: n }, (_, i) => flight.cameraAtHop(KL, LA, i / (n - 1), opts));
    const speeds = [];
    for (let i = 1; i < n - 2; i++) {
      const midZoom = (cams[i].zoom + cams[i + 1].zoom) / 2;
      speeds.push(flight.hopDistancePx(cams[i], cams[i + 1]) * 2 ** (midZoom - KL.zoom));
    }
    return Math.max(...speeds) / Math.min(...speeds);
  }
  assert.ok(maxMinRatio({ width: 3840 }) < 1.15);
  assert.ok(maxMinRatio({ width: 3840, flight: "phases", duration, flyZoom: 3 }) > 3);
});

test("omitted easing equals explicit linear for arc", () => {
  for (const t of [0, .1, .25, .5, .75, .9, 1]) {
    const omitted = flight.cameraAtHop(KL, LA, t, { width: 3840 });
    const explicit = flight.cameraAtHop(KL, LA, t, { width: 3840, easing: "linear" });
    assert.deepEqual(omitted, explicit);
  }
});

test("near-degenerate zoom-plus-pan stays numerically stable and completes exactly at f=1", () => {
  const w0 = 7680, w1 = 122880, u1 = 0.008, rho = 1.42;
  const path = arcModule.arcPath(w0, w1, u1, rho);
  const end = path.at(1);
  assert.ok(Math.abs(end.scale - 16) < 1e-9);
  assert.equal(end.pan, 1);
  const start = path.at(0);
  assert.equal(start.pan, 0);
  assert.equal(start.scale, 1);
  let prevPan = -1;
  for (const f of [0, .1, .25, .4, .5, .6, .75, .9, 1]) {
    const { pan } = path.at(f);
    assert.ok(pan >= prevPan - 1e-12);
    prevPan = pan;
  }
  assert.ok(prevPan < 1 - 1e-9 || prevPan === 1);
  assert.ok(path.at(.999).pan < 1);
});

test("pure zoom (same center) is monotone, exact at the midpoint, and keeps the center fixed", () => {
  const from = { lat: 10, lon: 10, zoom: 8, bearing: 0, pitch: 0 };
  const to = { ...from, zoom: 14 };
  let prev = from.zoom;
  for (const t of [0, .1, .25, .5, .75, .9, 1]) {
    const cam = flight.cameraAtHop(from, to, t, { width: 3840, easing: "linear" });
    assert.ok(Number.isFinite(cam.zoom));
    assert.ok(cam.zoom >= prev - 1e-9);
    prev = cam.zoom;
    assert.ok(Math.abs(cam.lat - from.lat) < 1e-9);
    assert.ok(Math.abs(cam.lon - from.lon) < 1e-9);
  }
  const mid = flight.cameraAtHop(from, to, .5, { width: 3840, easing: "linear" });
  assert.ok(Math.abs(mid.zoom - 11) < 1e-9);
});

test("cameraAtHop is symmetric under endpoint swap and time reversal", () => {
  for (const t of [.1, .25, .5, .75, .9]) {
    const forward = flight.cameraAtHop(KL, LA, t, { width: 3840, easing: "linear" });
    const backward = flight.cameraAtHop(LA, KL, 1 - t, { width: 3840, easing: "linear" });
    assert.ok(Math.abs(forward.zoom - backward.zoom) < 1e-9);
  }
});

test("curve (rho) is clamped to [0.5, 3], with NaN/undefined defaulting to 1.42", () => {
  for (const [curve, expected] of [[0.01, 0.5], [99, 3], [NaN, 1.42], [undefined, 1.42]]) {
    const cam = flight.cameraAtHop(KL, LA, .5, { width: 3840, easing: "linear", curve: expected });
    const clamped = flight.cameraAtHop(KL, LA, .5, { width: 3840, easing: "linear", curve });
    assert.ok(Math.abs(cam.zoom - clamped.zoom) < 1e-9);
    for (const value of Object.values(clamped)) assert.ok(Number.isFinite(value));
  }
});

test("bearing lerps linearly: 0 to 90 at t=.5 is 45", () => {
  const from = { lat: 0, lon: 0, zoom: 8, bearing: 0, pitch: 0 };
  const to = { ...from, bearing: 90 };
  const cam = flight.cameraAtHop(from, to, .5, { width: 3840, easing: "linear" });
  assert.ok(Math.abs(cam.bearing - 45) < 1e-9);
});

test("phases flight still honours a flyZoom plateau mid-hop", () => {
  const cam = flight.cameraAtHop(KL, LA, .5, { width: 3840, flight: "phases", duration: 1, flyZoom: 3, easeIn: 0.25, easeOut: 0.25 });
  assert.ok(Math.abs(cam.zoom - 3) < 1e-6);
});

test("phases branch matches precomputed fixtures for flyZoom/easeIn/easeOut, a route, and omitted easing", () => {
  const route = [{ lat: 20, lon: 20 }, { lat: 28, lon: -40 }];
  const ts = [0,0.15,0.3,0.5,0.7,0.85,1];
  const cases = [
    { opts: { width: 3840, duration: 3, flyZoom: 3, easeIn: 0.25, easeOut: 0.25 }, fixtures: [{"lat":3.139,"lon":101.6869,"zoom":8,"bearing":0,"pitch":0},{"lat":3.2067130132292023,"lon":101.97376213119992,"zoom":3,"bearing":0,"pitch":0},{"lat":5.460316935696255,"lon":111.53433909759997,"zoom":3,"bearing":0,"pitch":0},{"lat":19.3205331557289,"lon":171.72160000000002,"zoom":3,"bearing":0,"pitch":0},{"lat":32.10162810803637,"lon":-128.09113909760006,"zoom":3,"bearing":0,"pitch":0},{"lat":33.99599313872796,"lon":-118.5305621312,"zoom":3,"bearing":0,"pitch":0},{"lat":34.0522,"lon":-118.2437,"zoom":8,"bearing":0,"pitch":0}] },
    { opts: { width: 1920, duration: 2, flyZoom: 5, easeIn: 0.1, easeOut: 0.4, routePoints: route }, fixtures: [{"lat":3.139,"lon":101.6869,"zoom":8,"bearing":0,"pitch":0},{"lat":3.575198694576446,"lon":99.62113984119321,"zoom":5,"bearing":0,"pitch":0},{"lat":9.918003456644488,"lon":69.40939751864403,"zoom":5,"bearing":0,"pitch":0},{"lat":29.698354485657205,"lon":-61.46531663863486,"zoom":5,"bearing":0,"pitch":0},{"lat":33.89465863776589,"lon":-116.14079691254206,"zoom":5,"bearing":0,"pitch":0},{"lat":34.05219999999999,"lon":-118.24370000000002,"zoom":5.187499999999999,"bearing":0,"pitch":0},{"lat":34.0522,"lon":-118.2437,"zoom":8,"bearing":0,"pitch":0}] },
    { opts: { width: 1920, duration: 2, flyZoom: 5, easeIn: 0.1, easeOut: 0.4, routePoints: route, easing: undefined }, fixtures: [{"lat":3.139,"lon":101.6869,"zoom":8,"bearing":0,"pitch":0},{"lat":3.575198694576446,"lon":99.62113984119321,"zoom":5,"bearing":0,"pitch":0},{"lat":9.918003456644488,"lon":69.40939751864403,"zoom":5,"bearing":0,"pitch":0},{"lat":29.698354485657205,"lon":-61.46531663863486,"zoom":5,"bearing":0,"pitch":0},{"lat":33.89465863776589,"lon":-116.14079691254206,"zoom":5,"bearing":0,"pitch":0},{"lat":34.05219999999999,"lon":-118.24370000000002,"zoom":5.187499999999999,"bearing":0,"pitch":0},{"lat":34.0522,"lon":-118.2437,"zoom":8,"bearing":0,"pitch":0}] },
  ];
  for (const { opts, fixtures } of cases) {
    ts.forEach((t, i) => {
      const phases = flight.cameraAtHop(KL, LA, t, { ...opts, flight: "phases" });
      assert.deepEqual(phases, fixtures[i]);
    });
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

    const byId = (layers, id) => layers.find((layer) => layer.id === id);
    const vendorPrimary = byId(vendor.layers, "road_primary");
    for (const style of [full, lines]) {
      const primary = byId(style.layers, "road_primary");
      assert.deepEqual(
        primary.paint["line-width"].stops,
        vendorPrimary.paint["line-width"].stops.map(([z, w]) => [z, w * 0.55]),
      );
    }
    for (const id of boundaryIds) {
      assert.deepEqual(byId(lines.layers, id).paint["line-width"], byId(full.layers, id).paint["line-width"]);
      const vendorBoundary = byId(vendor.layers, id);
      if (vendorBoundary && vendorBoundary.paint) {
        assert.deepEqual(byId(full.layers, id).paint["line-width"], vendorBoundary.paint["line-width"]);
      }
    }
  } finally { global.fetch = oldFetch; }
});

test("thinLineWidths scales non-boundary line widths across all paint shapes", () => {
  const { thinLineWidths } = require(path.join(out, "tonerLines.js"));
  const layers = [
    { id: "a", type: "line", paint: { "line-width": 4 } },
    { id: "b", type: "line", paint: { "line-width": { base: 1.3, stops: [[5, 1], [14, 5]] } } },
    { id: "c", type: "line", paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1, 14, 5] } },
    { id: "d", type: "line", paint: {} },
    { id: "e", type: "fill", paint: { "fill-color": "#000" } },
  ];
  const scaled = thinLineWidths(layers, 0.55);
  assert.equal(scaled[0].paint["line-width"], 4 * 0.55);
  assert.deepEqual(scaled[1].paint["line-width"], { base: 1.3, stops: [[5, 0.55], [14, 2.75]] });
  assert.deepEqual(scaled[2].paint["line-width"], ["*", 0.55, ["interpolate", ["linear"], ["zoom"], 5, 1, 14, 5]]);
  assert.equal(scaled[3].paint["line-width"], 0.55);
  assert.deepEqual(scaled[4], layers[4]);
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
  assert.equal(low.minzoom, 4);
  assert.equal(low.maxzoom, 5);
  assert.equal(low.paint["line-width"], 1.2);
  assert.equal(low.paint["line-dasharray"], undefined);
  assert.deepEqual(low.filter, vendorState.filter);

  const countryLow = byId(next, "boundary_country_z0-4");
  assert.equal(countryLow.minzoom, 0);
  assert.equal(countryLow.maxzoom, 5);
  assert.deepEqual({ ...countryLow, minzoom: vendorCountryLow.minzoom }, vendorCountryLow);

  const state = byId(next, "boundary_state");
  assert.equal(state.minzoom, 5);
  assert.equal(state.paint["line-dasharray"], undefined);
  assert.ok(!("line-dasharray" in state.paint));
  assert.deepEqual(
    { ...state, minzoom: vendorState.minzoom, paint: { ...state.paint, "line-dasharray": vendorState.paint["line-dasharray"] } },
    vendorState
  );

  const countryHigh = byId(next, "boundary_country_z5-");
  assert.equal(countryHigh.minzoom, 5);
  assert.deepEqual({ ...countryHigh, minzoom: vendorCountryHigh.minzoom }, vendorCountryHigh);

  const nextIds = next.map((layer) => layer.id);
  const vendorIds = vendor.layers.map((layer) => layer.id);
  assert.deepEqual(nextIds.filter((id) => id !== "boundary_state_z1-4"), vendorIds);
  assert.equal(nextIds.indexOf("boundary_state_z1-4"), nextIds.indexOf("boundary_state") - 1);

  const previewOffset = -2.94;
  const preview = withLowZoomBoundaries(vendor.layers, previewOffset);
  const lowPreview = byId(preview, "boundary_state_z1-4");
  const statePreview = byId(preview, "boundary_state");
  const countryLowPreview = byId(preview, "boundary_country_z0-4");
  const countryHighPreview = byId(preview, "boundary_country_z5-");
  assert.ok(Math.abs(lowPreview.minzoom - 1.06) < 1e-9);
  assert.ok(Math.abs(lowPreview.maxzoom - 2.06) < 1e-9);
  assert.ok(Math.abs(statePreview.minzoom - 2.06) < 1e-9);
  assert.equal(countryLowPreview.minzoom, 0);
  assert.ok(Math.abs(countryLowPreview.maxzoom - 2.06) < 1e-9);
  assert.ok(Math.abs(countryHighPreview.minzoom - 2.06) < 1e-9);

  const clamped = withLowZoomBoundaries(vendor.layers, -6);
  assert.equal(byId(clamped, "boundary_state_z1-4").minzoom, 0);
  assert.equal(byId(clamped, "boundary_state_z1-4").maxzoom, 0);
  assert.equal(byId(clamped, "boundary_country_z0-4").minzoom, 0);
  assert.equal(byId(clamped, "boundary_country_z0-4").maxzoom, 0);
  assert.equal(byId(clamped, "boundary_country_z5-").minzoom, 0);
});
