import type { OutlineRow } from "../outline";

function CueChip({ tag }: { tag: string }) {
  const deck = /^dsk/i.test(tag) ? "dsk" : "lw";
  return <span className={`cue-chip ${deck}`}>[{tag}]</span>;
}

/**
 * Script behind one pair. Cue chips match Word: turquoise wall, yellow DSK.
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
