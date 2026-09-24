import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveClient, LiveEngine, LiveEngineAction, LiveEngineWarning } from "./api";

const ACTION_LABELS: Record<LiveEngineAction, string> = {
  start: "Take output",
  quit: "Release output",
  show: "Show OBS",
  restart: "Restart output engine",
  check: "Check again",
  setupDevice: "Set up output device",
  setupDone: "Done",
};

const WARNING_ACTIONS: Record<string, LiveEngineAction[]> = {
  obsMissing: ["check"],
  obsVersion: ["check"],
  obsUncleanExit: [],
  obsWaiting: ["show", "check"],
  obsSafeMode: ["restart"],
  obsExited: ["restart"],
  obsPageLost: ["restart"],
  engineError: ["restart"],
  obsUnreachable: ["restart"],
  noDevice: ["setupDevice"],
  deviceInactive: ["quit", "start"],
  stuck: ["show", "check"],
  obsIdentityUnknown: ["check"],
  ownedElsewhere: ["check"],
};

const DEAD_OUTPUT = new Set(["obsExited", "obsPageLost", "engineError", "obsUnreachable"]);

function allowedWhileLoaded(action: LiveEngineAction, warningId?: string): boolean {
  if (action === "check" || action === "show") return true;
  return action === "restart" && !!warningId && DEAD_OUTPUT.has(warningId);
}

const STATE_LABELS: Record<LiveEngine["state"], string> = {
  unavailable: "Unavailable",
  stopped: "Released",
  starting: "Starting",
  ready: "Ready",
  blocked: "Blocked",
  stuck: "Not responding",
  quitting: "Releasing",
};

export function engineBlocks(engine: LiveEngine | null): string {
  if (!engine) return "Checking the output engine";
  const block = engine.warnings.find((warning) => warning.severity === "block");
  if (block) return block.text;
  return engine.state === "ready" ? "" : "Take output and wait until the output engine is ready";
}

function warningActions(warning: LiveEngineWarning): LiveEngineAction[] {
  return WARNING_ACTIONS[warning.id] ?? (warning.action && warning.action in ACTION_LABELS ? [warning.action as LiveEngineAction] : []);
}

export function OutputEngine({ client, sessionLoaded, pollMs = 2000, onEngine }: {
  client: LiveClient;
  sessionLoaded: boolean;
  pollMs?: number;
  onEngine?: (engine: LiveEngine | null) => void;
}) {
  const [engine, setEngine] = useState<LiveEngine | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const mounted = useRef(false);
  const generation = useRef(0);

  const accept = useCallback((next: LiveEngine | null) => {
    setEngine(next);
    onEngine?.(next);
  }, [onEngine]);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const epoch = generation.current;
      try {
        const next = await client.engine();
        if (!cancelled && epoch === generation.current) accept(next);
      } catch (error) {
        if (!cancelled && epoch === generation.current) setMessage(error instanceof Error ? error.message : String(error));
      } finally {
        if (!cancelled) timer = setTimeout(refresh, pollMs);
      }
    }
    void refresh();
    return () => { cancelled = true; mounted.current = false; generation.current++; clearTimeout(timer); };
  }, [accept, client, pollMs]);

  useEffect(() => () => onEngine?.(null), [onEngine]);

  async function run(action: LiveEngineAction) {
    if (busy) return;
    setBusy(true);
    setMessage("");
    const epoch = ++generation.current;
    try {
      const next = await client.engineAction(action);
      if (mounted.current && epoch === generation.current) accept(next);
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  const state = engine?.state;
  const setup = engine?.setup ?? null;
  const locked = (action: LiveEngineAction, warningId?: string) => busy || (sessionLoaded && !allowedWhileLoaded(action, warningId));
  const takeDisabled = locked("start") || !engine || state === "starting" || state === "ready" || state === "quitting";
  const releaseDisabled = locked("quit") || !engine || state === "stopped" || state === "unavailable" || state === "quitting";
  return <div className="live-engine" aria-label="Output engine">
    <p className="live-engine-state">
      <span className="live-continuity-badge" data-mode={state === "ready" ? "qualified" : state === "blocked" || state === "stuck" ? "unsupported" : "unknown"}>
        Output engine · {engine ? STATE_LABELS[engine.state] : "Checking"}
      </span>
      {engine?.reason && setup === null && <span className="note"> {engine.reason}</span>}
    </p>
    <p className="note">Output device · {engine?.device.set ? engine.device.name || "Set up" : "Not set up"}</p>
    <div className="actions">
      <button type="button" className="btn" disabled={takeDisabled} title={sessionLoaded ? "Stop the show first." : ""} onClick={() => void run("start")}>{ACTION_LABELS.start}</button>
      <button type="button" className="btn secondary" disabled={releaseDisabled} title={sessionLoaded ? "Stop the show first." : ""} onClick={() => void run("quit")}>{ACTION_LABELS.quit}</button>
    </div>
    {message && <p role="alert">{message}</p>}
    {setup !== null && <div className="live-engine-setup" aria-label="Output device setup">
      <p>In OBS: Tools → Decklink Output → pick UltraStudio HD Mini, Mode 1080p{setup}, Keyer External, Pixel format BGRA 8-bit, tick Auto start, press Start, then OK. Then press Done here.</p>
      <button type="button" className="btn" disabled={locked("setupDone")} onClick={() => void run("setupDone")}>{ACTION_LABELS.setupDone}</button>
    </div>}
    {!!engine?.warnings.length && <ul className="live-engine-warnings">
      {engine.warnings.map((warning) => <li
        key={warning.id}
        data-severity={warning.severity}
        role={warning.id === "obsExited" && sessionLoaded ? "alert" : undefined}
        aria-label={warning.text}
      >
        <span>{warning.text}</span>
        {warningActions(warning).map((action) => <button type="button" key={action} className="btn secondary" disabled={locked(action, warning.id)} title={locked(action, warning.id) && sessionLoaded ? "Stop the show first." : ""} onClick={() => void run(action)}>{ACTION_LABELS[action]}</button>)}
      </li>)}
    </ul>}
  </div>;
}
