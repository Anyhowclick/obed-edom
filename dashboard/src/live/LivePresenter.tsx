import { useCallback, useEffect, useRef, useState } from "react";
import { liveClient, type LiveClient, type LiveContinuity, type LiveDisplay, type LiveEngine, type LiveOperation, type LiveOutputSettings, type LivePreparedDeck, type LiveQualification, type LiveSlide, type LiveSnapshot } from "./api";
import { engineBlocks, OutputEngine } from "./OutputEngine";
import { LiveDeckInput } from "./LiveDeckInput";
import { IconChevronLeft } from "../components/icons";
import "./live.css";

function Still({ slide, lazy = false }: { slide?: LiveSlide; lazy?: boolean }) {
  return slide?.thumbnailUrl
    ? <img src={slide.thumbnailUrl} alt={`Slide ${slide.originalOrdinal} still`} loading={lazy ? "lazy" : "eager"} />
    : <div className="live-placeholder">{slide?.skipped ? "Skipped" : slide ? "Still unavailable" : "No slide"}</div>;
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
  const [target, setTarget] = useState("");
  const [digits, setDigits] = useState("");
  const [qualification, setQualification] = useState<(LiveQualification & { outputMode: string }) | null>(null);
  const [checking, setChecking] = useState(false);
  const [qualificationAttempt, setQualificationAttempt] = useState(0);
  const [preparing, setPreparing] = useState(false);
  const selectionTouched = useRef(false);
  const [outputSettings, setOutputSettings] = useState<LiveOutputSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [engine, setEngine] = useState<LiveEngine | null>(null);
  const active = !!snapshot && snapshot.status !== "stopped";
  const qualified = !!qualification?.qualified && qualification.previewJobId === jobId && qualification.outputMode === outputSettings?.akOutputMode;

  const selectDeck = useCallback((id: string) => {
    selectionTouched.current = true;
    setQualification(null);
    setJobId(id);
    setQualificationAttempt((attempt) => attempt + 1);
  }, []);

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
        if (!selectionTouched.current) setJobId((selected) => nextDecks.some((deck) => deck.previewJobId === selected) ? selected : nextDecks[0]?.previewJobId || "");
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
    if (!jobId || !outputSettings || active) { setChecking(false); return; }
    let cancelled = false;
    const outputMode = outputSettings.akOutputMode;
    setChecking(true);
    setQualification(null);
    setMessage("");
    client.qualification(jobId).then((result) => {
      if (!cancelled) setQualification({ ...result, outputMode });
    }).catch((error) => {
      if (!cancelled) setMessage(error instanceof Error ? error.message : String(error));
    }).finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, [active, client, jobId, qualificationAttempt, outputSettings?.akOutputMode]);

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

  const previous = useCallback(() => {
    const state = observed.current;
    const slides = state?.slides.filter((slide) => !slide.skipped) || [];
    const index = slides.findIndex((slide) => slide.originalOrdinal === state?.originalSlide);
    if (index > 0) void send("goTo", slides[index - 1].originalOrdinal);
  }, [send]);

  useEffect(() => {
    if (!active) { setDigits(""); return; }
    function keydown(event: KeyboardEvent) {
      const element = event.target;
      const editing = element instanceof HTMLElement && (element.isContentEditable || element.closest("input, textarea, select, [contenteditable], [role=textbox]"));
      const button = element instanceof HTMLElement && element.closest("button, [role=button]");
      if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey || editing) return;
      if (/^\d$/.test(event.key)) { event.preventDefault(); setDigits((value) => (value + event.key).slice(0, 6)); }
      else if (event.key === "Enter" && digits) { event.preventDefault(); goTo(digits); setDigits(""); }
      else if (event.key === "Escape") setDigits("");
      else if (event.key === "ArrowLeft" && !digits) { event.preventDefault(); previous(); }
      else if ((event.key === "ArrowRight" || (event.key === " " && !button)) && !digits) { event.preventDefault(); void send("advance"); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [active, digits, goTo, previous, send]);

  async function start() {
    if (inFlight.current || !connected || !qualified || preparing || checking || savingSettings || engineReason || (!keyer && !displayId)) return;
    inFlight.current = true;
    setPending(true);
    const epoch = ++generation.current;
    setMessage("");
    try {
      const display = keyer ? undefined : displayId || undefined;
      const next = await client.start(jobId, display);
      if (mounted.current && epoch === generation.current) accept(next);
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error ? error.message : String(error));
    } finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }

  const current = snapshot?.slides.find((slide) => slide.originalOrdinal === snapshot.originalSlide);
  const available = snapshot?.slides.filter((slide) => !slide.skipped) || [];
  const currentIndex = available.findIndex((slide) => slide.originalOrdinal === snapshot?.originalSlide);
  const visibilityOperation = snapshot?.outputVisible ? "hide" : "show";
  const keyer = outputSettings?.akOutputMode === "keyer";
  const engineReason = keyer ? engineBlocks(engine) : "";
  const outputLocked = !outputSettings || savingSettings || active || pending;
  const deckName = active
    ? (qualification?.sourceDigest === snapshot.sourceDigest ? qualification.name : decks.find((deck) => deck.sourceDigest === snapshot.sourceDigest)?.name) || "Presentation"
    : qualification?.name;
  const backReason = disabledReason("goTo") || (currentIndex <= 0 ? "No previous playable slide" : "");
  const startDisabled = !connected || pending || preparing || checking || savingSettings || !qualified || (keyer ? !!engineReason : !displayId);
  return <section className="live-presenter" aria-label="Live presenter">
    <header className="live-heading">
      <div><h1>Alpha Keynote</h1><p className="note" role="status">{connected ? active ? `Player ${snapshot.status} · Output ${snapshot.outputVisible ? "visible" : "hidden"}` : "Add a Keynote, qualify it, then present." : connectionError ? "Disconnected · Reconnecting…" : "Connecting…"}</p></div>
      {active && <div className="actions">
        <button className="btn secondary" disabled={!!disabledReason(visibilityOperation)} title={disabledReason(visibilityOperation)} onClick={() => void send(visibilityOperation)}>{snapshot.outputVisible ? "Hide output" : "Show output"}</button>
        <button className="btn secondary" disabled={!!disabledReason("stop")} title={disabledReason("stop")} onClick={() => void send("stop")}>Stop session</button>
      </div>}
    </header>
    {connectionError && <p className="live-alert" role="alert">{connectionError}. Existing output may still be running; commands are disabled until reconnected.</p>}
    {(message || awaitingObservation || (active && snapshot.error)) && <p className="live-alert" role="alert">{message || (awaitingObservation ? "Command accepted; waiting for observed player state." : snapshot?.error)}</p>}
    {!active && <div className="live-setup">
      <section className="live-panel live-intake">
        <h2>1. Add & qualify</h2>
        <LiveDeckInput disabled={pending || checking} onPrepared={selectDeck} onPreparing={setPreparing} />
        {decks.length > 0 && <label className="live-prepared">Or use a prepared deck
          <select aria-label="Prepared deck" value={jobId} disabled={preparing || pending || checking} onChange={(event) => selectDeck(event.target.value)}>
            <option value="">Choose a prepared deck</option>
            {decks.map((deck) => <option key={deck.previewJobId} value={deck.previewJobId}>{deck.name} · {deck.slides} slides</option>)}
            {!!jobId && !decks.some((deck) => deck.previewJobId === jobId) && <option value={jobId}>{qualification?.name || "Selected Keynote"}</option>}
          </select>
        </label>}
        <div className="live-qualification" aria-live="polite">
          {checking ? <p>Checking deck qualification…</p> : qualification && <>
            <strong className={qualified ? "live-qualified" : "live-unqualified"}>{qualified ? "Deck qualified" : "Not qualified yet"}</strong>
            <p className="note">{qualified ? `${qualification.name} · ${qualification.slides} slides. Output is checked when the session starts.` : qualification.reason}</p>
          </>}
          {!!jobId && !checking && !qualified && <button className="btn secondary" type="button" onClick={() => selectDeck(jobId)}>Check qualification again</button>}
        </div>
        <p className="note">Qualification uses the current playback allowlist. Preparation works from a copy of your Keynote.</p>
      </section>
      <section className="live-panel live-start">
        <h2>2. Present</h2>
        <p className="note">Start with the output hidden, then show it when you are ready.</p>
        <button className="btn" disabled={startDisabled} title={engineReason || (!qualified ? "Qualify a Keynote first" : "")} onClick={() => void start()}>Start output session</button>
      </section>
    </div>}
    {active && <>
      <div className="live-filebar"><strong title={deckName}>{deckName}</strong><span>{snapshot.slides.length} slides</span><span>{snapshot.output.transport === "fill-key" ? "Keyer output" : "Screen output"} · {snapshot.output.width} × {snapshot.output.height}</span><span>Audio off</span></div>
      <div className="live-workspace">
        <section className="live-panel live-slides" aria-label="Deck slides">
          <div className="live-section-heading"><h2>Deck slides</h2><span className="note">Click a slide to jump</span></div>
          <div className="live-slide-grid">{snapshot.slides.map((slide) => {
            const selected = slide.originalOrdinal === snapshot.originalSlide;
            return <button type="button" className={`live-slide-tile${selected ? " selected" : ""}`} key={slide.originalOrdinal} aria-label={`Slide ${slide.originalOrdinal}${slide.skipped ? " · Skipped / unavailable" : ""}`} aria-current={selected ? "true" : undefined} disabled={slide.skipped || !!disabledReason("goTo")} title={slide.skipped ? "Skipped in Keynote" : disabledReason("goTo") || `Go to slide ${slide.originalOrdinal}`} onClick={() => goTo(String(slide.originalOrdinal))}>
              <Still slide={slide} lazy />
              <span className="live-tile-caption"><span>{slide.originalOrdinal}</span>{selected && <strong>{snapshot.outputVisible ? "On screen" : "Current"}</strong>}{slide.skipped && <span>Skipped</span>}</span>
            </button>;
          })}</div>
        </section>
        <aside className="live-current-column">
          <section className="live-panel live-current" aria-label="Current slide">
            <div className="live-section-heading"><h2>Current</h2><span className="note">Still preview</span></div>
            <div className="live-monitor">
              <Still slide={current} />
              <div className="live-transport" aria-label="Slide navigation">
                <button type="button" aria-label="Previous slide" disabled={!!backReason} title={backReason || "Previous slide (←)"} onClick={previous}><IconChevronLeft /></button>
                <button type="button" aria-label="Advance" disabled={!!disabledReason("advance")} title={disabledReason("advance") || "Next build or slide (→ / Space)"} onClick={() => void send("advance")}><IconChevronLeft className="flip" /></button>
              </div>
            </div>
            <p className="live-slide-position">Slide {snapshot.originalSlide ?? "unknown"} · Build {snapshot.buildIndex ?? "unknown"}</p>
            {snapshot.autoPlayDeferred && <p className="note" aria-live="polite">{snapshot.autoPlayDeferred}</p>}
            <p className="note live-keyboard-hint">← Previous slide · → Next build or slide</p>
            <form className="live-jump" onSubmit={(event) => { event.preventDefault(); goTo(target); }}>
              <label htmlFor="live-slide-target">Go to slide</label><input id="live-slide-target" inputMode="numeric" value={target} onChange={(event) => setTarget(event.target.value)} /><button className="btn secondary" disabled={!!disabledReason("goTo")} title={disabledReason("goTo")}>Go</button>
            </form>
            {digits && <p className="note" aria-live="polite">Go to: {digits} · Enter to jump · Esc to clear</p>}
            {current?.notes && <details className="live-notes"><summary>Presenter notes</summary><p>{current.notes}</p></details>}
          </section>
          <div className="live-playback-status">
            <ContinuityStatus continuity={snapshot.continuity} />
            <MovieWarnings warnings={snapshot.output.codecWarnings} heading="Some movies may not play in this output" />
            <MovieWarnings warnings={snapshot.output.rateWarnings} heading="Some movies do not match the output rate" />
            {keyer && engineReason && <p className="live-alert">{engineReason}</p>}
          </div>
        </aside>
      </div>
    </>}
    <details className="live-panel live-output-options" open={!active}>
      <summary>Output settings</summary>
      <div className="live-output-settings">
        <label className="live-output-field">Output
          <select aria-label="Output" value={outputSettings?.akOutputMode ?? "screen"} disabled={outputLocked} title={active ? "Stop the show first." : ""} onChange={(event) => void saveOutputSettings({ akOutputMode: event.target.value as LiveOutputSettings["akOutputMode"] })}>
            <option value="screen">Screen (HDMI)</option><option value="keyer">Keyer (fill + key via UltraStudio)</option>
          </select>
        </label>
        {!keyer && <label className="live-output-field">Output display
          <select aria-label="Output display" value={displayId} disabled={outputLocked || !displays.length} onChange={(event) => setDisplayId(event.target.value)}>
            {displays.length ? displays.map((display) => <option key={display.id} value={display.id}>{display.name} · {display.width} × {display.height}{display.primary ? " · Primary" : ""}</option>) : <option value="">No display detected</option>}
          </select>
        </label>}
        {keyer && outputSettings && <>
          <label className="live-output-field">Output rate
            <select aria-label="Output rate" value={outputSettings.akOutputRate} disabled={outputLocked} title={active ? "Stop the show first." : "Match the standard shown on the Pulse."} onChange={(event) => void saveOutputSettings({ akOutputRate: Number(event.target.value) as LiveOutputSettings["akOutputRate"] })}><option value={25}>25 fps</option><option value={30}>30 fps</option></select>
          </label>
          <div className="live-keyer-row">
            <label className="live-keyer-choice"><input type="checkbox" aria-label="Enable Keyer" aria-describedby="live-keyer-help" checked={outputSettings.akKeyer === "external"} disabled={outputLocked} onChange={(event) => void saveOutputSettings({ akKeyer: event.target.checked ? "external" : "off" })} />Enable Keyer
              <span id="live-keyer-help" className="live-keyer-help" role="tooltip">Sends separate picture (fill) and transparency (key) signals through UltraStudio, so the switcher can overlay your slides on live video. Turn off for ordinary video output.</span>
            </label>
          </div>
        </>}
      </div>
      {keyer && outputSettings && <OutputEngine client={client} sessionLoaded={active} pollMs={enginePollMs} onEngine={setEngine} />}
      <p className="note">Hiding keeps playback running. Closing this presenter leaves the session running.</p>
    </details>
  </section>;
}
