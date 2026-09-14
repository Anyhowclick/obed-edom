import { fragmentIdentity, inkFragmentKey as geometryFragmentKey, type WireFeature } from "./borderlandsGeometry";
import { authoredZoomFromMap, inkFullWidthCssPx } from "./borderlandsProjection";

export const INK_POLICY_VERSION = 3;

export type InkRebuildInput = {
  styleGeneration: number;
  sourceRevision: number;
  sourceReady: boolean;
  zoom: number;
  lng: number;
  lat: number;
  bearing: number;
  pitch: number;
  viewportW: number;
  viewportH: number;
  buildingsVisible: boolean;
  west?: number;
  south?: number;
  east?: number;
  north?: number;
};

export type CollectKind = "ok" | "loading" | "unavailable" | "error";

export type CollectResult =
  | { kind: "ok"; features: WireFeature[] }
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "error" };

export function inkPlanZoom(zoom: number): number {
  return zoom;
}

export function inkRebuildKey(opts: InkRebuildInput): string {
  const bounds = [opts.west, opts.south, opts.east, opts.north]
    .map((value) => (value == null || !Number.isFinite(value) ? "" : value.toFixed(6)))
    .join(",");
  return [
    INK_POLICY_VERSION,
    opts.styleGeneration,
    opts.sourceRevision,
    opts.sourceReady ? 1 : 0,
    opts.buildingsVisible ? 1 : 0,
    opts.zoom.toFixed(4),
    opts.lng.toFixed(6),
    opts.lat.toFixed(6),
    opts.bearing.toFixed(3),
    opts.pitch.toFixed(3),
    Math.round(opts.viewportW),
    Math.round(opts.viewportH),
    bounds,
  ].join(":");
}

/** Authoritative snapshots always replace. Loading/error keep the previous mesh. */
export function shouldReplaceInkMesh(result: CollectResult | { kind?: string }, _prevCount = 0, force = false): boolean {
  if (force) return true;
  return (result as CollectResult).kind === "ok";
}

export function inkFragmentKey(id: unknown, rings: number[][][], extras?: { base?: number; top?: number; source?: string; sourceLayer?: string }): string {
  const outer = rings[0];
  if (!outer?.length) return `${id ?? "anon"}#empty`;
  return geometryFragmentKey({
    id,
    source: extras?.source,
    sourceLayer: extras?.sourceLayer,
    geometry: { type: rings.length > 1 ? "MultiPolygon" : "Polygon", coordinates: rings.length > 1 ? rings.map((ring) => [ring]) : [outer, ...rings.slice(1)] },
    properties: { render_height: extras?.top ?? 20, render_min_height: extras?.base ?? 0 },
  }) || `${id ?? "anon"}#empty`;
}

export function inkFragmentIdentity(feature: WireFeature): string[] {
  return feature.geometry
    ? [geometryFragmentKey(feature) || fragmentIdentity({
        source: feature.source || "",
        sourceLayer: feature.sourceLayer || "building",
        sourceId: feature.id == null ? null : String(feature.id),
        base: 0,
        top: 0,
        outer: [[0, 0], [1, 0], [0, 1]],
        holes: [],
      })]
    : [];
}

export function inkWidthCssPx(mapZoom: number, authoredZoomDelta = 0): number {
  return inkFullWidthCssPx(authoredZoomFromMap(mapZoom, authoredZoomDelta));
}

export function buildingLayerActive(opts: { hasLayer: boolean; visibility: unknown; minzoom?: number; maxzoom?: number; zoom: number }): boolean {
  if (!opts.hasLayer || opts.visibility === "none") return false;
  const minzoom = opts.minzoom ?? 0;
  const maxzoom = opts.maxzoom ?? 25;
  return opts.zoom >= minzoom && opts.zoom < maxzoom;
}
