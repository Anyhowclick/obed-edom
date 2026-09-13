const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const out = fs.mkdtempSync(path.join(os.tmpdir(), "maps-overlays-admin1-race-"));
const runtime = process.env.CODEX_NODE || process.execPath;
const compile = spawnSync(runtime, [
  path.join(root, "node_modules/typescript/bin/tsc"), "--module", "commonjs", "--target", "ES2020", "--skipLibCheck", "true",
  "--outDir", out, path.join(root, "src/maps/overlays.ts"), path.join(root, "src/maps/adminSync.ts"),
], { cwd: root, encoding: "utf8" });
assert.equal(compile.status, 0, compile.stderr || compile.stdout);
const { ensureAdmin0Highlights, syncAdmin1Source, applyHighlights, applyAdmin1Highlights, applyIsolate, addOverlays } = require(path.join(out, "overlays.js"));
const { AdminSyncGate } = require(path.join(out, "adminSync.js"));

/** A fake MapLibre map recording every mutation `ensureAdmin0Highlights`/`syncAdmin1Source`
 * make, so a test can assert none of them ran once a request has been superseded. */
function fakeMap() {
  const sources = new Map();
  const layers = new Map();
  const calls = [];
  return {
    calls,
    getSource: (id) => sources.get(id),
    addSource: (id, spec) => {
      calls.push(["addSource", id]);
      sources.set(id, { ...spec, setData: (data) => calls.push(["setData", id, data]) });
    },
    removeSource: (id) => {
      calls.push(["removeSource", id]);
      sources.delete(id);
    },
    getLayer: (id) => layers.get(id),
    addLayer: (spec) => {
      calls.push(["addLayer", spec.id]);
      layers.set(spec.id, spec);
    },
    removeLayer: (id) => {
      calls.push(["removeLayer", id]);
      layers.delete(id);
    },
    setPaintProperty: (id, prop, value) => calls.push(["setPaintProperty", id, prop, value]),
    setLayoutProperty: (id, prop, value) => calls.push(["setLayoutProperty", id, prop, value]),
    setFeatureState: (target, state) => calls.push(["setFeatureState", target, state]),
    getStyle: () => ({ layers: [] }),
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

/** Controllable fetch: admin0 resolves immediately (seeded once, shared by every test in this
 * file); admin1/<code> resolves only when the test releases that code's deferred promise. */
const admin1Gates = new Map();
function gateFor(code) {
  const wanted = code.toUpperCase();
  let gate = admin1Gates.get(wanted);
  if (!gate) {
    gate = deferred();
    admin1Gates.set(wanted, gate);
  }
  return gate;
}
global.fetch = async (url) => {
  if (url === "/api/maps/ne/admin0") {
    return { ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) };
  }
  const match = /\/api\/maps\/ne\/admin1\/([A-Z]+)$/.exec(url);
  if (match) {
    await gateFor(match[1]).promise;
    return { ok: true, json: async () => ({ type: "FeatureCollection", features: [{ properties: { adm0_a3: match[1], adm1_code: `${match[1]}-1` }, geometry: null }] }) };
  }
  return { ok: false, json: async () => null };
};

test("removal during load: an isCurrent that goes false before the admin1 load resolves stops every post-await mutation", async () => {
  const map = fakeMap();
  let current = true;
  const done = ensureAdmin0Highlights(map, ["A1:RAA-1"], "positron", undefined, 0, [], () => current);
  current = false; // e.g. the highlight was cleared while RAA's admin-1 was still loading
  gateFor("RAA").resolve();
  await done;

  assert.deepEqual(map.calls, [], "no source/layer/paint mutation may run once isCurrent() is false");
});

test("replacement during load: a superseded request's admin1 load must not resurrect the old selection", async () => {
  const map = fakeMap();
  let generation = 0;
  const gen1 = ++generation;
  const isCurrent1 = () => generation === gen1;
  const first = ensureAdmin0Highlights(map, ["A1:RBB-1"], "positron", undefined, 0, [], isCurrent1);

  const gen2 = ++generation; // a newer selection supersedes the first before RBB resolves
  const isCurrent2 = () => generation === gen2;
  const second = ensureAdmin0Highlights(map, ["A1:RCC-1"], "positron", undefined, 0, [], isCurrent2);

  gateFor("RCC").resolve();
  await second;
  const afterSecond = map.calls.slice();
  assert.ok(afterSecond.some((c) => c[0] === "addSource" && c[1] === "admin0"), "the current request must apply its own mutations");

  gateFor("RBB").resolve();
  await first;
  assert.deepEqual(map.calls, afterSecond, "the superseded first request must add nothing once it finally resolves");
});

test("mode change during load: isolate mode flips off before the admin1 load resolves, so applyIsolate must not run stale", async () => {
  const map = fakeMap();
  let current = true;
  const done = ensureAdmin0Highlights(map, ["A1:RDD-1"], "positron", { mode: "darken", strength: 0.6 }, 0, [], () => current);
  current = false;
  gateFor("RDD").resolve();
  await done;

  assert.ok(!map.calls.some((c) => c[0] === "addLayer" && c[1] === "isolate-fill"), "isolate must not be applied for a superseded mode");
});

test("syncAdmin1Source is generation-guarded the same way: a superseded camera sync adds nothing", async () => {
  const map = fakeMap();
  let current = true;
  const done = syncAdmin1Source(map, ["REE"], () => current);
  current = false;
  gateFor("REE").resolve();
  await done;

  assert.deepEqual(map.calls, []);
});

test("syncAdmin1Source still merges the admin1 source when the request is current", async () => {
  const map = fakeMap();
  const done = syncAdmin1Source(map, ["RFF"]);
  gateFor("RFF").resolve();
  await done;

  assert.ok(map.calls.some((c) => c[0] === "addSource" && c[1] === "admin1"));
});

test("camera sync supersedes a highlight load: syncRegionCamera's own continuation must still apply highlights/isolate", async () => {
  const map = fakeMap();
  // Warm up admin0 (no admin1 needed) so the source/layers already exist, as they would by the
  // time a real map has been panned once.
  await ensureAdmin0Highlights(map, [], "positron", undefined, 0, [], () => true);

  let generation = 0;
  const gen1 = ++generation;
  const isCurrent1 = () => generation === gen1;
  const highlightLoad = ensureAdmin0Highlights(
    map,
    ["A1:RGG-1"],
    "positron",
    { mode: "darken", strength: 0.6 },
    0,
    [],
    isCurrent1
  );

  // The camera pans to an unrelated country (RHH) while RGG's admin1 fetch is still in flight,
  // superseding the highlight effect's generation the way `syncRegionCamera` does.
  const gen2 = ++generation;
  const isCurrent2 = () => generation === gen2;
  const cameraSync = syncAdmin1Source(map, ["RHH"], isCurrent2).then(() => {
    if (!isCurrent2()) return;
    applyHighlights(map, ["A1:RGG-1"]);
    applyAdmin1Highlights(map, ["A1:RGG-1"]);
    applyIsolate(map, ["A1:RGG-1"], { mode: "darken", strength: 0.6 });
  });
  gateFor("RHH").resolve();
  await cameraSync;

  assert.ok(
    map.calls.some((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill"),
    "the camera sync's own continuation must apply the admin-1 highlight paint, since the superseded highlight effect never will"
  );

  const afterCamera = map.calls.slice();
  gateFor("RGG").resolve();
  await highlightLoad;
  assert.deepEqual(map.calls, afterCamera, "the superseded highlight load must add nothing once it finally resolves");
});

/** MapView's coordination in miniature: `paintOverlays` owns the map for the length of a style
 * load, and a highlight effect arriving meanwhile defers to the replay it triggers. */
function fakeMapView() {
  const map = fakeMap();
  const gate = new AdminSyncGate();
  const state = { map, gate, styleReady: false, highlights: [], replays: 0, cameraCountries: [], warned: [], styleToken: null };

  /** MapView's `takeStyleToken`: the style-load token is acquired by whoever calls `setStyle`,
   * so the window between `setStyle` and `style.load` is already owned by the gate. */
  state.takeStyleToken = () => {
    const token = state.styleToken;
    state.styleToken = null;
    if (token !== null) return token;
    state.styleReady = false;
    return gate.beginStyleLoad();
  };

  /** The style-picker effect: acquires the token before `setStyle`, and only later does the
   * `style.load` event drive `paintOverlays`. */
  state.setStyle = () => {
    state.styleReady = false;
    state.styleToken = gate.beginStyleLoad();
  };

  state.styleLoadEvent = () => state.paintOverlays(state.takeStyleToken());

  state.overlayBuild = (isCurrent) =>
    addOverlays(map, state.highlights, [], null, "positron", false, undefined, 1, undefined, [], isCurrent);

  state.paintOverlays = (token) => {
    const generation = token === undefined ? state.takeStyleToken() : token;
    const isCurrent = () => gate.isCurrent(generation);
    let replayed;
    return state.overlayBuild(isCurrent)
      .then(() => {
        if (isCurrent()) state.styleReady = true;
      })
      .catch((err) => state.warned.push(String(err && err.message ? err.message : err)))
      .finally(() => {
        if (gate.endStyleLoad(generation)) {
          state.replays += 1;
          replayed = state.highlightEffect();
        }
      })
      .then(() => replayed);
  };

  state.highlightEffect = () => {
    if (!map.getSource("admin0")) return Promise.resolve();
    const generation = gate.beginSync();
    if (generation === null) return Promise.resolve();
    const isCurrent = () => gate.isCurrent(generation);
    const highlights = state.highlights;
    return gate.track(ensureAdmin0Highlights(map, highlights, "positron", undefined, 0, [], isCurrent));
  };

  /** `waitUntilIdle` in miniature: the style/tile readiness check plus `gate.settled()`. */
  state.waitUntilIdle = () => {
    const settled = { done: false };
    settled.promise = (async () => {
      while (!state.styleReady) await new Promise((r) => setTimeout(r, 1));
      await gate.settled();
      settled.done = true;
    })();
    return settled;
  };

  /** `syncRegionCamera` in miniature: its admin0/codes guards sit above `beginSync`, so a pan
   * that has nothing to sync must not consume a generation. */
  state.cameraSync = () => {
    if (!map.getSource("admin0")) return Promise.resolve();
    const codes = state.cameraCountries;
    if (!codes.length) return Promise.resolve();
    const generation = gate.beginSync();
    if (generation === null) return Promise.resolve();
    const isCurrent = () => gate.isCurrent(generation);
    return gate.track(syncAdmin1Source(map, codes, isCurrent).then(() => {
      if (!isCurrent()) return;
      applyHighlights(map, state.highlights);
      applyAdmin1Highlights(map, state.highlights);
      applyIsolate(map, state.highlights, undefined);
    }));
  };

  return state;
}

test("paintOverlays vs the highlight effect: a highlight change during a style load defers, then replays, and never wedges styleReady", async () => {
  const view = fakeMapView();
  // A first style load, so admin0 exists the way it does for a style-picker switch.
  await view.paintOverlays();
  const warmCalls = view.map.calls.length;
  view.highlights = ["A1:RII-1"];
  const painting = view.paintOverlays();

  // The operator picks a different region while the style load is still fetching RII's admin-1.
  view.highlights = ["A1:RJJ-1"];
  const deferred1 = view.highlightEffect();
  assert.equal(view.map.calls.length, warmCalls, "the highlight effect must not touch the map mid style load");

  gateFor("RII").resolve();
  gateFor("RJJ").resolve();
  await painting;
  await deferred1;

  assert.equal(view.styleReady, true, "the style load must still mark the map ready");
  assert.equal(view.replays, 1, "the deferred highlight work must be replayed once");
  const paints = view.map.calls.filter((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill");
  assert.ok(paints.length, "the replay must repaint the admin-1 fill");
  assert.ok(
    JSON.stringify(paints[paints.length - 1][3]).includes("RJJ-1"),
    "the last admin-1 paint must describe the newest selection"
  );
});

test("paintOverlays vs paintOverlays: a superseded style load leaves styleReady to the newer one instead of wedging it false", async () => {
  const view = fakeMapView();
  view.highlights = ["A1:RKK-1"];
  const first = view.paintOverlays();
  view.highlights = ["A1:RLL-1"];
  const second = view.paintOverlays();

  gateFor("RLL").resolve();
  await second;
  assert.equal(view.styleReady, true);

  gateFor("RKK").resolve();
  await first;
  assert.equal(view.styleReady, true, "the older load must neither clear styleReady nor block the newer one");

  // The gate is free again, so the next highlight effect runs immediately rather than deferring.
  assert.notEqual(view.gate.beginSync(), null);
});

test("a rejected overlay build still releases the gate: beginSync stays open and the next highlight effect reaches the map", async () => {
  const view = fakeMapView();
  await view.paintOverlays();
  view.overlayBuild = () => Promise.reject(new Error("landmark images"));
  await view.paintOverlays();

  assert.equal(view.styleReady, false);
  assert.deepEqual(view.warned, ["landmark images"]);
  assert.notEqual(view.gate.beginSync(), null, "a rejected style load must not wedge the gate shut");

  view.highlights = ["A1:RMM-1"];
  const effect = view.highlightEffect();
  gateFor("RMM").resolve();
  await effect;
  assert.ok(
    view.map.calls.some((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill"),
    "the highlight effect must still reach the map after a rejected overlay build"
  );
});

test("a camera sync with no countries under the camera must not discard an in-flight highlight load", async () => {
  const view = fakeMapView();
  await view.paintOverlays();

  view.highlights = ["A1:RNN-1"];
  const effect = view.highlightEffect();

  // The operator pans until the camera centre is over ocean: no countries, nothing to sync.
  view.cameraCountries = [];
  await view.cameraSync();

  gateFor("RNN").resolve();
  await effect;
  const paints = view.map.calls.filter((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill");
  assert.ok(paints.length, "the in-flight highlight load must still apply");
  assert.ok(JSON.stringify(paints[paints.length - 1][3]).includes("RNN-1"));
});

test("setStyle→style.load interval: a highlight request arriving before style.load is deferred and replayed", async () => {
  const view = fakeMapView();
  await view.paintOverlays();
  const warmCalls = view.map.calls.length;

  // The style picker switches style: the token is taken before `setStyle`, so the map is owned
  // by the gate for the whole interval before `style.load` fires.
  view.setStyle();
  view.highlights = ["A1:RPP-1"];
  const deferredEffect = view.highlightEffect();
  assert.equal(view.map.calls.length, warmCalls, "no mutation may reach the half-loaded style");

  // `style.load` finally arrives and paints with the pre-acquired generation.
  const painting = view.styleLoadEvent();
  gateFor("RPP").resolve();
  await painting;
  await deferredEffect;

  assert.equal(view.replays, 1, "the highlight request from the setStyle interval must be replayed");
  assert.equal(view.styleReady, true);
  const paints = view.map.calls.filter((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill");
  assert.ok(paints.length && JSON.stringify(paints[paints.length - 1][3]).includes("RPP-1"));
});

test("waitUntilIdle stays pending until a deferred admin-1 fetch and its replay finish", async () => {
  const view = fakeMapView();
  await view.paintOverlays();

  view.highlights = ["A1:RQQ-1"];
  view.setStyle();
  const painting = view.styleLoadEvent();
  // The operator picks a different region while the new style is still loading.
  view.highlights = ["A1:RTT-1"];
  view.highlightEffect();

  const idle = view.waitUntilIdle();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(idle.done, false, "capture must not be ready while the style load is in flight");

  gateFor("RQQ").resolve();
  while (!view.styleReady) await new Promise((r) => setTimeout(r, 1));
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(idle.done, false, "styleReady alone must not release the capture while the replay runs");

  gateFor("RTT").resolve();
  await painting;
  await idle.promise;
  assert.equal(idle.done, true);
  const paints = view.map.calls.filter((c) => c[0] === "setPaintProperty" && c[1] === "admin1-fill");
  assert.ok(JSON.stringify(paints[paints.length - 1][3]).includes("RTT-1"), "the capture waits for the newest selection to be painted");
});

test("waitUntilIdle stays pending through an ordinary admin-1 sync with no style load", async () => {
  const view = fakeMapView();
  await view.paintOverlays();

  view.highlights = ["A1:RSS-1"];
  const effect = view.highlightEffect();
  const idle = view.waitUntilIdle();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(idle.done, false, "an in-flight admin-1 fetch must hold the capture back");

  gateFor("RSS").resolve();
  await effect;
  await idle.promise;
  assert.equal(idle.done, true);
});
