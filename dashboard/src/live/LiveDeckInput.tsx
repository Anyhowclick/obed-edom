import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { applyHtmlPreview, chooseKeynote, pollJob, startHtmlPreview, type ChosenFile, type HtmlPreviewResult, type Job } from "../api";
import { FileWell } from "../components/FileWell";
import { PrepareOutputDialog } from "../components/PrepareOutputDialog";

export type LiveDeckInputHandle = {
  preparePath(path: string): Promise<boolean>;
};

export const LiveDeckInput = forwardRef<LiveDeckInputHandle, {
  disabled: boolean;
  onPrepared: (jobId: string) => void;
  onPreparing: (preparing: boolean) => void;
}>(function LiveDeckInput({ disabled, onPrepared, onPreparing }, ref) {
  const [file, setFile] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [outputReady, setOutputReady] = useState(false);
  const [outputOpen, setOutputOpen] = useState(false);
  const mounted = useRef(false);
  const working = useRef(false);
  const progressRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; onPreparing(false); };
  }, [onPreparing]);

  useEffect(() => {
    if (busy) progressRef.current?.focus();
  }, [busy]);

  function intakeError(message: string) {
    setError(message);
    setOutputReady(false);
    setLogs([]);
  }

  function selectPath(value: string) {
    if (disabled || working.current) return;
    const next = value.trim().replace(/\/+$/, "");
    if (!next.toLowerCase().endsWith(".key")) { setFile(null); onPrepared(""); intakeError("Choose a Keynote (.key) file."); return; }
    setFile({ path: next, name: next.split("/").pop() || next });
    setError("");
    setProgress("");
    setLogs([]);
    setOutputReady(false);
    setOutputOpen(false);
    onPrepared("");
  }

  async function choose() {
    if (disabled || working.current) return;
    try {
      const chosen = await chooseKeynote("Choose a Keynote to present");
      if (mounted.current && chosen.path) selectPath(chosen.path);
    } catch (error) {
      if (mounted.current) intakeError(error instanceof Error ? error.message : String(error));
    }
  }

  async function track(job: Job) {
    setLogs(job.logs);
    const done = await pollJob(job.id, (tick) => {
      if (mounted.current) {
        setLogs(tick.logs);
        setProgress(tick.progress?.label || tick.logs[tick.logs.length - 1] || "Preparing Keynote…");
      }
    });
    if (mounted.current) setLogs(done.logs);
    if (done.status === "error") throw new Error(done.error || "Could not prepare this Keynote.");
    return done;
  }

  async function prepare(path: string): Promise<boolean> {
    if (!path || disabled || working.current) return false;
    working.current = true;
    setFile({ path, name: path.split("/").pop() || path });
    setBusy(true);
    setError("");
    setLogs([]);
    setOutputReady(false);
    setOutputOpen(false);
    setProgress("Preparing Keynote…");
    onPrepared("");
    onPreparing(true);
    try {
      let done = await track(await startHtmlPreview(path));
      if (!mounted.current) return false;
      if ((done.result as HtmlPreviewResult)?.phase !== "ready") done = await track(await applyHtmlPreview(done.id));
      if (!mounted.current) return false;
      if ((done.result as HtmlPreviewResult)?.phase !== "ready") throw new Error("The Keynote preview is not ready.");
      setProgress("Keynote prepared.");
      onPrepared(done.id);
      return true;
    } catch (error) {
      if (mounted.current) setError(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      working.current = false;
      if (mounted.current) { setBusy(false); setOutputReady(true); onPreparing(false); }
    }
  }

  useImperativeHandle(ref, () => ({
    preparePath: prepare,
  }));

  return <div className="live-deck-input">
    <fieldset disabled={disabled || busy}>
      <FileWell tone="lw" label="Keynote (.key)" hint="Drop from Finder or choose on this Mac" file={file} onChoose={() => void choose()} onPath={selectPath} onError={intakeError} />
      <button className="btn" type="button" disabled={!file} onClick={() => void prepare(file?.path || "")}>Qualify Keynote</button>
    </fieldset>
    {(busy || error || outputReady) && <div className="live-prepare-status">
      {error ? <p ref={progressRef} className="live-alert" role="alert" tabIndex={-1}>{error}</p> : <p ref={progressRef} className="live-prepare-progress" aria-live="polite" tabIndex={-1}>{progress}</p>}
      {outputReady && <button className="btn secondary live-view-output" type="button" onClick={() => setOutputOpen(true)}>View output</button>}
    </div>}
    {outputOpen && file && <PrepareOutputDialog title={`Prepare output — ${file.name}`} logs={logs} error={error} onExited={() => setOutputOpen(false)} />}
  </div>;
});
