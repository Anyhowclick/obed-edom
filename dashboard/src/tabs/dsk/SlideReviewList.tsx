import { useState } from "react";
import { chooseKeynote, dskThumbUrl, type DskPage } from "../../api";
import {
  bulkAnchor,
  bulkInclude,
  bulkKeepSide,
  bulkVideosOnly,
  groupPages,
  includedSlides,
  needsClip,
  setAnchor,
  setClip,
  setInclude,
  setKeepSide,
  setVideosOnly,
  type DecisionsMap,
  type DskAnchor,
} from "../../dsk/decisions";
import { FileWell } from "../../components/FileWell";

const ANCHORS: { value: DskAnchor; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "centre", label: "Centre" },
  { value: "left", label: "Left" },
  { value: "right", label: "Right" },
];

function AlignButtons({ onPick }: { onPick: (anchor: DskAnchor) => void }) {
  return (
    <>
      {ANCHORS.map((a) => (
        <button key={a.value} className="btn secondary" type="button" onClick={() => onPick(a.value)}>
          {a.label}
        </button>
      ))}
    </>
  );
}

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
  const [filter, setFilter] = useState("all");
  const numbers = pages.map((p) => p.slide);
  const groups = groupPages(pages);
  const shown = filter === "all" ? groups : groups.filter((g) => g.key === filter);

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
        <span className="note">Align included:</span>
        <AlignButtons onPick={(anchor) => onChange(bulkAnchor(decisions, pages, includedSlides(decisions, pages), anchor))} />
        <label className="inline-field">
          Show
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All ({pages.length})</option>
            {groups.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label} ({g.pages.length})
              </option>
            ))}
          </select>
        </label>
      </div>
      {shown.map((group) => {
        const groupNumbers = group.pages.map((p) => p.slide);
        const groupIncluded = includedSlides(decisions, group.pages);
        const videoCapable = group.pages.filter((p) => p.canVideosOnly).map((p) => p.slide);
        return (
          <section key={group.key} className="dsk-review-group">
            <div className="actions">
              <strong>
                {group.label} <span className="chip">{group.pages.length} slide(s)</span>
              </strong>
              <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, pages, groupNumbers, true))}>
                Include
              </button>
              <button className="btn secondary" type="button" onClick={() => onChange(bulkInclude(decisions, pages, groupNumbers, false))}>
                Exclude
              </button>
              <span className="note">Align:</span>
              <AlignButtons onPick={(anchor) => onChange(bulkAnchor(decisions, pages, groupIncluded, anchor))} />
              {videoCapable.length > 0 && (
                <>
                  <button className="btn secondary" type="button" onClick={() => onChange(bulkVideosOnly(decisions, pages, videoCapable, true))}>
                    Videos only: all
                  </button>
                  <button className="btn secondary" type="button" onClick={() => onChange(bulkVideosOnly(decisions, pages, videoCapable, false))}>
                    Videos only: none
                  </button>
                </>
              )}
            </div>
            <table className="dsk-review-table">
              <thead>
                <tr>
                  <th>Thumb</th>
                  <th>Slide</th>
                  <th>Category</th>
                  <th>Include</th>
                  <th>Action</th>
                  <th>Align</th>
                  <th>Videos only</th>
                  <th>Keep side</th>
                  <th>Clip</th>
                </tr>
              </thead>
              <tbody>
                {group.pages.map((page) => {
                  const decision =
                    decisions[page.slide] ||
                    { include: !page.isText, action: "in_deck", anchor: "auto", keepSide: false, clip: null, videosOnly: false };
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
                        {page.stackedMovies && <span className="chip">stacked — source build order</span>}
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
                          {ANCHORS.map((a) => (
                            <option key={a.value} value={a.value}>
                              {a.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {page.canVideosOnly ? (
                          <input
                            type="checkbox"
                            checked={!!decision.videosOnly}
                            disabled={disabled}
                            onChange={(e) => onChange(setVideosOnly(decisions, pages, page.slide, e.target.checked))}
                          />
                        ) : (
                          <span className="note">—</span>
                        )}
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
          </section>
        );
      })}
    </div>
  );
}
