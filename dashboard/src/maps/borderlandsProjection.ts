export type MercatorPoint = { x: number; y: number; z: number };

export const INK_COLOR = "#4C4B50";
export const INK_COLOR_RGB: [number, number, number] = [76 / 255, 75 / 255, 80 / 255];
/** Clip-space depth bias. Stay at 0; roof lift / wall outset provide the physical offset. */
export const INK_DEPTH_BIAS = 0;

export function authoredZoomFromMap(mapZoom: number, authoredZoomDelta: number): number {
  return mapZoom - authoredZoomDelta;
}

export function inkFullWidthCssPx(authoredZoom: number): number {
  const z = authoredZoom;
  if (z <= 14) return 0.7;
  if (z <= 16) return 0.7 + ((z - 14) / 2) * 0.15;
  if (z <= 18) return 0.85 + ((z - 16) / 2) * 0.1;
  return 0.95;
}

export function halfWidthBufferPx(fullWidthCssPx: number, effectivePixelRatio: number): number {
  return (fullWidthCssPx * effectivePixelRatio) / 2;
}

export function effectivePixelRatio(drawingBufferWidth: number, layoutWidth: number, fallback = 1): number {
  if (!(layoutWidth > 0) || !(drawingBufferWidth > 0)) return fallback;
  return drawingBufferWidth / layoutWidth;
}

export function composeLocalMatrix(mapMatrix: ArrayLike<number>, origin: MercatorPoint): Float32Array {
  const local = new Float64Array(16);
  for (let i = 0; i < 16; i++) local[i] = Number(mapMatrix[i]);
  for (let r = 0; r < 4; r++) {
    local[12 + r] =
      Number(mapMatrix[r]) * origin.x +
      Number(mapMatrix[4 + r]) * origin.y +
      Number(mapMatrix[8 + r]) * origin.z +
      Number(mapMatrix[12 + r]);
  }
  return new Float32Array(local);
}

export function projectLocal(matrix: ArrayLike<number>, point: MercatorPoint): { x: number; y: number; z: number; w: number } {
  const x = Number(matrix[0]) * point.x + Number(matrix[4]) * point.y + Number(matrix[8]) * point.z + Number(matrix[12]);
  const y = Number(matrix[1]) * point.x + Number(matrix[5]) * point.y + Number(matrix[9]) * point.z + Number(matrix[13]);
  const z = Number(matrix[2]) * point.x + Number(matrix[6]) * point.y + Number(matrix[10]) * point.z + Number(matrix[14]);
  const w = Number(matrix[3]) * point.x + Number(matrix[7]) * point.y + Number(matrix[11]) * point.z + Number(matrix[15]);
  return { x, y, z, w };
}

/** Clip a homogeneous point that is behind the near plane toward `other`. */
export function clipBehindNear(clip: { x: number; y: number; z: number; w: number }, other: { x: number; y: number; z: number; w: number }, nearW = 1e-4) {
  if (clip.w > 0) return clip;
  if (other.w <= 0) return null;
  const t = (nearW - clip.w) / (other.w - clip.w);
  if (!Number.isFinite(t)) return null;
  const u = Math.max(0, Math.min(1, t));
  return {
    x: clip.x + (other.x - clip.x) * u,
    y: clip.y + (other.y - clip.y) * u,
    z: clip.z + (other.z - clip.z) * u,
    w: clip.w + (other.w - clip.w) * u,
  };
}

export function matrixAsFloat64(value: unknown): Float64Array | null {
  if (!value) return null;
  if (value instanceof Float64Array && value.length >= 16) return value;
  if (ArrayBuffer.isView(value) || Array.isArray(value)) {
    const view = value as ArrayLike<number>;
    if (view.length < 16) return null;
    const out = new Float64Array(16);
    for (let i = 0; i < 16; i++) {
      const n = Number(view[i]);
      if (!Number.isFinite(n)) return null;
      out[i] = n;
    }
    return out;
  }
  return null;
}
