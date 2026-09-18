import { useState } from "react";
import {
  applyDskExport,
  chooseFolder,
  chooseKeynote,
  pollJob,
  reveal,
  startDskExport,
  type ChosenFile,
  type DskSkip,
  type Job,
} from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { LoadingOverlay } from "../../components/PreviewGrid";
import { JobName } from "../../components/JobName";
import { DSK_WORKSPACE_KEY, useDefaultExportDir, useSessionPath } from "../../prefs";
import { renameAndApply } from "../../sessions";

function parentDir(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  return index > 0 ? trimmed.slice(0, index) : "";
}

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
  pngDir?: string;
  pngs?: string[];
  clips?: Record<string, string>;
  sequence?: string[];
  exportedClips?: number[];
  skipped?: DskSkip[];
};

export function DskExporter() {
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [workspace, setWorkspace] = useSessionPath(DSK_WORKSPACE_KEY);
  const defaultExportDir = useDefaultExportDir();

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

  async function exportDeck() {
    if (!keynote) {
      setError("Choose a DSK deck (1920×1080) to export from.");
      return;
    }
    setError(null);
    let chosen;
    try {
      chosen = await chooseFolder(
        "DSK workspace",
        parentDir(keynote.path) || workspace || defaultExportDir || undefined
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (/cancel/i.test(message)) return;
      setError(message);
      return;
    }
    setWorkspace(chosen.path);
    setBusy(true);
    try {
      const created = await startDskExport(keynote.path, {
        slides: parseSlideSpec(range),
        exportDir: chosen.path,
      });
      const proposed = await track(created);
      if (proposed.status === "error") return;
      const next = (proposed.result || {}) as ExportResult;
      if (next.phase === "done") return;
      if (!next.isStageDeck) {
        setError(
          next.isFwDeck
            ? `${keynote.name} looks like an FW wall deck, not a 1920×1080 DSK deck — stage PNG export needs a DSK-sized deck.`
            : `${keynote.name} is not a 1920×1080 DSK deck; stage PNG export needs a DSK-sized deck.`
        );
        return;
      }
      await track(await applyDskExport(proposed.id));
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
        <button className="btn" type="button" disabled={!keynote || busy} onClick={() => void exportDeck()}>
          Export
        </button>
      </div>
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
        </>
      )}
    </div>
  );
}
