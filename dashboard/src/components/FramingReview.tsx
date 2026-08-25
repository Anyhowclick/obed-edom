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

/** Where one object lands, in destination (CG) coordinates. */
export type PlannedRect = {
  role: string;
  kind: string;
  x: number;
  y: number;
  w: number;
  h: number;
  text?: string;
};

export type FramingCandidate = {
  templateSlide: number;
  name?: string;
  agreement: number;
  fit: number;
  autoPick?: boolean;
  wouldFallBack?: boolean;
  transform?: FramingTransform | null;
  rects?: PlannedRect[];
};

export type FramingPage = {
  slide: number;
  index: number;
  thumb?: string | null;
  autoTransform?: FramingTransform | null;
  autoRects?: PlannedRect[];
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

type Category = "matched" | "fitted" | "template" | "reviewed";

const CATEGORY_LABEL: Record<Category, string> = {
  matched: "Good fit",
  fitted: "Fitted content",
  template: "New template",
  reviewed: "Reviewed",
};

/** One colour per bucket, used on the tabs and on every button that moves a page
 *  into that bucket, so the same meaning always looks the same. */
const CATEGORY_TONE: Record<Category, string> = {
  matched: "tone-matched",
  fitted: "tone-alt",
  template: "tone-template",
  reviewed: "tone-reviewed",
};

const TABS: Category[] = ["matched", "fitted", "template", "reviewed"];

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
 * Which bucket a page sits in.
 *
 * Confirmed pages live in Reviewed, so the other three hold only what still
 * needs a look — that is what makes "how much is left" answerable at a glance.
 * The unreviewed buckets are keyed on the outcome of the framing the page will
 * use rather than on what was clicked, so switching a page to a framing that
 * applies cleanly moves it out of Fitted content by itself.
 */
function categoryOf(page: FramingPage, decisions: Record<number, FramingDecision>): Category {
  const state = stateOf(page, decisions);
  if (state === "pinned") return "reviewed";
  if (state === "deferred") return "template";
  return fellBackWith(page, chosenSlide(page, decisions)) ? "fitted" : "matched";
}

function transformFor(page: FramingPage, slide: number | null): FramingTransform | null {
  if (slide == null) return page.autoTransform ?? null;
  const candidate = page.candidates.find((c) => c.templateSlide === slide);
  return candidate?.transform ?? page.autoTransform ?? null;
}

function rectsFor(page: FramingPage, slide: number | null): PlannedRect[] {
  if (slide == null) return page.autoRects ?? [];
  const candidate = page.candidates.find((c) => c.templateSlide === slide);
  return candidate?.rects ?? page.autoRects ?? [];
}

/** The crop, drawn by placing the wall image inside a 16:9 window.
 *
 * `rects` draws what the planner does to each object on top of it. The crop is
 * one affine over the whole wall, so on its own it cannot show the badge landing
 * on its template slot, lists repacking, or the objects the run hides — which is
 * where the result actually diverges from what the operator was shown.
 */
function CropPreview({
  src,
  transform,
  rects,
  wallWidth,
  destWidth,
  destHeight,
  width,
  title,
}: {
  src?: string | null;
  transform?: FramingTransform | null;
  rects?: PlannedRect[];
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
      {(rects || []).map((rect, i) => (
        <span
          key={i}
          className={`plan-rect role-${rect.role}`}
          title={`${rect.role} · ${rect.kind}${rect.text ? ` · ${rect.text}` : ""}`}
          style={{
            left: rect.x * k,
            top: rect.y * k,
            // A rule inspects as zero-width, so give every box a hairline.
            width: Math.max(rect.w * k, 1),
            height: Math.max(rect.h * k, 1),
          }}
        />
      ))}
    </div>
  );
}

/** Which roles this page actually plans, and how many of each. A count of nothing
 *  is worth seeing too: 0 hidden on a page with name columns means the lists are
 *  about to be packed, not dropped. */
function PlanLegend({
  rects,
  hidden,
  onToggle,
}: {
  rects: PlannedRect[];
  hidden: Set<string>;
  onToggle: (role: string) => void;
}) {
  const counts = new Map<string, number>();
  for (const rect of rects) counts.set(rect.role, (counts.get(rect.role) || 0) + 1);
  if (!counts.size) return null;
  const order = ["map", "pin", "other", "list", "line", "title", "hide"];
  const roles = [...counts.keys()].sort(
    (a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99)
  );
  return (
    <div className="plan-legend">
      {roles.map((role) => (
        <button
          key={role}
          type="button"
          // 138 pins drown the handful of boxes worth looking at, so the legend
          // doubles as the filter rather than adding a second row of controls.
          className={`plan-key role-${role}${hidden.has(role) ? " off" : ""}`}
          aria-pressed={!hidden.has(role)}
          title={hidden.has(role) ? `Show ${role}` : `Hide ${role}`}
          onClick={() => onToggle(role)}
        >
          {role} {counts.get(role)}
        </button>
      ))}
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
  // Whether an opened group lists every page or only the selected ones.
  const [openScope, setOpenScope] = useState<"all" | "selected">("all");
  const [groupPage, setGroupPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [previewing, setPreviewing] = useState<Record<number, number>>({});
  // On by default: the whole point of opening a page is to see what the run does
  // to it, and the boxes are the only part of that the crop cannot show.
  const [showPlan, setShowPlan] = useState(true);
  // Pins outnumber everything else forty to one on a report card, so they start
  // hidden: the boxes exist to show the objects a crop cannot explain.
  const [hiddenRoles, setHiddenRoles] = useState<Set<string>>(new Set(["pin"]));
  // Drag across thumbnails to select a run of them. `adding` is fixed at
  // pointer-down from whatever the first thumbnail was, so one drag either selects
  // or deselects throughout instead of toggling each chip it crosses.
  const [drag, setDrag] = useState<{ adding: boolean } | null>(null);

  const byCategory = useMemo(() => {
    const out: Record<Category, FramingPage[]> = {
      matched: [],
      fitted: [],
      template: [],
      reviewed: [],
    };
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

  /**
   * Confirm, defer, or undo — not "move to bucket".
   *
   * Good fit and Fitted content are outcomes rather than choices, so there is no
   * honest way to put a page in one by clicking. Unconfirming returns it to auto
   * and the outcome decides which of the two it lands in.
   */
  function actOnSelected(action: "confirm" | "defer" | "unconfirm") {
    const indexes = [...selected];
    if (!indexes.length) return;
    if (action === "defer") decide(indexes, "deferred", () => null);
    else if (action === "unconfirm") decide(indexes, "auto", () => null);
    else decide(indexes, "pinned", (p) => chosenSlide(p, decisions) ?? p.autoTemplateSlide);
    setSelected(new Set());
  }

  function applySelection(index: number, adding: boolean) {
    setSelected((current) => {
      if (current.has(index) === adding) return current;
      const next = new Set(current);
      if (adding) next.add(index);
      else next.delete(index);
      return next;
    });
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
          {TABS.map((key) => (
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
              <span className="note">{selected.size} selected</span>
              {tab !== "template" && (
                <button
                  className="btn secondary tone-template"
                  type="button"
                  disabled={busy}
                  onClick={() => actOnSelected("defer")}
                >
                  New template
                </button>
              )}
              {tab !== "reviewed" && (
                <button
                  className="btn secondary tone-reviewed"
                  type="button"
                  disabled={busy}
                  onClick={() => actOnSelected("confirm")}
                >
                  Confirm selected
                </button>
              )}
              {tab === "reviewed" && (
                <button
                  className="btn secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => actOnSelected("unconfirm")}
                >
                  Unconfirm selected
                </button>
              )}
              <button className="btn secondary" type="button" onClick={() => setSelected(new Set())}>
                Clear selection
              </button>
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
        const chosenPages = group.pages.filter((p) => selected.has(p.index));
        const scoped = open && openScope === "selected" && chosenPages.length > 0;
        const listed = scoped ? chosenPages : group.pages;
        const start = open ? groupPage * pageSize : 0;
        const shown = open ? listed.slice(start, start + pageSize) : [];
        const totalPages = Math.max(1, Math.ceil(listed.length / pageSize));
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
                without opening anything. Drag across them to select a run. */}
            <div
              className="framing-strip"
              onPointerUp={() => setDrag(null)}
              onPointerLeave={() => setDrag(null)}
            >
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
                    onPointerDown={(e) => {
                      // Keep receiving moves after the pointer leaves this chip,
                      // otherwise the drag stops at the first boundary.
                      e.currentTarget.releasePointerCapture?.(e.pointerId);
                      const adding = !selected.has(page.index);
                      setDrag({ adding });
                      applySelection(page.index, adding);
                    }}
                    onPointerEnter={() => {
                      if (drag) applySelection(page.index, drag.adding);
                    }}
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
              {/* Selecting is the first half of confirming a group: the act that
                  changes a decision lives in one place, the pinned bar, so there
                  is no second path that behaves subtly differently. */}
              <button
                className="btn secondary tone-reviewed"
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
                {group.pages.every((p) => selected.has(p.index))
                  ? `Deselect ${group.pages.length}`
                  : `Select all ${group.pages.length}`}
              </button>
              <button
                className="btn secondary"
                type="button"
                onClick={() => {
                  setOpenGroup(open ? null : group.key);
                  setOpenScope(chosenPages.length > 0 ? "selected" : "all");
                  setGroupPage(0);
                }}
              >
                {open
                  ? "Hide pages"
                  : chosenPages.length > 0
                    ? `Open selected (${chosenPages.length})`
                    : `Open pages (${group.pages.length})`}
              </button>
              {scoped && (
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => {
                    setOpenScope("all");
                    setGroupPage(0);
                  }}
                >
                  Show all {group.pages.length}
                </button>
              )}
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
                      <span className="outline-num framing-row-num">{page.slide}</span>
                      <div className="framing-row-body">
                        {/* The wall slide whole, so the crop below can be judged
                            against what it came from rather than in isolation. */}
                        {thumbUrl(page) && (
                          <div className="framing-before">
                            <span className="framing-label">Before — full wall</span>
                            <img src={thumbUrl(page)!} alt="" />
                          </div>
                        )}
                        <div className="framing-after">
                          <div>
                            <span className="framing-label">
                              After — template slide {preview ?? "—"}
                              <label className="plan-toggle">
                                <input
                                  type="checkbox"
                                  checked={showPlan}
                                  onChange={(event) => setShowPlan(event.target.checked)}
                                />
                                where objects land
                              </label>
                            </span>
                            <CropPreview
                              src={thumbUrl(page)}
                              transform={transformFor(page, preview)}
                              rects={
                                showPlan
                                  ? rectsFor(page, preview).filter((r) => !hiddenRoles.has(r.role))
                                  : undefined
                              }
                              wallWidth={wallWidth}
                              destWidth={destWidth}
                              destHeight={destHeight}
                              width={440}
                              title={`Slide ${page.slide} as template slide ${preview}`}
                            />
                            {showPlan && (
                              <PlanLegend
                                rects={rectsFor(page, preview)}
                                hidden={hiddenRoles}
                                onToggle={(role) =>
                                  setHiddenRoles((cur) => {
                                    const next = new Set(cur);
                                    if (next.has(role)) next.delete(role);
                                    else next.add(role);
                                    return next;
                                  })
                                }
                              />
                            )}
                          </div>
                          {/* Each option shows what that framing does to *this*
                              page, not what the template slide looks like. Same
                              cached image throughout, so thirteen of them cost one
                              request and re-render instantly. */}
                          <div className="framing-picker">
                            {page.candidates.map((candidate) => (
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
                                <CropPreview
                                  src={thumbUrl(page)}
                                  transform={candidate.transform}
                                  wallWidth={wallWidth}
                                  destWidth={destWidth}
                                  destHeight={destHeight}
                                  width={104}
                                />
                                <span className="framing-option-num">
                                  {candidate.templateSlide} · {candidate.fit.toFixed(2)}
                                </span>
                                {/* The template slide behind this option, on hover:
                                    the option shows the result, this shows the frame
                                    that produced it. */}
                                {templateThumbUrl(candidate.templateSlide) && (
                                  <span className="option-tip">
                                    <img src={templateThumbUrl(candidate.templateSlide)!} alt="" />
                                    <span className="option-tip-label">
                                      Template slide {candidate.templateSlide}
                                    </span>
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      <div className="framing-row-controls">
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
