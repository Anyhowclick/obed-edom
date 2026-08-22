import { useMemo } from "react";
import { previewUrl, type Flag, type Job } from "../api";
import { PreviewGrid } from "./PreviewGrid";
import { SHOW_INFO_KEY, useSessionToggle } from "../prefs";
import { SlideFindings } from "./SlideFindings";
import { parseSlideTarget, ValidationPanel } from "./ValidationPanel";

export type InspectResult = {
  path?: string;
  outlinePath?: string | null;
  deck?: string;
  flags?: Flag[];
  outlineFlags?: Flag[];
  previewFileNames?: string[];
  previewFiles?: { lw: string[] };
  slideWidth?: number;
  slideHeight?: number;
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

/** Slide number a finding belongs to, from the field or the location text. */
function slideOf(flag: Flag): number | null {
  if (flag.slide != null) return flag.slide;
  return parseSlideTarget(flag.location)?.index ?? null;
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
  const [showInfo, setShowInfo] = useSessionToggle(SHOW_INFO_KEY, false);
  const names = useMemo(
    () => result?.previewFileNames || result?.previewFiles?.lw || [],
    [result?.previewFileNames, result?.previewFiles?.lw]
  );
  const previewsOk = present(job, "LW previews") && present(job, "preview dir");
  const flags = result?.flags || [];
  const outlineFlags = result?.outlineFlags || [];

  // Group by slide so a finding sits next to the slide it is about, the way
  // the Diff Checker already shows them.
  const { bySlide, deckWide } = useMemo(() => {
    const grouped = new Map<number, Flag[]>();
    const rest: Flag[] = [];
    for (const flag of flags) {
      const slide = slideOf(flag);
      if (slide == null) {
        rest.push(flag);
        continue;
      }
      const bucket = grouped.get(slide);
      if (bucket) bucket.push(flag);
      else grouped.set(slide, [flag]);
    }
    return { bySlide: grouped, deckWide: rest };
  }, [flags]);

  function jumpToSlide(location: string) {
    const target = parseSlideTarget(location);
    if (!target) return;
    const name = names[target.index - 1];
    if (name) onOpen(previewUrl(job.id, "lw", name));
  }

  if (job.status === "error") return <p className="err">{job.error}</p>;

  const rows =
    previewsOk && names.length
      ? names.map((name, i) => ({ name, number: i + 1, src: previewUrl(job.id, "lw", name) }))
      : [];
  const flagged = rows.some((row) => (bySlide.get(row.number) || []).length);

  return (
    <>
      {result?.slideWidth && (
        <p className="note">
          Source canvas {result.slideWidth}×{result.slideHeight}
        </p>
      )}
      {rows.length > 0 && flagged ? (
        <div className="slide-findings">
          {rows.map((row) => {
            const slideFlags = bySlide.get(row.number) || [];
            return (
              <article key={row.name} className={`slide-card${slideFlags.length ? " flagged" : ""}`}>
                <div className="slide-slot dsk-frame">
                  <div className="cap">
                    {labelPrefix} {row.number}
                  </div>
                  <img src={row.src} alt={`${labelPrefix} ${row.number}`} onClick={() => onOpen(row.src)} />
                </div>
                {slideFlags.length ? (
                  <SlideFindings flags={slideFlags} jobId={job.id} showInfo={showInfo} onOpen={onOpen} />
                ) : (
                  <p className="pair-ok note">No findings.</p>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        rows.length > 0 && <PreviewGrid urls={rows.map((r) => ({ src: r.src, label: `${labelPrefix} ${r.number}` }))} onOpen={onOpen} columns={2} />
      )}
      <ValidationPanel
        flags={deckWide}
        jobId={job.id}
        onJump={jumpToSlide}
        onOpen={onOpen}
        showInfo={showInfo}
        onShowInfo={setShowInfo}
        title={flagged ? "Deck-wide findings" : "Validation"}
      />
      {outlineFlags.length > 0 && (
        <ValidationPanel
          flags={outlineFlags}
          jobId={job.id}
          onOpen={onOpen}
          showInfo={showInfo}
          onShowInfo={setShowInfo}
          title="Outline findings"
        />
      )}
    </>
  );
}
