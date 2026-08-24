import { useEffect, useState } from "react";
import {
  applyResize,
  chooseKeynote,
  pollJob,
  reveal,
  saveResizeFramings,
  startResize,
  type ChosenFile,
  type FramingDecision,
} from "../api";
import { FileWell } from "../components/FileWell";
import { FramingReview, type FramingProposal } from "../components/FramingReview";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

function parseSlideSpec(raw: string): number[] | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const out = new Set<number>();
  for (const chunk of trimmed.split(",")) {
    const token = chunk.trim();
    if (!token) continue;
    const single = token.match(/^(\d+)$/);
    if (single) {
      const n = Number(single[1]);
      if (n < 1) return null;
      out.add(n);
      continue;
    }
    const m = token.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
    if (!m) return null;
    const from = Number(m[1]);
    const to = Number(m[2]);
    if (from < 1 || to < from) return null;
    for (let n = from; n <= to; n++) out.add(n);
  }
  if (!out.size) return null;
  return [...out].sort((a, b) => a - b);
}

type ResizeResult = FramingProposal & {
  path?: string;
  templatePath?: string;
  destPath?: string;
  applied?: number;
  missed?: number;
  counts?: { map?: number; pin?: number; list?: number; total?: number };
  goldScore?: { pinPairs?: number; pinRmse?: number | null };
  templateScore?: { pinPairs?: number; pinRmse?: number | null };
  recipe?: { source?: string };
  fittedSlides?: number[];
  offFrame?: { slide: number; role?: string }[];
  placements?: { slide: number; overlap?: number }[];
  framingReport?: { slide: number; templateSlide: number | null; confirmed?: boolean; fitted?: boolean }[];
};

export function ResizeTab() {
  const { job, upsert, error: openError } = useCurrentJob("resize");
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [template, setTemplate] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
  const [includeLists, setIncludeLists] = useState(true);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const result = (job?.result || undefined) as ResizeResult | undefined;

  useEffect(() => {
    const path = result?.path;
    if (path) setLw({ path, name: path.split("/").pop() || path });
    // Restore the template too, or reopening a run leaves the button disabled and
    // the operator has to re-pick a file the run already knows about.
    const templatePath = result?.templatePath;
    if (templatePath) {
      setTemplate({ path: templatePath, name: templatePath.split("/").pop() || templatePath });
    }
  }, [job?.id, result?.path, result?.templatePath]);

  const parsedSlides = parseSlideSpec(range);
  const rangeError = range.trim() && !parsedSlides ? "Enter slides like 2 or 2, 4-6." : null;

  async function runResize() {
    if (!lw) {
      setError("Choose a finalised LW or FW .key.");
      return;
    }
    if (!template) {
      setError("Choose CG_Template.key (the 16:9 map layout).");
      return;
    }
    if (rangeError) {
      setError(rangeError);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startResize(lw.path, {
        templatePath: template.path,
        slides: parsedSlides ?? undefined,
        includeLists,
      });
      upsert(created);
      await track(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function track(created: { id: string }) {
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      upsert(tick);
    });
    upsert(done);
    if (done.status === "error") setError(done.error || "Resize failed.");
    return done;
  }

  async function saveFramings(decisions: FramingDecision[]) {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      upsert(await saveResizeFramings(job.id, decisions));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function applyFramings(decisions: FramingDecision[]) {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      await track(await applyResize(job.id, decisions));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const counts = result?.counts;
  const score = result?.templateScore || result?.goldScore;
  const awaitingFramings = result?.phase === "framing";
  const fitted = result?.fittedSlides || [];
  const offFrame = result?.offFrame || [];
  const overruled = (result?.framingReport || []).filter((r) => r.confirmed && r.fitted);

  return (
    <div>
      <h1>CG resizer</h1>
      <p className="lede">
        Turns a wall deck into 1920×1080 CGs. Your template deck shows where
        things should end up: put each object where you want it, at the size you
        want it, and add a slide for each map layout you use. Anything it hasn’t
        seen before is shrunk to fit and listed for you to check.
      </p>
      <div className="row">
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
        <FileWell
          label="CG_Template.key"
          hint="The 16:9 deck showing where things should end up"
          file={template}
          onChoose={async () => {
            try {
              setTemplate(await chooseKeynote("CG template Keynote"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setTemplate({ path, name: path.split("/").pop() || path })}
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
      <label className="check">
        <input
          type="checkbox"
          checked={includeLists}
          onChange={(e) => setIncludeLists(e.target.checked)}
        />
        <span>Include resizing church-name lists on side panels (Special Offering Series)</span>
      </label>
      <div className="actions">
        <button className="btn" type="button" disabled={!lw || !template || busy} onClick={runResize}>
          Propose framings
        </button>
      </div>
      {awaitingFramings && result && job && (
        <FramingReview
          proposal={result}
          jobId={job.id}
          busy={busy}
          onSave={saveFramings}
          onApply={applyFramings}
        />
      )}
      {result?.destPath && overruled.length > 0 && (
        <p className="note">
          Your confirmed framing could not be used on slide{overruled.length === 1 ? "" : "s"}{" "}
          {overruled.map((r) => r.slide).join(", ")} — that template slide cannot frame{" "}
          {overruled.length === 1 ? "it" : "them"}, so the content was fitted to the frame instead.
        </p>
      )}
      {result?.destPath && fitted.length > 0 && (
        <p className="note">
          No template framing matched {fitted.length} slide(s): {fitted.slice(0, 14).join(", ")}
          {fitted.length > 14 ? `, +${fitted.length - 14} more` : ""}. Their content was scaled to
          fit. Add a template slide for those layouts.
        </p>
      )}
      {result?.destPath && offFrame.length > 0 && (
        <p className="note">
          {offFrame.length} object(s) visible on the wall land outside the CG frame. They are still in
          the deck — drag them back or adjust the template.
        </p>
      )}
      {result?.destPath && (
        <>
          <p className="note path-note">
            Wrote {result.destPath}
            {counts ? ` — ${counts.pin ?? 0} pins, ${counts.map ?? 0} map, ${counts.list ?? 0} list` : ""}
            {typeof result.applied === "number" ? ` (applied ${result.applied}` : ""}
            {typeof result.missed === "number" ? `, missed ${result.missed})` : result.applied != null ? ")" : ""}
            {score?.pinRmse != null ? `. Template pin RMSE ${score.pinRmse}px` : ""}
            {result.recipe?.source ? `. Recipe: ${result.recipe.source}` : ""}
          </p>
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(result.destPath!)}>
              Show CG.key
            </button>
          </div>
        </>
      )}
      {(error || openError || rangeError) && <p className="err">{error || openError || rangeError}</p>}
      {busy && <LoadingOverlay title="Remapping map and pins…" logs={logs} />}
      {job && <InspectResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
