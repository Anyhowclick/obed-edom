import { useEffect, useMemo, useRef, useState } from "react";
import {
  applyHtmlPreview,
  cleanupHtmlPreview,
  htmlPreviewPlayerUrl,
  pollJob,
  startHtmlPreview,
  type HtmlPreviewResult,
  type HtmlPreviewSlide,
  type Job,
} from "../api";
import { ErrorNotice } from "./ErrorNotice";
import { LoadingOverlay } from "./PreviewGrid";

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function firstPlayable(slides: HtmlPreviewSlide[]): number | null {
  const live = slides.find((slide) => !slide.skipped);
  return live ? live.originalOrdinal : null;
}

function disposeFrame(frame: HTMLIFrameElement | null) {
  if (!frame) return;
  try {
    frame.src = "about:blank";
  } catch {
    /* ignore */
  }
}

export const PREVIEW_ISSUE_SOURCE = "obed-edom-preview";

function issueLabel(kind: string, detail: unknown): string {
  return `${kind}: ${String(detail ?? "").replace(/\s+/g, " ").trim()}`.trim();
}

export function playerDiagnosticsScript(): string {
  return `(function(){
  if (window.__obedPreviewDiagnostics) return;
  window.__obedPreviewDiagnostics = true;
  function send(kind, detail) {
    var label = kind + ": " + String(detail == null ? "" : detail).replace(/\\s+/g, " ").trim();
    if (label.length <= kind.length + 2) return;
    try { parent.postMessage({ source: "${PREVIEW_ISSUE_SOURCE}", label: label }, "*"); } catch (e) {}
  }
  window.addEventListener("error", function(event) {
    if (event.message) { send("error", event.message); return; }
    var el = event.target;
    if (el && el !== window && el !== document) {
      send("resource", el.currentSrc || el.src || el.href || el.nodeName || "failed");
    }
  }, true);
  window.addEventListener("unhandledrejection", function(event) {
    send("error", event.reason || "unhandledrejection");
  });
  var cons = console;
  var origError = cons.error.bind(cons);
  var origWarn = cons.warn.bind(cons);
  cons.error = function() { send("console", Array.prototype.join.call(arguments, " ")); origError.apply(cons, arguments); };
  cons.warn = function() { send("console", Array.prototype.join.call(arguments, " ")); origWarn.apply(cons, arguments); };
  if (typeof fetch === "function") {
    var origFetch = fetch.bind(window);
    window.fetch = function(input, init) {
      var url = (typeof input === "string" || (typeof URL !== "undefined" && input instanceof URL)) ? String(input) : input.url;
      return origFetch(input, init).then(function(res) {
        if (!res.ok) send("network", res.status + " " + url);
        return res;
      }, function(err) { send("network", "failed " + url); throw err; });
    };
  }
  if (typeof XMLHttpRequest !== "undefined") {
    var XO = XMLHttpRequest.prototype.open;
    var XS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
      this.__obedUrl = String(url);
      return XO.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
      var xhr = this;
      var url = xhr.__obedUrl || "";
      xhr.addEventListener("error", function() { send("network", "failed " + url); });
      xhr.addEventListener("load", function() { if (xhr.status >= 400) send("network", xhr.status + " " + url); });
      return XS.apply(xhr, arguments);
    };
  }
})();`;
}

export function injectPlayerDiagnostics(html: string): string {
  if (html.includes("data-obed-preview-diagnostics")) return html;
  const snippet = `<script data-obed-preview-diagnostics="1">${playerDiagnosticsScript()}</script>`;
  const head = html.match(/<head[^>]*>/i);
  if (head && head.index != null) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + snippet + html.slice(at);
  }
  const root = html.match(/<html[^>]*>/i);
  if (root && root.index != null) {
    const at = root.index + root[0].length;
    return html.slice(0, at) + snippet + html.slice(at);
  }
  return snippet + html;
}

type PlayerWindow = Window & {
  console: Console;
  fetch: typeof fetch;
  XMLHttpRequest: typeof XMLHttpRequest;
};

export function attachPlayerDiagnostics(win: PlayerWindow, onIssue: (label: string) => void): () => void {
  const record = (kind: string, detail: unknown) => {
    const label = issueLabel(kind, detail);
    if (label.length > kind.length + 2) onIssue(label);
  };

  const onError = (event: Event) => {
    const errorEvent = event as ErrorEvent;
    if (typeof errorEvent.message === "string" && errorEvent.message) {
      record("error", errorEvent.message);
      return;
    }
    const target = event.target;
    if (target && target !== win && target !== win.document) {
      const el = target as { src?: string; href?: string; currentSrc?: string; nodeName?: string };
      record("resource", el.currentSrc || el.src || el.href || el.nodeName || "failed");
    }
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    record("error", event.reason ?? "unhandledrejection");
  };

  win.addEventListener("error", onError, true);
  win.addEventListener("unhandledrejection", onRejection);

  const cons = win.console;
  const origError = cons.error.bind(cons);
  const origWarn = cons.warn.bind(cons);
  cons.error = (...args: unknown[]) => {
    record("console", args.map(String).join(" "));
    origError(...args);
  };
  cons.warn = (...args: unknown[]) => {
    record("console", args.map(String).join(" "));
    origWarn(...args);
  };

  const origFetch = win.fetch.bind(win);
  win.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
    try {
      const res = await origFetch(input, init);
      if (!res.ok) record("network", `${res.status} ${url}`);
      return res;
    } catch (err) {
      record("network", `failed ${url}`);
      throw err;
    }
  };

  const XHR = win.XMLHttpRequest;
  const origOpen = XHR.prototype.open;
  const origSend = XHR.prototype.send;
  type OpenedXHR = XMLHttpRequest & { __obedUrl?: string };
  XHR.prototype.open = function (this: XMLHttpRequest, method: string, url: string | URL, async?: boolean, username?: string | null, password?: string | null) {
    (this as OpenedXHR).__obedUrl = String(url);
    return origOpen.call(this, method, url, async ?? true, username, password);
  };
  XHR.prototype.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
    const url = (this as OpenedXHR).__obedUrl || "";
    this.addEventListener("error", () => record("network", `failed ${url}`));
    this.addEventListener("load", () => {
      if (this.status >= 400) record("network", `${this.status} ${url}`);
    });
    return origSend.call(this, body);
  };

  return () => {
    win.removeEventListener("error", onError, true);
    win.removeEventListener("unhandledrejection", onRejection);
    cons.error = origError;
    cons.warn = origWarn;
    win.fetch = origFetch;
    XHR.prototype.open = origOpen;
    XHR.prototype.send = origSend;
  };
}

export function BuildPreview({
  path,
  expectedDigest,
  disabled,
}: {
  path: string | null | undefined;
  expectedDigest?: string;
  disabled?: boolean;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [ordinal, setOrdinal] = useState<number | null>(null);
  const [issues, setIssues] = useState<string[]>([]);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const diagnosticsRef = useRef<(() => void) | null>(null);
  const pathRef = useRef(path);

  const result = (job?.result || undefined) as HtmlPreviewResult | undefined;
  const slides = result?.slides || [];
  const current = slides.find((slide) => slide.originalOrdinal === ordinal) || null;
  const aspect = useMemo(() => {
    const width = result?.canvas?.width || 1920;
    const height = result?.canvas?.height || 1080;
    return `${width} / ${height}`;
  }, [result?.canvas?.height, result?.canvas?.width]);

  useEffect(() => {
    if (pathRef.current === path) return;
    pathRef.current = path;
    diagnosticsRef.current?.();
    diagnosticsRef.current = null;
    disposeFrame(frameRef.current);
    setOpen(false);
    setJob(null);
    setOrdinal(null);
    setIssues([]);
    setError(null);
    setLogs([]);
  }, [path]);

  useEffect(() => {
    return () => {
      diagnosticsRef.current?.();
      diagnosticsRef.current = null;
      disposeFrame(frameRef.current);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { source?: string; label?: string } | null;
      const label = data?.label;
      if (data?.source !== PREVIEW_ISSUE_SOURCE || typeof label !== "string") return;
      setIssues((prev) => (prev.includes(label) ? prev : [...prev, label]));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open]);

  async function track(created: Job) {
    setJob(created);
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      setJob(tick);
    });
    setJob(done);
    if (done.status === "error") throw new Error(done.error || "Build preview failed.");
    return done;
  }

  async function prepare() {
    if (!path || busy || disabled) return;
    setError(null);
    setBusy(true);
    try {
      const proposed = await track(await startHtmlPreview(path, expectedDigest));
      const phase = (proposed.result as HtmlPreviewResult | undefined)?.phase;
      const ready = phase === "ready" ? proposed : await track(await applyHtmlPreview(proposed.id));
      const next = (ready.result || {}) as HtmlPreviewResult;
      if (next.phase !== "ready") throw new Error("Build preview is not ready.");
      setOpen(true);
      setOrdinal(firstPlayable(next.slides || []));
      setIssues([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  function closePreview() {
    diagnosticsRef.current?.();
    diagnosticsRef.current = null;
    disposeFrame(frameRef.current);
    setOpen(false);
    setIssues([]);
  }

  async function removeCache() {
    if (!job) {
      closePreview();
      return;
    }
    setError(null);
    setBusy(true);
    try {
      diagnosticsRef.current?.();
      diagnosticsRef.current = null;
      disposeFrame(frameRef.current);
      setJob(await cleanupHtmlPreview(job.id));
      setOpen(false);
      setIssues([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function jump(next: number) {
    const slide = slides.find((item) => item.originalOrdinal === next);
    if (!slide) return;
    setOrdinal(next);
    if (slide.skipped) {
      diagnosticsRef.current?.();
      diagnosticsRef.current = null;
      disposeFrame(frameRef.current);
    }
  }

  function onFrameLoad() {
    const frame = frameRef.current;
    const win = frame?.contentWindow;
    if (!win || !current || current.skipped || !current.playerHash) return;
    try {
      if (win.location.hash !== current.playerHash) {
        win.location.hash = current.playerHash;
      }
    } catch {
      /* cross-origin: hash was already on the src */
    }
  }

  const playerSrc =
    job && current && !current.skipped && current.playerHash
      ? htmlPreviewPlayerUrl(job.id, "index.html", current.playerHash)
      : null;
  const frameSrcRef = useRef<string | null>(null);
  if (playerSrc && !frameSrcRef.current) frameSrcRef.current = playerSrc;
  if (!open || !job) frameSrcRef.current = null;

  useEffect(() => {
    if (!current?.playerHash || current.skipped) return;
    const frame = frameRef.current;
    const win = frame?.contentWindow;
    if (!win) return;
    try {
      if (win.location.hash !== current.playerHash) win.location.hash = current.playerHash;
    } catch {
      if (playerSrc) frame.src = playerSrc;
    }
  }, [current?.playerHash, current?.skipped, playerSrc]);

  const canPrev = ordinal != null && slides.some((slide) => slide.originalOrdinal === ordinal - 1);
  const canNext = ordinal != null && slides.some((slide) => slide.originalOrdinal === ordinal + 1);

  return (
    <div className="build-preview">
      <div className="actions">
        <button className="btn secondary" type="button" disabled={!path || busy || disabled} onClick={prepare}>
          Preview builds
        </button>
        {open && (
          <button className="btn secondary" type="button" disabled={busy} onClick={closePreview}>
            Back to stills
          </button>
        )}
      </div>
      {busy && <LoadingOverlay title="Preparing build preview…" logs={logs} />}
      <ErrorNotice message={error} onDismiss={() => setError(null)} />
      {open && result?.phase === "ready" && (
        <div className="build-preview-pane">
          <div className="build-preview-nav">
            <button className="btn secondary" type="button" disabled={!canPrev} onClick={() => ordinal != null && jump(ordinal - 1)}>
              Previous slide
            </button>
            <label className="field">
              Slide
              <select
                value={ordinal ?? ""}
                onChange={(event) => jump(Number(event.target.value))}
              >
                {slides.map((slide) => (
                  <option key={slide.originalOrdinal} value={slide.originalOrdinal}>
                    {slide.originalOrdinal}
                    {slide.skipped ? " — skipped" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn secondary" type="button" disabled={!canNext} onClick={() => ordinal != null && jump(ordinal + 1)}>
              Next slide
            </button>
          </div>
          {current?.skipped ? (
            <p className="note" role="status">
              Slide {current.originalOrdinal} is skipped in the source deck, so the HTML export omitted it.
            </p>
          ) : playerSrc ? (
            <iframe
              key={job?.id}
              ref={frameRef}
              className="build-preview-frame"
              title={`Build preview, slide ${current?.originalOrdinal}`}
              src={frameSrcRef.current || playerSrc}
              sandbox="allow-scripts allow-same-origin"
              style={{ aspectRatio: aspect }}
              onLoad={onFrameLoad}
              onError={() => setIssues((prev) => (prev.includes("player failed to load") ? prev : [...prev, "player failed to load"]))}
            />
          ) : (
            <p className="note" role="status">
              No exported slides are available to preview.
            </p>
          )}
          <p className="note">
            Click the player or use the keyboard while it is focused to step builds. Reverse-build
            is not available.
            {typeof result.bytes === "number" ? ` Cached player is ${formatBytes(result.bytes)}.` : ""}
            {result.reused ? " Reused a cached export." : ""}
          </p>
          {(current?.unsupportedMedia || []).length > 0 && (
            <p className="note">
              This slide references unsupported web media ({current!.unsupportedMedia!.join(", ")}).
              Local player assets still play; remote media is not loaded.
            </p>
          )}
          {issues.length > 0 && <p className="note">Player issues: {issues.join(" · ")}</p>}
          <div className="actions">
            <button className="btn secondary" type="button" disabled={busy} onClick={removeCache}>
              Remove cached preview
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
