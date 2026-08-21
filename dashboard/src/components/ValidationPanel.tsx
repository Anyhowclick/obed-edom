import type { Flag } from "../api";
import { countInfo, FlagCard, sortFlags } from "./SlideFindings";

export type SlideTarget = { deck: "lw" | "dsk"; index: number };

export function parseSlideTarget(location?: string): SlideTarget | null {
  if (!location) return null;
  const tagged = /(?:^|\b)(LW|DSK)\s+slide\s+(\d+)/i.exec(location);
  if (tagged) {
    return { deck: tagged[1].toLowerCase() as "lw" | "dsk", index: Number(tagged[2]) };
  }
  const plain = /(?:^|\b)slide\s+(\d+)/i.exec(location);
  if (!plain) return null;
  return { deck: "lw", index: Number(plain[1]) };
}

export function ValidationPanel({
  flags,
  onJump,
  onOpen,
  jobId,
  showInfo,
  onShowInfo,
  title = "Validation",
}: {
  flags: Flag[];
  onJump?: (location: string) => void;
  onOpen?: (src: string) => void;
  jobId?: string;
  showInfo?: boolean;
  onShowInfo?: (next: boolean) => void;
  title?: string;
}) {
  const visible = (flags || []).filter((flag) => flag.severity !== "success");
  if (!visible.length) {
    return (
      <section className="flags">
        <h2>{title}</h2>
        <p className="note">No flags yet.</p>
      </section>
    );
  }
  const reveal = showInfo ?? false;
  const info = countInfo(visible);
  const shown = sortFlags(reveal ? visible : visible.filter((flag) => flag.severity !== "info"));
  return (
    <section className="flags">
      <h2>{title}</h2>
      <p className="note">
        {shown.length} finding{shown.length === 1 ? "" : "s"}
        {!reveal && info > 0 ? `, ${info} info hidden` : ""}. Files are not modified.
        {onShowInfo && (
          <button type="button" className="info-chip" onClick={() => onShowInfo(!reveal)}>
            {reveal ? "Hide info" : "Show info"}
          </button>
        )}
      </p>
      {shown.map((flag, i) => {
        const canJump = Boolean(onJump && parseSlideTarget(flag.location));
        return (
          <FlagCard
            key={`${flag.rule || flag.category}-${i}`}
            flag={flag}
            jobId={jobId}
            onOpen={onOpen}
            onJump={canJump ? onJump : undefined}
          />
        );
      })}
    </section>
  );
}
