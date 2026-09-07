export type MapsStyleId = "positron" | "liberty" | "bright" | "dark" | "fiord" | "buildings3d";
export type MapsCropId = "wall" | "center+cg";
export type MapsLayerFilterId =
  | "roads"
  | "roadnames"
  | "shields"
  | "pois"
  | "rail"
  | "buildings"
  | "labels"
  | "boundaries";
export type MapsHopKind = "morph" | "movie" | "dissolve" | "cut";
export type MapsPinKind = "dot" | "dropPin";
export type MapsIconId = "none" | "building" | "cross";
export type MapsEasing = "ease-in-out" | "linear" | "ease-in" | "ease-out";

export type MapsCamera = {
  lat: number;
  lon: number;
  zoom: number;
  bearing: number;
  pitch: number;
};

export type MapsChurch = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  kind: MapsPinKind;
  color: string;
  icon?: MapsIconId;
  photoPath?: string;
};

export type MapsSlide = {
  id: string;
  title: string;
  style: MapsStyleId;
  camera: MapsCamera;
  highlights: string[];
  churches: MapsChurch[];
  stillPng?: string;
  cgShiftX: number;
  cgShiftY: number;
  includeSidePanels: boolean;
};

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
};

export type MapsDocument = {
  defaultStyle: MapsStyleId;
  crop: MapsCropId;
  exportLw: boolean;
  exportCg: boolean;
  hiddenLayers: MapsLayerFilterId[];
  cachedCountries: string[];
  slides: MapsSlide[];
  links: MapsLink[];
};

export const LAYER_FILTERS: { id: MapsLayerFilterId; label: string }[] = [
  { id: "roads", label: "Roads" },
  { id: "roadnames", label: "Road names" },
  { id: "shields", label: "Road signs" },
  { id: "pois", label: "POIs (bus stops…)" },
  { id: "rail", label: "Rail" },
  { id: "buildings", label: "Buildings" },
  { id: "labels", label: "Place labels" },
  { id: "boundaries", label: "Boundaries" },
];

const LAYER_FILTER_IDS = new Set(LAYER_FILTERS.map((item) => item.id));

export const DEFAULT_HIDDEN_LAYERS: MapsLayerFilterId[] = ["roadnames"];

export function parseHiddenLayers(raw: unknown): MapsLayerFilterId[] {
  if (raw == null) return [...DEFAULT_HIDDEN_LAYERS];
  if (!Array.isArray(raw)) return [...DEFAULT_HIDDEN_LAYERS];
  return raw.filter((item): item is MapsLayerFilterId => typeof item === "string" && LAYER_FILTER_IDS.has(item as MapsLayerFilterId));
}

export const HOP_LABELS: Record<MapsHopKind, string> = {
  morph: "Magic Move",
  movie: "Movie",
  dissolve: "Dissolve",
  cut: "Cut",
};

export const HOP_TIPS: Record<MapsHopKind, string> = {
  morph: "Keynote Magic Move on one oversized map plate — pan/zoom only.",
  movie: "Keynote movie. Used for pitch, bearing, 3D, or a large zoom jump. Three phases: zoom out, move, zoom in.",
  dissolve: "Keynote Dissolve. Crossfade stills over the hop duration.",
  cut: "Instant cut. Used when the map style or region highlights change.",
};

export const MORPH_MAX_PITCH = 0.5;
export const MORPH_MAX_BEARING = 0.5;
export const MORPH_MAX_DZOOM = 1;
export const MORPH_MAX_PLATE_PX = 8192;
const TILE_SIZE = 512;
export const WALL_W = 7680;
export const WALL_H = 1080;
export const CENTRE_W = 3840;
export const CENTRE_ORIGIN_X = 1920;

export function captureWidth(slide: { includeSidePanels?: boolean }): number {
  return slide.includeSidePanels ? WALL_W : CENTRE_W;
}

export function coerceHopKinds(doc: MapsDocument): MapsDocument {
  const byId = new Map(doc.slides.map((slide) => [slide.id, slide]));
  return {
    ...doc,
    links: doc.links.map((link) => {
      const from = byId.get(link.from);
      const to = byId.get(link.to);
      if (!from || !to) return link;
      const suggested = suggestedHopKind(from, to);
      let next: MapsLink = link;
      if (link.kind === "morph" && suggested !== "morph") {
        next = { ...link, kind: suggested };
        delete next.plateId;
      } else if (link.kind === "movie" && suggested === "cut") {
        next = { ...link, kind: "cut" };
        delete next.plateId;
      }
      if (next.kind !== "movie") {
        delete next.easing;
        delete next.route;
        delete next.easeIn;
        delete next.easeOut;
        delete next.flyZoom;
      }
      return next;
    }),
  };
}

export function inferHopKind(from: MapsSlide, to: MapsSlide): MapsHopKind {
  const fromHi = [...from.highlights].map((h) => h.toUpperCase()).sort().join(",");
  const toHi = [...to.highlights].map((h) => h.toUpperCase()).sort().join(",");
  if (from.style !== to.style || fromHi !== toHi) return "cut";
  const pitch = Math.max(Math.abs(from.camera.pitch), Math.abs(to.camera.pitch));
  const bearing = Math.max(Math.abs(from.camera.bearing), Math.abs(to.camera.bearing));
  const dZoom = Math.abs(from.camera.zoom - to.camera.zoom);
  if (from.style === "buildings3d" || to.style === "buildings3d" || pitch > MORPH_MAX_PITCH || bearing > MORPH_MAX_BEARING || dZoom > MORPH_MAX_DZOOM) {
    return "movie";
  }
  return "morph";
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

function mercatorY(lat: number): number {
  const clamped = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const rad = (clamped * Math.PI) / 180;
  const sin = Math.sin(rad);
  return 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI);
}

function wallViewport(camera: MapsCamera, width = WALL_W, height = WALL_H): { x0: number; y0: number; x1: number; y1: number } {
  const world = TILE_SIZE * 2 ** camera.zoom;
  const cx = (wrapLon(camera.lon) + 180) / 360;
  const cy = mercatorY(camera.lat);
  const nw = width / world;
  const nh = height / world;
  return { x0: cx - nw / 2, y0: cy - nh / 2, x1: cx + nw / 2, y1: cy + nh / 2 };
}

/** Union plate at the deeper zoom, same math as Keynote `morph_plate_geom`. */
export function morphPlatePx(
  from: MapsCamera,
  to: MapsCamera,
  fromW = WALL_W,
  toW = WALL_W,
): { w: number; h: number } | null {
  const a = wallViewport(from, fromW);
  const b = wallViewport(to, toW);
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
/** `log2(7680 / 512)` — world at least as wide as the 7680 wall, so wrap does not tile. Preview MapLibre zoom is offset by `log2(cssWidth / 7680)` so the FW band matches export. */
export const WORLD_MIN_ZOOM = Math.log2(7680 / 512);

/** Same wrap as `maps_geo.clamp_lon` — persist cameras in (−180, 180]. */
export function wrapLon(lon: number): number {
  let next = lon;
  while (next > 180) next -= 360;
  while (next < -180) next += 360;
  return next;
}

export function clampZoom(zoom: number): number {
  return Math.max(WORLD_MIN_ZOOM, Math.min(22, zoom));
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

export function documentFromResult(result: Record<string, unknown> | null | undefined): MapsDocument | null {
  if (!result || !Array.isArray(result.slides)) return null;
  const slides = (result.slides as MapsSlide[]).map((slide) => ({
    ...slide,
    cgShiftX: slide.cgShiftX ?? 0,
    cgShiftY: slide.cgShiftY ?? 0,
    includeSidePanels: slide.includeSidePanels === true,
    highlights: slide.highlights || [],
    churches: slide.churches || [],
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
    return next;
  });
  return coerceHopKinds({
    defaultStyle: (result.defaultStyle as MapsStyleId) || "positron",
    crop: (result.crop as MapsCropId) || "center+cg",
    exportLw: result.exportLw !== false,
    exportCg: result.exportCg !== false,
    hiddenLayers: parseHiddenLayers(result.hiddenLayers),
    cachedCountries: Array.isArray(result.cachedCountries)
      ? (result.cachedCountries as unknown[]).filter((item): item is string => typeof item === "string")
      : [],
    slides,
    links,
  });
}
