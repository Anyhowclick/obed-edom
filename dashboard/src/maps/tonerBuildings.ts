import type { LayerSpecification } from "maplibre-gl";

const BUILDING_FILL_ID = "building_fill";

/** Drops the solid `building_fill` (minzoom 16) so the `building_pattern` hatch (minzoom 14)
 * stays the only building paint at every zoom — no fill-to-hatch cliff. */
export function withoutSolidBuildings(layers: LayerSpecification[]): LayerSpecification[] {
  if (!layers.some((layer) => layer.id === BUILDING_FILL_ID)) return layers;
  return layers.filter((layer) => layer.id !== BUILDING_FILL_ID);
}
