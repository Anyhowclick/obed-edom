import { useEffect, useMemo, useState } from "react";
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
  /** The part of the wall this object occupies, for cutting it out. */
  sx?: number;
  sy?: number;
  sw?: number;
  sh?: number;
  /** False for anything the run deletes before output — a hidden duplicate or
   *  dropped side-panel object. Keyed off the plan, not the role string, so a
   *  whitelisted page's kept lists read as staying, not leaving. */
  willBeInOutput?: boolean;
};

/** boxes: the wall cropped by one affine, with each object's landing spot
 *  outlined on top — the badge on its slot, the lists repacked, the objects the
 *  run hides. composite: each object cut from the wall and drawn where it lands,
 *  which replaces the crop rather than layering on it, because otherwise every
 *  object shows twice, once where the affine put it and once where the plan
 *  puts it. */
export type PlanView = "boxes" | "composite";

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
  /** Document positions of slides set to Skip Slide in Keynote. */
  skippedSlides?: number[];
  /** How those positions read against Keynote's navigator, if they differ. */
  numberingNote?: string;
};

type Category = "matched" | "fitted" | "template" | "reviewed";

const CATEGORY_LABEL: Record<Category, string> = {
  matched: "Good fit",
  fitted: "Scaled Fit",
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

/** Whether the framing this page will use fails, leaving it scaled to the frame. */
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
 * applies cleanly moves it out of Scaled Fit by itself.
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
  view = "boxes",
  wallWidth,
  wallHeight,
  destWidth,
  destHeight,
  width,
  title,
}: {
  src?: string | null;
  transform?: FramingTransform | null;
  rects?: PlannedRect[];
  view?: PlanView;
  wallWidth: number;
  wallHeight: number;
  destWidth: number;
  destHeight: number;
  width: number;
  title?: string;
}) {
  const k = width / destWidth;
  const height = Math.round(destHeight * k);
  const composite = view === "composite" && !!src;
  return (
    <div className="crop-preview" style={{ width, height }} title={title}>
      {src && transform && !composite ? (
        <img
          src={src}
          alt=""
          style={{
            left: transform.tx * k,
            top: transform.ty * k,
            width: wallWidth * transform.s * k,
          }}
        />
      ) : composite ? null : (
        <span className="crop-empty">no preview</span>
      )}
      {composite &&
        (rects || []).map((rect, i) => {
          // A dropped object is drawn by not drawing it — that is the whole point
          // of showing this instead of the crop. Keyed on the plan's flag, not the
          // role, so it also omits anything else the run deletes before output.
          if (rect.willBeInOutput === false) return null;
          if (!rect.sw || !rect.sh || rect.w <= 0 || rect.h <= 0) return null;
          const zx = rect.w / rect.sw;
          const zy = rect.h / rect.sh;
          return (
            <span
              key={i}
              className="plan-piece"
              style={{ left: rect.x * k, top: rect.y * k, width: rect.w * k, height: rect.h * k }}
            >
              <img
                src={src!}
                alt=""
                style={{
                  left: -(rect.sx || 0) * zx * k,
                  top: -(rect.sy || 0) * zy * k,
                  width: wallWidth * zx * k,
                  height: wallHeight * zy * k,
                }}
              />
            </span>
          );
        })}
      {view === "boxes" &&
        (rects || []).map((rect, i) => (
          <span
            key={i}
            // `dropped` is keyed on the plan's willBeInOutput, not the role: an
            // object the run deletes before output is drawn as leaving (ghosted +
            // struck), so ~200 dropped objects no longer read as landing there.
            className={`plan-rect role-${rect.role}${
              rect.willBeInOutput === false ? " dropped" : ""
            }`}
            title={`${rect.role} · ${rect.kind}${rect.text ? ` · ${rect.text}` : ""}${
              rect.willBeInOutput === false ? " · will be removed" : ""
            }`}
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

type Marquee = {
  key: string;
  box: { x0: number; y0: number; x1: number; y1: number };
  /** Set once the pointer has moved far enough to mean a sweep rather than a
   *  click, so pressing a chip still just toggles it. */
  active: boolean;
  /** Selection as it stood when the drag began, so a live sweep replaces its own
   *  result each move instead of accumulating one. */
  base: Set<number>;
  /** Whether this sweep takes pages out of the selection instead of adding them.
   *  Null until the sweep has touched a chip to decide from. */
  removing: boolean | null;
  /** The chip the press landed on, if any. A press that never becomes a sweep
   *  toggles it on release. */
  from: number | null;
};

function marqueeRect(box: Marquee["box"]) {
  return {
    left: Math.min(box.x0, box.x1),
    top: Math.min(box.y0, box.y1),
    width: Math.abs(box.x1 - box.x0),
    height: Math.abs(box.y1 - box.y0),
  };
}

/** Chip indexes the box touches, read off layout rather than tracked per chip. */
function indexesUnder(strip: HTMLElement, box: Marquee["box"]): number[] {
  const { left, top, width, height } = marqueeRect(box);
  const right = left + width;
  const bottom = top + height;
  const out: number[] = [];
  for (const node of Array.from(strip.querySelectorAll<HTMLElement>("[data-page-index]"))) {
    const x = node.offsetLeft;
    const y = node.offsetTop;
    if (x < right && x + node.offsetWidth > left && y < bottom && y + node.offsetHeight > top) {
      out.push(Number(node.dataset.pageIndex));
    }
  }
  return out;
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
  const wallHeight = proposal.wallHeight || 1080;
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
  const [planView, setPlanView] = useState<PlanView>("boxes");
  // Pins outnumber everything else forty to one on a report card, so they start
  // hidden: the boxes exist to show the objects a crop cannot explain.
  const [hiddenRoles, setHiddenRoles] = useState<Set<string>>(new Set(["pin"]));
  // Sweep a box anywhere over the strip to take a block of pages; a press that
  // does not move is still just a click on that chip. Starting only from the
  // strip's empty space, as this first did, meant the obvious gesture — press a
  // chip and drag — never began a sweep at all.
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  // Filters that narrow every category tab at once: only whitelisted pages, and/or
  // only pages whose chosen framing uses one template slide. "all" = filter off.
  const [keptOnly, setKeptOnly] = useState(false);
  const [templateFilter, setTemplateFilter] = useState<string>("all");

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

  // Distinct chosen-framing keys present across the deck, for the template <select>.
  // "none" collects pages with no chosen slide (deferred, or auto with no usable
  // framing) — the same key `groups` uses.
  const templateOptions = useMemo(() => {
    const keys = new Set<string>();
    for (const page of pages) {
      const slide = chosenSlide(page, decisions);
      keys.add(slide == null ? "none" : String(slide));
    }
    return [...keys].sort((a, b) => {
      if (a === "none") return 1;
      if (b === "none") return -1;
      return Number(a) - Number(b);
    });
  }, [pages, decisions]);

  // If the pinned/chosen slide behind an active template filter disappears (e.g. the
  // last page using it is unpinned), drop back to "all" rather than stranding every
  // tab at zero.
  useEffect(() => {
    if (templateFilter !== "all" && !templateOptions.includes(templateFilter)) {
      setTemplateFilter("all");
    }
  }, [templateOptions, templateFilter]);

  const passesFilter = (page: FramingPage): boolean => {
    if (keptOnly && !keepsSideContent(page)) return false;
    if (templateFilter !== "all") {
      const slide = chosenSlide(page, decisions);
      if ((slide == null ? "none" : String(slide)) !== templateFilter) return false;
    }
    return true;
  };

  const filteredByCategory = useMemo(() => {
    const out = {} as Record<Category, FramingPage[]>;
    for (const key of TABS) out[key] = byCategory[key].filter(passesFilter);
    return out;
  }, [byCategory, keptOnly, templateFilter, decisions]);

  const groups = useMemo(() => {
    const map = new Map<string, FramingPage[]>();
    for (const page of filteredByCategory[tab]) {
      const key = String(chosenSlide(page, decisions) ?? "none");
      const list = map.get(key);
      if (list) list.push(page);
      else map.set(key, [page]);
    }
    return [...map.entries()]
      .map(([key, list]) => ({ key, slide: key === "none" ? null : Number(key), pages: list }))
      .sort((a, b) => b.pages.length - a.pages.length);
  }, [filteredByCategory, tab, decisions]);

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
        // Seed from the existing answer (local, or the one the server carried onto
        // the page) so a whitelist set separately survives a framing change; only
        // state and templateSlide are overwritten.
        next[index] = { ...(current[index] ?? page.decision), wallIndex: index, state, templateSlide: slide };
      }
      return next;
    });
  }

  /** Whether this page currently keeps its side-panel content. */
  function keepsSideContent(page: FramingPage): boolean {
    return !!(decisions[page.index] ?? page.decision)?.keepSideContent;
  }

  /** Set the side-content whitelist on pages without touching their framing state. */
  function toggleSideContent(indexes: number[], keep: boolean) {
    setDecisions((current) => {
      const next = { ...current };
      for (const index of indexes) {
        const page = pages.find((p) => p.index === index);
        if (!page) continue;
        const base = current[index] ?? page.decision ?? { wallIndex: index, state: "auto" as const, templateSlide: null };
        next[index] = { ...base, wallIndex: index, keepSideContent: keep };
      }
      return next;
    });
  }

  /**
   * Confirm, defer, or undo — not "move to bucket".
   *
   * Good fit and Scaled Fit are outcomes rather than choices, so there is no
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
      // A page kept on auto but whitelisted for side content is still a real
      // decision, so it must be sent even though its framing is automatic.
      .filter((d): d is FramingDecision => !!d && (d.state !== "auto" || !!d.keepSideContent));
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
              {CATEGORY_LABEL[key]} ({filteredByCategory[key].length})
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
              <button
                className="btn secondary"
                type="button"
                disabled={busy}
                title="Keep the LED-wall side-panel content on the selected pages (dropped everywhere else)"
                onClick={() => { toggleSideContent([...selected], true); setSelected(new Set()); }}
              >
                Keep side panels
              </button>
              <button
                className="btn secondary"
                type="button"
                disabled={busy}
                title="Drop the side-panel content on the selected pages (the default)"
                onClick={() => { toggleSideContent([...selected], false); setSelected(new Set()); }}
              >
                Drop side panels
              </button>
              <button
                className="btn secondary tone-clear"
                type="button"
                onClick={() => setSelected(new Set())}
              >
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

      <div className="framing-filter">
        <span className="framing-filter-icon" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M1.5 2h13a.5.5 0 0 1 .4.8L10 9.2V14a.5.5 0 0 1-.72.45l-3-1.5A.5.5 0 0 1 6 12.5V9.2L1.1 2.8A.5.5 0 0 1 1.5 2Z" />
          </svg>
        </span>
        <span className="framing-filter-label">Filter</span>
        <button
          type="button"
          className={"btn secondary" + (keptOnly ? " on tone-reviewed" : "")}
          aria-pressed={keptOnly}
          title="Show only pages whose LED-wall side-panel content is whitelisted to be kept"
          onClick={() => { setKeptOnly((v) => !v); setSelected(new Set()); setOpenGroup(null); setGroupPage(0); }}
        >
          Side panels kept
        </button>
        <label className="field inline-field">
          Template
          <select
            value={templateFilter}
            onChange={(e) => { setTemplateFilter(e.target.value); setSelected(new Set()); setOpenGroup(null); setGroupPage(0); }}
          >
            <option value="all">All</option>
            {templateOptions.map((key) => (
              <option key={key} value={key}>
                {key === "none" ? "Needs a new template slide" : `Slide ${key}`}
              </option>
            ))}
          </select>
        </label>
        {(keptOnly || templateFilter !== "all") && (
          <button
            type="button"
            className="btn secondary tone-clear"
            onClick={() => { setKeptOnly(false); setTemplateFilter("all"); }}
          >
            Clear filter
          </button>
        )}
      </div>

      <p className="note">
        {pages.length} page{pages.length === 1 ? "" : "s"} take a framing. {reviewed} reviewed,{" "}
        {byCategory.template.length} waiting on a new template slide.
        {proposal.templateChanged && (proposal.resurfaced?.length ?? 0) > 0 &&
          ` The template changed, so ${proposal.resurfaced!.length} deferred page(s) can now use a new framing.`}
      </p>

      {/* Before the apply, because the apply is the step that cannot be taken
          back. A range typed off Keynote's navigator selects different pages
          from the ones it names here, and nothing else would say so. */}
      {proposal.numberingNote && (
        <p className="danger-note">
          <strong>Check the slide range.</strong> {proposal.numberingNote} Un-hiding a
          slide while a proposal is open shifts the mapping under it, so re-propose
          if you do.
        </p>
      )}

      {groups.length === 0 && (
        <p className="note">
          {keptOnly || templateFilter !== "all"
            ? `No ${CATEGORY_LABEL[tab].toLowerCase()} pages match the filter.`
            : `Nothing in ${CATEGORY_LABEL[tab].toLowerCase()}.`}
        </p>
      )}

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
                  {fellBack > 0 && ` · ${fellBack} scaled to fit`}
                  {fellBack === 0 && group.slide != null && " · all matched this framing"}
                </span>
              </p>
            </div>

            {/* Every page in the group, so a wrong one in a batch of 56 is visible
                without opening anything. Click a chip to toggle it, or sweep a box
                across them to take a block that wraps rows. A sweep adds to what
                is already selected rather than replacing it, so the two compose,
                and a sweep whose first chip is already selected takes pages back
                out instead. Alt forces that from anywhere. */}
            <div
              className="framing-strip"
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                // Otherwise the browser starts a text/image drag mid-sweep.
                e.preventDefault();
                const strip = e.currentTarget;
                const rect = strip.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                strip.setPointerCapture?.(e.pointerId);
                const chip = (e.target as HTMLElement).closest?.("[data-page-index]");
                const from = chip ? Number((chip as HTMLElement).dataset.pageIndex) : null;
                setMarquee({
                  key: group.key,
                  box: { x0: x, y0: y, x1: x, y1: y },
                  active: false,
                  from,
                  // A sweep works on top of whatever is already selected rather
                  // than replacing it, so it composes with picking chips one by
                  // one, and it takes pages back out when the first chip it meets
                  // is already selected — the same read as dragging across them.
                  // Starting on empty space leaves that undecided until the sweep
                  // reaches a chip, because a press on nothing says nothing about
                  // which way it is going. Alt settles it up front.
                  base: new Set(selected),
                  removing: e.altKey ? true : from != null ? selected.has(from) : null,
                });
              }}
              onPointerMove={(e) => {
                if (!marquee || marquee.key !== group.key) return;
                const strip = e.currentTarget;
                const rect = strip.getBoundingClientRect();
                const box = {
                  ...marquee.box,
                  x1: e.clientX - rect.left,
                  y1: e.clientY - rect.top,
                };
                const moved =
                  Math.abs(box.x1 - box.x0) > 4 || Math.abs(box.y1 - box.y0) > 4;
                if (!moved && !marquee.active) {
                  setMarquee({ ...marquee, box });
                  return;
                }
                const hits = indexesUnder(strip, box);
                const removing =
                  marquee.removing ?? (hits.length ? marquee.base.has(hits[0]) : null);
                setMarquee({ ...marquee, box, active: true, removing });
                const next = new Set(marquee.base);
                for (const index of hits) {
                  if (removing) next.delete(index);
                  else next.add(index);
                }
                setSelected(next);
              }}
              onPointerUp={() => {
                // Capturing the pointer on the strip moves the click that would
                // follow off the chip, so the toggle has to happen here rather
                // than in an onClick that never fires.
                if (marquee && !marquee.active && marquee.from != null) {
                  applySelection(marquee.from, !selected.has(marquee.from));
                }
                setMarquee(null);
              }}
              onPointerCancel={() => setMarquee(null)}
            >
              {group.pages.map((page) => {
                const isSelected = selected.has(page.index);
                return (
                  <button
                    key={page.slide}
                    type="button"
                    data-page-index={page.index}
                    className={
                      "framing-chip" +
                      (isSelected ? " selected" : "") +
                      // Tracks the framing the page will use, so switching one to a
                      // clean framing turns its border green immediately.
                      (fellBackWith(page, chosenSlide(page, decisions)) ? " fellback" : "") +
                      (keepsSideContent(page) ? " kept" : "")
                    }
                    title={
                      `Slide ${page.slide}` +
                      (fellBackWith(page, chosenSlide(page, decisions))
                        ? " — no framing fit, so it is scaled to the frame"
                        : "") +
                      (keepsSideContent(page) ? " · side panels kept" : "")
                    }
                  >
                    <CropPreview
                      src={thumbUrl(page)}
                      transform={transformFor(page, chosenSlide(page, decisions))}
                      // Where objects land, not the bare crop: a chip should show
                      // the badge on its slot and the lists repacked. Pins are
                      // dropped — 138 of them bury the boxes worth seeing, the way
                      // the full view hides them by default.
                      rects={rectsFor(page, chosenSlide(page, decisions)).filter(
                        (r) => r.role !== "pin"
                      )}
                      wallWidth={wallWidth}
                      wallHeight={wallHeight}
                      destWidth={destWidth}
                      destHeight={destHeight}
                      width={104}
                    />
                    <span className="framing-chip-num">{page.slide}</span>
                  </button>
                );
              })}
              {marquee?.active && marquee.key === group.key && (
                <span
                  className={`framing-marquee${marquee.removing ? " removing" : ""}`}
                  style={marqueeRect(marquee.box)}
                />
              )}
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
                              <span className="plan-modes">
                                {(
                                  [
                                    ["boxes", "where objects land"],
                                    ["composite", "as it will look"],
                                  ] as [PlanView, string][]
                                ).map(([mode, label]) => (
                                  <button
                                    key={mode}
                                    type="button"
                                    className={planView === mode ? "current" : ""}
                                    aria-pressed={planView === mode}
                                    onClick={() => setPlanView(mode)}
                                  >
                                    {label}
                                  </button>
                                ))}
                              </span>
                            </span>
                            <CropPreview
                              src={thumbUrl(page)}
                              transform={transformFor(page, preview)}
                              view={planView}
                              rects={
                                planView === "composite"
                                  ? rectsFor(page, preview)
                                  : rectsFor(page, preview).filter((r) => !hiddenRoles.has(r.role))
                              }
                              wallWidth={wallWidth}
                              wallHeight={wallHeight}
                              destWidth={destWidth}
                              destHeight={destHeight}
                              width={440}
                              title={`Slide ${page.slide} as template slide ${preview}`}
                            />
                            {planView === "boxes" && (
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
                                // The tip is far wider than the chip, so one at
                                // the end of a row is cut off by the panel. Which
                                // chips those are depends on where the row wraps,
                                // which only layout knows — hence measuring here
                                // rather than a :nth-child rule.
                                onMouseEnter={(event) => {
                                  const chip = event.currentTarget;
                                  const strip = chip.parentElement;
                                  if (!strip) return;
                                  const tip = chip.querySelector<HTMLElement>(".option-tip");
                                  const width = tip?.offsetWidth || 330;
                                  chip.classList.toggle(
                                    "tip-left",
                                    chip.offsetLeft + width > strip.clientWidth
                                  );
                                }}
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
                                  rects={(candidate.rects ?? []).filter(
                                    (r) => r.role !== "pin"
                                  )}
                                  wallWidth={wallWidth}
                                  wallHeight={wallHeight}
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
                          {/* Confirms as well as switches. Gating this on the
                              preview differing from the current choice meant a
                              page whose automatic framing was already right
                              could not be reviewed from its own row at all. */}
                          <button
                            className="btn secondary tone-alt"
                            type="button"
                            disabled={busy || (preview ?? page.autoTemplateSlide) == null}
                            onClick={() =>
                              decide(
                                [page.index],
                                "pinned",
                                (p) => preview ?? p.autoTemplateSlide
                              )
                            }
                          >
                            {differs ? "Use this framing" : "Confirm this framing"}
                          </button>
                          <button
                            className="btn secondary tone-template"
                            type="button"
                            disabled={busy}
                            onClick={() => decide([page.index], "deferred", () => null)}
                          >
                            Needs a new template
                          </button>
                          <label className="check" title="Keep this page's LED-wall side-panel content instead of dropping it (the default)">
                            <input
                              type="checkbox"
                              checked={keepsSideContent(page)}
                              disabled={busy}
                              onChange={(e) => toggleSideContent([page.index], e.target.checked)}
                            />
                            <span>Keep side panels</span>
                          </label>
                        </div>
                        <p className="note">
                          {`Template slide ${preview ?? "—"}. `}
                          {previewFalls
                            ? "This framing does not fit, so the page is scaled to the frame. "
                            : "This framing applies cleanly. "}
                          {stateOf(page, decisions) === "pinned" && "Reviewed. "}
                          {keepsSideContent(page) && "Side panels kept. "}
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
