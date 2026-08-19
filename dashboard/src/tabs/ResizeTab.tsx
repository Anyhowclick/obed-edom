import { useState } from "react";
import {
  chooseKeynote,
  pollJob,
  previewUrl,
  stubResize,
  validateKeynote,
  type ChosenFile,
  type Flag,
  type Job,
} from "../api";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay, PreviewGrid } from "../components/PreviewGrid";
import { ValidationPanel } from "../components/ValidationPanel";

function parseRange(raw: string): { from: number; to: number } | null {
  const m = raw.trim().match(/^(\d+)\s*[-–—]\s*(\d+)$/);
  if (!m) return null;
  const from = Number(m[1]);
  const to = Number(m[2]);
  if (from < 1 || to < from) return null;
  return { from, to };
}

export function ResizeTab() {
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("5-12");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function runValidate() {
    if (!lw) {
      setError("Choose a finalised LW or FW .key.");
      return;
    }
    const parsed = parseRange(range);
    if (!parsed) {
      setError("Slide range must look like 5-12.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await validateKeynote(lw.path, {
        export: true,
        rangeFrom: parsed.from,
        rangeTo: parsed.to,
      });
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function resizeStub() {
    if (!parseRange(range)) {
      setError("Slide range must look like 5-12.");
      return;
    }
    setNotice(await stubResize());
  }

  const result = job?.result as
    | { flags?: Flag[]; previewFileNames?: string[]; previewFiles?: { lw: string[] }; slideWidth?: number; slideHeight?: number }
    | undefined;
  const names = result?.previewFileNames || result?.previewFiles?.lw || [];
  const urls =
    job && names.map((name: string, i: number) => ({ src: previewUrl(job.id, "lw", name), label: `Slide ${i + 1}` }));

  return (
    <div>
      <h1>CG resizer</h1>
      <p className="lede">
        Read existing FW or LW content (7680 or 3840 × 1080) and resize a slide range into a new 1920×1080
        Keynote, preserving animations and map pins. Resize logic is not implemented yet; validation still runs.
      </p>
      <FileWell
        label="Finalised LW / FW .key"
        hint="Choose the source LED or full-wall deck"
        file={lw}
        onChoose={async () => {
          try {
            setLw(await chooseKeynote("LW or FW Keynote"));
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          }
        }}
        onPath={(path) => setLw({ path, name: path.split("/").pop() || path })}
      />
      <label className="field">
        Slide range
        <input type="text" value={range} onChange={(e) => setRange(e.target.value)} placeholder="5-12" />
      </label>
      <div className="actions">
        <button className="btn secondary" type="button" disabled={!lw || busy} onClick={runValidate}>
          Run validation
        </button>
        <button className="btn" type="button" disabled={!lw} onClick={resizeStub}>
          Resize to 1920×1080
        </button>
      </div>
      {notice && <p className="note">{notice}</p>}
      {error && <p className="err">{error}</p>}
      {busy && <LoadingOverlay title="Validating range…" logs={logs} />}
      {result?.slideWidth && (
        <p className="note">
          Source canvas {result.slideWidth}×{result.slideHeight}
        </p>
      )}
      {urls && urls.length > 0 && <PreviewGrid urls={urls} onOpen={setOpen} />}
      <ValidationPanel flags={result?.flags || []} />
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
