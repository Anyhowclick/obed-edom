import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, reveal, startResize, validateKeynote, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

function parseRange(raw: string): { from: number; to: number } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const single = trimmed.match(/^(\d+)$/);
  if (single) {
    const n = Number(single[1]);
    if (n < 1) return null;
    return { from: n, to: n };
  }
  const m = trimmed.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
  if (!m) return null;
  const from = Number(m[1]);
  const to = Number(m[2]);
  if (from < 1 || to < from) return null;
  return { from, to };
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
  const [range, setRange] = useState("2");
  const [includeLists, setIncludeLists] = useState(false);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const result = (job?.result || undefined) as ResizeResult | undefined;

  useEffect(() => {
    const path = result?.path;
    if (path) setLw({ path, name: path.split("/").pop() || path });
  }, [job?.id, result?.path]);

  const parsedRange = parseRange(range);
  const rangeError = range.trim() && !parsedRange ? "Enter a slide number (2) or a range (1-9)." : null;

  async function runValidate() {
    if (!lw) {
      setError("Choose a finalised LW or FW .key.");
      return;
    }
    if (rangeError) {
      setError(rangeError);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await validateKeynote(lw.path, {
        export: true,
        rangeFrom: parsedRange?.from,
        rangeTo: parsedRange?.to,
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
        rangeFrom: parsedRange?.from,
        rangeTo: parsedRange?.to,
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
        MVP: copy the wall deck, copy the CG template’s 16:9 slide layouts
        onto it (MAP BLANK (16:9) is the repurposed background), set 1920×1080,
        then move existing objects onto that layout. Objects that share a
        scale+translation (the map cluster) move together; pins follow the
        group they sit on. Use Empty_Map.key (full map layers), not
        Only_Map.key.
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
      <label className="field">
        Slide (number or range)
        <input type="text" value={range} onChange={(e) => setRange(e.target.value)} placeholder="2" />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={includeLists}
          onChange={(e) => setIncludeLists(e.target.checked)}
        />
        <span>Also remap church-name text with the same map crop (leave off for a map-only slide)</span>
      </label>
      <div className="actions">
        <button className="btn secondary" type="button" disabled={!lw || busy} onClick={runValidate}>
          Run validation
        </button>
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
