import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HistoryTab } from "../src/tabs/HistoryTab";
import { makeJob } from "./fakes/doc";

// Any backend refusal of a delete must reach the operator, with the run still listed.
const DETAIL = "Could not delete resize-1: its output folder is in use.";

const job = makeJob({ kind: "resize", feature: "resize", name: "resize-1", result: { phase: "framing" } });

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return { ...actual, listJobs: vi.fn(async () => [job]) };
});

function refuseDeletes() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status: 409,
    json: async () => ({ detail: DETAIL }),
  } as Response);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("History delete refused by the backend", () => {
  it("shows the 409 message and keeps the run listed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchSpy = refuseDeletes();
    render(<HistoryTab active />);
    const del = await screen.findByRole("button", { name: "Delete resize-1" });

    await act(async () => {
      fireEvent.click(del);
    });

    expect(fetchSpy).toHaveBeenCalledWith(`/api/jobs/${job.id}`, { method: "DELETE" });
    expect(await screen.findByText(DETAIL)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete resize-1" })).toBeInTheDocument();
  });

  it("Delete All shows the 409 message and keeps the run listed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    refuseDeletes();
    render(<HistoryTab active />);
    await screen.findByRole("button", { name: "Delete resize-1" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete All" }));
    });

    expect(await screen.findByText(DETAIL)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete resize-1" })).toBeInTheDocument();
  });
});
