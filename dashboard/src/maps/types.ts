export const HILLSHADE_LAYER_ID = "hillshade";
export const HILLSHADE_SOURCE_ID = "terrarium";
export const HILLSHADE_NE2_LAYER_ID = "terrarium-ne2";

export type MapsStyleId = "positron" | "liberty" | "bright" | "dark" | "fiord" | "buildings3d" | "toner" | "toner-background" | "toner-lines" | "watercolour";
export type MapsCropId = "wall" | "center+cg";
export type MapsLayerFilterId =
  | "roads"
  | "roadnames"
  | "shields"
  | "arrows"
  | "pois"
  | "rail"
  | "buildings"
  | "labels"
  | "boundaries";
export type MapsHopKind = "morph" | "movie" | "dissolve" | "cut";
export type MapsPinKind = "dot" | "dropPin" | "landmark";
export type MapsIconId = "none" | "building" | "cross";
export type MapsEasing = "ease-in-out" | "linear" | "ease-in" | "ease-out";

export type MapsCamera = {
  lat: number;
  lon: number;
  zoom: number;
  bearing: number;
  pitch: number;
};

export type MapsIsolate = { mode: "darken"; strength: number };

export type MapsChurch = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  kind: MapsPinKind;
  color: string;
  showLabel?: boolean;
  icon?: MapsIconId;
  photoPath?: string;
  assetId?: string;
  assetVersion?: string;
  assetWidth?: number;
  assetHeight?: number;
  size?: number;
  opacity?: number;
};

export type MapsCgOverride = {
  camera: MapsCamera;
  style: MapsStyleId;
  highlights: string[];
  churches: MapsChurch[];
  hiddenLayers?: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  stillPng?: string;
  movieMov?: string;
  movieDuration?: number;
};

export type MapsSlide = {
  id: string;
  title: string;
  style: MapsStyleId;
  camera: MapsCamera;
  highlights: string[];
  churches: MapsChurch[];
  hiddenLayers?: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  stillPng?: string;
  movieMov?: string;
  movieDuration?: number;
  cgShiftX: number;
  cgShiftY: number;
  includeSidePanels: boolean;
  cg?: MapsCgOverride;
};

export type MapsAudience = "lw" | "cg";

export function slideForAudience(slide: MapsSlide, audience: MapsAudience): MapsSlide {
  if (audience !== "cg" || !slide.cg) return slide;
  return { ...slide, ...slide.cg, cgShiftX: 0, cgShiftY: 0, includeSidePanels: false };
}

export function authoredSurfaceWidth(slide: MapsSlide, audience: MapsAudience): number {
  if (audience === "cg" && slide.cg) return CG_W;
  return captureWidth(slide);
}

export type MapsRoutePoint = { lat: number; lon: number };

export type MapsRoute = { points: MapsRoutePoint[] };

export type MapsLink = {
  from: string;
  to: string;
  kind: MapsHopKind;
  duration: number;
  playWithoutClick: boolean;
  easing?: MapsEasing;
  plateId?: string;
  route?: MapsRoute;
  easeIn?: number;
  easeOut?: number;
  flyZoom?: number;
  curve?: number;
  objectTransition?: "fade" | "hold";
};

export type MapsAsset = {
  id: string;
  version: string;
  width: number;
  height: number;
};

export type MapsDocument = {
  defaultStyle: MapsStyleId;
  crop: MapsCropId;
  exportLw: boolean;
  exportCg: boolean;
  exportDsk: boolean;
  hiddenLayers: MapsLayerFilterId[];
  cachedCountries: string[];
  assets: MapsAsset[];
  slides: MapsSlide[];
  links: MapsLink[];
};

export const LAYER_FILTERS: { id: MapsLayerFilterId; label: string }[] = [
  { id: "roads", label: "Roads" },
  { id: "roadnames", label: "Road names" },
  { id: "shields", label: "Road signs" },
  { id: "arrows", label: "One-way arrows" },
  { id: "pois", label: "POIs (bus stops…)" },
  { id: "rail", label: "Rail" },
  { id: "buildings", label: "Buildings" },
  { id: "labels", label: "Place labels" },
  { id: "boundaries", label: "Boundaries" },
];

const LAYER_FILTER_IDS = new Set(LAYER_FILTERS.map((item) => item.id));

export const DEFAULT_HIDDEN_LAYERS: MapsLayerFilterId[] = ["roadnames", "arrows"];

export function parseHiddenLayers(raw: unknown): MapsLayerFilterId[] {
  if (raw == null) return [...DEFAULT_HIDDEN_LAYERS];
  if (!Array.isArray(raw)) return [...DEFAULT_HIDDEN_LAYERS];
  return raw.filter((item): item is MapsLayerFilterId => typeof item === "string" && LAYER_FILTER_IDS.has(item as MapsLayerFilterId));
}

export function slideHiddenLayers(source: { hiddenLayers?: unknown } | null | undefined): MapsLayerFilterId[] {
  return parseHiddenLayers(source?.hiddenLayers);
}

export const HOP_LABELS: Record<MapsHopKind, string> = {
  morph: "Magic Move",
  movie: "Movie",
  dissolve: "Dissolve",
  cut: "Cut",
};

export const HOP_TIPS: Record<MapsHopKind, string> = {
  morph: "Keynote Magic Move on one oversized map plate — pan/zoom only.",
  movie: "Keynote movie. Used for pitch, bearing changes, 3D, or a shared plate that is too large. Fly phases are optional.",
  dissolve: "Keynote Dissolve. Crossfade stills over the hop duration.",
  cut: "Instant cut. Used when the map style or region highlights change.",
};

export const MORPH_MAX_PITCH = 0.5;
export const MORPH_MAX_DBEARING = 0.05;
export const MORPH_MAX_DZOOM = 2;
export const MORPH_MAX_PLATE_PX = 8192;
const TILE_SIZE = 512;
export const WALL_W = 7680;
export const WALL_H = 1080;
export const CENTRE_W = 3840;
export const CENTRE_ORIGIN_X = 1920;
export const CG_W = 1920;

export function captureWidth(slide: { includeSidePanels?: boolean }): number {
  return slide.includeSidePanels ? WALL_W : CENTRE_W;
}

export function showCgBand(slide: { cg?: unknown }): boolean {
  return !slide.cg;
}

/** Band the preview canvas occupies inside the frame, at the authored aspect ratio (surfaceWidth × surfaceHeight). Matches the `.maps-map-band` CSS sizing. */
export function previewHostRect(
  frameWidth: number,
  frameHeight: number,
  surfaceWidth: number,
  surfaceHeight = 1080
): { x: number; y: number; width: number; height: number } {
  if (!frameWidth || !frameHeight) return { x: 0, y: 0, width: 0, height: 0 };
  const width = Math.min(frameWidth, (frameHeight * surfaceWidth) / surfaceHeight);
  const height = (width * surfaceHeight) / surfaceWidth;
  return { x: (frameWidth - width) / 2, y: (frameHeight - height) / 2, width, height };
}

export function coerceHopKinds(doc: MapsDocument): MapsDocument {
  const byId = new Map(doc.slides.map((slide) => [slide.id, slide]));
  return {
    ...doc,
    links: doc.links.map((link) => {
      const from = byId.get(link.from);
      const to = byId.get(link.to);
      if (!from || !to) return link;
      let suggested = suggestedHopKind(from, to);
      if (from.cg || to.cg) {
        const cgSuggested = suggestedHopKind(slideForAudience(from, "cg"), slideForAudience(to, "cg"));
        const rank = (kind: MapsHopKind) => (kind === "cut" ? 2 : kind === "movie" ? 1 : 0);
        if (rank(cgSuggested) > rank(suggested)) suggested = cgSuggested;
      }
      let next: MapsLink = link;
      if (link.kind === "morph" && suggested !== "morph") {
        next = { ...link, kind: suggested };
        if (suggested === "movie") next.objectTransition = "fade";
        delete next.plateId;
      }
      if (next.kind !== "movie") {
        delete next.easing;
        delete next.route;
        delete next.easeIn;
        delete next.easeOut;
        delete next.flyZoom;
        delete next.curve;
        delete next.objectTransition;
      }
      return next;
    }),
  };
}

export type MapsAppearanceField = "style" | "highlights" | "hiddenLayers" | "hillshade" | "isolate";

export function appearanceMismatch(from: MapsSlide, to: MapsSlide): MapsAppearanceField[] {
  const out: MapsAppearanceField[] = [];
  if (from.style !== to.style) out.push("style");
  const hi = (s: MapsSlide) => [...s.highlights].map((h) => h.toUpperCase()).sort().join(",");
  if (hi(from) !== hi(to)) out.push("highlights");
  const layers = (s: MapsSlide) => slideHiddenLayers(s).sort().join(",");
  if (layers(from) !== layers(to)) out.push("hiddenLayers");
  if ((from.hillshade === true) !== (to.hillshade === true)) out.push("hillshade");
  const iso = (s: MapsSlide) => (s.isolate ? `${s.isolate.mode}:${s.isolate.strength.toFixed(2)}` : "off");
  if (iso(from) !== iso(to)) out.push("isolate");
  return out;
}

/** Isolate/highlight mismatches on a Movie hop are expected (landing slide or darkened fly + cut) — never style/layers. */
export function softMovieFields(_from: MapsSlide, _to: MapsSlide): Set<MapsAppearanceField> {
  return new Set<MapsAppearanceField>(["highlights", "isolate"]);
}

export function movieAppearanceMismatch(from: MapsSlide, to: MapsSlide): boolean {
  const target: MapsSlide = to.isolate && to.highlights.length ? { ...to, highlights: [], isolate: undefined } : to;
  if (appearanceMismatch(from, target).length > 0) return true;
  if (!from.cg && !target.cg) return false;
  return appearanceMismatch(slideForAudience(from, "cg"), slideForAudience(target, "cg")).length > 0;
}

export function inferHopKind(from: MapsSlide, to: MapsSlide): MapsHopKind {
  if (appearanceMismatch(from, to).length) return "cut";
  const pitch = Math.max(Math.abs(from.camera.pitch), Math.abs(to.camera.pitch));
  const dBearing = bearingDelta(from.camera.bearing, to.camera.bearing);
  const dZoom = Math.abs(from.camera.zoom - to.camera.zoom);
  if (from.style === "buildings3d" || to.style === "buildings3d" || pitch > MORPH_MAX_PITCH || dBearing > MORPH_MAX_DBEARING || dZoom > MORPH_MAX_DZOOM) {
    return "movie";
  }
  return "morph";
}

export function bearingDelta(from: number, to: number): number {
  return Math.abs(((to - from + 540) % 360) - 180);
}

export function plateFitsMorph(from: MapsSlide, to: MapsSlide): boolean {
  const plate = morphPlatePx(from.camera, to.camera, captureWidth(from), captureWidth(to));
  return plate != null && plate.w <= MORPH_MAX_PLATE_PX && plate.h <= MORPH_MAX_PLATE_PX;
}

/** Authoring suggestion: hop rules, then plate size (oversized morph becomes Movie). */
export function suggestedHopKind(from: MapsSlide, to: MapsSlide): MapsHopKind {
  const kind = inferHopKind(from, to);
  if (kind === "morph" && !plateFitsMorph(from, to)) return "movie";
  return kind;
}

export function restitchLinks(nextSlides: MapsSlide[], prevLinks: MapsLink[]): MapsLink[] {
  const links: MapsLink[] = [];
  for (let i = 0; i < nextSlides.length - 1; i++) {
    const from = nextSlides[i];
    const to = nextSlides[i + 1];
    const existing = prevLinks.find((link) => link.from === from.id && link.to === to.id);
    const kind = suggestedHopKind(from, to);
    links.push(
      existing || {
        from: from.id,
        to: to.id,
        kind,
        duration: 1.0,
        playWithoutClick: false,
        ...(kind === "movie" ? { objectTransition: "fade" as const } : {}),
      }
    );
  }
  return links;
}

function clearMovieFields(slide: MapsSlide): MapsSlide {
  const next: MapsSlide = { ...slide };
  delete next.movieMov;
  delete next.movieDuration;
  if (next.cg) {
    next.cg = { ...next.cg };
    delete next.cg.movieMov;
    delete next.cg.movieDuration;
  }
  return next;
}

/** Swap the slide at `id` with its neighbour `delta` away, restitch links, and drop stale movie renders on the affected outgoing hops. Returns `doc` unchanged if the move is out of range. */
export function reorderSlides(doc: MapsDocument, id: string, delta: number): MapsDocument {
  const index = doc.slides.findIndex((s) => s.id === id);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= doc.slides.length) return doc;
  const slides = [...doc.slides];
  [slides[index], slides[target]] = [slides[target], slides[index]];
  const clearIds = new Set([slides[index].id, slides[target].id]);
  const predecessor = slides[Math.min(index, target) - 1];
  if (predecessor) clearIds.add(predecessor.id);
  const nextSlides = slides.map((slide) => (clearIds.has(slide.id) ? clearMovieFields(slide) : slide));
  const links = restitchLinks(nextSlides, doc.links);
  return { ...doc, slides: nextSlides, links };
}

function mercatorY(lat: number): number {
  const clamped = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const rad = (clamped * Math.PI) / 180;
  const sin = Math.sin(rad);
  return 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI);
}

function rotatedMercator(x: number, y: number, bearing: number): { x: number; y: number } {
  const theta = (bearing * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);
  return { x: cos * x + sin * y, y: -sin * x + cos * y };
}

function wallViewport(camera: MapsCamera, width = WALL_W, height = WALL_H, bearing = camera.bearing): { x0: number; y0: number; x1: number; y1: number } {
  const world = TILE_SIZE * 2 ** camera.zoom;
  const cx = (wrapLon(camera.lon) + 180) / 360;
  const cy = mercatorY(camera.lat);
  const rotated = rotatedMercator(cx, cy, bearing);
  const nw = width / world;
  const nh = height / world;
  return { x0: rotated.x - nw / 2, y0: rotated.y - nh / 2, x1: rotated.x + nw / 2, y1: rotated.y + nh / 2 };
}

/** Union plate at the deeper zoom, same math as Keynote `morph_plate_geom`. */
export function morphPlatePx(
  from: MapsCamera,
  to: MapsCamera,
  fromW = WALL_W,
  toW = WALL_W,
): { w: number; h: number } | null {
  const sharedBearing = from.bearing;
  const a = wallViewport(from, fromW, WALL_H, sharedBearing);
  const b = wallViewport(to, toW, WALL_H, sharedBearing);
  const world = TILE_SIZE * 2 ** Math.max(from.zoom, to.zoom);
  const w = (Math.max(a.x1, b.x1) - Math.min(a.x0, b.x0)) * world;
  const h = (Math.max(a.y1, b.y1) - Math.min(a.y0, b.y0)) * world;
  if (w <= 1 || h <= 1) return null;
  return { w, h };
}

/** 1920 CG window slides inside the 3840 centre wall (1920–5760). */
export const CG_SHIFT_MAX = 960;

export function clampCgShift(dx: number, dy: number): { cgShiftX: number; cgShiftY: number } {
  let x = Math.max(-CG_SHIFT_MAX, Math.min(CG_SHIFT_MAX, dx));
  if (2880 + x < 1920) x = 1920 - 2880;
  if (2880 + x + 1920 > 5760) x = 5760 - 1920 - 2880;
  void dy;
  return { cgShiftX: x, cgShiftY: 0 };
}

export const MAX_LAT = 85.051129;
/**
 * Wrap thresholds — not an OSM/MapLibre limit (tiles go to z0).
 * One world is `512 * 2^z` px. Below the threshold for a capture width,
 * `renderWorldCopies` tiles continents and pins. Warning only; zoom is not clamped to these.
 */
export const WORLD_MIN_ZOOM = Math.log2(WALL_W / 512);
export const CENTRE_MIN_ZOOM = Math.log2(CENTRE_W / 512);
export const CG_MIN_ZOOM = Math.log2(CG_W / 512);

export function minZoomForView(): number {
  return 0;
}

/** Which export crops would show more than one world copy at this authored zoom. */
export function worldCopyWarning(zoom: number): string | null {
  if (!Number.isFinite(zoom) || zoom >= WORLD_MIN_ZOOM) return null;
  const tiled: string[] = ["FW"];
  if (zoom < CENTRE_MIN_ZOOM) tiled.push("LW");
  if (zoom < CG_MIN_ZOOM) tiled.push("CG");
  return `World copies tile in ${tiled.join(" / ")}. Pins and orange countries will repeat.`;
}

/** Same wrap as `maps_geo.clamp_lon` — persist cameras in (−180, 180]. */
export function wrapLon(lon: number): number {
  let next = lon;
  while (next > 180) next -= 360;
  while (next < -180) next += 360;
  return next;
}

export function clampZoom(zoom: number, minZoom = 0): number {
  return Math.max(minZoom, Math.min(22, zoom));
}

export function nextSlideId(slides: MapsSlide[]): string {
  let n = 1;
  const used = new Set(slides.map((s) => s.id));
  while (used.has(`s${n}`)) n += 1;
  return `s${n}`;
}

export function nextPinId(churches: MapsChurch[]): string {
  let n = 1;
  const used = new Set(churches.map((c) => c.id));
  while (used.has(`p${n}`)) n += 1;
  return `p${n}`;
}

export function parseRoute(raw: unknown): MapsRoute | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const points = (raw as { points?: unknown }).points;
  if (!Array.isArray(points) || points.length < 2) return undefined;
  const next: MapsRoutePoint[] = [];
  for (const point of points) {
    if (!point || typeof point !== "object") return undefined;
    const lat = Number((point as { lat?: unknown }).lat);
    const lon = Number((point as { lon?: unknown }).lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return undefined;
    next.push({ lat, lon });
  }
  return { points: next };
}

export function parseIsolate(raw: unknown): MapsIsolate | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const mode = (raw as { mode?: unknown }).mode;
  if (mode !== undefined && mode !== "darken" && mode !== "erase") return undefined;
  const strengthRaw = Number((raw as { strength?: unknown }).strength);
  const strength = Number.isFinite(strengthRaw) ? Math.max(0, Math.min(1, strengthRaw)) : 0.6;
  return { mode: "darken", strength };
}

function cgFromResult(cg: MapsCgOverride | undefined): MapsCgOverride | undefined {
  if (!cg) return undefined;
  const { hiddenLayers, hillshade, isolate, ...rest } = cg;
  const iso = parseIsolate(isolate);
  return {
    ...rest,
    highlights: cg.highlights || [],
    churches: cg.churches || [],
    ...(hiddenLayers ? { hiddenLayers: parseHiddenLayers(hiddenLayers) } : {}),
    ...(typeof hillshade === "boolean" ? { hillshade } : {}),
    ...(iso ? { isolate: iso } : {}),
    camera: { ...cg.camera, zoom: clampZoom(cg.camera.zoom), lon: wrapLon(cg.camera.lon) },
  };
}

export function documentFromResult(result: Record<string, unknown> | null | undefined): MapsDocument | null {
  if (!result || !Array.isArray(result.slides)) return null;
  const deckHidden = parseHiddenLayers(result.hiddenLayers);
  const slides = (result.slides as MapsSlide[]).map((slide) => ({
    ...slide,
    cgShiftX: slide.cgShiftX ?? 0,
    cgShiftY: slide.cgShiftY ?? 0,
    includeSidePanels: slide.includeSidePanels === true,
    highlights: slide.highlights || [],
    churches: slide.churches || [],
    hiddenLayers: parseHiddenLayers(slide.hiddenLayers ?? deckHidden),
    hillshade: slide.hillshade === true,
    isolate: parseIsolate(slide.isolate),
    cg: cgFromResult(slide.cg),
    camera: {
      ...slide.camera,
      zoom: clampZoom(slide.camera.zoom),
      lon: wrapLon(slide.camera.lon),
    },
  }));
  const links = ((result.links as MapsLink[]) || []).map((link) => {
    const route = parseRoute(link.route);
    const next: MapsLink = { ...link };
    if (route) next.route = route;
    else delete next.route;
    if (typeof next.easeIn !== "number" || !Number.isFinite(next.easeIn)) delete next.easeIn;
    if (typeof next.easeOut !== "number" || !Number.isFinite(next.easeOut)) delete next.easeOut;
    if (typeof next.flyZoom !== "number" || !Number.isFinite(next.flyZoom)) delete next.flyZoom;
    if (typeof next.curve !== "number" || !Number.isFinite(next.curve)) delete next.curve;
    if (next.objectTransition !== "fade" && next.objectTransition !== "hold") delete next.objectTransition;
    return next;
  });
  return coerceHopKinds({
    defaultStyle: (result.defaultStyle as MapsStyleId) || "positron",
    crop: (result.crop as MapsCropId) || "center+cg",
    exportLw: result.exportLw !== false,
    exportCg: result.exportCg !== false,
    exportDsk: result.exportDsk === true,
    hiddenLayers: deckHidden,
    cachedCountries: Array.isArray(result.cachedCountries)
      ? (result.cachedCountries as unknown[]).filter((item): item is string => typeof item === "string")
      : [],
    assets: Array.isArray(result.assets)
      ? (result.assets as MapsAsset[]).filter((asset) => asset && typeof asset.id === "string" && typeof asset.version === "string")
      : [],
    slides,
    links,
  });
}
