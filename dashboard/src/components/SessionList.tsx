import { jobLabel } from "../sessions";
import type { Job } from "../api";
import { FEATURE_LABELS, asFeature } from "../nav";

type Props = {
  jobs: Job[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void;
};

export function SessionList({ jobs, activeId, onSelect, onDelete }: Props) {
  if (!jobs.length) return null;
  const groups = groupJobs(jobs);
  return (
    <div className="job-list">
      {groups.map(([feature, items]) => (
        <div key={feature} className="session-group">
            <div className="cap">{FEATURE_LABELS[feature as keyof typeof FEATURE_LABELS] || feature}</div>
          {items.map((job) => (
            <div key={job.id} className={`session-row ${job.id === activeId ? "active" : ""}`}>
              <button type="button" className="session-pick" onClick={() => onSelect(job.id)}>
                {jobLabel(job)}
                <div className="cap">
                  {job.status}
                  {job.artifacts && !job.artifacts.ok ? " · files missing" : ""}
                </div>
              </button>
              {onDelete && (
                <button
                  type="button"
                  className="session-del"
                  aria-label={`Delete ${jobLabel(job)}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(job.id);
                  }}
                >
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function groupJobs(jobs: Job[]): [string, Job[]][] {
  const order = ["generate", "diff", "visual", "check", "dsk", "resize"];
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
