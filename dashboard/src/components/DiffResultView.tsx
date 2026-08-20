import { diffImageUrl, type Flag, type Job } from "../api";
import { ValidationPanel } from "./ValidationPanel";

type Pair = {
  index: number;
  number: number;
  leftNumber?: number | null;
  rightNumber?: number | null;
  leftSkipped?: boolean;
  rightSkipped?: boolean;
  leftText?: string;
  rightText?: string;
  leftMarkup?: string;
  rightMarkup?: string;
  leftPng?: string;
  rightPng?: string;
  heatPng?: string;
  missing?: string;
  sameType?: boolean;
  flags?: Flag[];
};

export type DiffResult = {
  leftPath?: string;
  rightPath?: string;
  leftLabel: string;
  rightLabel: string;
  sameType?: boolean;
  leftPngs: string[];
  rightPngs: string[];
  heatPngs: string[];
  pairs: Pair[];
  flags: Flag[];
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

function pickPng(named: string | undefined): string | undefined {
  // Server maps visible-order Keynote exports (left.001.png) onto slide
  // indices. Guessing by the Keynote slide number attaches the wrong PNG.
  return named;
}

function pairKey(pair: Pair): string {
  return `${pair.index}-${pair.leftNumber}-${pair.rightNumber}`;
}

function cap(label: string, number?: number | null, skipped?: boolean): string {
  if (number == null) return `No ${label}`;
  return skipped ? `${label} ${number} (skipped)` : `${label} ${number}`;
}

function SlideSlot({
  job,
  side,
  png,
  label,
  onOpen,
}: {
  job: Job;
  side: "left" | "right";
  png?: string;
  label: string;
  onOpen: (src: string) => void;
}) {
  const artifact = side === "left" ? "left previews" : "right previews";
  const src = png && present(job, artifact) ? diffImageUrl(job.id, side, png) : "";
  return (
    <div className="slide-slot">
      <div className="cap">{label}</div>
      {src ? (
        <img src={src} alt={label} onClick={() => onOpen(src)} />
      ) : (
        <div className="slide-ph">{label}</div>
      )}
    </div>
  );
}

export function DiffResultView({ job, onOpen }: { job: Job; onOpen: (src: string) => void }) {
  const result = (job.result || null) as DiffResult | null;

  if (job.status === "error") return <p className="err">{job.error}</p>;
  if (!result || job.status !== "done") return null;

  const deckFlags = (result.flags || []).filter((flag) => flag.category !== "diff");

  return (
    <>
      <div className="diff-stack">
        {result.pairs.map((pair) => {
          const issues = pair.flags || [];
          return (
            <article key={pairKey(pair)} className="diff-row" id={`pair-${pair.index}`}>
              <div className="pair-slides">
                <SlideSlot
                  job={job}
                  side="left"
                  png={pickPng(pair.leftPng)}
                  label={cap(result.leftLabel, pair.leftNumber, pair.leftSkipped)}
                  onOpen={onOpen}
                />
                <SlideSlot
                  job={job}
                  side="right"
                  png={pickPng(pair.rightPng)}
                  label={cap(result.rightLabel, pair.rightNumber, pair.rightSkipped)}
                  onOpen={onOpen}
                />
              </div>
              {issues.length > 0 && (
                <div className="pair-issues">
                  {issues.map((flag, i) => (
                    <div key={`${flag.category}-${i}`} className={`flag ${flag.severity}`}>
                      <div className="meta">{flag.severity}</div>
                      {flag.message}
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
      {deckFlags.length > 0 && <ValidationPanel flags={deckFlags} />}
    </>
  );
}
