import { useEffect, useState } from "react";
import {
  chooseKeynote,
  deleteJob,
  getTemplates,
  patchJob,
  pollJob,
  stubDsk,
  validateKeynote,
  type ChosenFile,
  type Flag,
} from "../api";
import { FileWell } from "../components/FileWell";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useCurrentJob } from "../sessions";

export function DskTab() {
  const { job, upsert, error: openError } = useCurrentJob("dsk");
  const [lw, setLw] = useState<ChosenFile | null>(null);
  const [dsk, setDsk] = useState<ChosenFile | null>(null);
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const result = (job?.result || undefined) as { path?: string } | undefined;

  useEffect(() => {
    getTemplates().then((t) => setTemplate(t.dskTemplate || t.dskTemplatePath));
  }, []);

  useEffect(() => {
    const path = result?.path;
    if (path) setLw({ path, name: path.split("/").pop() || path });
  }, [job?.id, result?.path]);

  async function inspectAll() {
    if (!lw) {
      setError("Choose a finalised LW.key first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const first = await validateKeynote(lw.path, { export: true, feature: "dsk" });
      upsert(first);
      let done = await pollJob(first.id, (tick) => {
        setLogs(tick.logs);
        upsert(tick);
      });
      upsert(done);
      if (dsk) {
        const second = await validateKeynote(dsk.path, { export: false, feature: "dsk-aux" });
        const dskDone = await pollJob(second.id, (tick) => setLogs((prev) => [...prev, ...tick.logs]));
        const a = (done.result || {}) as { flags?: Flag[] };
        const b = (dskDone.result || {}) as { flags?: Flag[] };
        const merged = {
          ...(done.result || {}),
          flags: [...(a.flags || []), ...(b.flags || [])],
        };
        done = await patchJob(done.id, merged);
        upsert(done);
        await deleteJob(second.id).catch(() => undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function generateStub() {
    setNotice(await stubDsk());
  }

  return (
    <div>
      <h1>DSK generator</h1>
      <p className="lede">
        Shadow content from a finalised LW into a DSK deck (from an existing DSK or the template masters).
        Generation logic is not implemented yet; validation still runs. Finished checks are kept under
        Previous runs.
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
          onError={setError}
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
          onError={setError}
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
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title="Validating Keynote…" logs={logs} />}
      {job && <InspectResultView job={job} labelPrefix="LW" onOpen={setOpen} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
