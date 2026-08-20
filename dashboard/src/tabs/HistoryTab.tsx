import { useEffect, useState } from "react";
import { chooseFolder, chooseKeynote, relocateJob } from "../api";
import { DiffResultView } from "../components/DiffResultView";
import { GenerateResultView } from "../components/GenerateResultView";
import { InspectResultView } from "../components/InspectResultView";
import { Lightbox } from "../components/PreviewGrid";
import { SessionList } from "../components/SessionList";
import { OPEN_IN_LABELS, asFeature, useRunNav } from "../nav";
import { useJobSessions } from "../sessions";

export function HistoryTab({ active: visible }: { active: boolean }) {
  const { jobs, active, activeId, setActiveId, upsert, remove, reload, sessionError } = useJobSessions();
  const { openInFeature } = useRunNav();
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const feature = asFeature(active?.feature || active?.kind || "");

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
      if (feature === "visual") {
        const left = await chooseFolder("LW preview folder");
        const right = await chooseFolder("DSK preview folder");
        upsert(await relocateJob(active.id, { leftPath: left.path, rightPath: right.path }));
        return;
      }
      if (feature === "dsk" || feature === "resize" || feature === "check") {
        const file = await chooseKeynote("Keynote this run should point at");
        upsert(await relocateJob(active.id, { path: file.path }));
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
      <h1>Previous runs</h1>
      <p className="lede">
        Finished runs appear here. They are pointers to files under output/ — if you rename or delete those
        files in Finder, the catalog stays until you Relocate or Delete.
      </p>
      {(error || sessionError) && <p className="err">{error || sessionError}</p>}
      {jobs.length === 0 ? (
        <p className="note">No saved runs yet. Generate, compare, or validate from the other tabs.</p>
      ) : (
        <div className="split library">
          <SessionList jobs={jobs} activeId={activeId} onSelect={setActiveId} onDelete={remove} />
          <div className="library-detail">
            {active && (
              <>
                {active.artifacts && !active.artifacts.ok && (
                  <p className="err">Files missing: {active.artifacts.missing.join(", ")}</p>
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
                  {active.artifacts?.suggestedPath && (
                    <button className="btn secondary" type="button" onClick={useSuggested}>
                      Use this folder
                    </button>
                  )}
                  <button className="btn secondary" type="button" onClick={relocate}>
                    Relocate…
                  </button>
                </div>
                {feature === "generate" && <GenerateResultView job={active} onOpen={setOpen} />}
                {feature === "diff" && <DiffResultView job={active} onOpen={setOpen} />}
                {feature === "visual" && <DiffResultView job={active} onOpen={setOpen} />}
                {feature === "check" && <InspectResultView job={active} onOpen={setOpen} />}
                {feature === "dsk" && <InspectResultView job={active} labelPrefix="LW" onOpen={setOpen} />}
                {feature === "resize" && <InspectResultView job={active} onOpen={setOpen} />}
              </>
            )}
          </div>
        </div>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
