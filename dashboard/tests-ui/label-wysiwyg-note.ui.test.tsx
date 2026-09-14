import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderMapsTab } from "./renderMapsTab";
import { makeDoc, makeJob, makeSlide } from "./fakes/doc";

describe("label preview WYSIWYG note", () => {
  it("shows a note that the preview label font differs from the Keynote export when a pin with a label is selected", async () => {
    const doc = makeDoc({
      slides: [
        makeSlide({
          churches: [
            { id: "c1", name: "Grace Church", lat: 1.3, lon: 103.8, kind: "dot", color: "#c44a42", showLabel: true },
          ],
        }),
      ],
    });
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    await renderMapsTab({ job });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Grace Church/ }));
    });

    expect(screen.getByText(/Preview only/i)).toBeInTheDocument();
    expect(screen.getByText(/Amplitude Bold/)).toBeInTheDocument();
  });

  it("hides the note and renders the checkbox unchecked for a church with showLabel false", async () => {
    const doc = makeDoc({
      slides: [
        makeSlide({
          churches: [
            { id: "c1", name: "Grace Church", lat: 1.3, lon: 103.8, kind: "dot", color: "#c44a42", showLabel: false },
          ],
        }),
      ],
    });
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    await renderMapsTab({ job });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Grace Church/ }));
    });

    expect(screen.queryByText(/Preview only/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Show label/)).not.toBeChecked();
  });

  it("keeps the label on a legacy church saved with no showLabel key", async () => {
    const doc = makeDoc({
      slides: [
        makeSlide({
          churches: [
            { id: "c1", name: "Grace Church", lat: 1.3, lon: 103.8, kind: "dot", color: "#c44a42" },
          ],
        }),
      ],
    });
    const job = makeJob({ result: { ...doc, stateRevision: 1 } });
    await renderMapsTab({ job });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Grace Church/ }));
    });

    expect(screen.getByLabelText(/Show label/)).toBeChecked();
  });
});
