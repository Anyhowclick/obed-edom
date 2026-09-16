import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DskExporter } from "../src/tabs/dsk/DskExporter";
import { chooseKeynote, startDskExport, applyDskExport, pollJob } from "../src/api";
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
    pages: [
      {
        slide: 1,
        category: "image",
        buildCount: 0,
        movieCount: 0,
        isText: false,
        needsClip: false,
        decision: { slide: 1, include: true, action: "stage", anchor: "auto", keepSide: false, clip: null },
      },
      {
        slide: 2,
        category: "movie",
        buildCount: 0,
        movieCount: 1,
        isText: false,
        needsClip: true,
        decision: { slide: 2, include: true, action: "clip", anchor: "auto", keepSide: false, clip: null },
      },
      {
        slide: 3,
        category: "mixed",
        buildCount: 1,
        movieCount: 1,
        isText: false,
        needsClip: true,
        decision: { slide: 3, include: true, action: "clip", anchor: "auto", keepSide: false, clip: "/tmp/deck.003.mov" },
      },
    ],
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
    startDskExport: vi.fn(async () => reviewJob),
    applyDskExport: vi.fn(async () => doneJob),
    pollJob: vi.fn(async (_id, onTick) => {
      onTick(reviewJob);
      return reviewJob;
    }),
  };
});

async function proposeReview() {
  render(<DskExporter />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
  });
}

describe("DskExporter review table", () => {
  it("shows Output per slide: stage PNG or clip", async () => {
    await proposeReview();

    const rows = screen.getAllByRole("row").slice(1); // skip header
    expect(rows[0]).toHaveTextContent("stage PNG(s)");
    expect(rows[1]).toHaveTextContent("clip (.mov)");
    expect(rows[2]).toHaveTextContent("clip (.mov)");
  });
});

describe("DskExporter done summary", () => {
  it("shows counts and the interleaved sequence order", async () => {
    vi.mocked(chooseKeynote);
    vi.mocked(startDskExport);
    await proposeReview();

    vi.mocked(pollJob).mockImplementationOnce(async (_id, onTick) => {
      onTick(doneJob);
      return doneJob;
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });

    expect(applyDskExport).toHaveBeenCalledWith("job-1");
    expect(screen.getByText(/Wrote \/tmp\/out — 1 PNG\(s\), 2 clip\(s\)/)).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items.map((el) => el.textContent)).toEqual([
      "deck.001.00.png",
      "deck.002.mov",
      "deck.003.mov",
    ]);
  });

  it("renders counts from an already-completed job without traversing Propose/Export", async () => {
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
      fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    });

    expect(applyDskExport).not.toHaveBeenCalled();
    expect(screen.getByText(/Wrote \/tmp\/out — 1 PNG\(s\), 2 clip\(s\)/)).toBeInTheDocument();
  });
});
