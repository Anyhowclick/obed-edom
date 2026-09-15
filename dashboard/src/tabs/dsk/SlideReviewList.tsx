import { chooseKeynote, dskThumbUrl, type DskSlide } from "../../api";
import {
  bulkInclude,
  bulkKeepSide,
  needsClip,
  setAnchor,
  setClip,
  setInclude,
  setKeepSide,
  type DecisionsMap,
  type SlideAnchor,
} from "../../dsk/decisions";
import { FileWell } from "../../components/FileWell";

export function SlideReviewList({
  proposalId,
  slides,
  decisions,
  onChange,
  onOpen,
}: {
  proposalId: string;
  slides: DskSlide[];
  decisions: DecisionsMap;
  onChange: (next: DecisionsMap) => void;
  onOpen: (src: string) => void;
}) {
  const numbers = slides.map((s) => s.number);

  return (
    <div className="dsk-review">
      <div className="actions">
        <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, slides, numbers, true))}>
          Include all
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, slides, numbers, false))}>
          Include none
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkKeepSide(decisions, numbers, true))}>
          Keep side: all
        </button>
        <button className="btn secondary" type="button" onClick={() => onChange(bulkKeepSide(decisions, numbers, false))}>
          Keep side: none
        </button>
      </div>
      <table className="dsk-review-table">
        <thead>
          <tr>
            <th>Thumb</th>
            <th>Slide</th>
            <th>Class</th>
            <th>Include</th>
            <th>Action</th>
            <th>Anchor</th>
            <th>Keep side</th>
            <th>Clip</th>
          </tr>
        </thead>
        <tbody>
          {slides.map((page) => {
            const decision = decisions[page.number] || { include: !page.skipped };
            const disabled = page.skipped;
            return (
              <tr key={page.number} className={disabled ? "dsk-row-skipped" : undefined}>
                <td>
                  {page.thumbnail ? (
                    <button
                      type="button"
                      className="thumb-btn"
                      onClick={() => onOpen(dskThumbUrl(proposalId, page.thumbnail!))}
                    >
                      <img src={dskThumbUrl(proposalId, page.thumbnail)} alt={`Slide ${page.number}`} />
                    </button>
                  ) : (
                    <span className="note">—</span>
                  )}
                </td>
                <td>{page.number}</td>
                <td>
                  {page.class}
                  {disabled && <span className="chip">text slide — benched</span>}
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={decision.include}
                    disabled={disabled}
                    onChange={(e) => onChange(setInclude(decisions, slides, page.number, e.target.checked))}
                  />
                </td>
                <td>{disabled ? "skip" : "in deck"}</td>
                <td>
                  <select
                    value={decision.anchor || "centre"}
                    disabled={disabled}
                    onChange={(e) => onChange(setAnchor(decisions, page.number, e.target.value as SlideAnchor))}
                  >
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
                    onChange={(e) => onChange(setKeepSide(decisions, page.number, e.target.checked))}
                  />
                </td>
                <td>
                  {needsClip(page) && !disabled ? (
                    <FileWell
                      label=""
                      hint="Choose .mov clip"
                      file={decision.clip ? { path: decision.clip, name: decision.clip.split("/").pop() || decision.clip } : null}
                      onChoose={async () => {
                        const chosen = await chooseKeynote(`Clip for slide ${page.number}`).catch(() => null);
                        if (chosen) onChange(setClip(decisions, page.number, chosen.path));
                      }}
                      onPath={(path) => onChange(setClip(decisions, page.number, path))}
                      onClear={() => onChange(setClip(decisions, page.number, undefined))}
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
