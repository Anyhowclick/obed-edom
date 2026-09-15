export type LngLat = [number, number];
export type WireFeature = {
  id?: unknown;
  geometry: { type: string; coordinates: unknown };
  properties?: Record<string, unknown> | null;
  source?: string;
  sourceLayer?: string;
};

export type FacadeSeg = {
  a: [number, number, number];
  b: [number, number, number];
};

export type NormalizedComponent = {
  sourceId: string | null;
  source: string;
  sourceLayer: string;
  base: number;
  top: number;
  outer: LngLat[];
  holes: LngLat[][];
  identity: string;
  areaM2: number;
  perimeterM: number;
  roofOnly: boolean;
};

export type GeometryDiagnostics = {
  sourceFeatureCount: number;
  normalizedCount: number;
  duplicatesRemoved: number;
  invalidRings: number;
  slabsOmitted: number;
  sharedEdgesRemoved: number;
  roofFallbacks: number;
  selectedPosts: number;
  roofSegments: number;
  totalSegments: number;
  budgetDropped: number;
};

export const METERS_PER_DEG = 111320;
export const MIN_HEIGHT_M = 1.5;
export const SLAB_BASE_M = 1.2;
export const SLAB_RISE_M = 6;
export const ROOF_LIFT_M = 0.35;
export const ROOF_SEAM_LIFT_M = 1.5;
export const WALL_OUTSET_M = 0.18;
export const MIN_CORNER_TURN_DEG = 40;
export const MIN_CORNER_SUPPORT_M = 2;
export const MIN_POST_SPACING_M = 4;
export const POST_SPACING_PERIMETER_FACTOR = 0.04;
export const MAX_POSTS_PER_COMPONENT = 8;
export const MIN_INK_AREA_M2 = 4;
export const ROOF_SIMPLIFY_MAX_M = 0.25;
export const MAX_COMPONENTS = 3000;
export const MAX_SEGMENTS = 50_000;
export const MAX_RAW_VERTICES = 200_000;
export const MAX_ROOF_SEGMENTS = 512;
export const IDENTITY_QUANTUM_M = 0.01;

type En = { e: number; n: number };

export function renderedNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function buildingExtents(feature: WireFeature): { base: number; top: number; roofOnly: boolean } | null {
  const props = feature.properties || {};
  const top = renderedNumber(props.render_height);
  if (top == null || top < MIN_HEIGHT_M) return null;
  const rawBase = renderedNumber(props.render_min_height);
  const base = Math.max(0, rawBase ?? 0);
  if (top <= base + 0.4) return null;
  return { base, top, roofOnly: isShallowElevatedSlab(base, top) };
}

export function isShallowElevatedSlab(base: number, top: number): boolean {
  return base > SLAB_BASE_M && top - base < SLAB_RISE_M;
}

export function unwrapLng(lng: number, originLng: number): number {
  let next = lng;
  while (next - originLng > 180) next -= 360;
  while (next - originLng < -180) next += 360;
  return next;
}

export function metricOrigin(lng: number, lat: number): { lng: number; lat: number; cos: number } {
  return { lng, lat, cos: Math.max(Math.cos((lat * Math.PI) / 180), 0.2) };
}

export function toEn(point: LngLat, origin: { lng: number; lat: number; cos: number }): En {
  return {
    e: (point[0] - origin.lng) * METERS_PER_DEG * origin.cos,
    n: (point[1] - origin.lat) * METERS_PER_DEG,
  };
}

export function fromEn(point: En, origin: { lng: number; lat: number; cos: number }): LngLat {
  return [origin.lng + point.e / (METERS_PER_DEG * origin.cos), origin.lat + point.n / METERS_PER_DEG];
}

function almostSame(a: LngLat, b: LngLat): boolean {
  return Math.abs(a[0] - b[0]) < 1e-12 && Math.abs(a[1] - b[1]) < 1e-12;
}

function cleanOpenRing(raw: unknown, originLng: number): LngLat[] | null {
  if (!Array.isArray(raw) || raw.length < 3) return null;
  const pts: LngLat[] = [];
  for (const item of raw) {
    if (!Array.isArray(item) || item.length < 2) return null;
    const lng = Number(item[0]);
    const lat = Number(item[1]);
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
    const next: LngLat = [unwrapLng(lng, originLng), lat];
    if (pts.length && almostSame(pts[pts.length - 1], next)) continue;
    pts.push(next);
  }
  if (pts.length >= 2 && almostSame(pts[0], pts[pts.length - 1])) pts.pop();
  if (pts.length < 3) return null;
  for (let i = 0; i < pts.length; i++) {
    if (Math.abs(pts[i][0] - pts[(i + 1) % pts.length][0]) > 180) return null;
  }
  return pts;
}

function ringArea(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): number {
  let area = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = toEn(ring[i], origin);
    const b = toEn(ring[(i + 1) % ring.length], origin);
    area += a.e * b.n - b.e * a.n;
  }
  return area / 2;
}

function ringPerimeter(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): number {
  let length = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = toEn(ring[i], origin);
    const b = toEn(ring[(i + 1) % ring.length], origin);
    length += Math.hypot(b.e - a.e, b.n - a.n);
  }
  return length;
}

function isCollinearTriplet(a: En, b: En, c: En): boolean {
  const abe = b.e - a.e;
  const abn = b.n - a.n;
  const bce = c.e - b.e;
  const bcn = c.n - b.n;
  const ab = Math.hypot(abe, abn);
  const bc = Math.hypot(bce, bcn);
  if (ab < 1e-6 || bc < 1e-6) return true;
  const dot = Math.max(-1, Math.min(1, (abe * bce + abn * bcn) / (ab * bc)));
  return (Math.acos(dot) * 180) / Math.PI < 1.5;
}

function dropCollinear(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): LngLat[] {
  if (ring.length <= 3) return ring.slice();
  const ens = ring.map((point) => toEn(point, origin));
  const keep: LngLat[] = [];
  for (let i = 0; i < ring.length; i++) {
    const prev = ens[(i - 1 + ring.length) % ring.length];
    const curr = ens[i];
    const next = ens[(i + 1) % ring.length];
    if (!isCollinearTriplet(prev, curr, next)) keep.push(ring[i]);
  }
  return keep.length >= 3 ? keep : ring.slice();
}

function segmentsIntersect(a: En, b: En, c: En, d: En): boolean {
  const cross = (p: En, q: En, r: En) => (q.e - p.e) * (r.n - p.n) - (q.n - p.n) * (r.e - p.e);
  const d1 = cross(a, b, c);
  const d2 = cross(a, b, d);
  const d3 = cross(c, d, a);
  const d4 = cross(c, d, b);
  if ((d1 === 0 && d2 === 0 && d3 === 0 && d4 === 0) || d1 * d2 > 0 || d3 * d4 > 0) return false;
  return d1 * d2 <= 0 && d3 * d4 <= 0;
}

export function ringSelfIntersects(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): boolean {
  const ens = ring.map((point) => toEn(point, origin));
  const n = ens.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (Math.abs(i - j) <= 1 || (i === 0 && j === n - 1)) continue;
      if (segmentsIntersect(ens[i], ens[(i + 1) % n], ens[j], ens[(j + 1) % n])) return true;
    }
  }
  return false;
}

function orientOuter(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): LngLat[] {
  return ringArea(ring, origin) < 0 ? ring.slice().reverse() : ring.slice();
}

function lexRotate(ring: LngLat[]): LngLat[] {
  let best = 0;
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[best];
    if (a[0] < b[0] - 1e-12 || (Math.abs(a[0] - b[0]) <= 1e-12 && a[1] < b[1])) best = i;
  }
  return ring.slice(best).concat(ring.slice(0, best));
}

export function canonicalizeRing(ring: LngLat[], originLng = ring[0]?.[0] ?? 0): LngLat[] {
  const origin = metricOrigin(originLng, ring[0]?.[1] ?? 0);
  return lexRotate(orientOuter(ring, origin));
}

function pointOnSegment(p: En, a: En, b: En, eps = 0.03): boolean {
  const abe = b.e - a.e;
  const abn = b.n - a.n;
  const ape = p.e - a.e;
  const apn = p.n - a.n;
  const len = Math.hypot(abe, abn);
  if (len < 1e-6) return Math.hypot(ape, apn) <= eps;
  const t = (ape * abe + apn * abn) / (len * len);
  if (t <= 1e-6 || t >= 1 - 1e-6) return false;
  const proj = { e: a.e + abe * t, n: a.n + abn * t };
  return Math.hypot(p.e - proj.e, p.n - proj.n) <= eps;
}

function rdpChain(points: En[], start: number, end: number, tol: number, keep: boolean[]): void {
  let maxDist = 0;
  let index = -1;
  const a = points[start];
  const b = points[end];
  const abe = b.e - a.e;
  const abn = b.n - a.n;
  const len = Math.hypot(abe, abn);
  for (let i = start + 1; i < end; i++) {
    const p = points[i];
    const dist = len < 1e-9
      ? Math.hypot(p.e - a.e, p.n - a.n)
      : Math.abs(abe * (a.n - p.n) - abn * (a.e - p.e)) / len;
    if (dist > maxDist) {
      maxDist = dist;
      index = i;
    }
  }
  if (maxDist > tol && index >= 0) {
    rdpChain(points, start, index, tol, keep);
    rdpChain(points, index, end, tol, keep);
  } else {
    keep[start] = true;
    keep[end] = true;
  }
}

function simplifyClosed(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): LngLat[] {
  const cleaned = dropCollinear(ring, origin);
  if (cleaned.length <= 8) return cleaned;
  const ens = cleaned.map((point) => toEn(point, origin));
  let a = 0;
  for (let i = 1; i < ens.length; i++) {
    if (ens[i].e < ens[a].e - 1e-9 || (Math.abs(ens[i].e - ens[a].e) <= 1e-9 && ens[i].n < ens[a].n)) a = i;
  }
  let b = a;
  let best = -1;
  for (let i = 0; i < ens.length; i++) {
    const dist = Math.hypot(ens[i].e - ens[a].e, ens[i].n - ens[a].n);
    if (dist > best) {
      best = dist;
      b = i;
    }
  }
  if (a === b) return cleaned;
  const keep = ens.map(() => false);
  const walk = (from: number, to: number) => {
    const chain: number[] = [from];
    let i = from;
    while (i !== to) {
      i = (i + 1) % ens.length;
      chain.push(i);
    }
    const pts = chain.map((index) => ens[index]);
    const flags = pts.map(() => false);
    rdpChain(pts, 0, pts.length - 1, ROOF_SIMPLIFY_MAX_M, flags);
    flags.forEach((on, idx) => {
      if (on) keep[chain[idx]] = true;
    });
  };
  walk(a, b);
  walk(b, a);
  const next = cleaned.filter((_, index) => keep[index]);
  if (next.length < 3 || ringSelfIntersects(next, origin) || Math.abs(ringArea(next, origin)) < 1e-3) return cleaned;
  return next;
}

function significantVolume(areaM2: number, rise: number, perimeterM: number): boolean {
  if (areaM2 >= MIN_INK_AREA_M2) return true;
  const span = perimeterM / 4;
  return rise >= 12 && span >= 1.5;
}

function quantizeLngLat(point: LngLat): string {
  const cos = Math.max(Math.cos((point[1] * Math.PI) / 180), 0.2);
  const dLng = IDENTITY_QUANTUM_M / (METERS_PER_DEG * cos);
  const dLat = IDENTITY_QUANTUM_M / METERS_PER_DEG;
  return `${(Math.round(point[0] / dLng) * dLng).toFixed(7)},${(Math.round(point[1] / dLat) * dLat).toFixed(7)}`;
}

export function fragmentIdentity(component: Pick<NormalizedComponent, "source" | "sourceLayer" | "sourceId" | "base" | "top" | "outer" | "holes">): string {
  const ringKey = (ring: LngLat[]) =>
    canonicalizeRing(ring, component.outer[0][0])
      .map(quantizeLngLat)
      .join(";");
  const holes = component.holes.map(ringKey).sort().join("/");
  return [
    component.source,
    component.sourceLayer,
    component.sourceId ?? "anon",
    component.base.toFixed(3),
    component.top.toFixed(3),
    ringKey(component.outer),
    holes,
  ].join("#");
}

export function inkFragmentKey(feature: WireFeature): string | null {
  const components = normalizeFeature(feature);
  if (!components.length) return null;
  return components.map((item) => item.identity).sort().join("||");
}

function polygonMembers(geometry: WireFeature["geometry"]): unknown[] {
  if (geometry.type === "Polygon") return [geometry.coordinates];
  if (geometry.type === "MultiPolygon" && Array.isArray(geometry.coordinates)) return geometry.coordinates;
  return [];
}

export function ringIntersectsBounds(ring: LngLat[], bounds: { west: number; south: number; east: number; north: number }, pad = 0.008): boolean {
  if (!ring.length) return false;
  let minLng = ring[0][0];
  let maxLng = ring[0][0];
  let minLat = ring[0][1];
  let maxLat = ring[0][1];
  for (const point of ring) {
    minLng = Math.min(minLng, point[0]);
    maxLng = Math.max(maxLng, point[0]);
    minLat = Math.min(minLat, point[1]);
    maxLat = Math.max(maxLat, point[1]);
  }
  return !(maxLng < bounds.west - pad || minLng > bounds.east + pad || maxLat < bounds.south - pad || minLat > bounds.north + pad);
}

export function featureMayBeVisible(feature: WireFeature, bounds: { west: number; south: number; east: number; north: number }, pad = 0.008): boolean {
  for (const member of polygonMembers(feature.geometry)) {
    if (!Array.isArray(member) || !Array.isArray(member[0])) continue;
    const ring = (member[0] as number[][]).filter((point) => Number.isFinite(point?.[0]) && Number.isFinite(point?.[1])) as LngLat[];
    if (ringIntersectsBounds(ring, bounds, pad)) return true;
  }
  return false;
}

export function normalizeFeature(feature: WireFeature, originLng?: number): NormalizedComponent[] {
  const extents = buildingExtents(feature);
  if (!extents) return [];
  const members = polygonMembers(feature.geometry);
  const out: NormalizedComponent[] = [];
  const fallbackLng = originLng ?? 0;
  for (const member of members) {
    if (!Array.isArray(member) || !member.length) continue;
    const seed = Array.isArray(member[0]) && Array.isArray(member[0][0]) ? Number(member[0][0][0]) : fallbackLng;
    const outer = cleanOpenRing(member[0], Number.isFinite(seed) ? seed : fallbackLng);
    if (!outer) continue;
    const origin = metricOrigin(outer[0][0], outer[0][1]);
    if (Math.abs(ringArea(outer, origin)) < 1e-6) continue;
    const oriented = orientOuter(outer, origin);
    if (ringSelfIntersects(oriented, origin)) continue;
    const holes: LngLat[][] = [];
    for (let i = 1; i < member.length; i++) {
      const hole = cleanOpenRing(member[i], oriented[0][0]);
      if (hole) holes.push(orientOuter(hole, origin).reverse());
    }
    const areaM2 = Math.abs(ringArea(oriented, origin));
    const perimeterM = ringPerimeter(oriented, origin);
    if (!extents.roofOnly && !significantVolume(areaM2, extents.top - extents.base, perimeterM)) continue;
    const component: NormalizedComponent = {
      sourceId: feature.id == null || String(feature.id) === "" ? null : String(feature.id),
      source: feature.source || "",
      sourceLayer: feature.sourceLayer || "building",
      base: extents.base,
      top: extents.top,
      outer: lexRotate(oriented),
      holes,
      identity: "",
      areaM2,
      perimeterM,
      roofOnly: extents.roofOnly,
    };
    component.identity = fragmentIdentity(component);
    out.push(component);
  }
  return out;
}

export function normalizeBuildings(
  features: WireFeature[],
  opts?: { maxRawVertices?: number },
): { components: NormalizedComponent[]; diagnostics: GeometryDiagnostics } {
  const diagnostics: GeometryDiagnostics = {
    sourceFeatureCount: features.length,
    normalizedCount: 0,
    duplicatesRemoved: 0,
    invalidRings: 0,
    slabsOmitted: 0,
    sharedEdgesRemoved: 0,
    roofFallbacks: 0,
    selectedPosts: 0,
    roofSegments: 0,
    totalSegments: 0,
    budgetDropped: 0,
  };
  const seen = new Set<string>();
  const components: NormalizedComponent[] = [];
  for (const feature of features) {
    const next = normalizeFeature(feature);
    if (!next.length && polygonMembers(feature.geometry).length) diagnostics.invalidRings += 1;
    for (const component of next) {
      if (seen.has(component.identity)) {
        diagnostics.duplicatesRemoved += 1;
        continue;
      }
      seen.add(component.identity);
      components.push(component);
    }
  }
  components.sort((a, b) => {
    const va = a.areaM2 * (a.top - a.base);
    const vb = b.areaM2 * (b.top - b.base);
    if (vb !== va) return vb - va;
    return a.identity < b.identity ? -1 : a.identity > b.identity ? 1 : 0;
  });
  const maxRaw = opts?.maxRawVertices ?? MAX_RAW_VERTICES;
  const kept: NormalizedComponent[] = [];
  let rawVerts = 0;
  for (const component of components) {
    if (rawVerts + component.outer.length > maxRaw) {
      diagnostics.budgetDropped += 1;
      continue;
    }
    rawVerts += component.outer.length;
    kept.push(component);
  }
  diagnostics.normalizedCount = kept.length;
  return { components: kept, diagnostics };
}

type Corner = { index: number; e: number; n: number; turn: number; support: number; along: number };

export function selectSignificantCorners(ring: LngLat[]): number[] {
  if (ring.length < 3) return [];
  const origin = metricOrigin(ring[0][0], ring[0][1]);
  const collapsed = dropCollinear(ring, origin);
  const ens = collapsed.map((point) => toEn(point, origin));
  const n = ens.length;
  const perimeter = ringPerimeter(collapsed, origin);
  const spacing = Math.max(MIN_POST_SPACING_M, perimeter * POST_SPACING_PERIMETER_FACTOR);
  const along: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) along[i] = along[i - 1] + Math.hypot(ens[i].e - ens[i - 1].e, ens[i].n - ens[i - 1].n);
  const candidates: Corner[] = [];
  for (let i = 0; i < n; i++) {
    const prev = ens[(i - 1 + n) % n];
    const curr = ens[i];
    const next = ens[(i + 1) % n];
    const inE = curr.e - prev.e;
    const inN = curr.n - prev.n;
    const outE = next.e - curr.e;
    const outN = next.n - curr.n;
    const inLen = Math.hypot(inE, inN);
    const outLen = Math.hypot(outE, outN);
    const support = Math.min(inLen, outLen);
    if (support < MIN_CORNER_SUPPORT_M) continue;
    const dot = Math.max(-1, Math.min(1, (inE * outE + inN * outN) / (inLen * outLen)));
    const turn = (Math.acos(dot) * 180) / Math.PI;
    if (turn < MIN_CORNER_TURN_DEG || turn > 170) continue;
    candidates.push({ index: i, e: curr.e, n: curr.n, turn, support, along: along[i] });
  }
  candidates.sort((a, b) => {
    if (b.turn !== a.turn) return b.turn - a.turn;
    if (b.support !== a.support) return b.support - a.support;
    if (a.e !== b.e) return a.e - b.e;
    return a.n - b.n;
  });
  const chosen: Corner[] = [];
  for (const candidate of candidates) {
    if (chosen.length >= MAX_POSTS_PER_COMPONENT) break;
    const farEnough = chosen.every((other) => {
      const delta = Math.abs(candidate.along - other.along);
      return Math.min(delta, perimeter - delta) >= spacing - 1e-6;
    });
    if (farEnough) chosen.push(candidate);
  }
  const byIndex = new Map(collapsed.map((point, index) => [`${point[0].toFixed(8)},${point[1].toFixed(8)}`, index]));
  return chosen
    .map((item) => {
      const key = `${collapsed[item.index][0].toFixed(8)},${collapsed[item.index][1].toFixed(8)}`;
      const original = ring.findIndex((point) => `${point[0].toFixed(8)},${point[1].toFixed(8)}` === key);
      return original >= 0 ? original : byIndex.get(key) ?? item.index;
    })
    .sort((a, b) => a - b);
}

function unit(e: number, n: number): En {
  const len = Math.hypot(e, n);
  return len > 1e-9 ? { e: e / len, n: n / len } : { e: 0, n: 0 };
}

function outwardNormals(ring: LngLat[], origin: { lng: number; lat: number; cos: number }): En[] {
  const ens = ring.map((point) => toEn(point, origin));
  const sign = ringArea(ring, origin) >= 0 ? 1 : -1;
  return ens.map((curr, i) => {
    const next = ens[(i + 1) % ens.length];
    const edge = unit(next.e - curr.e, next.n - curr.n);
    return { e: edge.n * sign, n: -edge.e * sign };
  });
}

function offsetVertex(prevN: En, nextN: En, outset: number): En {
  const sum = { e: prevN.e + nextN.e, n: prevN.n + nextN.n };
  const len = Math.hypot(sum.e, sum.n);
  if (len < 1e-8) return { e: nextN.e * outset, n: nextN.n * outset };
  const bisector = { e: sum.e / len, n: sum.n / len };
  const cos = bisector.e * nextN.e + bisector.n * nextN.n;
  if (Math.abs(cos) < 1e-4) return { e: nextN.e * outset, n: nextN.n * outset };
  const dist = Math.min(Math.abs(outset / cos), outset * 2) * Math.sign(outset / cos);
  return { e: bisector.e * dist, n: bisector.n * dist };
}

function offsetRing(ring: LngLat[], outset: number): LngLat[] {
  const origin = metricOrigin(ring[0][0], ring[0][1]);
  const ens = ring.map((point) => toEn(point, origin));
  const normals = outwardNormals(ring, origin);
  return ens.map((curr, i) => {
    const prevN = normals[(i - 1 + ring.length) % ring.length];
    const nextN = normals[i];
    const off = offsetVertex(prevN, nextN, outset);
    return fromEn({ e: curr.e + off.e, n: curr.n + off.n }, origin);
  });
}

type SourceEdge = {
  a: LngLat;
  b: LngLat;
  base: number;
  top: number;
  component: number;
};

function orderedKey(a: LngLat, b: LngLat): string {
  const leftFirst = a[0] < b[0] - 1e-10 || (Math.abs(a[0] - b[0]) <= 1e-10 && a[1] <= b[1]);
  const p = leftFirst ? a : b;
  const q = leftFirst ? b : a;
  return `${p[0].toFixed(7)},${p[1].toFixed(7)}|${q[0].toFixed(7)},${q[1].toFixed(7)}`;
}

function splitAtPoints(a: LngLat, b: LngLat, cuts: LngLat[], origin: { lng: number; lat: number; cos: number }): Array<[LngLat, LngLat]> {
  const ae = toEn(a, origin);
  const be = toEn(b, origin);
  const abe = be.e - ae.e;
  const abn = be.n - ae.n;
  const len = Math.hypot(abe, abn);
  if (len < 1e-6) return [];
  const ts = [0, 1];
  for (const cut of cuts) {
    const p = toEn(cut, origin);
    const t = ((p.e - ae.e) * abe + (p.n - ae.n) * abn) / (len * len);
    if (t > 1e-4 && t < 1 - 1e-4) ts.push(t);
  }
  ts.sort((x, y) => x - y);
  const out: Array<[LngLat, LngLat]> = [];
  for (let i = 0; i < ts.length - 1; i++) {
    if (ts[i + 1] - ts[i] < 1e-4) continue;
    const p0 = fromEn({ e: ae.e + abe * ts[i], n: ae.n + abn * ts[i] }, origin);
    const p1 = fromEn({ e: ae.e + abe * ts[i + 1], n: ae.n + abn * ts[i + 1] }, origin);
    out.push([p0, p1]);
  }
  return out.length ? out : [[a, b]];
}

const EDGE_CELL_M = 8;

function heightKey(base: number, top: number): string {
  return `${base.toFixed(2)}|${top.toFixed(2)}`;
}

function cellCoord(value: number): number {
  return Math.floor(value / EDGE_CELL_M);
}

function endpointBucketKey(ce: number, cn: number, base: number, top: number): string {
  return `${ce},${cn}|${heightKey(base, top)}`;
}

function cellsForSegment(ae: En, be: En): Array<[number, number]> {
  const e0 = cellCoord(Math.min(ae.e, be.e));
  const e1 = cellCoord(Math.max(ae.e, be.e));
  const n0 = cellCoord(Math.min(ae.n, be.n));
  const n1 = cellCoord(Math.max(ae.n, be.n));
  const cells: Array<[number, number]> = [];
  for (let ce = e0; ce <= e1; ce++) {
    for (let cn = n0; cn <= n1; cn++) cells.push([ce, cn]);
  }
  return cells;
}

type IndexedEndpoint = { point: LngLat; en: En; component: number };

export type SharedSeam = { a: LngLat; b: LngLat; base: number; top: number };

export type SharedSeams = {
  keys: Set<string>;
  spans: SharedSeam[];
  origin: { lng: number; lat: number; cos: number };
  index: Map<string, SharedSeam[]>;
};

function indexSharedSpans(spans: SharedSeam[], origin: { lng: number; lat: number; cos: number }): Map<string, SharedSeam[]> {
  const index = new Map<string, SharedSeam[]>();
  for (const span of spans) {
    const seen = new Set<string>();
    for (const [ce, cn] of cellsForSegment(toEn(span.a, origin), toEn(span.b, origin))) {
      const key = endpointBucketKey(ce, cn, span.base, span.top);
      if (seen.has(key)) continue;
      seen.add(key);
      const list = index.get(key);
      if (list) list.push(span);
      else index.set(key, [span]);
    }
  }
  return index;
}

function nearbySpans(
  a: LngLat,
  b: LngLat,
  base: number,
  top: number,
  shared: SharedSeams,
): SharedSeam[] {
  const ae = toEn(a, shared.origin);
  const be = toEn(b, shared.origin);
  const seen = new Set<SharedSeam>();
  const out: SharedSeam[] = [];
  for (const [ce, cn] of cellsForSegment(ae, be)) {
    const hits = shared.index.get(endpointBucketKey(ce, cn, base, top));
    if (!hits) continue;
    for (const span of hits) {
      if (seen.has(span)) continue;
      seen.add(span);
      out.push(span);
    }
  }
  return out;
}

export function suppressSharedEdges(components: NormalizedComponent[]): SharedSeams {
  const origin = components[0] ? metricOrigin(components[0].outer[0][0], components[0].outer[0][1]) : metricOrigin(0, 0);
  const edges: SourceEdge[] = [];
  const buckets = new Map<string, IndexedEndpoint[]>();
  components.forEach((component, componentIndex) => {
    const ring = component.outer;
    for (let i = 0; i < ring.length; i++) {
      const point = ring[i];
      const en = toEn(point, origin);
      const bucket = endpointBucketKey(cellCoord(en.e), cellCoord(en.n), component.base, component.top);
      const list = buckets.get(bucket);
      const indexed = { point, en, component: componentIndex };
      if (list) list.push(indexed);
      else buckets.set(bucket, [indexed]);
      edges.push({
        a: point,
        b: ring[(i + 1) % ring.length],
        base: component.base,
        top: component.top,
        component: componentIndex,
      });
    }
  });
  const split: SourceEdge[] = [];
  for (const edge of edges) {
    const cuts: LngLat[] = [];
    const ae = toEn(edge.a, origin);
    const be = toEn(edge.b, origin);
    const seen = new Set<string>();
    for (const [ce, cn] of cellsForSegment(ae, be)) {
      const hits = buckets.get(endpointBucketKey(ce, cn, edge.base, edge.top));
      if (!hits) continue;
      for (const other of hits) {
        if (other.component === edge.component) continue;
        const id = `${other.point[0].toFixed(7)},${other.point[1].toFixed(7)}`;
        if (seen.has(id)) continue;
        seen.add(id);
        if (pointOnSegment(other.en, ae, be)) cuts.push(other.point);
      }
    }
    for (const [a, b] of splitAtPoints(edge.a, edge.b, cuts, origin)) {
      split.push({ ...edge, a, b });
    }
  }
  const counts = new Map<string, number>();
  const byKey = new Map<string, SharedSeam>();
  for (const edge of split) {
    const key = `${orderedKey(edge.a, edge.b)}|${edge.base.toFixed(2)}|${edge.top.toFixed(2)}`;
    counts.set(key, (counts.get(key) || 0) + 1);
    if (!byKey.has(key)) byKey.set(key, { a: edge.a, b: edge.b, base: edge.base, top: edge.top });
  }
  const keys = new Set<string>();
  const spans: SharedSeam[] = [];
  for (const [key, count] of counts) {
    if (count < 2) continue;
    keys.add(key);
    const span = byKey.get(key);
    if (span) spans.push(span);
  }
  return { keys, spans, origin, index: indexSharedSpans(spans, origin) };
}

function edgeIdentity(a: LngLat, b: LngLat, base: number, top: number): string {
  return `${orderedKey(a, b)}|${base.toFixed(2)}|${top.toFixed(2)}`;
}

function paramOnEdge(point: LngLat, a: LngLat, b: LngLat, origin: { lng: number; lat: number; cos: number }): number {
  const ae = toEn(a, origin);
  const be = toEn(b, origin);
  const pe = toEn(point, origin);
  const abe = be.e - ae.e;
  const abn = be.n - ae.n;
  const len2 = abe * abe + abn * abn;
  if (len2 < 1e-12) return 0;
  return ((pe.e - ae.e) * abe + (pe.n - ae.n) * abn) / len2;
}

function lerpLngLat(a: LngLat, b: LngLat, t: number): LngLat {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function cutsForDrawingEdge(a: LngLat, b: LngLat, shared: SharedSeams, base: number, top: number): LngLat[] {
  const ae = toEn(a, shared.origin);
  const be = toEn(b, shared.origin);
  const cuts: LngLat[] = [];
  for (const span of nearbySpans(a, b, base, top, shared)) {
    if (pointOnSegment(toEn(span.a, shared.origin), ae, be, 0.12)) cuts.push(span.a);
    if (pointOnSegment(toEn(span.b, shared.origin), ae, be, 0.12)) cuts.push(span.b);
  }
  return cuts;
}

function pieceCoveredBySeam(
  a: LngLat,
  b: LngLat,
  shared: SharedSeams,
  base: number,
  top: number,
): boolean {
  if (shared.keys.has(edgeIdentity(a, b, base, top))) return true;
  const mid = {
    e: (toEn(a, shared.origin).e + toEn(b, shared.origin).e) / 2,
    n: (toEn(a, shared.origin).n + toEn(b, shared.origin).n) / 2,
  };
  for (const span of nearbySpans(a, b, base, top, shared)) {
    if (pointOnSegment(mid, toEn(span.a, shared.origin), toEn(span.b, shared.origin), 0.15)) return true;
  }
  return false;
}

const CLIP_AXIS_DEG = 1e-6;
const CLIP_EDGE_MIN_M = 12;
const CLIP_LONG_M = 18;
const CLIP_RUN_GAP_M = 3;
const CLIP_RAIL_SPAN_M = 80;
const CLIP_BUFFER_GAPS_M = [9.53, 19.06];
const CLIP_BUFFER_GAP_TOL_M = 0.8;

function quantizeAxis(value: number): string {
  return value.toFixed(6);
}

function parseRailKey(key: string): { kind: "lng" | "lat"; value: number } | null {
  const split = key.indexOf(":");
  if (split < 0) return null;
  const kind = key.slice(0, split);
  const value = Number(key.slice(split + 1));
  if ((kind !== "lng" && kind !== "lat") || !Number.isFinite(value)) return null;
  return { kind, value };
}

function isBufferPairM(distanceM: number): boolean {
  return CLIP_BUFFER_GAPS_M.some((gap) => Math.abs(distanceM - gap) <= CLIP_BUFFER_GAP_TOL_M);
}

function clipRailKey(kind: "lng" | "lat", value: number): string {
  return `${kind}:${quantizeAxis(value)}`;
}

function ringCentroid(ring: LngLat[]): LngLat {
  const origin = metricOrigin(ring[0][0], ring[0][1]);
  let e = 0;
  let n = 0;
  for (const point of ring) {
    const en = toEn(point, origin);
    e += en.e;
    n += en.n;
  }
  const count = Math.max(ring.length, 1);
  return fromEn({ e: e / count, n: n / count }, origin);
}

function mergeRunSpanM(intervals: Array<[number, number]>, gapM: number): { runs: number; spanM: number } {
  if (!intervals.length) return { runs: 0, spanM: 0 };
  const sorted = intervals
    .map(([a, b]) => (a < b ? [a, b] : [b, a]) as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const runs: Array<[number, number]> = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    const prev = runs[runs.length - 1];
    const next = sorted[i];
    if (next[0] <= prev[1] + gapM) prev[1] = Math.max(prev[1], next[1]);
    else runs.push(next);
  }
  return { runs: runs.length, spanM: runs[runs.length - 1][1] - runs[0][0] };
}

function intervalOverlapM(a0: number, a1: number, b0: number, b1: number): number {
  const aLo = Math.min(a0, a1);
  const aHi = Math.max(a0, a1);
  const bLo = Math.min(b0, b1);
  const bHi = Math.max(b0, b1);
  return Math.max(0, Math.min(aHi, bHi) - Math.max(aLo, bLo));
}

function opposingPairCount(hits: Array<{ along0: number; along1: number; side: number }>): number {
  const plus = hits.filter((hit) => hit.side > 0);
  const minus = hits.filter((hit) => hit.side < 0);
  let pairs = 0;
  for (const a of plus) {
    for (const b of minus) {
      if (intervalOverlapM(a.along0, a.along1, b.along0, b.along1) >= CLIP_EDGE_MIN_M) pairs += 1;
    }
  }
  return pairs;
}

function isRegularPanelPitch(hits: Array<{ along0: number; along1: number }>): boolean {
  if (hits.length < 6) return false;
  const lens = hits.map((hit) => Math.abs(hit.along1 - hit.along0)).sort((a, b) => a - b);
  const median = lens[lens.length >> 1];
  if (median < 4 || median > 24) return false;
  const within = lens.filter((len) => Math.abs(len - median) <= 2).length;
  return within / lens.length >= 0.75;
}

function mercatorX(lng: number): number {
  return (lng + 180) / 360;
}

function mercatorY(lat: number): number {
  const s = Math.sin((lat * Math.PI) / 180);
  return (1 - Math.log((1 + s) / (1 - s)) / (2 * Math.PI)) / 2;
}

const CLIP_TILE_ZOOMS = [14, 15, 16];
const CLIP_TILE_FRACS = [0, 64 / 4096, -64 / 4096, 128 / 4096, -128 / 4096];
const CLIP_TILE_EPS_M = 1.25;
/** Vertex jitter on the same clip line, well below 8 m panel pitch. */
const CLIP_RAIL_MATCH_M = 0.75;
const WORLD_M = 40075016.686;

function axisSeparationM(kind: "lng" | "lat", a: number, b: number, cos: number): number {
  return kind === "lat"
    ? Math.abs(a - b) * METERS_PER_DEG
    : Math.abs(a - b) * METERS_PER_DEG * cos;
}

function isMercatorClipValue(kind: "lng" | "lat", value: number, cos: number): boolean {
  const frac = kind === "lng" ? mercatorX(value) : mercatorY(value);
  for (const zoom of CLIP_TILE_ZOOMS) {
    const metersPerTile = (WORLD_M / 2 ** zoom) * (kind === "lng" ? 1 : cos);
    for (const offset of CLIP_TILE_FRACS) {
      const scaled = frac * 2 ** zoom - offset;
      const distM = Math.abs(scaled - Math.round(scaled)) * metersPerTile;
      if (distM <= CLIP_TILE_EPS_M) return true;
    }
  }
  return false;
}

/**
 * Vector tiles clip polygons on a constant-lng / constant-lat grid. Those seams
 * line up through every building they cut, unlike architectural tessellation.
 */
export function findClipRails(components: NormalizedComponent[]): Set<string> {
  type Hit = { id: string; along0: number; along1: number; side: number; base: number; top: number };
  const buckets = new Map<string, Hit[]>();
  const origin = components[0]
    ? metricOrigin(components[0].outer[0][0], components[0].outer[0][1])
    : metricOrigin(0, 0);
  for (const component of components) {
    if (component.outer.length < 3) continue;
    const centroid = ringCentroid(component.outer);
    const id = component.sourceId ?? component.identity;
    const ring = component.outer;
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      const ae = toEn(a, origin);
      const be = toEn(b, origin);
      const len = Math.hypot(be.e - ae.e, be.n - ae.n);
      if (len < CLIP_EDGE_MIN_M) continue;
      if (Math.abs(a[0] - b[0]) < CLIP_AXIS_DEG) {
        const key = clipRailKey("lng", (a[0] + b[0]) / 2);
        const side = Math.sign(centroid[0] - a[0]) || 1;
        const hit = { id, along0: ae.n, along1: be.n, side, base: component.base, top: component.top };
        const list = buckets.get(key);
        if (list) list.push(hit);
        else buckets.set(key, [hit]);
      } else if (Math.abs(a[1] - b[1]) < CLIP_AXIS_DEG) {
        const key = clipRailKey("lat", (a[1] + b[1]) / 2);
        const side = Math.sign(centroid[1] - a[1]) || 1;
        const hit = { id, along0: ae.e, along1: be.e, side, base: component.base, top: component.top };
        const list = buckets.get(key);
        if (list) list.push(hit);
        else buckets.set(key, [hit]);
      }
    }
  }
  type Candidate = {
    keys: string[];
    kind: "lng" | "lat";
    value: number;
    ids: number;
    sides: Set<number>;
    runs: number;
    spanM: number;
    longCount: number;
    splitSameId: boolean;
    pairs: number;
    regular: boolean;
    heights: number;
    mercator: boolean;
  };

  const clustered = clusterRailBuckets(buckets, origin.cos);
  const candidates: Candidate[] = clustered.map((cluster) => {
    const hits = cluster.hits;
    const ids = new Set(hits.map((hit) => hit.id));
    const sides = new Set(hits.map((hit) => hit.side));
    const { runs, spanM } = mergeRunSpanM(
      hits.map((hit) => [hit.along0, hit.along1]),
      CLIP_RUN_GAP_M,
    );
    return {
      keys: cluster.keys,
      kind: cluster.kind,
      value: cluster.value,
      ids: ids.size,
      sides,
      runs,
      spanM,
      longCount: hits.filter((hit) => Math.abs(hit.along1 - hit.along0) >= CLIP_LONG_M).length,
      splitSameId: [...ids].some((id) => hits.filter((hit) => hit.id === id).length >= 2),
      pairs: opposingPairCount(hits),
      regular: isRegularPanelPitch(hits),
      heights: new Set(hits.map((hit) => `${hit.base.toFixed(2)}|${hit.top.toFixed(2)}`)).size,
      mercator: isMercatorClipValue(cluster.kind, cluster.value, origin.cos),
    };
  });

  const rails = new Set<string>();
  const addCandidate = (info: Candidate) => {
    for (const key of info.keys) rails.add(key);
  };
  for (const info of candidates) {
    if (info.splitSameId && info.sides.size >= 2 && info.spanM >= CLIP_EDGE_MIN_M) addCandidate(info);
    else if (info.longCount >= 2 && info.spanM >= CLIP_RAIL_SPAN_M && info.sides.size >= 2 && (info.runs >= 2 || info.ids >= 3)) addCandidate(info);
    else if (info.pairs >= 3 && info.spanM >= CLIP_RAIL_SPAN_M && !info.regular) addCandidate(info);
    else if (info.pairs >= 2 && info.heights >= 2 && info.spanM >= CLIP_RAIL_SPAN_M) addCandidate(info);
    else if (info.mercator && info.spanM >= 40 && (info.ids >= 2 || info.pairs >= 1 || info.longCount >= 1)) addCandidate(info);
  }
  for (let i = 0; i < candidates.length; i++) {
    const infoI = candidates[i];
    if (infoI.spanM < CLIP_RAIL_SPAN_M || infoI.ids < 3) continue;
    for (let j = i + 1; j < candidates.length; j++) {
      const infoJ = candidates[j];
      if (infoJ.kind !== infoI.kind) continue;
      if (infoJ.spanM < CLIP_RAIL_SPAN_M || infoJ.ids < 3) continue;
      if (!isBufferPairM(axisSeparationM(infoI.kind, infoI.value, infoJ.value, origin.cos))) continue;
      const opposite = [...infoI.sides].some((side) => infoJ.sides.has(-side));
      if (!opposite) continue;
      addCandidate(infoI);
      addCandidate(infoJ);
    }
  }
  return rails;
}

function clusterRailBuckets(
  buckets: Map<string, Array<{ id: string; along0: number; along1: number; side: number; base: number; top: number }>>,
  cos: number,
): Array<{
  keys: string[];
  kind: "lng" | "lat";
  value: number;
  hits: Array<{ id: string; along0: number; along1: number; side: number; base: number; top: number }>;
}> {
  const byKind: Record<"lng" | "lat", Array<{ key: string; value: number }>> = { lng: [], lat: [] };
  for (const key of buckets.keys()) {
    const parsed = parseRailKey(key);
    if (parsed) byKind[parsed.kind].push({ key, value: parsed.value });
  }
  const clusters: Array<{
    keys: string[];
    kind: "lng" | "lat";
    value: number;
    hits: Array<{ id: string; along0: number; along1: number; side: number; base: number; top: number }>;
  }> = [];
  for (const kind of ["lng", "lat"] as const) {
    const items = byKind[kind].sort((a, b) => a.value - b.value);
    let keys: string[] = [];
    let lastValue = NaN;
    const flush = () => {
      if (!keys.length) return;
      const hits = keys.flatMap((key) => buckets.get(key) ?? []);
      const value = keys.reduce((sum, key) => sum + (parseRailKey(key)?.value ?? 0), 0) / keys.length;
      clusters.push({ keys, kind, value, hits });
      keys = [];
    };
    for (const item of items) {
      if (keys.length && axisSeparationM(kind, item.value, lastValue, cos) > CLIP_RAIL_MATCH_M) flush();
      keys.push(item.key);
      lastValue = item.value;
    }
    flush();
  }
  return clusters;
}

export function isClipRailEdge(a: LngLat, b: LngLat, rails: Set<string>): boolean {
  if (!rails.size) return false;
  const cos = Math.max(Math.cos((a[1] * Math.PI) / 180), 0.2);
  let kind: "lng" | "lat" | null = null;
  let value = 0;
  if (Math.abs(a[0] - b[0]) < CLIP_AXIS_DEG) {
    kind = "lng";
    value = (a[0] + b[0]) / 2;
  } else if (Math.abs(a[1] - b[1]) < CLIP_AXIS_DEG) {
    kind = "lat";
    value = (a[1] + b[1]) / 2;
  }
  if (!kind) return false;
  for (const key of rails) {
    const parsed = parseRailKey(key);
    if (parsed?.kind === kind && axisSeparationM(kind, parsed.value, value, cos) <= CLIP_RAIL_MATCH_M) return true;
  }
  return false;
}

export function planComponent(
  component: NormalizedComponent,
  shared: SharedSeams,
  diagnostics: GeometryDiagnostics,
  rails: Set<string> = new Set(),
): FacadeSeg[] {
  const roofZ = component.top + ROOF_LIFT_M;
  const origin = metricOrigin(component.outer[0][0], component.outer[0][1]);
  const drawing = simplifyClosed(component.outer, origin);
  const offset = offsetRing(drawing, WALL_OUTSET_M);
  const segs: FacadeSeg[] = [];
  if (drawing.length > MAX_ROOF_SEGMENTS) {
    diagnostics.roofFallbacks += 1;
  } else {
    for (let i = 0; i < drawing.length; i++) {
      const a = drawing[i];
      const b = drawing[(i + 1) % drawing.length];
      const oa = offset[i];
      const ob = offset[(i + 1) % offset.length];
      const cuts = cutsForDrawingEdge(a, b, shared, component.base, component.top);
      for (const [p0, p1] of splitAtPoints(a, b, cuts, origin)) {
        if (pieceCoveredBySeam(p0, p1, shared, component.base, component.top)) continue;
        if (isClipRailEdge(p0, p1, rails)) continue;
        const t0 = paramOnEdge(p0, a, b, origin);
        const t1 = paramOnEdge(p1, a, b, origin);
        const o0 = lerpLngLat(oa, ob, t0);
        const o1 = lerpLngLat(oa, ob, t1);
        segs.push({ a: [o0[0], o0[1], roofZ], b: [o1[0], o1[1], roofZ] });
        diagnostics.roofSegments += 1;
      }
    }
  }
  const posts = component.roofOnly ? [] : selectSignificantCorners(component.outer);
  const originalOffset = offsetRing(component.outer, WALL_OUTSET_M);
  for (const index of posts) {
    const prev = component.outer[(index - 1 + component.outer.length) % component.outer.length];
    const curr = component.outer[index];
    const next = component.outer[(index + 1) % component.outer.length];
    const leftShared = shared.keys.has(edgeIdentity(prev, curr, component.base, component.top));
    const rightShared = shared.keys.has(edgeIdentity(curr, next, component.base, component.top));
    if (leftShared && rightShared) continue;
    if (isClipRailEdge(prev, curr, rails) && isClipRailEdge(curr, next, rails)) continue;
    const p = originalOffset[index] || curr;
    segs.push({ a: [p[0], p[1], component.base], b: [p[0], p[1], roofZ] });
    diagnostics.selectedPosts += 1;
  }
  return segs;
}

export function planNormalizedInk(
  components: NormalizedComponent[],
  opts?: { seamsOnly?: boolean },
): { segs: FacadeSeg[]; diagnostics: GeometryDiagnostics } {
  const selected = components.slice(0, MAX_COMPONENTS);
  const diagnostics: GeometryDiagnostics = {
    sourceFeatureCount: 0,
    normalizedCount: selected.length,
    duplicatesRemoved: 0,
    invalidRings: 0,
    slabsOmitted: 0,
    sharedEdgesRemoved: 0,
    roofFallbacks: 0,
    selectedPosts: 0,
    roofSegments: 0,
    totalSegments: 0,
    budgetDropped: Math.max(0, components.length - selected.length),
  };
  const shared = suppressSharedEdges(selected);
  const rails = findClipRails(selected);
  diagnostics.sharedEdgesRemoved = shared.keys.size;
  const segs: FacadeSeg[] = [];
  if (!opts?.seamsOnly) {
    for (const component of selected) {
      const next = planComponent(component, shared, diagnostics, rails);
      if (segs.length + next.length > MAX_SEGMENTS) {
        diagnostics.budgetDropped += 1;
        continue;
      }
      segs.push(...next);
    }
  }
  for (const span of shared.spans) {
    if (segs.length >= MAX_SEGMENTS) {
      diagnostics.budgetDropped += 1;
      break;
    }
    if (isClipRailEdge(span.a, span.b, rails)) continue;
    const z = span.top + ROOF_SEAM_LIFT_M;
    segs.push({ a: [span.a[0], span.a[1], z], b: [span.b[0], span.b[1], z] });
    diagnostics.roofSegments += 1;
  }
  diagnostics.totalSegments = segs.length;
  return { segs, diagnostics };
}

export function geometrySignature(segs: FacadeSeg[]): string {
  return segs
    .map((seg) => seg.a.concat(seg.b).map((value) => value.toFixed(6)).join(","))
    .sort()
    .join("|");
}
