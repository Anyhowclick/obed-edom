import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab, tick } from "./renderMapsTab";
import type { Job } from "../src/api";
import { makeCamera, makeDoc, makeJob } from "./fakes/doc";
import { mapsApiScript } from "./fakes/mapsApi";

beforeEach(() => {
  vi.useFakeTimers();
  // jsdom doesn't implement the PointerEvent capture API.
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
  HTMLElement.prototype.releasePointerCapture = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

function pill(): HTMLElement {
  return screen.getByText(/^(Saved|Unsaved|Saving…|Paused|Save failed)$/);
}

function pillState(): string {
  const el = pill();
  const cls = Array.from(el.classList).find((c) => c.startsWith("maps-save-status-"));
  return `${el.textContent} (${cls})`;
}

describe("save-status pill", () => {
  it("walks Saved → Unsaved → Saving… → Saved across a debounced camera edit", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    expect(pillState()).toBe("Saved (maps-save-status-saved)");

    let resolveSave: (job: Job) => void = () => undefined;
    mapsApiScript.saveMapsState.deferOnce(
      new Promise((resolve) => {
        resolveSave = resolve;
      })
    );

    mapFake.emit.cameraCommit(makeCamera({ zoom: 14 }));
    await tick(0);
    expect(pillState()).toBe("Unsaved (maps-save-status-unsaved)");

    await tick(500);
    expect(pillState()).toBe("Saving… (maps-save-status-saving)");

    resolveSave(makeJob({ id: job.id, result: { ...doc, stateRevision: 2 } }));
    await tick(0);
    expect(pillState()).toBe("Saved (maps-save-status-saved)");
    expect(pill()).toHaveAttribute("aria-live", "polite");
  });

  it("moves to Paused on a scripted conflict", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    mapFake.emit.cameraCommit(makeCamera({ zoom: 14 }));
    await tick(0);

    mapsApiScript.saveMapsState.conflictOnce({
      document: { ...doc, slides: [{ ...doc.slides[0], camera: makeCamera({ zoom: 9 }) }] },
      stateRevision: 5,
    });

    await tick(500);
    await tick(0);

    expect(pillState()).toBe("Paused (maps-save-status-paused)");
  });

  it("does not change status on nav-list resize drag or inspector toggle", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    const before = pillState();

    const handle = screen.getByLabelText("Resize slide list");
    await act(async () => {
      fireEvent.pointerDown(handle, { clientX: 200 });
      fireEvent.pointerMove(handle, { clientX: 260 });
      fireEvent.pointerUp(handle, { clientX: 260 });
    });
    expect(pillState()).toBe(before);
    expect(mapFake.resize).toHaveBeenCalled();

    mapFake.resize.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /inspector/i }));
    });
    expect(pillState()).toBe(before);
    expect(mapFake.resize).toHaveBeenCalled();
  });
});
