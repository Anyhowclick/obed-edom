import type { LayerSpecification, StyleSpecification } from "maplibre-gl";
import { HILLSHADE_LAYER_ID, HILLSHADE_SOURCE_ID, type MapsStyleId } from "./types";
import { proxyOpenFreeMapUrl } from "./tileProxy";
import { TERRAIN_ATTRIBUTION } from "./stampOsm";

export const OPENFREEMAP_STYLES: Record<MapsStyleId, string> = {
  positron: "https://tiles.openfreemap.org/styles/positron",
  liberty: "https://tiles.openfreemap.org/styles/liberty",
  bright: "https://tiles.openfreemap.org/styles/bright",
  dark: "https://tiles.openfreemap.org/styles/dark",
  fiord: "https://tiles.openfreemap.org/styles/fiord",
  buildings3d: "https://tiles.openfreemap.org/styles/liberty",
};

export const STYLE_SWATCHES: { id: MapsStyleId; label: string; color: string }[] = [
  { id: "positron", label: "Positron", color: "#e8eef4" },
  { id: "liberty", label: "Liberty", color: "#d5e4c5" },
  { id: "bright", label: "Bright", color: "#f4e4b8" },
  { id: "dark", label: "Dark", color: "#2b3340" },
  { id: "fiord", label: "Fiord", color: "#3d4c5e" },
  { id: "buildings3d", label: "3D", color: "#c9b48a" },
];

const styleCache = new Map<string, Promise<StyleSpecification>>();

/** Top-down relief only: no `setTerrain()`, no draping, no pitch. Inserted before the first
 * water layer so the opaque water fill covers terrarium's ETOPO1 ocean-floor bathymetry. */
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
      "hillshade-exaggeration": ["interpolate", ["linear"], ["zoom"], 6, 0, 8, dark ? 0.5 : 0.35],
      "hillshade-shadow-color": dark ? "#000000" : "#4a4033",
      "hillshade-highlight-color": dark ? "#7f93ad" : "#ffffff",
      "hillshade-accent-color": dark ? "#000814" : "#6b5c46",
    },
  };
  const anchor = (
    style.layers.find((l) => (l as { "source-layer"?: string })["source-layer"] === "water") ||
    style.layers.find((l) => l.type === "line") ||
    style.layers.find((l) => l.type === "symbol")
  )?.id;
  const index = anchor ? style.layers.findIndex((l) => l.id === anchor) : style.layers.length;
  style.layers.splice(index, 0, layer);
  return style;
}

/** Inline TileJSON `tiles` so MapLibre actually requests vector PBFs past the NE raster. */
export function resolveOpenFreeMapStyle(styleId: MapsStyleId): Promise<StyleSpecification> {
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
  return pending.then((s) => withHillshade(structuredClone(s), styleId));
}
