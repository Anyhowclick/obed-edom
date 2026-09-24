import { useCallback, useEffect, useRef, useState } from "react";
import { liveClient, type LiveClient, type LiveContinuity, type LiveDisplay, type LiveEngine, type LiveOperation, type LiveOutputSettings, type LivePreparedDeck, type LiveSlide, type LiveSnapshot } from "./api";
import { engineBlocks, OutputEngine } from "./OutputEngine";
import "./live.css";

function Still({ slide, label }: { slide?: LiveSlide; label: string }) {
  return <figure className="live-still">
    <figcaption>{label}{slide ? ` · Slide ${slide.originalOrdinal}` : ""} · Still preview</figcaption>
    {slide?.thumbnailUrl ? <img src={slide.thumbnailUrl} alt={`Slide ${slide.originalOrdinal} still`} /> : <div className="live-placeholder">{slide ? "Still unavailable" : "No slide"}</div>}
  </figure>;
}

function ContinuityStatus({ continuity }: { continuity?: LiveContinuity }) {
  const mode = continuity?.mode;
  const label = mode === "qualified" ? "Qualified" : mode === "unsupported" ? "Unsupported" : mode === "off" ? "Off" : mode === "pending" ? "Checking" : "Unavailable";
  const detail = continuity?.reason || (mode === "qualified"
    ? (continuity?.scale && continuity.scale !== 1 ? `Enabled for this deck (stage scaled ×${continuity.scale.toFixed(2)}).` : "Enabled for this deck.")
    : mode === "unsupported" || mode === "off"
      ? "Using the deck’s native movie playback."
      : mode === "pending"
        ? "Checking this deck and output size."
        : "This session has not reported movie continuity status.");
  const notCarried = continuity?.notCarried ?? [];
  const visible = notCarried.slice(0, 3);
  const hidden = notCarried.length - visible.length;
  return <div className="live-continuity" aria-live="polite">
    <span className="live-continuity-badge" data-mode={mode || "unknown"}>Movie continuity · {label}</span>
    <p className="note">{detail}</p>
    {notCarried.length > 0 && <ul className="note live-continuity-not-carried">
      {visible.map((entry, index) => <li key={`${index}-${entry.asset}`}>Slide {entry.fromSlide} → {entry.toSlide}: movie not carried — {entry.reason}</li>)}
      {hidden > 0 && <li>+{hidden} more</li>}
    </ul>}
  </div>;
}

function MovieWarnings({ warnings, heading }: { warnings?: string[]; heading: string }) {
  if (!warnings?.length) return null;
  const visible = warnings.slice(0, 5);
  const hidden = warnings.length - visible.length;
  return <div className="live-codecs" aria-live="polite">
    <span className="live-continuity-badge" data-mode="unsupported">{heading}</span>
    <ul className="note">
      {visible.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
      {hidden > 0 && <li>+{hidden} more</li>}
    </ul>
  </div>;
}

export function LivePresenter({ client = liveClient, previewJobId = "", pollMs = 1000, enginePollMs = 2000 }: { client?: LiveClient; previewJobId?: string; pollMs?: number; enginePollMs?: number }) {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const observed = useRef<LiveSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [pending, setPending] = useState(false);
  const [stopPending, setStopPending] = useState(false);
  const inFlight = useRef(false);
  const stopInFlight = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(false);
  const [connectionError, setConnectionError] = useState("");
  const [message, setMessage] = useState("");
  const [awaitingObservation, setAwaitingObservation] = useState(false);
  const [decks, setDecks] = useState<LivePreparedDeck[]>([]);
  const [displays, setDisplays] = useState<LiveDisplay[]>([]);
  const [jobId, setJobId] = useState(previewJobId);
  const [displayId, setDisplayId] = useState("");
  const [continuityEnabled, setContinuityEnabled] = useState(true);
  const [target, setTarget] = useState("");
  const [digits, setDigits] = useState("");
  const [upcomingCount, setUpcomingCount] = useState(3);
  const [outputSettings, setOutputSettings] = useState<LiveOutputSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [engine, setEngine] = useState<LiveEngine | null>(null);

  const accept = useCallback((next: LiveSnapshot | null) => {
    const current = observed.current;
    if (current && next?.sessionId === current.sessionId && next.revision < current.revision) return;
    observed.current = next;
    setSnapshot(next);
  }, []);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const epoch = generation.current;
      try {
        if (!inFlight.current) {
          const next = await client.state();
          if (!cancelled && epoch === generation.current) {
            accept(next);
            setConnected(true);
            setConnectionError("");
          }
        }
      } catch (error) {
        if (!cancelled && epoch === generation.current) {
          setConnected(false);
          setConnectionError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (!cancelled) timer = setTimeout(refresh, pollMs);
      }
    }
    void refresh();
    return () => { cancelled = true; mounted.current = false; generation.current++; clearTimeout(timer); };
  }, [accept, client, pollMs]);

  useEffect(() => {
    let cancelled = false;
    async function loadChoices() {
      try {
        const [nextDecks, nextDisplays] = await Promise.all([client.decks(), client.displays()]);
        if (cancelled) return;
        setDecks(nextDecks);
        setDisplays(nextDisplays);
        setJobId((selected) => nextDecks.some((deck) => deck.previewJobId === selected) ? selected : nextDecks[0]?.previewJobId || "");
        setDisplayId((selected) => {
          if (nextDisplays.some((display) => display.id === selected)) return selected;
          return nextDisplays.find((display) => !display.primary)?.id || nextDisplays[0]?.id || "";
        });
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : String(error));
      }
    }
    void loadChoices();
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    client.outputSettings().then((settings) => { if (!cancelled) setOutputSettings(settings); }).catch((error) => {
      if (!cancelled) setMessage(error instanceof Error ? error.message : String(error));
    });
    return () => { cancelled = true; };
  }, [client]);

  async function saveOutputSettings(patch: Partial<LiveOutputSettings>) {
    if (!outputSettings || savingSettings) return;
    setSavingSettings(true);
    setMessage("");
    try {
      const saved = await client.saveOutputSettings({ ...outputSettings, ...patch });
      if (mounted.current) setOutputSettings(saved);
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mounted.current) setSavingSettings(false);
    }
  }

  useEffect(() => {
    if (awaitingObservation && snapshot && (snapshot.status === "ready" || snapshot.status === "error" || snapshot.status === "stopped")) {
      setAwaitingObservation(false);
    }
  }, [awaitingObservation, snapshot]);

  const disabledReason = useCallback((operation: LiveOperation): string => {
    if (!connected) return "Waiting for connection to output host";
    if (!snapshot || snapshot.status === "stopped") return "No active session";
    if (operation === "stop") return stopPending ? "Waiting for command acknowledgment" : "";
    if (pending || stopPending) return "Waiting for command acknowledgment";
    if ((operation === "advance" || operation === "goTo") && snapshot.status !== "ready") return `Player is ${snapshot.status}`;
    if ((operation === "hide" || operation === "show") && snapshot.status !== "ready" && snapshot.status !== "busy") return `Player is ${snapshot.status}`;
    const capability = snapshot.capabilities?.[operation] || { supported: false, reason: "Not available in this player state" };
    return capability.supported ? "" : capability.reason || "Not supported by this player";
  }, [connected, snapshot, pending, stopPending]);

  const send = useCallback(async (operation: LiveOperation, slide?: number) => {
    const current = observed.current;
    if (!current) return;
    const isStop = operation === "stop";
    const reason = disabledReason(operation);
    if (reason) { setMessage(reason); return; }
    if (isStop ? stopInFlight.current : inFlight.current) return;
    if (isStop) { stopInFlight.current = true; setStopPending(true); }
    else { inFlight.current = true; setPending(true); }
    const epoch = ++generation.current;
    setMessage("");
    try {
      const result = await client.command(current.sessionId, { requestId: crypto.randomUUID(), operation, ...(slide === undefined ? {} : { slide }) });
      if (mounted.current && generation.current === epoch && result.state.sessionId === current.sessionId) {
        accept(result.state);
        setAwaitingObservation(result.outcome === "accepted");
        setMessage(result.outcome === "rejected" ? result.reason || "Command rejected" : "");
      }
    } catch (error) {
      if (mounted.current && generation.current === epoch) {
        setConnected(false);
        setConnectionError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (isStop) { stopInFlight.current = false; if (mounted.current) setStopPending(false); }
      else { inFlight.current = false; if (mounted.current) setPending(false); }
    }
  }, [accept, client, disabledReason]);

  const goTo = useCallback((value: string) => {
    if (!/^\d+$/.test(value)) { setMessage("Enter an original slide number."); return; }
    const slide = Number(value);
    const entry = observed.current?.slides.find((item) => item.originalOrdinal === slide);
    if (!entry || entry.skipped) { setMessage(entry?.skipped ? `Slide ${slide} is skipped and unavailable.` : `Slide ${slide} is unavailable.`); return; }
    void send("goTo", slide);
  }, [send]);

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      const element = event.target;
      const editing = element instanceof HTMLElement && (element.isContentEditable || element.closest("input, textarea, select, [contenteditable], [role=textbox]"));
      const button = element instanceof HTMLElement && element.closest("button, [role=button]");
      if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey || editing) return;
      if (/^\d$/.test(event.key)) { event.preventDefault(); setDigits((value) => (value + event.key).slice(0, 6)); }
      else if (event.key === "Enter" && digits) { event.preventDefault(); goTo(digits); setDigits(""); }
      else if (event.key === "Escape") setDigits("");
      else if ((event.key === " " || event.key === "ArrowRight") && !digits && !button) { event.preventDefault(); void send("advance"); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [digits, goTo, send]);

  async function start() {
    if (inFlight.current || !connected || !jobId.trim() || engineReason) return;
    inFlight.current = true;
    setPending(true);
    const epoch = ++generation.current;
    setMessage("");
    try {
      const display = keyer ? undefined : displayId || undefined;
      const next = continuityEnabled
        ? await client.start(jobId, display)
        : await client.start(jobId, display, "off");
      if (mounted.current && epoch === generation.current) accept(next);
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error ? error.message : String(error));
    } finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }

  const current = snapshot?.slides.find((slide) => slide.originalOrdinal === snapshot.originalSlide);
  const available = snapshot?.slides.filter((slide) => !slide.skipped) || [];
  const currentIndex = available.findIndex((slide) => slide.originalOrdinal === snapshot?.originalSlide);
  const upcoming = currentIndex < 0 ? [] : available.slice(currentIndex + 1, currentIndex + 1 + upcomingCount);
  const visibilityOperation = snapshot?.outputVisible ? "hide" : "show";
  const active = !!snapshot && snapshot.status !== "stopped";
  const keyer = outputSettings?.akOutputMode === "keyer";
  const engineReason = keyer ? engineBlocks(engine) : "";
  const outputLocked = !outputSettings || savingSettings || active;
  return <section className="live-presenter" aria-label="Live presenter">
    <h1>Alpha Keynote</h1>
    <p className="lede">Experimental silent HDMI output. The picture is 16:9 within the detected display. DeckLink fill + key is not qualified.</p>
    <p className="note">Movie continuity is available only for qualified decks. Alpha output is not qualified.</p>
    <p role="status">{connected ? snapshot ? `Player ${snapshot.status} · Output ${snapshot.outputVisible ? "visible" : "hidden"}` : "No active session" : connectionError ? "Disconnected · Reconnecting…" : "Connecting…"}</p>
    {connectionError && <p role="alert">{connectionError}. Existing output may still be running; commands are disabled until reconnected.</p>}
    {(message || awaitingObservation || snapshot?.error) && <p role="alert">{message || (awaitingObservation ? "Command accepted; waiting for observed player state." : snapshot?.error)}</p>}
    <div className="actions live-output-settings">
      <label>Output
        <select aria-label="Output" value={outputSettings?.akOutputMode ?? "screen"} disabled={outputLocked} title={active ? "Stop the show first." : ""} onChange={(event) => void saveOutputSettings({ akOutputMode: event.target.value as LiveOutputSettings["akOutputMode"] })}>
          <option value="screen">Screen (HDMI)</option>
          <option value="keyer">Keyer (fill + key via UltraStudio)</option>
        </select>
      </label>
      {keyer && outputSettings && <>
        <label>Match the standard the Pulse shows
          <select aria-label="Output rate" value={outputSettings.akOutputRate} disabled={outputLocked} title={active ? "Stop the show first." : ""} onChange={(event) => void saveOutputSettings({ akOutputRate: Number(event.target.value) as LiveOutputSettings["akOutputRate"] })}>
            <option value={25}>25 fps</option>
            <option value={30}>30 fps</option>
          </select>
        </label>
        <label>
          <input type="checkbox" checked={outputSettings.akKeyer === "external"} disabled={outputLocked} onChange={(event) => void saveOutputSettings({ akKeyer: event.target.checked ? "external" : "off" })} />
          Keyer on
        </label>
      </>}
    </div>
    {keyer && outputSettings && <OutputEngine client={client} rate={outputSettings.akOutputRate} sessionLoaded={active} pollMs={enginePollMs} onEngine={setEngine} />}
    {!active && <form className="actions" onSubmit={(event) => { event.preventDefault(); void start(); }}>
      <label>Prepared deck
        <select aria-label="Prepared deck" value={jobId} onChange={(event) => setJobId(event.target.value)} disabled={!decks.length}>
          {decks.length ? decks.map((deck) => <option key={deck.previewJobId} value={deck.previewJobId}>{deck.name} · {deck.slides} slides</option>) : <option value="">No prepared decks available</option>}
        </select>
      </label>
      {!keyer && <label>Output display
        <select aria-label="Output display" value={displayId} onChange={(event) => setDisplayId(event.target.value)} disabled={!displays.length}>
          {displays.length ? displays.map((display) => <option key={display.id} value={display.id}>{display.name} · {display.width} × {display.height}{display.primary ? " · Primary" : ""}</option>) : <option value="">No display detected</option>}
        </select>
      </label>}
      <label className="live-continuity-choice">
        <input type="checkbox" checked={continuityEnabled} disabled={pending} onChange={(event) => setContinuityEnabled(event.target.checked)} />
        Enable movie continuity when qualified
      </label>
      <p className="note live-continuity-help">Applies to the next session. Check its continuity status before showing output.</p>
      {!decks.length && <p className="note">Prepare a deck in Sermon Checker with Build Preview first. Live output never creates a new export.</p>}
      <button className="btn" disabled={!connected || pending || !jobId || (keyer ? !!engineReason : !displays.length)} title={engineReason}>Start output session</button>
    </form>}
    {active && <ContinuityStatus continuity={snapshot.continuity} />}
    {active && <MovieWarnings warnings={snapshot.output.codecWarnings} heading="Some movies may not play in this output" />}
    {active && <MovieWarnings warnings={snapshot.output.rateWarnings} heading="Some movies do not match the output rate" />}
    {snapshot && <>
      <p className="note">Slide {snapshot.originalSlide ?? "unknown"} · Build {snapshot.buildIndex ?? "unknown"} · Display {snapshot.output.width} × {snapshot.output.height} · Audio off</p>
      {snapshot.autoPlayDeferred && <p className="note" aria-live="polite">{snapshot.autoPlayDeferred}</p>}
      <Still slide={current} label="Current" />
      <p className="live-notes"><strong>Presenter notes</strong><br />{current?.notes || "Presenter notes are unavailable in this prepared export."}</p>
      <div className="actions">
        <button className="btn" disabled={!!disabledReason("advance")} title={disabledReason("advance")} onClick={() => void send("advance")}>Advance</button>
        <button className="btn secondary" disabled={!!disabledReason(visibilityOperation)} title={disabledReason(visibilityOperation)} onClick={() => void send(visibilityOperation)}>{snapshot.outputVisible ? "Hide output" : "Show output"}</button>
        <button className="btn secondary" disabled={!!disabledReason("stop")} title={disabledReason("stop")} onClick={() => void send("stop")}>Stop session</button>
      </div>
      <p className="note">Hiding keeps playback running. Closing this presenter leaves the session running.</p>
      {(["advance", "goTo", "hide", "show"] as const).filter((operation) => !snapshot.capabilities?.[operation]?.supported).map((operation) => <p className="note" key={operation}>{operation === "goTo" ? "Go to slide" : operation}: {snapshot.capabilities?.[operation]?.reason || "Not supported by this player"}</p>)}
      <form className="actions" onSubmit={(event) => { event.preventDefault(); goTo(target); }}>
        <label>Go to slide <input inputMode="numeric" value={target} onChange={(event) => setTarget(event.target.value)} /></label>
        <button className="btn secondary" disabled={!!disabledReason("goTo")} title={disabledReason("goTo")}>Go</button>
      </form>
      <p className="note">Type a slide number then Enter, or use the field above. Space / right arrow advances. {digits && <strong>Go to: {digits} (Esc clears)</strong>}</p>
      <label>Upcoming slides <select value={upcomingCount} onChange={(event) => setUpcomingCount(Number(event.target.value))}>{[1, 2, 3, 4].map((count) => <option key={count}>{count}</option>)}</select></label>
      <div className="live-upcoming">{upcoming.map((slide, index) => <Still key={slide.originalOrdinal} slide={slide} label={index === 0 ? "Next" : "Upcoming"} />)}</div>
      <details><summary>Deck slides</summary><ol className="live-deck">{snapshot.slides.map((slide) => <li key={slide.originalOrdinal}><button className="btn secondary" disabled={slide.skipped || !!disabledReason("goTo")} onClick={() => goTo(String(slide.originalOrdinal))}>Slide {slide.originalOrdinal}{slide.skipped ? " · Skipped / unavailable" : ""}</button></li>)}</ol></details>
    </>}
  </section>;
}
