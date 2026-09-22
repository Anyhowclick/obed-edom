import { useState } from "react";
import { chooseKeynote, generateDocx, pollJob, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { ErrorNotice } from "../components/ErrorNotice";
import { GenerateResultView } from "../components/GenerateResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useStoredTemplate } from "../prefs";
import { useCurrentJob } from "../sessions";

export function GeneratorTab() {
  const { job, upsert, rename, error: openError } = useCurrentJob("generate");
  const [lwTemplate, setLwTemplate] = useStoredTemplate("lwTemplate");
  const [dskTemplate, setDskTemplate] = useStoredTemplate("dskTemplate");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remember(which: "lw" | "dsk", file: ChosenFile | null) {
    try {
      await (which === "lw" ? setLwTemplate(file) : setDskTemplate(file));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function pickTemplate(which: "lw" | "dsk") {
    try {
      await remember(which, await chooseKeynote(which === "lw" ? "LW Keynote template" : "DSK Keynote template"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run(files: File[]) {
    const docx = files.filter((f) => f.name.toLowerCase().endsWith(".docx"));
    if (!docx.length) {
      setError("Drop one or more .docx outline files.");
      return;
    }
    if (!lwTemplate && !dskTemplate) {
      setError("Drop or choose at least one Keynote template (LW, DSK, or both).");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await generateDocx(docx, {
        lwTemplate: lwTemplate?.path,
        dskTemplate: dskTemplate?.path,
      });
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
        Drop a sermon or offering outline, then at least one Keynote template (LW, DSK, or both —
        remembered on this Mac). Only decks with a template are generated. Each outline runs in sequence
        (Keynote is single-instance). Finished runs are kept under History.
      </p>
      <div className="row">
        <FileWell
          label="Sermon outline (.docx)"
          hint="Drag and drop one or more Word outlines"
          tone="document"
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          multiple
          onFiles={run}
        />
        <FileWell
          label="LW template (.key)"
          hint="Optional. Drop Sermon_GW.key or choose on this Mac"
          tone="lw"
          file={lwTemplate}
          onChoose={() => pickTemplate("lw")}
          onPath={(path) => void remember("lw", { path, name: path.split("/").pop() || path })}
          onClear={() => void remember("lw", null)}
          onError={setError}
        />
        <FileWell
          label="DSK template (.key)"
          hint="Optional. Drop the lower-thirds .key or choose on this Mac"
          tone="dsk"
          file={dskTemplate}
          onChoose={() => pickTemplate("dsk")}
          onPath={(path) => void remember("dsk", { path, name: path.split("/").pop() || path })}
          onClear={() => void remember("dsk", null)}
          onError={setError}
        />
      </div>
      <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
      {(busy || running) && <LoadingOverlay title="Generating decks…" logs={logs} />}
      {job && (
        <GenerateResultView
          job={job}
          onOpen={setOpen}
          onRename={rename}
          onError={setError}
        />
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
