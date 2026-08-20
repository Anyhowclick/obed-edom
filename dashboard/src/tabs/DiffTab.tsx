import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, startDiff, startDiffCheck, type ChosenFile } from "../api";
import { DiffResultView } from "../components/DiffResultView";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";
import { useLayout } from "../nav";
import type { Slot } from "../playlist";

export function DiffTab() {
  const { job, upsert, error: openError } = useCurrentJob("diff");
  const { focusMode } = useLayout();
  const [left, setLeft] = useState<ChosenFile | null>(null);
  const [right, setRight] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const data = (job?.result || {}) as { leftPath?: string; rightPath?: string };
    if (data.leftPath) setLeft({ path: data.leftPath, name: data.leftPath.split("/").pop() || data.leftPath });
    if (data.rightPath) setRight({ path: data.rightPath, name: data.rightPath.split("/").pop() || data.rightPath });
  }, [job?.id]);

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
      const created = await startDiff(left.path, right.path, "LW", /dsk/i.test(right.name) ? "DSK" : "Other");
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

  async function runChecks(slots: Slot[]) {
    if (!job) return;
    setError(null);
    setBusy(true);
    try {
      const started = await startDiffCheck(job.id, slots);
      upsert(started);
      const done = await pollJob(job.id, (tick) => {
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

  const overlayTitle =
    job?.status === "running" && (job.result as { phase?: string } | null)?.phase === "match"
      ? "Checking pairs…"
      : "Matching Keynotes…";

  return (
    <div className={focusMode ? "diff-tab focus" : "diff-tab"}>
      <div className="diff-setup">
      <h1>Diff Checker</h1>
      <p className="lede">
        Match a pastor-finalised LW.key against a DSK first, fix the playlist if needed, then run wording and
        photo checks. Read-only: nothing is saved back to those files. Finished compares are kept under Previous
        runs.
      </p>
      <div className="row">
        <FileWell
          label="Final LW.key"
          hint="Drop from Finder or choose on this Mac"
          file={left}
          onChoose={() => pick("left")}
          onPath={(path) => setLeft({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
        <FileWell
          label="DSK or other .key"
          hint="Drop from Finder or choose on this Mac"
          file={right}
          onChoose={() => pick("right")}
          onPath={(path) => setRight({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
      </div>
      <div className="actions">
        <button className="btn" type="button" disabled={!left || !right || busy} onClick={run}>
          Match pairs
        </button>
      </div>
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title={overlayTitle} logs={logs} />}
      {job && <DiffResultView job={job} onOpen={setOpen} onRunChecks={runChecks} checking={busy} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
