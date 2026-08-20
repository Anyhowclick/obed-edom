import { useEffect, useState } from "react";
import { chooseKeynote, pollJob, validateKeynote, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

export function CheckTab() {
  const { job, upsert, error: openError } = useCurrentJob("check");
  const [file, setFile] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const result = (job?.result || undefined) as { path?: string } | undefined;

  useEffect(() => {
    const path = result?.path;
    if (path) setFile({ path, name: path.split("/").pop() || path });
  }, [job?.id, result?.path]);

  async function pick() {
    try {
      setFile(await chooseKeynote("Keynote to check"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run() {
    if (!file) {
      setError("Choose a Keynote file.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await validateKeynote(file.path, { export: true, feature: "check" });
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
      <h1>Sermon Checker</h1>
      <p className="lede">
        Drop one LW or DSK Keynote. House-style checks run read-only (Bible wording, contrast, overflow, and the
        rest). Finished checks are kept under Previous runs.
      </p>
      <FileWell
        label="Keynote (.key)"
        hint="Drop from Finder or choose on this Mac"
        file={file}
        onChoose={pick}
        onPath={(path) => setFile({ path, name: path.split("/").pop() || path })}
        onError={setError}
      />
      <div className="actions">
        <button className="btn" type="button" disabled={!file || busy} onClick={run}>
          Check (read-only)
        </button>
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title="Checking Keynote…" logs={logs} />}
      {job && <InspectResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
