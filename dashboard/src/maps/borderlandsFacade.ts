import {
  buildingExtents as extentsFromFeature,
  featureMayBeVisible,
  featureNearCenter,
  geometrySignature,
  metricOrigin,
  normalizeBuildings,
  normalizeFeature,
  planNormalizedInk,
  ringIntersectsBounds,
  toEn,
  type FacadeSeg,
  type GeometryDiagnostics,
  type NormalizedComponent,
  type WireFeature,
} from "./borderlandsGeometry";

export type { FacadeSeg, WireFeature } from "./borderlandsGeometry";
export { ROOF_LIFT_M as ROOF_BIAS_M, WALL_OUTSET_M } from "./borderlandsGeometry";

export function buildingExtents(feature: WireFeature): { base: number; top: number } | null {
  return extentsFromFeature(feature);
}

export function ringsOf(geometry: WireFeature["geometry"]): number[][][] {
  if (geometry.type === "Polygon") return (geometry.coordinates as number[][][]) || [];
  if (geometry.type === "MultiPolygon") return ((geometry.coordinates as number[][][][]) || []).flat();
  return [];
}

export function planBuildingFacade(feature: WireFeature, _zoom = 16): FacadeSeg[] {
  const { segs } = planNormalizedInk(normalizeFeature(feature));
  return segs;
}

function componentNearCenter(component: NormalizedComponent, center: { lng: number; lat: number }, radiusM: number): boolean {
  const origin = metricOrigin(center.lng, center.lat);
  let e = 0;
  let n = 0;
  for (const point of component.outer) {
    const en = toEn(point, origin);
    e += en.e;
    n += en.n;
  }
  const count = Math.max(component.outer.length, 1);
  return Math.hypot(e / count, n / count) <= radiusM;
}

export function planBuildingsInk(
  features: WireFeature[],
  opts?: {
    bounds?: { west: number; south: number; east: number; north: number };
    padDeg?: number;
    center?: { lng: number; lat: number };
    radiusM?: number;
  }
): { segs: FacadeSeg[]; components: NormalizedComponent[]; diagnostics: GeometryDiagnostics; signature: string } {
  const gated = features.filter((feature) => {
    if (opts?.center && opts.radiusM != null && !featureNearCenter(feature, opts.center, opts.radiusM)) return false;
    if (opts?.bounds && !featureMayBeVisible(feature, opts.bounds, opts.padDeg)) return false;
    return true;
  });
  const { components, diagnostics } = normalizeBuildings(gated);
  const visible = components.filter((component) => {
    if (opts?.bounds && !ringIntersectsBounds(component.outer, opts.bounds, opts.padDeg)) return false;
    if (opts?.center && opts.radiusM != null && !componentNearCenter(component, opts.center, opts.radiusM)) return false;
    return true;
  });
  diagnostics.normalizedCount = visible.length;
  diagnostics.budgetDropped += Math.max(0, components.length - visible.length);
  const planned = planNormalizedInk(visible);
  diagnostics.sharedEdgesRemoved = planned.diagnostics.sharedEdgesRemoved;
  diagnostics.roofFallbacks = planned.diagnostics.roofFallbacks;
  diagnostics.selectedPosts = planned.diagnostics.selectedPosts;
  diagnostics.roofSegments = planned.diagnostics.roofSegments;
  diagnostics.totalSegments = planned.diagnostics.totalSegments;
  diagnostics.budgetDropped += planned.diagnostics.budgetDropped;
  return { segs: planned.segs, components, diagnostics, signature: geometrySignature(planned.segs) };
}
