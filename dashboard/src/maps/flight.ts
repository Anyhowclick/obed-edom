export const DEFAULT_RHO = 1.42;
export const MIN_RHO = 0.5;
export const MAX_RHO = 3;

export function clampRho(curve?: number): number {
  return Math.max(MIN_RHO, Math.min(MAX_RHO, Number.isFinite(curve) ? curve! : DEFAULT_RHO));
}

export type ArcPath = { S: number; at: (f: number) => { pan: number; scale: number } };

/** Van Wijk (2003) "Tour into the picture" arc: w(s) = w0/cosh(r), pan traces the great-circle-in-log-space distance. `scale` is w(s)/w0 — caller derives zoom via z0 - log2(scale). */
export function arcPath(w0: number, w1: number, u1: number, rho: number): ArcPath {
  if (!(u1 > 1e-6 * w0) || !Number.isFinite(u1)) {
    const k = Math.log(w1 / w0);
    const S = Math.abs(k) / rho;
    return { S, at: (f) => ({ pan: f, scale: Math.exp(k * f) }) };
  }
  const rho2 = rho * rho;
  const rho4 = rho2 * rho2;
  const b0 = (w1 * w1 - w0 * w0 + rho4 * u1 * u1) / (2 * w0 * rho2 * u1);
  const b1 = (w1 * w1 - w0 * w0 - rho4 * u1 * u1) / (2 * w1 * rho2 * u1);
  const r0 = -Math.asinh(b0);
  const r1 = -Math.asinh(b1);
  const S = (r1 - r0) / rho;
  if (!Number.isFinite(S) || Math.abs(S) < 1e-9) {
    const k = Math.log(w1 / w0);
    const Sd = Math.abs(k) / rho;
    return { S: Sd, at: (f) => ({ pan: f, scale: Math.exp(k * f) }) };
  }
  return {
    S,
    at: (f) => {
      if (f <= 0) return { pan: 0, scale: 1 };
      if (f >= 1) return { pan: 1, scale: w1 / w0 };
      const r = r0 + rho * S * f;
      const u = (w0 * Math.sinh(r - r0)) / (rho2 * Math.cosh(r));
      const w = Math.cosh(r0) / Math.cosh(r);
      const pan = Math.max(0, Math.min(1, u / u1));
      return { pan, scale: w };
    },
  };
}
