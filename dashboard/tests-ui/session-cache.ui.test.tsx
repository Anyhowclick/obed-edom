import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mapsApiScript } from "./fakes/mapsApi";
import { makeJob } from "./fakes/doc";
import { renderMapsTab } from "./renderMapsTab";

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:session");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("session + cache overlay", () => {
  it("shows a spinner while saving the session + cache", async () => {
    let resolveDownload!: (value: { blob: Blob; filename: string }) => void;
    await renderMapsTab();
    mapsApiScript.downloadMapsSession.deferOnce(
      new Promise((resolve) => {
        resolveDownload = resolve;
      })
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Session" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save session + cache…" }));
    });

    expect(screen.getByRole("heading", { name: "Saving session + cache…" })).toBeInTheDocument();
    expect(document.querySelector(".spinner")).toBeTruthy();

    await act(async () => {
      resolveDownload({ blob: new Blob(["session"]), filename: "maps-job-1.obedmaps" });
      await Promise.resolve();
    });

    expect(screen.queryByRole("heading", { name: "Saving session + cache…" })).not.toBeInTheDocument();
  });

  it("shows a spinner while loading the session + cache", async () => {
    let resolveLoad!: (job: ReturnType<typeof makeJob>) => void;
    await renderMapsTab();
    mapsApiScript.loadMapsSession.deferOnce(
      new Promise((resolve) => {
        resolveLoad = resolve;
      })
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Session" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load session + cache…" }));
    });

    const input = document.querySelector('input[accept=".obedmaps,.zip,application/zip"]') as HTMLInputElement;
    const file = new File(["session"], "deck.obedmaps", { type: "application/zip" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(screen.getByRole("heading", { name: "Loading session + cache…" })).toBeInTheDocument();
    expect(document.querySelector(".spinner")).toBeTruthy();

    await act(async () => {
      resolveLoad(makeJob());
      await Promise.resolve();
    });

    expect(screen.queryByRole("heading", { name: "Loading session + cache…" })).not.toBeInTheDocument();
  });
});
