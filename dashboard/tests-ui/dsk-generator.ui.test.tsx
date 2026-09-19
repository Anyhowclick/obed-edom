import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DskGenerator } from "../src/tabs/dsk/DskGenerator";
import { applyDsk, chooseFolder, pollJob, saveDskDecisions } from "../src/api";
import type { Job } from "../src/api";

const reviewJob: Job = {
  id: "job-1",
  kind: "dsk",
  feature: "dsk",
  status: "done",
  logs: [],
  result: {
    phase: "review",
    path: "/tmp/fw.key",
    pages: [
      {
        slide: 1,
        category: "static",
        buildCount: 1,
        movieCount: 0,
        isText: false,
        needsClip: false,
        decision: {
          slide: 1,
          include: true,
          action: "in_deck",
          anchor: "auto",
          keepSide: false,
          clip: null,
        },
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
    path: "/tmp/fw.key",
    deckPath: "/tmp/workspace/fw_DSK.key",
    exportDir: "/tmp/workspace",
    slidesKept: [1],
    skipped: [],
  },
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    chooseFolder: vi.fn(async () => ({ path: "/tmp/workspace", name: "workspace" })),
    saveDskDecisions: vi.fn(async () => reviewJob),
    applyDsk: vi.fn(async () => doneJob),
    pollJob: vi.fn(async (_id, onTick) => {
      onTick(doneJob);
      return doneJob;
    }),
  };
});

vi.mock("../src/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/sessions")>();
  return {
    ...actual,
    useCurrentJob: () => ({
      job: reviewJob,
      upsert: () => undefined,
      rename: async () => doneJob,
      error: null,
    }),
  };
});

beforeEach(() => {
  vi.mocked(chooseFolder).mockReset();
  vi.mocked(saveDskDecisions).mockReset();
  vi.mocked(applyDsk).mockReset();
  vi.mocked(pollJob).mockReset();
  vi.mocked(chooseFolder).mockResolvedValue({ path: "/tmp/workspace", name: "workspace" });
  vi.mocked(saveDskDecisions).mockResolvedValue(reviewJob);
  vi.mocked(applyDsk).mockResolvedValue(doneJob);
  vi.mocked(pollJob).mockImplementation(async (_id, onTick) => {
    onTick(doneJob);
    return doneJob;
  });
});

describe("DskGenerator workspace", () => {
  it("picks a workspace on Run and applies into that folder", async () => {
    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });

    expect(chooseFolder).toHaveBeenCalledWith("DSK workspace", undefined);
    expect(applyDsk).toHaveBeenCalledWith("job-1", expect.any(Array), "/tmp/workspace");
  });

  it("does not apply when the workspace picker is cancelled", async () => {
    vi.mocked(chooseFolder).mockRejectedValueOnce(new Error("Cancelled"));

    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });

    expect(applyDsk).not.toHaveBeenCalled();
  });
});
