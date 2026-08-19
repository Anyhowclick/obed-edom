import { previewUrl, type Flag, type Job } from "../api";
import { PreviewGrid } from "./PreviewGrid";
import { ValidationPanel } from "./ValidationPanel";

export type InspectResult = {
  path?: string;
  flags?: Flag[];
  previewFileNames?: string[];
  previewFiles?: { lw: string[] };
  slideWidth?: number;
  slideHeight?: number;
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

export function InspectResultView({
  job,
  labelPrefix = "Slide",
  onOpen,
}: {
  job: Job;
  labelPrefix?: string;
  onOpen: (src: string) => void;
}) {
  const result = (job.result || undefined) as InspectResult | undefined;
  const names = result?.previewFileNames || result?.previewFiles?.lw || [];
  const previewsOk = present(job, "LW previews") && present(job, "preview dir");
  const urls =
    previewsOk && names.length
      ? names.map((name, i) => ({ src: previewUrl(job.id, "lw", name), label: `${labelPrefix} ${i + 1}` }))
      : [];

  if (job.status === "error") return <p className="err">{job.error}</p>;

  return (
    <>
      {result?.slideWidth && (
        <p className="note">
          Source canvas {result.slideWidth}×{result.slideHeight}
        </p>
      )}
      {urls.length > 0 ? <PreviewGrid urls={urls} onOpen={onOpen} /> : null}
      <ValidationPanel flags={result?.flags || []} />
    </>
  );
}
