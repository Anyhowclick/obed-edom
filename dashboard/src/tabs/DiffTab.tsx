import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, startDiff, type ChosenFile } from "../api";
import { DiffResultView } from "../components/DiffResultView";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

export function DiffTab() {
  const { job, upsert, error: openError } = useCurrentJob("diff");
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
      const created = await startDiff(left.path, right.path, "LW", "Other");
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

  return (
    <div>
      <h1>Diff Checker</h1>
      <p className="lede">
        Compare a pastor-finalised LW.key against a DSK (or any other Keynote). Read-only: nothing is saved
        back to those files. Finished compares are kept under Previous runs.
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
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title="Inspecting Keynotes…" logs={logs} />}
      {job && <DiffResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
