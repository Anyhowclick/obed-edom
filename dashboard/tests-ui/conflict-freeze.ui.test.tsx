import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab, tick } from "./renderMapsTab";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeCamera, makeDoc, makeJob } from "./fakes/doc";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("conflict freeze", () => {
  it("blocks further doc edits and thumbnail publishes until the operator resolves the banner", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    const { mapFake } = await renderMapsTab({ job });

    const localCamera = makeCamera({ zoom: 14 });
    mapFake.emit.cameraCommit(localCamera);
    await tick(0);

    const remoteCamera = makeCamera({ zoom: 9 });
    mapsApiScript.saveMapsState.conflictOnce({
      document: { ...doc, slides: [{ ...doc.slides[0], camera: remoteCamera }] },
      stateRevision: 5,
    });

    await tick(500);
    await tick(0);

    expect(screen.getByRole("alert")).toHaveTextContent("This map was changed elsewhere");
    expect(mapFake.getLatestProps().camera).toEqual(localCamera);

    // onToggleCountry reaches applyLocalDoc directly, with no `locked` gate of its own —
    // this is what actually proves applyLocalDoc's freeze early-return, not just the
    // (separately gated) camera-commit path above.
    mapFake.emit.toggleCountry("SGP");
    await tick(0);
    expect(mapFake.getLatestProps().highlights).toEqual([]);

    mapFake.emit.objectMove("church-x", 1.5, 103.9);
    await tick(0);

    await tick(750);
    await tick(0);
    expect(mapsApiScript.postMapsPng.calls).toHaveLength(0);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reload latest" }));
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keep my changes clears the banner and resumes editing", async () => {
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

    expect(screen.getByRole("alert")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Keep my changes" }));
    });
    await tick(0);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    mapFake.emit.cameraCommit(makeCamera({ zoom: 17 }));
    await tick(0);
    expect(mapFake.getLatestProps().camera).toEqual(makeCamera({ zoom: 17 }));
  });
});
