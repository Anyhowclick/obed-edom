import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MapsExportPlan } from "../src/api";
import { flushMicrotasks, renderMapsTab, tick } from "./renderMapsTab";
import { MAPS_SAVE_IDLE_MS } from "../src/maps/saveQueue";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeCamera, makeJob, makeSlide } from "./fakes/doc";

const captureExportRaster = vi.fn(async (..._args: unknown[]) => new Blob(["still"]));
const captureIsolatePair = vi.fn(async (..._args: unknown[]) => null);
vi.mock("../src/maps/captureExport", () => ({
  captureExportRaster: (...args: unknown[]) => captureExportRaster(...args),
  captureIsolatePair: (...args: unknown[]) => captureIsolatePair(...args),
}));

const captureFlyFrames = vi.fn(async (..._args: unknown[]) => 1);
vi.mock("../src/maps/captureFly", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/maps/captureFly")>();
  return {
    ...actual,
    captureFlyFrames: (...args: unknown[]) => captureFlyFrames(...args),
  };
});

beforeEach(() => {
  vi.useFakeTimers();
  captureExportRaster.mockClear();
  captureFlyFrames.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("export flow with credits toggled on", () => {
  it("sends credits in the export request body and passes stamp: false to stills and fly frames", async () => {
    const camA = makeCamera({ lat: 1.3, lon: 103.8 });
    const camB = makeCamera({ lat: 1.35, lon: 103.85 });
    const slideA = makeSlide({ id: "s1", camera: camA });
    const slideB = makeSlide({ id: "s2", camera: camB });
    const job = makeJob({
      result: {
        defaultStyle: "positron",
        crop: "center+cg",
        exportLw: true,
        exportCg: false,
        exportDsk: false,
        hiddenLayers: [],
        cachedCountries: [],
        attribution: "stamp",
        assets: [],
        slides: [slideA, slideB],
        links: [],
        stateRevision: 1,
      },
    });

    const plan: MapsExportPlan = {
      links: [
        { from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: true },
      ],
      stills: [
        { slideId: "s1", style: "positron", camera: camA, highlights: [] },
      ],
      plates: [],
    };
    await renderMapsTab({ job });
    mapsApiScript.fetchMapsExportPlan.resolve(plan);

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    const checkbox = screen.getByRole("checkbox", { name: "Credits slide instead of stamped attribution" });
    await act(async () => {
      fireEvent.click(checkbox);
    });
    await tick(MAPS_SAVE_IDLE_MS);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    for (let i = 0; i < 20; i++) {
      await flushMicrotasks();
    }

    expect(mapsApiScript.exportMaps.calls.length).toBeGreaterThan(0);
    const exportCall = mapsApiScript.exportMaps.calls[mapsApiScript.exportMaps.calls.length - 1];
    expect(exportCall.body?.credits).toBeDefined();
    expect(exportCall.body?.credits?.length).toBeGreaterThan(0);

    expect(captureExportRaster).toHaveBeenCalled();
    for (const call of captureExportRaster.mock.calls) {
      expect((call[0] as unknown as { stamp?: boolean }).stamp).toBe(false);
    }

    expect(captureFlyFrames).toHaveBeenCalled();
    for (const call of captureFlyFrames.mock.calls) {
      expect((call[0] as unknown as { stamp?: boolean }).stamp).toBe(false);
    }
  });
});
