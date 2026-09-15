import { jobLabel } from "../sessions";
import type { Job } from "../api";
import { FEATURE_LABELS, asFeature } from "../nav";
import { JobName } from "./JobName";
import { statusLabel } from "../statusLabel";
import { IconTick, IconTrash } from "./icons";

type Props = {
  jobs: Job[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void;
  onRename?: (id: string, name: string) => Promise<Job>;
};

export function SessionList({ jobs, activeId, onSelect, onDelete, onRename }: Props) {
  if (!jobs.length) return null;
  const groups = groupJobs(jobs);
  return (
    <div className="job-list">
      {groups.map(([feature, items]) => (
        <div key={feature} className="session-group">
            <div className="cap" data-feature={feature}>{FEATURE_LABELS[feature as keyof typeof FEATURE_LABELS] || feature}</div>
          {items.map((job) => {
            const { text, tone } = statusLabel(feature, job.status);
            return (
            <div key={job.id} className={`session-row ${job.id === activeId ? "active" : ""}`} data-feature={feature}>
              <div className="session-pick-info">
                {onRename && <JobName job={job} onRename={onRename} onSelect={onSelect} />}
                <button
                  type="button"
                  className="session-pick"
                  aria-label={`Open ${jobLabel(job)}`}
                  onClick={() => onSelect(job.id)}
                >
                  {!onRename && jobLabel(job)}
                  <div className="cap">
                    <span className={`status-badge status-${tone}`}>
                      {tone === "ok" && <IconTick className="status-icon" />}
                      {text}
                    </span>
                  </div>
                  {job.artifacts && !job.artifacts.ok ? <div className="cap">files missing</div> : null}
                </button>
              </div>
              {onDelete && (
                <button
                  type="button"
                  className="session-del"
                  aria-label={`Delete ${jobLabel(job)}`}
                  title={`Delete ${jobLabel(job)}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(job.id);
                  }}
                >
                  <IconTrash className="status-icon" />
                </button>
              )}
            </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function groupJobs(jobs: Job[]): [string, Job[]][] {
  const order = ["generate", "diff", "check", "dsk", "resize", "maps", "watercolour"];
  const map = new Map<string, Job[]>();
  for (const job of jobs) {
    const feature = asFeature(job.feature || job.kind) || job.feature || job.kind;
    const list = map.get(feature) || [];
    list.push(job);
    map.set(feature, list);
  }
  const keys = [...order.filter((key) => map.has(key)), ...[...map.keys()].filter((key) => !order.includes(key))];
  return keys.map((key) => [key, map.get(key) || []]);
}
