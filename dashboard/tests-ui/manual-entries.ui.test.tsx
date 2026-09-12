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

async function openForm(item: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: item }));
  });
}

async function type(label: string, value: string) {
  await act(async () => {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  });
}

async function clickDone() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
  });
  await tick(0);
  await tick(0);
}

describe("manual entry forms", () => {
  it("posts one row per entry and selects the new slide", async () => {
    await renderMapsTab();
    // persistCurrentState saves first and the fake acks expectedRevision + 1, so the job the
    // poll resolves must carry a revision above that or the queue never publishes it.
    const done = makeJob({
      status: "done",
      result: {
        ...makeDoc({
          slides: [
            makeSlide(),
            makeSlide({ id: "s2", title: "Singapore" }),
            makeSlide({ id: "s3", title: "London" }),
          ],
        }),
        stateRevision: 3,
      },
    });
    mapsApiScript.pollJob.resolve(done);

    await openForm("Add slides manually…");
    await type("Name row 1", "Singapore");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    });
    await type("Name row 2", "London");
    await clickDone();

    expect(mapsApiScript.bootstrapMapsRows.calls).toHaveLength(1);
    expect(mapsApiScript.bootstrapMapsRows.calls[0]).toEqual({
      id: "job-1",
      body: { rows: [{ name: "Singapore" }, { name: "London" }] },
    });
    expect(screen.queryByRole("group", { name: "Add slides manually" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select slide London/ })).toBeInTheDocument();
  });

  it("rebases the save queue onto the revision the bootstrap wrote", async () => {
    const { mapFake } = await renderMapsTab();
    mapsApiScript.pollJob.resolve(makeJob({ result: { ...makeDoc(), stateRevision: 3 } }));

    await openForm("Add slides manually…");
    await type("Name row 1", "Singapore");
    await clickDone();

    mapFake.emit.cameraCommit(makeCamera({ zoom: 15 }));
    await tick(0);
    await tick(500);
    await tick(0);

    const saves = mapsApiScript.saveMapsState.calls;
    expect(saves[saves.length - 1]?.expectedRevision).toBe(3);
  });

  it("removes a row before posting", async () => {
    await renderMapsTab();
    mapsApiScript.pollJob.resolve(makeJob({ result: { ...makeDoc(), stateRevision: 3 } }));

    await openForm("Add slides manually…");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add row" }));
      fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    });
    await type("Name row 1", "Singapore");
    await type("Name row 2", "Nowhere");
    await type("Name row 3", "London");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove row 2" }));
    });
    await clickDone();

    expect(mapsApiScript.bootstrapMapsRows.calls[0].body.rows).toEqual([{ name: "Singapore" }, { name: "London" }]);
  });

  it("shows a validation error and posts nothing when a slides row has no name", async () => {
    await renderMapsTab();

    await openForm("Add slides manually…");
    await type("Latitude row 1", "1.3521");
    await clickDone();

    expect(screen.getByRole("alert")).toHaveTextContent("Row 1: enter a name.");
    expect(mapsApiScript.bootstrapMapsRows.calls).toHaveLength(0);
    expect(screen.getByRole("group", { name: "Add slides manually" })).toBeInTheDocument();
  });

  it("keeps the rows when the server rejects the batch", async () => {
    await renderMapsTab();
    mapsApiScript.bootstrapMapsRows.failOnce(new Error("Row 1: no name"));

    await openForm("Add slides manually…");
    await type("Name row 1", "Singapore");
    await clickDone();

    expect(screen.getByText("Row 1: no name")).toBeInTheDocument();
    expect(screen.getByLabelText("Name row 1")).toHaveValue("Singapore");
    expect(screen.getByRole("group", { name: "Add slides manually" })).toBeInTheDocument();
  });

  it("pins mode posts the target slide and the active audience", async () => {
    await renderMapsTab();
    mapsApiScript.pollJob.resolve(makeJob({ result: { ...makeDoc(), stateRevision: 3 } }));

    await openForm("Add pins to this view manually…");
    await type("Name row 1", "Bedok");
    await clickDone();

    expect(mapsApiScript.bootstrapMapsRows.calls[0].body).toEqual({
      rows: [{ name: "Bedok", kind: "dropPin" }],
      targetSlideId: "slide-1",
      audience: "lw",
    });
  });

  it("hides the manual entries behind the lock", async () => {
    await renderMapsTab({ job: makeJob({ status: "running" }) });

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});
