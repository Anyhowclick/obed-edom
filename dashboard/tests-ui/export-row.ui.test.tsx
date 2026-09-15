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

describe("MapsTab export row sits in the Export button's row", () => {
  it("shares an .actions ancestor with the Export button and renders Export to… as a collab button", async () => {
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    const exportTo = screen.getByRole("button", { name: "Export to…" });
    const exportBtn = screen.getByRole("button", { name: "Export" });

    expect(exportTo).toHaveClass("collab");
    expect(exportTo.closest(".actions")).not.toBeNull();
    expect(exportTo.closest(".actions")).toBe(exportBtn.closest(".actions"));

    const path = screen.getByText(/output\/ \(default\)|\(default\)/);
    expect(exportTo.compareDocumentPosition(path) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
