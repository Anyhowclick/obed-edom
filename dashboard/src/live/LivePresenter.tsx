import { useCallback, useEffect, useRef, useState } from "react";
import { liveClient, type LiveClient, type LiveDisplay, type LiveOperation, type LivePreparedDeck, type LiveSlide, type LiveSnapshot } from "./api";
import "./live.css";

function Still({ slide, label }: { slide?: LiveSlide; label: string }) {
  return <figure className="live-still">
    <figcaption>{label}{slide ? ` · Slide ${slide.originalOrdinal}` : ""} · Still preview</figcaption>
    {slide?.thumbnailUrl ? <img src={slide.thumbnailUrl} alt={`Slide ${slide.originalOrdinal} still`} /> : <div className="live-placeholder">{slide ? "Still unavailable" : "No slide"}</div>}
  </figure>;
}

export function LivePresenter({ client = liveClient, previewJobId = "", pollMs = 1000 }: { client?: LiveClient; previewJobId?: string; pollMs?: number }) {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const observed = useRef<LiveSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
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
  const [upcomingCount, setUpcomingCount] = useState(3);

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
    if (awaitingObservation && snapshot && (snapshot.status === "ready" || snapshot.status === "error" || snapshot.status === "stopped")) {
      setAwaitingObservation(false);
    }
  }, [awaitingObservation, snapshot]);

  const disabledReason = useCallback((operation: LiveOperation): string => {
    if (!connected) return "Waiting for connection to output host";
    if (!snapshot || snapshot.status === "stopped") return "No active session";
    if (pending) return "Waiting for command acknowledgment";
    if (operation === "stop") return "";
    if ((operation === "advance" || operation === "goTo") && snapshot.status !== "ready") return `Player is ${snapshot.status}`;
    if ((operation === "hide" || operation === "show") && snapshot.status !== "ready" && snapshot.status !== "busy") return `Player is ${snapshot.status}`;
    const capability = snapshot.capabilities?.[operation] || { supported: false, reason: "Not available in this player state" };
    return capability.supported ? "" : capability.reason || "Not supported by this player";
  }, [connected, snapshot, pending]);

  const send = useCallback(async (operation: LiveOperation, slide?: number) => {
    const current = observed.current;
    if (!current || inFlight.current || disabledReason(operation)) return;
    inFlight.current = true;
    setPending(true);
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
      inFlight.current = false;
      if (mounted.current) setPending(false);
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
    if (inFlight.current || !connected || !jobId.trim()) return;
    inFlight.current = true;
    setPending(true);
    const epoch = ++generation.current;
    setMessage("");
    try {
      const next = await client.start(jobId, displayId || undefined);
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
  const active = snapshot && snapshot.status !== "stopped";
  return <section className="live-presenter" aria-label="Live presenter">
    <h1>Alpha Keynote</h1>
    <p className="lede">Experimental silent HDMI output. The picture is 16:9 within the detected display. DeckLink fill + key is not qualified.</p>
    <p className="note">Native HTML playback only; alpha and movie continuity are not qualified.</p>
    <p role="status">{connected ? snapshot ? `Player ${snapshot.status} · Output ${snapshot.outputVisible ? "visible" : "hidden"}` : "No active session" : connectionError ? "Disconnected · Reconnecting…" : "Connecting…"}</p>
    {connectionError && <p role="alert">{connectionError}. Existing output may still be running; commands are disabled until reconnected.</p>}
    {(message || awaitingObservation || snapshot?.error) && <p role="alert">{message || (awaitingObservation ? "Command accepted; waiting for observed player state." : snapshot?.error)}</p>}
    {!active && <form className="actions" onSubmit={(event) => { event.preventDefault(); void start(); }}>
      <label>Prepared deck
        <select aria-label="Prepared deck" value={jobId} onChange={(event) => setJobId(event.target.value)} disabled={!decks.length}>
          {decks.length ? decks.map((deck) => <option key={deck.previewJobId} value={deck.previewJobId}>{deck.name} · {deck.slides} slides</option>) : <option value="">No prepared decks available</option>}
        </select>
      </label>
      <label>Output display
        <select aria-label="Output display" value={displayId} onChange={(event) => setDisplayId(event.target.value)} disabled={!displays.length}>
          {displays.length ? displays.map((display) => <option key={display.id} value={display.id}>{display.name} · {display.width} × {display.height}{display.primary ? " · Primary" : ""}</option>) : <option value="">No display detected</option>}
        </select>
      </label>
      {!decks.length && <p className="note">Prepare a deck in Sermon Checker with Build Preview first. Live output never creates a new export.</p>}
      <button className="btn" disabled={!connected || pending || !jobId || !displays.length}>Start output session</button>
    </form>}
    {snapshot && <>
      <p className="note">Slide {snapshot.originalSlide ?? "unknown"} · Build {snapshot.buildIndex ?? "unknown"} · Display {snapshot.output.width} × {snapshot.output.height} · Audio off</p>
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
