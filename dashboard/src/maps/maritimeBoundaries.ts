import type { FilterSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";

/** OpenMapTiles `maritime=1` is EEZ / territorial-sea lines. Positron and Bright already drop
 * them; Dark and Fiord paint them as country borders. */
export const NO_MARITIME: FilterSpecification = ["!=", ["get", "maritime"], 1];
/** Legacy form — Toner still uses `["==", "admin_level", 2]`; MapLibre rejects mixing that with expressions. */
export const NO_MARITIME_LEGACY: FilterSpecification = ["!=", "maritime", 1];

const LEGACY_OPS = new Set(["==", "!=", ">", ">=", "<", "<=", "in", "!in", "has", "!has", "all", "any", "none"]);

type FilterableLayer = LayerSpecification & { filter?: FilterSpecification };

function isGetMaritime(node: unknown): boolean {
  return Array.isArray(node) && node[0] === "get" && node[1] === "maritime";
}

/** True when `filter` is Mapbox legacy syntax (property name as a string), not an expression. */
export function isLegacyFilter(filter: unknown): boolean {
  if (!Array.isArray(filter) || typeof filter[0] !== "string" || !LEGACY_OPS.has(filter[0])) return false;
  const op = filter[0];
  if (op === "all" || op === "any" || op === "none") return filter.length > 1 && filter.slice(1).every(isLegacyFilter);
  if (op === "has" || op === "!has") return typeof filter[1] === "string";
  return typeof filter[1] === "string";
}

/** True when `filter` already excludes OpenMapTiles maritime boundaries (legacy or expression). */
export function filterExcludesMaritime(filter: unknown): boolean {
  if (!Array.isArray(filter) || filter.length < 2) return false;
  if (filter[0] === "!=") {
    return isGetMaritime(filter[1]) || filter[1] === "maritime";
  }
  if (filter[0] === "all") return filter.slice(1).some(filterExcludesMaritime);
  return false;
}

function withNoMaritime(filter: FilterSpecification | undefined): FilterSpecification {
  if (filterExcludesMaritime(filter)) return filter as FilterSpecification;
  const clause = isLegacyFilter(filter) ? NO_MARITIME_LEGACY : NO_MARITIME;
  if (filter == null) return NO_MARITIME;
  if (Array.isArray(filter) && filter[0] === "all") {
    return [...filter, clause] as FilterSpecification;
  }
  return ["all", filter, clause] as FilterSpecification;
}

function isBoundaryLayer(layer: LayerSpecification): layer is FilterableLayer {
  return ("source-layer" in layer && layer["source-layer"] === "boundary") || layer.id.startsWith("boundary");
}

/** Drop international sea / EEZ lines from every `boundary` layer, matching Positron. */
export function withoutMaritimeBoundaries(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers.map((layer) => {
      if (!isBoundaryLayer(layer)) return layer;
      const filter = withNoMaritime(layer.filter);
      if (filter === layer.filter) return layer;
      return { ...layer, filter };
    }),
  };
}
