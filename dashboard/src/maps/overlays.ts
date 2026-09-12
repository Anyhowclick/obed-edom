import { GeoJSONSource, type LayerSpecification, type Map as MapLibreMap } from "maplibre-gl";
import { isolateMaskGeometry } from "./isolate";
import { shift } from "./tonerBoundaries";
import { HILLSHADE_LAYER_ID, HILLSHADE_NE2_LAYER_ID, type MapsChurch, type MapsIsolate, type MapsStyleId } from "./types";
import { defaultObjectSize, zoomScaledStops } from "./objects";

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
export function ensureLowZoomRaster(map: MapLibreMap, styleId?: string, zoomOffset = 0): void {
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
      maxzoom: shift(8, zoomOffset),
      paint: {
        "raster-opacity": [
          "interpolate",
          ["linear"],
          ["zoom"],
          shift(0, zoomOffset),
          dark ? 0.55 : 1,
          shift(6, zoomOffset),
          dark ? 0.35 : 0.7,
          shift(8, zoomOffset),
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

export function applyIsolate(map: MapLibreMap, highlights: string[], isolate: MapsIsolate | undefined): void {
  if (!map.getStyle()) return;
  const mask = isolate ? isolateMaskGeometry((admin0Cache?.features || []) as never, highlights) : null;
  if (!isolate || !mask) {
    if (map.getLayer("isolate-fill")) map.removeLayer("isolate-fill");
    if (map.getSource("isolate")) map.removeSource("isolate");
    return;
  }
  const source = map.getSource("isolate") as GeoJSONSource | undefined;
  if (source) {
    source.setData(mask);
    map.setPaintProperty("isolate-fill", "fill-opacity", Math.max(0, Math.min(1, isolate.strength)));
  } else {
    map.addSource("isolate", { type: "geojson", data: mask });
    map.addLayer(
      {
        id: "isolate-fill",
        type: "fill",
        source: "isolate",
        paint: {
          "fill-color": "#000000",
          "fill-opacity": Math.max(0, Math.min(1, isolate.strength)),
          "fill-antialias": false,
        },
      },
      firstSymbolId(map)
    );
  }
}

export async function ensureAdmin0Highlights(
  map: MapLibreMap,
  highlights: string[],
  styleId?: string,
  isolate?: MapsIsolate,
  zoomOffset = 0
): Promise<void> {
  ensureLowZoomRaster(map, styleId, zoomOffset);
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
  applyIsolate(map, highlights, isolate);
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
        size: church.size || defaultObjectSize(church.kind),
        opacity: church.opacity ?? 1,
        sel: church.id === selectedPinId,
        objectScale,
        scaleWithMap: church.scaleWithMap === true,
        sizeZoomRef: (church.sizeZoom ?? 0) + Math.log2(objectScale),
      },
      geometry: { type: "Point", coordinates: [church.lon, church.lat] },
    })),
  };
}

const painted = (c: MapsChurch) => c.kind === "landmark" && Boolean(c.reveal);

/** Landmarks with a paint-on reveal are captured into the slide still; hop movies must not double them. */
export function withoutRevealed(list: MapsChurch[]): MapsChurch[] {
  return list.filter((c) => !painted(c));
}

/**
 * `destinationPaintsReveal` mirrors maps_keynote.build_slide_items's `bg_movie is None` gate: the
 * destination slide only places (paints on) its revealed landmarks when it has no outgoing movie
 * link of its own. When it does (an A→B→C movie chain), B never paints the landmark on its own
 * slide, so the incoming A→B movie must keep carrying it through to avoid the landmark popping in.
 */
export function movieObjectsAt(from: MapsChurch[], to: MapsChurch[], t: number, transition: "fade" | "hold" | undefined, destinationPaintsReveal = true): MapsChurch[] {
  const clamped = Math.max(0, Math.min(1, t));
  const destination = destinationPaintsReveal ? withoutRevealed(to) : to;
  if ((transition || "hold") === "hold") return clamped < 1 ? from.map((item) => ({ ...item, opacity: item.opacity ?? 1 })) : destination.map((item) => ({ ...item, opacity: item.opacity ?? 1 }));
  const sourceAlpha = Math.max(0, 1 - 2 * clamped);
  const destAlpha = Math.max(0, 2 * clamped - 1);
  return [
    ...from.map((item) => ({ ...item, opacity: (item.opacity ?? 1) * sourceAlpha })),
    ...destination.map((item) => ({ ...item, id: `to-${item.id}`, opacity: (item.opacity ?? 1) * destAlpha })),
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

/**
 * Preview drop pin, drawn to Keynote's `_place_churches` geometry: a head circle of
 * diameter = size, a tail triangle 0.46 wide x 0.4 tall starting at 0.68, and a white
 * hole of diameter 0.36 at the head centre. Total height is 1.08 x size, tip on the anchor.
 */
const DROP_PIN_DEVICE_HEAD = 100;
const DROP_PIN_PIXEL_RATIO = 2;

/** Head diameter in CSS px of the raster `dropPinImage` returns. */
export const DROP_PIN_HEAD_PX = DROP_PIN_DEVICE_HEAD / DROP_PIN_PIXEL_RATIO;
/** Head-to-tip height in CSS px of that raster. */
export const DROP_PIN_TOTAL_PX = DROP_PIN_HEAD_PX * 1.08;
/** Emphasis applied to a selected drop pin's `icon-size`. */
export const DROP_PIN_SELECTED_SCALE = 1.08;

/** Selection-box size for a drop pin whose unselected head measures `headPx` on screen. */
export function dropPinSelectionBox(headPx: number): { w: number; h: number } {
  const w = headPx * DROP_PIN_SELECTED_SCALE;
  return { w, h: (w * DROP_PIN_TOTAL_PX) / DROP_PIN_HEAD_PX };
}

function dropPinImage(color: string): ImageData {
  const size = DROP_PIN_DEVICE_HEAD;
  const height = Math.round(size * 1.08);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(size, height);
  const half = size / 2;
  const tailW = size * 0.46;
  const tailTop = size * 0.68;
  ctx.beginPath();
  ctx.moveTo(half - tailW / 2, tailTop);
  ctx.lineTo(half + tailW / 2, tailTop);
  ctx.lineTo(half, tailTop + size * 0.4);
  ctx.closePath();
  ctx.moveTo(size, half);
  ctx.arc(half, half, half, 0, Math.PI * 2);
  // Stroke under the fill: the outer silhouette keeps a thin white rim while the fill hides
  // the head/tail seam. The rim's overshoot is clipped by the canvas, so the head stays `size` wide.
  ctx.lineWidth = size * 0.03;
  ctx.strokeStyle = "#ffffff";
  ctx.lineJoin = "round";
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(half, half, size * 0.18, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

export function ensureDropPinImages(map: MapLibreMap, churches: MapsChurch[]) {
  for (const church of churches) {
    if (church.kind !== "dropPin") continue;
    const id = dropPinImageId(church.color);
    if (!map.hasImage(id)) map.addImage(id, dropPinImage(church.color), { pixelRatio: DROP_PIN_PIXEL_RATIO });
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

/** Layer specs `addOverlays` installs on the `churches` source; factored out so tests can validate them directly. */
export function churchesLayers(): LayerSpecification[] {
  return [
    {
      id: "churches-dots",
      type: "circle",
      source: "churches",
      filter: ["==", ["get", "kind"], "dot"],
      paint: {
        // MapLibre clamps circle-radius to 1024px; Keynote's EFFECTIVE_SIZE_MAX (20000) never binds in the preview.
        "circle-radius": zoomScaledStops(["*", 0.5, ["get", "size"], ["get", "objectScale"]], 1024),
        "circle-color": ["get", "color"],
        "circle-opacity": ["coalesce", ["get", "opacity"], 1],
        "circle-stroke-opacity": ["coalesce", ["get", "opacity"], 1],
        "circle-stroke-width": zoomScaledStops(["*", ["case", ["boolean", ["get", "sel"], false], 3, 1.5], ["get", "objectScale"], ["/", ["get", "size"], defaultObjectSize("dot")]]),
        "circle-stroke-color": "#FFFFFF",
      },
    },
    {
      id: "churches-landmarks",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "kind"], "landmark"],
      layout: {
        "icon-image": ["concat", "landmark-", ["get", "assetId"], "-", ["coalesce", ["get", "assetVersion"], "v1"]],
        "icon-anchor": "bottom",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "icon-size": zoomScaledStops(["/", ["*", ["coalesce", ["get", "size"], 120], ["get", "objectScale"]], ["max", 1, ["get", "assetRenderWidth"]]]),
        "icon-rotation-alignment": "viewport",
        "icon-pitch-alignment": "viewport",
      },
      paint: { "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
    },
    {
      id: "churches-drops",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "kind"], "dropPin"],
      layout: {
        "icon-image": ["get", "pinImage"],
        "icon-anchor": "bottom",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        // Dividing by the raster's head diameter renders church.size px head-to-head, like Keynote's drop pin.
        "icon-size": zoomScaledStops(["*", ["case", ["boolean", ["get", "sel"], false], DROP_PIN_SELECTED_SCALE, 1], ["get", "size"], ["get", "objectScale"], 1 / DROP_PIN_HEAD_PX]),
      },
      paint: { "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
    },
    {
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
    },
  ] as LayerSpecification[];
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
    for (const layer of churchesLayers()) map.addLayer(layer);
  } else {
    (map.getSource("churches") as GeoJSONSource).setData(pins);
  }
  applyHighlights(map, highlights);
  applyIsolate(map, highlights, isolate);
}
