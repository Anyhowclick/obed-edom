import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  attachPlayerDiagnostics,
  BuildPreview,
  injectPlayerDiagnostics,
  PREVIEW_ISSUE_SOURCE,
} from "../src/components/BuildPreview";
import { GenerateResultView } from "../src/components/GenerateResultView";
import { makeJob } from "./fakes/doc";
import type { HtmlPreviewResult, Job } from "../src/api";

const jobs = new Map<string, Job>();
const startHtmlPreview = vi.fn<(path: string, digest?: string) => Promise<Job>>();
const applyHtmlPreview = vi.fn<(jobId: string) => Promise<Job>>();
const cleanupHtmlPreview = vi.fn<(jobId: string) => Promise<Job>>();

async function pollJob(id: string, onTick: (job: Job) => void): Promise<Job> {
  const job = jobs.get(id);
  if (!job) throw new Error(`unknown job ${id}`);
  onTick(job);
  return job;
}

function remember(job: Job): Job {
  jobs.set(job.id, job);
  return job;
}

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    startHtmlPreview: (path: string, digest?: string) => startHtmlPreview(path, digest),
    applyHtmlPreview: (jobId: string) => applyHtmlPreview(jobId),
    cleanupHtmlPreview: (jobId: string) => cleanupHtmlPreview(jobId),
    pollJob,
  };
});

function readyJob(overrides: Partial<HtmlPreviewResult> = {}): Job {
  return {
    id: "prev-1",
    kind: "html-preview",
    feature: "html-preview",
    status: "done",
    logs: ["Exported"],
    error: null,
    result: {
      phase: "ready",
      slides: [
        { originalOrdinal: 1, skipped: false, playerIndex: 0, playerHash: "#0" },
        { originalOrdinal: 2, skipped: true, playerIndex: null, playerHash: null },
        { originalOrdinal: 3, skipped: false, playerIndex: 1, playerHash: "#1" },
      ],
      canvas: { width: 1920, height: 1080 },
      bytes: 95_000_000,
      reused: false,
      ...overrides,
    },
    createdAt: 0,
    updatedAt: 0,
  };
}

describe("BuildPreview", () => {
  beforeEach(() => {
    jobs.clear();
    startHtmlPreview.mockReset();
    applyHtmlPreview.mockReset();
    cleanupHtmlPreview.mockReset();
  });

  it("shows preparation, then a skipped-slide unavailable state", async () => {
    startHtmlPreview.mockImplementation(async () => remember(readyJob({ phase: "review", needsExport: true })));
    applyHtmlPreview.mockImplementation(async () => remember(readyJob()));

    render(<BuildPreview path="/decks/GW.key" />);
    expect(screen.getByRole("button", { name: "Preview builds" })).toBeEnabled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Preview builds" }));
    });

    await waitFor(() => {
      expect(screen.getByTitle("Build preview, slide 1")).toBeInTheDocument();
    });
    expect(screen.queryByText("Preparing build preview…")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Slide"), { target: { value: "2" } });
    });
    expect(
      screen.getByText(/Slide 2 is skipped in the source deck, so the HTML export omitted it/)
    ).toBeInTheDocument();
    expect(screen.queryByTitle(/Build preview, slide/)).not.toBeInTheDocument();
  });

  it("keeps the still-preview action after a failed export", async () => {
    startHtmlPreview.mockRejectedValue(new Error("Keynote is already running"));
    render(<BuildPreview path="/decks/GW.key" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Preview builds" }));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Keynote is already running");
    expect(screen.getByRole("button", { name: "Preview builds" })).toBeEnabled();
    expect(screen.queryByTitle(/Build preview/)).not.toBeInTheDocument();
  });

  it("records console, resource, and network failures from the player", async () => {
    const seen: string[] = [];
    const origFetch = window.fetch;
    window.fetch = (async () => new Response("missing", { status: 404 })) as typeof fetch;
    const restore = attachPlayerDiagnostics(window, (label) => seen.push(label));
    try {
      window.console.error("shader compile failed");
      const img = document.createElement("img");
      img.src = "missing.jpeg";
      document.body.appendChild(img);
      img.dispatchEvent(new Event("error"));
      await window.fetch("/assets/player/missing.json");
      expect(seen.some((item) => item.startsWith("console:") && item.includes("shader compile failed"))).toBe(true);
      expect(seen.some((item) => item.startsWith("resource:") && item.includes("missing.jpeg"))).toBe(true);
      expect(seen.some((item) => item.startsWith("network:") && item.includes("404"))).toBe(true);
    } finally {
      restore();
      window.fetch = origFetch;
      document.querySelectorAll('img[src="missing.jpeg"]').forEach((node) => node.remove());
    }
  });

  it("records an initial resource failure before iframe load", async () => {
    const player = `<!doctype html><html><head></head><body><script src="assets/player/main.js"></script><img src="missing-startup.jpeg"></body></html>`;
    const injected = injectPlayerDiagnostics(player);
    expect(injected.indexOf("data-obed-preview-diagnostics")).toBeLessThan(injected.indexOf("assets/player/main.js"));
    expect(injected.indexOf("data-obed-preview-diagnostics")).toBeLessThan(injected.indexOf("missing-startup.jpeg"));

    startHtmlPreview.mockImplementation(async () => remember(readyJob()));
    render(<BuildPreview path="/decks/GW.key" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Preview builds" }));
    });
    const iframe = await screen.findByTitle("Build preview, slide 1");
    expect(iframe).toBeInTheDocument();
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { source: PREVIEW_ISSUE_SOURCE, label: "resource: missing-startup.jpeg" },
        }),
      );
    });
    expect(screen.getByText(/Player issues:.*resource: missing-startup.jpeg/)).toBeInTheDocument();
  });

  it("unmounts the player when returning to stills", async () => {
    startHtmlPreview.mockImplementation(async () => remember(readyJob()));
    applyHtmlPreview.mockImplementation(async () => remember(readyJob()));
    render(<BuildPreview path="/decks/GW.key" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Preview builds" }));
    });
    await waitFor(() => expect(screen.getByTitle("Build preview, slide 1")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Back to stills" }));
    });
    expect(screen.queryByTitle(/Build preview/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview builds" })).toBeInTheDocument();
  });
});

describe("GenerateResultView stills plus preview", () => {
  it("adds Preview builds without printing deck paths", () => {
    const outputDir = "/tmp/out/2026-09-12-run";
    const { container } = render(
      <GenerateResultView
        job={makeJob({
          kind: "generate",
          feature: "generate",
          result: {
            stem: "wall",
            outputDir,
            lwKey: `${outputDir}/LW.key`,
            dskKey: `${outputDir}/DSK.key`,
            cuedDocx: `${outputDir}/cued.docx`,
            reviewPath: `${outputDir}/review.pdf`,
            previewFiles: { lw: [], dsk: [] },
            flags: [],
            lwCount: 3,
            dskCount: 2,
          },
        })}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "Preview builds" })).toBeInTheDocument();
    expect(container.textContent || "").not.toContain(outputDir);
  });
});
