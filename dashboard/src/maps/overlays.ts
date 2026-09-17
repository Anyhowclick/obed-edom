import {
  GeoJSONSource,
  type DataDrivenPropertyValueSpecification,
  type LayerSpecification,
  type Map as MapLibreMap,
} from "maplibre-gl";
import { isolateMaskGeometry } from "./isolate";
import { shift } from "./tonerBoundaries";
import { churchLabelColor, DEFAULT_LABEL_PILL_COLOR, HILLSHADE_LAYER_ID, HILLSHADE_NE2_LAYER_ID, ML_MAX_ZOOM, ML_MIN_ZOOM, type MapsChurch, type MapsIsolate, type MapsStyleId } from "./types";
import { defaultObjectSize, ICON_SIZE_PACK_MAX, zoomScaledStops } from "./objects";
import { filledHighlights, highlightColour, highlightColourExpression, setHighlightColour } from "./highlight";

/** Hairline on every dot; 0.25pt at 1× (defaultObjectSize("dot")), scales with the marker. */
export const DOT_BORDER_PT = 0.25;

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

export function highlightName(code: string): string {
  return code.startsWith("A1:") ? admin1Name(code) : admin0Name(code);
}

export type Admin1Feature = {
  properties?: { adm0_a3?: string; adm1_code?: string; iso_3166_2?: string; name?: string; type_en?: string } | null;
  geometry?: { type: string; coordinates: unknown } | null;
};

export type Admin1 = { type: "FeatureCollection"; features: Admin1Feature[] };

const admin1Cache = new Map<string, Admin1>();
const admin1Pending = new Map<string, Promise<Admin1 | null>>();

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

export async function loadAdmin1(code: string): Promise<Admin1 | null> {
  const wanted = code.toUpperCase();
  const cached = admin1Cache.get(wanted);
  if (cached) return cached;
  let pending = admin1Pending.get(wanted);
  if (!pending) {
    pending = fetch(`/api/maps/ne/admin1/${wanted}`)
      .then(async (res) => {
        if (!res.ok) {
          console.warn("admin1 fetch failed", wanted, res.status);
          return null;
        }
        const data = (await res.json()) as Admin1;
        admin1Cache.set(wanted, data);
        return data;
      })
      .catch((err) => {
        console.warn("admin1 fetch failed", wanted, err);
        return null;
      })
      .finally(() => {
        admin1Pending.delete(wanted);
      });
    admin1Pending.set(wanted, pending);
  }
  return pending;
}

export function isAdmin1Loaded(code: string): boolean {
  return admin1Cache.has(code.toUpperCase());
}

/** Every admin-1 feature loaded so far, flattened — the clip path and the isolate mask read this. */
export function admin1Features(): Admin1Feature[] {
  const out: Admin1Feature[] = [];
  for (const data of admin1Cache.values()) out.push(...data.features);
  return out;
}

/** Resolves an `A1:` id's country: prefers the loaded feature's `adm0_a3`, falling back to the
 * code's own prefix (`adm1_code` always carries its country as the first three characters,
 * e.g. `MYS-1186`, `GAZ+00?`). The one resolver both `admin1Countries` and `admin1FeaturesInPlay`
 * use, so a code whose prefix differs from its `adm0_a3` resolves the same way everywhere. */
function admin1CodeCountry(id: string): string {
  const feat = admin1Features().find((item) => item.properties?.adm1_code === id);
  return String(feat?.properties?.adm0_a3 || id.slice(0, 3)).toUpperCase();
}

/** Every country a highlight names — bare or `A1:` — the set the isolate mask, the export clip,
 * and the admin-1 preload all key off, so they never disagree on which countries are in play. */
export function highlightedCountries(highlights: string[]): string[] {
  const countries = new Set<string>();
  for (const highlight of highlights) {
    const country = highlight.startsWith("A1:") ? admin1CodeCountry(highlight.slice(3)) : highlight;
    if (country) countries.add(country.toUpperCase());
  }
  return [...countries];
}

/** Admin-1 features for the countries a highlight actually names — bare or `A1:` — never every
 * cached country, so the isolate mask's shape depends only on what is highlighted, not on which
 * countries happen to be loaded (e.g. from the Regions-mode camera preload). */
export function admin1FeaturesInPlay(highlights: string[]): Admin1Feature[] {
  const out: Admin1Feature[] = [];
  for (const country of highlightedCountries(highlights)) {
    const data = admin1Cache.get(country);
    if (data) out.push(...data.features);
  }
  return out;
}

/** Countries named by an `A1:` highlight only — used to resolve the merged admin-1 source. */
export function admin1Countries(highlights: string[]): string[] {
  const codes = new Set<string>();
  for (const highlight of highlights) {
    if (!highlight.startsWith("A1:")) continue;
    const country = admin1CodeCountry(highlight.slice(3));
    if (country.length === 3) codes.add(country);
  }
  return [...codes];
}

export function admin1Name(id: string): string {
  const code = id.startsWith("A1:") ? id.slice(3) : id;
  for (const data of admin1Cache.values()) {
    const feat = data.features.find((item) => item.properties?.adm1_code === code);
    if (!feat) continue;
    const name = feat.properties?.name || code;
    const type = feat.properties?.type_en || "";
    const twin = data.features.some(
      (item) => item.properties?.name === name && item.properties?.adm1_code !== code
    );
    return twin && type ? `${name} (${type})` : name;
  }
  return code;
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

export function applyHighlights(map: MapLibreMap, highlights: string[], highlightColours?: Record<string, string>) {
  if (!map.getSource("admin0") || !admin0Cache) return;
  const wanted = new Set(
    filledHighlights(
      highlights.filter((h) => !h.startsWith("A1:")),
      highlightColours
    ).map((h) => h.toUpperCase())
  );
  for (const feat of admin0Cache.features) {
    const id = String(feat.properties?.ADM0_A3 || "");
    if (!id) continue;
    map.setFeatureState({ source: "admin0", id }, { hl: wanted.has(id.toUpperCase()) });
  }
}

export const ADMIN0_FILL_OPACITY = 0.55;
export const ADMIN0_LINE_OPACITY = 0.9;
export const ADMIN1_FILL_OPACITY = 0.55;
export const ADMIN1_LINE_OPACITY = 0.9;

/** Highlighted-country fill/line opacity, keyed off `feature-state.hl` set by `applyHighlights`. */
export function admin0PaintExpression(on: number): DataDrivenPropertyValueSpecification<number> {
  return ["case", ["boolean", ["feature-state", "hl"], false], on, 0] as DataDrivenPropertyValueSpecification<number>;
}

/** Highlighted-region ids drive an `["in", …]` expression rather than feature state: one
 * `setPaintProperty` repaints every region, and no `promoteId` is needed on the source. */
export function admin1PaintExpression(
  highlights: string[],
  on: number,
  highlightColours?: Record<string, string>
): DataDrivenPropertyValueSpecification<number> {
  const filled = filledHighlights(highlights, highlightColours);
  const ids = [...new Set(filled.filter((h) => h.startsWith("A1:")).map((h) => h.slice(3)))];
  return ["case", ["in", ["get", "adm1_code"], ["literal", ids]], on, 0] as DataDrivenPropertyValueSpecification<number>;
}

export function applyAdmin1Highlights(
  map: MapLibreMap,
  highlights: string[],
  highlightColours?: Record<string, string>
): void {
  if (!map.getLayer("admin1-fill")) return;
  map.setPaintProperty("admin1-fill", "fill-opacity", admin1PaintExpression(highlights, ADMIN1_FILL_OPACITY, highlightColours));
  map.setPaintProperty("admin1-line", "line-opacity", admin1PaintExpression(highlights, ADMIN1_LINE_OPACITY, highlightColours));
}

function firstSymbolId(map: MapLibreMap): string | undefined {
  const style = map.getStyle();
  return style?.layers?.find((layer) => layer.type === "symbol")?.id;
}

export function applyIsolate(map: MapLibreMap, highlights: string[], isolate: MapsIsolate | undefined): void {
  if (!map.getStyle()) return;
  const mask = isolate ? isolateMaskGeometry((admin0Cache?.features || []) as never, highlights, admin1FeaturesInPlay(highlights)) : null;
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

/** True while `map`'s style/generation is still the one the caller started this async work for.
 * Every mutation after an `await` in `ensureAdmin0Highlights` and `syncAdmin1Source` must be
 * gated on this, not only the caller's own follow-up (e.g. `triggerRepaint`) — otherwise an
 * older, slower request can overwrite a newer selection when admin-1 loads resolve out of order. */
export type IsCurrent = () => boolean;

const ALWAYS_CURRENT: IsCurrent = () => true;

export async function ensureAdmin0Highlights(
  map: MapLibreMap,
  highlights: string[],
  styleId?: string,
  isolate?: MapsIsolate,
  zoomOffset = 0,
  extraAdmin1: string[] = [],
  isCurrent: IsCurrent = ALWAYS_CURRENT,
  highlightColourOverride?: string,
  highlightColours?: Record<string, string>
): Promise<void> {
  ensureLowZoomRaster(map, styleId, zoomOffset);
  const data = await loadAdmin0();
  if (!data || !isCurrent()) return;
  // A border cut (spec 10.3) needs every named country's admin-1 loaded, not only the A1:-tagged
  // ones, so the cut rings never fall back to admin-0 for a bare-highlighted country.
  const hasAdmin1Highlight = highlights.some((h) => h.startsWith("A1:"));
  const admin1Codes = [...new Set([...(hasAdmin1Highlight ? highlightedCountries(highlights) : []), ...extraAdmin1])];
  if (admin1Codes.length) await Promise.all(admin1Codes.map(loadAdmin1));
  if (!isCurrent()) return;
  const colour = highlightColourOverride ?? highlightColour();
  const admin0Paint = highlightColourExpression("ADM0_A3", colour, highlightColours) as string;
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
          "fill-color": admin0Paint,
          "fill-opacity": admin0PaintExpression(ADMIN0_FILL_OPACITY),
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
          "line-color": admin0Paint,
          "line-width": 1.2,
          "line-opacity": admin0PaintExpression(ADMIN0_LINE_OPACITY),
        },
      },
      before
    );
  }
  ensureAdmin1Layers(map, admin1Codes, colour, highlightColours);
  applyHighlights(map, highlights, highlightColours);
  applyAdmin1Highlights(map, highlights, highlightColours);
  applyIsolate(map, highlights, isolate);
  applyHighlightColour(map, colour, highlightColours);
}

/** Sets the module-level highlight colour and repaints the admin-0/admin-1 layers already on `map`. */
export function applyHighlightColour(map: MapLibreMap, colour: string, overrides?: Record<string, string>): void {
  setHighlightColour(colour);
  const next = highlightColour();
  const admin0 = highlightColourExpression("ADM0_A3", next, overrides) as string;
  const admin1 = highlightColourExpression("adm1_code", next, overrides) as string;
  if (map.getLayer("admin0-fill")) map.setPaintProperty("admin0-fill", "fill-color", admin0);
  if (map.getLayer("admin0-line")) map.setPaintProperty("admin0-line", "line-color", admin0);
  if (map.getLayer("admin1-fill")) map.setPaintProperty("admin1-fill", "fill-color", admin1);
  if (map.getLayer("admin1-line")) map.setPaintProperty("admin1-line", "line-color", admin1);
}

/** Loads `codes` and re-feeds the merged `admin1` source from the cache — the explicit
 * operation for keeping that source in step with the camera country in Regions mode, since
 * the fast highlight-effect path only touches paint expressions. Generation-guarded: `isCurrent`
 * is checked after the load before the source is touched, so a superseded call is a no-op. */
export async function syncAdmin1Source(
  map: MapLibreMap,
  codes: string[],
  isCurrent: IsCurrent = ALWAYS_CURRENT
): Promise<void> {
  if (codes.length) await Promise.all(codes.map(loadAdmin1));
  if (!isCurrent()) return;
  ensureAdmin1Layers(map, codes);
}

/** Adds (or re-feeds) the merged admin-1 source for `codes`. No-op while nothing is highlighted. */
function ensureAdmin1Layers(
  map: MapLibreMap,
  codes: string[],
  highlightColourOverride?: string,
  highlightColours?: Record<string, string>
): void {
  if (!codes.length) {
    if (map.getLayer("admin1-line")) map.removeLayer("admin1-line");
    if (map.getLayer("admin1-fill")) map.removeLayer("admin1-fill");
    if (map.getSource("admin1")) map.removeSource("admin1");
    return;
  }
  const features: Admin1Feature[] = [];
  for (const code of codes) features.push(...(admin1Cache.get(code)?.features || []));
  const data = { type: "FeatureCollection", features } as GeoJSON.GeoJSON;
  const source = map.getSource("admin1") as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    stackAdmin1AboveAdmin0(map);
    return;
  }
  map.addSource("admin1", { type: "geojson", data });
  // Pin admin1-fill below isolate-fill regardless of which layer is (re)created first, so the
  // isolate mask always stays on top of the region fill, matching today's look.
  const before = map.getLayer("isolate-fill") ? "isolate-fill" : firstSymbolId(map);
  const colour = highlightColourOverride ?? highlightColour();
  const admin1Paint = highlightColourExpression("adm1_code", colour, highlightColours) as string;
  map.addLayer(
    {
      id: "admin1-fill",
      type: "fill",
      source: "admin1",
      paint: { "fill-color": admin1Paint, "fill-opacity": 0 },
    },
    before
  );
  map.addLayer(
    {
      id: "admin1-line",
      type: "line",
      source: "admin1",
      paint: { "line-color": admin1Paint, "line-width": 1.2, "line-opacity": 0 },
    },
    before
  );
  stackAdmin1AboveAdmin0(map);
}

/** Region fills sit above the country wash so a blue province stays visible on yellow Indonesia. */
function stackAdmin1AboveAdmin0(map: MapLibreMap): void {
  if (!map.getLayer("admin1-fill") || !map.getLayer("admin0-fill")) return;
  const before = map.getLayer("isolate-fill") ? "isolate-fill" : firstSymbolId(map);
  map.moveLayer("admin1-fill", before);
  if (map.getLayer("admin1-line")) map.moveLayer("admin1-line", before);
}

const LABEL_SCALE_MIN = 0.5;
const LABEL_SCALE_MAX = 8;
/** Mirrors `maps_keynote.LABEL_FONT_PT`. */
export const LABEL_FONT_PX = 23;
/** Mirrors `maps_keynote.LABEL_CHAR_W` / `NAME_HEIGHT` / pill width clamp. */
export const LABEL_CHAR_W_PX = 13;
export const LABEL_NAME_HEIGHT_PX = 32;
export const LABEL_PILL_MIN_PX = 48;
export const LABEL_PILL_MAX_PX = 420;
/** Kept for Keynote-parity tests; preview pills no longer wrap MapLibre text. */
export const LABEL_MAX_WIDTH_EMS = 40;
export const LABEL_GAP_EMS = 0.35;
/** Mirrors `maps_keynote.PILL_PAD_X` / `PILL_PAD_Y`. */
const PILL_PAD_X_PX = 6;
export const PILL_PAD_Y_PX = 2;

/** Mirrors `maps_keynote._label_scale`: pins and dots share the drop-pin default so a
 * grouped pin and dot at the same size get the same text and pill. Landmarks use their
 * own authored default as 1×. Zoom lives in the `icon-size` stops, which carry the clamp. */
function labelScale(kind: string, size: number, assetWidth = 0): number {
  const base = kind === "landmark" ? defaultObjectSize(kind, assetWidth) : defaultObjectSize("dropPin");
  return base ? size / base : 1;
}

/** `icon-text-fit-padding` and an image's corner radius are layout constants, so the pill's
 * padding and radius can only follow the label through a data-driven `icon-image`: one baked
 * variant per bucket of `scale * objectScale`, which is the non-zoom half of the rendered text
 * size (`LABEL_FONT_PX * labelScale * objectScale`, see `icon-size` below). The buckets are an octave apart
 * and the geometry is geometric, so snapping to the nearest in log2 bounds that half's
 * padding/radius error at sqrt(2) — the zoom-driven half of the total scale (`scaleWithMap`
 * features only) cannot feed a data property and is not covered by this bound. */
export const LABEL_PILL_BUCKETS: number[] = [0.5, 1, 2, 4, 8];

export function labelPillBucket(scale: number): number {
  const target = Math.log2(Math.max(scale, Number.MIN_VALUE));
  let bucket = LABEL_PILL_BUCKETS[0];
  for (const candidate of LABEL_PILL_BUCKETS) {
    if (Math.abs(target - Math.log2(candidate)) < Math.abs(target - Math.log2(bucket))) bucket = candidate;
  }
  return bucket;
}

function labelOffsetProperty(zoom: number): string {
  return `labelOffset${zoom}`;
}

function labelNameKey(name: string): string {
  let hash = 2166136261;
  for (const char of name) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return String(hash >>> 0);
}

/** Named pills bake at 1× CSS; `icon-size` applies labelScale × objectScale × zoom. */
export const LABEL_PILL_BAKE_SCALE = 1;

/** Keynote `_place_churches` box: `nw = clamp(48, 420, 13 * len) * scale`, plus pads. */
export function labelPillCssSize(name: string, scale: number): { w: number; h: number } {
  const s = Math.max(scale, Number.MIN_VALUE);
  const nw = Math.max(LABEL_PILL_MIN_PX * s, Math.min(LABEL_PILL_MAX_PX * s, measureNamePx(name, s)));
  const nh = LABEL_NAME_HEIGHT_PX * s;
  return { w: Math.round(nw + 2 * PILL_PAD_X_PX * s), h: Math.round(nh + 2 * PILL_PAD_Y_PX * s) };
}

function measureNamePx(name: string, scale: number): number {
  try {
    const ctx = document.createElement("canvas").getContext("2d");
    if (ctx && typeof ctx.measureText === "function") {
      ctx.font = `700 ${LABEL_FONT_PX * scale}px "Noto Sans", sans-serif`;
      const width = ctx.measureText(name).width;
      if (width > 0) return width;
    }
  } catch {
    /* node tests stub a canvas without measureText */
  }
  return LABEL_CHAR_W_PX * scale * [...name].length;
}

/** LABEL: the name is baked into the pill so it cannot drift. The pill's bottom sits
 * `LABEL_GAP_EMS` of the rendered (clamped) text size above the marker top, matching
 * Keynote's `top - LABEL_GAP * scale`. `icon-offset` is in the image's CSS pixels and
 * MapLibre then multiplies it by `icon-size`, so each integer zoom stores
 * `-needScreen / iconSize`. A selected drop pin's height already includes
 * `DROP_PIN_SELECTED_SCALE` via `markerHeightPx`. */
function labelOffsets(markerPx: number, totalScale: number, bakeScale: number, scaleWithMap: boolean, sizeZoomRef: number): Record<string, [number, number]> {
  const bake = Math.max(bakeScale, Number.MIN_VALUE);
  const factorAt = (zoom: number) => (scaleWithMap ? Math.pow(2, zoom - sizeZoomRef) : 1);
  const textScaleAt = (zoom: number) => Math.min(LABEL_SCALE_MAX, Math.max(LABEL_SCALE_MIN, totalScale * factorAt(zoom)));
  const iconSizeAt = (zoom: number) => textScaleAt(zoom) / bake;
  const needAt = (zoom: number) => markerPx * factorAt(zoom) + LABEL_GAP_EMS * LABEL_FONT_PX * textScaleAt(zoom);
  const zooms = Array.from({ length: ML_MAX_ZOOM - ML_MIN_ZOOM + 1 }, (_, index) => ML_MIN_ZOOM + index);
  const iconSize = zooms.map(iconSizeAt);
  const need = zooms.map(needAt);
  const offset = zooms.map((_, index) => -need[index] / iconSize[index]);
  // Between stops MapLibre interpolates icon-offset and icon-size independently; their
  // product (screen px) dips on a segment that straddles the 0.5x..8x clamp. Sample the
  // shortfall and lift both end offsets so the chord stays above the marker.
  const slack = zooms.map(() => 0);
  for (let index = 0; index + 1 < zooms.length; index++) {
    if (!scaleWithMap) continue;
    const b = iconSize[index + 1] - iconSize[index];
    const a = iconSize[index] - b;
    const d = offset[index + 1] - offset[index];
    const c = offset[index] - d;
    if (b === 0 && d === 0) continue;
    let dip = 0;
    for (let step = 1; step < 100; step++) {
      const u = 1 + step / 100;
      const zoom = zooms[index] + Math.log2(u);
      const screen = -(c + d * u) * (a + b * u);
      dip = Math.max(dip, needAt(zoom) - screen);
    }
    if (!(dip > 0)) continue;
    slack[index] += dip / iconSize[index];
    slack[index + 1] += dip / iconSize[index + 1];
  }
  const offsets: Record<string, [number, number]> = {};
  zooms.forEach((zoom, index) => {
    offsets[labelOffsetProperty(zoom)] = [0, offset[index] - slack[index]];
  });
  return offsets;
}

/** Base-2 interpolation between the per-zoom offsets, the same ramp shape `icon-size` uses. */
function labelOffsetExpression(property = labelOffsetProperty): DataDrivenPropertyValueSpecification<[number, number]> {
  const stops: unknown[] = ["interpolate", ["exponential", 2], ["zoom"]];
  for (let zoom = ML_MIN_ZOOM; zoom <= ML_MAX_ZOOM; zoom++) stops.push(zoom, ["array", "number", 2, ["get", property(zoom)]]);
  return stops as unknown as DataDrivenPropertyValueSpecification<[number, number]>;
}

function markerHeightPx(church: MapsChurch, size: number, selected: boolean): number {
  if (church.kind === "dot") return size / 2;
  if (church.kind === "dropPin") return size * DROP_PIN_ASPECT * (selected ? DROP_PIN_SELECTED_SCALE : 1);
  const width = church.assetWidth || 1;
  const height = church.assetHeight || 1;
  return (size * height) / width;
}

export function churchesGeo(
  churches: MapsChurch[],
  selectedPinId: string | null,
  numberPins = false,
  objectScale = 1
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: churches.map((church, index) => {
      const size = church.size || defaultObjectSize(church.kind, church.assetWidth);
      const scale = labelScale(church.kind, size, church.assetWidth);
      const bucket = labelPillBucket(Math.min(LABEL_SCALE_MAX, Math.max(LABEL_SCALE_MIN, scale * objectScale)));
      const name = numberPins ? `${index + 1}. ${church.name}` : church.name;
      return {
        type: "Feature",
        properties: {
          id: church.id,
          name,
          showLabel: church.showLabel === true,
          color: church.color,
          kind: church.kind,
          pinImage: dropPinImageId(church.color),
          assetId: church.assetId || "",
          assetVersion: church.assetVersion || "v1",
          assetWidth: church.assetWidth || 1,
          assetRenderWidth: landmarkRenderWidths.get(`landmark-${church.assetId}-${church.assetVersion || "v1"}`) || church.assetWidth || 1,
          assetHeight: church.assetHeight || 1,
          size,
          opacity: church.opacity ?? 1,
          labelOpacity: church.labelOpacity ?? church.opacity ?? 1,
          sel: church.id === selectedPinId,
          objectScale,
          scaleWithMap: church.scaleWithMap === true,
          sizeZoomRef: (church.sizeZoom ?? 0) + Math.log2(objectScale),
          labelScale: scale,
          labelBucket: String(bucket),
          labelPill: labelPillImageId(name, churchLabelColor(church)),
          ...labelOffsets(
            markerHeightPx(church, size, church.id === selectedPinId) * objectScale,
            scale * objectScale,
            LABEL_PILL_BAKE_SCALE,
            church.scaleWithMap === true,
            (church.sizeZoom ?? 0) + Math.log2(objectScale)
          ),
        },
        geometry: { type: "Point", coordinates: [church.lon, church.lat] },
      };
    }),
  };
}

const painted = (c: MapsChurch) => c.kind === "landmark" && Boolean(c.reveal);

/** Landmarks with a paint-on reveal are captured into the slide still; hop movies must not double them. */
export function withoutRevealed(list: MapsChurch[]): MapsChurch[] {
  return list.filter((c) => !painted(c));
}

/** Pins and landmarks stay; Keynote paints Amplitude Bold labels on stills, not on movie rasters. */
function withoutMovieLabel(item: MapsChurch): MapsChurch {
  return { ...item, showLabel: false };
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
  if ((transition || "hold") === "hold") {
    if (clamped >= 1) return destination.map((item) => withoutMovieLabel({ ...item, opacity: item.opacity ?? 1 }));
    return from.map((item) => withoutMovieLabel({ ...item, opacity: item.opacity ?? 1 }));
  }
  const sourceAlpha = Math.max(0, 1 - 2 * clamped);
  const destAlpha = Math.max(0, 2 * clamped - 1);
  return [
    ...from.map((item) => withoutMovieLabel({ ...item, opacity: (item.opacity ?? 1) * sourceAlpha })),
    ...destination.map((item) => withoutMovieLabel({ ...item, id: `to-${item.id}`, opacity: (item.opacity ?? 1) * destAlpha })),
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
 * diameter = size, a tail triangle tangent to the head, and a white hole of diameter
 * 0.36 at the head centre. Total height is `DROP_PIN_ASPECT` x size, tip on the anchor.
 */
const DROP_PIN_DEVICE_HEAD = 100;
const DROP_PIN_PIXEL_RATIO = 2;

/** Head-to-tip aspect ratio, matching `maps_pins.PIN_ASPECT`. */
export const DROP_PIN_ASPECT = 1.45;

/** Head diameter in CSS px of the raster `dropPinImage` returns. */
export const DROP_PIN_HEAD_PX = DROP_PIN_DEVICE_HEAD / DROP_PIN_PIXEL_RATIO;
/** Head-to-tip height in CSS px of that raster. */
export const DROP_PIN_TOTAL_PX = DROP_PIN_HEAD_PX * DROP_PIN_ASPECT;
/** Emphasis applied to a selected drop pin's `icon-size`. */
export const DROP_PIN_SELECTED_SCALE = 1.08;

/** Screen-px-per-authored-px for a selected object's resize handles: the drop pin's box and
 * raster both carry `DROP_PIN_SELECTED_SCALE`, so its drag must read the handle through it too. */
export function selectedDragScale(kind: string, objectScale: number): number {
  return kind === "dropPin" ? objectScale * DROP_PIN_SELECTED_SCALE : objectScale;
}

/** Selection-box size for a drop pin whose unselected head measures `headPx` on screen. */
export function dropPinSelectionBox(headPx: number): { w: number; h: number } {
  const w = headPx * DROP_PIN_SELECTED_SCALE;
  return { w, h: (w * DROP_PIN_TOTAL_PX) / DROP_PIN_HEAD_PX };
}

function dropPinImage(color: string): ImageData {
  const size = DROP_PIN_DEVICE_HEAD;
  const height = Math.round(size * DROP_PIN_ASPECT);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(size, height);
  const half = size / 2;
  const d = height - half;
  const contactY = half + (half * half) / d;
  const contactHalfW = (half * Math.sqrt(d * d - half * half)) / d;
  ctx.beginPath();
  ctx.moveTo(half - contactHalfW, contactY);
  ctx.lineTo(half + contactHalfW, contactY);
  ctx.lineTo(half, height);
  ctx.closePath();
  ctx.moveTo(size, half);
  ctx.arc(half, half, half, 0, Math.PI * 2);
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

/** Gold_Wall_Input.key slide 8: corner scalar 9.57 at h~46 -> radius ~= 0.21*h. Mirrors `maps_pins.LABEL_RADIUS_FRAC`. */
const LABEL_RADIUS_FRAC = 0.21;
export const LABEL_PILL_ID = "church-label-pill";

export function labelPillImageId(name: string, color: string = DEFAULT_LABEL_PILL_COLOR): string {
  return `${LABEL_PILL_ID}-${labelNameKey(name)}-${churchLabelColor({ labelColor: color }).slice(1)}`;
}

function labelPillImageSized(cssW: number, cssH: number, name: string, scale: number, color: string): ImageData {
  const ratio = DROP_PIN_PIXEL_RATIO;
  const w = Math.max(1, Math.round(cssW * ratio));
  const h = Math.max(1, Math.round(cssH * ratio));
  return drawLabelPill(w, h, LABEL_RADIUS_FRAC * h, name, LABEL_FONT_PX * scale * ratio, color);
}

function drawLabelPill(w: number, h: number, cornerPx: number, name?: string, fontPx?: number, color: string = DEFAULT_LABEL_PILL_COLOR): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(w, h);
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, cornerPx);
  ctx.fillStyle = churchLabelColor({ labelColor: color });
  ctx.fill();
  if (name && fontPx) {
    ctx.font = `700 ${fontPx}px "Noto Sans", sans-serif`;
    ctx.fillStyle = "#FFFFFF";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(name, w / 2, h / 2);
  }
  return ctx.getImageData(0, 0, w, h);
}

function pruneLabelPillImages(map: MapLibreMap, keep: Set<string>) {
  const ids = typeof map.listImages === "function" ? map.listImages() : [];
  for (const id of ids) {
    if (!id.startsWith(`${LABEL_PILL_ID}-`) || keep.has(id)) continue;
    map.removeImage(id);
  }
}

/** Re-runnable: a style reload drops every image, so `addOverlays` calls this again.
 * Pills bake at 1×; stale name keys are removed so rename does not leak GPU images. */
export function ensureLabelPillImage(map: MapLibreMap, churches: MapsChurch[] = [], _objectScale = 1, numberPins = false) {
  const keep = new Set<string>();
  churches.forEach((church, index) => {
    if (church.showLabel !== true) return;
    const name = numberPins ? `${index + 1}. ${church.name}` : church.name;
    const color = churchLabelColor(church);
    const box = labelPillCssSize(name, LABEL_PILL_BAKE_SCALE);
    const id = labelPillImageId(name, color);
    keep.add(id);
    if (map.hasImage(id)) return;
    map.addImage(id, labelPillImageSized(box.w, box.h, name, LABEL_PILL_BAKE_SCALE, color), { pixelRatio: DROP_PIN_PIXEL_RATIO });
  });
  pruneLabelPillImages(map, keep);
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

/** Re-applies `churchesLayers()` onto an already-installed source so HMR / spec tweaks
 * take effect without recreating the map. No-op when the source is missing. */
export function syncChurchesLayerSpecs(map: MapLibreMap): void {
  if (!map.getSource("churches")) return;
  for (const layer of churchesLayers()) {
    if (!map.getLayer(layer.id)) {
      map.addLayer(layer);
      continue;
    }
    if ("layout" in layer && layer.layout) {
      for (const [key, value] of Object.entries(layer.layout)) {
        map.setLayoutProperty(layer.id, key as never, value as never);
      }
    }
    if ("paint" in layer && layer.paint) {
      for (const [key, value] of Object.entries(layer.paint)) {
        map.setPaintProperty(layer.id, key as never, value as never);
      }
    }
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
        "circle-stroke-width": zoomScaledStops(["*", DOT_BORDER_PT, ["get", "objectScale"], ["/", ["get", "size"], defaultObjectSize("dot")]]),
        "circle-stroke-color": "#000000",
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
        "icon-size": zoomScaledStops(["/", ["*", ["coalesce", ["get", "size"], 120], ["get", "objectScale"]], ["max", 1, ["get", "assetRenderWidth"]]], ICON_SIZE_PACK_MAX),
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
        "icon-size": zoomScaledStops(["*", ["case", ["boolean", ["get", "sel"], false], DROP_PIN_SELECTED_SCALE, 1], ["get", "size"], ["get", "objectScale"], 1 / DROP_PIN_HEAD_PX], ICON_SIZE_PACK_MAX),
      },
      paint: { "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
    },
    {
      id: "churches-labels",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "showLabel"], true],
      layout: {
        // Name is painted into the pill PNG. A separate text-field used em offsets while
        // icon-offset is in image pixels, so "CHC Medan" drifted off its bar; icon-text-fit
        // stretched to the wrap box and left empty red bars. Baking keeps them glued.
        "text-field": "",
        "icon-image": ["get", "labelPill"],
        "icon-anchor": "bottom",
        "icon-offset": labelOffsetExpression(),
        "icon-size": zoomScaledStops(["*", ["get", "labelScale"], ["get", "objectScale"]], LABEL_SCALE_MAX, LABEL_SCALE_MIN),
        "icon-text-fit": "none",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: { "icon-opacity": ["coalesce", ["get", "labelOpacity"], 1] },
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
  isolate?: MapsIsolate,
  extraAdmin1: string[] = [],
  isCurrent: IsCurrent = ALWAYS_CURRENT,
  highlightColourOverride?: string,
  highlightColours?: Record<string, string>
) {
  await ensureAdmin0Highlights(map, highlights, styleId, isolate, 0, extraAdmin1, isCurrent, highlightColourOverride, highlightColours);
  if (!isCurrent()) return;
  ensureDropPinImages(map, churches);
  ensureLabelPillImage(map, churches, objectScale, numberPins);
  await ensureLandmarkImages(map, churches, assetBaseUrl);
  if (!isCurrent()) return;
  const pins = churchesGeo(churches, selectedPinId, numberPins, objectScale);
  if (!map.getSource("churches")) {
    map.addSource("churches", { type: "geojson", data: pins, promoteId: "id" });
    for (const layer of churchesLayers()) map.addLayer(layer);
  } else {
    (map.getSource("churches") as GeoJSONSource).setData(pins);
  }
  applyHighlights(map, highlights, highlightColours);
  applyAdmin1Highlights(map, highlights, highlightColours);
  applyIsolate(map, highlights, isolate);
}
