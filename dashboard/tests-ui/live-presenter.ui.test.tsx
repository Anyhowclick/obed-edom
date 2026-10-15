import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LivePresenter } from "../src/live/LivePresenter";
import { applyHtmlPreview, chooseKeynote, pollJob, startHtmlPreview, type Job } from "../src/api";
import { liveClient, type LiveClient, type LiveCommand, type LiveContinuity, type LiveEngine, type LiveOutputSettings, type LiveResult, type LiveSnapshot, type Placement } from "../src/live/api";

vi.mock("../src/api", () => ({ applyHtmlPreview: vi.fn(), chooseKeynote: vi.fn(), pollJob: vi.fn(), startHtmlPreview: vi.fn(), resolveDrop: vi.fn() }));

function state(overrides: Partial<LiveSnapshot> = {}): LiveSnapshot {
  return {
    sessionId: "live-1",
    revision: 1,
    status: "ready",
    sourceDigest: "source",
    exportKey: "export",
    playerDigest: "player",
    runtimeRevision: "1",
    originalSlide: 1,
    sceneId: "scene-1",
    buildIndex: 0,
    outputVisible: true,
    capabilities: {
      advance: { supported: true }, goTo: { supported: true }, hide: { supported: true }, show: { supported: true },
      recalibrate: { supported: false, reason: "Recalibration is available only for managed OBS output." },
    },
    slides: [
      { originalOrdinal: 1, skipped: false, notes: "Opening" },
      { originalOrdinal: 2, skipped: true },
      { originalOrdinal: 3, skipped: false, notes: "Close" },
    ],
    output: { transport: "hdmi", width: 1920, height: 1080, alpha: false, audio: false },
    ...overrides,
  };
}

function placement(overrides: Partial<Placement> = {}): Placement {
  return {
    state: "invalid", grant: null, reason: "not-calibrated", at: null, product: "Chrome/127.0.0.0",
    gpuCompositing: null, method: "probe", probeId: null, leaseMs: null, leaseExpiresAt: null,
    tone: { observed: null, applied: "identity" }, automaticProbesDisabled: false, ...overrides,
  };
}

function engineState(overrides: Partial<LiveEngine> = {}): LiveEngine {
  return {
    state: "ready",
    taken: !["stopped", "unavailable"].includes(overrides.state || "ready"),
    obs: { path: "/Applications/OBS.app", version: "32.2.2", pinned: "32.2.2" },
    rate: { output: 25, canvas: "25 PAL", source: 50 },
    device: { name: "UltraStudio HD Mini", set: true },
    keyer: "external",
    setup: null,
    warnings: [],
    ...overrides,
  };
}

const screenSettings: LiveOutputSettings = { akOutputMode: "screen", akOutputRate: 25, akKeyer: "external" };
const keyerSettings: LiveOutputSettings = { akOutputMode: "keyer", akOutputRate: 25, akKeyer: "external" };

function client(overrides: Partial<LiveClient> = {}): LiveClient {
  return {
    state: vi.fn(async () => null),
    decks: vi.fn(async () => [{ previewJobId: "prepared-1", name: "Sunday service", slides: 3, sourceDigest: "source", sourceState: "current" as const, sourcePath: "/Slides/Sunday service.key" }]),
    qualification: vi.fn(async (previewJobId) => ({ previewJobId, name: "Sunday service", slides: 3, sourceDigest: "source", sourceState: "current" as const, sourcePath: "/Slides/Sunday service.key", qualified: true, continuity: { mode: "qualified" as const, reason: null, notCarried: [] }, convertedMovies: [] })),
    displays: vi.fn(async () => [{ id: "screen-2", name: "HDMI projector", width: 1920, height: 1080, x: 0, y: 0, primary: true }]),
    start: vi.fn(async () => state()),
    command: vi.fn(async (_sessionId: string, command: LiveCommand): Promise<LiveResult> => ({ requestId: command.requestId, outcome: "completed", state: state() })),
    engine: vi.fn(async () => engineState()),
    engineAction: vi.fn(async () => engineState()),
    outputSettings: vi.fn(async () => screenSettings),
    saveOutputSettings: vi.fn(async (settings: LiveOutputSettings) => settings),
    ...overrides,
  };
}

describe("LivePresenter", () => {
  beforeEach(() => {
    let nextRequestId = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `request-${++nextRequestId}` });
  });

  it("starts only a prepared deck on the selected detected display", async () => {
    const api = client();
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    await waitFor(() => expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled());
    expect(screen.queryByRole("checkbox", { name: /movie continuity/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2"));
    expect(screen.queryByTitle(/player|preview/i)).not.toBeInTheDocument();
  });

  it("starts with automatic continuity and no continuity preference", async () => {
    const api = client({ start: vi.fn(async () => state({ continuity: { mode: "qualified" } })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    await waitFor(() => expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2"));
    expect(await screen.findByText("Movie continuity · On")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Enable movie continuity when qualified" })).not.toBeInTheDocument();
    expect(api.command).not.toHaveBeenCalled();
  });

  it.each([
    ["qualified", "On", "Enabled for this deck."],
    ["unsupported", "Off for this deck", "stage is not the authored size"],
    ["off", "Off for this deck", "Using the deck’s native movie playback."],
    ["pending", "Checking", "Checking this deck and output size."],
  ] as const)("shows observed %s continuity alongside Show output", async (mode, label, detail) => {
    const continuity: LiveContinuity = { mode, ...(mode === "unsupported" ? { reason: detail } : {}) };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const badge = await screen.findByText(`Movie continuity · ${label}`);
    expect(screen.getByText(detail)).toBeInTheDocument();
    expect(badge).toBeVisible();
    expect(screen.getByRole("button", { name: "Show output" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Show output" })).toHaveClass("live-take-output");
  });

  it.each([
    [undefined, "Enabled for this deck."],
    [1, "Enabled for this deck."],
    [1.3333, "Enabled for this deck (stage scaled ×1.33)."],
  ] as const)("shows scale %s in the qualified continuity detail", async (scale, detail) => {
    const continuity: LiveContinuity = { mode: "qualified", ...(scale === undefined ? {} : { scale }) };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · On");
    expect(screen.getByText(detail)).toBeInTheDocument();
  });

  it("does not claim qualification when the host omits continuity status", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByText("Movie continuity · Unavailable")).toBeInTheDocument();
    expect(screen.getByText("This session has not reported movie continuity status.")).toBeInTheDocument();
    expect(screen.queryByText("Movie continuity · On")).not.toBeInTheDocument();
  });

  it.each([
    ["initial", placement(), { supported: true }, "Output not calibrated", true, ""],
    ["probing", placement({ state: "probing", reason: "calibrating", probeId: "probe-1" }), { supported: false, reason: "Calibration is already running." }, "Calibrating…", false, "Calibration is already running."],
    ["deferred", placement({ state: "probing", reason: "waiting-for-transition", probeId: "probe-2" }), { supported: false, reason: "Calibration is already running." }, "Waiting for the current transition to finish.", false, "Calibration is already running."],
    ["valid", placement({ state: "valid", grant: "frac", reason: "granted", probeId: "probe-3", leaseMs: 15_000 }), { supported: true }, "Output calibrated", true, ""],
    ["failed", placement({ reason: "probe-failed", probeId: "probe-4" }), { supported: true }, "Calibration unavailable. Movies use the standard transition.", true, ""],
    ["suppressed", placement({ reason: "program-disturbed", automaticProbesDisabled: true }), { supported: true }, "Calibration paused. Recalibrate output to retry.", true, ""],
    ["unsupported", undefined, { supported: false, reason: "Recalibration is available only for managed OBS output." }, "Recalibration is available only for managed OBS output.", false, "Recalibration is available only for managed OBS output."],
    ["disconnected", placement({ reason: "disconnected" }), { supported: false, reason: "Waiting for connection to output host" }, "Waiting for connection to output host", false, "Waiting for connection to output host"],
  ] as const)("shows %s calibration state and applies only its own run guard", async (_name, currentPlacement, capability, status, enabled, reason) => {
    const base = state();
    const api = client({
      state: vi.fn(async () => state({
        capabilities: { ...base.capabilities, recalibrate: capability },
        output: { ...base.output, ...(currentPlacement ? { placement: currentPlacement } : {}) },
      })),
    });
    render(<LivePresenter client={api} pollMs={60_000} />);

    expect(await screen.findByText(status)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Recalibrate output" });
    if (_name === "probing" || _name === "deferred") {
      expect(screen.getByRole("button", { name: "Advance" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Hide output" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Stop session" })).toBeEnabled();
    }
    if (enabled) {
      expect(button).toBeEnabled();
      fireEvent.click(button);
      await waitFor(() => expect(api.command).toHaveBeenCalledWith("live-1", expect.objectContaining({ operation: "recalibrate" })));
      expect(screen.queryByText("Command accepted; waiting for observed player state.")).not.toBeInTheDocument();
    } else {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", reason);
      fireEvent.click(button);
      expect(api.command).not.toHaveBeenCalled();
    }
  });

  it("says nothing about codecs when the host omits the fields", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    expect(screen.queryByText("Some movies may not play in this output")).not.toBeInTheDocument();
  });

  it("says nothing about codecs when the host reports no warnings", async () => {
    const output = { ...state().output, codecs: [{ asset: "clip.mov", codec: "avc1", family: "h264" as const }], codecWarnings: [] };
    const api = client({ state: vi.fn(async () => state({ output })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    expect(screen.queryByText("Some movies may not play in this output")).not.toBeInTheDocument();
    expect(screen.queryByText(/more$/)).not.toBeInTheDocument();
  });

  it("keeps every unplayable movie warning visible alongside Show output", async () => {
    const codecWarnings = ["clip.mov (hvc1) may not play in this output", "sting.mov (apcn) may not play in this output"];
    const output = { ...state().output, codecWarnings };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, output })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const heading = await screen.findByText("Some movies may not play in this output");
    for (const warning of codecWarnings) expect(screen.getByText(warning)).toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
    expect(heading).toBeVisible();
    expect(screen.getByRole("button", { name: "Show output" })).toBeEnabled();
  });

  it("caps the codec warning list at five and counts the rest", async () => {
    const codecWarnings = Array.from({ length: 7 }, (_, index) => `clip-${index + 1}.mov (hvc1) may not play in this output`);
    const output = { ...state().output, codecWarnings };
    const api = client({ state: vi.fn(async () => state({ output })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Some movies may not play in this output");
    for (const warning of codecWarnings.slice(0, 5)) expect(screen.getByText(warning)).toBeInTheDocument();
    for (const warning of codecWarnings.slice(5)) expect(screen.queryByText(warning)).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("says nothing about declined cuts when the host reports none", async () => {
    const api = client({ state: vi.fn(async () => state({ continuity: { mode: "qualified" } })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · On");
    expect(screen.queryByText(/not carried/)).not.toBeInTheDocument();
  });

  it("names a cut continuity declines under the continuity badge", async () => {
    const continuity: LiveContinuity = {
      mode: "qualified",
      notCarried: [{ fromSlide: 3, toSlide: 4, asset: "clip.mov", reason: "artwork overlaps the carried movie" }],
    };
    const api = client({ state: vi.fn(async () => state({ continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · On · 1 not carried");
    expect(screen.getByText("Slide 3 → 4 · clip.mov · artwork overlaps the carried movie")).toBeInTheDocument();
    expect(screen.queryByText(/^\d+ more$/)).not.toBeInTheDocument();
  });

  it("shows poster holds on one line under the continuity badge", async () => {
    const continuity: LiveContinuity = {
      mode: "qualified",
      posterHold: [
        { fromSlide: 6, toSlide: 7, movie: "clip-a.mov", objectId: "a", planned: "exact", mode: "baked", reason: "one-shot upload refused" },
        { fromSlide: 7, toSlide: 8, movie: "clip-b.mov", objectId: "b", planned: "continuous", mode: "unavailable", reason: "WebGL context lost" },
      ],
    };
    const api = client({ state: vi.fn(async () => state({ continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · On");
    expect(screen.getByText("Poster hold · 6 → 7 · clip-a.mov · baked poster (planned exact departure frame; one-shot upload refused); 7 → 8 · clip-b.mov · unavailable (planned continuous feed; WebGL context lost)")).toBeVisible();
  });

  it("lists three declined cuts and folds the rest into an expandable list", async () => {
    const notCarried = Array.from({ length: 5 }, (_, index) => ({
      fromSlide: index + 1, toSlide: index + 2, asset: `clip-${index + 1}.mov`, reason: `reason ${index + 1}`,
    }));
    const api = client({ state: vi.fn(async () => state({ continuity: { mode: "qualified", notCarried } })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · On · 5 not carried");
    const line = (entry: (typeof notCarried)[number]) => screen.getByText(`Slide ${entry.fromSlide} → ${entry.toSlide} · ${entry.asset} · ${entry.reason}`);
    for (const entry of notCarried.slice(0, 3)) expect(line(entry)).toBeVisible();
    for (const entry of notCarried.slice(3)) expect(line(entry)).not.toBeVisible();
    fireEvent.click(screen.getByText("2 more"));
    for (const entry of notCarried.slice(3)) expect(line(entry)).toBeVisible();
  });

  it("does not move the presenter until a delayed command returns observed state", async () => {
    let resolve!: (value: LiveResult) => void;
    const command = vi.fn(() => new Promise<LiveResult>((done) => { resolve = done; }));
    const api = client({ state: vi.fn(async () => state()), command });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    fireEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(screen.getByRole("status")).toHaveTextContent("Player ready");
    expect(screen.getByRole("button", { name: "Advance" })).toBeDisabled();
    await act(async () => resolve({ requestId: "request-1", outcome: "completed", state: state({ originalSlide: 3, revision: 2, sceneId: "scene-3" }) }));
    expect(screen.getByRole("status")).toHaveTextContent("Player ready");
    expect(screen.getByText(/Slide 3 · Build/)).toBeInTheDocument();
  });

  it("clears accepted waiting status after polling observes the completed player state", async () => {
    const getState = vi.fn()
      .mockResolvedValueOnce(state())
      .mockResolvedValueOnce(state({ revision: 2, originalSlide: 3, sceneId: "scene-3" }));
    const api = client({
      state: getState,
      command: vi.fn(async (_sessionId: string, command: LiveCommand): Promise<LiveResult> => ({
        requestId: command.requestId,
        outcome: "accepted",
        state: state({ status: "busy", revision: 2 }),
      })),
    });
    vi.useFakeTimers();
    try {
      render(<LivePresenter client={api} pollMs={100} />);
      await act(async () => {});
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Advance" })); });
      expect(screen.getByRole("alert")).toHaveTextContent("Command accepted; waiting for observed player state.");
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(screen.queryByText("Command accepted; waiting for observed player state.")).not.toBeInTheDocument();
      expect(screen.getByText(/Slide 3 · Build/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the auto-play-deferred note near the slide line", async () => {
    const api = client({ state: vi.fn(async () => state({ autoPlayDeferred: "Movies idle until next advance" })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const note = await screen.findByText("Movies idle until next advance");
    const slideLine = screen.getByText(/Slide 1 · Build/);
    expect(slideLine.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says nothing when auto-play was not deferred", async () => {
    const api = client({ state: vi.fn(async () => state({ autoPlayDeferred: null })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText(/Slide 1 · Build/);
    expect(screen.queryByText("Movies idle until next advance")).not.toBeInTheDocument();
  });

  it("keeps the observed slide when go-to is rejected", async () => {
    const api = client({
      state: vi.fn(async () => state()),
      command: vi.fn(async (_sessionId: string, command: LiveCommand): Promise<LiveResult> => ({ requestId: command.requestId, outcome: "rejected", reason: "Player is busy.", state: state() })),
    });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    fireEvent.change(screen.getByLabelText("Go to slide"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Player is busy.");
    expect(screen.getByText(/Slide 1 · Build/)).toBeInTheDocument();
  });

  it("ignores a delayed response for a stale session", async () => {
    const api = client({
      state: vi.fn(async () => state()),
      command: vi.fn(async (_sessionId: string, command: LiveCommand): Promise<LiveResult> => ({
        requestId: command.requestId,
        outcome: "completed",
        state: state({ sessionId: "live-old", revision: 99, originalSlide: 3, sceneId: "scene-3" }),
      })),
    });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    fireEvent.click(screen.getByRole("button", { name: "Advance" }));
    await waitFor(() => expect(api.command).toHaveBeenCalled());
    expect(screen.getByText(/Slide 1 · Build/)).toBeInTheDocument();
    expect(screen.queryByText(/Slide 3 · Build/)).not.toBeInTheDocument();
  });

  it("does not treat number entry in a form control as a go-to shortcut", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const input = await screen.findByLabelText("Go to slide");
    fireEvent.keyDown(input, { key: "3" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(api.command).not.toHaveBeenCalled();
  });

  it("uses number and Enter from a focused sidebar-like button without taking its native Space key", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<><button type="button">Alpha Keynote</button><LivePresenter client={api} pollMs={60_000} /></>);
    await screen.findByText("Player ready · Output visible");
    const sidebarButton = screen.getByRole("button", { name: "Alpha Keynote" });
    sidebarButton.focus();
    await act(async () => { fireEvent.keyDown(sidebarButton, { key: "1" }); });
    expect(screen.getByText("Go to: 1 · Enter to jump · Esc to clear")).toBeInTheDocument();
    fireEvent.keyDown(sidebarButton, { key: "Enter" });
    await waitFor(() => expect(api.command).toHaveBeenCalledWith("live-1", expect.objectContaining({ operation: "goTo", slide: 1 })));
    vi.mocked(api.command).mockClear();
    const allowed = fireEvent.keyDown(sidebarButton, { key: " " });
    expect(allowed).toBe(true);
    expect(api.command).not.toHaveBeenCalled();
  });

  it("keeps a running session after reconnecting", async () => {
    const getState = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(state({ revision: 4, originalSlide: 3, outputVisible: false }));
    vi.useFakeTimers();
    try {
      render(<LivePresenter client={client({ state: getState })} pollMs={100} />);
      await act(async () => {});
      expect(screen.getByRole("alert")).toHaveTextContent("offline");
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(screen.getByRole("status")).toHaveTextContent("Player ready");
      expect(screen.getByText(/Slide 3 · Build/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders an error snapshot with incomplete capabilities and keeps Stop usable", async () => {
    const api = client({
      state: vi.fn(async () => state({ status: "error", error: "Output window closed", capabilities: {} as LiveSnapshot["capabilities"] })),
    });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Output window closed");
    expect(screen.getByRole("button", { name: "Stop session" })).toBeEnabled();
    expect(screen.getByText("Movie continuity · Unavailable")).toBeInTheDocument();
  });

  it("allows output hiding while the player is busy but blocks navigation", async () => {
    const api = client({ state: vi.fn(async () => state({ status: "busy" })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByRole("button", { name: "Hide output" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Hide output" })).toHaveClass("live-release-output");
    expect(screen.getByRole("button", { name: "Advance" })).toBeDisabled();
  });

  it("keeps Stop enabled and sendable while another command is pending, but ignores a second stop click", async () => {
    let resolveAdvance!: (value: LiveResult) => void;
    const command = vi.fn((_sessionId: string, cmd: LiveCommand): Promise<LiveResult> => {
      if (cmd.operation === "advance") return new Promise<LiveResult>((done) => { resolveAdvance = done; });
      return Promise.resolve({ requestId: cmd.requestId, outcome: "completed", state: state({ status: "stopped" }) });
    });
    const api = client({ state: vi.fn(async () => state()), command });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    fireEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(screen.getByRole("button", { name: "Advance" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop session" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop session" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop session" }));
    await waitFor(() => expect(command).toHaveBeenCalledWith("live-1", expect.objectContaining({ operation: "stop" })));
    const stopCalls = command.mock.calls.filter((call) => call[1].operation === "stop");
    expect(stopCalls).toHaveLength(1);
    const advanceRequestId = command.mock.calls.find((call) => call[1].operation === "advance")![1].requestId;
    const stopRequestId = stopCalls[0][1].requestId;
    expect(stopRequestId).not.toBe(advanceRequestId);
    await act(async () => resolveAdvance({ requestId: advanceRequestId, outcome: "completed", state: state({ originalSlide: 3, revision: 2, sceneId: "scene-3" }) }));
  });

  it("shows the disabled reason and sends nothing when a shortcut fires while blocked", async () => {
    const api = client({ state: vi.fn(async () => state({ status: "busy" })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("button", { name: "Hide output" });
    fireEvent.keyDown(window, { key: " " });
    expect(await screen.findByRole("alert")).toHaveTextContent("Player is busy");
    expect(api.command).not.toHaveBeenCalled();
  });
});

describe("live start request", () => {
  it.each([undefined, "off"] as const)("sends only the requested continuity override (%s)", async (continuity) => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(state()), { status: 200 }));
    try {
      await liveClient.start("prepared-1", "screen-2", continuity);
      expect(fetch).toHaveBeenCalledWith("/api/live", expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ previewJobId: "prepared-1", displayId: "screen-2", ...(continuity ? { continuity } : {}) }),
      }));
    } finally {
      fetch.mockRestore();
    }
  });
});

describe("LivePresenter output mode", () => {
  beforeEach(() => {
    let nextRequestId = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `request-${++nextRequestId}` });
  });

  it("does not poll the output engine in Screen mode", async () => {
    const api = client();
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Output" })).toBeEnabled());
    expect(screen.getByRole("combobox", { name: "Output" })).toHaveValue("screen");
    expect(screen.getByRole("combobox", { name: "Output display" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Output rate" })).not.toBeInTheDocument();
    expect(api.engine).not.toHaveBeenCalled();
  });

  it("switching to Keyer saves the mode, hides the Display picker and shows the engine panel", async () => {
    const api = client();
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Output" })).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Output" }), { target: { value: "keyer" } });
    await waitFor(() => expect(api.saveOutputSettings).toHaveBeenCalledWith(keyerSettings));
    expect(await screen.findByText("Output engine · Ready")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Output display" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Output rate" })).toHaveValue("25");
    expect(screen.getByRole("combobox", { name: "Output rate" })).toHaveAttribute("title", "Match the standard shown on the Pulse.");
    expect(screen.getByRole("checkbox", { name: "Enable Keyer" })).toHaveAccessibleDescription(/picture \(fill\).*transparency \(key\)/);
    expect(screen.getByRole("checkbox", { name: "Enable Keyer" })).toBeChecked();
    expect(api.engine).toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Output" }), { target: { value: "screen" } });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Output display" })).toBeInTheDocument());
    expect(screen.queryByText(/^Output engine ·/)).not.toBeInTheDocument();
  });

  it("saves the rate and keyer choices", async () => {
    const api = client({ outputSettings: vi.fn(async () => keyerSettings) });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    const rate = await screen.findByRole("combobox", { name: "Output rate" });
    fireEvent.change(rate, { target: { value: "30" } });
    await waitFor(() => expect(api.saveOutputSettings).toHaveBeenCalledWith({ ...keyerSettings, akOutputRate: 30 }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Enable Keyer" })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: "Enable Keyer" }));
    await waitFor(() => expect(api.saveOutputSettings).toHaveBeenCalledWith({ ...keyerSettings, akOutputRate: 30, akKeyer: "off" }));
    expect(screen.getByRole("checkbox", { name: "Enable Keyer" })).not.toBeChecked();
  });

  it("shows a refused settings change and keeps the saved mode", async () => {
    const api = client({ saveOutputSettings: vi.fn(async () => { throw new Error("Stop the show first."); }) });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Output" })).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Output" }), { target: { value: "keyer" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Stop the show first.");
    expect(screen.getByRole("combobox", { name: "Output" })).toHaveValue("screen");
  });

  it("starts a Keyer session without a display once the engine is ready", async () => {
    const api = client({ outputSettings: vi.fn(async () => keyerSettings) });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByText("Output engine · Ready");
    await waitFor(() => expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", undefined));
  });

  it.each([
    ["stopped", []],
    ["starting", []],
    ["blocked", [{ id: "obsMissing", severity: "block", text: "Output engine not installed. Install OBS 32.2.2 into Applications, then press Check again." }]],
    ["ready", [{ id: "deviceInactive", severity: "block", text: "Alpha Keynote cannot open the UltraStudio." }]],
  ] as const)("disables Start output session while the engine is %s with blocks %j", async (engine, warnings) => {
    const api = client({
      outputSettings: vi.fn(async () => keyerSettings),
      engine: vi.fn(async () => engineState({ state: engine, warnings: [...warnings] })),
    });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    await waitFor(() => expect(api.engine).toHaveBeenCalled());
    await act(async () => {});
    const start = screen.getByRole("button", { name: "Start output session" });
    expect(start).toBeDisabled();
    if (warnings.length) expect(start).toHaveAttribute("title", warnings[0].text);
  });

  it("keeps Start enabled on a warn-only engine warning", async () => {
    const text = "OBS closed unexpectedly last time. It has been restarted; check the output before going live.";
    const api = client({
      outputSettings: vi.fn(async () => keyerSettings),
      engine: vi.fn(async () => engineState({ warnings: [{ id: "obsUncleanExit", severity: "warn", text }] })),
    });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByText(text);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled());
  });

  it("locks the mode, rate and keyer controls while a session is loaded", async () => {
    const api = client({
      state: vi.fn(async () => state({ output: { ...state().output, transport: "fill-key", bridge: "obs-managed" } })),
      outputSettings: vi.fn(async () => keyerSettings),
    });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    await screen.findByText("Output engine · Ready");
    expect(screen.getByRole("combobox", { name: "Output" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Output rate" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Enable Keyer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Release output" })).toBeDisabled();
  });

  it("shows rate warnings beside codec warnings", async () => {
    const codecWarnings = ["clip.mov (hvc1) may not play in this output"];
    const rateWarnings = ["walk.mov is 29.97 fps but the output is 25 fps, so it will judder slightly. Re-export it at 25 fps for smooth motion."];
    const api = client({ state: vi.fn(async () => state({ output: { ...state().output, codecWarnings, rateWarnings } })) });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    const codecs = await screen.findByText("Some movies may not play in this output");
    const rates = screen.getByText("Some movies do not match the output rate");
    expect(screen.getByText(rateWarnings[0])).toBeInTheDocument();
    expect(codecs.compareDocumentPosition(rates) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(rates.parentElement!).getByText(rateWarnings[0])).toBeInTheDocument();
  });

  it("says nothing about the output rate when the host omits rate warnings", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<LivePresenter client={api} pollMs={60_000} enginePollMs={60_000} />);
    await screen.findByRole("button", { name: "Advance" });
    expect(screen.queryByText("Some movies do not match the output rate")).not.toBeInTheDocument();
  });
});

describe("live engine and output-settings requests", () => {
  it.each(["start", "restart", "check", "show", "quit", "setupDevice", "setupDone"] as const)("posts %s to its engine route", async (action) => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(engineState()), { status: 200 }));
    try {
      await liveClient.engineAction(action);
      expect(fetch).toHaveBeenCalledWith(`/api/live/engine/${action}`, { method: "POST" });
    } finally {
      fetch.mockRestore();
    }
  });

  it("reads the engine state and output settings with GET and saves settings with PUT", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(keyerSettings), { status: 200 }));
    try {
      await liveClient.engine();
      await liveClient.outputSettings();
      await liveClient.saveOutputSettings(keyerSettings);
      expect(fetch).toHaveBeenNthCalledWith(1, "/api/live/engine", undefined);
      expect(fetch).toHaveBeenNthCalledWith(2, "/api/live/output-settings", undefined);
      expect(fetch).toHaveBeenNthCalledWith(3, "/api/live/output-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(keyerSettings),
      });
    } finally {
      fetch.mockRestore();
    }
  });

  it("surfaces a 409 detail", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Stop the show first." }), { status: 409 }));
    try {
      await expect(liveClient.engineAction("quit")).rejects.toThrow("Stop the show first.");
    } finally {
      fetch.mockRestore();
    }
  });
});

describe("Alpha Keynote intake and slide grid", () => {
  beforeEach(() => {
    let request = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `new-${++request}` });
    for (const fn of [chooseKeynote, startHtmlPreview, applyHtmlPreview, pollJob]) vi.mocked(fn).mockReset();
  });

  it.each(["chooser", "drop"])("prepares a Keynote from %s, qualifies it, then enables Start", async (method) => {
    const proposal: Job = { id: "new-deck", kind: "html-preview", status: "done", logs: [], result: { phase: "review" } };
    const ready: Job = { ...proposal, result: { phase: "ready" } };
    vi.mocked(startHtmlPreview).mockResolvedValue(proposal);
    vi.mocked(applyHtmlPreview).mockResolvedValue(ready);
    vi.mocked(pollJob).mockResolvedValueOnce(proposal).mockResolvedValueOnce(ready);
    vi.mocked(chooseKeynote).mockResolvedValue({ path: "/Slides/Service.key", name: "Service.key" });
    const api = client({ decks: vi.fn(async () => []) });
    const { container } = render(<LivePresenter client={api} pollMs={60_000} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Output" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Start output session" })).toBeDisabled();
    expect(screen.queryByLabelText("Or enter a file path")).not.toBeInTheDocument();
    if (method === "chooser") {
      fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
    } else {
      fireEvent.drop(container.querySelector(".well")!, { dataTransfer: { getData: () => "file:///Slides/Service.key", files: [] } });
    }
    await screen.findByText("Service.key");
    fireEvent.click(screen.getByRole("button", { name: "Qualify Keynote" }));
    await screen.findByText("Deck ready");
    expect(screen.getByRole("button", { name: "View output" })).toBeEnabled();
    expect(startHtmlPreview).toHaveBeenCalledWith("/Slides/Service.key");
    expect(applyHtmlPreview).toHaveBeenCalledWith("new-deck");
    expect(api.qualification).toHaveBeenCalledWith("new-deck");
    expect(api.start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("new-deck", "screen-2"));
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("does not export again when the preparation reuses a ready cache", async () => {
    const ready: Job = { id: "cached", kind: "html-preview", status: "done", logs: [], result: { phase: "ready" } };
    vi.mocked(startHtmlPreview).mockResolvedValue(ready);
    vi.mocked(pollJob).mockResolvedValue(ready);
    const api = client({ decks: vi.fn(async () => []) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    vi.mocked(chooseKeynote).mockResolvedValue({ path: "/Slides/Cached.key", name: "Cached.key" });
    fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
    await screen.findByText("Cached.key");
    fireEvent.click(screen.getByRole("button", { name: "Qualify Keynote" }));
    await screen.findByText("Deck ready");
    expect(applyHtmlPreview).not.toHaveBeenCalled();
  });

  it("warns about changed and missing sources and can prepare a changed Keynote again", async () => {
    const sourcePath = "/Slides/Sunday service.key";
    const missingPath = "/Archive/Missing.key";
    const stale = { previewJobId: "prepared-1", name: "Sunday service", slides: 3, sourceDigest: "old", sourceState: "changed" as const, sourcePath };
    const missing = { previewJobId: "missing-1", name: "Missing", slides: 2, sourceDigest: "missing", sourceState: "missing" as const, sourcePath: missingPath };
    const qualification = vi.fn(async (previewJobId: string) => ({
      ...(previewJobId === "prepared-1" ? stale : previewJobId === "missing-1" ? missing : {
        previewJobId, name: "Sunday service", slides: 3, sourceDigest: "new", sourceState: "current" as const, sourcePath,
      }),
      qualified: true,
      continuity: { mode: "qualified" as const, reason: null, notCarried: [] },
      convertedMovies: [],
    }));
    const api = client({ decks: vi.fn(async () => [stale, missing]), qualification });
    const proposal1: Job = { id: "reprepare-1", kind: "html-preview", status: "done", logs: [], result: { phase: "review" } };
    const proposal2: Job = { id: "prepared-2", kind: "html-preview", status: "done", logs: [], result: { phase: "review" } };
    const ready2: Job = { ...proposal2, result: { phase: "ready" } };
    let resolveProposal!: (job: Job) => void;
    vi.mocked(startHtmlPreview).mockResolvedValueOnce(proposal1).mockResolvedValueOnce(proposal2);
    vi.mocked(applyHtmlPreview).mockRejectedValueOnce(new Error("Close Keynote before exporting a build preview (strictly serial).")).mockResolvedValueOnce(ready2);
    vi.mocked(pollJob)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveProposal = resolve; }))
      .mockResolvedValueOnce(proposal2)
      .mockResolvedValueOnce(ready2);

    render(<LivePresenter client={api} pollMs={60_000} />);
    const warningText = "This Keynote was edited after this deck was prepared. This deck still plays the old version. Save and close Keynote, then prepare again to pick up the edits.";
    const warning = await screen.findByText(warningText);
    expect(screen.getByRole("option", { name: "Sunday service · 3 slides · Keynote changed — re-prepare" })).toBeInTheDocument();
    expect(warning.closest(".notice")).toHaveClass("warning");
    const prepareAgain = screen.getByRole("button", { name: "Prepare again" });
    expect(prepareAgain).toHaveClass("tone-alt");
    expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled();

    fireEvent.click(prepareAgain);
    await waitFor(() => expect(startHtmlPreview).toHaveBeenCalledWith(sourcePath));
    await waitFor(() => expect(document.activeElement).toHaveClass("live-prepare-progress"));
    expect(chooseKeynote).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start output session" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose on this Mac" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Qualify Keynote" })).toBeDisabled();
    await act(async () => resolveProposal(proposal1));
    expect(applyHtmlPreview).toHaveBeenCalledWith("reprepare-1");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Close Keynote before exporting a build preview (strictly serial).");
    expect(document.activeElement).toBe(alert);
    await screen.findByText(warningText);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Prepared deck" })).toHaveValue("prepared-1");
    expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Prepare again" }));
    await waitFor(() => expect(startHtmlPreview).toHaveBeenLastCalledWith(sourcePath));
    await waitFor(() => expect(applyHtmlPreview).toHaveBeenLastCalledWith("prepared-2"));
    await waitFor(() => expect(qualification).toHaveBeenCalledWith("prepared-2"));
    expect(screen.getByRole("combobox", { name: "Prepared deck" })).toHaveValue("prepared-2");
    expect(await screen.findByText("Sunday service · 3 slides. Output is checked when the session starts.")).toBeVisible();
    expect(screen.queryByText(warningText)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Prepared deck" }), { target: { value: "missing-1" } });
    expect(await screen.findByText(`Original Keynote not found or can't be read at ${missingPath} — can't check for edits.`)).toHaveClass("path-note");
    expect(screen.queryByText(warningText)).not.toBeInTheDocument();
  });

  it("starts a deck whose continuity is off and says why, with its moves and converted movies", async () => {
    const reason = "R3: slide 2's transition is not on its last event";
    const qualification = vi.fn(async (previewJobId: string) => ({
      previewJobId, name: "Minimal.key", slides: 3, sourceDigest: "source", sourceState: "current" as const, sourcePath: "/Slides/Minimal.key", qualified: true,
      continuity: { mode: "unsupported" as const, reason, notCarried: [] },
      convertedMovies: [{ asset: "untitled.mov", sourceCodec: "HEVC" }, { asset: "clip-10-1000001.mov", sourceCodec: "ProRes" }],
    }));
    const api = client({ qualification });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Deck ready");
    expect(screen.getByText(`Movie continuity off for this deck: ${reason}`)).toBeVisible();
    expect(screen.getByText("Converted 2 movies to H.264 for playback: untitled.mov (HEVC), clip-10-1000001.mov (ProRes).")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Start output session" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2"));
  });

  it("lists the moves continuity will not carry before the deck starts", async () => {
    const notCarried = [{ fromSlide: 6, toSlide: 8, asset: "vid-20250608-wa0125.mp4", reason: "later-authored artwork overlaps" }];
    const api = client({ qualification: vi.fn(async (previewJobId: string) => ({
      previewJobId, name: "Sunday service", slides: 3, sourceDigest: "source", sourceState: "current" as const, sourcePath: "/Slides/Sunday service.key", qualified: true,
      continuity: { mode: "qualified" as const, reason: null, notCarried }, convertedMovies: [],
    })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByText("Movie continuity on · 1 move not carried")).toBeVisible();
    expect(screen.getByText("Slide 6 → 8 · vid-20250608-wa0125.mp4 · later-authored artwork overlaps")).toBeVisible();
    expect(screen.queryByText(/Converted/)).not.toBeInTheDocument();
  });

  it("shows preparation errors in red and keeps the complete output in an Escape-closeable dialog", async () => {
    const error = "HTML export failed: Application isn't running. (-600)";
    const proposal: Job = { id: "proposal", kind: "html-preview", status: "done", logs: ["Inspected 12 slides", "Cannot embed clip.mov"], result: { phase: "review" } };
    const failed: Job = { ...proposal, status: "error", logs: [...proposal.logs, "Exporting HTML", `Error: ${error}`], error };
    vi.mocked(startHtmlPreview).mockResolvedValue(proposal);
    vi.mocked(applyHtmlPreview).mockResolvedValue(failed);
    vi.mocked(pollJob).mockResolvedValueOnce(proposal).mockResolvedValueOnce(failed);
    const api = client({ decks: vi.fn(async () => []) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    vi.mocked(chooseKeynote).mockResolvedValue({ path: "/Slides/Service.key", name: "Service.key" });
    fireEvent.click(screen.getByRole("button", { name: "Choose on this Mac" }));
    await screen.findByText("Service.key");
    fireEvent.click(screen.getByRole("button", { name: "Qualify Keynote" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(error);
    expect(alert).toHaveClass("live-alert");
    expect(api.qualification).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start output session" })).toBeDisabled();
    const viewOutput = screen.getByRole("button", { name: "View output" });
    viewOutput.focus();
    fireEvent.click(viewOutput);
    const dialog = screen.getByRole("dialog", { name: "Prepare output — Service.key" });
    expect(dialog).toHaveFocus();
    const log = dialog.querySelector<HTMLElement>(".prepare-output-log")!;
    fireEvent.keyDown(document, { key: "Tab" });
    expect(log).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(log).toHaveFocus();
    for (const line of failed.logs) expect(within(dialog).getByText(line)).toBeInTheDocument();
    expect(within(dialog).getByText("Cannot embed clip.mov")).toHaveClass("live-alert");
    expect(within(dialog).getByText(`Error: ${error}`)).toHaveClass("live-alert");
    expect(within(dialog).queryByText(error)).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(viewOutput).toHaveFocus());
  });

  it("uses previous playable slide on left arrow, even with a button focused", async () => {
    const api = client({ state: vi.fn(async () => state({ originalSlide: 3 })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const advance = await screen.findByRole("button", { name: "Advance" });
    advance.focus();
    fireEvent.keyDown(advance, { key: "ArrowLeft" });
    await waitFor(() => expect(api.command).toHaveBeenCalledWith("live-1", expect.objectContaining({ operation: "goTo", slide: 1 })));
  });

  it.each([
    ["Enter", { operation: "advance" }],
    ["PageDown", { operation: "advance" }],
    ["PageUp", { operation: "goTo", slide: 1 }],
  ])("treats %s as a presenter key", async (key, command) => {
    const api = client({ state: vi.fn(async () => state({ originalSlide: 3 })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Player ready · Output visible");
    const allowed = fireEvent.keyDown(window, { key });
    expect(allowed).toBe(false);
    await waitFor(() => expect(api.command).toHaveBeenCalledWith("live-1", expect.objectContaining(command)));
    expect(api.command).toHaveBeenCalledTimes(1);
  });

  it("takes clicker Page Up/Down even with a button focused, but leaves a bare Enter to the button", async () => {
    const api = client({ state: vi.fn(async () => state({ originalSlide: 3 })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const advance = await screen.findByRole("button", { name: "Advance" });
    advance.focus();
    expect(fireEvent.keyDown(advance, { key: "Enter" })).toBe(true);
    expect(api.command).not.toHaveBeenCalled();
    fireEvent.keyDown(advance, { key: "PageUp" });
    await waitFor(() => expect(api.command).toHaveBeenCalledWith("live-1", expect.objectContaining({ operation: "goTo", slide: 1 })));
    await waitFor(() => expect(advance).toBeEnabled());
    fireEvent.keyDown(advance, { key: "PageDown" });
    await waitFor(() => expect(api.command).toHaveBeenLastCalledWith("live-1", expect.objectContaining({ operation: "advance" })));
  });

  it("keeps chevrons below the only current preview and highlights only observed state", async () => {
    const api = client({ state: vi.fn(async () => state()), command: vi.fn(async (_session, command): Promise<LiveResult> => ({ requestId: command.requestId, outcome: "rejected", reason: "Busy", state: state() })) });
    const { container } = render(<LivePresenter client={api} pollMs={60_000} />);
    const previous = await screen.findByRole("button", { name: "Previous slide" });
    expect(previous).toBeDisabled();
    expect(screen.getByRole("button", { name: "Slide 2 · Skipped / unavailable" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Slide 3" }));
    await screen.findByText("Busy");
    expect(screen.getByRole("button", { name: "Slide 1" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Slide 3" })).not.toHaveAttribute("aria-current");
    expect(container.querySelector(".live-monitor > .live-placeholder + .live-transport")).not.toBeNull();
    expect(screen.queryByText("Upcoming slides")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pause|play/i })).not.toBeInTheDocument();
  });

  it("ignores navigation keys in inputs and repeated or modified keys", async () => {
    const api = client({ state: vi.fn(async () => state({ originalSlide: 3 })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const input = await screen.findByLabelText("Go to slide");
    fireEvent.keyDown(input, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "ArrowRight", repeat: true });
    fireEvent.keyDown(window, { key: "ArrowLeft", metaKey: true });
    fireEvent.keyDown(input, { key: "PageDown" });
    fireEvent.keyDown(window, { key: "PageDown", repeat: true });
    fireEvent.keyDown(window, { key: "PageUp", altKey: true });
    expect(api.command).not.toHaveBeenCalled();
  });
});
