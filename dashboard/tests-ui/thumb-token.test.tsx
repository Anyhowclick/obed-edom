import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab, tick } from "./renderMapsTab";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeCamera, makeDoc, makeJob, makeSlide } from "./fakes/doc";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("thumbnail token gating", () => {
  it("a conflict that lands mid-capture aborts the pending publish", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    mapFake.holdIdle();
    await tick(750);

    expect(mapFake.waitUntilIdle).toHaveBeenCalled();

    mapFake.emit.cameraCommit(makeCamera({ zoom: 15 }));
    await tick(0);

    mapsApiScript.saveMapsState.conflictOnce({
      document: { ...doc, slides: [{ ...doc.slides[0], camera: makeCamera({ zoom: 8 }) }] },
      stateRevision: 3,
      paths: ["slides.0.camera"],
    });

    await tick(500);
    await tick(0);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    mapFake.releaseIdle();
    await tick(0);
    await tick(0);

    expect(mapsApiScript.postMapsPng.calls).toHaveLength(0);
  });

  it("switching the active slide mid-capture invalidates the stale capture's token; only the newer one publishes", async () => {
    // Both captures target the same unchanged slide-1 content (same fingerprint), so only the
    // thumbnailToken bump — not a fingerprint mismatch — can tell the stale one apart.
    const doc = makeDoc({ slides: [makeSlide({ id: "slide-1", title: "Slide 1" }), makeSlide({ id: "slide-2", title: "Slide 2" })] });
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    mapFake.holdIdle();
    await tick(750);
    expect(mapFake.waitUntilIdle).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Select slide Slide 2/ }));
    });
    await tick(0);
    expect(mapFake.waitUntilIdle).toHaveBeenCalledTimes(2);

    mapFake.releaseIdle();
    await tick(0);
    await tick(0);

    expect(mapsApiScript.postMapsPng.calls).toHaveLength(1);
    expect(mapsApiScript.postMapsPng.calls[0]).toMatchObject({ slideId: "slide-1" });
  });
});
