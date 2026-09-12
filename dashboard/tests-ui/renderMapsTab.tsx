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
    getSettings: apiFake.getSettings,
  };
});

vi.mock("../src/maps/stampOsm", () => ({
  stampOsm: vi.fn(async (blob: Blob) => blob),
}));

vi.mock("../src/maps/overlays", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/maps/overlays")>();
  return {
    ...actual,
    loadAdmin0: vi.fn(async () => null),
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
