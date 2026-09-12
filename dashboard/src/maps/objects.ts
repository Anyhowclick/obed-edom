import type { ExpressionSpecification } from "maplibre-gl";

/** Mirrors `_default_landmark_size` in src/obed_edom/web/watercolour.py. */
export function defaultLandmarkSize(assetWidth: number): number {
  return Math.trunc(Math.max(240, Math.min(1600, Math.min(assetWidth, Math.trunc(1920 / 3) * 2))));
}

/** Ratio between an object's ground size authored at `sizeZoom` and its size at `authoredZoom`. */
export function zoomSizeFactor(sizeZoom: number, authoredZoom: number): number {
  return Math.pow(2, authoredZoom - sizeZoom);
}

/** Authored px for `church` at `authoredZoom`, honouring "scale with map" when set. */
export function effectiveObjectSize(church: { size?: number; scaleWithMap?: boolean; sizeZoom?: number }, authoredZoom: number): number {
  const size = church.size ?? 120;
  if (!church.scaleWithMap || church.sizeZoom == null) return size;
  return size * zoomSizeFactor(church.sizeZoom, authoredZoom);
}

/**
 * `icon-size` stops for a top-level `["zoom"]` interpolate. `base` is the current
 * (non-scaling) icon-size expression; the stops fold in the geometric zoom growth for
 * features with `scaleWithMap` via `sizeZoomRef` (see overlays.ts `churchesGeo`).
 */
export function iconSizeStops(base: unknown): ExpressionSpecification {
  const swm = ["boolean", ["get", "scaleWithMap"], false];
  const stopAt = (z: number): ExpressionSpecification => ["case", swm, ["*", base, ["^", 2, ["-", z, ["get", "sizeZoomRef"]]]], base] as unknown as ExpressionSpecification;
  return ["interpolate", ["exponential", 2], ["zoom"], 0, stopAt(0), 22, stopAt(22)];
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
