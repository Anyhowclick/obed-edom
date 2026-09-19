import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { renderMapsTab } from "./renderMapsTab";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("maps confirm modal", () => {
  it("asks before removing a slide and keeps it on cancel", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    await renderMapsTab({
      job: makeJob({
        result: {
          ...makeDoc({
            slides: [makeSlide({ id: "s1", title: "SEA" }), makeSlide({ id: "s2", title: "Indo" })],
          }),
          stateRevision: 1,
        },
      }),
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete slide" }));
    });

    expect(screen.getByRole("dialog", { name: "Remove slide “SEA”?" })).toBeInTheDocument();
    expect(nativeConfirm).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Select slide SEA/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select slide Indo/ })).toBeInTheDocument();
  });

  it("removes the slide after confirming", async () => {
    await renderMapsTab({
      job: makeJob({
        result: {
          ...makeDoc({
            slides: [makeSlide({ id: "s1", title: "SEA" }), makeSlide({ id: "s2", title: "Indo" })],
          }),
          stateRevision: 1,
        },
      }),
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete slide" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Select slide SEA/ })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Select slide Indo/ })).toBeInTheDocument();
  });

  it("asks before loading a saved session", async () => {
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Session" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load session + cache…" }));
    });

    expect(screen.getByRole("dialog", { name: "Load a saved map session?" })).toBeInTheDocument();
    expect(
      screen.getByText("The current deck will be replaced; cached tiles from the session will be added to this cache.")
    ).toBeInTheDocument();
  });
});
