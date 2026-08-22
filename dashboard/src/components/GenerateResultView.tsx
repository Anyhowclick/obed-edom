import { useState } from "react";
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

  const hasLw = Boolean(result.lwKey) || (result.previewFiles?.lw || []).length > 0;
  const hasDsk = Boolean(result.dskKey) || (result.previewFiles?.dsk || []).length > 0;
  const shown = deck === "lw" && !hasLw && hasDsk ? "dsk" : deck === "dsk" && !hasDsk && hasLw ? "lw" : deck;
  const names = result.previewFiles?.[shown] || [];
  const previewLabel = shown === "lw" ? "LW previews" : "DSK previews";
  const generated = shown === "lw" ? hasLw : hasDsk;
  const urls =
    generated && present(job, previewLabel) && names.length
      ? names.map((name, i) => ({
          src: previewUrl(job.id, shown, name),
          label: `${shown.toUpperCase()} ${i + 1}`,
        }))
      : [];

  return (
    <>
      <p className="note path-note">
        {hasLw ? `${result.lwCount} LW` : "No LW"}
        {" · "}
        {hasDsk ? `${result.dskCount} DSK` : "No DSK"}
        {" · "}
        {result.outputDir}
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
      {(hasLw || hasDsk) && (
        <div className="seg">
          {hasLw && (
            <button type="button" className={shown === "lw" ? "on" : ""} onClick={() => setDeck("lw")}>
              LW previews
            </button>
          )}
          {hasDsk && (
            <button type="button" className={shown === "dsk" ? "on" : ""} onClick={() => setDeck("dsk")}>
              DSK previews
            </button>
          )}
        </div>
      )}
      {urls.length > 0 ? (
        <PreviewGrid urls={urls} onOpen={onOpen} columns={shown === "lw" ? LW_PREVIEW_COLS : DSK_PREVIEW_COLS} />
      ) : generated ? (
        <p className="note">Previews are missing on disk.</p>
      ) : (
        <p className="note">This run did not generate a {shown.toUpperCase()} deck (no template).</p>
      )}
      <ValidationPanel flags={result.flags || []} onJump={jumpToSlide} />
    </>
  );
}
