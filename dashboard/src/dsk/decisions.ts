/** Pure logic for the DSK Generator's per-slide review list. No React, no fetch. */

export type SlideAnchor = "centre" | "left" | "right";

export type SlidePage = {
  number: number;
  class: string;
  skipped: boolean;
  thumbnail?: string;
};

export type SlideDecision = {
  include: boolean;
  clip?: string;
  anchor?: SlideAnchor;
  keepSide?: boolean;
};

export type DecisionsMap = Record<number, SlideDecision>;

/** Movie-bearing classes need a clip file before the slide can go into the deck. */
export function needsClip(page: SlidePage): boolean {
  return page.class === "movie" || page.class === "mixed";
}

/** A skipped (text) slide is never included by default; everything else is. */
export function defaultDecision(page: SlidePage): SlideDecision {
  return { include: !page.skipped };
}

export function buildDecisionsMap(slides: SlidePage[]): DecisionsMap {
  const map: DecisionsMap = {};
  for (const page of slides) map[page.number] = defaultDecision(page);
  return map;
}

/** A skipped slide can never be included, no matter what the operator (or a stale payload) says. */
export function setInclude(map: DecisionsMap, slides: SlidePage[], number: number, include: boolean): DecisionsMap {
  const page = slides.find((p) => p.number === number);
  const allowed = page?.skipped ? false : include;
  const current = map[number] || defaultDecision(page || { number, class: "", skipped: false });
  return { ...map, [number]: { ...current, include: allowed } };
}

export function setClip(map: DecisionsMap, number: number, clip: string | undefined): DecisionsMap {
  const current = map[number] || { include: true };
  return { ...map, [number]: { ...current, clip } };
}

export function setAnchor(map: DecisionsMap, number: number, anchor: SlideAnchor | undefined): DecisionsMap {
  const current = map[number] || { include: true };
  return { ...map, [number]: { ...current, anchor } };
}

export function setKeepSide(map: DecisionsMap, number: number, keepSide: boolean): DecisionsMap {
  const current = map[number] || { include: true };
  return { ...map, [number]: { ...current, keepSide } };
}

/** Bulk include/exclude over a set of slides, respecting the skipped invariant. */
export function bulkInclude(map: DecisionsMap, slides: SlidePage[], numbers: number[], include: boolean): DecisionsMap {
  let next = map;
  for (const number of numbers) next = setInclude(next, slides, number, include);
  return next;
}

export function bulkKeepSide(map: DecisionsMap, numbers: number[], keepSide: boolean): DecisionsMap {
  let next = map;
  for (const number of numbers) next = setKeepSide(next, number, keepSide);
  return next;
}

export type DecisionsPayload = { slides: Record<string, SlideDecision> };

/** Shape expected by `POST /api/dsk/{id}/decisions`: `{slides: {[number]: decision}}`. */
export function toDecisionsPayload(map: DecisionsMap): DecisionsPayload {
  const slides: Record<string, SlideDecision> = {};
  for (const [number, decision] of Object.entries(map)) slides[number] = decision;
  return { slides };
}
