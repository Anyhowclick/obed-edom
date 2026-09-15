import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab } from "./renderMapsTab";
import { mapsApiScript } from "./fakes/mapsApi";

vi.mock("../src/maps/captureExport", () => ({
  captureExportRaster: vi.fn(async () => new Blob(["raster"])),
  captureIsolatePair: vi.fn(async () => ({
    base: new Blob(["base"]),
    pieces: [{ id: "MYS", x: 0, y: 0, w: 10, h: 10, blob: new Blob(["piece"]) }],
  })),
}));
import { ExportDestinationRow } from "../src/components/ExportDestinationRow";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MapsTab export is a single save-panel button", () => {
  it("shows Export without a separate Export to… row", async () => {
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export to…" })).not.toBeInTheDocument();
    expect(screen.queryByText(/output\/ \(default\)|\(default\)/)).not.toBeInTheDocument();
  });

  it("opens the save panel then posts the chosen path", async () => {
    await renderMapsTab();
    mapsApiScript.exportPlan.set({
      links: [],
      stills: [],
      plates: [],
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(mapsApiScript.chooseSave.calls.length).toBe(1);
    expect(mapsApiScript.chooseSave.calls[0][0]).toEqual(
      expect.objectContaining({ prompt: "Export Keynote", defaultName: "maps.key" })
    );
    expect(mapsApiScript.exportMaps.calls.length).toBeGreaterThan(0);
    const exportCall = mapsApiScript.exportMaps.calls[mapsApiScript.exportMaps.calls.length - 1];
    expect(exportCall.body).toEqual(
      expect.objectContaining({ exportPath: "/tmp/exports/maps.key" })
    );
  });

  it("does not start export when the save panel is cancelled", async () => {
    await renderMapsTab();
    mapsApiScript.chooseSave.resolve(null);

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(mapsApiScript.chooseSave.calls.length).toBe(1);
    expect(mapsApiScript.exportMaps.calls.length).toBe(0);
  });
});

describe("ExportDestinationRow default (non-inline) rendering", () => {
  it("still shows the Export to heading when inline is not passed", () => {
    render(<ExportDestinationRow value="" onChange={() => undefined} />);
    expect(screen.getByText("Export to")).toBeInTheDocument();
  });
});

describe("export stills with highlights but no isolate", () => {
  it("takes the base + pieces path and POSTs region pieces then the manifest", async () => {
    const { captureIsolatePair, captureExportRaster } = await import("../src/maps/captureExport");
    await renderMapsTab();
    mapsApiScript.exportPlan.set({
      links: [],
      stills: [
        {
          slideId: "s1",
          style: "positron",
          camera: { lat: 1.3, lon: 103.8, zoom: 12, bearing: 0, pitch: 0 },
          highlights: ["MYS"],
          hiddenLayers: [],
          hillshade: false,
          isolate: null,
          width: 3840,
          height: 1080,
        },
      ],
      plates: [],
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(captureIsolatePair).toHaveBeenCalledTimes(1);
    expect(captureExportRaster).not.toHaveBeenCalled();
    const posts = mapsApiScript.postMapsPng.calls.filter((opts) => opts?.kind === "still");
    expect(posts.map((opts) => opts?.variant)).toEqual([undefined, "region", "regions"]);
    expect(posts.map((opts) => opts?.index)).toEqual([undefined, 0, undefined]);
  });
});
