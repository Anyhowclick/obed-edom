/** Mirrors `_default_landmark_size` in src/obed_edom/web/watercolour.py. */
export function defaultLandmarkSize(assetWidth: number): number {
  return Math.trunc(Math.max(240, Math.min(1600, Math.min(assetWidth, Math.trunc(1920 / 3) * 2))));
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
