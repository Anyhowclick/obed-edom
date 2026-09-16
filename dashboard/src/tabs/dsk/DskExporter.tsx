import { useState } from "react";
import {
  applyDskExport,
  chooseKeynote,
  pollJob,
  reveal,
  startDskExport,
  type ChosenFile,
  type DskPage,
  type DskSkip,
  type Job,
} from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { BuildPreview } from "../../components/BuildPreview";
import { LoadingOverlay } from "../../components/PreviewGrid";
import { JobName } from "../../components/JobName";
import { renameAndApply } from "../../sessions";

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
  phase?: "review" | "done";
  path?: string;
  isStageDeck?: boolean;
  isFwDeck?: boolean;
  pages?: DskPage[];
  skipped?: DskSkip[];
  pngDir?: string;
  pngs?: string[];
  clips?: Record<string, string>;
  sequence?: string[];
  exportedClips?: number[];
};

export function DskExporter() {
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const result = (job?.result || undefined) as ExportResult | undefined;

  async function track(created: Job) {
    setJob(created);
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      setJob(tick);
    });
    setJob(done);
    if (done.status === "error") setError(done.error || "Export failed.");
    return done;
  }

  async function propose() {
    if (!keynote) {
      setError("Choose a DSK deck (1920×1080) to export from.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startDskExport(keynote.path, { slides: parseSlideSpec(range) });
      await track(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!job) return;
    setError(null);
    setBusy(true);
    try {
      const created = await applyDskExport(job.id);
      await track(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="lede">
        Renders a DSK deck (1920×1080) as one flat asset sequence in slide order. Image and built
        slides become stage PNGs (one per build step); movie and mixed slides become one .mov each,
        always re-rendered so the current live overlays are baked in. The Generator's pure-video
        intermediates under src/ are removed after a successful export.
      </p>
      <div className="row">
        <FileWell
          label="DSK .key"
          tone="dsk"
          hint="A 1920×1080 DSK deck"
          file={keynote}
          onChoose={async () => {
            try {
              setKeynote(await chooseKeynote("DSK Keynote to export from"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setKeynote({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
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
        <button className="btn" type="button" disabled={!keynote || busy} onClick={propose}>
          Propose
        </button>
      </div>
      {result?.phase === "review" && (
        <>
          {result.isFwDeck && !result.isStageDeck && (
            <p className="note">
              {keynote?.name} looks like an FW wall deck, not a 1920×1080 DSK deck — stage PNG
              export needs a DSK-sized deck.
            </p>
          )}
          <table className="dsk-review-table">
            <thead>
              <tr>
                <th>Slide</th>
                <th>Category</th>
                <th>Output</th>
              </tr>
            </thead>
            <tbody>
              {(result.pages || []).map((page) => (
                <tr key={page.slide}>
                  <td>{page.slide}</td>
                  <td>{page.category}</td>
                  <td>{page.needsClip ? "clip (.mov)" : "stage PNG(s)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(result.skipped || []).length > 0 && (
            <p className="note">
              skipped: {result.skipped!.map((s) => `${s.slide} (${s.reason})`).join(", ")}
            </p>
          )}
          <div className="actions">
            <button className="btn" type="button" disabled={busy || !result.isStageDeck} onClick={apply}>
              Export
            </button>
          </div>
          <BuildPreview path={result.path || keynote?.path} disabled={busy} />
        </>
      )}
      <ErrorNotice message={error} onDismiss={() => setError(null)} />
      {busy && <LoadingOverlay title="Exporting…" logs={logs} />}
      {result?.phase === "done" && result.pngDir && (
        <>
          <JobName job={job!} onRename={(id, name) => renameAndApply(id, name, setJob)} className="path-note" />
          <p className="note path-note">
            Wrote {result.pngDir} — {(result.pngs || []).length} PNG(s),{" "}
            {(result.exportedClips || []).length} clip(s)
          </p>
          {(result.sequence || []).length > 0 && (
            <ol className="mono-list">
              {result.sequence!.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ol>
          )}
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(result.pngDir!)}>
              Open folder
            </button>
          </div>
          <BuildPreview path={result.path || keynote?.path} disabled={busy} />
        </>
      )}
    </div>
  );
}
