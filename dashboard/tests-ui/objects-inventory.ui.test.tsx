import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { loadAdmin0Stub, loadAdmin1Stub, renderMapsTab } from "./renderMapsTab";
import { makeDoc, makeJob, makeSlide } from "./fakes/doc";

beforeEach(() => {
  loadAdmin1Stub.mockClear();
  loadAdmin0Stub.mockReset();
  loadAdmin0Stub.mockResolvedValue(null);
});

async function openObjects() {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
  });
}

describe("Objects tab: pins and highlights", () => {
  it("shows a row per highlight with its resolved name", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["MYS", "A1:MYS-1186"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await openObjects();

    expect(screen.getByText("Highlights")).toBeInTheDocument();
    expect(screen.getByText("MYS")).toBeInTheDocument();
    expect(screen.getByText("Sabah")).toBeInTheDocument();
  });

  it("gives the region row and the country row different glyph classes", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["MYS", "A1:MYS-1186"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await openObjects();

    const countryRow = screen.getByText("MYS").closest(".maps-pin-row") as HTMLElement;
    const regionRow = screen.getByText("Sabah").closest(".maps-pin-row") as HTMLElement;
    expect(countryRow).toHaveClass("kind-country");
    expect(regionRow).toHaveClass("kind-region");
    expect(countryRow.querySelector(".maps-pin-kind")).toHaveClass("kind-country");
    expect(regionRow.querySelector(".maps-pin-kind")).toHaveClass("kind-region");
  });

  it("removing a highlight strips exactly that code", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["MYS", "A1:MYS-1186"] })] }), stateRevision: 1 },
    });
    const { mapFake } = await renderMapsTab({ job });
    await openObjects();

    const countryRow = screen.getByText("MYS").closest(".maps-pin-row") as HTMLElement;
    await act(async () => {
      fireEvent.click(within(countryRow).getByRole("button", { name: /Remove/ }));
    });

    expect(mapFake.getLatestProps().highlights).toEqual(["A1:MYS-1186"]);
  });

  it("pins and highlights coexist in the same tab", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({
              highlights: ["MYS"],
              churches: [{ id: "c1", name: "Church One", lat: 1, lon: 103, kind: "dot", color: "#fff" }],
            }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await openObjects();

    expect(screen.getByText("Church One")).toBeInTheDocument();
    expect(screen.getByText("MYS")).toBeInTheDocument();
  });

  it("sums pins and highlights in the tab count badge", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({
              highlights: ["MYS", "A1:MYS-1186"],
              churches: [{ id: "c1", name: "Church One", lat: 1, lon: 103, kind: "dot", color: "#fff" }],
            }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });

    const tab = screen.getByRole("tab", { name: /Objects/ });
    expect(within(tab).getByText("3")).toBeInTheDocument();
  });

  it("opening a highlight row shows its colour override in Properties", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["MYS"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await openObjects();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "MYS" }));
    });

    expect(screen.getByRole("button", { name: "Camera" })).toBeInTheDocument();
    expect(screen.getByLabelText("Highlight colour")).toBeInTheDocument();
    expect(screen.getByText("Highlight")).toBeInTheDocument();
  });

  it("hides the empty-state note when only highlights exist", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["MYS"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await openObjects();

    expect(screen.queryByText(/Shift-click the map to add a pin/)).not.toBeInTheDocument();
  });
});
