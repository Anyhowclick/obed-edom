import { chooseKeynote, dskThumbUrl, type DskPage } from "../../api";
import {
  bulkInclude,
  bulkKeepSide,
  needsClip,
  setAnchor,
  setClip,
  setInclude,
  setKeepSide,
  type DecisionsMap,
  type DskAnchor,
} from "../../dsk/decisions";
import { FileWell } from "../../components/FileWell";

export function SlideReviewList({
  jobId,
  pages,
  decisions,
  onChange,
  onOpen,
}: {
  jobId: string;
  pages: DskPage[];
  decisions: DecisionsMap;
  onChange: (next: DecisionsMap) => void;
  onOpen: (src: string) => void;
}) {
  const numbers = pages.map((p) => p.slide);

  return (
    <div className="dsk-review">
      <div className="actions">
        <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, pages, numbers, true))}>
          Include all
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, pages, numbers, false))}>
          Include none
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkKeepSide(decisions, pages, numbers, true))}>
          Keep side: all
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkKeepSide(decisions, pages, numbers, false))}>
          Keep side: none
        </button>
      </div>
      <table className="dsk-review-table">
        <thead>
          <tr>
            <th>Thumb</th>
            <th>Slide</th>
            <th>Category</th>
            <th>Include</th>
            <th>Action</th>
            <th>Anchor</th>
            <th>Keep side</th>
            <th>Clip</th>
          </tr>
        </thead>
        <tbody>
          {pages.map((page) => {
            const decision = decisions[page.slide] || { include: !page.isText, action: "in_deck", anchor: "auto", keepSide: false, clip: null };
            const disabled = page.isText;
            return (
              <tr key={page.slide} className={disabled ? "dsk-row-skipped" : undefined}>
                <td>
                  {page.thumb ? (
                    <button
                      type="button"
                      className="thumb-btn"
                      onClick={() => onOpen(dskThumbUrl(jobId, page.thumb!))}
                    >
                      <img src={dskThumbUrl(jobId, page.thumb)} alt={`Slide ${page.slide}`} />
                    </button>
                  ) : (
                    <span className="note">—</span>
                  )}
                </td>
                <td>{page.slide}</td>
                <td>
                  {page.category}
                  {disabled && <span className="chip">text slide — benched</span>}
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={decision.include}
                    disabled={disabled}
                    onChange={(e) => onChange(setInclude(decisions, pages, page.slide, e.target.checked))}
                  />
                </td>
                <td>{disabled ? "skip" : needsClip(page) ? "clip + deck" : "in deck"}</td>
                <td>
                  <select
                    value={decision.anchor || "auto"}
                    disabled={disabled}
                    onChange={(e) => onChange(setAnchor(decisions, pages, page.slide, e.target.value as DskAnchor))}
                  >
                    <option value="auto">Auto</option>
                    <option value="centre">Centre</option>
                    <option value="left">Left</option>
                    <option value="right">Right</option>
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={!!decision.keepSide}
                    disabled={disabled}
                    onChange={(e) => onChange(setKeepSide(decisions, pages, page.slide, e.target.checked))}
                  />
                </td>
                <td>
                  {needsClip(page) && !disabled ? (
                    <FileWell
                      label=""
                      hint="Choose .mov clip"
                      file={decision.clip ? { path: decision.clip, name: decision.clip.split("/").pop() || decision.clip } : null}
                      onChoose={async () => {
                        const chosen = await chooseKeynote(`Clip for slide ${page.slide}`).catch(() => null);
                        if (chosen) onChange(setClip(decisions, pages, page.slide, chosen.path));
                      }}
                      onPath={(path) => onChange(setClip(decisions, pages, page.slide, path))}
                      onClear={() => onChange(setClip(decisions, pages, page.slide, null))}
                    />
                  ) : (
                    <span className="note">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
