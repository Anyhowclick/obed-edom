import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, stubResize, validateKeynote, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

function parseRange(raw: string): { from: number; to: number } | null {
  const m = raw.trim().match(/^(\d+)\s*[-–—]\s*(\d+)$/);
  if (!m) return null;
  const from = Number(m[1]);
  const to = Number(m[2]);
  if (from < 1 || to < from) return null;
  return { from, to };
}

export function ResizeTab() {
  const { job, upsert, error: openError } = useCurrentJob("resize");
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("5-12");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const result = (job?.result || undefined) as { path?: string } | undefined;

  useEffect(() => {
    const path = result?.path;
    if (path) setLw({ path, name: path.split("/").pop() || path });
  }, [job?.id, result?.path]);

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
        feature: "resize",
      });
      upsert(created);
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        upsert(tick);
      });
      upsert(done);
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

  return (
    <div>
      <h1>CG resizer</h1>
      <p className="lede">
        Read existing FW or LW content (7680 or 3840 × 1080) and resize a slide range into a new 1920×1080
        Keynote, preserving animations and map pins. Resize logic is not implemented yet; validation still runs.
        Finished checks are kept under Previous runs.
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
        onError={setError}
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
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title="Validating range…" logs={logs} />}
      {job && <InspectResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
