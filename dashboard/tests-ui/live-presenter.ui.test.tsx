import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LivePresenter } from "../src/live/LivePresenter";
import type { LiveClient, LiveCommand, LiveResult, LiveSnapshot } from "../src/live/api";

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
    vi.stubGlobal("crypto", { randomUUID: () => "request-1" });
  });

  it("starts only a prepared deck on the selected detected display", async () => {
    const api = client();
    render(<LivePresenter client={api} pollMs={60_000} />);
    await screen.findByRole("option", { name: /Sunday service/ });
    fireEvent.click(screen.getByRole("button", { name: "Start output session" }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith("prepared-1", "screen-2"));
    expect(screen.queryByTitle(/player|preview/i)).not.toBeInTheDocument();
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
    expect(screen.getByText("Native HTML playback only; alpha and movie continuity are not qualified.")).toBeInTheDocument();
  });

  it("allows output hiding while the player is busy but blocks navigation", async () => {
    const api = client({ state: vi.fn(async () => state({ status: "busy" })) });
    render(<LivePresenter client={api} pollMs={60_000} />);
    expect(await screen.findByRole("button", { name: "Hide output" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Advance" })).toBeDisabled();
  });
});
