import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LivePresenter } from "../src/live/LivePresenter";
import { liveClient, type LiveClient, type LiveCommand, type LiveContinuity, type LiveEngine, type LiveOutputSettings, type LiveResult, type LiveSnapshot } from "../src/live/api";

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

function engineState(overrides: Partial<LiveEngine> = {}): LiveEngine {
  return {
    state: "ready",
    obs: { path: "/Applications/OBS.app", version: "32.2.2", pinned: "32.2.2" },
    rate: { output: 25, canvas: 25, source: 50 },
    device: { name: "UltraStudio HD Mini", set: true },
    keyer: "external",
    warnings: [],
    ...overrides,
  };
}

const screenSettings: LiveOutputSettings = { akOutputMode: "screen", akOutputRate: 25, akKeyer: "external" };
const keyerSettings: LiveOutputSettings = { akOutputMode: "keyer", akOutputRate: 25, akKeyer: "external" };

function client(overrides: Partial<LiveClient> = {}): LiveClient {
  return {
    state: vi.fn(async () => null),
    decks: vi.fn(async () => [{ previewJobId: "prepared-1", name: "Sunday service", slides: 3, sourceDigest: "source" }]),
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
    expect(screen.getByRole("checkbox", { name: "Enable movie continuity when qualified" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2"));
    expect(screen.queryByTitle(/player|preview/i)).not.toBeInTheDocument();
  });

  it("turns continuity off for the next session without changing a running session", async () => {
    const api = client({ start: vi.fn(async () => state({ continuity: { mode: "off" } })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    fireEvent.click(screen.getByRole("checkbox", { name: "Enable movie continuity when qualified" }));
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2", "off"));
    expect(await screen.findByText("Movie continuity · Off")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Enable movie continuity when qualified" })).not.toBeInTheDocument();
    expect(api.command).not.toHaveBeenCalled();
  });

  it.each([
    ["qualified", "Qualified", "Enabled for this deck."],
    ["unsupported", "Unsupported", "stage is not the authored size"],
    ["off", "Off", "Using the deck’s native movie playback."],
    ["pending", "Checking", "Checking this deck and output size."],
  ] as const)("shows observed %s continuity before Show output", async (mode, label, detail) => {
    const continuity: LiveContinuity = { mode, ...(mode === "unsupported" ? { reason: detail } : {}) };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const badge = await screen.findByText(`Movie continuity · ${label}`);
    expect(screen.getByText(detail)).toBeInTheDocument();
    const show = screen.getByRole("button", { name: "Show output" });
    expect(badge.compareDocumentPosition(show) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    [undefined, "Enabled for this deck."],
    [1, "Enabled for this deck."],
    [1.3333, "Enabled for this deck (stage scaled ×1.33)."],
  ] as const)("shows scale %s in the qualified continuity detail", async (scale, detail) => {
    const continuity: LiveContinuity = { mode: "qualified", ...(scale === undefined ? {} : { scale }) };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · Qualified");
    expect(screen.getByText(detail)).toBeInTheDocument();
  });

  it("does not claim qualification when the host omits continuity status", async () => {
    const api = client({ state: vi.fn(async () => state()) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByText("Movie continuity · Unavailable")).toBeInTheDocument();
    expect(screen.getByText("This session has not reported movie continuity status.")).toBeInTheDocument();
    expect(screen.queryByText("Movie continuity · Qualified")).not.toBeInTheDocument();
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

  it("warns about every unplayable movie above Show output", async () => {
    const codecWarnings = ["clip.mov (hvc1) may not play in this output", "sting.mov (apcn) may not play in this output"];
    const output = { ...state().output, codecWarnings };
    const api = client({ state: vi.fn(async () => state({ outputVisible: false, output })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    const heading = await screen.findByText("Some movies may not play in this output");
    for (const warning of codecWarnings) expect(screen.getByText(warning)).toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
    const show = screen.getByRole("button", { name: "Show output" });
    expect(heading.compareDocumentPosition(show) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
    await screen.findByText("Movie continuity · Qualified");
    expect(screen.queryByText(/movie not carried/)).not.toBeInTheDocument();
  });

  it("names a cut continuity declines under the continuity badge", async () => {
    const continuity: LiveContinuity = {
      mode: "qualified",
      notCarried: [{ fromSlide: 3, toSlide: 4, asset: "clip.mov", reason: "artwork overlaps the carried movie" }],
    };
    const api = client({ state: vi.fn(async () => state({ continuity })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · Qualified");
    expect(screen.getByText("Slide 3 → 4: movie not carried — artwork overlaps the carried movie")).toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
  });

  it("caps the declined-cut list at three and counts the rest", async () => {
    const notCarried = Array.from({ length: 5 }, (_, index) => ({
      fromSlide: index + 1, toSlide: index + 2, asset: `clip-${index + 1}.mov`, reason: `reason ${index + 1}`,
    }));
    const api = client({ state: vi.fn(async () => state({ continuity: { mode: "qualified", notCarried } })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByText("Movie continuity · Qualified");
    for (const entry of notCarried.slice(0, 3)) {
      expect(screen.getByText(`Slide ${entry.fromSlide} → ${entry.toSlide}: movie not carried — ${entry.reason}`)).toBeInTheDocument();
    }
    for (const entry of notCarried.slice(3)) {
      expect(screen.queryByText(`Slide ${entry.fromSlide} → ${entry.toSlide}: movie not carried — ${entry.reason}`)).not.toBeInTheDocument();
    }
    expect(screen.getByText("+2 more")).toBeInTheDocument();
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
    const sidebarButton = screen.getByRole("button", { name: "Alpha Keynote" });
    sidebarButton.focus();
    await act(async () => { fireEvent.keyDown(sidebarButton, { key: "1" }); });
    expect(screen.getByText("Go to: 1 (Esc clears)")).toBeInTheDocument();
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
    expect(screen.getByText("Movie continuity is available only for qualified decks. Alpha output is not qualified.")).toBeInTheDocument();
  });

  it("allows output hiding while the player is busy but blocks navigation", async () => {
    const api = client({ state: vi.fn(async () => state({ status: "busy" })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByRole("button", { name: "Hide output" })).toBeEnabled();
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
    expect(screen.getByText("Match the standard the Pulse shows")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Keyer on" })).toBeChecked();
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
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Keyer on" })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: "Keyer on" }));
    await waitFor(() => expect(api.saveOutputSettings).toHaveBeenCalledWith({ ...keyerSettings, akOutputRate: 30, akKeyer: "off" }));
    expect(screen.getByRole("checkbox", { name: "Keyer on" })).not.toBeChecked();
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
    expect(screen.getByRole("checkbox", { name: "Keyer on" })).toBeDisabled();
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
