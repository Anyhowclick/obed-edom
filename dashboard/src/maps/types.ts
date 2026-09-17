import { highlightColoursKey, isHighlightHex, normaliseHighlightColour, parseHighlightColours } from "./highlight";

export const HILLSHADE_LAYER_ID = "hillshade";
export const HILLSHADE_SOURCE_ID = "terrarium";
export const HILLSHADE_NE2_LAYER_ID = "terrarium-ne2";

export type MapsStyleId = "positron" | "bright" | "dark" | "fiord" | "buildings3d" | "borderlands" | "toner" | "toner-background" | "toner-lines" | "watercolour";

/** Retired picker id; OpenFreeMap Liberty is what `buildings3d` already loads. */
export function coerceMapsStyleId(value: unknown, fallback: MapsStyleId = "positron"): MapsStyleId {
  if (value === "liberty") return "buildings3d";
  if (
    value === "positron" ||
    value === "bright" ||
    value === "dark" ||
    value === "fiord" ||
    value === "buildings3d" ||
    value === "borderlands" ||
    value === "toner" ||
    value === "toner-background" ||
    value === "toner-lines" ||
    value === "watercolour"
  ) {
    return value;
  }
  return fallback;
}

export function isExtrudedStyle(value: unknown): boolean {
  const id = coerceMapsStyleId(value);
  return id === "buildings3d" || id === "borderlands";
}
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
  | "waternames"
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

export const DEFAULT_ISOLATE_STRENGTH = 0.65;

export type MapsChurch = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  kind: MapsPinKind;
  color: string;
  showLabel?: boolean;
  /** Pill background. Omitted = gold-red `#ee220c`. */
  labelColor?: string;
  icon?: MapsIconId;
  photoPath?: string;
  assetId?: string;
  assetVersion?: string;
  assetWidth?: number;
  assetHeight?: number;
  size?: number;
  opacity?: number;
  /** Runtime-only, never persisted. */
  labelOpacity?: number;
  reveal?: { kind: "brush"; duration: number; strokes?: number };
  scaleWithMap?: boolean;
  sizeZoom?: number;
};

export type MapsCgOverride = {
  camera: MapsCamera;
  style: MapsStyleId;
  highlights: string[];
  highlightColours?: Record<string, string>;
  churches: MapsChurch[];
  hiddenLayers?: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  stillPng?: string;
  movieMov?: string;
  movieDuration?: number;
  revealMovie?: boolean;
};

export type MapsSlide = {
  id: string;
  title: string;
  style: MapsStyleId;
  camera: MapsCamera;
  highlights: string[];
  highlightColours?: Record<string, string>;
  churches: MapsChurch[];
  hiddenLayers?: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  stillPng?: string;
  movieMov?: string;
  movieDuration?: number;
  revealMovie?: boolean;
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

/** Export render surface for a movie hop: the wider of the two endpoints' own capture surfaces
 * (mirrors the export's captureFlyFrames call — a mixed-surface hop renders, both in export and
 * in preview, at the denser of the two). Used by both the export call sites and MapView's preview
 * so they cannot drift. */
export function hopSurfaceWidth(from: MapsSlide, to: MapsSlide, audience: MapsAudience): number {
  return Math.max(authoredSurfaceWidth(from, audience), authoredSurfaceWidth(to, audience));
}

export type PlateSurfaceHint = {
  slideIds: string[];
  plateW?: number;
  /** Plate capture bearing (first camera of the morph run / `captureCamera`). */
  captureBearing?: number;
  camera?: { bearing?: number };
};

/** MapLibre render surface for a movie hop. Output size stays `hopSurfaceWidth`; this is the
 * style/tile zoom surface. When either end sits on a morph plate, use that plate's surface so
 * the Magic Move landing and movie frame 0 share one zoom offset. */
export function movieEndpointSurface(
  slide: MapsSlide,
  audience: MapsAudience,
  plates: PlateSurfaceHint[] = [],
  slidesById: Map<string, { includeSidePanels?: boolean }> = new Map()
): number {
  const own = authoredSurfaceWidth(slide, audience);
  if (audience === "cg") return own;
  for (const plate of plates) {
    if (!plate.slideIds.includes(slide.id)) continue;
    return Math.max(own, plateSurfaceWidth(plate.slideIds, slidesById, plate.plateW));
  }
  return own;
}

/** Style/tile surface for movie frame 0: the *source* plate's surface, else the source slide.
 * Does not take `Math.max` with the hop/dest — a 3840 plate followed by a 7680 movie must
 * still take off at 3840, or frame 0 shows the side panels the plate never had. */
export function movieRenderSurface(
  from: MapsSlide,
  _to: MapsSlide,
  audience: MapsAudience,
  plates: PlateSurfaceHint[] = [],
  slidesById: Map<string, { includeSidePanels?: boolean }> = new Map()
): number {
  return movieEndpointSurface(from, audience, plates, slidesById);
}

/** Consecutive morph hops share one plate (pairwise union would dissolve on a chain). */
export function morphRuns(slides: { id: string }[], links: { from: string; to: string; kind?: string }[]): string[][] {
  const byPair = new Map<string, { kind?: string }>();
  for (const link of links) byPair.set(`${link.from}\0${link.to}`, link);
  const ids = slides.map((slide) => slide.id);
  const runs: string[][] = [];
  let current: string[] = [];
  for (let i = 0; i < ids.length - 1; i++) {
    const start = ids[i];
    const end = ids[i + 1];
    const link = byPair.get(`${start}\0${end}`);
    if (link && link.kind === "morph") {
      if (!current.length) current = [start, end];
      else current.push(end);
    } else if (current.length) {
      runs.push(current);
      current = [];
    }
  }
  if (current.length) runs.push(current);
  return runs;
}

/** Plate hints from the document's morph runs — same grouping export uses for `movieRenderSurface`. */
export function morphPlateHints(slides: MapsSlide[], links: MapsLink[], audience: MapsAudience = "lw"): PlateSurfaceHint[] {
  return morphRuns(slides, links).map((slideIds) => {
    const first = slides.find((slide) => slide.id === slideIds[0]);
    const view = first ? slideForAudience(first, audience) : undefined;
    return { slideIds, captureBearing: view?.camera.bearing ?? 0 };
  });
}

/** Half away from zero. Shared with Python `round_half_away` — `Math.round` / `round()`
 * disagree at `.5` (10.5 → 11 vs 10, −11.5 → −11 vs −12). */
export function roundHalfAway(value: number): number {
  return value >= 0 ? Math.floor(value + 0.5) : Math.ceil(value - 0.5);
}

export function quantizedRotation(degrees: number): number {
  const snapped = roundHalfAway(Number(degrees) || 0);
  return snapped ? snapped : 0;
}

/** Bearing Keynote shows after integer plate rotation, kept on the authored wrap. */
export function effectivePlateBearing(plateBearing: number, cameraBearing: number): number {
  const delta = bearingDeltaSigned(plateBearing, cameraBearing);
  const next = cameraBearing + quantizedRotation(delta) - delta;
  const nearest = roundHalfAway(next);
  return Math.abs(next - nearest) < 1e-6 ? nearest : next;
}

export function plateCaptureBearing(
  plate: PlateSurfaceHint,
  slidesById?: Map<string, { camera?: { bearing?: number } }>
): number | undefined {
  if (typeof plate.captureBearing === "number") return plate.captureBearing;
  if (typeof plate.camera?.bearing === "number") return plate.camera.bearing;
  const first = plate.slideIds[0];
  const slide = first ? slidesById?.get(first) : undefined;
  if (typeof slide?.camera?.bearing === "number") return slide.camera.bearing;
  return undefined;
}

/** Snap a movie endpoint to the plate Keynote will show when that end sits on a morph plate. */
export function movieEndpointCamera(camera: MapsCamera, plateBearing?: number | null): MapsCamera {
  if (plateBearing == null || !Number.isFinite(plateBearing)) return camera;
  const bearing = effectivePlateBearing(plateBearing, camera.bearing);
  return bearing === camera.bearing ? camera : { ...camera, bearing };
}

export function movieHopCameras(
  from: MapsSlide,
  to: MapsSlide,
  plates: PlateSurfaceHint[],
  slidesById?: Map<string, { camera?: { bearing?: number } }>
): { from: MapsCamera; to: MapsCamera } {
  const fromPlate = plates.find((plate) => plate.slideIds.includes(from.id));
  const toPlate = plates.find((plate) => plate.slideIds.includes(to.id));
  return {
    from: movieEndpointCamera(from.camera, fromPlate ? plateCaptureBearing(fromPlate, slidesById) : undefined),
    to: movieEndpointCamera(to.camera, toPlate ? plateCaptureBearing(toPlate, slidesById) : undefined),
  };
}

/** Flight width, endpoint viewports, and plate-snapped cameras for one movie hop.
 * `width` is the Keynote/output size (max of the ends). Frame 0 uses `fromWidth` /
 * `fromSurface`; the hop then transitions to `toWidth`. */
export function movieHopView(
  from: MapsSlide,
  to: MapsSlide,
  audience: MapsAudience,
  plates: PlateSurfaceHint[],
  slidesById: Map<string, MapsSlide> = new Map()
): {
  width: number;
  fromWidth: number;
  toWidth: number;
  fromSurface: number;
  toSurface: number;
  surfaceWidth: number;
  prefetchSurface: number;
  from: MapsCamera;
  to: MapsCamera;
} {
  const ends = movieHopCameras(from, to, plates, slidesById);
  const fromWidth = authoredSurfaceWidth(from, audience);
  const toWidth = authoredSurfaceWidth(to, audience);
  const fromSurface = movieEndpointSurface(from, audience, plates, slidesById);
  const toSurface = movieEndpointSurface(to, audience, plates, slidesById);
  const width = hopSurfaceWidth(from, to, audience);
  return {
    width,
    fromWidth,
    toWidth,
    fromSurface,
    toSurface,
    surfaceWidth: fromSurface,
    prefetchSurface: Math.max(width, fromSurface, toSurface),
    from: ends.from,
    to: ends.to,
  };
}

export type MapsFlight = "arc" | "phases";

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
  flight?: MapsFlight;
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
  attribution: MapsAttribution;
  assets: MapsAsset[];
  slides: MapsSlide[];
  links: MapsLink[];
  retiredLinks?: MapsLink[];
};

export type MapsAttribution = "stamp" | "credits";

export const MAX_RETIRED_LINKS = 200;

export const LAYER_FILTERS: { id: MapsLayerFilterId; label: string }[] = [
  { id: "roads", label: "Roads" },
  { id: "roadnames", label: "Road names" },
  { id: "shields", label: "Road signs" },
  { id: "arrows", label: "One-way arrows" },
  { id: "pois", label: "POIs (bus stops…)" },
  { id: "rail", label: "Rail" },
  { id: "buildings", label: "Buildings" },
  { id: "labels", label: "Place labels" },
  { id: "waternames", label: "Water names" },
  { id: "boundaries", label: "Boundaries" },
];

const LAYER_FILTER_IDS = new Set(LAYER_FILTERS.map((item) => item.id));

export const DEFAULT_HIDDEN_LAYERS: MapsLayerFilterId[] = ["roadnames", "arrows", "labels", "waternames", "boundaries"];

export function parseHiddenLayers(raw: unknown): MapsLayerFilterId[] {
  if (raw == null) return [...DEFAULT_HIDDEN_LAYERS];
  if (!Array.isArray(raw)) return [...DEFAULT_HIDDEN_LAYERS];
  return raw.filter((item): item is MapsLayerFilterId => typeof item === "string" && LAYER_FILTER_IDS.has(item as MapsLayerFilterId));
}

export function slideHiddenLayers(source: { hiddenLayers?: unknown } | null | undefined): MapsLayerFilterId[] {
  return parseHiddenLayers(source?.hiddenLayers);
}

/** 3D extrusions / Borderlands ink only exist while the Buildings layer is visible. */
export function buildingsLayerOn(source: { hiddenLayers?: unknown } | null | undefined): boolean {
  return !slideHiddenLayers(source).includes("buildings");
}

export const HOP_LABELS: Record<MapsHopKind, string> = {
  morph: "Magic Move",
  movie: "Movie",
  dissolve: "Dissolve",
  cut: "Cut",
};

export const HOP_TIPS: Record<MapsHopKind, string> = {
  morph: "Keynote Magic Move on one shared map plate — pan, zoom, and rotate. Overflow is fine up to 16384pt; a bigger zoom hop becomes a Movie.",
  movie: "Keynote movie. Used for pitch, 3D buildings, or a zoom too large for one Magic Move image.",
  dissolve: "Keynote Dissolve. Crossfade stills over the hop duration.",
  cut: "Instant cut. Used when the map style or region highlights change.",
};

/** Reference CSS width for export rendering: every surface renders as if it were an
 * EXPORT_REF_WIDTH-px-wide screen, at pixelRatio = its own scale, so tiles/relief/text are
 * fetched at the same density everywhere and output px still equals authored px. */
export const EXPORT_REF_WIDTH = 1920;

export function exportScale(surfaceWidth: number): number {
  return 2 ** Math.max(0, Math.round(Math.log2(surfaceWidth / EXPORT_REF_WIDTH)));
}

export function exportZoomDelta(surfaceWidth: number): number {
  return -Math.log2(exportScale(surfaceWidth)) || 0;
}

/** MapLibre's cameraToCenterDistance = 0.5*canvasHeight/tan(fov/2). Widening the render canvas
 * past the band (full-frame preview host) needs a matching fov widening so the band region
 * projects exactly as the export while the margins around it show live map for nav context. */
export const BASE_FOV_DEG = 36.87;

export function compensatedFov(canvasHeight: number, bandHeight: number, baseFovDeg = BASE_FOV_DEG): number {
  if (!bandHeight) return baseFovDeg;
  const baseFovRad = (baseFovDeg * Math.PI) / 180;
  const fovRad = 2 * Math.atan((Math.tan(baseFovRad / 2) * canvasHeight) / bandHeight);
  return (fovRad * 180) / Math.PI;
}

/** Cap on how much taller than the band the preview host is allowed to grow, so an
 * extreme window aspect doesn't widen the fov to a degenerate angle. */
export const PREVIEW_NAV_MAX = 3;

export type PreviewLayout = {
  innerW: number;
  innerH: number;
  bandW: number;
  bandH: number;
  bandTop: number;
  bandInnerH: number;
  k: number;
  fov: number;
};

/** Sizes and positions the pinned preview surface for one frame: `inner` fills the whole frame
 * (not just the band) at the same CSS-px-per-authored-px density, so the margins above/below the
 * band render live map instead of a dimmed void. `scale` is `exportScale(authoredWidth)`; the
 * band itself always mirrors the CSS `min(100cqw, 100cqh*W/1080)` sizing. */
export function previewLayout(frameW: number, frameH: number, surfaceWidth: number, scale: number): PreviewLayout {
  if (frameW <= 0 || frameH <= 0 || surfaceWidth <= 0 || scale <= 0) {
    return { innerW: 0, innerH: 0, bandW: 0, bandH: 0, bandTop: 0, bandInnerH: 0, k: 1, fov: BASE_FOV_DEG };
  }
  const s = 1 / scale;
  const innerW = surfaceWidth * s;
  const bandInnerH = 1080 * s;
  const bandW = Math.min(frameW, (frameH * surfaceWidth) / 1080);
  const bandH = (bandW * 1080) / surfaceWidth;
  const k = innerW > 0 ? bandW / innerW : 1;
  const innerH = k > 0 ? Math.min(Math.max(frameH / k, bandInnerH), bandInnerH * PREVIEW_NAV_MAX) : bandInnerH;
  const bandTop = (innerH - bandInnerH) / 2;
  const fov = compensatedFov(innerH, bandInnerH);
  return { innerW, innerH, bandW, bandH, bandTop, bandInnerH, k, fov };
}

/** Maps a band-local object box (authored px) to inner-local CSS px, the same way the inner
 * transform (`translateY(-bandTop*k) scale(k)`) maps the band row into view. */
export function objectBoxStyle(
  box: { x: number; y: number; w: number; h: number },
  k: number,
  bandTop: number
): { left: number; top: number; width: number; height: number } {
  return { left: box.x * k, top: (box.y - bandTop) * k, width: box.w * k, height: box.h * k };
}

export type ExportSurface = {
  cssWidth: number;
  cssHeight: number;
  pixelRatio: number;
  canvasWidth: number;
  canvasHeight: number;
  cropX: number;
  cropY: number;
};

/** `surfaceWidth` defaults to `width` (stills, movies, CG); morph plates pass the slide's
 * surface width explicitly since the plate itself can be larger than one authored surface. */
export function exportSurface(width: number, height: number, surfaceWidth = width): ExportSurface {
  const scale = exportScale(surfaceWidth);
  const cssWidth = Math.ceil(width / scale);
  const cssHeight = Math.ceil(height / scale);
  const canvasWidth = cssWidth * scale;
  const canvasHeight = cssHeight * scale;
  return {
    cssWidth,
    cssHeight,
    pixelRatio: scale,
    canvasWidth,
    canvasHeight,
    cropX: Math.floor((canvasWidth - width) / 2),
    cropY: Math.floor((canvasHeight - height) / 2),
  };
}

export function exportCamera(camera: MapsCamera, surfaceWidth: number): MapsCamera {
  return { ...camera, zoom: camera.zoom + exportZoomDelta(surfaceWidth) };
}

export const MORPH_MAX_PITCH = 0.5;
export const MORPH_MAX_DBEARING = 0.05;
export const MORPH_MAX_PLATE_PX = 8192;
/** Keynote object size, not the capture raster. A z+4 hop on the 3840 centre is ~61k pt
 * and Magic Move hitching / wrong placement is Keynote giving up on that object. 16384 is
 * 2× the old unfitted-8192 gate: about two zoom stops of overflow, then Movie. */
export const MORPH_MAX_DISPLAY_PX = 16384;
const TILE_SIZE = 512;
export const WALL_W = 7680;
export const WALL_H = 1080;
export const CENTRE_W = 3840;
export const CENTRE_ORIGIN_X = 1920;
export const CG_W = 1920;
export const FW_W = 1920;

export function captureWidth(slide: { includeSidePanels?: boolean }): number {
  return slide.includeSidePanels ? WALL_W : CENTRE_W;
}

/** Displayed band width in authored px: the CG split shows only the CG crop; a full-wall slide
 * (authoredWidth === WALL_W) always shows the full wall; a centre-only slide (authoredWidth ===
 * CENTRE_W) shows just the centre unless "Show side panels" widens the visible band to the full
 * wall for context — density (authoredWidth) is unchanged either way. */
export function surfaceWidthOf(authoredWidth: number, sidePanels: boolean): number {
  if (authoredWidth <= CG_W) return CG_W;
  if (authoredWidth === WALL_W) return WALL_W;
  if (authoredWidth === CENTRE_W) return sidePanels ? WALL_W : CENTRE_W;
  return authoredWidth;
}

/** Widest capture surface among a plate's constituent slides — this picks the render scale
 * (exportScale/exportSurface) for the plate, since one plate's slides can mix FW and centre-only.
 * When no slideIds resolve, falls back to a guess from the plate's own pixel width rather than
 * silently assuming centre-only. */
export function plateSurfaceWidth(
  slideIds: string[],
  slidesById: Map<string, { includeSidePanels?: boolean }>,
  plateW?: number
): number {
  const resolved = slideIds.map((sid) => slidesById.get(sid)).filter((s): s is { includeSidePanels?: boolean } => Boolean(s));
  if (!resolved.length) return plateW !== undefined && plateW > CENTRE_W ? WALL_W : CENTRE_W;
  return resolved.reduce((max, slide) => Math.max(max, captureWidth(slide)), CENTRE_W);
}

export function showCgBand(slide: { cg?: unknown }): boolean {
  return !slide.cg;
}

/** Strictest hop across LW and a CG split — same rule `coerceHopKinds` uses. */
export function suggestedHopKindForLink(from: MapsSlide, to: MapsSlide): MapsHopKind {
  let suggested = suggestedHopKind(from, to);
  if (from.cg || to.cg) {
    const cgSuggested = suggestedHopKind(slideForAudience(from, "cg"), slideForAudience(to, "cg"));
    const rank = (kind: MapsHopKind) => (kind === "cut" ? 2 : kind === "movie" ? 1 : 0);
    if (rank(cgSuggested) > rank(suggested)) suggested = cgSuggested;
  }
  return suggested;
}

export function coerceHopKinds(doc: MapsDocument, prev: MapsDocument | null = null): MapsDocument {
  const byId = new Map(doc.slides.map((slide) => [slide.id, slide]));
  const prevById = prev ? new Map(prev.slides.map((slide) => [slide.id, slide])) : null;
  return {
    ...doc,
    links: doc.links.map((link) => {
      const from = byId.get(link.from);
      const to = byId.get(link.to);
      if (!from || !to) return link;
      const suggested = suggestedHopKindForLink(from, to);
      let next: MapsLink = link;
      if (link.kind === "morph" && suggested !== "morph") {
        next = { ...link, kind: suggested };
        if (suggested === "movie") next.objectTransition = "fade";
        delete next.plateId;
      } else if (link.kind === "movie" && suggested === "morph" && prevById) {
        const oldFrom = prevById.get(link.from);
        const oldTo = prevById.get(link.to);
        const oldSuggested = oldFrom && oldTo ? suggestedHopKindForLink(oldFrom, oldTo) : "morph";
        if (oldSuggested !== "morph") {
          next = { ...link, kind: "morph" };
          delete next.plateId;
        }
      }
      if (next.kind !== "movie") {
        delete next.easing;
        delete next.route;
        delete next.easeIn;
        delete next.easeOut;
        delete next.flyZoom;
        delete next.curve;
        delete next.flight;
        delete next.objectTransition;
      }
      return next;
    }),
  };
}

export type MapsAppearanceField = "style" | "highlights" | "highlightColours" | "hiddenLayers" | "hillshade" | "isolate";

export function appearanceMismatch(from: MapsSlide, to: MapsSlide): MapsAppearanceField[] {
  const out: MapsAppearanceField[] = [];
  if (coerceMapsStyleId(from.style) !== coerceMapsStyleId(to.style)) out.push("style");
  const hi = (s: MapsSlide) => [...s.highlights].map((h) => h.toUpperCase()).sort().join(",");
  if (hi(from) !== hi(to)) out.push("highlights");
  if (highlightColoursKey(from.highlightColours) !== highlightColoursKey(to.highlightColours)) out.push("highlightColours");
  const layers = (s: MapsSlide) => slideHiddenLayers(s).sort().join(",");
  if (layers(from) !== layers(to)) out.push("hiddenLayers");
  if ((from.hillshade === true) !== (to.hillshade === true)) out.push("hillshade");
  const iso = (s: MapsSlide) => (s.isolate ? `${s.isolate.mode}:${s.isolate.strength.toFixed(2)}` : "off");
  if (iso(from) !== iso(to)) out.push("isolate");
  return out;
}

/** Isolate/highlight mismatches on a Movie hop are expected (landing slide or darkened fly + cut) — never style/layers.
 *  Colour overrides ride with the highlight set: hard only when the IDs themselves match. */
export function softMovieFields(from: MapsSlide, to: MapsSlide): Set<MapsAppearanceField> {
  const fields = new Set<MapsAppearanceField>(["highlights", "isolate"]);
  const hi = (s: MapsSlide) => [...s.highlights].map((h) => h.toUpperCase()).sort().join(",");
  if (hi(from) !== hi(to)) fields.add("highlightColours");
  return fields;
}

/** Movie dest isolate+highlights after a non-isolated source: land on a plain still, then dissolve in. */
export function isolateDissolveNeeded(from: MapsSlide, to: MapsSlide): boolean {
  return !!(to.isolate && to.highlights.length && !from.isolate);
}

export function plainIsolateTarget(slide: MapsSlide): MapsSlide {
  return { ...slide, highlights: [], isolate: undefined, highlightColours: undefined };
}

export function movieAppearanceMismatch(from: MapsSlide, to: MapsSlide): boolean {
  const target: MapsSlide = isolateDissolveNeeded(from, to) ? plainIsolateTarget(to) : to;
  if (appearanceMismatch(from, target).length > 0) return true;
  if (!from.cg && !target.cg) return false;
  return appearanceMismatch(slideForAudience(from, "cg"), slideForAudience(target, "cg")).length > 0;
}

export function inferHopKind(from: MapsSlide, to: MapsSlide): MapsHopKind {
  if (appearanceMismatch(from, to).length) return "cut";
  const pitch = Math.max(Math.abs(from.camera.pitch), Math.abs(to.camera.pitch));
  const extruded = isExtrudedStyle(from.style) || isExtrudedStyle(to.style);
  const buildingsOn = buildingsLayerOn(from) || buildingsLayerOn(to);
  // Zoom/bearing deltas are not Movie triggers: one shared plate may overflow
  // (zoom, either direction) and Keynote rotates that plate (bearing).
  if ((extruded && buildingsOn) || pitch > MORPH_MAX_PITCH) {
    return "movie";
  }
  return "morph";
}

export function bearingDeltaSigned(from: number, to: number): number {
  return ((to - from + 540) % 360) - 180;
}

export function bearingDelta(from: number, to: number): number {
  return Math.abs(bearingDeltaSigned(from, to));
}

export function plateFitsMorph(from: MapsSlide, to: MapsSlide): boolean {
  return morphPlatePx(from.camera, to.camera, captureWidth(from), captureWidth(to)) != null;
}

/** Authoring suggestion: hop rules, then a usable shared plate (degenerate union becomes Movie). */
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
        ...(kind === "movie" ? { flight: "arc" as const, objectTransition: "fade" as const } : {}),
      }
    );
  }
  return links;
}

function linkKey(from: string, to: string): string {
  return JSON.stringify([from, to]);
}

/** Like `restitchLinks`, but remembers links displaced by a reorder so a pair re-adjacent later regains its hop instead of falling back to `suggestedHopKind`. */
export function restitchWithMemory(
  nextSlides: MapsSlide[],
  prevLinks: MapsLink[],
  prevRetired: MapsLink[] | undefined
): { links: MapsLink[]; retired: MapsLink[] } {
  const pool = new Map<string, MapsLink>();
  for (const link of prevRetired || []) pool.set(linkKey(link.from, link.to), link);
  for (const link of prevLinks) {
    const key = linkKey(link.from, link.to);
    pool.delete(key);
    pool.set(key, link);
  }

  const links: MapsLink[] = [];
  for (let i = 0; i < nextSlides.length - 1; i++) {
    const from = nextSlides[i];
    const to = nextSlides[i + 1];
    const key = linkKey(from.id, to.id);
    const pooled = pool.get(key);
    if (pooled) {
      pool.delete(key);
      const fromPrevLinks = prevLinks.some((link) => link.from === from.id && link.to === to.id);
      links.push(fromPrevLinks ? pooled : { ...pooled, from: from.id, to: to.id });
    } else {
      const kind = suggestedHopKind(from, to);
      links.push({
        from: from.id,
        to: to.id,
        kind,
        duration: 1.0,
        playWithoutClick: false,
        ...(kind === "movie" ? { flight: "arc" as const, objectTransition: "fade" as const } : {}),
      });
    }
  }

  const slideIds = new Set(nextSlides.map((slide) => slide.id));
  const retiredByKey = new Map<string, MapsLink>();
  for (const link of pool.values()) {
    if (!slideIds.has(link.from) || !slideIds.has(link.to)) continue;
    retiredByKey.set(linkKey(link.from, link.to), link);
  }
  let retired = [...retiredByKey.values()];
  if (retired.length > MAX_RETIRED_LINKS) retired = retired.slice(retired.length - MAX_RETIRED_LINKS);
  return { links, retired };
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

function outgoingPairs(slides: MapsSlide[]): Map<string, string> {
  const pairs = new Map<string, string>();
  for (let i = 0; i < slides.length - 1; i++) pairs.set(slides[i].id, slides[i + 1].id);
  return pairs;
}

/** Move the slide at `id` to `toIndex`, restitch links, and drop stale movie renders on every outgoing hop that changed. Returns `doc` unchanged if the move is a no-op or `id` is unknown. */
export function moveSlideTo(doc: MapsDocument, id: string, toIndex: number): MapsDocument {
  const fromIndex = doc.slides.findIndex((s) => s.id === id);
  if (fromIndex < 0) return doc;
  const target = Math.max(0, Math.min(doc.slides.length - 1, toIndex));
  if (target === fromIndex) return doc;
  const prevPairs = outgoingPairs(doc.slides);
  const slides = [...doc.slides];
  const [moved] = slides.splice(fromIndex, 1);
  slides.splice(target, 0, moved);
  const nextPairs = outgoingPairs(slides);
  const clearIds = new Set<string>();
  for (const from of new Set([...prevPairs.keys(), ...nextPairs.keys()])) {
    if (prevPairs.get(from) !== nextPairs.get(from)) clearIds.add(from);
  }
  const nextSlides = slides.map((slide) => (clearIds.has(slide.id) ? clearMovieFields(slide) : slide));
  const { links, retired } = restitchWithMemory(nextSlides, doc.links, doc.retiredLinks);
  const next: MapsDocument = { ...doc, slides: nextSlides, links };
  if (retired.length) next.retiredLinks = retired;
  else delete next.retiredLinks;
  return next;
}

/** Swap the slide at `id` with its neighbour `delta` away, restitch links, and drop stale movie renders on the affected outgoing hops. Returns `doc` unchanged if the move is out of range. */
export function reorderSlides(doc: MapsDocument, id: string, delta: number): MapsDocument {
  const index = doc.slides.findIndex((s) => s.id === id);
  if (index < 0) return doc;
  const target = index + delta;
  if (target < 0 || target >= doc.slides.length) return doc;
  return moveSlideTo(doc, id, target);
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

/** Axis-aligned box of a camera viewport in the plate's bearing frame. */
function viewportAabb(
  camera: MapsCamera,
  width: number,
  height: number,
  plateBearing: number,
): { x0: number; y0: number; x1: number; y1: number } {
  const axis = wallViewport(camera, width, height, plateBearing);
  const delta = bearingDeltaSigned(plateBearing, camera.bearing);
  if (Math.abs(delta) < 1e-6) return axis;
  const cx = (axis.x0 + axis.x1) / 2;
  const cy = (axis.y0 + axis.y1) / 2;
  const hw = (axis.x1 - axis.x0) / 2;
  const hh = (axis.y1 - axis.y0) / 2;
  const theta = (delta * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [dx, dy] of [
    [-hw, -hh],
    [hw, -hh],
    [hw, hh],
    [-hw, hh],
  ] as const) {
    const rx = cos * dx + sin * dy;
    const ry = -sin * dx + cos * dy;
    x0 = Math.min(x0, cx + rx);
    y0 = Math.min(y0, cy + ry);
    x1 = Math.max(x1, cx + rx);
    y1 = Math.max(y1, cy + ry);
  }
  return { x0, y0, x1, y1 };
}

/** Mercator AABB of the LW circumcircle — same pad as Keynote `_camera_cover_box`. */
function cameraCoverBox(
  camera: MapsCamera,
  width: number,
  height: number,
  plateBearing: number,
): { x0: number; y0: number; x1: number; y1: number } {
  const axis = wallViewport(camera, width, height, plateBearing);
  const cx = (axis.x0 + axis.x1) / 2;
  const cy = (axis.y0 + axis.y1) / 2;
  const world = TILE_SIZE * 2 ** camera.zoom;
  const radius = world ? Math.hypot(width / 2, height / 2) / world : 0;
  return { x0: cx - radius, y0: cy - radius, x1: cx + radius, y1: cy + radius };
}

/** Union plate at the deeper zoom, same math as Keynote `morph_plate_geom` before the 8192 fit.
 * This is the size Keynote actually places (overflow), not the capture PNG. */
export function morphPlateNativePx(
  from: MapsCamera,
  to: MapsCamera,
  fromW = WALL_W,
  toW = WALL_W,
): { w: number; h: number } | null {
  const sharedBearing = from.bearing;
  const boxes = [
    viewportAabb(from, fromW, WALL_H, sharedBearing),
    viewportAabb(to, toW, WALL_H, sharedBearing),
  ];
  // Same gate as Keynote `morph_plate_geom`: only a bearing hop pays for the
  // circumcircle. Zoom/pan must keep the camera AABB or the fitted 8192 raster
  // is mostly padding and export no longer matches the live preview.
  if (Math.abs(bearingDeltaSigned(from.bearing, to.bearing)) >= 0.5) {
    boxes.push(cameraCoverBox(from, fromW, WALL_H, sharedBearing), cameraCoverBox(to, toW, WALL_H, sharedBearing));
  }
  const world = TILE_SIZE * 2 ** Math.max(from.zoom, to.zoom);
  const w = (Math.max(...boxes.map((b) => b.x1)) - Math.min(...boxes.map((b) => b.x0))) * world;
  const h = (Math.max(...boxes.map((b) => b.y1)) - Math.min(...boxes.map((b) => b.y0))) * world;
  if (w <= 1 || h <= 1) return null;
  return { w, h };
}

/** Capture size after the 8192 fit. Null when the union is degenerate or the Keynote
 * object would exceed `MORPH_MAX_DISPLAY_PX` (Export then uses Movie). */
export function morphPlatePx(
  from: MapsCamera,
  to: MapsCamera,
  fromW = WALL_W,
  toW = WALL_W,
): { w: number; h: number } | null {
  const native = morphPlateNativePx(from, to, fromW, toW);
  if (!native) return null;
  if (Math.max(native.w, native.h) > MORPH_MAX_DISPLAY_PX) return null;
  let { w, h } = native;
  const longest = Math.max(w, h);
  if (longest > MORPH_MAX_PLATE_PX) {
    const scale = MORPH_MAX_PLATE_PX / longest;
    w *= scale;
    h *= scale;
  }
  return { w, h };
}

/** 1920 CG window slides inside the 3840 centre wall (1920–5760). */
export const CG_SHIFT_MAX = 960;

export function snapCgShift(x: number, threshold = 24): number {
  return Math.abs(x) <= threshold ? 0 : x;
}

/** Mirrors maps_keynote's `_outgoing(...).kind === "movie"`: the *first* outgoing link's kind, not any outgoing link. */
export function hasOutgoingMovie(links: MapsLink[], slideId: string): boolean {
  return links.find((link) => link.from === slideId)?.kind === "movie";
}

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
  return `World copies tile in ${tiled.join(" / ")}. Pins and highlighted countries will repeat.`;
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

/** MapLibre map-zoom bounds for the render map (preview and, via exportZoomDelta, export):
 * authored zoom 0 at the deepest export scale (exportZoomDelta(WALL_W) === -2) must stay
 * unclamped, so the floor sits at -2, not 0. */
export const ML_MIN_ZOOM = -2;
export const ML_MAX_ZOOM = 22;

export function clampMapZoom(zoom: number): number {
  return Math.max(ML_MIN_ZOOM, Math.min(ML_MAX_ZOOM, zoom));
}

/** Converts a raw CG-crop pointer-drag delta (client px) into an authored-px shift: the drag
 * spans `bandWidth` client px across `surfaceWidth` authored px — the DISPLAYED surface width,
 * not the density-driving authoredWidth (those differ when "Show side panels" widens the band
 * without changing capture density). */
export function cgDragDx(clientDx: number, surfaceWidth: number, bandWidth: number): number {
  return bandWidth > 0 ? (clientDx * surfaceWidth) / bandWidth : 0;
}

export function nextSlideId(slides: MapsSlide[]): string {
  let n = 1;
  const used = new Set(slides.map((s) => s.id));
  while (used.has(`s${n}`)) n += 1;
  return `s${n}`;
}

function cloneChurches(churches: MapsChurch[]): MapsChurch[] {
  return churches.map((church) => ({
    ...church,
    reveal: church.reveal ? { ...church.reveal } : church.reveal,
  }));
}

/** New slide after the current one. Add leaves objects empty; Duplicate copies them. */
export function cloneSlide(slide: MapsSlide, id: string, opts?: { objects?: boolean }): MapsSlide {
  const objects = opts?.objects === true;
  return {
    ...slide,
    id,
    churches: objects ? cloneChurches(slide.churches) : [],
    stillPng: undefined,
    cg: slide.cg
      ? {
          ...slide.cg,
          camera: { ...slide.cg.camera },
          highlights: [...slide.cg.highlights],
          churches: objects ? cloneChurches(slide.cg.churches) : [],
          stillPng: undefined,
          movieMov: undefined,
        }
      : undefined,
    cgShiftX: slide.cgShiftX,
    cgShiftY: 0,
    includeSidePanels: slide.includeSidePanels === true,
  };
}

export function nextPinId(churches: MapsChurch[]): string {
  let n = 1;
  const used = new Set(churches.map((c) => c.id));
  while (used.has(`p${n}`)) n += 1;
  return `p${n}`;
}

export function shouldFocusAddedLandmark(
  target: { slideId: string; audience: MapsAudience },
  active: { slideId: string | null; audience: MapsAudience }
): boolean {
  return active.slideId === target.slideId && active.audience === target.audience;
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
  const strength = Number.isFinite(strengthRaw)
    ? Math.max(0, Math.min(1, strengthRaw))
    : DEFAULT_ISOLATE_STRENGTH;
  return { mode: "darken", strength };
}

/** Gold_Wall_Input.key slide 8; Keynote `LABEL_PILL_RGB` and the preview bake. */
export const DEFAULT_LABEL_PILL_COLOR = "#ee220c";

export function churchLabelColor(church: { labelColor?: string } | undefined): string {
  const raw = church?.labelColor;
  if (isHighlightHex(raw)) return normaliseHighlightColour(raw);
  return DEFAULT_LABEL_PILL_COLOR;
}

/** `showLabel` defaulted to true before it was written explicitly, so a saved church with no
 * key predates the flip and keeps its label; every creation path writes the key. */
function churchesFromResult(churches: MapsChurch[] | undefined): MapsChurch[] {
  return (churches || []).map((church) => ("showLabel" in church ? church : { ...church, showLabel: true }));
}

function cgFromResult(cg: MapsCgOverride | undefined): MapsCgOverride | undefined {
  if (!cg) return undefined;
  const { hiddenLayers, hillshade, isolate, ...rest } = cg;
  const iso = parseIsolate(isolate);
  return {
    ...rest,
    style: coerceMapsStyleId(cg.style),
    highlights: cg.highlights || [],
    highlightColours: parseHighlightColours(cg.highlightColours),
    churches: churchesFromResult(cg.churches),
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
    style: coerceMapsStyleId(slide.style),
    cgShiftX: slide.cgShiftX ?? 0,
    cgShiftY: slide.cgShiftY ?? 0,
    includeSidePanels: slide.includeSidePanels === true,
    highlights: slide.highlights || [],
    highlightColours: parseHighlightColours(slide.highlightColours),
    churches: churchesFromResult(slide.churches),
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
  function normaliseLink(link: MapsLink): MapsLink {
    const route = parseRoute(link.route);
    const next: MapsLink = { ...link };
    if (route) next.route = route;
    else delete next.route;
    if (typeof next.easeIn !== "number" || !Number.isFinite(next.easeIn)) delete next.easeIn;
    if (typeof next.easeOut !== "number" || !Number.isFinite(next.easeOut)) delete next.easeOut;
    if (typeof next.flyZoom !== "number" || !Number.isFinite(next.flyZoom)) delete next.flyZoom;
    if (typeof next.curve !== "number" || !Number.isFinite(next.curve)) delete next.curve;
    if (next.flight !== "arc" && next.flight !== "phases") delete next.flight;
    if (next.objectTransition !== "fade" && next.objectTransition !== "hold") delete next.objectTransition;
    return next;
  }
  const links = ((result.links as MapsLink[]) || []).map(normaliseLink);
  const slideIds = new Set(slides.map((slide) => slide.id));
  const retiredLinks = ((result.retiredLinks as MapsLink[]) || [])
    .map(normaliseLink)
    .filter((link) => slideIds.has(link.from) && slideIds.has(link.to));
  const coerced = coerceHopKinds({
    defaultStyle: coerceMapsStyleId(result.defaultStyle),
    crop: (result.crop as MapsCropId) || "center+cg",
    exportLw: result.exportLw !== false,
    exportCg: result.exportCg !== false,
    exportDsk: result.exportDsk === true,
    hiddenLayers: deckHidden,
    cachedCountries: Array.isArray(result.cachedCountries)
      ? (result.cachedCountries as unknown[]).filter((item): item is string => typeof item === "string")
      : [],
    attribution: result.attribution === "stamp" ? "stamp" : "credits",
    assets: Array.isArray(result.assets)
      ? (result.assets as MapsAsset[]).filter((asset) => asset && typeof asset.id === "string" && typeof asset.version === "string")
      : [],
    slides,
    links,
  });
  if (retiredLinks.length) coerced.retiredLinks = retiredLinks;
  return coerced;
}
