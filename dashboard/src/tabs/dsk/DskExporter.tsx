import { useState } from "react";
import { chooseFolder, chooseKeynote, evidenceUrl, pollJob, reveal, startDskExport, type ChosenFile, type DskExportKind, type Job } from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { Lightbox, LoadingOverlay, PreviewGrid } from "../../components/PreviewGrid";

function parseSlideSpec(raw: string): number[] | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const out = new Set<number>();
  for (const chunk of trimmed.split(",")) {
    const token = chunk.trim();
    if (!token) continue;
    const single = token.match(/^(\d+)$/);
    if (single) {
      out.add(Number(single[1]));
      continue;
    }
    const m = token.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
    if (!m) continue;
    for (let n = Number(m[1]); n <= Number(m[2]); n++) out.add(n);
  }
  return out.size ? [...out].sort((a, b) => a - b) : undefined;
}

type ExportResult = {
  outDir?: string;
  manifest?: string;
  previews?: string[];
};

export function DskExporter() {
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [kind, setKind] = useState<DskExportKind>("stages");
  const [range, setRange] = useState("");
  const [outDir, setOutDir] = useState<ChosenFile | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const result = (job?.result || undefined) as ExportResult | undefined;

  async function run() {
    if (!keynote) {
      setError("Choose a DSK (or FW, for clips) Keynote first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startDskExport(keynote.path, kind, {
        slides: parseSlideSpec(range),
        outDir: outDir?.path,
      });
      setJob(created);
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
      if (done.status === "error") setError(done.error || "Export failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const previews = (result?.previews || []).map((src) => ({
    src: job && !(src.startsWith("/") || src.startsWith("http")) ? evidenceUrl(job.id, src) : src,
  }));

  return (
    <div>
      <p className="lede">
        Exports still images or clips from a DSK-shaped deck. Stage PNGs work on any 1920×1080
        DSK deck — hand-built ones included. Clip export only works on the FW deck (7680×1080
        or 3840×1080); this tool won&apos;t try it on anything else.
      </p>
      <div className="row">
        <FileWell
          label="DSK or FW .key"
          hint="Stage PNGs: any DSK deck. Clips: the FW deck"
          file={keynote}
          onChoose={async () => {
            try {
              setKeynote(await chooseKeynote("DSK or FW Keynote to export from"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setKeynote({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
        <FileWell
          label="Output folder (optional)"
          hint="Defaults to next to the deck"
          file={outDir}
          onChoose={async () => {
            try {
              setOutDir(await chooseFolder("Output folder for the export"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setOutDir({ path, name: path.split("/").pop() || path })}
          onClear={() => setOutDir(null)}
          onError={setError}
        />
      </div>
      <div className="seg">
        <button type="button" className={kind === "stages" ? "on" : ""} onClick={() => setKind("stages")}>
          Stage PNGs
        </button>
        <button type="button" className={kind === "clips" ? "on" : ""} onClick={() => setKind("clips")}>
          Clips (FW only)
        </button>
      </div>
      <label className="field">
        Slides — leave blank for the whole deck
        <input
          type="text"
          value={range}
          onChange={(e) => setRange(e.target.value)}
          placeholder="All slides (or 2, or 2, 4-6)"
        />
      </label>
      <div className="actions">
        <button className="btn" type="button" disabled={!keynote || busy} onClick={run}>
          Run
        </button>
      </div>
      <ErrorNotice message={error} onDismiss={() => setError(null)} />
      {busy && <LoadingOverlay title="Exporting…" logs={logs} />}
      {result?.outDir && (
        <>
          <p className="note path-note">Wrote {result.outDir}</p>
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(result.outDir!)}>
              Open folder
            </button>
          </div>
          <PreviewGrid urls={previews} onOpen={setOpen} />
        </>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
