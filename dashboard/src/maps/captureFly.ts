import { Map as MapLibreMap, MercatorCoordinate } from "maplibre-gl";
import { createExportMap, waitIdleForFrame } from "./captureExport";
import { stampOsmCropOnCanvas } from "./stampOsm";
import { churchesGeo, movieObjectsAt, withoutRevealed } from "./overlays";
import { arcPath, clampRho } from "./flight";
import {
  exportCamera,
  type MapsCamera,
  type MapsChurch,
  type MapsEasing,
  type MapsFlight,
  type MapsIsolate,
  type MapsLayerFilterId,
  type MapsRoutePoint,
  type MapsStyleId,
} from "./types";

const TILE = 512;

function easeLinear(t: number): number {
  return t;
}

function easeIn(t: number): number {
  return t * t;
}

function easeOut(t: number): number {
  return 1 - (1 - t) ** 2;
}

function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
}

const EASE_FNS: Record<MapsEasing, (t: number) => number> = {
  linear: easeLinear,
  "ease-in": easeIn,
  "ease-out": easeOut,
  "ease-in-out": easeInOut,
};

function shortestAngleLerp(from: number, to: number, t: number): number {
  let delta = ((to - from + 180) % 360 + 360) % 360 - 180;
  if (delta === -180) delta = 180;
  return from + delta * t;
}

function unwrapMercatorX(fromX: number, toX: number): number {
  let x = toX;
  const delta = x - fromX;
  if (delta > 0.5) x -= 1;
  else if (delta < -0.5) x += 1;
  return x;
}

function wrapUnit(x: number): number {
  return ((x % 1) + 1) % 1;
}

function mercatorOf(point: { lat: number; lon: number }): MercatorCoordinate {
  return MercatorCoordinate.fromLngLat({ lng: point.lon, lat: point.lat });
}

function segmentLength(from: MapsRoutePoint, to: MapsRoutePoint): number {
  const a = mercatorOf(from);
  const b = mercatorOf(to);
  const bx = unwrapMercatorX(a.x, b.x);
  return Math.hypot(bx - a.x, b.y - a.y);
}

const WALL_W = 7680;
const WALL_H = 1080;
const CRUISE_PAD = 0.35;

/** Zoom that fits the hop on the capture wall, or the start/end zoom if the hop is already on-screen. */
export function cruiseZoom(fromZ: number, toZ: number, distX: number, distY: number, width = WALL_W): number {
  let zFit = 22;
  if (distX > 1e-9) zFit = Math.min(zFit, Math.log2(width / TILE / distX));
  if (distY > 1e-9) zFit = Math.min(zFit, Math.log2(WALL_H / TILE / distY));
  return Math.max(0, Math.min(fromZ, toZ, zFit - CRUISE_PAD));
}

export function autoCruiseZoom(from: MapsCamera, to: MapsCamera, width = WALL_W): number {
  const a = mercatorOf(from);
  const b = mercatorOf(to);
  const bx = unwrapMercatorX(a.x, b.x);
  return cruiseZoom(from.zoom, to.zoom, Math.abs(bx - a.x), Math.abs(b.y - a.y), width);
}

export type HopInterp = {
  easing?: MapsEasing;
  routePoints?: MapsRoutePoint[];
  curve?: number;
  flyZoom?: number;
  easeIn?: number;
  easeOut?: number;
  duration?: number;
  width?: number;
  flight?: MapsFlight;
};

export type HopPhases = { zoomOut: number; move: number; zoomIn: number };

export function resolveHopPhases(interp: Pick<HopInterp, "duration" | "easeIn" | "easeOut">): HopPhases {
  const duration = Math.max(0.15, interp.duration ?? 1);
  let zoomOut = interp.easeIn != null && Number.isFinite(interp.easeIn) ? interp.easeIn : duration * 0.25;
  let zoomIn = interp.easeOut != null && Number.isFinite(interp.easeOut) ? interp.easeOut : duration * 0.25;
  zoomOut = Math.max(0, zoomOut);
  zoomIn = Math.max(0, zoomIn);
  if (zoomOut + zoomIn > duration) {
    const scale = duration / (zoomOut + zoomIn);
    zoomOut *= scale;
    zoomIn *= scale;
  }
  const move = Math.max(0, duration - zoomOut - zoomIn);
  return { zoomOut, move, zoomIn };
}

function hopFractions(interp: HopInterp): { inF: number; moveF: number; outF: number } {
  const phases = resolveHopPhases(interp);
  const duration = phases.zoomOut + phases.move + phases.zoomIn;
  return { inF: phases.zoomOut / duration, moveF: phases.move / duration, outF: phases.zoomIn / duration };
}

/** Zoom out, hold cruise, zoom in. `t` is linear 0–1 over the whole hop. */
export function flyZoomAt(t: number, z0: number, z1: number, zCruise: number, inF: number, outF: number): number {
  const outStart = 1 - outF;
  if (t <= inF) {
    const u = inF > 0 ? easeInOut(Math.max(0, Math.min(1, t / inF))) : 1;
    return z0 + (zCruise - z0) * u;
  }
  if (t >= outStart) {
    const u = outF > 0 ? easeInOut(Math.max(0, Math.min(1, (t - outStart) / outF))) : 1;
    return zCruise + (z1 - zCruise) * u;
  }
  return zCruise;
}

export function lerpCamera(from: MapsCamera, to: MapsCamera, t: number, interp: HopInterp = {}): MapsCamera {
  return cameraAtHop(from, to, t, interp);
}

export function easeAt(easing: MapsEasing, t: number): number {
  return (EASE_FNS[easing] || EASE_FNS["ease-in-out"])(t);
}

type MercatorPoint = { x: number; y: number };

function routeMercator(from: MapsCamera, to: MapsCamera, route?: MapsRoutePoint[]): MercatorPoint[] {
  const scale = TILE * 2 ** from.zoom;
  const points = [{ lat: from.lat, lon: from.lon }, ...(route || []), { lat: to.lat, lon: to.lon }];
  const out: MercatorPoint[] = [];
  for (const point of points) {
    const next = mercatorOf(point);
    const previous = out[out.length - 1];
    const rawX = previous ? unwrapMercatorX(previous.x / scale, next.x) : next.x;
    const x = rawX * scale;
    const y = next.y * scale;
    if (!previous || Math.hypot(x - previous.x, y - previous.y) > 1e-6) out.push({ x, y });
  }
  return out.length > 1 ? out : [{ x: mercatorOf(from).x * scale, y: mercatorOf(from).y * scale }, { x: mercatorOf(to).x * scale, y: mercatorOf(to).y * scale }];
}

function routePointAt(points: MercatorPoint[], distance: number): MercatorPoint {
  let left = Math.max(0, distance);
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (length <= 1e-12) continue;
    if (left <= length || i === points.length - 1) {
      const t = Math.max(0, Math.min(1, left / length));
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
    }
    left -= length;
  }
  return points[points.length - 1];
}

export function hopDistancePx(from: MapsCamera, to: MapsCamera, routePoints?: MapsRoutePoint[]): number {
  const points = routeMercator(from, to, routePoints);
  return points.slice(1).reduce((total, point, index) => total + Math.hypot(point.x - points[index].x, point.y - points[index].y), 0);
}

function smoothFlight(from: MapsCamera, to: MapsCamera, t: number, interp: HopInterp): MapsCamera {
  const progress = easeAt(interp.easing || "linear", t);
  const points = routeMercator(from, to, interp.routePoints);
  const distance = hopDistancePx(from, to, interp.routePoints);
  const width = Math.max(1, interp.width ?? WALL_W);
  const height = WALL_H;
  const w0 = Math.max(width, height);
  const w1 = Math.max(width, height) / 2 ** (to.zoom - from.zoom);
  const rho = clampRho(interp.curve);
  const { pan, scale } = arcPath(w0, w1, distance, rho).at(progress);
  const position = pan;
  const zoom = from.zoom - Math.log2(scale);
  const point = routePointAt(points, distance * position);
  const scalePx = TILE * 2 ** from.zoom;
  const merc = new MercatorCoordinate(wrapUnit(point.x / scalePx), point.y / scalePx, 0);
  const lngLat = merc.toLngLat();
  const minZoom = Math.min(from.zoom, to.zoom, zoom);
  const flatten = Math.max(0, Math.min(1, (Math.min(from.zoom, to.zoom) - minZoom) / 2));
  return {
    lat: lngLat.lat,
    lon: lngLat.lng,
    zoom: Math.max(0, Math.min(22, zoom)),
    bearing: shortestAngleLerp(from.bearing, to.bearing, progress),
    pitch: (from.pitch + (to.pitch - from.pitch) * progress) * (1 - flatten * 0.5),
  };
}

export function cameraAtHop(from: MapsCamera, to: MapsCamera, t: number, interp: HopInterp = {}): MapsCamera {
  const tClamped = Math.max(0, Math.min(1, t));
  if (tClamped === 0) return { ...from };
  if (tClamped === 1) return { ...to };
  if ((interp.flight ?? "arc") !== "phases") return smoothFlight(from, to, tClamped, interp);
  const { inF, moveF, outF } = hopFractions(interp);
  const moveEnd = 1 - outF;
  const moveSpan = Math.max(1e-9, moveEnd - inF);
  let tPos = 0;
  if (moveF <= 1e-9) tPos = easeAt(interp.easing || "ease-in-out", tClamped);
  else if (tClamped >= moveEnd) tPos = 1;
  else if (tClamped > inF) tPos = easeAt(interp.easing || "ease-in-out", (tClamped - inF) / moveSpan);
  const zCruiseRaw = interp.flyZoom;
  let zCruise =
    zCruiseRaw != null && Number.isFinite(zCruiseRaw)
      ? Math.max(0, Math.min(22, zCruiseRaw))
      : autoCruiseZoom(from, to, interp.width ?? WALL_W);
  if (inF <= 1e-9) zCruise = from.zoom;
  if (outF <= 1e-9) zCruise = to.zoom;
  const zoom =
    inF <= 1e-9 && outF <= 1e-9
      ? from.zoom + (to.zoom - from.zoom) * easeAt(interp.easing || "ease-in-out", tClamped)
      : flyZoomAt(tClamped, from.zoom, to.zoom, zCruise, inF, outF);
  const a = mercatorOf(from);
  const b = mercatorOf(to);
  const bx = unwrapMercatorX(a.x, b.x);
  const merc = new MercatorCoordinate(wrapUnit(a.x + (bx - a.x) * tPos), a.y + (b.y - a.y) * tPos, 0);
  const lngLat = merc.toLngLat();
  const zTop = Math.min(from.zoom, to.zoom);
  const flatten =
    zTop - zCruise > 0.2 ? Math.max(0, Math.min(1, (zTop - zoom) / (zTop - zCruise))) : 0;
  const pitchLine = from.pitch + (to.pitch - from.pitch) * tPos;
  const cam: MapsCamera = {
    lat: lngLat.lat,
    lon: lngLat.lng,
    zoom,
    bearing: shortestAngleLerp(from.bearing, to.bearing, tPos),
    pitch: pitchLine * (1 - 0.85 * flatten),
  };
  const route = interp.routePoints;
  if (route && route.length >= 2) {
    return cameraAlongRoute(
      cam,
      [{ lat: from.lat, lon: from.lon }, ...route, { lat: to.lat, lon: to.lon }],
      tPos
    );
  }
  return cam;
}

export function cameraAlongRoute(base: MapsCamera, points: MapsRoutePoint[], t: number): MapsCamera {
  if (points.length < 2) return base;
  const lengths = points.slice(0, -1).map((point, i) => segmentLength(point, points[i + 1]));
  const total = lengths.reduce((sum, len) => sum + len, 0);
  if (total <= 0) return base;
  let remain = total * t;
  for (let i = 0; i < lengths.length; i++) {
    const len = lengths[i];
    const last = i === lengths.length - 1;
    if (remain > len && !last) {
      remain -= len;
      continue;
    }
    const u = len > 0 ? Math.min(1, remain / len) : 0;
    const a = mercatorOf(points[i]);
    const b = mercatorOf(points[i + 1]);
    const bx = unwrapMercatorX(a.x, b.x);
    const merc = new MercatorCoordinate(wrapUnit(a.x + (bx - a.x) * u), a.y + (b.y - a.y) * u, 0);
    const lngLat = merc.toLngLat();
    return { ...base, lat: lngLat.lat, lon: lngLat.lng };
  }
  return base;
}

const FRAME_TILE_WAIT_MS = 45000;

function jumpToCamera(map: MapLibreMap, cam: MapsCamera, surfaceWidth: number): void {
  const render = exportCamera(cam, surfaceWidth);
  map.jumpTo({ center: [render.lon, render.lat], zoom: render.zoom, bearing: render.bearing, pitch: render.pitch });
}

function unloadedTileCount(map: MapLibreMap): number | undefined {
  try {
    const style = map.style as unknown as {
      sourceCaches?: Record<string, { _tiles?: Record<string, { state?: string }> }>;
      _sourceCaches?: Record<string, { _tiles?: Record<string, { state?: string }> }>;
    };
    const caches = style.sourceCaches || style._sourceCaches;
    if (!caches) return undefined;
    let n = 0;
    for (const cache of Object.values(caches)) {
      const tiles = cache._tiles;
      if (!tiles) continue;
      for (const tile of Object.values(tiles)) {
        if (tile.state !== "loaded" && tile.state !== "errored") n += 1;
      }
    }
    return n;
  } catch {
    return undefined;
  }
}

function frameError(map: MapLibreMap, index: number, cam: MapsCamera, cause: unknown): Error {
  const unloaded = unloadedTileCount(map);
  const extra = unloaded != null ? ` unloaded=${unloaded}` : "";
  const why = cause instanceof Error ? cause.message : String(cause);
  return new Error(
    `Fly frame ${index} at lat=${cam.lat.toFixed(4)} lon=${cam.lon.toFixed(4)} zoom=${cam.zoom.toFixed(2)}${extra}: ${why}`
  );
}

async function waitFrameOrRetry(
  map: MapLibreMap,
  cam: MapsCamera,
  surfaceWidth: number,
  index: number,
  frameDeadline: number,
  isCancelled?: () => boolean
): Promise<void> {
  const budget = () => frameDeadline - Date.now();
  const waitOnce = async () => {
    const left = budget();
    if (left <= 0) throw new Error("frame tile-wait budget exhausted");
    await waitIdleForFrame(map, left, isCancelled);
  };
  jumpToCamera(map, cam, surfaceWidth);
  try {
    await waitOnce();
  } catch (err) {
    if (isCancelled?.()) throw new Error("Export cancelled.");
    if (budget() <= 0) throw frameError(map, index, cam, err);
    jumpToCamera(map, cam, surfaceWidth);
    try {
      await waitOnce();
    } catch (err2) {
      if (isCancelled?.()) throw new Error("Export cancelled.");
      throw frameError(map, index, cam, err2);
    }
  }
}

export async function captureFlyFrames(opts: {
  width: number;
  height: number;
  from: MapsCamera;
  to: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  hiddenLayers: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  churches?: MapsChurch[];
  destinationChurches?: MapsChurch[];
  destinationPaintsReveal?: boolean;
  objectTransition?: "fade" | "hold";
  assetBaseUrl?: string;
  numberPins?: boolean;
  duration: number;
  fps?: number;
  easing?: MapsEasing;
  routePoints?: MapsRoutePoint[];
  curve?: number;
  flyZoom?: number;
  easeIn?: number;
  easeOut?: number;
  flight?: MapsFlight;
  outputCrop?: {
    width: number;
    height: number;
    fromX: number;
    toX: number;
    fromY?: number;
    toY?: number;
  };
  isCancelled?: () => boolean;
  onFrame: (blob: Blob, index: number, count: number) => Promise<void>;
}): Promise<number> {
  const {
    width,
    height,
    from,
    to,
    styleId,
    highlights,
    hiddenLayers,
    hillshade,
    isolate,
    churches,
    destinationChurches,
    destinationPaintsReveal = true,
    objectTransition,
    assetBaseUrl,
    numberPins = false,
    duration,
    fps = 30,
    easing,
    routePoints,
    curve,
    flyZoom,
    easeIn,
    easeOut,
    flight,
    outputCrop,
    isCancelled,
    onFrame,
  } = opts;
  const cancelled = () => Boolean(isCancelled?.());
  if (cancelled()) throw new Error("Export cancelled.");
  const count = Math.max(2, Math.round(duration * fps));
  const { map, host, surface } = await createExportMap({
    width,
    height,
    camera: from,
    styleId,
    highlights,
    hiddenLayers,
    hillshade,
    isolate,
    churches: destinationChurches ? [...(churches || []), ...(destinationPaintsReveal ? withoutRevealed(destinationChurches) : destinationChurches)] : churches,
    numberPins,
    assetBaseUrl,
    isCancelled,
  });
  const objectScale = 1 / surface.pixelRatio;
  try {
    // Hop maths (cruiseZoom, cameraAtHop, arcPath) stay in authored px/zoom — `width` here is
    // the authored surface width, unrelated to the render scale applied at jumpToCamera.
    const cameras: MapsCamera[] = [];
    for (let i = 0; i < count; i++) {
      const t = i / (count - 1);
      cameras.push(cameraAtHop(from, to, t, { easing, routePoints, curve, flyZoom, easeIn, easeOut, flight, duration, width }));
    }
    for (let i = 0; i < count; i++) {
      if (cancelled()) throw new Error("Export cancelled.");
      const cam = cameras[i];
      const t = i / (count - 1);
      if (churches && map.getSource("churches")) {
        const objects = destinationChurches ? movieObjectsAt(churches, destinationChurches, t, objectTransition, destinationPaintsReveal) : churches;
        (map.getSource("churches") as unknown as { setData(data: GeoJSON.FeatureCollection): void }).setData(churchesGeo(objects, null, numberPins, objectScale));
        map.triggerRepaint();
      }
      await waitFrameOrRetry(map, cam, width, i, Date.now() + FRAME_TILE_WAIT_MS, isCancelled);
      if (cancelled()) throw new Error("Export cancelled.");
      const cropX = surface.cropX + (outputCrop ? outputCrop.fromX + (outputCrop.toX - outputCrop.fromX) * t : 0);
      const cropY = surface.cropY + (outputCrop ? (outputCrop.fromY || 0) + ((outputCrop.toY || 0) - (outputCrop.fromY || 0)) * t : 0);
      const blob = await stampOsmCropOnCanvas(
        map.getCanvas(),
        cropX,
        cropY,
        outputCrop ? outputCrop.width : width,
        outputCrop ? outputCrop.height : height,
        "image/jpeg",
        0.95,
        hillshade === true,
        styleId
      );
      if (cancelled()) throw new Error("Export cancelled.");
      await onFrame(blob, i, count);
    }
    return count;
  } finally {
    map.remove();
    host.remove();
  }
}
