import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab, tick } from "./renderMapsTab";
import { makeCamera, makeDoc, makeJob } from "./fakes/doc";
import { mapsApiScript, saveMapsState, renameJob } from "./fakes/mapsApi";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("rename persists the unsaved edit first", () => {
  it("saves the map state before renaming, and the local edit survives the server echo", async () => {
    const doc = makeDoc();
    const job = makeJob({ result: { ...doc, stateRevision: 1 }, name: undefined });
    const { mapFake } = await renderMapsTab({ job });

    const editedCamera = makeCamera({ zoom: 17 });
    mapFake.emit.cameraCommit(editedCamera);
    await tick(0);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Rename/ }));
    });

    const input = document.querySelector(".job-name-input") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: "renamed-deck" } });
      fireEvent.keyDown(input, { key: "Enter" });
    });
    // the save→rename await chain resolves over two microtask hops; one tick(0) per hop.
    await tick(0);
    await tick(0);

    expect(mapsApiScript.renameJob.calls).toHaveLength(1);
    expect(mapsApiScript.saveMapsState.calls.length).toBeGreaterThan(0);

    const saveOrder = saveMapsState.mock.invocationCallOrder[0];
    const renameOrder = renameJob.mock.invocationCallOrder[0];
    expect(saveOrder).toBeLessThan(renameOrder);

    expect(mapsApiScript.renameJob.calls[0]).toEqual({ id: job.id, name: "renamed-deck" });

    expect(mapFake.getLatestProps().camera).toEqual(editedCamera);
  });
});
