import type { PortableStyle } from "./watercolourStyle";

const PAPER = "#E8E4D8";
const WATER = "#6B91A0";
const COAST = "#141312";
const ICE = "#E6E8EA";
const PARK = "#6A7B5C";
const WOOD = "#3F5346";
const WETLAND = "#3A5F5C";
const SAND = "#D6D0C0";
const BUILDING = "#D5D0C6";
const INK = "#141312";
const RESIDENTIAL = "#C9C5BA";
const AEROWAY = "#B8B4AA";
const ROAD = "#F3F1EB";
const ROAD_MAJOR = "#EDEAE3";
const RAIL = "#1A1916";
const HALO = "#F0EEE8";
const CASING_SCALE = 1.15;

function scaledWidth(value: unknown, scale: number): unknown {
  if (typeof value === "number") return value * scale;
  if (!Array.isArray(value) || (value[0] !== "interpolate" && value[0] !== "step")) return value;
  const next = [...value];
  const firstOutput = value[0] === "interpolate" ? 4 : 2;
  for (let index = firstOutput; index < next.length; index += 2) {
    if (typeof next[index] === "number") next[index] = next[index] * scale;
  }
  return next;
}

function withScaledWidth(paint: Record<string, unknown>, scale: number): Record<string, unknown> {
  const width = scaledWidth(paint["line-width"], scale);
  return width === undefined ? paint : { ...paint, "line-width": width };
}

function withoutPattern(paint: Record<string, unknown>): Record<string, unknown> {
  const next = { ...paint };
  delete next["background-pattern"];
  delete next["fill-pattern"];
  delete next["line-pattern"];
  return next;
}

function isWaterFill(layer: Record<string, unknown>): boolean {
  return layer.type === "fill" && layer["source-layer"] === "water";
}

export function buildBorderlandsStyle(base: PortableStyle, options: { sourceUrl?: string; glyphsUrl?: string } = {}): { style: PortableStyle } {
  const style = structuredClone(base);
  if (options.sourceUrl) {
    for (const source of Object.values(style.sources)) {
      if (source && typeof source === "object" && (source as { type?: unknown }).type === "vector") {
        const vector = source as { url?: string; tiles?: unknown };
        vector.url = options.sourceUrl;
        delete vector.tiles;
      }
    }
  }
  if (options.glyphsUrl) (style as PortableStyle & { glyphs?: string }).glyphs = options.glyphsUrl;

  const out: Array<Record<string, unknown>> = [];
  for (const layer of style.layers) {
    const next = structuredClone(layer);
    const originalPaint = (next.paint || {}) as Record<string, unknown>;
    const paint = withoutPattern(originalPaint);
    const layerId = String(next.id || "");
    const sourceLayer = String(next["source-layer"] || "");
    const key = `${sourceLayer} ${layerId}`;

    if (next.type === "background") {
      next.paint = { ...paint, "background-color": PAPER };
    } else if (next.type === "raster") {
      next.paint = { ...paint, "raster-saturation": -0.55, "raster-contrast": 0.2, "raster-opacity": 0.35 };
    } else if (next.type === "fill" && (sourceLayer === "water" || /(^|[-_])water/.test(layerId))) {
      next.paint = { ...paint, "fill-color": WATER, "fill-opacity": 1, "fill-outline-color": COAST };
    } else if (next.type === "fill" && /ice|glacier/.test(key)) {
      next.paint = { ...paint, "fill-color": ICE, "fill-opacity": 1 };
    } else if (next.type === "fill" && /park|grass|pitch|cemetery/.test(key)) {
      next.paint = { ...paint, "fill-color": PARK, "fill-opacity": 1, "fill-outline-color": INK };
    } else if (next.type === "fill" && /wood/.test(key)) {
      next.paint = { ...paint, "fill-color": WOOD, "fill-opacity": 1, "fill-outline-color": INK };
    } else if (next.type === "fill" && /wetland/.test(key)) {
      next.paint = { ...paint, "fill-color": WETLAND, "fill-opacity": 1, "fill-outline-color": INK };
    } else if (next.type === "fill" && /sand/.test(key)) {
      next.paint = { ...paint, "fill-color": SAND, "fill-opacity": 1 };
    } else if (next.type === "fill" && /building/.test(key)) {
      next.paint = { ...paint, "fill-color": BUILDING, "fill-opacity": 1 };
    } else if (next.type === "fill-extrusion" && /building/.test(key)) {
      next.paint = {
        ...paint,
        "fill-extrusion-color": BUILDING,
        "fill-extrusion-opacity": 1,
        "fill-extrusion-vertical-gradient": false,
      };
    } else if (next.type === "fill" && /residential/.test(key)) {
      next.paint = { ...paint, "fill-color": RESIDENTIAL, "fill-opacity": 1 };
    } else if (next.type === "fill" && /aeroway|pier/.test(key)) {
      next.paint = { ...paint, "fill-color": AEROWAY, "fill-opacity": 1, "fill-outline-color": INK };
    } else if (next.type === "fill") {
      next.paint = { ...paint, "fill-color": PAPER, "fill-opacity": 1 };
    } else if (next.type === "line") {
      if (/boundary/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 1.15), "line-color": INK, "line-opacity": 1 };
        delete (next.paint as Record<string, unknown>)["line-dasharray"];
        delete (next.paint as Record<string, unknown>)["line-blur"];
      } else if (/waterway/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 1.1), "line-color": WATER, "line-opacity": 1 };
        delete (next.paint as Record<string, unknown>)["line-blur"];
      } else if (/rail/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 1.15), "line-color": RAIL, "line-opacity": 1 };
        delete (next.paint as Record<string, unknown>)["line-blur"];
      } else if (sourceLayer === "transportation" || sourceLayer === "aeroway") {
        const casing = /casing/.test(layerId);
        const major = /motorway|trunk|primary/.test(key);
        next.paint = {
          ...withScaledWidth(paint, casing ? CASING_SCALE : 1),
          "line-color": casing ? INK : major ? ROAD_MAJOR : ROAD,
          "line-opacity": 1,
        };
        delete (next.paint as Record<string, unknown>)["line-blur"];
        delete (next.paint as Record<string, unknown>)["line-dasharray"];
      } else {
        next.paint = { ...withScaledWidth(paint, 1.2), "line-color": INK, "line-opacity": 1 };
        delete (next.paint as Record<string, unknown>)["line-blur"];
        delete (next.paint as Record<string, unknown>)["line-dasharray"];
      }
    } else if (next.type === "symbol") {
      next.paint = { ...paint, "text-color": INK, "text-halo-color": HALO, "text-halo-width": 1.6, "text-halo-blur": 0 };
      const layout = { ...((next.layout || {}) as Record<string, unknown>) };
      if (layout["text-font"]) layout["text-font"] = ["Noto Sans Bold"];
      next.layout = layout;
    } else {
      next.paint = paint;
    }
    out.push(next);
  }

  const waterAt = out.findIndex(isWaterFill);
  if (waterAt > 0) {
    const landIds = new Set(
      out.filter((layer) => layer.type === "fill" && String(layer["source-layer"] || "").includes("land")).map((layer) => String(layer.id))
    );
    if (landIds.size) {
      const before = out.slice(0, waterAt);
      const after = out.slice(waterAt);
      const land = after.filter((layer) => landIds.has(String(layer.id)));
      const rest = after.filter((layer) => !landIds.has(String(layer.id)));
      style.layers = [...before, ...land, ...rest];
      return { style };
    }
  }
  style.layers = out;
  return { style };
}
