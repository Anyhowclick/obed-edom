import { useMemo, useState } from "react";
import { previewUrl, reveal, type Flag, type Job } from "../api";
import { PreviewGrid } from "./PreviewGrid";
import { parseSlideTarget, ValidationPanel } from "./ValidationPanel";

const LW_PREVIEW_COLS = 2;
const DSK_PREVIEW_COLS = 3;

export type GenResult = {
  stem: string;
  outputDir: string;
  lwKey?: string;
  dskKey?: string;
  cuedDocx?: string;
  reviewPath?: string;
  previewFiles: { lw: string[]; dsk: string[] };
  flags: Flag[];
  lwCount: number;
  dskCount: number;
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

export function GenerateResultView({ job, onOpen }: { job: Job; onOpen: (src: string) => void }) {
  const [deck, setDeck] = useState<"lw" | "dsk">("lw");
  const result = (job.result || null) as GenResult | null;
  const urls = useMemo(() => {
    if (!result) return [];
    const names = result.previewFiles?.[deck] || [];
    const previewLabel = deck === "lw" ? "LW previews" : "DSK previews";
    if (!present(job, previewLabel)) return [];
    return names.map((name, i) => ({
      src: previewUrl(job.id, deck, name),
      label: `${deck.toUpperCase()} ${i + 1}`,
    }));
  }, [job, result, deck]);

  function jumpToSlide(location: string) {
    if (!result) return;
    const target = parseSlideTarget(location);
    if (!target) return;
    const names = result.previewFiles?.[target.deck] || [];
    const name = names[target.index - 1];
    if (!name) return;
    setDeck(target.deck);
    onOpen(previewUrl(job.id, target.deck, name));
  }

  if (job.status === "error") return <p className="err">{job.error}</p>;
  if (!result || job.status !== "done") return null;

  return (
    <>
      <p className="note path-note">
        {result.lwCount} LW · {result.dskCount} DSK · {result.outputDir}
      </p>
      <div className="actions">
        {result.lwKey && present(job, "LW.key") && (
          <button className="btn secondary" type="button" onClick={() => reveal(result.lwKey!)}>
            Show LW.key
          </button>
        )}
        {result.dskKey && present(job, "DSK.key") && (
          <button className="btn secondary" type="button" onClick={() => reveal(result.dskKey!)}>
            Show DSK.key
          </button>
        )}
        {result.cuedDocx && present(job, "cued outline") && (
          <button className="btn secondary" type="button" onClick={() => reveal(result.cuedDocx!)}>
            Show cued outline
          </button>
        )}
        {result.reviewPath && present(job, "review.pdf") && (
          <button className="btn secondary" type="button" onClick={() => reveal(result.reviewPath!)}>
            Show review.pdf
          </button>
        )}
      </div>
      <div className="seg">
        <button type="button" className={deck === "lw" ? "on" : ""} onClick={() => setDeck("lw")}>
          LW previews
        </button>
        <button type="button" className={deck === "dsk" ? "on" : ""} onClick={() => setDeck("dsk")}>
          DSK previews
        </button>
      </div>
      {urls.length > 0 ? (
        <PreviewGrid urls={urls} onOpen={onOpen} columns={deck === "lw" ? LW_PREVIEW_COLS : DSK_PREVIEW_COLS} />
      ) : (
        <p className="note">Previews are missing on disk.</p>
      )}
      <ValidationPanel flags={result.flags || []} onJump={jumpToSlide} />
    </>
  );
}
