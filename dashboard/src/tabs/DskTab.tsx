import { useEffect, useState } from "react";
import {
  chooseKeynote,
  getTemplates,
  pollJob,
  previewUrl,
  stubDsk,
  validateKeynote,
  type ChosenFile,
  type Flag,
  type Job,
} from "../api";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay, PreviewGrid } from "../components/PreviewGrid";
import { ValidationPanel } from "../components/ValidationPanel";

export function DskTab() {
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [dsk, setDsk] = useState<ChosenFile | null>(null);
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    getTemplates().then((t) => setTemplate(t.dskTemplate || t.dskTemplatePath));
  }, []);

  async function inspectAll() {
    if (!lw) {
      setError("Choose a finalised LW.key first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const first = await validateKeynote(lw.path, { export: true });
      let done = await pollJob(first.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      if (dsk) {
        const second = await validateKeynote(dsk.path, { export: false });
        const dskDone = await pollJob(second.id, (tick) => setLogs((prev) => [...prev, ...tick.logs]));
        const a = (done.result || {}) as { flags?: Flag[] };
        const b = (dskDone.result || {}) as { flags?: Flag[] };
        done = {
          ...done,
          result: { ...done.result, flags: [...(a.flags || []), ...(b.flags || [])] },
        };
      }
      setJob(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function generateStub() {
    setNotice(await stubDsk());
  }

  const result = job?.result as
    | { flags?: Flag[]; previewFileNames?: string[]; previewFiles?: { lw: string[] } }
    | undefined;
  const names = result?.previewFileNames || result?.previewFiles?.lw || [];
  const urls =
    job && names.map((name: string, i: number) => ({ src: previewUrl(job.id, "lw", name), label: `LW ${i + 1}` }));

  return (
    <div>
      <h1>DSK generator</h1>
      <p className="lede">
        Shadow content from a finalised LW into a DSK deck (from an existing DSK or the template masters).
        Generation logic is not implemented yet; validation still runs.
      </p>
      <div className="row">
        <FileWell
          label="Finalised LW.key"
          hint="Required"
          file={lw}
          onChoose={async () => {
            try {
              setLw(await chooseKeynote("Finalised LW"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setLw({ path, name: path.split("/").pop() || path })}
        />
        <FileWell
          label="Optional DSK.key to modify"
          hint={template ? `Otherwise use template: ${template}` : "Or create from template"}
          file={dsk}
          onChoose={async () => {
            try {
              setDsk(await chooseKeynote("Existing DSK (optional)"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setDsk({ path, name: path.split("/").pop() || path })}
        />
      </div>
      <div className="actions">
        <button className="btn secondary" type="button" disabled={!lw || busy} onClick={inspectAll}>
          Run validation
        </button>
        <button className="btn" type="button" disabled={!lw} onClick={generateStub}>
          Generate DSK
        </button>
      </div>
      {notice && <p className="note">{notice}</p>}
      {error && <p className="err">{error}</p>}
      {busy && <LoadingOverlay title="Validating Keynote…" logs={logs} />}
      {urls && urls.length > 0 && <PreviewGrid urls={urls} onOpen={setOpen} />}
      <ValidationPanel flags={result?.flags || []} />
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
