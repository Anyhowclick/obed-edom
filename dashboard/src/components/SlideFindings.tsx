import { useState } from "react";
import { evidenceUrl, type Flag } from "../api";

const SEVERITY_ORDER: Record<string, number> = { error: 0, warning: 1, info: 2, success: 3 };

export function sortFlags(flags: Flag[]): Flag[] {
  return [...flags].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9));
}

export function countInfo(flags: Flag[]): number {
  return flags.filter((flag) => flag.severity === "info").length;
}

export function flagTitle(flag: Flag): string {
  if (flag.title) return flag.title;
  const raw = flag.rule || flag.category || "";
  return raw
    .replace(/[._]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function FlagCard({
  flag,
  jobId,
  onJump,
  onOpen,
}: {
  flag: Flag;
  jobId?: string;
  onJump?: (location: string) => void;
  onOpen?: (src: string) => void;
}) {
  const heading = [flagTitle(flag), flag.location].filter(Boolean).join(" · ");
  const canJump = Boolean(onJump && flag.location);
  const evidence = jobId && flag.evidence ? evidenceUrl(jobId, flag.evidence) : "";
  return (
    <div className={`flag ${flag.severity}`}>
      {canJump ? (
        <button type="button" className="meta jump" onClick={() => onJump!(flag.location!)}>
          {heading}
        </button>
      ) : (
        <div className="meta">{heading}</div>
      )}
      {flag.message ? <div className="flag-body">{flag.message}</div> : null}
      {evidence && (
        <img
          className="flag-evidence"
          src={evidence}
          alt="The object this finding refers to"
          onClick={() => onOpen?.(evidence)}
        />
      )}
    </div>
  );
}

/**
 * Findings for one slide or pair. Info findings are the running commentary an
 * operator only wants when they go looking, so they stay behind a chip.
 */
export function SlideFindings({
  flags,
  jobId,
  showInfo,
  onJump,
  onOpen,
  className = "pair-issues",
}: {
  flags: Flag[];
  jobId?: string;
  showInfo: boolean;
  onJump?: (location: string) => void;
  onOpen?: (src: string) => void;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const real = (flags || []).filter((flag) => flag.severity !== "success");
  if (!real.length) return null;
  const info = countInfo(real);
  const reveal = showInfo || expanded;
  const shown = sortFlags(reveal ? real : real.filter((flag) => flag.severity !== "info"));
  if (!shown.length && !info) return null;
  return (
    <div className={className}>
      {shown.map((flag, i) => (
        <FlagCard key={`${flag.rule || flag.category}-${i}`} flag={flag} jobId={jobId} onJump={onJump} onOpen={onOpen} />
      ))}
      {info > 0 && !showInfo && (
        <button
          type="button"
          className="info-chip"
          onClick={(event) => {
            event.stopPropagation();
            setExpanded(!expanded);
          }}
        >
          {expanded ? `Hide ${info} info finding${info === 1 ? "" : "s"}` : `${info} info finding${info === 1 ? "" : "s"} hidden`}
        </button>
      )}
    </div>
  );
}
