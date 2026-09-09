import type { LayerSpecification, StyleSpecification } from "maplibre-gl";
import { HILLSHADE_LAYER_ID, HILLSHADE_NE2_LAYER_ID, HILLSHADE_SOURCE_ID, type MapsStyleId } from "./types";
import { proxyOpenFreeMapUrl } from "./tileProxy";
import { TERRAIN_ATTRIBUTION } from "./stampOsm";
import { buildWatercolourStyle } from "./watercolourStyle";
import tonerStyleUrl from "./vendor/maptiler-toner-8688fbd.json?url";

export const OPENFREEMAP_STYLES: Record<MapsStyleId, string> = {
  positron: "https://tiles.openfreemap.org/styles/positron",
  liberty: "https://tiles.openfreemap.org/styles/liberty",
  bright: "https://tiles.openfreemap.org/styles/bright",
  dark: "https://tiles.openfreemap.org/styles/dark",
  fiord: "https://tiles.openfreemap.org/styles/fiord",
  buildings3d: "https://tiles.openfreemap.org/styles/liberty",
  toner: "https://tiles.openfreemap.org/styles/positron",
  "toner-background": "https://tiles.openfreemap.org/styles/positron",
  "toner-lines": "https://tiles.openfreemap.org/styles/positron",
  watercolour: "https://tiles.openfreemap.org/styles/positron",
};

export const MAP_STYLE_REGISTRY: { id: MapsStyleId; label: string; attribution: string }[] = [
  { id: "positron", label: "Positron", attribution: "© OpenStreetMap contributors" },
  { id: "liberty", label: "Liberty", attribution: "© OpenStreetMap contributors" },
  { id: "bright", label: "Bright", attribution: "© OpenStreetMap contributors" },
  { id: "dark", label: "Dark", attribution: "© OpenStreetMap contributors" },
  { id: "fiord", label: "Fiord", attribution: "© OpenStreetMap contributors" },
  { id: "buildings3d", label: "3D", attribution: "© OpenStreetMap contributors" },
  { id: "toner", label: "Toner", attribution: "© OpenStreetMap contributors · © MapTiler" },
  { id: "toner-background", label: "Toner background", attribution: "© OpenStreetMap contributors · © MapTiler" },
  { id: "toner-lines", label: "Toner lines", attribution: "© OpenStreetMap contributors · © MapTiler" },
  { id: "watercolour", label: "Watercolour", attribution: "© OpenStreetMap contributors" },
];

export const STYLE_SWATCHES: { id: MapsStyleId; label: string; color: string }[] = [
  { id: "positron", label: "Positron", color: "#e8eef4" },
  { id: "liberty", label: "Liberty", color: "#d5e4c5" },
  { id: "bright", label: "Bright", color: "#f4e4b8" },
  { id: "dark", label: "Dark", color: "#2b3340" },
  { id: "fiord", label: "Fiord", color: "#3d4c5e" },
  { id: "buildings3d", label: "3D", color: "#c9b48a" },
  { id: "toner", label: "Toner", color: "#f4f2ea" },
  { id: "toner-background", label: "Toner background", color: "#ece9e2" },
  { id: "toner-lines", label: "Toner lines", color: "#2f3130" },
  { id: "watercolour", label: "Watercolour", color: "#f1e5cb" },
];

const styleCache = new Map<string, Promise<StyleSpecification>>();
let tonerDocument: Promise<StyleSpecification> | null = null;

export function remapTonerFonts(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(remapTonerFonts);
  if (!value || typeof value !== "object") {
    if (value === "Noto Sans Bold Italic") return "Noto Sans Italic";
    if (typeof value === "string" && value.startsWith("Nunito")) return value.includes("Regular") ? "Noto Sans Regular" : "Noto Sans Bold";
    return value;
  }
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, child]) => [key, remapTonerFonts(child)]));
}

async function resolveTonerStyle(styleId: Extract<MapsStyleId, "toner" | "toner-background" | "toner-lines">): Promise<StyleSpecification> {
  if (!tonerDocument) {
    tonerDocument = fetch(tonerStyleUrl)
      .then((response) => response.ok ? response.json() as Promise<StyleSpecification> : Promise.reject(new Error(`Vendored Toner style failed (${response.status})`)));
  }
  const [base, toner] = await Promise.all([resolveOpenFreeMapStyle("positron"), tonerDocument]);
  const next = structuredClone(toner);
  const vector = Object.values(base.sources).find((source) => source.type === "vector");
  if (!vector) throw new Error("OpenFreeMap Positron has no vector source");
  next.sources = { openmaptiles: { ...structuredClone(vector), attribution: "© OpenStreetMap contributors · © MapTiler" } };
  next.glyphs = base.glyphs;
  delete next.sprite;
  next.layers = (remapTonerFonts(next.layers) as LayerSpecification[]).filter((layer) => {
    if (styleId === "toner-background") return layer.type === "background" || layer.type === "fill";
    if (styleId === "toner-lines") return layer.type === "background" || layer.type === "line";
    return true;
  });
  return withHillshade(next, styleId);
}

/** Top-down relief only: no `setTerrain()`, no draping, no pitch. Both layers are spliced in
 * before the first water layer (so opaque water covers terrarium's ETOPO1 bathymetry; buildWatercolourStyle lifts its land fills above that anchor so relief is not occluded), NE2 boost first so hillshade composites over it. */
function withHillshade(style: StyleSpecification, styleId: MapsStyleId): StyleSpecification {
  style.sources[HILLSHADE_SOURCE_ID] = {
    type: "raster-dem",
    encoding: "terrarium",
    tiles: ["/api/maps/tiles/terrarium/{z}/{x}/{y}.png"],
    tileSize: 256,
    minzoom: 0,
    maxzoom: 12,
    attribution: TERRAIN_ATTRIBUTION,
  };
  const dark = styleId === "dark" || styleId === "fiord";
  const relief = styleId === "watercolour"
    ? { exaggeration: 0.38, shadow: "#5B4636", highlight: "#FFFBF2", accent: "#7A6650" }
    : dark
      ? { exaggeration: 0.5, shadow: "#000000", highlight: "#7f93ad", accent: "#000814" }
      : { exaggeration: 0.35, shadow: "#4a4033", highlight: "#ffffff", accent: "#6b5c46" };
  const layer: LayerSpecification = {
    id: HILLSHADE_LAYER_ID,
    type: "hillshade",
    source: HILLSHADE_SOURCE_ID,
    minzoom: 6,
    layout: { visibility: "none" },
    paint: {
      "hillshade-method": "igor",
      "hillshade-illumination-anchor": "map",
      "hillshade-illumination-direction": 335,
      "hillshade-exaggeration": relief.exaggeration,
      "hillshade-shadow-color": relief.shadow,
      "hillshade-highlight-color": relief.highlight,
      "hillshade-accent-color": relief.accent,
    },
  };
  const anchor = (
    style.layers.find((l) => (l as { "source-layer"?: string })["source-layer"] === "water") ||
    style.layers.find((l) => l.type === "line") ||
    style.layers.find((l) => l.type === "symbol")
  )?.id;
  const index = anchor ? style.layers.findIndex((l) => l.id === anchor) : style.layers.length;
  const ne2 =
    style.sources.ne2_shaded && style.layers.some((l) => l.type === "raster")
      ? ({
          id: HILLSHADE_NE2_LAYER_ID,
          type: "raster",
          source: "ne2_shaded",
          maxzoom: 6,
          layout: { visibility: "none" },
          paint: { "raster-opacity": dark ? 0.28 : 0.45, "raster-saturation": -1 },
        } as LayerSpecification)
      : null;
  style.layers.splice(index, 0, ...(ne2 ? [ne2, layer] : [layer]));
  return style;
}

/** Inline TileJSON `tiles` so MapLibre actually requests vector PBFs past the NE raster. */
export function resolveOpenFreeMapStyle(styleId: MapsStyleId): Promise<StyleSpecification> {
  if (styleId === "toner" || styleId === "toner-background" || styleId === "toner-lines") return resolveTonerStyle(styleId);
  const url = OPENFREEMAP_STYLES[styleId];
  let pending = styleCache.get(url);
  if (!pending) {
    pending = fetch(proxyOpenFreeMapUrl(url))
      .then((res) => {
        if (!res.ok) throw new Error(`OpenFreeMap style ${styleId} failed (${res.status})`);
        return res.json() as Promise<StyleSpecification>;
      })
      .then(async (style) => {
        const sources = style.sources || {};
        await Promise.all(
          Object.values(sources).map(async (source) => {
            if (source.type !== "vector" || !("url" in source) || typeof source.url !== "string" || source.tiles?.length) {
              return;
            }
            try {
              const tilejson = (await (await fetch(proxyOpenFreeMapUrl(source.url))).json()) as {
                tiles?: string[];
                minzoom?: number;
                maxzoom?: number;
              };
              if (!tilejson.tiles?.length) return;
              source.tiles = tilejson.tiles;
              if (typeof tilejson.minzoom === "number") source.minzoom = tilejson.minzoom;
              if (typeof tilejson.maxzoom === "number") source.maxzoom = tilejson.maxzoom;
              delete source.url;
            } catch {
              /* keep source.url so MapLibre can still fetch TileJSON itself */
            }
          })
        );
        return structuredClone(style);
      })
      .catch((err) => {
        styleCache.delete(url);
        throw err;
      });
    styleCache.set(url, pending);
  }
  return pending.then((s) => {
    let next = structuredClone(s);
    if (styleId === "watercolour") next = buildWatercolourStyle(next).style as StyleSpecification;
    return withHillshade(next, styleId);
  });
}
