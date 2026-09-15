import { useState } from "react";
import { applyDsk, chooseFolder, chooseKeynote, evidenceUrl, pollJob, reveal, saveDskDecisions, startDsk, type ChosenFile, type DskProposal, type Job } from "../../api";
import { FileWell } from "../../components/FileWell";
import { ErrorNotice } from "../../components/ErrorNotice";
import { Lightbox, LoadingOverlay, PreviewGrid } from "../../components/PreviewGrid";
import { buildDecisionsMap, toDecisionsPayload, type DecisionsMap } from "../../dsk/decisions";
import { SlideReviewList } from "./SlideReviewList";

type ApplyResult = {
  deck?: string;
  assetsDir?: string;
  previews?: string[];
  skipped?: { slide: number; reason: string }[];
  warnings?: string[];
};

export function DskGenerator() {
  const [keynote, setKeynote] = useState<ChosenFile | null>(null);
  const [outDir, setOutDir] = useState<ChosenFile | null>(null);
  const [proposal, setProposal] = useState<DskProposal | null>(null);
  const [decisions, setDecisions] = useState<DecisionsMap>({});
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const applyResult = (job?.result || undefined) as ApplyResult | undefined;

  async function propose() {
    if (!keynote) {
      setError("Choose the finalised FW/LW Keynote first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const result = await startDsk(keynote.path);
      setProposal(result);
      setDecisions(buildDecisionsMap(result.slides));
      setJob(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveDecisions(next: DecisionsMap) {
    setDecisions(next);
    if (!proposal) return;
    try {
      await saveDskDecisions(proposal.id, toDecisionsPayload(next).slides);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run() {
    if (!proposal) return;
    setError(null);
    setBusy(true);
    try {
      await saveDskDecisions(proposal.id, toDecisionsPayload(decisions).slides);
      const created = await applyDsk(proposal.id, outDir?.path);
      setJob(created);
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
      if (done.status === "error") setError(done.error || "DSK generation failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const previewUrls = (applyResult?.previews || []).map((src) => ({ src }));

  return (
    <div>
      <p className="lede">
        Builds a DSK deck from the shipped content path: image and video slides only. Text /
        verse slides are skipped and listed below — that resizing is benched for now.
      </p>
      <div className="row">
        <FileWell
          label="Finalised FW / LW .key"
          hint="The source wall deck"
          file={keynote}
          onChoose={async () => {
            try {
              setKeynote(await chooseKeynote("Finalised FW or LW Keynote"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setKeynote({ path, name: path.split("/").pop() || path })}
          onError={setError}
        />
        <FileWell
          label="Output folder (optional)"
          hint="Defaults to output/<stem>/dsk"
          file={outDir}
          onChoose={async () => {
            try {
              setOutDir(await chooseFolder("Output folder for the DSK deck"));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
          onPath={(path) => setOutDir({ path, name: path.split("/").pop() || path })}
          onClear={() => setOutDir(null)}
          onError={setError}
        />
      </div>
      <div className="actions">
        <button className="btn" type="button" disabled={!keynote || busy} onClick={propose}>
          Propose
        </button>
      </div>
      {proposal && (
        <>
          <SlideReviewList
            proposalId={proposal.id}
            slides={proposal.slides}
            decisions={decisions}
            onChange={saveDecisions}
            onOpen={setOpen}
          />
          <div className="actions">
            <button className="btn" type="button" disabled={busy} onClick={run}>
              Run
            </button>
          </div>
        </>
      )}
      <ErrorNotice message={error} onDismiss={() => setError(null)} />
      {busy && <LoadingOverlay title="Building the DSK deck…" logs={logs} />}
      {applyResult?.deck && (
        <>
          <p className="note path-note">Wrote {applyResult.deck}</p>
          {applyResult.assetsDir && <p className="note path-note">Assets in {applyResult.assetsDir}</p>}
          <div className="actions">
            <button className="btn secondary" type="button" onClick={() => reveal(applyResult.deck!)}>
              Show in Finder
            </button>
          </div>
          {(applyResult.skipped || []).length > 0 && (
            <p className="note">
              Skipped: {applyResult.skipped!.map((s) => `${s.slide} (${s.reason})`).join(", ")}
            </p>
          )}
          {(applyResult.warnings || []).length > 0 && (
            <p className="note">{applyResult.warnings!.join(" · ")}</p>
          )}
          <PreviewGrid
            urls={job ? previewUrls.map((u) => ({ src: u.src.startsWith("/") || u.src.startsWith("http") ? u.src : evidenceUrl(job.id, u.src) })) : previewUrls}
            onOpen={setOpen}
          />
        </>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
