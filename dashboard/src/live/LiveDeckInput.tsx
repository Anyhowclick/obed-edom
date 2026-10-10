import { useEffect, useRef, useState } from "react";
import { applyHtmlPreview, chooseKeynote, pollJob, startHtmlPreview, type ChosenFile, type HtmlPreviewResult, type Job } from "../api";
import { FileWell } from "../components/FileWell";

export function LiveDeckInput({ disabled, onPrepared, onPreparing }: {
  disabled: boolean;
  onPrepared: (jobId: string) => void;
  onPreparing: (preparing: boolean) => void;
}) {
  const [file, setFile] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const working = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; onPreparing(false); };
  }, [onPreparing]);

  function selectPath(value: string) {
    if (disabled || working.current) return;
    const next = value.trim().replace(/\/+$/, "");
    if (!next.toLowerCase().endsWith(".key")) { setFile(null); onPrepared(""); setError("Choose a Keynote (.key) file."); return; }
    setFile({ path: next, name: next.split("/").pop() || next });
    setError("");
    setProgress("");
    onPrepared("");
  }

  async function choose() {
    if (disabled || working.current) return;
    try {
      const chosen = await chooseKeynote("Choose a Keynote to present");
      if (mounted.current && chosen.path) selectPath(chosen.path);
    } catch (error) {
      if (mounted.current) setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function track(job: Job) {
    const done = await pollJob(job.id, (tick) => {
      if (mounted.current) setProgress(tick.progress?.label || tick.logs[tick.logs.length - 1] || "Preparing Keynote…");
    });
    if (done.status === "error") throw new Error(done.error || "Could not prepare this Keynote.");
    return done;
  }

  async function prepare() {
    if (!file || disabled || working.current) return;
    working.current = true;
    setBusy(true);
    setError("");
    setProgress("Preparing Keynote…");
    onPrepared("");
    onPreparing(true);
    try {
      let done = await track(await startHtmlPreview(file.path));
      if (!mounted.current) return;
      if ((done.result as HtmlPreviewResult)?.phase !== "ready") done = await track(await applyHtmlPreview(done.id));
      if (!mounted.current) return;
      if ((done.result as HtmlPreviewResult)?.phase !== "ready") throw new Error("The Keynote preview is not ready.");
      setProgress("");
      onPrepared(done.id);
    } catch (error) {
      if (mounted.current) setError(error instanceof Error ? error.message : String(error));
    } finally {
      working.current = false;
      if (mounted.current) { setBusy(false); onPreparing(false); }
    }
  }

  return <div className="live-deck-input">
    <fieldset disabled={disabled || busy}>
      <FileWell tone="lw" label="Keynote (.key)" hint="Drop from Finder or choose on this Mac" file={file} onChoose={() => void choose()} onPath={selectPath} onError={setError} />
      <button className="btn" type="button" disabled={!file} onClick={() => void prepare()}>Qualify Keynote</button>
    </fieldset>
    {busy && <p className="note" aria-live="polite">{progress}</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
