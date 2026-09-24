import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunNavContext } from "../src/nav";
import { ResizeTab } from "../src/tabs/ResizeTab";
import { getJob, pollJob, startResize } from "../src/api";
import type { Job } from "../src/api";

const REASON = "the IWA writer refused the deck before writing";
const NOTICE = `Offline hides aborted: ${REASON}. Offline hides are switched off for the next run.`;
const TIMEOUT_DETAIL = "Keynote did not finish; close wall_CG.key without saving, then re-apply into fresh output.";
const TIMEOUT_NOTICE =
  `Offline hides aborted: hide fallback session did not finish. ${TIMEOUT_DETAIL} ` +
  "Offline hides are switched off for the next run. Close wall_CG.key in Keynote before re-applying.";

const proposal = {
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
};

// The backend keeps the framing proposal on the errored job, persists `offlineHides: "off"`
// and adds the structured `offlineHidesAborted`; the UI keys on those, never on the error text.
const aborted: Job = {
  id: "job-1",
  kind: "resize",
  feature: "resize",
  status: "error",
  error: `Offline hides aborted: ${REASON}. Rerun with OBED_OFFLINE_HIDES=off.`,
  logs: [],
  result: {
    ...proposal,
    offlineHides: "off",
    offlineHidesAborted: { reason: REASON, detail: "", needsFreshOutput: false, outputPath: "/tmp/out/wall_CG.key" },
  },
  createdAt: 0,
  updatedAt: 0,
};

// A fallback-session timeout: Keynote may still hold a partly edited output deck.
const timedOut: Job = {
  ...aborted,
  error: `Offline hides aborted: hide fallback session did not finish (${TIMEOUT_DETAIL}). Rerun with OBED_OFFLINE_HIDES=off.`,
  result: {
    ...proposal,
    offlineHides: "off",
    offlineHidesAborted: {
      reason: "hide fallback session did not finish",
      detail: TIMEOUT_DETAIL,
      needsFreshOutput: true,
      outputPath: "/tmp/out/wall_CG.key",
      generation: 7,
    },
  },
};

const plainError: Job = {
  ...aborted,
  error: "Keynote went away",
  result: { ...proposal },
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    getJob: vi.fn(async () => aborted),
    pollJob: vi.fn(async () => aborted),
    startResize: vi.fn(actual.startResize),
    chooseFolder: vi.fn(async () => ({ path: "/tmp/exports-b", name: "exports-b" })),
  };
});

vi.mock("../src/prefs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/prefs")>();
  return { ...actual, useDefaultExportDir: () => "" };
});

function renderOpenRun(jobId = aborted.id) {
  return render(
    <RunNavContext.Provider
      value={{
        openInFeature: () => undefined,
        clearOpenRun: () => undefined,
        openRun: { feature: "resize", jobId },
      }}
    >
      <ResizeTab />
    </RunNavContext.Provider>
  );
}

function spyFetch(response: Job) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => response,
  } as Response);
}

async function clickApply() {
  const apply = await screen.findByRole("button", { name: "Resize with these framings" });
  await act(async () => {
    fireEvent.click(apply);
  });
}

function applyBody(fetchSpy: ReturnType<typeof spyFetch>, jobId = "job-1") {
  const call = fetchSpy.mock.calls.find(([url]) => url === `/api/resize/${jobId}/apply`);
  expect(call).toBeDefined();
  return JSON.parse(String((call![1] as RequestInit).body));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(getJob).mockImplementation(async () => aborted);
  vi.mocked(pollJob).mockImplementation(async () => aborted);
});

describe("Resize tab after an offline-hides abort", () => {
  it("shows the reason instead of the raw error and keeps Apply available", async () => {
    renderOpenRun();
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByText(aborted.error!)).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Resize with these framings" })).toBeInTheDocument();
  });

  it("re-applying sends offlineHides off, without launching anything by itself", async () => {
    const fetchSpy = spyFetch(aborted);
    renderOpenRun();
    await screen.findByText(NOTICE);
    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("/apply"))).toBe(false);

    await clickApply();

    expect(applyBody(fetchSpy).offlineHides).toBe("off");
  });

  it("a fresh Propose carries offline hides off, and so does the reopened proposal's Apply", async () => {
    // The new proposal stores `offlineHides: "off"` server-side, so a refresh or reopen
    // (which rebuilds the tab from the job alone) still sends it on Apply.
    const next: Job = {
      ...aborted,
      id: "job-2",
      status: "done",
      error: null,
      result: { ...proposal, offlineHides: "off" },
    };
    const fetchSpy = spyFetch(next);
    vi.mocked(pollJob).mockImplementation(async () => next);
    renderOpenRun();
    await screen.findByText(NOTICE);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Propose framings" }));
    });

    expect(vi.mocked(startResize).mock.lastCall?.[1]).toMatchObject({ offlineHides: "off" });
    const form = fetchSpy.mock.calls.find(([url]) => url === "/api/resize")![1]!.body as FormData;
    expect(form.get("offline_hides")).toBe("off");
    expect(
      await screen.findByText("Offline hides are switched off for this run after the last abort.")
    ).toBeInTheDocument();

    await clickApply();
    expect(applyBody(fetchSpy, "job-2").offlineHides).toBe("off");

    cleanup();
    vi.mocked(getJob).mockImplementation(async () => next);
    fetchSpy.mockClear();
    renderOpenRun("job-2");
    await clickApply();
    expect(applyBody(fetchSpy, "job-2").offlineHides).toBe("off");
  });

  it("dismissing the notice hides it but keeps offline hides off for the re-apply", async () => {
    const fetchSpy = spyFetch(aborted);
    renderOpenRun();
    await screen.findByText(NOTICE);

    const notice = screen.getByText(NOTICE).closest(".error-notice") as HTMLElement;
    await act(async () => {
      fireEvent.click(within(notice).getByRole("button", { name: "Dismiss error" }));
    });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();

    await clickApply();

    expect(applyBody(fetchSpy).offlineHides).toBe("off");
  });

  it("a timeout abort shows the recovery detail and blocks re-Apply until the output is confirmed closed", async () => {
    vi.mocked(getJob).mockImplementation(async () => timedOut);
    vi.mocked(pollJob).mockImplementation(async () => timedOut);
    const fetchSpy = spyFetch(timedOut);
    renderOpenRun();
    expect(await screen.findByText(TIMEOUT_NOTICE)).toBeInTheDocument();

    await clickApply();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("/apply"))).toBe(false);
    expect(
      screen.getByText(
        "Close wall_CG.key in Keynote and tick “I’ve closed wall_CG.key in Keynote” before re-applying."
      )
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" }));
    });
    await clickApply();

    expect(applyBody(fetchSpy)).toMatchObject({ offlineHides: "off", outputClosed: "/tmp/out/wall_CG.key", outputClosedUpTo: 7 });
  });

  it("a confirmed retry that times out again needs a fresh confirmation", async () => {
    // Sol r6 #3: the second abort keeps the job ID; only its new run generation differs.
    const first: Job = { ...timedOut, startedAt: 100 };
    const second: Job = { ...timedOut, startedAt: 200 };
    vi.mocked(getJob).mockImplementation(async () => first);
    vi.mocked(pollJob).mockImplementation(async () => second);
    const fetchSpy = spyFetch(second);
    renderOpenRun();
    await screen.findByText(TIMEOUT_NOTICE);

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" }));
    });
    await clickApply();
    expect(applyBody(fetchSpy)).toMatchObject({ outputClosed: "/tmp/out/wall_CG.key", outputClosedUpTo: 7 });

    const checkbox = await screen.findByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" });
    expect(checkbox).not.toBeChecked();
    fetchSpy.mockClear();
    await clickApply();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("/apply"))).toBe(false);
    expect(
      screen.getByText(
        "Close wall_CG.key in Keynote and tick “I’ve closed wall_CG.key in Keynote” before re-applying."
      )
    ).toBeInTheDocument();
  });

  it("changing the export folder clears the closure confirmation", async () => {
    // Sol r7 #1: a confirmation for one output must not ride along to another destination.
    vi.mocked(getJob).mockImplementation(async () => timedOut);
    vi.mocked(pollJob).mockImplementation(async () => timedOut);
    const fetchSpy = spyFetch(timedOut);
    renderOpenRun();
    await screen.findByText(TIMEOUT_NOTICE);

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" }));
    });
    expect(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" })).toBeChecked();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export to…" }));
    });
    expect(await screen.findByText("/tmp/exports-b")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" })).not.toBeChecked();

    await clickApply();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("/apply"))).toBe(false);
  });

  it("a fresh proposal after a timeout still requires confirming the shared output is closed", async () => {
    // The backend keys the unresolved closure by output path, so the new proposal job
    // carries `outputCloseRequired` even though it has no abort of its own.
    const fresh: Job = {
      ...aborted,
      id: "job-2",
      status: "done",
      error: null,
      result: { ...proposal, offlineHides: "off", outputCloseRequired: "/tmp/out/wall_CG.key", outputCloseUpTo: 7 },
    };
    vi.mocked(getJob).mockImplementation(async () => fresh);
    vi.mocked(pollJob).mockImplementation(async () => fresh);
    const fetchSpy = spyFetch(fresh);
    renderOpenRun("job-2");

    await clickApply();
    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("/apply"))).toBe(false);

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "I’ve closed wall_CG.key in Keynote" }));
    });
    await clickApply();

    expect(applyBody(fetchSpy, "job-2")).toMatchObject({ offlineHides: "off", outputClosed: "/tmp/out/wall_CG.key", outputClosedUpTo: 7 });
  });

  it("an ordinary error shows its message and leaves offline hides alone", async () => {
    vi.mocked(getJob).mockImplementation(async () => plainError);
    vi.mocked(pollJob).mockImplementation(async () => plainError);
    const fetchSpy = spyFetch(plainError);
    renderOpenRun();
    await screen.findByRole("button", { name: "Resize with these framings" });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /closed/ })).not.toBeInTheDocument();

    await clickApply();

    expect(applyBody(fetchSpy)).not.toHaveProperty("offlineHides");
    expect(applyBody(fetchSpy)).not.toHaveProperty("outputClosed");
    expect((await screen.findAllByText("Keynote went away")).length).toBeGreaterThan(0);
  });
});
