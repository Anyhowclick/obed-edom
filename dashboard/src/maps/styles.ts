import type { StyleSpecification } from "maplibre-gl";
import type { MapsStyleId } from "./types";
import { proxyOpenFreeMapUrl } from "./tileProxy";

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
  return pending;
}
