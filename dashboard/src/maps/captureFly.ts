import { Map as MapLibreMap, MercatorCoordinate } from "maplibre-gl";
import { createExportMap, waitIdleForFrame } from "./captureExport";
import { stampOsmCropOnCanvas, stampOsmOnCanvas } from "./stampOsm";
import {
  type MapsCamera,
  type MapsChurch,
  type MapsEasing,
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
  flyZoom?: number;
  easeIn?: number;
  easeOut?: number;
  duration?: number;
  width?: number;
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

export function cameraAtHop(from: MapsCamera, to: MapsCamera, t: number, interp: HopInterp = {}): MapsCamera {
  const tClamped = Math.max(0, Math.min(1, t));
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

function jumpToCamera(map: MapLibreMap, cam: MapsCamera): void {
  map.jumpTo({ center: [cam.lon, cam.lat], zoom: cam.zoom, bearing: cam.bearing, pitch: cam.pitch });
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
  jumpToCamera(map, cam);
  try {
    await waitOnce();
  } catch (err) {
    if (isCancelled?.()) throw new Error("Export cancelled.");
    if (budget() <= 0) throw frameError(map, index, cam, err);
    jumpToCamera(map, cam);
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
  churches?: MapsChurch[];
  numberPins?: boolean;
  duration: number;
  fps?: number;
  easing?: MapsEasing;
  routePoints?: MapsRoutePoint[];
  flyZoom?: number;
  easeIn?: number;
  easeOut?: number;
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
    churches,
    numberPins = false,
    duration,
    fps = 30,
    easing = "ease-in-out",
    routePoints,
    flyZoom,
    easeIn,
    easeOut,
    outputCrop,
    isCancelled,
    onFrame,
  } = opts;
  const cancelled = () => Boolean(isCancelled?.());
  if (cancelled()) throw new Error("Export cancelled.");
  const count = Math.max(2, Math.round(duration * fps));
  const { map, host } = await createExportMap({
    width,
    height,
    camera: from,
    styleId,
    highlights,
    hiddenLayers,
    hillshade,
    churches,
    numberPins,
    isCancelled,
  });
  try {
    const cameras: MapsCamera[] = [];
    for (let i = 0; i < count; i++) {
      const t = i / (count - 1);
      cameras.push(cameraAtHop(from, to, t, { easing, routePoints, flyZoom, easeIn, easeOut, duration, width }));
    }
    for (let i = 0; i < count; i++) {
      if (cancelled()) throw new Error("Export cancelled.");
      const cam = cameras[i];
      await waitFrameOrRetry(map, cam, i, Date.now() + FRAME_TILE_WAIT_MS, isCancelled);
      if (cancelled()) throw new Error("Export cancelled.");
      const t = i / (count - 1);
      const blob = outputCrop
        ? await stampOsmCropOnCanvas(
            map.getCanvas(),
            outputCrop.fromX + (outputCrop.toX - outputCrop.fromX) * t,
            (outputCrop.fromY || 0) + ((outputCrop.toY || 0) - (outputCrop.fromY || 0)) * t,
            outputCrop.width,
            outputCrop.height,
            "image/jpeg",
            0.95,
            hillshade === true
          )
        : await stampOsmOnCanvas(map.getCanvas(), "image/jpeg", 0.95, hillshade === true);
      if (cancelled()) throw new Error("Export cancelled.");
      await onFrame(blob, i, count);
    }
    return count;
  } finally {
    map.remove();
    host.remove();
  }
}
