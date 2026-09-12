import { previewUrl, type Job } from "../api";
import { ArtifactActions } from "./ArtifactActions";
import { JobName } from "./JobName";

export function MapsResultView({
  job,
  onOpen,
  onRename,
  onError,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRename?: (id: string, name: string) => Promise<Job>;
  onError?: (message: string) => void;
}) {
  const result = (job.result || {}) as {
    destPath?: string;
    destPathCg?: string;
    destPathDsk?: string;
    previewFiles?: { maps?: string[] };
    slides?: { id: string; title: string; stillPng?: string }[];
  };
  const names = result.previewFiles?.maps || [];
  const artifacts = [
    result.destPath ? { label: "LED wall", path: result.destPath } : null,
    result.destPathCg ? { label: "CG", path: result.destPathCg } : null,
    result.destPathDsk ? { label: "DSK", path: result.destPathDsk } : null,
  ].filter((artifact): artifact is { label: string; path: string } => artifact != null);
  return (
    <div>
      {onRename && <JobName job={job} onRename={onRename} className="note" />}
      <ArtifactActions artifacts={artifacts} onError={onError} />
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
