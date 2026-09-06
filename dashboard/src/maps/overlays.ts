import type { Map as MapLibreMap } from "maplibre-gl";

export type Admin0 = {
  type: "FeatureCollection";
  features: Array<{ properties?: { ADM0_A3?: string; NAME?: string } | null }>;
};

export function admin0Name(code: string): string {
  const wanted = code.toUpperCase();
  const feat = admin0Cache?.features.find((item) => String(item.properties?.ADM0_A3 || "").toUpperCase() === wanted);
  return feat?.properties?.NAME || code;
}

let admin0Cache: Admin0 | null = null;
let admin0Pending: Promise<Admin0 | null> | null = null;

export async function loadAdmin0(): Promise<Admin0 | null> {
  if (admin0Cache) return admin0Cache;
  if (!admin0Pending) {
    admin0Pending = fetch("/api/maps/ne/admin0")
      .then(async (res) => {
        if (!res.ok) return null;
        admin0Cache = (await res.json()) as Admin0;
        return admin0Cache;
      })
      .catch(() => null)
      .finally(() => {
        admin0Pending = null;
      });
  }
  return admin0Pending;
}

/** Positron/Bright/Dark/Fiord ship the NE raster source but no layer; Liberty shows land at SEA zoom because it does. */
export function ensureLowZoomRaster(map: MapLibreMap, styleId?: string): void {
  if (!map.getSource("ne2_shaded")) return;
  if (map.getStyle().layers?.some((layer) => layer.type === "raster")) return;
  if (map.getLayer("ne2-shaded-fallback")) return;
  const before = map.getStyle().layers?.find((layer) => layer.type !== "background")?.id;
  const dark = styleId === "dark" || styleId === "fiord";
  map.addLayer(
    {
      id: "ne2-shaded-fallback",
      type: "raster",
      source: "ne2_shaded",
      maxzoom: 8,
      paint: {
        "raster-opacity": [
          "interpolate",
          ["linear"],
          ["zoom"],
          0,
          dark ? 0.55 : 1,
          6,
          dark ? 0.35 : 0.7,
          8,
          0,
        ],
        ...(dark ? { "raster-saturation": -0.65, "raster-brightness-max": 0.7 } : {}),
      },
    },
    before
  );
}

export function applyHighlights(map: MapLibreMap, highlights: string[]) {
  if (!map.getSource("admin0") || !admin0Cache) return;
  const wanted = new Set(highlights.map((h) => h.toUpperCase()));
  for (const feat of admin0Cache.features) {
    const id = String(feat.properties?.ADM0_A3 || "");
    if (!id) continue;
    map.setFeatureState({ source: "admin0", id }, { hl: wanted.has(id.toUpperCase()) });
  }
}

function firstSymbolId(map: MapLibreMap): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

export async function ensureAdmin0Highlights(map: MapLibreMap, highlights: string[], styleId?: string): Promise<void> {
  ensureLowZoomRaster(map, styleId);
  const data = await loadAdmin0();
  if (!data) return;
  if (!map.getSource("admin0")) {
    map.addSource("admin0", { type: "geojson", data: data as GeoJSON.GeoJSON, promoteId: "ADM0_A3" });
  }
  const before = firstSymbolId(map);
  if (!map.getLayer("admin0-fill")) {
    map.addLayer(
      {
        id: "admin0-fill",
        type: "fill",
        source: "admin0",
        paint: {
          "fill-color": "#e8772a",
          "fill-opacity": ["case", ["boolean", ["feature-state", "hl"], false], 0.4, 0],
        },
      },
      before
    );
    map.addLayer(
      {
        id: "admin0-line",
        type: "line",
        source: "admin0",
        paint: {
          "line-color": "#e8772a",
          "line-width": 1.2,
          "line-opacity": ["case", ["boolean", ["feature-state", "hl"], false], 0.9, 0],
        },
      },
      before
    );
  }
  applyHighlights(map, highlights);
}
