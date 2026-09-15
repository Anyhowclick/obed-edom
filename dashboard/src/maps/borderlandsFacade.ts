import {
  buildingExtents as extentsFromFeature,
  featureMayBeVisible,
  geometrySignature,
  normalizeBuildings,
  normalizeFeature,
  planNormalizedInk,
  ringIntersectsBounds,
  type FacadeSeg,
  type GeometryDiagnostics,
  type NormalizedComponent,
  type WireFeature,
} from "./borderlandsGeometry";

export type { FacadeSeg, WireFeature } from "./borderlandsGeometry";
export { ROOF_LIFT_M as ROOF_BIAS_M, WALL_OUTSET_M } from "./borderlandsGeometry";

export function buildingExtents(feature: WireFeature): { base: number; top: number; roofOnly: boolean } | null {
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

export function planBuildingsInk(
  features: WireFeature[],
  opts?: {
    bounds?: { west: number; south: number; east: number; north: number };
    padDeg?: number;
    seamsOnly?: boolean;
  }
): { segs: FacadeSeg[]; components: NormalizedComponent[]; diagnostics: GeometryDiagnostics; signature: string } {
  const gated = opts?.bounds
    ? features.filter((feature) => featureMayBeVisible(feature, opts.bounds!, opts.padDeg))
    : features;
  const { components, diagnostics } = normalizeBuildings(gated);
  const visible = opts?.bounds
    ? components.filter((component) => ringIntersectsBounds(component.outer, opts.bounds!, opts.padDeg))
    : components;
  diagnostics.normalizedCount = visible.length;
  diagnostics.budgetDropped += Math.max(0, components.length - visible.length);
  const planned = planNormalizedInk(visible, { seamsOnly: opts?.seamsOnly });
  diagnostics.sharedEdgesRemoved = planned.diagnostics.sharedEdgesRemoved;
  diagnostics.roofFallbacks = planned.diagnostics.roofFallbacks;
  diagnostics.selectedPosts = planned.diagnostics.selectedPosts;
  diagnostics.roofSegments = planned.diagnostics.roofSegments;
  diagnostics.totalSegments = planned.diagnostics.totalSegments;
  diagnostics.budgetDropped += planned.diagnostics.budgetDropped;
  return { segs: planned.segs, components, diagnostics, signature: geometrySignature(planned.segs) };
}
