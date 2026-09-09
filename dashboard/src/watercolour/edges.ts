function luma(rgba: Uint8ClampedArray, w: number, h: number, x: number, y: number): number {
  const cx = Math.min(w - 1, Math.max(0, x));
  const cy = Math.min(h - 1, Math.max(0, y));
  const offset = (cx + cy * w) * 4;
  return 0.299 * rgba[offset] + 0.587 * rgba[offset + 1] + 0.114 * rgba[offset + 2];
}

export function sobelMagnitude(rgba: Uint8ClampedArray, w: number, h: number): Float32Array {
  const out = new Float32Array(w * h);
  let max = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const tl = luma(rgba, w, h, x - 1, y - 1);
      const t = luma(rgba, w, h, x, y - 1);
      const tr = luma(rgba, w, h, x + 1, y - 1);
      const l = luma(rgba, w, h, x - 1, y);
      const r = luma(rgba, w, h, x + 1, y);
      const bl = luma(rgba, w, h, x - 1, y + 1);
      const b = luma(rgba, w, h, x, y + 1);
      const br = luma(rgba, w, h, x + 1, y + 1);
      const gx = tr + 2 * r + br - tl - 2 * l - bl;
      const gy = bl + 2 * b + br - tl - 2 * t - tr;
      const magnitude = Math.hypot(gx, gy);
      out[x + y * w] = magnitude;
      if (magnitude > max) max = magnitude;
    }
  }
  if (max > 0) {
    for (let i = 0; i < out.length; i++) out[i] /= max;
  }
  return out;
}

export function snapToEdge(grad: Float32Array, w: number, h: number, x: number, y: number, r: number): [number, number] {
  const x0 = Math.max(0, Math.floor(x - r));
  const x1 = Math.min(w - 1, Math.ceil(x + r));
  const y0 = Math.max(0, Math.floor(y - r));
  const y1 = Math.min(h - 1, Math.ceil(y + r));
  let bestX = Math.min(w - 1, Math.max(0, Math.round(x)));
  let bestY = Math.min(h - 1, Math.max(0, Math.round(y)));
  let bestValue = grad[bestX + bestY * w] ?? 0;
  let bestDist = 0;
  for (let py = y0; py <= y1; py++) {
    for (let px = x0; px <= x1; px++) {
      const value = grad[px + py * w];
      const dist = Math.hypot(px - x, py - y);
      if (value > bestValue || (value === bestValue && dist < bestDist)) {
        bestValue = value;
        bestDist = dist;
        bestX = px;
        bestY = py;
      }
    }
  }
  return [bestX, bestY];
}
