import { useState } from "react";
import { chooseKeynote, generateDocx, pollJob, type ChosenFile } from "../api";
import { FileWell } from "../components/FileWell";
import { GenerateResultView } from "../components/GenerateResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import {
  DSK_TEMPLATE_KEY,
  LW_TEMPLATE_KEY,
  loadStoredFile,
  saveStoredFile,
} from "../prefs";
import { useCurrentJob } from "../sessions";

export function GeneratorTab() {
  const { job, upsert, error: openError } = useCurrentJob("generate");
  const [lwTemplate, setLwTemplate] = useState<ChosenFile | null>(() => loadStoredFile(LW_TEMPLATE_KEY));
  const [dskTemplate, setDskTemplate] = useState<ChosenFile | null>(() => loadStoredFile(DSK_TEMPLATE_KEY));
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function rememberLw(file: ChosenFile) {
    setLwTemplate(file);
    saveStoredFile(LW_TEMPLATE_KEY, file);
  }

  function rememberDsk(file: ChosenFile) {
    setDskTemplate(file);
    saveStoredFile(DSK_TEMPLATE_KEY, file);
  }

  async function pickTemplate(which: "lw" | "dsk") {
    try {
      const file = await chooseKeynote(which === "lw" ? "LW Keynote template" : "DSK Keynote template");
      if (which === "lw") rememberLw(file);
      else rememberDsk(file);
      setError(null);
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
          tone="keynote"
          file={lwTemplate}
          onChoose={() => pickTemplate("lw")}
          onPath={(path) => rememberLw({ path, name: path.split("/").pop() || path })}
          onClear={() => {
            setLwTemplate(null);
            saveStoredFile(LW_TEMPLATE_KEY, null);
          }}
          onError={setError}
        />
        <FileWell
          label="DSK template (.key)"
          hint="Optional. Drop the lower-thirds .key or choose on this Mac"
          tone="keynote"
          file={dskTemplate}
          onChoose={() => pickTemplate("dsk")}
          onPath={(path) => rememberDsk({ path, name: path.split("/").pop() || path })}
          onClear={() => {
            setDskTemplate(null);
            saveStoredFile(DSK_TEMPLATE_KEY, null);
          }}
          onError={setError}
        />
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {(busy || running) && <LoadingOverlay title="Generating decks…" logs={logs} />}
      {job && <GenerateResultView job={job} onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
