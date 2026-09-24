import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OutputEngine } from "../src/live/OutputEngine";
import type { LiveClient, LiveEngine, LiveEngineAction, LiveEngineWarning } from "../src/live/api";

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

function client(overrides: Partial<LiveClient> = {}): LiveClient {
  return {
    state: vi.fn(async () => null),
    decks: vi.fn(async () => []),
    displays: vi.fn(async () => []),
    start: vi.fn(),
    command: vi.fn(),
    engine: vi.fn(async () => engineState()),
    engineAction: vi.fn(async () => engineState()),
    outputSettings: vi.fn(),
    saveOutputSettings: vi.fn(),
    ...overrides,
  };
}

const WARNINGS: [LiveEngineWarning, string[]][] = [
  [{ id: "obsMissing", severity: "block", text: "Output engine not installed. Install OBS 32.2.2 into Applications, then press Check again." }, ["Check again"]],
  [{ id: "obsVersion", severity: "block", text: "Output engine is OBS 31.0.0; Alpha Keynote needs OBS 32.2.2. Install 32.2.2, then press Check again." }, ["Check again"]],
  [{ id: "obsUncleanExit", severity: "warn", text: "OBS closed unexpectedly last time. It has been restarted; check the output before going live." }, []],
  [{ id: "obsWaiting", severity: "block", text: "OBS is waiting for an answer or a permission. Press Show OBS, answer it, then press Check again." }, ["Show OBS", "Check again"]],
  [{ id: "obsSafeMode", severity: "block", text: "OBS started in Safe Mode, so Alpha Keynote cannot watch it. Press Restart output engine and choose Normal Mode when OBS asks." }, ["Restart output engine"]],
  [{ id: "obsExited", severity: "block", text: "OBS stopped unexpectedly — nothing is going to the keyer. Press Restart output engine. OBS may then ask a question (see Show OBS)." }, ["Restart output engine"]],
  [{ id: "noDevice", severity: "warn", text: "No output device set for 25 fps — the keyer receives nothing. With the UltraStudio connected, press Set up output device (one time)." }, ["Set up output device"]],
  [{ id: "deviceInactive", severity: "block", text: "Alpha Keynote cannot open the UltraStudio. If ProPresenter is running, remove its SDI screen in Screen Configuration or quit ProPresenter; otherwise check the Thunderbolt cable and Desktop Video. Then press Release output and Take output again." }, ["Release output", "Take output"]],
  [{ id: "stuck", severity: "block", text: "OBS is not responding to Quit. Press Show OBS and quit it from the OBS menu, then press Check again." }, ["Show OBS"]],
  [{ id: "ownedElsewhere", severity: "block", text: "The output engine is being used by another dashboard window (pid 4242). Close that dashboard first." }, ["Check again"]],
];

const ACTIONS: Record<string, LiveEngineAction> = {
  "Check again": "check",
  "Show OBS": "show",
  "Restart output engine": "restart",
  "Set up output device": "setupDevice",
  "Release output": "quit",
  "Take output": "start",
};

describe("OutputEngine", () => {
  it.each(WARNINGS)("shows the $id warning with its action buttons", async (warning, buttons) => {
    const blocked = engineState({ state: warning.id === "stuck" ? "stuck" : "blocked", warnings: [warning] });
    const api = client({ engine: vi.fn(async () => blocked), engineAction: vi.fn(async () => blocked) });
    render(<OutputEngine client={api} rate={25} sessionLoaded={false} pollMs={60_000} />);
    const item = await screen.findByRole("listitem", { name: warning.text });
    expect(item).toHaveAttribute("data-severity", warning.severity);
    expect(within(item).queryAllByRole("button").map((button) => button.textContent)).toEqual(buttons);
    for (const label of buttons) {
      const button = within(screen.getByRole("listitem", { name: warning.text })).getByRole("button", { name: label });
      await waitFor(() => expect(button).toBeEnabled());
      await act(async () => { fireEvent.click(button); });
      expect(api.engineAction).toHaveBeenLastCalledWith(ACTIONS[label]);
    }
    expect(api.engineAction).toHaveBeenCalledTimes(buttons.length);
  });

  it("raises the engine-exited warning as an alert during a session", async () => {
    const warning = WARNINGS.find(([entry]) => entry.id === "obsExited")![0];
    const api = client({ engine: vi.fn(async () => engineState({ state: "blocked", warnings: [warning] })) });
    render(<OutputEngine client={api} rate={25} sessionLoaded pollMs={60_000} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(warning.text);
  });

  it("Take output starts the engine and Release output quits it", async () => {
    const api = client({
      engine: vi.fn(async () => engineState({ state: "stopped" })),
      engineAction: vi.fn(async (action: LiveEngineAction) => engineState({ state: action === "start" ? "ready" : "stopped" })),
    });
    render(<OutputEngine client={api} rate={25} sessionLoaded={false} pollMs={60_000} />);
    await screen.findByText("Output engine · Released");
    expect(screen.getByRole("button", { name: "Release output" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Take output" }));
    await waitFor(() => expect(api.engineAction).toHaveBeenCalledWith("start"));
    await screen.findByText("Output engine · Ready");
    expect(screen.getByRole("button", { name: "Take output" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Release output" }));
    await waitFor(() => expect(api.engineAction).toHaveBeenCalledWith("quit"));
    await screen.findByText("Output engine · Released");
    expect(api.engineAction).toHaveBeenCalledTimes(2);
  });

  it("does not start the engine on mount", async () => {
    const api = client({ engine: vi.fn(async () => engineState({ state: "stopped" })) });
    render(<OutputEngine client={api} rate={25} sessionLoaded={false} pollMs={60_000} />);
    await screen.findByText("Output engine · Released");
    expect(api.engineAction).not.toHaveBeenCalled();
  });

  it("disables Release output while a session is loaded", async () => {
    render(<OutputEngine client={client()} rate={25} sessionLoaded pollMs={60_000} />);
    await screen.findByText("Output engine · Ready");
    expect(screen.getByRole("button", { name: "Release output" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Release output" })).toHaveAttribute("title", "Stop the show first.");
  });

  it("shows a refused action's detail", async () => {
    const api = client({ engineAction: vi.fn(async () => { throw new Error("Stop the show first."); }) });
    render(<OutputEngine client={api} rate={25} sessionLoaded={false} pollMs={60_000} />);
    await screen.findByText("Output engine · Ready");
    fireEvent.click(screen.getByRole("button", { name: "Release output" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stop the show first.");
  });

  it("walks the one-time device setup: Set up output device, instructions, Done", async () => {
    const noDevice = WARNINGS.find(([entry]) => entry.id === "noDevice")![0];
    const noDevice30 = { ...noDevice, text: noDevice.text.replace("25 fps", "30 fps") };
    const api = client({
      engine: vi.fn(async () => engineState({ device: { name: null, set: false }, warnings: [noDevice30] })),
      engineAction: vi.fn(async (action: LiveEngineAction) => action === "setupDone"
        ? engineState()
        : engineState({ state: "starting", device: { name: null, set: false }, warnings: [noDevice30] })),
    });
    render(<OutputEngine client={api} rate={30} sessionLoaded={false} pollMs={60_000} />);
    expect(await screen.findByText("Output device · Not set up")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set up output device" }));
    await waitFor(() => expect(api.engineAction).toHaveBeenCalledWith("setupDevice"));
    expect(await screen.findByText("In OBS: Tools → Decklink Output → pick UltraStudio HD Mini, Mode 1080p30, Keyer External, Pixel format BGRA 8-bit, tick Auto start, press Start, then OK. Then press Done here.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.engineAction).toHaveBeenCalledWith("setupDone"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument());
    expect(screen.queryByText(/^In OBS: Tools/)).not.toBeInTheDocument();
    expect(screen.getByText("Output device · UltraStudio HD Mini")).toBeInTheDocument();
  });

  it("keeps the setup instructions when Done is refused", async () => {
    const noDevice = WARNINGS.find(([entry]) => entry.id === "noDevice")![0];
    const api = client({
      engine: vi.fn(async () => engineState({ device: { name: null, set: false }, warnings: [noDevice] })),
      engineAction: vi.fn(async (action: LiveEngineAction) => {
        if (action === "setupDone") throw new Error("OBS did not write the device file.");
        return engineState({ state: "starting", device: { name: null, set: false }, warnings: [noDevice] });
      }),
    });
    render(<OutputEngine client={api} rate={25} sessionLoaded={false} pollMs={60_000} />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up output device" }));
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("OBS did not write the device file.");
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(screen.getByText(/Mode 1080p25/)).toBeInTheDocument();
  });

  it("polls the engine state and reports it to the parent", async () => {
    const onEngine = vi.fn();
    const engine = vi.fn()
      .mockResolvedValueOnce(engineState({ state: "starting" }))
      .mockResolvedValue(engineState());
    vi.useFakeTimers();
    try {
      const view = render(<OutputEngine client={client({ engine })} rate={25} sessionLoaded={false} pollMs={2000} onEngine={onEngine} />);
      await act(async () => {});
      expect(screen.getByText("Output engine · Starting")).toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect(screen.getByText("Output engine · Ready")).toBeInTheDocument();
      expect(engine).toHaveBeenCalledTimes(2);
      expect(onEngine).toHaveBeenLastCalledWith(expect.objectContaining({ state: "ready" }));
      view.unmount();
      expect(onEngine).toHaveBeenLastCalledWith(null);
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(engine).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
