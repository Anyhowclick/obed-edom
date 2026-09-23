import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunNavContext } from "../src/nav";
import { ResizeTab } from "../src/tabs/ResizeTab";
import { getJob, pollJob, startResize } from "../src/api";
import type { Job } from "../src/api";

const REASON = "the IWA writer refused the deck before writing";
const NOTICE = `Offline hides aborted: ${REASON}. Offline hides are switched off for the next run.`;

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

// The backend keeps the framing proposal on the errored job and adds the structured
// `offlineHidesAborted` field; the UI keys on that field, never on the error text.
const aborted: Job = {
  id: "job-1",
  kind: "resize",
  feature: "resize",
  status: "error",
  error: `Offline hides aborted: ${REASON}. Rerun with OBED_OFFLINE_HIDES=off.`,
  logs: [],
  result: { ...proposal, offlineHidesAborted: REASON },
  createdAt: 0,
  updatedAt: 0,
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

function applyBody(fetchSpy: ReturnType<typeof spyFetch>) {
  const call = fetchSpy.mock.calls.find(([url]) => url === "/api/resize/job-1/apply");
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

  it("a fresh Propose carries offline hides off, and so does that new job's Apply", async () => {
    const next: Job = { ...aborted, id: "job-2", status: "done", error: null, result: { ...proposal } };
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
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();

    await clickApply();
    const call = fetchSpy.mock.calls.find(([url]) => url === "/api/resize/job-2/apply");
    expect(JSON.parse(String((call![1] as RequestInit).body)).offlineHides).toBe("off");
  });

  it("dismissing the notice stops sending offlineHides", async () => {
    const fetchSpy = spyFetch(aborted);
    renderOpenRun();
    await screen.findByText(NOTICE);

    const notice = screen.getByText(NOTICE).closest(".error-notice") as HTMLElement;
    await act(async () => {
      fireEvent.click(within(notice).getByRole("button", { name: "Dismiss error" }));
    });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();

    await clickApply();

    expect(applyBody(fetchSpy)).not.toHaveProperty("offlineHides");
  });

  it("an ordinary error shows its message and leaves offline hides alone", async () => {
    vi.mocked(getJob).mockImplementation(async () => plainError);
    vi.mocked(pollJob).mockImplementation(async () => plainError);
    const fetchSpy = spyFetch(plainError);
    renderOpenRun();
    await screen.findByRole("button", { name: "Resize with these framings" });
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();

    await clickApply();

    expect(applyBody(fetchSpy)).not.toHaveProperty("offlineHides");
    expect((await screen.findAllByText("Keynote went away")).length).toBeGreaterThan(0);
  });
});
