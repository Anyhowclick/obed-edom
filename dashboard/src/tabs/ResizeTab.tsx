import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, startResize, validateKeynote, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

function parseRange(raw: string): { from: number; to: number } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
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
  recipe?: { source?: string };
};

export function ResizeTab() {
  const { job, upsert, error: openError } = useCurrentJob("resize");
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [gold, setGold] = useState<ChosenFile | null>(null);
  const [range, setRange] = useState("");
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
  const rangeError = range.trim() && !parsedRange ? "Slide range must look like 1-9, or leave blank for all slides." : null;

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
    if (rangeError) {
      setError(rangeError);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startResize(lw.path, {
        goldPath: gold?.path,
        rangeFrom: parsedRange?.from,
        rangeTo: parsedRange?.to,
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
  const score = result?.goldScore;

  return (
    <div>
      <h1>CG resizer</h1>
      <p className="lede">
        Copy a 7680×1080 wall deck and remap the map plus pin-drop movies into 1920×1080, keeping object
        identity so builds stay. Optional gold CG (same weekend) learns the crop; otherwise the map covers
        16:9 (center crop).
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
        label="Gold CG .key (optional)"
        hint="Same-weekend 1920×1080 map, if you have one"
        file={gold}
        onChoose={async () => {
          try {
            setGold(await chooseKeynote("Gold CG Keynote"));
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          }
        }}
        onPath={(path) => setGold({ path, name: path.split("/").pop() || path })}
        onError={setError}
      />
      <label className="field">
        Slide range (blank = all)
        <input type="text" value={range} onChange={(e) => setRange(e.target.value)} placeholder="1-9" />
      </label>
      <div className="actions">
        <button className="btn secondary" type="button" disabled={!lw || busy} onClick={runValidate}>
          Run validation
        </button>
        <button className="btn" type="button" disabled={!lw || busy} onClick={runResize}>
          Resize to 1920×1080
        </button>
      </div>
      {result?.destPath && (
        <p className="note">
          Wrote {result.destPath}
          {counts ? ` — ${counts.pin ?? 0} pins, ${counts.map ?? 0} map, ${counts.list ?? 0} list` : ""}
          {typeof result.applied === "number" ? ` (applied ${result.applied}` : ""}
          {typeof result.missed === "number" ? `, missed ${result.missed})` : result.applied != null ? ")" : ""}
          {score?.pinRmse != null ? `. Gold pin RMSE ${score.pinRmse}px` : ""}
          {result.recipe?.source ? `. Recipe: ${result.recipe.source}` : ""}
        </p>
      )}
      {(error || openError || rangeError) && <p className="err">{error || openError || rangeError}</p>}
      {busy && <LoadingOverlay title="Remapping map and pins…" logs={logs} />}
      {job && <InspectResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
