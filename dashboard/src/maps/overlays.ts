import {
  GeoJSONSource,
  type DataDrivenPropertyValueSpecification,
  type LayerSpecification,
  type Map as MapLibreMap,
} from "maplibre-gl";
import { isolateMaskGeometry } from "./isolate";
import { shift } from "./tonerBoundaries";
import { HILLSHADE_LAYER_ID, HILLSHADE_NE2_LAYER_ID, ML_MAX_ZOOM, ML_MIN_ZOOM, type MapsChurch, type MapsIsolate, type MapsStyleId } from "./types";
import { defaultObjectSize, zoomScaledStops } from "./objects";
import { highlightColour, setHighlightColour } from "./highlight";

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

export function applyHighlights(map: MapLibreMap, highlights: string[]) {
  if (!map.getSource("admin0") || !admin0Cache) return;
  const wanted = new Set(highlights.filter((h) => !h.startsWith("A1:")).map((h) => h.toUpperCase()));
  for (const feat of admin0Cache.features) {
    const id = String(feat.properties?.ADM0_A3 || "");
    if (!id) continue;
    map.setFeatureState({ source: "admin0", id }, { hl: wanted.has(id.toUpperCase()) });
  }
}

export const ADMIN0_FILL_OPACITY = 0.4;
export const ADMIN0_LINE_OPACITY = 0.9;
export const ADMIN1_FILL_OPACITY = 0.4;
export const ADMIN1_LINE_OPACITY = 0.9;

/** Highlighted-country fill/line opacity, keyed off `feature-state.hl` set by `applyHighlights`. */
export function admin0PaintExpression(on: number): DataDrivenPropertyValueSpecification<number> {
  return ["case", ["boolean", ["feature-state", "hl"], false], on, 0] as DataDrivenPropertyValueSpecification<number>;
}

/** Highlighted-region ids drive an `["in", …]` expression rather than feature state: one
 * `setPaintProperty` repaints every region, and no `promoteId` is needed on the source. */
export function admin1PaintExpression(
  highlights: string[],
  on: number
): DataDrivenPropertyValueSpecification<number> {
  const bare = new Set(highlights.filter((h) => !h.startsWith("A1:")).map((h) => h.toUpperCase()));
  const ids = [
    ...new Set(
      highlights
        .filter((h) => h.startsWith("A1:"))
        .map((h) => h.slice(3))
        .filter((id) => !bare.has(id.slice(0, 3).toUpperCase()))
    ),
  ];
  return ["case", ["in", ["get", "adm1_code"], ["literal", ids]], on, 0] as DataDrivenPropertyValueSpecification<number>;
}

export function applyAdmin1Highlights(map: MapLibreMap, highlights: string[]): void {
  if (!map.getLayer("admin1-fill")) return;
  map.setPaintProperty("admin1-fill", "fill-opacity", admin1PaintExpression(highlights, ADMIN1_FILL_OPACITY));
  map.setPaintProperty("admin1-line", "line-opacity", admin1PaintExpression(highlights, ADMIN1_LINE_OPACITY));
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
  highlightColourOverride?: string
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
          "fill-color": colour,
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
          "line-color": colour,
          "line-width": 1.2,
          "line-opacity": admin0PaintExpression(ADMIN0_LINE_OPACITY),
        },
      },
      before
    );
  }
  ensureAdmin1Layers(map, admin1Codes, colour);
  applyHighlights(map, highlights);
  applyAdmin1Highlights(map, highlights);
  applyIsolate(map, highlights, isolate);
}

/** Sets the module-level highlight colour and repaints the admin-0/admin-1 layers already on `map`. */
export function applyHighlightColour(map: MapLibreMap, colour: string): void {
  setHighlightColour(colour);
  const next = highlightColour();
  if (map.getLayer("admin0-fill")) map.setPaintProperty("admin0-fill", "fill-color", next);
  if (map.getLayer("admin0-line")) map.setPaintProperty("admin0-line", "line-color", next);
  if (map.getLayer("admin1-fill")) map.setPaintProperty("admin1-fill", "fill-color", next);
  if (map.getLayer("admin1-line")) map.setPaintProperty("admin1-line", "line-color", next);
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
function ensureAdmin1Layers(map: MapLibreMap, codes: string[], highlightColourOverride?: string): void {
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
    return;
  }
  map.addSource("admin1", { type: "geojson", data });
  // Pin admin1-fill below isolate-fill regardless of which layer is (re)created first, so the
  // isolate mask always stays on top of the region fill, matching today's look.
  const before = map.getLayer("isolate-fill") ? "isolate-fill" : firstSymbolId(map);
  const colour = highlightColourOverride ?? highlightColour();
  map.addLayer(
    {
      id: "admin1-fill",
      type: "fill",
      source: "admin1",
      paint: { "fill-color": colour, "fill-opacity": 0 },
    },
    before
  );
  map.addLayer(
    {
      id: "admin1-line",
      type: "line",
      source: "admin1",
      paint: { "line-color": colour, "line-width": 1.2, "line-opacity": 0 },
    },
    before
  );
}

const LABEL_SCALE_MIN = 0.5;
const LABEL_SCALE_MAX = 8;
export const LABEL_GAP_EMS = 0.35;
/** Mirrors `maps_keynote.PILL_PAD_X` / `PILL_PAD_Y`. */
const PILL_PAD_X_PX = 6;
export const PILL_PAD_Y_PX = 2;

/** Mirrors `maps_keynote._label_scale`: authored size over the kind's default, every kind alike.
 * The zoom-driven half of the total scale lives in the `text-size` stops, which carry the clamp. */
function labelScale(kind: string, size: number, assetWidth = 0): number {
  const base = defaultObjectSize(kind, assetWidth);
  return base ? size / base : 1;
}

/** `icon-text-fit-padding` and an image's corner radius are layout constants, so the pill's
 * padding and radius can only follow the label through a data-driven `icon-image`: one baked
 * variant per bucket of `scale * objectScale`, which is the non-zoom half of the rendered text
 * size (`24 * labelScale * objectScale`, see `text-size` below). The buckets are an octave apart
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

/** LABEL: the pill's bottom sits `LABEL_GAP_EMS` of the rendered text size above the marker's
 * rendered top, as the export's `top - LABEL_GAP * scale` pill bottom does. `text-offset` is in
 * ems of the rendered — i.e. clamped — text size, so past the 0.5x..8x clamp a fixed ratio stops
 * tracking a `scaleWithMap` marker, which keeps growing with zoom. Expressions cannot build an
 * array, so the zoom-dependent ratio ships as one offset property per integer zoom and
 * `text-offset` interpolates between them (see `labelOffsetExpression`). A selected drop pin's
 * `icon-size` carries `DROP_PIN_SELECTED_SCALE` (see below): selection is known per-feature at
 * GeoJSON build time (`sel`, from `selectedPinId`), so `markerHeightPx` folds that scale into the
 * marker height feeding these offsets instead of needing `text-offset` to read the icon's state. */
function labelOffsets(markerPx: number, totalScale: number, bucket: number, scaleWithMap: boolean, sizeZoomRef: number): Record<string, [number, number]> {
  const factorAt = (zoom: number) => (scaleWithMap ? Math.pow(2, zoom - sizeZoomRef) : 1);
  const textAt = (zoom: number) => Math.min(24 * LABEL_SCALE_MAX, Math.max(24 * LABEL_SCALE_MIN, 24 * totalScale * factorAt(zoom)));
  const needAt = (zoom: number, textPx: number) => (markerPx * factorAt(zoom) + PILL_PAD_Y_PX * bucket) / textPx + LABEL_GAP_EMS;
  const zooms = Array.from({ length: ML_MAX_ZOOM - ML_MIN_ZOOM + 1 }, (_, index) => ML_MIN_ZOOM + index);
  const text = zooms.map(textAt);
  const need = zooms.map((zoom, index) => needAt(zoom, text[index]));
  // Between two stops MapLibre interpolates the offset and the text size independently, and the
  // product of those two chords dips below what the (still geometric) marker needs. Substituting
  // u = 2^(z - z0), u in [1, 2] — base-2 interpolation is affine in u — the size chord is
  // S(u) = a + b*u, the offset chord is N(u) = c + d*u, and a scaleWithMap marker is exactly K*u,
  // so the shortfall in ems is h(u) = (K*u + P)/S(u) + LABEL_GAP_EMS - N(u), with P the pill
  // padding. h'(u) = (K*a - b*P)/S(u)^2 - d is monotone in u (S > 0 across the segment), so h has
  // at most one interior extremum and h(1) = h(2) = 0 by construction: the exact dip is h at the
  // closed-form root of h'. Lifting both stops of the segment by it lifts the whole chord clear.
  const slack = zooms.map(() => 0);
  const padPx = PILL_PAD_Y_PX * bucket;
  for (let index = 0; index + 1 < zooms.length; index++) {
    const b = text[index + 1] - text[index];
    const a = text[index] - b;
    const d = need[index + 1] - need[index];
    const c = need[index] - d;
    if (!scaleWithMap || b === 0 || d === 0) continue;
    const marker = markerPx * factorAt(zooms[index]);
    const square = (marker * a - b * padPx) / d;
    if (!(square > 0)) continue;
    const root = (Math.sqrt(square) - a) / b;
    if (!(root > 1 && root < 2)) continue;
    const dip = (marker * root + padPx) / (a + b * root) + LABEL_GAP_EMS - (c + d * root);
    if (!(dip > 0)) continue;
    slack[index] = Math.max(slack[index], dip);
    slack[index + 1] = Math.max(slack[index + 1], dip);
  }
  const offsets: Record<string, [number, number]> = {};
  zooms.forEach((zoom, index) => {
    offsets[labelOffsetProperty(zoom)] = [0, -(need[index] + slack[index])];
  });
  return offsets;
}

/** Base-2 interpolation between the per-zoom offsets, the same ramp shape `text-size` uses. */
function labelOffsetExpression(): DataDrivenPropertyValueSpecification<[number, number]> {
  const stops: unknown[] = ["interpolate", ["exponential", 2], ["zoom"]];
  for (let zoom = ML_MIN_ZOOM; zoom <= ML_MAX_ZOOM; zoom++) stops.push(zoom, ["array", "number", 2, ["get", labelOffsetProperty(zoom)]]);
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
      return {
        type: "Feature",
        properties: {
          id: church.id,
          name: numberPins ? `${index + 1}. ${church.name}` : church.name,
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
          sel: church.id === selectedPinId,
          objectScale,
          scaleWithMap: church.scaleWithMap === true,
          sizeZoomRef: (church.sizeZoom ?? 0) + Math.log2(objectScale),
          labelScale: scale,
          labelBucket: String(bucket),
          ...labelOffsets(
            markerHeightPx(church, size, church.id === selectedPinId) * objectScale,
            scale * objectScale,
            bucket,
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

/** Gold_Wall_Input.key slide 8: corner scalar 9.57 at h~46 -> radius ~= 0.21*h. Mirrors `maps_pins.LABEL_RADIUS_FRAC`. */
const LABEL_RADIUS_FRAC = 0.21;
export const LABEL_PILL_ID = "church-label-pill";
const LABEL_PILL_TEMPLATE_W = 64;
const LABEL_PILL_TEMPLATE_H = 32;

export function labelPillImageId(bucket: number): string {
  return `${LABEL_PILL_ID}-${bucket}`;
}

function labelPillBox(bucket: number): { w: number; h: number; cornerPx: number; padX: number; padY: number } {
  const w = LABEL_PILL_TEMPLATE_W * bucket * DROP_PIN_PIXEL_RATIO;
  const h = LABEL_PILL_TEMPLATE_H * bucket * DROP_PIN_PIXEL_RATIO;
  return {
    w,
    h,
    cornerPx: LABEL_RADIUS_FRAC * h,
    padX: PILL_PAD_X_PX * bucket * DROP_PIN_PIXEL_RATIO,
    padY: PILL_PAD_Y_PX * bucket * DROP_PIN_PIXEL_RATIO,
  };
}

function labelPillImage(bucket: number): ImageData {
  const { w, h, cornerPx } = labelPillBox(bucket);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(w, h);
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, cornerPx);
  ctx.fillStyle = "#EE220C";
  ctx.fill();
  return ctx.getImageData(0, 0, w, h);
}

/** Re-runnable: a style reload drops every image, so `addOverlays` calls this again. */
export function ensureLabelPillImage(map: MapLibreMap) {
  for (const bucket of LABEL_PILL_BUCKETS) {
    const id = labelPillImageId(bucket);
    if (map.hasImage(id)) continue;
    const { w, h, cornerPx, padX, padY } = labelPillBox(bucket);
    map.addImage(id, labelPillImage(bucket), {
      pixelRatio: DROP_PIN_PIXEL_RATIO,
      stretchX: [[cornerPx, w - cornerPx]],
      stretchY: [[cornerPx, h - cornerPx]],
      // The content inset is the pill padding: `icon-text-fit` sizes the image so this box
      // covers the text, leaving a bucket-scaled margin all round.
      content: [padX, padY, w - padX, h - padY],
    });
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
        "text-size": zoomScaledStops(["*", 24, ["get", "labelScale"], ["get", "objectScale"]], 24 * LABEL_SCALE_MAX, 24 * LABEL_SCALE_MIN),
        "text-offset": labelOffsetExpression(),
        "text-anchor": "bottom",
        "text-allow-overlap": true,
        "text-ignore-placement": true,
        "icon-image": ["concat", `${LABEL_PILL_ID}-`, ["get", "labelBucket"]],
        "icon-text-fit": "both",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: { "text-color": "#FFFFFF", "text-opacity": ["coalesce", ["get", "opacity"], 1], "icon-opacity": ["coalesce", ["get", "opacity"], 1] },
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
  highlightColourOverride?: string
) {
  await ensureAdmin0Highlights(map, highlights, styleId, isolate, 0, extraAdmin1, isCurrent, highlightColourOverride);
  if (!isCurrent()) return;
  ensureDropPinImages(map, churches);
  ensureLabelPillImage(map);
  await ensureLandmarkImages(map, churches, assetBaseUrl);
  if (!isCurrent()) return;
  const pins = churchesGeo(churches, selectedPinId, numberPins, objectScale);
  if (!map.getSource("churches")) {
    map.addSource("churches", { type: "geojson", data: pins, promoteId: "id" });
    for (const layer of churchesLayers()) map.addLayer(layer);
  } else {
    (map.getSource("churches") as GeoJSONSource).setData(pins);
  }
  applyHighlights(map, highlights);
  applyAdmin1Highlights(map, highlights);
  applyIsolate(map, highlights, isolate);
}
