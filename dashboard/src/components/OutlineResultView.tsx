import { useMemo } from "react";
import { outlinePdfUrl, type Flag, type Job } from "../api";
import type { OutlineCue, OutlineParagraph, OutlineResult } from "../outline";
import { SHOW_INFO_KEY, useSessionToggle } from "../prefs";
import { SlideFindings } from "./SlideFindings";
import { ValidationPanel } from "./ValidationPanel";

/** Split a paragraph into its cue tags and the words between them. */
function segments(para: OutlineParagraph): { text: string; cue?: OutlineCue }[] {
  const cues = [...(para.cues || [])].sort((a, b) => a.start - b.start);
  if (!cues.length) return [{ text: para.text }];
  const out: { text: string; cue?: OutlineCue }[] = [];
  let at = 0;
  for (const cue of cues) {
    if (cue.start > at) out.push({ text: para.text.slice(at, cue.start) });
    out.push({ text: para.text.slice(cue.start, cue.end), cue });
    at = cue.end;
  }
  if (at < para.text.length) out.push({ text: para.text.slice(at) });
  return out;
}

/**
 * The cued outline as the operator reads it, with findings alongside.
 *
 * This is the whole result when no Keynote is supplied, so the document itself
 * is the layout: cue chips sit where Word highlights them and each finding sits
 * next to the line it is about, the way the pair rows show slide findings.
 */
export function OutlineResultView({ job }: { job: Job }) {
  const result = (job.result || undefined) as OutlineResult | undefined;
  const [showInfo, setShowInfo] = useSessionToggle(SHOW_INFO_KEY, false);
  const flags = useMemo(() => result?.outlineFlags || [], [result?.outlineFlags]);

  const { byParagraph, wide } = useMemo(() => {
    const grouped = new Map<number, Flag[]>();
    const rest: Flag[] = [];
    for (const flag of flags) {
      if (flag.slide == null) {
        rest.push(flag);
        continue;
      }
      const bucket = grouped.get(flag.slide);
      if (bucket) bucket.push(flag);
      else grouped.set(flag.slide, [flag]);
    }
    return { byParagraph: grouped, wide: rest };
  }, [flags]);

  if (job.status === "error") return <p className="err">{job.error}</p>;
  if (!result || job.status !== "done") return null;

  const paragraphs = (result.paragraphs || []).filter((p) => p.text.trim() || p.cues.length);

  return (
    <>
      <div className="playlist-bar">
        <p className="note outline-summary">
          {result.lwCues ?? 0} LW and {result.dskCues ?? 0} DSK cues across{" "}
          {result.rows?.length ?? 0} slide advances.
        </p>
        <div className="actions playlist-controls">
          {result.outlineReport && (
            <a className="btn secondary" href={outlinePdfUrl(job.id)} target="_blank" rel="noreferrer">
              Export PDF
            </a>
          )}
          <button
            className={`btn secondary toggle${showInfo ? " on" : ""}`}
            type="button"
            aria-pressed={showInfo}
            title="Info findings are notes rather than problems"
            onClick={() => setShowInfo(!showInfo)}
          >
            {showInfo ? "Hide info findings" : "Show info findings"}
          </button>
        </div>
      </div>

      <div className="outline-reader">
        {paragraphs.map((para) => {
          const found = byParagraph.get(para.number) || [];
          return (
            <article
              key={para.index}
              className={`outline-para${found.length ? " flagged" : ""}`}
            >
              <p className="outline-text">
                <span className="outline-num">{para.number}</span>
                {segments(para).map((seg, i) =>
                  seg.cue ? (
                    <span key={i} className={`cue-chip ${seg.cue.deck}`}>
                      {seg.text}
                    </span>
                  ) : (
                    <span key={i}>{seg.text}</span>
                  )
                )}
              </p>
              {found.length > 0 && (
                <SlideFindings flags={found} jobId={job.id} showInfo={showInfo} />
              )}
            </article>
          );
        })}
      </div>

      {wide.length > 0 && (
        <ValidationPanel
          flags={wide}
          jobId={job.id}
          showInfo={showInfo}
          onShowInfo={setShowInfo}
          title="Outline findings"
        />
      )}
    </>
  );
}
