import { GeoJSONSource, type Map as MapLibreMap } from "maplibre-gl";
import { isolateMaskGeometry } from "./isolate";
import { STYLE_SWATCHES } from "./styles";
import { HILLSHADE_LAYER_ID, HILLSHADE_NE2_LAYER_ID, type MapsChurch, type MapsIsolate, type MapsStyleId } from "./types";

export type Admin0 = {
  type: "FeatureCollection";
  features: Array<{
    properties?: { ADM0_A3?: string; NAME?: string } | null;
    geometry?: { type: string; coordinates: unknown } | null;
  }>;
};

export function admin0Name(code: string): string {
  const wanted = code.toUpperCase();
  const feat = admin0Cache?.features.find((item) => String(item.properties?.ADM0_A3 || "").toUpperCase() === wanted);
  return feat?.properties?.NAME || code;
}

let admin0Cache: Admin0 | null = null;
let admin0Pending: Promise<Admin0 | null> | null = null;
const landmarkRenderWidths = new Map<string, number>();

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
  if (styleId === "watercolour") return;
  if (!map.getSource("ne2_shaded")) return;
  const style = map.getStyle();
  if (!style) return;
  if (style.layers?.some((layer) => layer.type === "raster")) return;
  if (map.getLayer("ne2-shaded-fallback")) return;
  const before = style.layers?.find((layer) => layer.type !== "background")?.id;
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

export function applyHillshade(map: MapLibreMap, on: boolean): void {
  const visibility = on ? "visible" : "none";
  for (const id of [HILLSHADE_NE2_LAYER_ID, HILLSHADE_LAYER_ID]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
  }
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
  const style = map.getStyle();
  return style?.layers?.find((layer) => layer.type === "symbol")?.id;
}

function backgroundColor(map: MapLibreMap, styleId?: string): string {
  const style = map.getStyle();
  const bgLayer = style?.layers?.find((layer) => layer.type === "background");
  const color = (bgLayer as { paint?: { "background-color"?: unknown } } | undefined)?.paint?.["background-color"];
  if (typeof color === "string") return color;
  return STYLE_SWATCHES.find((item) => item.id === styleId)?.color || "#ffffff";
}

const isolateModeByMap = new WeakMap<MapLibreMap, MapsIsolate["mode"]>();

export function applyIsolate(map: MapLibreMap, highlights: string[], isolate: MapsIsolate | undefined, styleId?: string): void {
  if (!map.getStyle()) return;
  const mask = isolate ? isolateMaskGeometry((admin0Cache?.features || []) as never, highlights) : null;
  if (!isolate || !mask) {
    if (map.getLayer("isolate-fill")) map.removeLayer("isolate-fill");
    if (map.getSource("isolate")) map.removeSource("isolate");
    isolateModeByMap.delete(map);
    return;
  }
  const source = map.getSource("isolate") as GeoJSONSource | undefined;
  if (source && isolateModeByMap.get(map) === isolate.mode) {
    source.setData(mask);
    map.setPaintProperty("isolate-fill", "fill-color", isolate.mode === "darken" ? "#000000" : backgroundColor(map, styleId));
    map.setPaintProperty("isolate-fill", "fill-opacity", Math.max(0, Math.min(1, isolate.strength)));
  } else {
    if (map.getLayer("isolate-fill")) map.removeLayer("isolate-fill");
    if (map.getSource("isolate")) map.removeSource("isolate");
    map.addSource("isolate", { type: "geojson", data: mask });
    map.addLayer(
      {
        id: "isolate-fill",
        type: "fill",
        source: "isolate",
        paint: {
          "fill-color": isolate.mode === "darken" ? "#000000" : backgroundColor(map, styleId),
          "fill-opacity": Math.max(0, Math.min(1, isolate.strength)),
          "fill-antialias": false,
        },
      },
      isolate.mode === "darken" ? firstSymbolId(map) : undefined
    );
    isolateModeByMap.set(map, isolate.mode);
  }
}

export async function ensureAdmin0Highlights(
  map: MapLibreMap,
  highlights: string[],
  styleId?: string,
  isolate?: MapsIsolate
): Promise<void> {
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
  applyIsolate(map, highlights, isolate, styleId);
}

export function churchesGeo(
  churches: MapsChurch[],
  selectedPinId: string | null,
  numberPins = false,
  objectScale = 1
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: churches.map((church, index) => ({
      type: "Feature",
      properties: {
        id: church.id,
        name: numberPins ? `${index + 1}. ${church.name}` : church.name,
        showLabel: church.showLabel !== false,
        color: church.color,
        kind: church.kind,
        pinImage: dropPinImageId(church.color),
        assetId: church.assetId || "",
        assetVersion: church.assetVersion || "v1",
        assetWidth: church.assetWidth || 1,
        assetRenderWidth: landmarkRenderWidths.get(`landmark-${church.assetId}-${church.assetVersion || "v1"}`) || church.assetWidth || 1,
        assetHeight: church.assetHeight || 1,
        size: church.size || 120,
        opacity: church.opacity ?? 1,
        sel: church.id === selectedPinId,
        objectScale,
      },
      geometry: { type: "Point", coordinates: [church.lon, church.lat] },
    })),
  };
}

export function movieObjectsAt(from: MapsChurch[], to: MapsChurch[], t: number, transition: "fade" | "hold" | undefined): MapsChurch[] {
  const clamped = Math.max(0, Math.min(1, t));
  if ((transition || "hold") === "hold") return clamped < 1 ? from.map((item) => ({ ...item, opacity: item.opacity ?? 1 })) : to.map((item) => ({ ...item, opacity: item.opacity ?? 1 }));
  const source = Math.max(0, 1 - 2 * clamped);
  const destination = Math.max(0, 2 * clamped - 1);
  return [
    ...from.map((item) => ({ ...item, opacity: (item.opacity ?? 1) * source })),
    ...to.map((item) => ({ ...item, id: `to-${item.id}`, opacity: (item.opacity ?? 1) * destination })),
  ];
}

function dropPinImageId(color: string): string {
  let hash = 2166136261;
  for (const char of color.trim().toLowerCase()) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return `church-drop-${hash >>> 0}`;
}

function dropPinImage(color: string): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = 48;
  canvas.height = 60;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(48, 60);
  ctx.beginPath();
  ctx.moveTo(24, 58);
  ctx.bezierCurveTo(20, 49, 7, 37, 7, 23);
  ctx.bezierCurveTo(7, 11, 14, 3, 24, 3);
  ctx.bezierCurveTo(34, 3, 41, 11, 41, 23);
  ctx.bezierCurveTo(41, 37, 28, 49, 24, 58);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = "#ffffff";
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(24, 22, 7, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

export function ensureDropPinImages(map: MapLibreMap, churches: MapsChurch[]) {
  for (const church of churches) {
    if (church.kind !== "dropPin") continue;
    const id = dropPinImageId(church.color);
    if (!map.hasImage(id)) map.addImage(id, dropPinImage(church.color), { pixelRatio: 2 });
  }
}

export async function ensureLandmarkImages(map: MapLibreMap, churches: MapsChurch[], assetBaseUrl?: string): Promise<void> {
  for (const church of churches) {
    if (church.kind !== "landmark" || !church.assetId || !assetBaseUrl) continue;
    const id = `landmark-${church.assetId}-${church.assetVersion || "v1"}`;
    if (map.hasImage(id)) continue;
    const response = await fetch(`${assetBaseUrl}/${encodeURIComponent(church.assetId)}.png`);
    if (!response.ok) continue;
    const image = await createImageBitmap(await response.blob());
    const max = 1024;
    const scale = Math.min(1, max / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    canvas.getContext("2d")?.drawImage(image, 0, 0, canvas.width, canvas.height);
    landmarkRenderWidths.set(id, canvas.width);
    if (!map.hasImage(id)) map.addImage(id, canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height), { pixelRatio: 1 });
  }
}

export async function addOverlays(
  map: MapLibreMap,
  highlights: string[],
  churches: MapsChurch[],
  selectedPinId: string | null,
  styleId: MapsStyleId,
  numberPins: boolean,
  assetBaseUrl?: string,
  objectScale = 1,
  isolate?: MapsIsolate
) {
  await ensureAdmin0Highlights(map, highlights, styleId, isolate);
  ensureDropPinImages(map, churches);
  await ensureLandmarkImages(map, churches, assetBaseUrl);
  const pins = churchesGeo(churches, selectedPinId, numberPins, objectScale);
  if (!map.getSource("churches")) {
    map.addSource("churches", { type: "geojson", data: pins, promoteId: "id" });
    map.addLayer({
      id: "churches-dots",
      type: "circle",
      source: "churches",
      filter: ["==", ["get", "kind"], "dot"],
      paint: {
        "circle-radius": ["*", 14, ["get", "objectScale"]],
        "circle-color": ["get", "color"],
        "circle-opacity": ["coalesce", ["get", "opacity"], 1],
        "circle-stroke-opacity": ["coalesce", ["get", "opacity"], 1],
        "circle-stroke-width": ["*", ["case", ["boolean", ["get", "sel"], false], 3, 1.5], ["get", "objectScale"]],
        "circle-stroke-color": "#FFFFFF",
      },
    });
    map.addLayer({
      id: "churches-landmarks",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "kind"], "landmark"],
      layout: {
        "icon-image": ["concat", "landmark-", ["get", "assetId"], "-", ["coalesce", ["get", "assetVersion"], "v1"]],
        "icon-anchor": "bottom",
        "icon-allow-overlap": true,
        "icon-size": ["/", ["*", ["coalesce", ["get", "size"], 120], ["get", "objectScale"]], ["max", 1, ["get", "assetRenderWidth"]]],
        "icon-rotation-alignment": "viewport",
        "icon-pitch-alignment": "viewport",
      },
      paint: { "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
    });
    map.addLayer({
      id: "churches-drops",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "kind"], "dropPin"],
      layout: {
        "icon-image": ["get", "pinImage"],
        "icon-anchor": "bottom",
        "icon-allow-overlap": true,
        "icon-size": ["*", ["case", ["boolean", ["get", "sel"], false], 1.08, 1], ["get", "objectScale"]],
      },
      paint: { "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
    });
    map.addLayer({
      id: "churches-labels",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "showLabel"], true],
      layout: {
        "text-field": ["get", "name"],
        "text-size": ["*", 24, ["get", "objectScale"]],
        "text-offset": [0, 1.35],
        "text-anchor": "top",
      },
      paint: { "text-color": "#FFFFFF", "text-halo-color": "#07070A", "text-halo-width": ["*", 1.2, ["get", "objectScale"]], "text-opacity": ["coalesce", ["get", "opacity"], 1] },
    });
  } else {
    (map.getSource("churches") as GeoJSONSource).setData(pins);
  }
  applyHighlights(map, highlights);
  applyIsolate(map, highlights, isolate, styleId);
}
