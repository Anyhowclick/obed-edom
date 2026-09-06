import type { Map as MapLibreMap } from "maplibre-gl";
import type { MapsLayerFilterId } from "./types";

type LayerBits = { id: string; type?: string; "source-layer"?: string };

const SKIP = new Set(["background", "ne2-shaded-fallback", "admin0-fill", "admin0-line"]);

function bits(layer: { id: string; type?: string; "source-layer"?: string }): LayerBits {
  return { id: layer.id, type: layer.type, "source-layer": layer["source-layer"] };
}

function sourceLayer(layer: LayerBits): string {
  return layer["source-layer"] || "";
}

export function filterForLayer(layer: LayerBits): MapsLayerFilterId | null {
  const sl = sourceLayer(layer);
  const id = layer.id.toLowerCase();
  if (id.includes("railway") || id.includes("rail_")) return "rail";
  if (id.includes("shield")) return "shields";
  if (sl === "transportation_name") return "roadnames";
  if (sl === "poi" || sl === "housenumber" || sl === "aerodrome_label" || id.startsWith("poi_")) return "pois";
  if (sl === "transportation" || sl === "aeroway") return "roads";
  if (sl === "building" || id.includes("building")) return "buildings";
  if (sl === "place" || sl === "water_name" || id.startsWith("label_")) return "labels";
  if (sl === "boundary" || id.startsWith("boundary_")) return "boundaries";
  return null;
}

export function applyLayerFilters(map: MapLibreMap, hidden: readonly MapsLayerFilterId[]): void {
  const hide = new Set(hidden);
  const style = map.getStyle();
  for (const layer of style.layers || []) {
    if (SKIP.has(layer.id) || layer.id.startsWith("churches-")) continue;
    const match = filterForLayer(bits(layer));
    if (!match) continue;
    map.setLayoutProperty(layer.id, "visibility", hide.has(match) ? "none" : "visible");
  }
}
