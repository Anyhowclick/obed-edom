import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab, tick } from "./renderMapsTab";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeDoc, makeJob } from "./fakes/doc";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("credits slide toggle in the Export inspector tab", () => {
  it("is checked by default and patches attribution: stamp when unchecked", async () => {
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    const checkbox = screen.getByRole("checkbox", { name: "Credits slide instead of stamped attribution" });
    expect(checkbox).toBeChecked();

    await act(async () => {
      fireEvent.click(checkbox);
    });
    await tick(500);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1].document.attribution).toBe("stamp");
  });

  it("checks the box and patches attribution: credits when starting from stamp", async () => {
    await renderMapsTab({
      job: makeJob({ result: { ...makeDoc({ attribution: "stamp" }), stateRevision: 1 } }),
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    const checkbox = screen.getByRole("checkbox", { name: "Credits slide instead of stamped attribution" });
    expect(checkbox).not.toBeChecked();

    await act(async () => {
      fireEvent.click(checkbox);
    });
    await tick(500);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1].document.attribution).toBe("credits");
  });
});
