import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MapsExportPlan } from "../src/api";
import { DEFAULT_HIGHLIGHT_COLOUR, highlightColour as currentHighlightColour } from "../src/maps/highlight";
import { flushMicrotasks, renderMapsTab, tick } from "./renderMapsTab";
import { MAPS_SAVE_IDLE_MS } from "../src/maps/saveQueue";
import { mapsApiScript, putSettings, saveMapsState, fetchMapsExportPlan } from "./fakes/mapsApi";
import { makeCamera, makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { refreshHighlightColour } from "../src/prefs";

const captureExportRaster = vi.fn(async (..._args: unknown[]) => new Blob(["still"]));
const captureIsolatePair = vi.fn(async (..._args: unknown[]) => null);
vi.mock("../src/maps/captureExport", () => ({
  captureExportRaster: (...args: unknown[]) => captureExportRaster(...args),
  captureIsolatePair: (...args: unknown[]) => captureIsolatePair(...args),
}));

const captureFlyFrames = vi.fn(async (..._args: unknown[]) => 1);
vi.mock("../src/maps/captureFly", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/maps/captureFly")>();
  return {
    ...actual,
    captureFlyFrames: (...args: unknown[]) => captureFlyFrames(...args),
  };
});

beforeEach(() => {
  vi.useFakeTimers();
  captureExportRaster.mockClear();
  captureIsolatePair.mockClear();
  captureFlyFrames.mockClear();
  saveMapsState.mockClear();
  fetchMapsExportPlan.mockClear();
  refreshHighlightColour();
});

afterEach(() => {
  vi.useRealTimers();
});

function buildExportSetup() {
  const camA = makeCamera({ lat: 1.3, lon: 103.8 });
  const slideA = makeSlide({ id: "s1", camera: camA });
  const job = makeJob({
    result: {
      defaultStyle: "positron",
      crop: "center+cg",
      exportLw: true,
      exportCg: false,
      exportDsk: false,
      hiddenLayers: [],
      cachedCountries: [],
      attribution: "stamp",
      assets: [],
      slides: [slideA],
      links: [],
      stateRevision: 1,
    },
  });
  const plan: MapsExportPlan = {
    links: [],
    stills: [{ slideId: "s1", style: "positron", camera: camA, highlights: [] }],
    plates: [],
  };
  return { job, plan };
}

function buildFullExportSetup() {
  const camA = makeCamera({ lat: 1.3, lon: 103.8 });
  const camB = makeCamera({ lat: 1.35, lon: 103.85 });
  const slideA = makeSlide({ id: "s1", camera: camA });
  const slideB = makeSlide({ id: "s2", camera: camB });
  const job = makeJob({
    result: {
      defaultStyle: "positron",
      crop: "center+cg",
      exportLw: true,
      exportCg: true,
      exportDsk: false,
      hiddenLayers: [],
      cachedCountries: [],
      attribution: "stamp",
      assets: [],
      slides: [slideA, slideB],
      links: [],
      stateRevision: 1,
    },
  });
  const movieLink = { from: "s1", to: "s2", kind: "movie", duration: 1, playWithoutClick: true };
  const plan: MapsExportPlan = {
    links: [movieLink],
    stills: [
      { slideId: "s1", style: "positron", camera: camA, highlights: [] },
      { slideId: "s2", style: "positron", camera: camB, highlights: ["h1"] },
    ],
    plates: [
      { plateId: "p1", plateW: 1080, plateH: 1080, slideIds: ["s1"], camera: camA, style: "positron", highlights: [] },
    ],
    cg: {
      links: [movieLink],
      stills: [],
      plates: [],
      affectedSlideIds: ["s1", "s2"],
    },
  };
  return { job, plan };
}

async function startExport() {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Export" }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
  });
}

describe("highlight colour readiness gates export", () => {
  it("waits for a slow settings response before rendering stills", async () => {
    const { job, plan } = buildExportSetup();
    await renderMapsTab({ job });
    mapsApiScript.fetchMapsExportPlan.resolve(plan);

    let resolveSettings!: (value: { highlightColour: string; reuseThreshold: number; reusePairings: boolean; reusePreviews: boolean; defaultExportDir: string }) => void;
    const deferred = new Promise<Parameters<typeof resolveSettings>[0]>((resolve) => {
      resolveSettings = resolve;
    });
    mapsApiScript.getSettings.deferOnce(deferred);
    await act(async () => {
      refreshHighlightColour();
    });

    await startExport();

    for (let i = 0; i < 5; i++) await flushMicrotasks();
    expect(captureExportRaster).not.toHaveBeenCalled();

    await act(async () => {
      resolveSettings({
        reuseThreshold: 0,
        reusePairings: false,
        reusePreviews: false,
        defaultExportDir: "",
        highlightColour: "#123456",
      });
    });
    for (let i = 0; i < 20; i++) await flushMicrotasks();

    expect(captureExportRaster).toHaveBeenCalled();
    expect(currentHighlightColour()).toBe("#123456");
  });

  it("falls back to the default colour on both live and offscreen paint when settings fetch fails", async () => {
    const { job, plan } = buildExportSetup();
    await renderMapsTab({ job });
    mapsApiScript.fetchMapsExportPlan.resolve(plan);

    const rejected = Promise.reject(new Error("network down"));
    rejected.catch(() => undefined);
    mapsApiScript.getSettings.deferOnce(rejected);
    await act(async () => {
      refreshHighlightColour();
    });

    await startExport();

    for (let i = 0; i < 20; i++) await flushMicrotasks();

    expect(captureExportRaster).toHaveBeenCalled();
    expect(currentHighlightColour()).toBe(DEFAULT_HIGHLIGHT_COLOUR);
    expect(document.documentElement.style.getPropertyValue("--maps-highlight")).toBe(DEFAULT_HIGHLIGHT_COLOUR);
  });

  it("uses one consistent highlight colour across every capture even when settings resolve late, after the 2s fallback, mid-export", async () => {
    const { job, plan } = buildFullExportSetup();
    await renderMapsTab({ job });
    mapsApiScript.fetchMapsExportPlan.resolve(plan);

    let resolveSettings!: (value: { highlightColour: string; reuseThreshold: number; reusePairings: boolean; reusePreviews: boolean; defaultExportDir: string }) => void;
    const deferred = new Promise<Parameters<typeof resolveSettings>[0]>((resolve) => {
      resolveSettings = resolve;
    });
    mapsApiScript.getSettings.deferOnce(deferred);
    await act(async () => {
      refreshHighlightColour();
    });

    // Block the very first capture (the s1 still, via captureExportRaster) on a
    // deferred promise so we can resolve settings to a different colour while a
    // capture is genuinely in flight, rather than relying on a timing race.
    let releaseFirstCapture!: () => void;
    const firstCaptureGate = new Promise<void>((resolve) => {
      releaseFirstCapture = resolve;
    });
    captureExportRaster.mockImplementationOnce(async (..._args: unknown[]) => {
      await firstCaptureGate;
      return new Blob(["still"]);
    });

    await startExport();

    // Let the 2s fallback timer win the race before the settings request ever settles.
    await tick(2000);
    for (let i = 0; i < 10; i++) await flushMicrotasks();

    // The first capture should now be blocked, mid-flight, against the fallback colour.
    expect(captureExportRaster).toHaveBeenCalledTimes(1);
    expect(captureIsolatePair).not.toHaveBeenCalled();
    expect(captureFlyFrames).not.toHaveBeenCalled();

    // While that capture is still blocked, the settings request finally resolves to a
    // different colour. Because the highlight colour is snapshot once (`readyColour`)
    // before captures start, this late resolution must NOT leak into any capture call.
    await act(async () => {
      resolveSettings({
        reuseThreshold: 0,
        reusePairings: false,
        reusePreviews: false,
        defaultExportDir: "",
        highlightColour: "#abcdef",
      });
    });
    for (let i = 0; i < 10; i++) await flushMicrotasks();

    // Still blocked: only the first capture has been invoked.
    expect(captureExportRaster).toHaveBeenCalledTimes(1);
    expect(captureIsolatePair).not.toHaveBeenCalled();
    expect(captureFlyFrames).not.toHaveBeenCalled();

    // Now release the blocked capture and let the rest of the export run to completion.
    await act(async () => {
      releaseFirstCapture();
    });
    for (let i = 0; i < 20; i++) await flushMicrotasks();

    expect(captureExportRaster).toHaveBeenCalledTimes(2);
    expect(captureIsolatePair).toHaveBeenCalledTimes(1);
    expect(captureFlyFrames).toHaveBeenCalledTimes(2);

    const allOptions = [
      ...captureExportRaster.mock.calls.map((call) => call[0] as { highlightColour?: string }),
      ...captureIsolatePair.mock.calls.map((call) => call[0] as { highlightColour?: string }),
      ...captureFlyFrames.mock.calls.map((call) => call[0] as { highlightColour?: string }),
    ];
    expect(allOptions).toHaveLength(5);
    for (const opts of allOptions) {
      expect(opts.highlightColour).toBe(DEFAULT_HIGHLIGHT_COLOUR);
    }

    const usedColours = new Set(allOptions.map((opts) => opts.highlightColour));
    expect(usedColours.size).toBe(1);
    expect(usedColours.has("#abcdef")).toBe(false);
  });

  it("does not save, fetch a plan, or capture anything when cancelled while highlightColourReady() is pending", async () => {
    const { job, plan } = buildFullExportSetup();
    await renderMapsTab({ job });
    mapsApiScript.fetchMapsExportPlan.resolve(plan);

    let resolveSettings!: (value: { highlightColour: string; reuseThreshold: number; reusePairings: boolean; reusePreviews: boolean; defaultExportDir: string }) => void;
    const deferred = new Promise<Parameters<typeof resolveSettings>[0]>((resolve) => {
      resolveSettings = resolve;
    });
    mapsApiScript.getSettings.deferOnce(deferred);
    await act(async () => {
      refreshHighlightColour();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });

    await act(async () => {
      for (const button of screen.getAllByRole("button", { name: "Cancel" })) {
        fireEvent.click(button);
      }
    });

    await act(async () => {
      resolveSettings({
        reuseThreshold: 0,
        reusePairings: false,
        reusePreviews: false,
        defaultExportDir: "",
        highlightColour: "#123456",
      });
    });
    for (let i = 0; i < 20; i++) await flushMicrotasks();

    expect(saveMapsState).not.toHaveBeenCalled();
    expect(fetchMapsExportPlan).not.toHaveBeenCalled();
    expect(captureExportRaster).not.toHaveBeenCalled();
    expect(captureIsolatePair).not.toHaveBeenCalled();
    expect(captureFlyFrames).not.toHaveBeenCalled();
  });
});

describe("Selected regions colour wheel", () => {
  it("writes the global highlight colour from Selected regions", async () => {
    await renderMapsTab();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#123abc" } });
    });
    await tick(300);

    expect(putSettings).toHaveBeenCalledWith({ highlightColour: "#123abc" });
  });

  it("stores a per-region colour override on the slide", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["SGP"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "SGP" }));
    });

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#00aaff" } });
    });
    await tick(MAPS_SAVE_IDLE_MS);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{ highlightColours?: Record<string, string> }>;
    expect(slides[0]?.highlightColours).toEqual({ SGP: "#00aaff" });
    expect(screen.getByRole("button", { name: "Default" })).toBeInTheDocument();
  });

  it("stores no-fill on the selected highlight and still lets the operator pick a colour", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["SGP"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "SGP" }));
    });

    const noFill = screen.getByRole("button", { name: "No fill" });
    await act(async () => {
      fireEvent.click(noFill);
    });
    await tick(MAPS_SAVE_IDLE_MS);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{ highlightColours?: Record<string, string> }>;
    expect(slides[0]?.highlightColours).toEqual({ SGP: "none" });
    expect(screen.getByLabelText("Highlight colour")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Default" })).toBeInTheDocument();

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#112233" } });
    });
    await tick(MAPS_SAVE_IDLE_MS);
    const after = mapsApiScript.saveMapsState.calls[mapsApiScript.saveMapsState.calls.length - 1].document
      .slides as Array<{ highlightColours?: Record<string, string> }>;
    expect(after[0]?.highlightColours).toEqual({ SGP: "#112233" });
  });

  it("tints each Properties chip from that highlight's fill", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({
              highlights: ["SGP", "IDN"],
              highlightColours: { SGP: "none", IDN: "#00aaff" },
            }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });

    const empty = screen.getByRole("button", { name: "SGP" }).closest(".maps-hl-chip");
    const filled = screen.getByRole("button", { name: "IDN" }).closest(".maps-hl-chip");
    expect(empty).toHaveClass("none");
    expect(filled).not.toHaveClass("none");
    expect((filled as HTMLElement).style.getPropertyValue("--maps-highlight")).toBe("#00aaff");
  });

  it("does not apply a pending colour override to another slide", async () => {
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({ id: "s1", title: "Slide 1", highlights: ["SGP"] }),
            makeSlide({ id: "s2", title: "Slide 2", highlights: ["SGP"] }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "SGP" }));
    });

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#00aaff" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Select slide Slide 2/ }));
    });
    await tick(MAPS_SAVE_IDLE_MS);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{ id: string; highlightColours?: Record<string, string> }>;
    expect(slides.find((slide) => slide.id === "s1")?.highlightColours).toEqual({ SGP: "#00aaff" });
    expect(slides.find((slide) => slide.id === "s2")?.highlightColours).toBeUndefined();
  });

  it("does not apply a pending colour override to the other audience", async () => {
    const cam = makeCamera();
    const job = makeJob({
      result: {
        ...makeDoc({
          slides: [
            makeSlide({
              id: "s1",
              title: "Slide 1",
              highlights: ["SGP"],
              cg: { camera: cam, style: "positron", highlights: ["SGP"], churches: [] },
            }),
          ],
        }),
        stateRevision: 1,
      },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "SGP" }));
    });

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#00aaff" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle("Independent CG"));
    });
    await tick(MAPS_SAVE_IDLE_MS);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{
      highlightColours?: Record<string, string>;
      cg?: { highlightColours?: Record<string, string> };
    }>;
    const slide = slides[0];
    expect(slide.highlightColours).toEqual({ SGP: "#00aaff" });
    expect(slide.cg?.highlightColours).toBeUndefined();
  });
});

describe("bulk highlight colour", () => {
  it("applies one colour to every selected region", async () => {
    const job = makeJob({
      result: { ...makeDoc({ slides: [makeSlide({ highlights: ["SGP", "MYS"] })] }), stateRevision: 1 },
    });
    await renderMapsTab({ job });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Objects/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "Select SGP" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: "Select MYS" }));
    });

    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(picker, { target: { value: "#112233" } });
    });
    await tick(MAPS_SAVE_IDLE_MS);

    const calls = mapsApiScript.saveMapsState.calls;
    expect(calls.length).toBeGreaterThan(0);
    const slides = calls[calls.length - 1].document.slides as Array<{ highlightColours?: Record<string, string> }>;
    expect(slides[0]?.highlightColours).toEqual({ SGP: "#112233", MYS: "#112233" });
  });
});

describe("live paint", () => {
  it("writes the highlight CSS vars onto documentElement once settings resolve", async () => {
    const { job } = buildExportSetup();
    await renderMapsTab({ job });
    await tick(0);
    for (let i = 0; i < 5; i++) await flushMicrotasks();

    expect(document.documentElement.style.getPropertyValue("--maps-highlight")).toBe("#e8772a");
    expect(document.documentElement.style.getPropertyValue("--maps-highlight-soft")).toMatch(/^rgba\(/);
    expect(document.documentElement.style.getPropertyValue("--maps-highlight-edge")).toMatch(/^rgba\(/);
  });
});
