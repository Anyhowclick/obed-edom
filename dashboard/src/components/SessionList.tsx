import { jobLabel } from "../sessions";
import type { Job } from "../api";
import { FEATURE_LABELS, asFeature } from "../nav";
import { JobName } from "./JobName";
import { statusLabel } from "../statusLabel";

function IconTick() {
  return (
    <svg className="status-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconTrashSmall() {
  return (
    <svg className="status-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M7 7h10M9.5 7V6a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 6v1M8 7l.7 12.5h6.6L16 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

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
            <div className="cap">{FEATURE_LABELS[feature as keyof typeof FEATURE_LABELS] || feature}</div>
          {items.map((job) => {
            const { text, tone } = statusLabel(feature, job.status);
            return (
            <div key={job.id} className={`session-row ${job.id === activeId ? "active" : ""}`}>
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
                      {tone === "ok" && <IconTick />}
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
                  <IconTrashSmall />
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
