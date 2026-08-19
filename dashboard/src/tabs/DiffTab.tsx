import { useState } from "react";
import {
  chooseKeynote,
  diffImageUrl,
  pollJob,
  startDiff,
  type ChosenFile,
  type Flag,
  type Job,
} from "../api";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { ValidationPanel } from "../components/ValidationPanel";

type Pair = {
  index: number;
  number: number;
  leftText?: string;
  rightText?: string;
  leftMarkup?: string;
  rightMarkup?: string;
  leftPng?: string;
  rightPng?: string;
  heatPng?: string;
  missing?: string;
};

type DiffResult = {
  leftLabel: string;
  rightLabel: string;
  leftPngs: string[];
  rightPngs: string[];
  heatPngs: string[];
  pairs: Pair[];
  flags: Flag[];
};

export function DiffTab() {
  const [left, setLeft] = useState<ChosenFile | null>(null);
  const [right, setRight] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slide, setSlide] = useState(0);
  const [open, setOpen] = useState<string | null>(null);

  async function pick(which: "left" | "right") {
    try {
      const file = await chooseKeynote(which === "left" ? "Final LW Keynote" : "Keynote to compare");
      if (which === "left") setLeft(file);
      else setRight(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run() {
    if (!left || !right) {
      setError("Choose both Keynote files.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await startDiff(left.path, right.path, "LW", "Other");
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
      setSlide(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const result = (job?.result || null) as DiffResult | null;
  const pair = result?.pairs?.[slide];

  function jump(location: string) {
    const m = /slide\s+(\d+)/i.exec(location);
    if (m) setSlide(Number(m[1]) - 1);
  }

  return (
    <div>
      <h1>Diff Checker</h1>
      <p className="lede">
        Compare a pastor-finalised LW.key against a DSK (or any other Keynote). Read-only: nothing is saved
        back to those files. Flags highlight text, highlight-range, and visual (circle/blur) differences.
      </p>
      <div className="row">
        <FileWell
          label="Final LW.key"
          hint="Choose the approved LED wall deck"
          file={left}
          onChoose={() => pick("left")}
          onPath={(path) => setLeft({ path, name: path.split("/").pop() || path })}
        />
        <FileWell
          label="DSK or other .key"
          hint="Choose the deck to check against LW"
          file={right}
          onChoose={() => pick("right")}
          onPath={(path) => setRight({ path, name: path.split("/").pop() || path })}
        />
      </div>
      <div className="actions">
        <button className="btn" type="button" disabled={!left || !right || busy} onClick={run}>
          Compare (read-only)
        </button>
      </div>
      {error && <p className="err">{error}</p>}
      {busy && <LoadingOverlay title="Inspecting Keynotes…" logs={logs} />}

      {result && job?.status === "done" && (
        <>
          <div className="thumbs-row">
            {result.pairs.map((p, i) => {
              const name = result.heatPngs[i] || result.leftPngs[i];
              const src = name
                ? diffImageUrl(job.id, result.heatPngs[i] ? "heat" : "left", name)
                : "";
              return src ? (
                <img
                  key={p.number}
                  className={i === slide ? "on" : ""}
                  src={src}
                  alt={`Slide ${p.number}`}
                  onClick={() => setSlide(i)}
                />
              ) : (
                <button key={p.number} type="button" onClick={() => setSlide(i)}>
                  {p.number}
                </button>
              );
            })}
          </div>
          {pair && (
            <div className="pair">
              <div>
                <div className="cap">{result.leftLabel} {pair.number}</div>
                {pair.leftPng && (
                  <img
                    src={diffImageUrl(job.id, "left", pair.leftPng)}
                    alt=""
                    onClick={() => setOpen(diffImageUrl(job.id, "left", pair.leftPng!))}
                  />
                )}
                <pre className="log">{pair.leftMarkup || pair.leftText || "(no text)"}</pre>
              </div>
              <div>
                <div className="cap">{result.rightLabel} {pair.number}</div>
                {pair.rightPng && (
                  <img
                    src={diffImageUrl(job.id, "right", pair.rightPng)}
                    alt=""
                    onClick={() => setOpen(diffImageUrl(job.id, "right", pair.rightPng!))}
                  />
                )}
                <pre className="log">{pair.rightMarkup || pair.rightText || "(no text)"}</pre>
              </div>
              <div>
                <div className="cap">Visual diff</div>
                {pair.heatPng && (
                  <img
                    src={diffImageUrl(job.id, "heat", pair.heatPng)}
                    alt=""
                    onClick={() => setOpen(diffImageUrl(job.id, "heat", pair.heatPng!))}
                  />
                )}
              </div>
            </div>
          )}
          <ValidationPanel flags={result.flags || []} onJump={jump} />
        </>
      )}
      {job?.status === "error" && <p className="err">{job.error}</p>}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
