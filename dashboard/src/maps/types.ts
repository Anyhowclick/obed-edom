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
export type MapsHopKind = "morph" | "movie" | "cut";
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
};

export type MapsDocument = {
  defaultStyle: MapsStyleId;
  crop: MapsCropId;
  exportLw: boolean;
  exportCg: boolean;
  hiddenLayers: MapsLayerFilterId[];
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
  cut: "Cut",
};

export const HOP_TIPS: Record<MapsHopKind, string> = {
  morph: "Keynote Magic Move on one oversized map plate — pan/zoom only.",
  movie: "Keynote movie. Used for pitch, bearing, 3D, or a large zoom jump.",
  cut: "Instant cut. Used when the map style or orange countries change.",
};

export function coerceHopKinds(doc: MapsDocument): MapsDocument {
  const byId = new Map(doc.slides.map((slide) => [slide.id, slide]));
  return {
    ...doc,
    links: doc.links.map((link) => {
      const from = byId.get(link.from);
      const to = byId.get(link.to);
      if (!from || !to) return link;
      const suggested = inferHopKind(from, to);
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
  if (from.style === "buildings3d" || to.style === "buildings3d" || pitch > 0.5 || bearing > 0.5 || dZoom > 1) {
    return "movie";
  }
  return "morph";
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
    highlights: slide.highlights || [],
    churches: slide.churches || [],
  }));
  const links = ((result.links as MapsLink[]) || []).map((link) => {
    const route = parseRoute(link.route);
    const next: MapsLink = { ...link };
    if (route) next.route = route;
    else delete next.route;
    return next;
  });
  return coerceHopKinds({
    defaultStyle: (result.defaultStyle as MapsStyleId) || "positron",
    crop: (result.crop as MapsCropId) || "center+cg",
    exportLw: result.exportLw !== false,
    exportCg: result.exportCg !== false,
    hiddenLayers: parseHiddenLayers(result.hiddenLayers),
    slides,
    links,
  });
}
