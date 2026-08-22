import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, reveal, startResize, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
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

type ResizeResult = {
  path?: string;
  destPath?: string;
  applied?: number;
  missed?: number;
  counts?: { map?: number; pin?: number; list?: number; total?: number };
  goldScore?: { pinPairs?: number; pinRmse?: number | null };
  templateScore?: { pinPairs?: number; pinRmse?: number | null };
  recipe?: { source?: string };
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
  }, [job?.id, result?.path]);

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
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        upsert(tick);
      });
      upsert(done);
      if (done.status === "error") {
        setError(done.error || "Resize failed.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const counts = result?.counts;
  const score = result?.templateScore || result?.goldScore;

  return (
    <div>
      <h1>CG resizer</h1>
      <p className="lede">
        Copies the wall deck, copies the CG template’s 16:9 slide layouts onto it
        (<code>MAP BLANK (16:9)</code> is the repurposed background), sets
        1920×1080, then moves the existing objects onto that layout. The template
        teaches the crop: every object in it should sit at its final CG size and
        position, and more anchors that agree makes the fit more reliable. Give
        it one slide per map framing you use — a page whose framing it has never
        seen is scaled to fit and reported instead.
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
          hint="Required 16:9 deck (Empty_Map.key). Its slide layouts are copied over; object positions teach the crop."
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
        <span>
          Bring the church-name lists across, resized to the template’s sample
          size and placed wherever the CG frame is still empty. Labels sitting on
          the map always come across and keep their place, whichever way this is
          set. Leave off to drop the side-panel name columns entirely.
        </span>
      </label>
      <div className="actions">
        <button className="btn" type="button" disabled={!lw || !template || busy} onClick={runResize}>
          Resize to 1920×1080
        </button>
      </div>
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
