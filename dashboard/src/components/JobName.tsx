import { useRef, useState } from "react";
import type { Job } from "../api";
import { jobLabel } from "../sessions";
import { IconPencil } from "./icons";

function previewNormalise(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

type Props = {
  job: Job;
  onRename: (id: string, name: string) => Promise<Job>;
  onSelect?: (id: string) => void;
  className?: string;
};

export function JobName({ job, onRename, onSelect, className }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  const label = jobLabel(job);
  const locked = job.status === "queued" || job.status === "running";

  function startEditing(event: React.MouseEvent) {
    event.stopPropagation();
    if (locked || saving) return;
    setDraft(job.name || label);
    setError(null);
    setEditing(true);
  }

  function cancel(event?: React.SyntheticEvent) {
    event?.stopPropagation();
    setEditing(false);
    setError(null);
  }

  async function commit(event?: React.SyntheticEvent) {
    event?.stopPropagation();
    if (savingRef.current) return;
    const next = previewNormalise(draft);
    if (!next || next === (job.name || "").toLowerCase()) {
      setEditing(false);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      await onRename(job.id, next);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span className={`job-name ${className || ""}`}>
        <span
          className="job-name-text"
          onClick={() => onSelect?.(job.id)}
        >
          {label}
        </span>
        {!locked && (
          <button
            type="button"
            className="job-name-edit"
            aria-label={`Rename ${label}`}
            onClick={startEditing}
          >
            <IconPencil />
          </button>
        )}
      </span>
    );
  }

  return (
    <span className={`job-name job-name-editing ${className || ""}`} onClick={(event) => event.stopPropagation()}>
      <input
        autoFocus
        type="text"
        className="job-name-input"
        value={draft}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit(event);
          if (event.key === "Escape") cancel(event);
        }}
        onBlur={commit}
      />
      <span className="job-name-preview">{previewNormalise(draft) || "…"}</span>
      {error && <span className="job-name-error">{error}</span>}
    </span>
  );
}
