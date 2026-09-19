/** Pure logic for the DSK Generator's per-slide review list. No React, no fetch.
 * Mirrors the real API contract: `POST /api/dsk/{id}/decisions` takes
 * `{decisions: [{slide, include, action, anchor, keepSide, clip, videosOnly}]}` — a LIST,
 * not a map keyed by slide. `DecisionsMap` below is only a client-side convenience for
 * editing; `toDecisionsPayload` flattens it back to the list the API expects.
 */

export type DskAnchor = "auto" | "centre" | "left" | "right";

export type DskDecision = {
  slide: number;
  include: boolean;
  action: string;
  anchor: string;
  keepSide: boolean;
  clip: string | null;
  videosOnly: boolean;
};

export type DskPage = {
  slide: number;
  category: string;
  isText: boolean;
  needsClip: boolean;
  canVideosOnly?: boolean;
  stackedMovies?: boolean;
  decision?: DskDecision | null;
};

export type DecisionsMap = Record<number, DskDecision>;

/** Movie-bearing categories need a clip file before the slide can go into the deck. */
export function needsClip(page: DskPage): boolean {
  return page.needsClip;
}

/** A skipped (text) slide is never included by default; everything else is,
 * matching `_dsk_decision_defaults` in `web/app.py`. */
export function defaultDecision(page: DskPage): DskDecision {
  if (page.decision) return { ...page.decision, videosOnly: !!page.decision.videosOnly };
  return {
    slide: page.slide,
    include: !page.isText,
    action: page.needsClip ? "both" : "in_deck",
    anchor: "auto",
    keepSide: false,
    clip: null,
    videosOnly: false,
  };
}

export function buildDecisionsMap(pages: DskPage[]): DecisionsMap {
  const map: DecisionsMap = {};
  for (const page of pages) map[page.slide] = defaultDecision(page);
  return map;
}

/** A text-slide can never be included, no matter what the operator (or a stale payload) says. */
export function setInclude(map: DecisionsMap, pages: DskPage[], slide: number, include: boolean): DecisionsMap {
  const page = pages.find((p) => p.slide === slide);
  const allowed = page?.isText ? false : include;
  const current = map[slide] || defaultDecision(page || { slide, category: "", isText: false, needsClip: false });
  return { ...map, [slide]: { ...current, include: allowed } };
}

export function setClip(map: DecisionsMap, pages: DskPage[], slide: number, clip: string | null): DecisionsMap {
  const page = pages.find((p) => p.slide === slide);
  const current = map[slide] || defaultDecision(page || { slide, category: "", isText: false, needsClip: false });
  return { ...map, [slide]: { ...current, clip } };
}

export function setAnchor(map: DecisionsMap, pages: DskPage[], slide: number, anchor: DskAnchor): DecisionsMap {
  const page = pages.find((p) => p.slide === slide);
  const current = map[slide] || defaultDecision(page || { slide, category: "", isText: false, needsClip: false });
  return { ...map, [slide]: { ...current, anchor } };
}

export function setKeepSide(map: DecisionsMap, pages: DskPage[], slide: number, keepSide: boolean): DecisionsMap {
  const page = pages.find((p) => p.slide === slide);
  const current = map[slide] || defaultDecision(page || { slide, category: "", isText: false, needsClip: false });
  return { ...map, [slide]: { ...current, keepSide } };
}

/** Videos-only is only offered where the backend said the slide can take it
 * (`canVideosOnly`); anywhere else it is pinned false, mirroring `_apply_dsk_decisions`. */
export function setVideosOnly(map: DecisionsMap, pages: DskPage[], slide: number, videosOnly: boolean): DecisionsMap {
  const page = pages.find((p) => p.slide === slide);
  const allowed = page?.canVideosOnly ? videosOnly : false;
  const current = map[slide] || defaultDecision(page || { slide, category: "", isText: false, needsClip: false });
  return { ...map, [slide]: { ...current, videosOnly: allowed } };
}

/** Bulk include/exclude over a set of slides, respecting the text-slide invariant. */
export function bulkInclude(map: DecisionsMap, pages: DskPage[], slides: number[], include: boolean): DecisionsMap {
  let next = map;
  for (const slide of slides) next = setInclude(next, pages, slide, include);
  return next;
}

export function bulkKeepSide(map: DecisionsMap, pages: DskPage[], slides: number[], keepSide: boolean): DecisionsMap {
  let next = map;
  for (const slide of slides) next = setKeepSide(next, pages, slide, keepSide);
  return next;
}

export function bulkAnchor(map: DecisionsMap, pages: DskPage[], slides: number[], anchor: DskAnchor): DecisionsMap {
  let next = map;
  for (const slide of slides) next = setAnchor(next, pages, slide, anchor);
  return next;
}

export function bulkVideosOnly(map: DecisionsMap, pages: DskPage[], slides: number[], videosOnly: boolean): DecisionsMap {
  let next = map;
  for (const slide of slides) next = setVideosOnly(next, pages, slide, videosOnly);
  return next;
}

/** Slides the operator has kept, i.e. the set a bulk control should touch. */
export function includedSlides(map: DecisionsMap, pages: DskPage[]): number[] {
  return pages.filter((p) => (map[p.slide] || defaultDecision(p)).include).map((p) => p.slide);
}

export type DskGroup<P extends DskPage = DskPage> = { key: string; label: string; pages: P[] };

const GROUP_ORDER = ["movie", "mixed", "built", "static"];
const GROUP_LABELS: Record<string, string> = {
  movie: "Movie",
  mixed: "Mixed (movie + stills)",
  built: "Built",
  static: "Static",
  text: "Text — skipped",
};

/** Groups the review rows the way the CG resizer groups pages: the ones needing
 * attention (movies, which want a clip and may want videos-only) first, text last. */
export function groupPages<P extends DskPage>(pages: P[]): DskGroup<P>[] {
  const groups = new Map<string, P[]>();
  for (const page of pages) {
    const key = page.isText ? "text" : page.category || "other";
    const bucket = groups.get(key);
    if (bucket) bucket.push(page);
    else groups.set(key, [page]);
  }
  const rank = (key: string) => {
    const index = GROUP_ORDER.indexOf(key);
    if (index >= 0) return index;
    return key === "text" ? GROUP_ORDER.length + 1 : GROUP_ORDER.length;
  };
  return [...groups.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))
    .map(([key, rows]) => ({ key, label: GROUP_LABELS[key] || key, pages: rows }));
}

/** Shape expected by `POST /api/dsk/{id}/decisions` and `/apply`: a list, keyed by nothing. */
export function toDecisionsPayload(map: DecisionsMap): DskDecision[] {
  return Object.values(map).sort((a, b) => a.slide - b.slide);
}
