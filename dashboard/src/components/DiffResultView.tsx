import { useState } from "react";
import { diffImageUrl, type Flag, type Job } from "../api";
import { ValidationPanel } from "./ValidationPanel";

type Pair = {
  index: number;
  number: number;
  leftText?: string;
  rightText?: string;
  leftMarkup?: string;
  rightMarkup?: string;
  leftPng?: string;
  rightPng?: string;
  heatPng?: string;
};

export type DiffResult = {
  leftPath?: string;
  rightPath?: string;
  leftLabel: string;
  rightLabel: string;
  leftPngs: string[];
  rightPngs: string[];
  heatPngs: string[];
  pairs: Pair[];
  flags: Flag[];
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

export function DiffResultView({ job, onOpen }: { job: Job; onOpen: (src: string) => void }) {
  const [slide, setSlide] = useState(0);
  const result = (job.result || null) as DiffResult | null;
  const pair = result?.pairs?.[slide];
  const previewsOk = present(job, "left previews") || present(job, "visual diff");

  function jump(location: string) {
    const m = /slide\s+(\d+)/i.exec(location);
    if (m) setSlide(Number(m[1]) - 1);
  }

  if (job.status === "error") return <p className="err">{job.error}</p>;
  if (!result || job.status !== "done") return null;

  return (
    <>
      {previewsOk && (
        <div className="thumbs-row">
          {result.pairs.map((p, i) => {
            const name = result.heatPngs[i] || result.leftPngs[i];
            const src = name ? diffImageUrl(job.id, result.heatPngs[i] ? "heat" : "left", name) : "";
            return src ? (
              <img
                key={p.number}
                className={i === slide ? "on" : ""}
                src={src}
                alt={`Slide ${p.number}`}
                onClick={() => setSlide(i)}
              />
            ) : (
              <button key={p.number} type="button" onClick={() => setSlide(i)}>
                {p.number}
              </button>
            );
          })}
        </div>
      )}
      {pair && (
        <div className="pair">
          <div>
            <div className="cap">
              {result.leftLabel} {pair.number}
            </div>
            {pair.leftPng && present(job, "left previews") && (
              <img
                src={diffImageUrl(job.id, "left", pair.leftPng)}
                alt=""
                onClick={() => onOpen(diffImageUrl(job.id, "left", pair.leftPng!))}
              />
            )}
            <pre className="log">{pair.leftMarkup || pair.leftText || "(no text)"}</pre>
          </div>
          <div>
            <div className="cap">
              {result.rightLabel} {pair.number}
            </div>
            {pair.rightPng && present(job, "right previews") && (
              <img
                src={diffImageUrl(job.id, "right", pair.rightPng)}
                alt=""
                onClick={() => onOpen(diffImageUrl(job.id, "right", pair.rightPng!))}
              />
            )}
            <pre className="log">{pair.rightMarkup || pair.rightText || "(no text)"}</pre>
          </div>
          <div>
            <div className="cap">Visual diff</div>
            {pair.heatPng && present(job, "visual diff") && (
              <img
                src={diffImageUrl(job.id, "heat", pair.heatPng)}
                alt=""
                onClick={() => onOpen(diffImageUrl(job.id, "heat", pair.heatPng!))}
              />
            )}
          </div>
        </div>
      )}
      <ValidationPanel flags={result.flags || []} onJump={jump} />
    </>
  );
}
