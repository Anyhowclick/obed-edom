import { useEffect, useState } from "react";
import {
  applyDsk,
  chooseFolder,
  chooseKeynote,
  pollJob,
  reveal,
  saveDskDecisions,
  startDsk,
  type ChosenFile,
  type DskPage,
  type DskSkip,
} from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { LoadingOverlay, Lightbox } from "../../components/PreviewGrid";
import { buildDecisionsMap, toDecisionsPayload, type DecisionsMap } from "../../dsk/decisions";
import { SlideReviewList } from "./SlideReviewList";
import { DSK_WORKSPACE_KEY, useDefaultExportDir, useSessionPath } from "../../prefs";
import { useCurrentJob } from "../../sessions";
import { JobName } from "../../components/JobName";

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

type DskResult = {
  phase?: "review" | "done";
  path?: string;
  pages?: DskPage[];
  skipped?: DskSkip[];
  deckPath?: string;
  exportDir?: string;
  slidesKept?: number[];
  warnings?: string[];
  overflows?: string[];
  clips?: Record<string, string[]>;
  ordinals?: Record<string, number>;
};

export function DskGenerator() {
  const { job, upsert, rename, error: openError } = useCurrentJob("dsk");
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [referenceDeck, setReferenceDeck] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
  const [decisions, setDecisions] = useState<DecisionsMap>({});
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [workspace, setWorkspace] = useSessionPath(DSK_WORKSPACE_KEY);
  const defaultExportDir = useDefaultExportDir();

  const result = (job?.result || undefined) as DskResult | undefined;
  const pages = result?.pages || [];
  const skipped = result?.skipped || [];

  useEffect(() => {
    const path = result?.path;
    if (path) setKeynote({ path, name: path.split("/").pop() || path });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, result?.path]);

  useEffect(() => {
    if (result?.phase === "review") setDecisions(buildDecisionsMap(pages));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  async function track(created: { id: string }) {
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      upsert(tick);
    });
    upsert(done);
    if (done.status === "error") setError(done.error || "DSK job failed.");
    return done;
  }

  async function propose() {
    if (!keynote) {
      setError("Choose the finalised FW (7680×1080) Keynote first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startDsk(keynote.path, {
        referenceDeck: referenceDeck?.path,
        slides: parseSlideSpec(range),
      });
      upsert(created);
      await track(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveDecisions(next: DecisionsMap) {
    setDecisions(next);
    if (!job) return;
    try {
      upsert(await saveDskDecisions(job.id, toDecisionsPayload(next)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run() {
    if (!job) return;
    setError(null);
    let chosen;
    try {
      chosen = await chooseFolder("DSK workspace", workspace || defaultExportDir || undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (/cancel/i.test(message)) return;
      setError(message);
      return;
    }
    setWorkspace(chosen.path);
    setBusy(true);
    try {
      await saveDskDecisions(job.id, toDecisionsPayload(decisions));
      const created = await applyDsk(job.id, toDecisionsPayload(decisions), chosen.path);
      upsert(created);
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
        Builds a DSK deck from the shipped content path: image and video slides only. Text /
        verse slides are skipped and listed below — that resizing is benched for now.
      </p>
      <div className="row">
        <FileWell
          label="Finalised FW .key"
          tone="lw"
          hint="The source 7680×1080 wall deck"
          file={keynote}
          onChoose={async () => {
            try {
              setKeynote(await chooseKeynote("Finalised FW Keynote"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setKeynote({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
        <FileWell
          label="Reference deck (optional)"
          tone="dsk"
          hint="Layout import source; leave blank for the built-in DSK layouts"
          file={referenceDeck}
          onChoose={async () => {
            try {
              setReferenceDeck(await chooseKeynote("Reference Keynote for layout import"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setReferenceDeck({ path, name: path.split("/").pop() || path })}
          onClear={() => setReferenceDeck(null)}
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
      {result?.phase === "review" && job && (
        <>
          <SlideReviewList
            jobId={job.id}
            pages={pages}
            decisions={decisions}
            onChange={saveDecisions}
            onOpen={setOpen}
          />
          {skipped.length > 0 && (
            <p className="note">Skipped: {skipped.map((s) => `${s.slide} (${s.reason})`).join(", ")}</p>
          )}
          <div className="actions">
            <button className="btn" type="button" disabled={busy} onClick={run}>
              Run
            </button>
          </div>
        </>
      )}
      <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
      {busy && <LoadingOverlay title="Building the DSK deck…" logs={logs} />}
      {result?.phase === "done" && result.deckPath && (
        <>
          <JobName job={job!} onRename={rename} className="path-note" />
          <p className="note path-note">
            Wrote {result.deckPath}
            {result.slidesKept ? ` — ${result.slidesKept.length} slide(s)` : ""}
          </p>
          <p className="note">
            The deck is editable — each movie item became a pure-video clip inserted behind the
            live objects. Export it with the Exporter tab to bake the live overlays and produce
            the final .mov(s).
          </p>
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(result.deckPath!)}>
              Show in Finder
            </button>
          </div>
          {skipped.length > 0 && (
            <p className="note">Skipped: {skipped.map((s) => `${s.slide} (${s.reason})`).join(", ")}</p>
          )}
          {(result.warnings || []).length > 0 && <p className="note">{result.warnings!.join(" · ")}</p>}
          {(result.overflows || []).length > 0 && (
            <p className="note">Overflow on slide(s): {result.overflows!.join(", ")}</p>
          )}
        </>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
