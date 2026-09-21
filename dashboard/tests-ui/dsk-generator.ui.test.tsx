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
    review: {
      schemaVersion: 2,
      revision: 0,
      source: { fingerprint: "fixture" },
      canvas: { width: 1920, height: 1080 },
      safeArea: { left: 43, right: 1877, bottom: 1065 },
      defaults: { viewport: { width: 935, height: 263, aspectLocked: true }, alignment: "centre" },
      compositions: [{
        id: "slide:50", sourceSlides: [50], layoutSlide: 50, category: "mixed", mediaLayout: "stacked", thumb: "slide-50.png",
        capabilities: { videoOnly: true, mask: true }, warnings: [],
        media: [
          { occurrenceId: "lower", assetId: "lower", kind: "movie", sourceSlide: 50, sourceItem: { kind: "movie", kindIndex: 0, archiveId: "lower" }, sourceModes: ["lw", "fw"], slot: { x: 0, y: 0, width: 1, height: 1 } },
          { occurrenceId: "upper", assetId: "upper", kind: "movie", sourceSlide: 50, sourceItem: { kind: "movie", kindIndex: 1, archiveId: "upper" }, sourceModes: ["lw", "fw"], slot: { x: 0, y: 0, width: 1, height: 1 } },
        ],
        previewLayers: [
          { kind: "media", occurrenceId: "lower", src: "lower.png", slot: { x: 0, y: 0, width: 1, height: 1 } },
          { kind: "media", occurrenceId: "upper", src: "upper.png", slot: { x: 0, y: 0, width: 1, height: 1 } },
        ],
        decision: { include: true, alignment: "inherit", viewport: null, source: "lw", contentMode: "video", masks: {} },
      }],
    },
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
    expect(applyDsk).toHaveBeenCalledWith("job-1", expect.objectContaining({ schemaVersion: 2, sourceFingerprint: "fixture" }), "/tmp/workspace", 0);
  });

  it("does not apply when the workspace picker is cancelled", async () => {
    vi.mocked(chooseFolder).mockRejectedValueOnce(new Error("Cancelled"));

    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });

    expect(applyDsk).not.toHaveBeenCalled();
  });

  it("shows an ordered mask selector for fully overlapping movie layers", () => {
    render(<DskGenerator />);
    expect(screen.getByRole("combobox", { name: "Mask media" })).toHaveValue("lower");
    fireEvent.change(screen.getByRole("combobox", { name: "Mask media" }), { target: { value: "upper" } });
    expect(screen.getByRole("combobox", { name: "Mask media" })).toHaveValue("upper");
  });
});
