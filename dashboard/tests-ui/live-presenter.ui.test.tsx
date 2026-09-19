import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LivePresenter } from "../src/live/LivePresenter";
import { liveClient, type LiveClient, type LiveCommand, type LiveContinuity, type LiveResult, type LiveSnapshot } from "../src/live/api";

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

function client(overrides: Partial<LiveClient> = {}): LiveClient {
  return {
    state: vi.fn(async () => null),
    decks: vi.fn(async () => [{ previewJobId: "prepared-1", name: "Sunday service", slides: 3, sourceDigest: "source" }]),
    displays: vi.fn(async () => [{ id: "screen-2", name: "HDMI projector", width: 1920, height: 1080, x: 0, y: 0, primary: true }]),
    start: vi.fn(async () => state()),
    command: vi.fn(async (_sessionId: string, command: LiveCommand): Promise<LiveResult> => ({ requestId: command.requestId, outcome: "completed", state: state() })),
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
