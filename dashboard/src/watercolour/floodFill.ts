export function floodFill(rgba: Uint8ClampedArray, w: number, h: number, x: number, y: number, tolerance: number): Uint8Array {
  const out = new Uint8Array(w * h);
  if (x < 0 || y < 0 || x >= w || y >= h) return out;
  const seed = (x + y * w) * 4;
  const sr = rgba[seed];
  const sg = rgba[seed + 1];
  const sb = rgba[seed + 2];
  const tol = tolerance * 2.55;
  const visited = new Uint8Array(w * h);
  const queue = new Int32Array(w * h);
  let head = 0;
  let tail = 0;
  const start = x + y * w;
  queue[tail++] = start;
  visited[start] = 1;
  while (head < tail) {
    const index = queue[head++];
    const px = index % w;
    const py = (index - px) / w;
    const offset = index * 4;
    const dr = Math.abs(rgba[offset] - sr);
    const dg = Math.abs(rgba[offset + 1] - sg);
    const db = Math.abs(rgba[offset + 2] - sb);
    if (Math.max(dr, dg, db) > tol) continue;
    out[index] = 1;
    if (px > 0) {
      const left = index - 1;
      if (!visited[left]) { visited[left] = 1; queue[tail++] = left; }
    }
    if (px < w - 1) {
      const right = index + 1;
      if (!visited[right]) { visited[right] = 1; queue[tail++] = right; }
    }
    if (py > 0) {
      const up = index - w;
      if (!visited[up]) { visited[up] = 1; queue[tail++] = up; }
    }
    if (py < h - 1) {
      const down = index + w;
      if (!visited[down]) { visited[down] = 1; queue[tail++] = down; }
    }
  }
  return out;
}
