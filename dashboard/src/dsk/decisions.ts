/** Pure logic for the DSK Generator's per-slide review list. No React, no fetch.
 * Mirrors the real API contract: `POST /api/dsk/{id}/decisions` takes
 * `{decisions: [{slide, include, action, anchor, keepSide, clip}]}` — a LIST, not a map
 * keyed by slide. `DecisionsMap` below is only a client-side convenience for editing;
 * `toDecisionsPayload` flattens it back to the list the API expects.
 */

export type DskAnchor = "auto" | "centre" | "left" | "right";

export type DskDecision = {
  slide: number;
  include: boolean;
  action: string;
  anchor: string;
  keepSide: boolean;
  clip: string | null;
};

export type DskPage = {
  slide: number;
  category: string;
  isText: boolean;
  needsClip: boolean;
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
  if (page.decision) return { ...page.decision };
  return {
    slide: page.slide,
    include: !page.isText,
    action: page.needsClip ? "both" : "in_deck",
    anchor: "auto",
    keepSide: false,
    clip: null,
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

/** Shape expected by `POST /api/dsk/{id}/decisions` and `/apply`: a list, keyed by nothing. */
export function toDecisionsPayload(map: DecisionsMap): DskDecision[] {
  return Object.values(map).sort((a, b) => a.slide - b.slide);
}
