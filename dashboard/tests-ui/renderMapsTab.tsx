import { act, render } from "@testing-library/react";
import { vi } from "vitest";
import type { Job } from "../src/api";
import { RunNavContext } from "../src/nav";
import { MapsTab } from "../src/tabs/MapsTab";
import { createMapViewFake, type MapViewFake } from "./fakes/mapView";
import { makeJob } from "./fakes/doc";
import { getJob, mapsApiScript, resetMapsApiScript } from "./fakes/mapsApi";

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  const apiFake = await import("./fakes/mapsApi");
  return {
    ...actual,
    saveMapsState: apiFake.saveMapsState,
    postMapsPng: apiFake.postMapsPng,
    renameJob: apiFake.renameJob,
    getJob: apiFake.getJob,
    bootstrapMapsRows: apiFake.bootstrapMapsRows,
    pollJob: apiFake.pollJob,
    fetchMapsExportPlan: apiFake.fetchMapsExportPlan,
    exportMaps: apiFake.exportMaps,
    getSettings: apiFake.getSettings,
    cancelMapsExport: apiFake.cancelMapsExport,
    planMapsTiles: apiFake.planMapsTiles,
    prefetchMapsTiles: apiFake.prefetchMapsTiles,
  };
});

vi.mock("../src/maps/stampOsm", () => ({
  stampOsm: vi.fn(async (blob: Blob) => blob),
}));

const admin1Stubs = vi.hoisted(() => ({
  loadAdmin0: vi.fn(async () => null as { features: unknown[] } | null),
  loadAdmin1: vi.fn(async (code: string) => ({
    type: "FeatureCollection" as const,
    features: [{ properties: { adm0_a3: code, adm1_code: `${code}-1186`, name: "Sabah", type_en: "State" }, geometry: null }],
  })),
  admin1Name: vi.fn((id: string) => (id === "A1:MYS-1186" ? "Sabah" : id)),
}));

export const loadAdmin0Stub = admin1Stubs.loadAdmin0;
export const loadAdmin1Stub = admin1Stubs.loadAdmin1;

vi.mock("../src/maps/overlays", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/maps/overlays")>();
  return {
    ...actual,
    loadAdmin0: admin1Stubs.loadAdmin0,
    loadAdmin1: admin1Stubs.loadAdmin1,
    admin1Name: admin1Stubs.admin1Name,
  };
});

vi.mock("../src/prefs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/prefs")>();
  return {
    ...actual,
    useDefaultExportDir: () => "",
  };
});

let currentMapFake: MapViewFake | null = null;

vi.mock("../src/maps/MapView", () => ({
  get MapView() {
    return currentMapFake!.MapView;
  },
}));

export async function renderMapsTab(opts: { job?: Job } = {}) {
  resetMapsApiScript();
  const job = opts.job ?? makeJob();
  mapsApiScript.getJob.resolve(job);
  getJob.mockClear();

  const mapFake = createMapViewFake();
  currentMapFake = mapFake;

  const utils = render(
    <RunNavContext.Provider value={{ openInFeature: () => undefined, clearOpenRun: () => undefined, openRun: { feature: "maps", jobId: job.id } }}>
      <MapsTab />
    </RunNavContext.Provider>
  );

  await act(async () => {
    await Promise.resolve();
  });

  return { ...utils, mapFake, job };
}

export async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

export async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
