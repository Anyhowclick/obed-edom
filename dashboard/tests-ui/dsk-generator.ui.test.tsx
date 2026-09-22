import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DskGenerator } from "../src/tabs/dsk/DskGenerator";
import { applyDsk, chooseFolder, chooseKeynote, FieldError, pollJob, saveDskDecisions, startDsk } from "../src/api";
import type { Job } from "../src/api";
import { DSK_TEMPLATE_KEY } from "../src/prefs";

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

const doneJobWithNotes: Job = {
  ...doneJob,
  result: {
    phase: "done",
    path: "/tmp/fw.key",
    deckPath: "/tmp/workspace/fw_DSK.key",
    exportDir: "/tmp/workspace",
    slidesKept: [1],
    skipped: [{ slide: 4, reason: "empty" }],
    warnings: ["Slide 7 measured a thin video band."],
    overflows: [12],
  },
};

const queuedJob: Job = {
  id: "job-2",
  kind: "dsk",
  feature: "dsk",
  status: "queued",
  logs: [],
  result: null,
  createdAt: 0,
  updatedAt: 0,
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    chooseFolder: vi.fn(async () => ({ path: "/tmp/workspace", name: "workspace" })),
    chooseKeynote: vi.fn(async () => ({ path: "/tmp/fw.key", name: "fw.key" })),
    startDsk: vi.fn(async () => queuedJob),
    saveDskDecisions: vi.fn(async () => reviewJob),
    applyDsk: vi.fn(async () => doneJob),
    reveal: vi.fn(async () => undefined),
    pollJob: vi.fn(async (_id, onTick) => {
      onTick(doneJob);
      return doneJob;
    }),
  };
});

type SessionMock = { job: Job | null; upsert: (job: Job) => void; rename: (name: string) => Promise<Job>; error: string | null };

const currentJobMock = vi.fn<() => SessionMock>(() => ({
  job: reviewJob,
  upsert: () => undefined,
  rename: async () => doneJob,
  error: null,
}));

vi.mock("../src/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/sessions")>();
  return {
    ...actual,
    useCurrentJob: () => currentJobMock(),
  };
});

function mockSession(initialJob: Job | null) {
  let current = initialJob;
  currentJobMock.mockImplementation(() => ({
    job: current,
    upsert: (job: Job) => {
      current = job;
    },
    rename: async () => doneJob,
    error: null,
  }));
}

beforeEach(() => {
  vi.mocked(chooseFolder).mockReset();
  vi.mocked(chooseKeynote).mockReset();
  vi.mocked(startDsk).mockReset();
  vi.mocked(saveDskDecisions).mockReset();
  vi.mocked(applyDsk).mockReset();
  vi.mocked(pollJob).mockReset();
  currentJobMock.mockReset();
  vi.mocked(chooseFolder).mockResolvedValue({ path: "/tmp/workspace", name: "workspace" });
  vi.mocked(chooseKeynote).mockResolvedValue({ path: "/tmp/fw.key", name: "fw.key" });
  vi.mocked(startDsk).mockResolvedValue(queuedJob);
  vi.mocked(saveDskDecisions).mockResolvedValue(reviewJob);
  vi.mocked(applyDsk).mockResolvedValue(doneJob);
  vi.mocked(pollJob).mockImplementation(async (_id, onTick) => {
    onTick(doneJob);
    return doneJob;
  });
  mockSession(reviewJob);
});

describe("DskGenerator workspace", () => {
  it("picks a workspace on Run and applies into that folder, sending the current template", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });

    expect(chooseFolder).toHaveBeenCalledWith("DSK workspace", undefined);
    expect(applyDsk).toHaveBeenCalledWith(
      "job-1",
      expect.objectContaining({ schemaVersion: 2, sourceFingerprint: "fixture" }),
      "/tmp/workspace",
      0,
      "/tmp/template.key"
    );
  });

  it("does not apply when the workspace picker is cancelled", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
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

function getWell(label: string) {
  const strong = screen.getByText((_content, node) => node?.tagName === "STRONG" && !!node.textContent?.startsWith(label));
  return strong.closest(".col") as HTMLElement;
}

/** The merged "DSK decks" card renders each field as a `.dsk-deck-row` with its own label div. */
function getDeckRow(label: string) {
  const rowLabel = screen.getByText(
    (_content, node) => !!node?.classList.contains("dsk-deck-row-label") && !!node.textContent?.startsWith(label)
  );
  return rowLabel.closest(".dsk-deck-row") as HTMLElement;
}

describe("DskGenerator DSK template", () => {
  it("shows the remembered template as the default: file name, folder path, and a default label, no required marker", () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/somewhere/template.key", name: "template.key" }));
    mockSession(null);

    render(<DskGenerator />);

    const row = getDeckRow("DSK template");
    expect(within(row).getByText("template.key")).toBeInTheDocument();
    expect(within(row).getByText("default")).toBeInTheDocument();
    expect(within(row).getByText("/tmp/somewhere")).toBeInTheDocument();
    expect(within(row).queryByText("Required")).toBeNull();
    expect(within(row).getByRole("button", { name: "Change DSK template" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Forget DSK template" })).toBeInTheDocument();
  });

  it("shows the required state with a required marker and Choose on this Mac when no template is remembered", () => {
    mockSession(null);
    render(<DskGenerator />);

    const row = getDeckRow("DSK template");
    expect(within(row).getByText("Required")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Choose on this Mac" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Change DSK template" })).toBeNull();
  });

  it("Forget returns the row to the required state and disables Propose", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
    mockSession(null);
    render(<DskGenerator />);

    const row = getDeckRow("DSK template");
    await act(async () => {
      fireEvent.click(within(row).getByRole("button", { name: "Forget DSK template" }));
    });

    expect(within(row).getByText("Required")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Choose on this Mac" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose" })).toBeDisabled();
  });

  it("disables Propose and shows a reason until a template is chosen", async () => {
    mockSession(null);
    render(<DskGenerator />);

    await act(async () => {
      fireEvent.click(within(getWell("Finalised FW .key")).getByRole("button", { name: "Choose on this Mac" }));
    });

    expect(screen.getByRole("button", { name: "Propose" })).toBeDisabled();
    expect(screen.getByText("Choose the DSK template to continue.")).toBeInTheDocument();
  });

  it("disables Run and shows a reason until a template is chosen", () => {
    mockSession(reviewJob);
    render(<DskGenerator />);

    const runButton = screen.getByRole("button", { name: "Run" });
    expect(runButton).toBeDisabled();
    expect(within(runButton.closest(".actions") as HTMLElement).getByText("Choose the DSK template to continue.")).toBeInTheDocument();
  });

  it("sends the chosen template to startDsk as dskTemplate", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
    mockSession(null);
    render(<DskGenerator />);

    await act(async () => {
      fireEvent.click(within(getWell("Finalised FW .key")).getByRole("button", { name: "Choose on this Mac" }));
    });
    expect(screen.getByRole("button", { name: "Propose" })).toBeEnabled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    });

    expect(startDsk).toHaveBeenCalledWith("/tmp/fw.key", expect.objectContaining({ dskTemplate: "/tmp/template.key" }));
  });

  it("shows a FieldError from startDsk inline on the template row only, once, and not in the global notice", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/missing.key", name: "missing.key" }));
    mockSession(null);
    vi.mocked(startDsk).mockRejectedValueOnce(
      new FieldError("dskTemplate", "DSK template not found at /tmp/missing.key. Choose it again with \u201cChoose on this Mac\u201d.")
    );
    render(<DskGenerator />);

    await act(async () => {
      fireEvent.click(within(getWell("Finalised FW .key")).getByRole("button", { name: "Choose on this Mac" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    });

    const templateRow = getDeckRow("DSK template");
    const alert = within(templateRow).getByRole("alert");
    expect(alert).toHaveTextContent("DSK template not found at /tmp/missing.key.");
    const changeButton = within(templateRow).getByRole("button", { name: "Change DSK template" });
    expect(changeButton.getAttribute("aria-describedby")?.split(" ")).toContain(alert.id);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("clears the inline template error from the whole document once a new template is chosen", async () => {
    const message = "DSK template not found at /tmp/missing.key.";
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/missing.key", name: "missing.key" }));
    mockSession(null);
    vi.mocked(startDsk).mockRejectedValueOnce(new FieldError("dskTemplate", message));
    render(<DskGenerator />);

    await act(async () => {
      fireEvent.click(within(getWell("Finalised FW .key")).getByRole("button", { name: "Choose on this Mac" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    });
    expect(screen.getByText(message)).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(getDeckRow("DSK template")).getByRole("button", { name: "Change DSK template" }));
    });

    expect(screen.queryByText(message)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sends the newly chosen template to applyDsk after a FieldError, not the stale one", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/old.key", name: "old.key" }));
    mockSession(reviewJob);
    vi.mocked(applyDsk).mockRejectedValueOnce(new FieldError("dskTemplate", "DSK template not found at /tmp/old.key."));
    vi.mocked(chooseKeynote).mockResolvedValueOnce({ path: "/tmp/new.key", name: "new.key" });
    render(<DskGenerator />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });
    expect(within(getDeckRow("DSK template")).getByRole("alert")).toHaveTextContent("DSK template not found at /tmp/old.key.");

    await act(async () => {
      fireEvent.click(within(getDeckRow("DSK template")).getByRole("button", { name: "Change DSK template" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
    });

    expect(applyDsk).toHaveBeenLastCalledWith(
      "job-1",
      expect.objectContaining({ schemaVersion: 2, sourceFingerprint: "fixture" }),
      "/tmp/workspace",
      0,
      "/tmp/new.key"
    );
  });
});

describe("DskGenerator reference deck", () => {
  it("shows Standard video band and a Choose action when blank", () => {
    mockSession(null);
    render(<DskGenerator />);

    const row = getDeckRow("Reference deck");
    expect(within(row).getByText("Standard video band")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Choose reference deck" })).toBeInTheDocument();
  });

  it("shows the chosen reference file and a Clear action, then clears back to blank", async () => {
    mockSession(null);
    vi.mocked(chooseKeynote).mockResolvedValueOnce({ path: "/tmp/ref.key", name: "ref.key" });
    render(<DskGenerator />);

    const row = getDeckRow("Reference deck");
    await act(async () => {
      fireEvent.click(within(row).getByRole("button", { name: "Choose reference deck" }));
    });
    expect(within(row).getByText("ref.key")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Clear reference deck" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(row).getByRole("button", { name: "Clear reference deck" }));
    });
    expect(within(row).getByText("Standard video band")).toBeInTheDocument();
  });
});

describe("DskGenerator result card", () => {
  it("renders the deck file name, slide count, and full path, with no Notes section when there is nothing to note", () => {
    mockSession(doneJob);
    render(<DskGenerator />);

    expect(screen.getByText("fw_DSK.key · 1 slides")).toBeInTheDocument();
    expect(screen.getByText("/tmp/workspace/fw_DSK.key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show in Finder" })).toBeInTheDocument();
    expect(screen.getByText(/Next: open the Exporter tab/)).toBeInTheDocument();
    expect(screen.queryByText("Notes")).toBeNull();
  });

  it("lists skipped slides, warnings, and overflows as Notes when present", () => {
    mockSession(doneJobWithNotes);
    render(<DskGenerator />);

    expect(screen.getByText("Notes")).toBeInTheDocument();
    expect(screen.getByText("Skipped slide 4 — empty")).toBeInTheDocument();
    expect(screen.getByText("Slide 7 measured a thin video band.")).toBeInTheDocument();
    expect(screen.getByText("Overflow on slide 12")).toBeInTheDocument();
  });
});

describe("DskGenerator stage progress overlay", () => {
  it("maps job.progress to a Step N of M overlay with elapsed time and collapsed details while running", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
    mockSession(reviewJob);
    let resolveTick: (() => void) | undefined;
    vi.mocked(pollJob).mockImplementation(
      (_id, onTick) =>
        new Promise<Job>((resolve) => {
          onTick({
            ...doneJob,
            status: "running",
            logs: ["Assembling Alpha_Wall_DSK.key…"],
            details: ["opened archive", "wrote iwa"],
            progress: { step: 2, steps: 3, label: "Assembling the DSK deck" },
            startedAt: Math.floor(Date.now() / 1000) - 3,
          });
          resolveTick = () => resolve(doneJob);
        })
    );

    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.getByRole("heading", { name: "Building the DSK deck…" })).toBeInTheDocument();
    expect(screen.getByText("Step 2 of 3 — Assembling the DSK deck")).toBeInTheDocument();
    expect(screen.getByText(/^Elapsed \d:\d\d$/)).toBeInTheDocument();
    const details = screen.getByText("Technical details").closest("details");
    expect(details).not.toHaveAttribute("open");

    await act(async () => {
      resolveTick?.();
      await new Promise((r) => setTimeout(r, 0));
    });
  });

  it("titles the overlay for Propose as preparing the review, not building the deck", async () => {
    localStorage.setItem(DSK_TEMPLATE_KEY, JSON.stringify({ path: "/tmp/template.key", name: "template.key" }));
    mockSession(null);
    let resolvePoll: (() => void) | undefined;
    vi.mocked(pollJob).mockImplementation(
      () =>
        new Promise<Job>((resolve) => {
          resolvePoll = () => resolve(reviewJob);
        })
    );
    render(<DskGenerator />);
    await act(async () => {
      fireEvent.click(within(getWell("Finalised FW .key")).getByRole("button", { name: "Choose on this Mac" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Propose" }));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.getByRole("heading", { name: "Preparing the review…" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Building the DSK deck…" })).not.toBeInTheDocument();

    await act(async () => {
      resolvePoll?.();
      await new Promise((r) => setTimeout(r, 0));
    });
  });
});
