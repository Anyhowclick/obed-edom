import { useEffect, useState } from "react";
import { chooseFolder, pollJob, saveVisualSlots, startVisual, startVisualCheck, type ChosenFile } from "../api";
import { DiffResultView } from "../components/DiffResultView";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useLayout } from "../nav";
import { useCurrentJob } from "../sessions";
import type { Slot } from "../playlist";

export function VisualTab() {
  const { job, upsert, error: openError } = useCurrentJob("visual");
  const { focusMode } = useLayout();
  const [left, setLeft] = useState<ChosenFile | null>(null);
  const [right, setRight] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState<"open" | "check">("open");
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
      const folder = await chooseFolder(which === "left" ? "LW preview folder" : "DSK preview folder");
      if (which === "left") setLeft(folder);
      else setRight(folder);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run(fresh = false) {
    if (!left || !right) {
      setError("Choose both preview folders.");
      return;
    }
    setError(null);
    setBusyKind("open");
    setBusy(true);
    try {
      const created = await startVisual(left.path, right.path, fresh);
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

  async function saveSlots(slots: Slot[]) {
    if (!job) return;
    setError(null);
    try {
      upsert(await saveVisualSlots(job.id, slots));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runChecks(slots: Slot[]) {
    if (!job) return;
    setError(null);
    setBusyKind("check");
    setBusy(true);
    try {
      const started = await startVisualCheck(job.id, slots);
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

  return (
    <div className={focusMode ? "diff-tab focus" : "diff-tab"}>
      <div className="diff-setup">
        <h1>Visual Checker</h1>
        <p className="lede">
          Drop exported LW and DSK preview folders for a side-by-side look (PNG, JPEG, or MOV). Pair them,
          then run wording and photo checks from the stills — Keynote metadata is not read. Finished views
          are kept under History.
        </p>
        <div className="row">
          <FileWell
            folder
            label="LW preview folder"
            hint="Drop the folder of LW PNG, JPEG, or MOV files or choose on this Mac"
            file={left}
            onChoose={() => pick("left")}
            onPath={(path) => setLeft({ path, name: path.split("/").pop() || path })}
            onError={setError}
          />
          <FileWell
            folder
            label="DSK preview folder"
            hint="Drop the folder of DSK PNG, JPEG, or MOV files or choose on this Mac"
            file={right}
            onChoose={() => pick("right")}
            onPath={(path) => setRight({ path, name: path.split("/").pop() || path })}
            onError={setError}
          />
        </div>
        <div className="actions">
          <button className="btn" type="button" disabled={!left || !right || busy} onClick={() => run()}>
            Open previews
          </button>
        </div>
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && (
        <LoadingOverlay
          title={busyKind === "check" ? "Checking pairs…" : "Loading preview folders…"}
          logs={logs}
        />
      )}
      {job && (
        <DiffResultView
          job={job}
          onOpen={setOpen}
          onRunChecks={runChecks}
          onSaveSlots={saveSlots}
          onStartFresh={() => run(true)}
          checking={busy}
        />
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
