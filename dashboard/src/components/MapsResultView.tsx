import { previewUrl, reveal, type Job } from "../api";
import { JobName } from "./JobName";

export function MapsResultView({
  job,
  onOpen,
  onRename,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRename?: (id: string, name: string) => Promise<Job>;
}) {
  const result = (job.result || {}) as {
    destPath?: string;
    destPathCg?: string;
    destPathDsk?: string;
    previewFiles?: { maps?: string[] };
    slides?: { id: string; title: string; stillPng?: string }[];
  };
  const names = result.previewFiles?.maps || [];
  return (
    <div>
      {onRename && <JobName job={job} onRename={onRename} className="note" />}
      {result.destPath && (
        <p className="note path-note">
          LED wall: {result.destPath}{" "}
          <button className="btn secondary" type="button" onClick={() => void reveal(result.destPath!)}>
            Reveal
          </button>
        </p>
      )}
      {result.destPathCg && (
        <p className="note path-note">
          CG: {result.destPathCg}{" "}
          <button className="btn secondary" type="button" onClick={() => void reveal(result.destPathCg!)}>
            Reveal
          </button>
        </p>
      )}
      {result.destPathDsk && (
        <p className="note path-note">
          DSK: {result.destPathDsk}{" "}
          <button className="btn secondary" type="button" onClick={() => void reveal(result.destPathDsk!)}>
            Reveal
          </button>
        </p>
      )}
      <div className="thumbs">
        {names.map((name) => {
          const src = previewUrl(job.id, "maps", name);
          const slide = (result.slides || []).find((s) => s.stillPng === name);
          return (
            <button key={name} type="button" className="maps-thumb" onClick={() => onOpen(src)}>
              <img src={src} alt="" />
              <span className="maps-thumb-label">{slide?.title || name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
