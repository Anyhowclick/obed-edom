import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RunNavContext } from "../src/nav";
import { ResizeTab } from "../src/tabs/ResizeTab";
import { GeneratorTab } from "../src/tabs/GeneratorTab";
import { applyResize, getJob, pollJob } from "../src/api";
import type { Job } from "../src/api";

const job: Job = {
  id: "job-1",
  kind: "resize",
  feature: "resize",
  status: "done",
  logs: [],
  result: {
    phase: "framing",
    path: "/tmp/wall.key",
    templatePath: "/tmp/CG.key",
    pages: [
      {
        slide: 1,
        index: 0,
        autoTemplateSlide: null,
        autoFellBack: false,
        needsAttention: false,
        noUsableFraming: false,
        candidates: [],
      },
    ],
  },
  createdAt: 0,
  updatedAt: 0,
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    getJob: vi.fn(async () => job),
    pollJob: vi.fn(async () => job),
    chooseFolder: vi.fn(async () => ({ path: "/tmp/exports", name: "exports" })),
  };
});

vi.mock("../src/prefs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/prefs")>();
  return {
    ...actual,
    useDefaultExportDir: () => "",
  };
});

function renderWithOpenRun(feature: "resize" | "generate", ui: React.ReactElement) {
  return render(
    <RunNavContext.Provider
      value={{ openInFeature: () => undefined, clearOpenRun: () => undefined, openRun: { feature, jobId: job.id } }}
    >
      {ui}
    </RunNavContext.Provider>
  );
}

describe("export row only appears once framings exist", () => {
  it("Resize tab renders no Export to… button with no job", () => {
    render(<ResizeTab />);
    expect(screen.queryByRole("button", { name: "Export to…" })).not.toBeInTheDocument();
  });

  it("Resize tab renders the Export to… button once a proposal is in phase: framing", async () => {
    renderWithOpenRun("resize", <ResizeTab />);
    expect(await screen.findByRole("button", { name: "Export to…" })).toBeInTheDocument();
  });

  it("Generator tab renders no Export to… button", () => {
    render(<GeneratorTab />);
    expect(screen.queryByRole("button", { name: "Export to…" })).not.toBeInTheDocument();
  });

  it("shows the propose-time proposalExportDir as the default label, not the live settings default", async () => {
    const proposalJob: Job = {
      ...job,
      result: { ...job.result, proposalExportDir: "/tmp/proposed-exports" },
    };
    vi.mocked(getJob).mockResolvedValueOnce(proposalJob);
    vi.mocked(pollJob).mockResolvedValueOnce(proposalJob);

    renderWithOpenRun("resize", <ResizeTab />);
    await screen.findByRole("button", { name: "Export to…" });
    expect(await screen.findByText("/tmp/proposed-exports")).toBeInTheDocument();
  });

  it("shows no Use default button until the operator picks a folder", async () => {
    renderWithOpenRun("resize", <ResizeTab />);
    await screen.findByRole("button", { name: "Export to…" });
    expect(screen.queryByRole("button", { name: "Use default" })).not.toBeInTheDocument();
  });

  it("applyResize puts exportDir in the request body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => job,
    } as Response);

    await applyResize("job-1", undefined, "/tmp/exports");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/resize/job-1/apply",
      expect.objectContaining({ body: JSON.stringify({ exportDir: "/tmp/exports" }) })
    );
    fetchSpy.mockRestore();
  });

  it("applyResize sends an explicit empty exportDir when the row was cleared", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => job,
    } as Response);

    await applyResize("job-1", undefined, "");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/resize/job-1/apply",
      expect.objectContaining({ body: JSON.stringify({ exportDir: "" }) })
    );
    fetchSpy.mockRestore();
  });

  it("picking a folder in ExportDestinationRow and clicking Apply sends that folder to applyResize", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => job,
    } as Response);

    renderWithOpenRun("resize", <ResizeTab />);

    const pickButton = await screen.findByRole("button", { name: "Export to…" });
    await act(async () => {
      fireEvent.click(pickButton);
    });
    expect(await screen.findByText("/tmp/exports")).toBeInTheDocument();

    const applyButton = screen.getByRole("button", { name: "Resize with these framings" });
    await act(async () => {
      fireEvent.click(applyButton);
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/resize/job-1/apply",
      expect.objectContaining({
        body: expect.stringContaining(`"exportDir":"/tmp/exports"`),
      })
    );
    fetchSpy.mockRestore();
  });

  it("clicking Use default then Apply sends an explicit empty exportDir", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => job,
    } as Response);

    renderWithOpenRun("resize", <ResizeTab />);

    const pickButton = await screen.findByRole("button", { name: "Export to…" });
    await act(async () => {
      fireEvent.click(pickButton);
    });
    const resetButton = await screen.findByRole("button", { name: "Use default" });
    await act(async () => {
      fireEvent.click(resetButton);
    });
    expect(screen.queryByRole("button", { name: "Use default" })).not.toBeInTheDocument();

    const applyButton = screen.getByRole("button", { name: "Resize with these framings" });
    await act(async () => {
      fireEvent.click(applyButton);
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/resize/job-1/apply",
      expect.objectContaining({
        body: expect.stringContaining(`"exportDir":""`),
      })
    );
    fetchSpy.mockRestore();
  });
});
