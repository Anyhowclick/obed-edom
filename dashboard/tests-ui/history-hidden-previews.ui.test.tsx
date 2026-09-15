import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HistoryTab } from "../src/tabs/HistoryTab";
import { makeJob } from "./fakes/doc";

const previewName = "slide-1.png";
const job = makeJob({
  kind: "generate",
  feature: "generate",
  artifacts: { ok: true, missing: [] },
  result: {
    stem: "sermon",
    outputDir: "/tmp/output/sermon",
    previewFiles: { lw: [previewName], dsk: [] },
    flags: [],
    lwCount: 1,
    dskCount: 0,
  },
});
const listJobs = vi.fn(async () => [job]);

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    listJobs: () => listJobs(),
  };
});

describe("hidden History previews", () => {
  beforeEach(() => {
    listJobs.mockClear();
  });

  it("does not render preview images until History is opened", async () => {
    const { rerender } = render(<HistoryTab active={false} />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(listJobs).not.toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: "LW 1" })).not.toBeInTheDocument();

    rerender(<HistoryTab active />);

    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(1));
    const preview = await screen.findByRole("img", { name: "LW 1" });
    expect(preview).toHaveAttribute("src", `/api/jobs/${job.id}/previews/lw/${previewName}`);
  });
});
