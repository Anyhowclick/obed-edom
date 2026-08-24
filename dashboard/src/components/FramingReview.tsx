import { useMemo, useState } from "react";
import type { FramingDecision } from "../api";

/**
 * Confirm which crop each map page uses, before anything is remapped.
 *
 * Every row renders the actual crop: the wall slide's own thumbnail placed inside
 * a 16:9 box under the candidate's transform. Slide numbers alone say nothing
 * about how a framing looks, and alt-tabbing to Keynote to find out defeats the
 * point of asking here.
 *
 * Pages are grouped by the framing they use, because on a real report card 155
 * pages collapse into about ten framings — so the common case is confirming a
 * group, not paging through slides. Rows open underneath for when a single page
 * needs a different crop from its neighbours, which is the failure this exists
 * to catch.
 */

export type FramingTransform = { s: number; tx: number; ty: number };

export type FramingCandidate = {
  templateSlide: number;
  name?: string;
  agreement: number;
  fit: number;
  autoPick?: boolean;
  wouldFallBack?: boolean;
  transform?: FramingTransform | null;
};

export type FramingPage = {
  slide: number;
  index: number;
  thumb?: string | null;
  autoTransform?: FramingTransform | null;
  autoTemplateSlide: number | null;
  autoFellBack: boolean;
  needsAttention: boolean;
  noUsableFraming: boolean;
  resurfaced?: boolean;
  candidates: FramingCandidate[];
  decision?: FramingDecision;
};

export type FramingProposal = {
  phase?: string;
  pages?: FramingPage[];
  needAttention?: number[];
  noUsableFraming?: number[];
  templateChanged?: boolean;
  resurfaced?: number[];
  destWidth?: number;
  destHeight?: number;
  wallWidth?: number;
  wallHeight?: number;
  /** Template slide number to thumbnail file name. */
  templateThumbs?: Record<string, string>;
};

type Category = "matched" | "fitted" | "template";

const CATEGORY_LABEL: Record<Category, string> = {
  matched: "Matched",
  fitted: "Fitted content",
  template: "New template",
};

/** One colour per bucket, used on the tabs and on every button that moves a page
 *  into that bucket, so the same meaning always looks the same. */
const CATEGORY_TONE: Record<Category, string> = {
  matched: "tone-matched",
  fitted: "tone-alt",
  template: "tone-template",
};

const PAGE_SIZES = [5, 10, 25];

/** The framing a page will actually use, whoever decided it. */
function chosenSlide(page: FramingPage, decisions: Record<number, FramingDecision>): number | null {
  const decision = decisions[page.index] ?? page.decision;
  if (decision?.state === "pinned" && decision.templateSlide != null) return decision.templateSlide;
  if (decision?.state === "deferred") return null;
  return page.autoTemplateSlide;
}

function stateOf(page: FramingPage, decisions: Record<number, FramingDecision>): FramingDecision["state"] {
  return (decisions[page.index] ?? page.decision)?.state ?? "auto";
}

/** Whether the framing this page will use falls back to fitting content. */
function fellBackWith(page: FramingPage, slide: number | null): boolean {
  if (slide == null) return page.autoFellBack;
  const candidate = page.candidates.find((c) => c.templateSlide === slide);
  return candidate?.wouldFallBack ?? page.autoFellBack;
}

/**
 * Which bucket a page sits in, keyed on the outcome of the framing it will
 * actually use. Switching a page to a framing that applies cleanly moves it out
 * of Fitted content by itself, which is the point: the tabs track what the deck
 * will look like, not what was clicked.
 */
function categoryOf(page: FramingPage, decisions: Record<number, FramingDecision>): Category {
  if (stateOf(page, decisions) === "deferred") return "template";
  return fellBackWith(page, chosenSlide(page, decisions)) ? "fitted" : "matched";
}

function transformFor(page: FramingPage, slide: number | null): FramingTransform | null {
  if (slide == null) return page.autoTransform ?? null;
  const candidate = page.candidates.find((c) => c.templateSlide === slide);
  return candidate?.transform ?? page.autoTransform ?? null;
}

/** The crop, drawn by placing the wall image inside a 16:9 window. */
function CropPreview({
  src,
  transform,
  wallWidth,
  destWidth,
  destHeight,
  width,
  title,
}: {
  src?: string | null;
  transform?: FramingTransform | null;
  wallWidth: number;
  destWidth: number;
  destHeight: number;
  width: number;
  title?: string;
}) {
  const k = width / destWidth;
  const height = Math.round(destHeight * k);
  return (
    <div className="crop-preview" style={{ width, height }} title={title}>
      {src && transform ? (
        <img
          src={src}
          alt=""
          style={{
            left: transform.tx * k,
            top: transform.ty * k,
            width: wallWidth * transform.s * k,
          }}
        />
      ) : (
        <span className="crop-empty">no preview</span>
      )}
    </div>
  );
}

function candidateLabel(candidate: FramingCandidate): string {
  const bits = [`Template slide ${candidate.templateSlide}`];
  if (candidate.wouldFallBack) bits.push("would fall back");
  if (candidate.autoPick) bits.push("auto");
  bits.push(`agreement ${candidate.agreement}`, `fit ${candidate.fit.toFixed(3)}`);
  return bits.join(" — ");
}

export function FramingReview({
  proposal,
  jobId,
  busy,
  onSave,
  onApply,
}: {
  proposal: FramingProposal;
  jobId: string;
  busy: boolean;
  onSave: (decisions: FramingDecision[]) => void;
  onApply: (decisions: FramingDecision[]) => void;
}) {
  const pages = proposal.pages || [];
  const wallWidth = proposal.wallWidth || 7680;
  const destWidth = proposal.destWidth || 1920;
  const destHeight = proposal.destHeight || 1080;

  const [decisions, setDecisions] = useState<Record<number, FramingDecision>>({});
  const [tab, setTab] = useState<Category>("matched");
  const [pageSize, setPageSize] = useState(10);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [groupPage, setGroupPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [previewing, setPreviewing] = useState<Record<number, number>>({});

  const byCategory = useMemo(() => {
    const out: Record<Category, FramingPage[]> = { matched: [], fitted: [], template: [] };
    for (const page of pages) out[categoryOf(page, decisions)].push(page);
    // Fell back first, since those are the ones needing eyes, then deck order so
    // the rest stay findable by slide number.
    for (const list of Object.values(out)) {
      list.sort((a, b) => {
        const af = fellBackWith(a, chosenSlide(a, decisions));
        const bf = fellBackWith(b, chosenSlide(b, decisions));
        if (af !== bf) return af ? -1 : 1;
        return a.slide - b.slide;
      });
    }
    return out;
  }, [pages, decisions]);

  const groups = useMemo(() => {
    const map = new Map<string, FramingPage[]>();
    for (const page of byCategory[tab]) {
      const key = String(chosenSlide(page, decisions) ?? "none");
      const list = map.get(key);
      if (list) list.push(page);
      else map.set(key, [page]);
    }
    return [...map.entries()]
      .map(([key, list]) => ({ key, slide: key === "none" ? null : Number(key), pages: list }))
      .sort((a, b) => b.pages.length - a.pages.length);
  }, [byCategory, tab, decisions]);

  function thumbUrl(page: FramingPage): string | null {
    return page.thumb ? `/api/resize/${jobId}/thumb/wall/${encodeURIComponent(page.thumb)}` : null;
  }

  function templateThumbUrl(slide: number | null): string | null {
    const name = slide == null ? null : proposal.templateThumbs?.[String(slide)];
    return name ? `/api/resize/${jobId}/thumb/template/${encodeURIComponent(name)}` : null;
  }

  function decide(indexes: number[], state: FramingDecision["state"], slideFor: (page: FramingPage) => number | null) {
    setDecisions((current) => {
      const next = { ...current };
      for (const index of indexes) {
        const page = pages.find((p) => p.index === index);
        if (!page) continue;
        const slide = state === "pinned" ? slideFor(page) : null;
        next[index] = { wallIndex: index, state, templateSlide: slide };
      }
      return next;
    });
  }

  function moveSelected(target: Category) {
    const indexes = [...selected];
    if (!indexes.length) return;
    if (target === "template") {
      decide(indexes, "deferred", () => null);
    } else if (target === "matched") {
      // Pin the best framing that does not fall back, so "move to Matched" is a
      // real instruction rather than a wish. Pages with no such framing stay put.
      decide(indexes, "pinned", (p) => {
        const clean = p.candidates.find((c) => !c.wouldFallBack);
        return clean ? clean.templateSlide : chosenSlide(p, decisions);
      });
    } else {
      // Accepting a fitted result: pin what it already uses, so the page counts as
      // looked at rather than merely untouched.
      decide(indexes, "pinned", (p) => chosenSlide(p, decisions) ?? p.autoTemplateSlide);
    }
    setSelected(new Set());
  }

  function collect(): FramingDecision[] {
    return pages
      .map((page) => decisions[page.index] ?? page.decision)
      .filter((d): d is FramingDecision => !!d && d.state !== "auto");
  }

  const reviewed = pages.filter((p) => stateOf(p, decisions) === "pinned").length;

  if (!pages.length) return null;

  return (
    <div className="framing-review">
      <div className="playlist-bar framing-bar">
        <div className="framing-tabs">
          {(Object.keys(CATEGORY_LABEL) as Category[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`btn secondary ${CATEGORY_TONE[key]}${tab === key ? " on" : ""}`}
              onClick={() => {
                setTab(key);
                setOpenGroup(null);
                setGroupPage(0);
              }}
            >
              {CATEGORY_LABEL[key]} ({byCategory[key].length})
            </button>
          ))}
        </div>
        <div className="actions playlist-controls">
          {selected.size > 0 && (
            <>
              <span className="note">{selected.size} selected → </span>
              {(Object.keys(CATEGORY_LABEL) as Category[])
                .filter((key) => key !== tab)
                .map((key) => (
                  <button
                    key={key}
                    className={`btn secondary ${CATEGORY_TONE[key]}`}
                    type="button"
                    disabled={busy}
                    onClick={() => moveSelected(key)}
                  >
                    {CATEGORY_LABEL[key]}
                  </button>
                ))}
            </>
          )}
          <label className="field inline-field">
            Per page
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setGroupPage(0); }}>
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="btn tone-save" type="button" disabled={busy} onClick={() => onSave(collect())}>
            Save decisions
          </button>
          <button className="btn run-checks" type="button" disabled={busy} onClick={() => onApply(collect())}>
            Resize with these framings
          </button>
        </div>
      </div>

      <p className="note">
        {pages.length} page{pages.length === 1 ? "" : "s"} take a framing. {reviewed} reviewed,{" "}
        {byCategory.template.length} waiting on a new template slide.
        {proposal.templateChanged && (proposal.resurfaced?.length ?? 0) > 0 &&
          ` The template changed, so ${proposal.resurfaced!.length} deferred page(s) can now use a new framing.`}
      </p>

      {groups.length === 0 && <p className="note">Nothing in {CATEGORY_LABEL[tab].toLowerCase()}.</p>}

      {groups.map((group) => {
        const open = openGroup === group.key;
            const fellBack = group.pages.filter((p) =>
              fellBackWith(p, chosenSlide(p, decisions))
            ).length;
        const start = open ? groupPage * pageSize : 0;
        const shown = open ? group.pages.slice(start, start + pageSize) : [];
        const totalPages = Math.max(1, Math.ceil(group.pages.length / pageSize));
        return (
          <article key={group.key} className={`framing-group${fellBack ? " flagged" : ""}`}>
            {/* The template slide, not just its number: "template slide 4" means
                nothing without seeing the framing it stands for. */}
            <div className="framing-head">
              {templateThumbUrl(group.slide) && (
                <span className="template-thumb">
                  <img src={templateThumbUrl(group.slide)!} alt={`Template slide ${group.slide}`} />
                  <span className="template-zoom">
                    <img src={templateThumbUrl(group.slide)!} alt="" />
                  </span>
                </span>
              )}
              <p className="outline-text">
                <strong>
                  {group.slide == null ? "Needs a new template slide" : `Template slide ${group.slide}`}
                </strong>
                <span className="note">
                  {group.pages.length} page{group.pages.length === 1 ? "" : "s"}
                  {fellBack > 0 && ` · ${fellBack} fell back to fitting content`}
                  {fellBack === 0 && group.slide != null && " · all matched this framing"}
                </span>
              </p>
            </div>

            {/* Every page in the group, so a wrong one in a batch of 56 is visible
                without opening anything. */}
            <div className="framing-strip">
              {group.pages.map((page) => {
                const isSelected = selected.has(page.index);
                return (
                  <button
                    key={page.slide}
                    type="button"
                    className={
                      "framing-chip" +
                      (isSelected ? " selected" : "") +
                      // Tracks the framing the page will use, so switching one to a
                      // clean framing turns its border green immediately.
                      (fellBackWith(page, chosenSlide(page, decisions)) ? " fellback" : "")
                    }
                    title={
                      `Slide ${page.slide}` +
                      (fellBackWith(page, chosenSlide(page, decisions))
                        ? " — falls back to fitting content"
                        : "")
                    }
                    onClick={() =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (next.has(page.index)) next.delete(page.index);
                        else next.add(page.index);
                        return next;
                      })
                    }
                  >
                    <CropPreview
                      src={thumbUrl(page)}
                      transform={transformFor(page, chosenSlide(page, decisions))}
                      wallWidth={wallWidth}
                      destWidth={destWidth}
                      destHeight={destHeight}
                      width={104}
                    />
                    <span className="framing-chip-num">{page.slide}</span>
                  </button>
                );
              })}
            </div>

            <div className="actions">
              {group.slide != null && (
                <button
                  className="btn secondary tone-matched"
                  type="button"
                  disabled={busy}
                  onClick={() => decide(group.pages.map((p) => p.index), "pinned", () => group.slide)}
                >
                  Confirm all {group.pages.length}
                </button>
              )}
              <button
                className="btn secondary tone-template"
                type="button"
                disabled={busy}
                onClick={() => decide(group.pages.map((p) => p.index), "deferred", () => null)}
              >
                Needs a new template slide
              </button>
              <button
                className="btn secondary"
                type="button"
                onClick={() => {
                  setOpenGroup(open ? null : group.key);
                  setGroupPage(0);
                }}
              >
                {open ? "Hide pages" : `Open pages (${group.pages.length})`}
              </button>
              <button
                className="btn secondary"
                type="button"
                onClick={() =>
                  setSelected((current) => {
                    const next = new Set(current);
                    const all = group.pages.every((p) => next.has(p.index));
                    for (const p of group.pages) {
                      if (all) next.delete(p.index);
                      else next.add(p.index);
                    }
                    return next;
                  })
                }
              >
                {group.pages.every((p) => selected.has(p.index)) ? "Deselect group" : "Select group"}
              </button>
            </div>

            {open && (
              <div className="framing-pages">
                {shown.map((page) => {
                  const current = chosenSlide(page, decisions);
                  const preview = previewing[page.index] ?? current;
                  const differs = preview != null && preview !== current;
                  const previewFalls = fellBackWith(page, preview);
                  return (
                    <div key={page.slide} className="framing-row">
                      <label className="framing-check">
                        <input
                          type="checkbox"
                          checked={selected.has(page.index)}
                          onChange={(e) =>
                            setSelected((cur) => {
                              const next = new Set(cur);
                              if (e.target.checked) next.add(page.index);
                              else next.delete(page.index);
                              return next;
                            })
                          }
                        />
                        <span className="outline-num">{page.slide}</span>
                      </label>
                      <CropPreview
                        src={thumbUrl(page)}
                        transform={transformFor(page, preview)}
                        wallWidth={wallWidth}
                        destWidth={destWidth}
                        destHeight={destHeight}
                        width={280}
                        title={`Slide ${page.slide} as template slide ${preview}`}
                      />
                      <div className="framing-row-controls">
                        {/* A native select cannot show images in its option list, so
                            the framings are picked from their own thumbnails. Also
                            better than a dropdown here: all of them are visible at
                            once rather than one at a time. */}
                        <div className="framing-picker">
                          {page.candidates.map((candidate) => {
                            const url = templateThumbUrl(candidate.templateSlide);
                            return (
                              <button
                                key={candidate.templateSlide}
                                type="button"
                                disabled={busy}
                                title={candidateLabel(candidate)}
                                className={
                                  "framing-option" +
                                  (candidate.templateSlide === preview ? " current" : "") +
                                  (candidate.wouldFallBack ? " fellback" : "")
                                }
                                onClick={() =>
                                  setPreviewing((cur) => ({
                                    ...cur,
                                    [page.index]: candidate.templateSlide,
                                  }))
                                }
                              >
                                {url ? <img src={url} alt="" /> : <span className="crop-empty">?</span>}
                                <span className="framing-option-num">
                                  {candidate.templateSlide} · {candidate.fit.toFixed(2)}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                        <div className="actions">
                          <button
                            className="btn secondary tone-alt"
                            type="button"
                            disabled={busy || !differs}
                            onClick={() => decide([page.index], "pinned", () => preview)}
                          >
                            Use this framing
                          </button>
                          <button
                            className="btn secondary tone-template"
                            type="button"
                            disabled={busy}
                            onClick={() => decide([page.index], "deferred", () => null)}
                          >
                            Needs a new template
                          </button>
                        </div>
                        <p className="note">
                          {`Template slide ${preview ?? "—"}. `}
                          {previewFalls
                            ? "This framing falls back to fitting content. "
                            : "This framing applies cleanly. "}
                          {stateOf(page, decisions) === "pinned" && "Reviewed. "}
                          {page.resurfaced && "The template changed since you deferred this. "}
                        </p>
                      </div>
                    </div>
                  );
                })}
                {totalPages > 1 && (
                  <div className="actions">
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={groupPage === 0}
                      onClick={() => setGroupPage((n) => Math.max(0, n - 1))}
                    >
                      Previous
                    </button>
                    <span className="note">
                      Page {groupPage + 1} of {totalPages}
                    </span>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={groupPage >= totalPages - 1}
                      onClick={() => setGroupPage((n) => Math.min(totalPages - 1, n + 1))}
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
