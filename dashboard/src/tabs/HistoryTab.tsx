import { useEffect, useState } from "react";
import { chooseFolder, chooseKeynote, relocateJob } from "../api";
import { CheckResultView } from "../components/CheckResultView";
import { ErrorNotice } from "../components/ErrorNotice";
import { DiffResultView } from "../components/DiffResultView";
import { GenerateResultView } from "../components/GenerateResultView";
import { InspectResultView } from "../components/InspectResultView";
import { MapsResultView } from "../components/MapsResultView";
import { Lightbox } from "../components/PreviewGrid";
import { SessionList } from "../components/SessionList";
import { WatercolourResultView } from "../components/WatercolourResultView";
import { OPEN_IN_LABELS, asFeature, useRunNav } from "../nav";
import { useJobSessions } from "../sessions";

export function HistoryTab({ active: visible }: { active: boolean }) {
  const { jobs, active, activeId, setActiveId, upsert, remove, removeAll, reload, sessionError } = useJobSessions();
  const { openInFeature } = useRunNav();
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rawFeature = active?.feature || active?.kind || "";
  const feature = asFeature(rawFeature);
  const isLeftoverVisual = rawFeature === "visual";

  useEffect(() => {
    if (visible) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  async function relocate() {
    if (!active || !feature) return;
    setError(null);
    try {
      if (feature === "generate") {
        const folder = await chooseFolder("Folder with this run’s Keynotes and previews");
        upsert(await relocateJob(active.id, { folder: folder.path }));
        return;
      }
      if (feature === "dsk" || feature === "resize" || feature === "check") {
        const file = await chooseKeynote("Keynote this run should point at");
        upsert(await relocateJob(active.id, { path: file.path }));
        return;
      }
      if (feature === "maps") {
        const wall = await chooseKeynote("LED wall Map Keynote");
        const result = (active.result || {}) as {
          exportCg?: boolean;
          exportDsk?: boolean;
          destPathCg?: string;
          destPathDsk?: string;
        };
        const needCg = result.exportCg !== false || Boolean(result.destPathCg);
        const needDsk = result.exportDsk === true || Boolean(result.destPathDsk);
        const body: { destPath: string; destPathCg?: string; destPathDsk?: string } = { destPath: wall.path };
        if (needCg) {
          try {
            const cg = await chooseKeynote("CG Map Keynote");
            body.destPathCg = cg.path;
          } catch {}
        }
        if (needDsk) {
          try {
            const dsk = await chooseKeynote("DSK Map Keynote");
            body.destPathDsk = dsk.path;
          } catch {
            /* wall relocate still proceeds */
          }
        }
        upsert(await relocateJob(active.id, body));
        return;
      }
      const left = await chooseKeynote("Left / LW Keynote");
      const right = await chooseKeynote("Right Keynote");
      upsert(await relocateJob(active.id, { leftPath: left.path, rightPath: right.path }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function useSuggested() {
    if (!active?.artifacts?.suggestedPath) return;
    upsert(await relocateJob(active.id, { folder: active.artifacts.suggestedPath }));
  }

  return (
    <div>
      <div className="history-head">
        <h1>History</h1>
        {jobs.length > 0 && (
          <button className="btn delete-all" type="button" onClick={() => void removeAll()}>
            Delete All
          </button>
        )}
      </div>
      <p className="lede">
        Finished runs appear here. They are pointers to files under output/ — if you rename or delete those
        files in Finder, the catalog stays until you Relocate or Delete.
      </p>
      <ErrorNotice message={error || sessionError} onDismiss={error ? () => setError(null) : undefined} />
      {jobs.length === 0 ? (
        <p className="note">No saved runs yet. Generate, compare, or validate from the other tabs.</p>
      ) : (
        <div className="split library">
          <SessionList jobs={jobs} activeId={activeId} onSelect={setActiveId} onDelete={remove} />
          <div className="library-detail">
            {active && (
              <>
                {active.artifacts && !active.artifacts.ok && (
                  <ErrorNotice message={`Files missing: ${active.artifacts.missing.join(", ")}`} />
                )}
                {active.artifacts?.suggestedPath && (
                  <p className="note path-note">
                    Found a folder that matches this stem: {active.artifacts.suggestedPath}
                  </p>
                )}
                <div className="actions">
                  {feature && (
                    <button className="btn" type="button" onClick={() => openInFeature(feature, active.id)}>
                      {OPEN_IN_LABELS[feature]}
                    </button>
                  )}
                  {active.artifacts?.suggestedPath && feature !== "maps" && (
                    <button className="btn secondary" type="button" onClick={useSuggested}>
                      Use this folder
                    </button>
                  )}
                  {feature && feature !== "watercolour" && (
                    <button className="btn secondary" type="button" onClick={relocate}>
                      Relocate…
                    </button>
                  )}
                </div>
                {feature === "generate" && <GenerateResultView job={active} onOpen={setOpen} />}
                {feature === "diff" && <CheckResultView job={active} onOpen={setOpen} />}
                {isLeftoverVisual && <DiffResultView job={active} onOpen={setOpen} />}
                {feature === "check" && <CheckResultView job={active} onOpen={setOpen} />}
                {feature === "dsk" && <InspectResultView job={active} labelPrefix="LW" onOpen={setOpen} />}
                {feature === "resize" && <InspectResultView job={active} onOpen={setOpen} />}
                {feature === "maps" && <MapsResultView job={active} onOpen={setOpen} />}
                {feature === "watercolour" && <WatercolourResultView job={active} onOpen={setOpen} onError={setError} />}
              </>
            )}
          </div>
        </div>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
