import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { renderMapsTab } from "./renderMapsTab";

const pin = (id: string, name: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name,
  lat: 1.3,
  lon: 103.8,
  kind: "dot" as const,
  color: "#c44a42",
  size: 28,
  ...overrides,
});

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function openObjects() {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
  });
}

async function selectNamed(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${name}` }));
  });
}

describe("object bulk actions", () => {
  it("hides paste destinations after paste to slides or delete", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({ id: "s1", title: "SEA", churches: [pin("c1", "Alpha")] }),
            makeSlide({ id: "s2", title: "Indo" }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await openObjects();

    expect(screen.queryByRole("group", { name: "Paste destinations" })).not.toBeInTheDocument();

    await selectNamed("Alpha");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    });
    expect(screen.getByRole("group", { name: "Paste destinations" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /Indo/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Paste selected slides" }));
    });
    expect(screen.queryByRole("group", { name: "Paste destinations" })).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Paste to slides" }));
    });
    expect(screen.getByRole("group", { name: "Paste destinations" })).toBeInTheDocument();

    await selectNamed("Alpha");
    expect(screen.getByRole("group", { name: "Paste destinations" })).toBeInTheDocument();

    await selectNamed("Alpha");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete selected objects" }));
    });
    expect(screen.queryByRole("group", { name: "Paste destinations" })).not.toBeInTheDocument();
  });

  it("opens paste destinations from the clipboard after the selection is cleared", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({ id: "s1", title: "SEA", churches: [pin("c1", "Alpha")] }),
            makeSlide({ id: "s2", title: "Indo", churches: [pin("c2", "Beta")] }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await openObjects();

    await selectNamed("Alpha");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /Indo/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Paste selected slides" }));
    });
    expect(screen.queryByRole("group", { name: "Paste destinations" })).not.toBeInTheDocument();

    await selectNamed("Alpha");
    expect(screen.queryByRole("checkbox", { name: "Select Alpha" })).not.toBeChecked();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Paste to slides" }));
    });
    expect(screen.getByRole("group", { name: "Paste destinations" })).toBeInTheDocument();
  });

  it("applies the same size, colour, and scale-with-map to selected pins", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({
              churches: [pin("c1", "Alpha", { size: 28, color: "#c44a42" }), pin("c2", "Beta", { size: 40, color: "#415bc3", kind: "dropPin" })],
            }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await openObjects();
    await selectNamed("Alpha");
    await selectNamed("Beta");

    const style = screen.getByRole("group", { name: "Selected pin style" });
    expect(style).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Pin size"), { target: { value: "120" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Colour"), { target: { value: "#112233" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /Scale with map/ }));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 550));
    });

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const document = calls[calls.length - 1].document as {
      slides: Array<{ churches: Array<{ id: string; size?: number; color: string; scaleWithMap?: boolean }> }>;
    };
    const churches = document.slides[0].churches;
    expect(churches.find((c) => c.id === "c1")).toMatchObject({ size: 120, color: "#112233", scaleWithMap: true });
    expect(churches.find((c) => c.id === "c2")).toMatchObject({ size: 120, color: "#112233", scaleWithMap: true });
  });

  it("does not show opacity on a selected object", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ churches: [pin("c1", "Alpha")] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await openObjects();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Alpha/ }));
    });

    expect(screen.queryByText("Opacity")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Scale with map/)).toBeInTheDocument();
  });
});
