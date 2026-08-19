import { useState } from "react";
import { generateDocx, pollJob } from "../api";
import { FileWell } from "../components/FileWell";
import { GenerateResultView } from "../components/GenerateResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

export function GeneratorTab() {
  const { job, upsert, error: openError } = useCurrentJob("generate");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(files: File[]) {
    const docx = files.filter((f) => f.name.toLowerCase().endsWith(".docx"));
    if (!docx.length) {
      setError("Drop one or more .docx outline files.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await generateDocx(docx);
      for (const createdJob of created) {
        upsert(createdJob);
        const done = await pollJob(createdJob.id, (tick) => {
          setLogs(tick.logs);
          upsert(tick);
        });
        upsert(done);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const running = job?.status === "queued" || job?.status === "running";

  return (
    <div>
      <h1>Sermon Base Generator</h1>
      <p className="lede">
        Drop sermon or offering outlines. Each file is generated in sequence (Keynote is single-instance)
        into LW and DSK decks plus preview PNGs. Finished runs are kept under Previous runs.
      </p>
      <FileWell
        label="Sermon outline (.docx)"
        hint="Drag and drop one or more Word outlines"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        multiple
        onFiles={run}
      />
      {(error || openError) && <p className="err">{error || openError}</p>}
      {(busy || running) && <LoadingOverlay title="Generating decks…" logs={logs} />}
      {job && <GenerateResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
