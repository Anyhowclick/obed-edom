import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushMicrotasks, loadAdmin0Stub, loadAdmin1Stub, renderMapsTab } from "./renderMapsTab";
import { MAPS_PICK_MODE_KEY } from "../src/prefs";
import { makeCamera, makeDoc, makeJob, makeSlide } from "./fakes/doc";

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
    const regions = screen.getByRole("button", { name: "Regions" });
    const countries = screen.getByRole("button", { name: "Countries" });
    expect(countries).toHaveClass("on");
    expect(regions).not.toHaveClass("on");

    await act(async () => {
      fireEvent.click(regions);
    });

    expect(screen.getByRole("button", { name: "Regions" })).toHaveClass("on");
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
    expect(chip).toHaveClass("maps-hl-chip");

    await act(async () => {
      fireEvent.click(chip);
    });

    expect(mapFake.getLatestProps().highlights).toEqual([]);
  });

  it("region picking is off until the operator turns it on", async () => {
    const { mapFake } = await renderMapsTab();
    expect(mapFake.getLatestProps().pickRegions).toBe(false);

    await openProperties();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Regions" }));
    });

    expect(mapFake.getLatestProps().pickRegions).toBe(true);
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

    expect(screen.getByRole("button", { name: /Sabah/ })).toHaveClass("maps-hl-chip");
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
      fireEvent.click(screen.getByRole("button", { name: "CG" }));
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
  it("reads Isolate OFF by default and Isolate ON after toggling", async () => {
    await renderMapsTab();
    await openProperties();

    const checkbox = screen.getByRole("checkbox", { name: /Isolate/ });
    expect(screen.getByText("OFF")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(checkbox);
    });

    expect(screen.getByText("ON")).toBeInTheDocument();
  });
});
