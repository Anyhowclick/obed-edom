import { afterEach, describe, expect, it, vi } from "vitest";
import { createBorderlandsInkLayer, waitForBorderlandsInk } from "../src/maps/borderlandsInk";

type Handler = (...args: unknown[]) => void;

function fakeGl(): WebGL2RenderingContext {
  return {
    VERTEX_SHADER: 1,
    FRAGMENT_SHADER: 2,
    createShader: () => null,
  } as unknown as WebGL2RenderingContext;
}

function createFakeMap(features: unknown[] = []) {
  const listeners = new Map<string, Set<Handler>>();
  const map = {
    zoom: 16.2,
    center: { lng: 103.86, lat: 1.29 },
    bearing: 0,
    pitch: 45,
    tilesLoaded: true,
    features,
    _layer: undefined as unknown,
    getZoom: () => map.zoom,
    getCenter: () => map.center,
    getBearing: () => map.bearing,
    getPitch: () => map.pitch,
    getBounds: () => ({
      getWest: () => 103.85,
      getSouth: () => 1.28,
      getEast: () => 103.87,
      getNorth: () => 1.30,
    }),
    getCanvas: () => ({ clientWidth: 800, clientHeight: 400, width: 800, height: 400 }),
    getPixelRatio: () => 1,
    areTilesLoaded: () => map.tilesLoaded,
    getLayer: (id: string) => (id === "building-3d" ? { id } : id === "borderlands-ink" ? { implementation: map._layer } : undefined),
    getLayoutProperty: (id: string, key: string) => (id === "building-3d" && key === "visibility" ? "visible" : undefined),
    getStyle: () => ({
      layers: [{ id: "building-3d", type: "fill-extrusion", source: "openmaptiles", "source-layer": "building", minzoom: 14 }],
    }),
    getSource: () => ({ loaded: () => true }),
    querySourceFeatures: () => map.features,
    triggerRepaint: vi.fn(),
    addLayer: () => undefined,
    removeLayer: () => undefined,
    on: (name: string, handler: Handler) => {
      const set = listeners.get(name) || new Set();
      set.add(handler);
      listeners.set(name, set);
    },
    off: (name: string, handler: Handler) => listeners.get(name)?.delete(handler),
    once: (name: string, handler: Handler) => {
      const wrap: Handler = (...args) => {
        map.off(name, wrap);
        handler(...args);
      };
      map.on(name, wrap);
    },
    emit: (name: string, payload?: unknown) => {
      for (const handler of [...(listeners.get(name) || [])]) handler(payload);
    },
  };
  return map;
}

const square = {
  id: 1,
  geometry: {
    type: "Polygon",
    coordinates: [[
      [103.86, 1.29],
      [103.8602, 1.29],
      [103.8602, 1.2902],
      [103.86, 1.2902],
      [103.86, 1.29],
    ]],
  },
  properties: { render_height: 20, render_min_height: 0 },
};

describe("borderlands ink lifecycle", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("cancels a pending debounce when a new gesture starts", () => {
    vi.useFakeTimers();
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.onAdd?.(map as never, fakeGl());
    map.emit("moveend");
    vi.advanceTimersByTime(40);
    map.emit("movestart");
    vi.advanceTimersByTime(80);
    const committed = layer.committedGeneration();
    map.emit("moveend");
    vi.advanceTimersByTime(80);
    expect(layer.committedGeneration()).toBeGreaterThan(committed);
  });

  it("flush reuses an unchanged current mesh", () => {
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    const first = layer.committedGeneration();
    const firstCount = layer.vertexCount;
    layer.flush();
    expect(layer.committedGeneration()).toBe(first);
    expect(layer.vertexCount).toBe(firstCount);
  });

  it("authoritative empty views clear the mesh", () => {
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    expect(layer.vertexCount).toBeGreaterThan(0);
    map.features = [];
    map.center = { lng: 104.2, lat: 1.29 };
    layer.flush();
    expect(layer.vertexCount).toBe(0);
  });

  it("wait times out instead of succeeding after 100 ms", async () => {
    vi.useFakeTimers();
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    const pending = layer.waitUntilRendered({ deadlineMs: 40 });
    const assertion = expect(pending).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(40);
    await assertion;
  });

  it("wait resolves only after the requested generation is acknowledged", async () => {
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    const pending = layer.waitUntilRendered({ deadlineMs: 1000 });
    layer.acknowledgeRender();
    await pending;
    expect(layer.renderedGeneration()).toBe(layer.committedGeneration());
  });

  it("cancellation rejects and cleans waiters", async () => {
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    let cancelled = false;
    const pending = layer.waitUntilRendered({ isCancelled: () => cancelled, deadlineMs: 1000 });
    cancelled = true;
    await expect(pending).rejects.toThrow(/cancelled/);
  });

  it("below building minzoom does not idle-loop rebuilds", () => {
    vi.useFakeTimers();
    const map = createFakeMap([square]);
    map.zoom = 12;
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.onAdd?.(map as never, fakeGl());
    layer.flush();
    const requested = layer.requestedGeneration();
    const committed = layer.committedGeneration();
    expect(layer.vertexCount).toBe(0);
    map.emit("idle");
    vi.advanceTimersByTime(200);
    map.emit("idle");
    vi.advanceTimersByTime(200);
    expect(layer.requestedGeneration()).toBe(requested);
    expect(layer.committedGeneration()).toBe(committed);
    expect(map.triggerRepaint).toHaveBeenCalled();
  });

  it("waitForBorderlandsInk returns immediately when the layer is absent", async () => {
    const map = createFakeMap();
    await expect(waitForBorderlandsInk(map as never)).resolves.toBeUndefined();
  });

  it("style removal fails outstanding waiters", async () => {
    const map = createFakeMap([square]);
    const layer = createBorderlandsInkLayer(map as never);
    map._layer = layer;
    layer.flush();
    const pending = layer.waitUntilRendered({ deadlineMs: 1000 });
    layer.onRemove?.(map as never, { deleteProgram() {}, deleteBuffer() {}, deleteVertexArray() {} } as never);
    await expect(pending).rejects.toThrow(/removed/);
  });
});
