import type { Map as MapLibreMap } from "maplibre-gl";
import {
  ADMIN0_FILL_OPACITY,
  ADMIN0_LINE_OPACITY,
  ADMIN1_FILL_OPACITY,
  ADMIN1_LINE_OPACITY,
  admin0PaintExpression,
  admin1PaintExpression,
} from "./overlays";

/** The subset of `MapLibreMap` the isolate-pair visibility toggles touch — kept narrow so this
 * logic is testable against a fake map without a real MapLibre instance. */
export type CaptureMapLike = Pick<MapLibreMap, "getLayer" | "setPaintProperty" | "setLayoutProperty">;

const HIGHLIGHT_LAYERS: Array<[string, "fill-opacity" | "line-opacity"]> = [
  ["admin0-fill", "fill-opacity"],
  ["admin0-line", "line-opacity"],
  ["admin1-fill", "fill-opacity"],
  ["admin1-line", "line-opacity"],
];

/** `value === null` restores each layer to its authored (feature-state/id-list driven) opacity
 * expression; any number pins every highlight layer present on `map` to that flat opacity. */
export function setHighlightOpacity(
  map: CaptureMapLike,
  value: number | null,
  highlights: string[],
  highlightColours?: Record<string, string>
): void {
  for (const [id, property] of HIGHLIGHT_LAYERS) {
    if (!map.getLayer(id)) continue;
    if (value !== null) {
      map.setPaintProperty(id, property, value);
      continue;
    }
    const admin1On = property === "fill-opacity" ? ADMIN1_FILL_OPACITY : ADMIN1_LINE_OPACITY;
    const admin0On = property === "fill-opacity" ? ADMIN0_FILL_OPACITY : ADMIN0_LINE_OPACITY;
    map.setPaintProperty(
      id,
      property,
      id.startsWith("admin1")
        ? admin1PaintExpression(highlights, admin1On, highlightColours)
        : admin0PaintExpression(admin0On)
    );
  }
}

/** Hides the highlight layers for the "base" capture of an isolate pair — the base always drops
 * the highlight, regardless of isolate mode. */
export function isolatePairBaseVisibility(map: CaptureMapLike, highlights: string[]): void {
  setHighlightOpacity(map, 0, highlights);
}

/** The cutout capture's toggle. The isolate mask itself must never bake into either raster, so
 * it is hidden first, unconditionally; highlight fill then returns so coloured regions land in
 * the piece. No-fill (`none`) codes stay unpainted via the restored opacity expressions. */
export function isolatePairCutoutVisibility(
  map: CaptureMapLike,
  highlights: string[],
  highlightColours?: Record<string, string>
): void {
  if (map.getLayer("isolate-fill")) map.setLayoutProperty("isolate-fill", "visibility", "none");
  setHighlightOpacity(map, null, highlights, highlightColours);
}
