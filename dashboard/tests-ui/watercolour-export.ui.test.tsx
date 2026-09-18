import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatercolourTab } from "../src/tabs/WatercolourTab";
import { WatercolourResultView } from "../src/components/WatercolourResultView";
import { chooseFolder, exportWatercolour, reveal, type Job } from "../src/api";

const doneJob: Job = {
  id: "wash-1",
  kind: "watercolour",
  feature: "watercolour",
  status: "done",
  logs: [],
  result: {
    items: [{ id: "i1", name: "photo.png", result: "00-photo-watercolour.png", status: "done", width: 10, height: 10 }],
  },
  createdAt: 0,
  updatedAt: 0,
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    listJobs: vi.fn(async () => []),
    chooseFolder: vi.fn(async () => ({ path: "/tmp/exports", name: "exports" })),
    exportWatercolour: vi.fn(async () => ({ ...doneJob, result: { ...doneJob.result, exportDir: "/tmp/exports" } })),
    reveal: vi.fn(async () => undefined),
  };
});

vi.mock("../src/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/sessions")>();
  return {
    ...actual,
    useCurrentJob: () => ({ job: null, upsert: () => undefined, rename: async () => doneJob, error: null }),
  };
});

describe("watercolour Export", () => {
  it("does not show Export on a fresh tab", () => {
    render(<WatercolourTab />);
    expect(screen.queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export to…" })).not.toBeInTheDocument();
    expect(screen.queryByText("Export to")).not.toBeInTheDocument();
  });

  it("shows Export after a converted or loaded session and copies into the chosen folder", async () => {
    render(
      <WatercolourResultView
        job={doneJob}
        onOpen={() => undefined}
        onError={() => undefined}
      />
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export to…" })).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    expect(chooseFolder).toHaveBeenCalledWith("Export watercolours");
    expect(exportWatercolour).toHaveBeenCalledWith("wash-1", "/tmp/exports");
    expect(reveal).toHaveBeenCalledWith("/tmp/exports");
  });
});
