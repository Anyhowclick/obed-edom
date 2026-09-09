import type { LayerSpecification, LineLayerSpecification } from "maplibre-gl";

type LegacyFunction = { base?: number; stops: [number, number][] };

function isLegacyFunction(value: unknown): value is LegacyFunction {
  return !!value && typeof value === "object" && Array.isArray((value as LegacyFunction).stops);
}

const NUMERIC_EXPRESSION_OPS = new Set(["interpolate", "step", "case", "match", "get"]);

function isNumericExpression(value: unknown): value is unknown[] {
  return Array.isArray(value) && typeof value[0] === "string" && NUMERIC_EXPRESSION_OPS.has(value[0]);
}

type LineWidth = NonNullable<LineLayerSpecification["paint"]>["line-width"];

function scaledLineWidth(width: unknown, factor: number): LineWidth {
  if (width === undefined) return factor;
  if (typeof width === "number") return width * factor;
  if (isLegacyFunction(width)) {
    return { ...width, stops: width.stops.map(([zoom, value]) => [zoom, value * factor] as [number, number]) } as LineWidth;
  }
  if (isNumericExpression(width)) return ["*", factor, width] as unknown as LineWidth;
  return width as LineWidth;
}

/** Scales `line-width` on every line layer; leaves non-numeric expressions untouched. */
export function thinLineWidths(layers: LayerSpecification[], factor: number): LayerSpecification[] {
  return layers.map((layer): LayerSpecification => {
    if (layer.type !== "line") return layer;
    return {
      ...layer,
      paint: { ...layer.paint, "line-width": scaledLineWidth(layer.paint?.["line-width"], factor) },
    };
  });
}
