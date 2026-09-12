import type { ExpressionSpecification } from "maplibre-gl";

/** Mirrors `_default_landmark_size` in src/obed_edom/web/watercolour.py. */
export function defaultLandmarkSize(assetWidth: number): number {
  return Math.trunc(Math.max(240, Math.min(1600, Math.min(assetWidth, Math.trunc(1920 / 3) * 2))));
}

/** Ratio between an object's ground size authored at `sizeZoom` and its size at `authoredZoom`. */
export function zoomSizeFactor(sizeZoom: number, authoredZoom: number): number {
  return Math.pow(2, authoredZoom - sizeZoom);
}

/** Default authored px per object kind when a church carries no `size`. */
export function defaultObjectSize(kind: string): number {
  if (kind === "dot") return 28;
  if (kind === "dropPin") return 64;
  return 120;
}

/** Authored px for `church` at `authoredZoom`, honouring "scale with map" when set. */
export function effectiveObjectSize(church: { size?: number; scaleWithMap?: boolean; sizeZoom?: number; kind?: string }, authoredZoom: number): number {
  const size = church.size ?? defaultObjectSize(church.kind || "landmark");
  if (!church.scaleWithMap || church.sizeZoom == null) return size;
  return size * zoomSizeFactor(church.sizeZoom, authoredZoom);
}

/**
 * `size`-like stops for a top-level `["zoom"]` interpolate. `base` is the current
 * (non-scaling) size expression; the stops fold in the geometric zoom growth for
 * features with `scaleWithMap` via `sizeZoomRef` (see overlays.ts `churchesGeo`).
 */
export function zoomScaledStops(base: unknown, max?: number): ExpressionSpecification {
  const swm = ["boolean", ["get", "scaleWithMap"], false];
  const stopAt = (z: number): ExpressionSpecification => {
    const value = ["case", swm, ["*", base, ["^", 2, ["-", z, ["get", "sizeZoomRef"]]]], base];
    return (max == null ? value : ["min", max, value]) as unknown as ExpressionSpecification;
  };
  // A pair of interpolate stops reproduces an exact 2^z curve between them (algebraically, base-2
  // interpolation of two true samples of A*2^z recovers A*2^z everywhere in between) but NOT when a
  // stop is min()-clamped, so a clamped max needs one stop per integer zoom: a segment whose two
  // endpoints are both below the clamp stays exact, a segment fully past the clamp is flat at max,
  // and the one segment straddling the clamp is still base-2 interpolated between its two (unequal)
  // endpoints, so it undershoots max in between (e.g. 949 vs 1024 at z14.5).
  if (max == null) return ["interpolate", ["exponential", 2], ["zoom"], 0, stopAt(0), 22, stopAt(22)];
  const stops: unknown[] = ["interpolate", ["exponential", 2], ["zoom"]];
  for (let z = 0; z <= 22; z++) stops.push(z, stopAt(z));
  return stops as unknown as ExpressionSpecification;
}

export type ObjectCorner = "nw" | "ne" | "sw" | "se";

/**
 * Box is anchored at the icon's bottom-centre: width grows symmetrically about the
 * anchor, height grows one-sided from the pinned bottom. Dominant-axis drag decides
 * the size delta, so a pure horizontal drag matches the old edge-handle behaviour.
 */
export function resizeFromCorner(
  start: { x: number; y: number },
  current: { x: number; y: number },
  startSize: number,
  objectScale: number,
  corner: ObjectCorner,
  aspect = 1
): number {
  const scale = objectScale || 1;
  const a = aspect > 0 ? aspect : 1;
  const sx = corner.endsWith("e") ? 1 : -1;
  const sy = corner.startsWith("n") ? -1 : 1;
  const dx = current.x - start.x;
  const dy = current.y - start.y;
  const px = (2 * sx * dx) / scale;
  const py = (sy * dy) / (a * scale);
  const d = Math.abs(px) >= Math.abs(py) ? px : py;
  return Math.round(Math.max(24, Math.min(4000, startSize + d)));
}

/**
 * Clipboard rebase: materialise the object's on-screen size at `sourceZoom` into `size`
 * and re-anchor `sizeZoom` to the target camera, so a paste keeps the same on-screen size.
 */
export function rebaseForPaste<T extends { size?: number; scaleWithMap?: boolean; sizeZoom?: number; kind?: string }>(
  church: T,
  sourceZoom: number,
  targetZoom: number
): T {
  if (!church.scaleWithMap) return church;
  return { ...church, size: Math.round(effectiveObjectSize(church, sourceZoom)), sizeZoom: targetZoom };
}
