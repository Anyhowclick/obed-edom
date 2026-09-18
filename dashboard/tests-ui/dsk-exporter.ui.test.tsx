import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DskExporter } from "../src/tabs/dsk/DskExporter";
import { chooseFolder, chooseKeynote, startDskExport, applyDskExport, pollJob } from "../src/api";
import type { Job } from "../src/api";

const reviewJob: Job = {
  id: "job-1",
  kind: "dsk-export",
  feature: "dsk-export",
  status: "done",
  logs: [],
  result: {
    phase: "review",
    path: "/tmp/deck.key",
    isStageDeck: true,
    isFwDeck: false,
    pages: [],
    skipped: [],
  },
  createdAt: 0,
  updatedAt: 0,
};

const doneJob: Job = {
  ...reviewJob,
  result: {
    phase: "done",
    path: "/tmp/deck.key",
    pngDir: "/tmp/out",
    pngs: ["deck.001.00.png"],
    clips: { "2": "deck.002.mov", "3": "deck.003.mov" },
    sequence: ["deck.001.00.png", "deck.002.mov", "deck.003.mov"],
    exportedClips: [2, 3],
    skipped: [],
  },
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    chooseKeynote: vi.fn(async () => ({ path: "/tmp/deck.key", name: "deck.key" })),
    chooseFolder: vi.fn(async () => ({ path: "/tmp/exports", name: "exports" })),
    startDskExport: vi.fn(async () => reviewJob),
    applyDskExport: vi.fn(async () => doneJob),
    pollJob: vi.fn(async (_id, onTick) => {
      const next = vi.mocked(applyDskExport).mock.calls.length ? doneJob : reviewJob;
      onTick(next);
      return next;
    }),
  };
});

beforeEach(() => {
  vi.mocked(startDskExport).mockReset();
  vi.mocked(applyDskExport).mockReset();
  vi.mocked(pollJob).mockReset();
  vi.mocked(chooseFolder).mockReset();
  vi.mocked(startDskExport).mockResolvedValue(reviewJob);
  vi.mocked(applyDskExport).mockResolvedValue(doneJob);
  vi.mocked(chooseFolder).mockResolvedValue({ path: "/tmp/exports", name: "exports" });
  vi.mocked(pollJob).mockImplementation(async (_id, onTick) => {
    const next = vi.mocked(applyDskExport).mock.calls.length ? doneJob : reviewJob;
    onTick(next);
    return next;
  });
});

async function exportOnce() {
  render(<DskExporter />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
  });
}

describe("DskExporter", () => {
  it("exports without a propose table", async () => {
    vi.mocked(chooseKeynote);
    vi.mocked(startDskExport);
    await exportOnce();

    expect(chooseFolder).toHaveBeenCalledWith("DSK workspace", "/tmp");
    expect(startDskExport).toHaveBeenCalledWith("/tmp/deck.key", {
      slides: undefined,
      exportDir: "/tmp/exports",
    });
    expect(screen.queryByRole("columnheader", { name: "Category" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Propose" })).not.toBeInTheDocument();
    expect(applyDskExport).toHaveBeenCalledWith("job-1");
    expect(screen.getByText(/Wrote \/tmp\/out — 1 PNG\(s\), 2 clip\(s\)/)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((el) => el.textContent)).toEqual([
      "deck.001.00.png",
      "deck.002.mov",
      "deck.003.mov",
    ]);
  });

  it("renders counts from an already-completed job without a second apply", async () => {
    vi.mocked(startDskExport).mockImplementationOnce(async () => doneJob);
    vi.mocked(pollJob).mockImplementationOnce(async (_id, onTick) => {
      onTick(doneJob);
      return doneJob;
    });

    render(<DskExporter />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });

    expect(applyDskExport).not.toHaveBeenCalled();
    expect(screen.getByText(/Wrote \/tmp\/out — 1 PNG\(s\), 2 clip\(s\)/)).toBeInTheDocument();
  });

  it("does not start an export when the folder picker is cancelled", async () => {
    vi.mocked(chooseFolder).mockRejectedValueOnce(new Error("Cancelled"));

    render(<DskExporter />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });

    expect(startDskExport).not.toHaveBeenCalled();
    expect(applyDskExport).not.toHaveBeenCalled();
    expect(screen.queryByText(/Wrote/)).not.toBeInTheDocument();
  });
});
