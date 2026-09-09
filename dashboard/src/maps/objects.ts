/** Mirrors `_default_landmark_size` in src/obed_edom/web/watercolour.py. */
export function defaultLandmarkSize(assetWidth: number): number {
  return Math.trunc(Math.max(240, Math.min(1600, Math.min(assetWidth, Math.trunc(1920 / 3) * 2))));
}

/** Handle sits at the object's right edge, so a horizontal drag delta is half the width change. */
export function resizeFromHandle(
  start: { x: number; y: number },
  current: { x: number; y: number },
  startSize: number,
  objectScale: number
): number {
  const scale = objectScale || 1;
  const size = startSize + (2 * (current.x - start.x)) / scale;
  return Math.round(Math.max(24, Math.min(4000, size)));
}
