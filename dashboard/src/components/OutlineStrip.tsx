import type { OutlineRow } from "../outline";

function CueChip({ tag }: { tag: string }) {
  const deck = /^dsk/i.test(tag) ? "dsk" : "lw";
  return <span className={`cue-chip ${deck}`}>[{tag}]</span>;
}

/**
 * The script behind one pair row.
 *
 * Cues are coloured the way Word highlights them — turquoise for the wall,
 * yellow for the lower third — so the strip reads like the printed show-call
 * sheet the operator is holding.
 */
export function OutlineStrip({ row, holds }: { row: OutlineRow; holds?: string }) {
  return (
    <div className="outline-strip">
      <div className="outline-cues">
        {row.tags.length ? (
          row.tags.map((tag, i) => <CueChip key={`${tag}-${i}`} tag={tag} />)
        ) : (
          <span className="cue-chip none">no cue</span>
        )}
        {holds && <span className="cue-hold">{holds} holds</span>}
      </div>
      {row.script && <p className="outline-script">{row.script}</p>}
    </div>
  );
}
