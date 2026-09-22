import { useEffect, useRef, useState } from "react";
import {
  applyDsk,
  chooseFolder,
  chooseKeynote,
  FieldError,
  pollJob,
  reveal,
  saveDskDecisions,
  startDsk,
  type ChosenFile,
  type DskPage,
  type DskSkip,
  type JobProgress,
} from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { BuildPreview } from "../../components/BuildPreview";
import { LoadingOverlay, Lightbox, type OverlayProgress } from "../../components/PreviewGrid";
import { buildDecisionsMap, toDecisionsPayload, type DecisionsMap } from "../../dsk/decisions";
import { SlideReviewList } from "./SlideReviewList";
import { DskReviewWorkspace } from "./DskReviewWorkspace";
import { DskDecksCard } from "./DskDecksCard";
import { editableReview, editorState, isDskReview, type DskEditorState, type DskReview } from "../../dsk/decisions";
import { DSK_WORKSPACE_KEY, useDefaultExportDir, useSessionPath, useStoredTemplate } from "../../prefs";
import { useCurrentJob } from "../../sessions";
import { JobName } from "../../components/JobName";
import { IconTick, IconInfo, IconWarning } from "../../components/icons";

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
  review?: DskReview;
  schemaVersion?: number;
  revision?: number;
  compositions?: unknown[];
};

export function DskGenerator() {
  const { job, upsert, rename, error: openError } = useCurrentJob("dsk");
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [dskTemplate, setDskTemplate] = useStoredTemplate("dskTemplate");
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [referenceDeck, setReferenceDeck] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
  const [decisions, setDecisions] = useState<DecisionsMap>({});
  const [reviewState, setReviewState] = useState<DskEditorState | null>(null);
  const [busy, setBusy] = useState<false | "propose" | "run">(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [details, setDetails] = useState<string[]>([]);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [workspace, setWorkspace] = useSessionPath(DSK_WORKSPACE_KEY);
  const defaultExportDir = useDefaultExportDir();
  const latestReview = useRef<DskEditorState | null>(null);
  const reviewRevision = useRef(0);
  const initializedReviewJob = useRef<string | null>(null);
  const saveTimer = useRef<number | null>(null);
  const saveTail = useRef(Promise.resolve());

  const result = (job?.result || undefined) as DskResult | undefined;
  const pages = result?.pages || [];
  const skipped = result?.skipped || [];
  const review = isDskReview(result?.review) ? result.review : isDskReview(result) ? result : null;
  const overlayProgress: OverlayProgress | null = progress
    ? {
        label: `Step ${progress.step} of ${progress.steps} — ${progress.label}`,
        value: progress.step - 1,
        max: progress.steps,
        detail: progress.detail || undefined,
      }
    : null;

  useEffect(() => {
    const path = result?.path;
    if (path) setKeynote({ path, name: path.split("/").pop() || path });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, result?.path]);

  useEffect(() => {
    if (review && initializedReviewJob.current !== job?.id) {
      const next = editorState(review);
      latestReview.current = next;
      reviewRevision.current = review.revision;
      setReviewState(next);
      initializedReviewJob.current = job?.id || null;
    } else if (result?.phase === "review") setDecisions(buildDecisionsMap(pages));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, !!review]);

  useEffect(() => () => { if (saveTimer.current != null) window.clearTimeout(saveTimer.current); }, []);

  async function rememberDskTemplate(file: ChosenFile | null) {
    setTemplateError(null);
    try {
      await setDskTemplate(file);
    } catch (e) {
      setTemplateError(e instanceof Error ? e.message : String(e));
    }
  }

  async function track(created: { id: string }) {
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      setDetails(tick.details || []);
      setProgress(tick.progress ?? null);
      upsert(tick);
    });
    upsert(done);
    setDetails(done.details || []);
    setProgress(done.progress ?? null);
    if (done.status === "error") setError(done.error || "DSK job failed.");
    return done;
  }

  async function propose() {
    if (!keynote) {
      setError("Choose the finalised FW (7680×1080) Keynote first.");
      return;
    }
    setError(null);
    setBusy("propose");
    setDetails([]);
    setProgress(null);
    try {
      const created = await startDsk(keynote.path, {
        dskTemplate: dskTemplate?.path,
        referenceDeck: referenceDeck?.path,
        slides: parseSlideSpec(range),
      });
      upsert(created);
      await track(created);
    } catch (err) {
      if (err instanceof FieldError && err.field === "dskTemplate") {
        setTemplateError(err.message);
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
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

  function queueReviewSave(state: DskEditorState) {
    if (!job) return;
    const payload = editableReview(state);
    saveTail.current = saveTail.current.then(async () => {
      const saved = await saveDskDecisions(job.id, payload, reviewRevision.current);
      const savedResult = saved.result as DskResult | undefined;
      const nextRevision = savedResult?.revision;
      if (typeof nextRevision === "number") reviewRevision.current = nextRevision;
      upsert(saved);
    }).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }

  function changeReview(next: DskEditorState, persist = false) {
    latestReview.current = next;
    setReviewState(next);
    if (saveTimer.current != null) window.clearTimeout(saveTimer.current);
    if (persist) queueReviewSave(next);
    else saveTimer.current = window.setTimeout(() => queueReviewSave(latestReview.current || next), 350);
  }

  async function run() {
    if (!job) return;
    if (!dskTemplate) {
      setError("Choose the DSK template first.");
      return;
    }
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
    setBusy("run");
    setDetails([]);
    setProgress(null);
    try {
      if (reviewState && latestReview.current) {
        if (saveTimer.current != null) { window.clearTimeout(saveTimer.current); saveTimer.current = null; }
        await saveTail.current;
        const current = latestReview.current;
        const created = await applyDsk(job.id, editableReview(current), chosen.path, reviewRevision.current, dskTemplate?.path);
        upsert(created);
        await track(created);
        return;
      }
      await saveDskDecisions(job.id, toDecisionsPayload(decisions));
      const created = await applyDsk(job.id, toDecisionsPayload(decisions), chosen.path, undefined, dskTemplate?.path);
      upsert(created);
      await track(created);
    } catch (err) {
      if (err instanceof FieldError && err.field === "dskTemplate") {
        setTemplateError(err.message);
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
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
        <DskDecksCard
          dskTemplate={dskTemplate}
          templateError={templateError}
          onChooseTemplate={async () => {
            try {
              await rememberDskTemplate(await chooseKeynote("DSK Keynote template"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onTemplatePath={(path) => void rememberDskTemplate({ path, name: path.split("/").pop() || path })}
          onForgetTemplate={() => void rememberDskTemplate(null)}
          referenceDeck={referenceDeck}
          onChooseReference={async () => {
            try {
              setReferenceDeck(await chooseKeynote("Reference DSK deck for video-band measurement"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onReferencePath={(path) => setReferenceDeck({ path, name: path.split("/").pop() || path })}
          onClearReference={() => setReferenceDeck(null)}
          onDropError={setError}
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
        <button className="btn" type="button" disabled={!keynote || !dskTemplate || !!busy} onClick={propose}>
          Propose
        </button>
        {!dskTemplate && <span className="note">Choose the DSK template to continue.</span>}
      </div>
      {result?.phase === "review" && job && (
        <>
          {reviewState ? <DskReviewWorkspace jobId={job.id} state={reviewState} onChange={changeReview} /> : <SlideReviewList jobId={job.id} pages={pages} decisions={decisions} onChange={saveDecisions} onOpen={setOpen} />}
          {skipped.length > 0 && (
            <p className="note">Skipped: {skipped.map((s) => `${s.slide} (${s.reason})`).join(", ")}</p>
          )}
          <BuildPreview path={result.path} disabled={!!busy} />
          <div className="actions">
            <button className="btn" type="button" disabled={!!busy || !dskTemplate} onClick={run}>
              Run
            </button>
            {!dskTemplate && <span className="note">Choose the DSK template to continue.</span>}
          </div>
        </>
      )}
      <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
      {busy && (
        <LoadingOverlay
          title={busy === "propose" ? "Preparing the review…" : "Building the DSK deck…"}
          logs={logs}
          progress={overlayProgress}
          details={details}
          startedAt={job?.startedAt ?? undefined}
        />
      )}
      {result?.phase === "done" && result.deckPath && (
        <div className="dsk-result">
          <div className="dsk-result-header">
            <IconTick className="dsk-result-icon" />
            <div className="dsk-result-heading">
              <JobName job={job!} onRename={rename} />
              <p className="dsk-result-name">
                {result.deckPath.split("/").pop()}
                {result.slidesKept ? ` · ${result.slidesKept.length} slides` : ""}
              </p>
            </div>
          </div>
          <p className="path-note dsk-result-path">{result.deckPath}</p>
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(result.deckPath!)}>
              Show in Finder
            </button>
          </div>
          <BuildPreview path={result.deckPath} disabled={!!busy} />
          <p className="note">Next: open the Exporter tab to bake the live overlays into the final .mov(s).</p>
          {(skipped.length > 0 || (result.warnings || []).length > 0 || (result.overflows || []).length > 0) && (
            <div className="dsk-result-notes">
              <p className="dsk-result-notes-title">Notes</p>
              {skipped.map((s) => (
                <div className="flag info" key={`skip-${s.slide}`}>
                  <IconInfo className="status-icon" />
                  <span>
                    Skipped slide {s.slide} — {s.reason}
                  </span>
                </div>
              ))}
              {(result.warnings || []).map((warning, i) => (
                <div className="flag warning" key={`warning-${i}`}>
                  <IconWarning className="status-icon" />
                  <span>{warning}</span>
                </div>
              ))}
              {(result.overflows || []).map((slide) => (
                <div className="flag warning" key={`overflow-${slide}`}>
                  <IconWarning className="status-icon" />
                  <span>Overflow on slide {slide}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
