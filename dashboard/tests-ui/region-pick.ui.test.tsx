import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushMicrotasks, loadAdmin0Stub, loadAdmin1Stub, renderMapsTab, tick } from "./renderMapsTab";
import { MAPS_PICK_MODE_KEY } from "../src/prefs";
import { makeCamera, makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { MAPS_SAVE_IDLE_MS } from "../src/maps/saveQueue";
import { mapsApiScript } from "./fakes/mapsApi";
import type { MapsIsolate } from "../src/maps/types";

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  loadAdmin1Stub.mockClear();
  loadAdmin0Stub.mockReset();
  loadAdmin0Stub.mockResolvedValue(null);
});

afterEach(() => {
  vi.useRealTimers();
});

async function openProperties() {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
  });
}

describe("Pick: Countries | Regions", () => {
  it("renders the segmented control and persists the choice to sessionStorage", async () => {
    await renderMapsTab();
    await openProperties();

    expect(screen.getByText("Selected regions")).toBeInTheDocument();
    const regions = screen.getByRole("tab", { name: "Regions" });
    const countries = screen.getByRole("tab", { name: "Countries" });
    expect(countries).toHaveClass("on");
    expect(regions).not.toHaveClass("on");

    await act(async () => {
      fireEvent.click(regions);
    });

    expect(screen.getByRole("tab", { name: "Regions" })).toHaveClass("on");
    expect(sessionStorage.getItem(MAPS_PICK_MODE_KEY)).toBe("1");
  });

  it("toggling a region adds A1:<code> to the slide and the chip shows its name", async () => {
    const { mapFake } = await renderMapsTab();
    await openProperties();

    await act(async () => {
      mapFake.emit.toggleRegion("MYS-1186");
    });

    const props = mapFake.getLatestProps();
    expect(props.highlights).toEqual(["A1:MYS-1186"]);

    const chip = screen.getByRole("button", { name: /Sabah/ });
    expect(chip.closest(".maps-hl-chip")).toBeTruthy();

    await act(async () => {
      fireEvent.click(chip);
    });

    expect(mapFake.getLatestProps().highlights).toEqual(["A1:MYS-1186"]);
    expect(screen.getByText("Sabah").closest(".maps-name-pill")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove highlight" }));
    });

    expect(mapFake.getLatestProps().highlights).toEqual([]);
  });

  it("region picking is off until the operator turns it on", async () => {
    const { mapFake } = await renderMapsTab();
    expect(mapFake.getLatestProps().pickRegions).toBe(false);

    await openProperties();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Regions" }));
    });

    expect(mapFake.getLatestProps().pickRegions).toBe(true);
  });

  it("does not flash the pan-hint when switching to Regions over a country", async () => {
    const { mapFake } = await renderMapsTab();
    mapFake.setRegionCountries(["MYS"]);
    await openProperties();

    const panHint = "Pan a country into view to pick its regions.";
    let sawPanHint = false;
    const observer = new MutationObserver(() => {
      if (document.body.textContent?.includes(panHint)) sawPanHint = true;
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Regions" }));
    });
    observer.disconnect();

    expect(sawPanHint).toBe(false);
    expect(screen.queryByText(panHint)).not.toBeInTheDocument();
  });

  it("shows the pan-hint after a probe finds no country in view", async () => {
    const { mapFake } = await renderMapsTab();
    mapFake.setRegionCountries([]);
    await openProperties();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Regions" }));
    });

    expect(screen.getByText("Pan a country into view to pick its regions.")).toBeInTheDocument();
  });

  it("checking a country in the cache picker asks the server for its regions", async () => {
    loadAdmin0Stub.mockResolvedValue({
      features: [{ properties: { ADM0_A3: "MYS", NAME: "Malaysia" } }],
    });
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Countries to cache" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /Malaysia/ }));
    });

    expect(loadAdmin1Stub).toHaveBeenCalledWith("MYS");
  });

  it("shows the region name chip for a pre-seeded A1: highlight even with pick mode set to Countries", async () => {
    const job = makeJob({ result: { ...makeDoc({ slides: [makeSlide({ highlights: ["A1:MYS-1186"] })] }), stateRevision: 1 } });
    await renderMapsTab({ job });
    await openProperties();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: /Sabah/ }).closest(".maps-hl-chip")).toBeTruthy();
    expect(loadAdmin1Stub).toHaveBeenCalledWith("MYS");
  });

  it("does not keep re-fetching admin-1 for the same camera country", async () => {
    sessionStorage.setItem(MAPS_PICK_MODE_KEY, "1");
    const job = makeJob({ result: { ...makeDoc({ cachedCountries: ["MYS"] }), stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });
    mapFake.setRegionCountries(["MYS"]);

    const camera = { lat: 2, lon: 100, zoom: 5, bearing: 0, pitch: 0 };
    await act(async () => {
      mapFake.emit.cameraCommit(camera);
      await Promise.resolve();
      await Promise.resolve();
    });
    const callsAfterFirstSettle = loadAdmin1Stub.mock.calls.length;

    await act(async () => {
      mapFake.emit.cameraCommit(camera);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(loadAdmin1Stub.mock.calls.length).toBe(callsAfterFirstSettle);
  });

  it("switching to a CG override and panning it re-derives the region camera", async () => {
    sessionStorage.setItem(MAPS_PICK_MODE_KEY, "1");
    const slide = makeSlide({
      cg: {
        camera: makeCamera({ lat: 4, lon: 101, zoom: 6 }),
        style: "positron",
        highlights: [],
        churches: [],
      },
    });
    const job = makeJob({ result: { ...makeDoc({ slides: [slide] }), stateRevision: 1 } });

    const releases = new Map<string, () => void>();
    loadAdmin1Stub.mockImplementation(
      (code: string) =>
        new Promise((resolve) => {
          releases.set(code, () => resolve({ type: "FeatureCollection", features: [] }));
        })
    );

    const { mapFake } = await renderMapsTab({ job });
    await openProperties();

    mapFake.setRegionCountries(["MYS"]);
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "CG" }));
    });
    await flushMicrotasks();

    expect(loadAdmin1Stub).toHaveBeenCalledWith("MYS");
    expect(screen.getByText("Loading regions…")).toBeInTheDocument();

    await act(async () => {
      releases.get("MYS")!();
    });
    await flushMicrotasks();
    expect(screen.queryByText("Loading regions…")).not.toBeInTheDocument();

    mapFake.setRegionCountries(["IDN"]);
    await act(async () => {
      mapFake.emit.cameraCommit({ lat: -2, lon: 118, zoom: 5, bearing: 0, pitch: 0 });
    });
    await flushMicrotasks();

    expect(loadAdmin1Stub).toHaveBeenCalledWith("IDN");
    expect(screen.getByText("Loading regions…")).toBeInTheDocument();
  });
});

describe("Isolate toggle label", () => {
  it("toggles Isolate without spelling ON or OFF", async () => {
    await renderMapsTab({
      job: makeJob({ result: { ...makeDoc({ slides: [makeSlide({ highlights: ["SGP"] })] }), stateRevision: 1 } }),
    });
    await openProperties();

    const checkbox = screen.getByRole("checkbox", { name: "Isolate" });
    expect(checkbox).not.toBeChecked();
    expect(screen.queryByText("OFF")).not.toBeInTheDocument();
    expect(screen.queryByText("ON")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(checkbox);
    });

    expect(checkbox).toBeChecked();
    expect(screen.queryByText("ON")).not.toBeInTheDocument();
  });

  it("is absent when the slide has no highlights", async () => {
    await renderMapsTab();
    await openProperties();

    expect(screen.queryByRole("checkbox", { name: /Isolate/ })).not.toBeInTheDocument();
  });

  it("disappears, and isolate clears, once the last highlight chip is removed", async () => {
    await renderMapsTab({
      job: makeJob({
        result: {
          ...makeDoc({ slides: [makeSlide({ highlights: ["SGP"], isolate: { mode: "darken", strength: 0.6 } })] }),
          stateRevision: 1,
        },
      }),
    });
    await openProperties();

    expect(screen.getByRole("checkbox", { name: /Isolate/ })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTitle("Remove highlight"));
    });
    await tick(MAPS_SAVE_IDLE_MS);

    expect(screen.queryByRole("checkbox", { name: /Isolate/ })).not.toBeInTheDocument();
    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{ id: string; isolate?: unknown }>;
    const lastSlide = slides.find((s) => s.id === "slide-1");
    expect(lastSlide?.isolate).toBeUndefined();
  });

  it("clears the CG override's isolate on its last highlight chip without touching LW", async () => {
    const lwIsolate: MapsIsolate = { mode: "darken", strength: 0.6 };
    const cgIsolate: MapsIsolate = { mode: "darken", strength: 0.6 };
    await renderMapsTab({
      job: makeJob({
        result: {
          ...makeDoc({
            slides: [
              makeSlide({
                highlights: ["SGP"],
                isolate: lwIsolate,
                cg: {
                  camera: makeCamera(),
                  style: "positron",
                  highlights: ["MYS"],
                  churches: [],
                  isolate: cgIsolate,
                },
              }),
            ],
          }),
          stateRevision: 1,
        },
      }),
    });
    await openProperties();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "CG" }));
    });
    await flushMicrotasks();

    expect(screen.getByRole("checkbox", { name: /Isolate/ })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTitle("Remove highlight"));
    });
    await tick(MAPS_SAVE_IDLE_MS);

    expect(screen.queryByRole("checkbox", { name: /Isolate/ })).not.toBeInTheDocument();
    const calls2 = mapsApiScript.saveMapsState.calls;
    expect(calls2.length).toBeGreaterThan(0);
    const slides2 = calls2[calls2.length - 1].document.slides as Array<{
      id: string;
      isolate?: unknown;
      cg?: { isolate?: unknown };
    }>;
    const lastSlide2 = slides2.find((s) => s.id === "slide-1");
    expect(lastSlide2?.cg?.isolate).toBeUndefined();
    expect(lastSlide2?.isolate).toEqual(lwIsolate);
  });
});
