import { Map as MapLibreMap, MercatorCoordinate } from "maplibre-gl";
import { createExportMap } from "./captureExport";
import { stampOsmOnCanvas } from "./stampOsm";
import type { MapsCamera, MapsEasing, MapsLayerFilterId, MapsRoutePoint, MapsStyleId } from "./types";

const IDLE_TIMEOUT_MS = 6000;

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

export function lerpCamera(from: MapsCamera, to: MapsCamera, t: number): MapsCamera {
  const a = mercatorOf(from);
  const b = mercatorOf(to);
  const bx = unwrapMercatorX(a.x, b.x);
  const merc = new MercatorCoordinate(wrapUnit(a.x + (bx - a.x) * t), a.y + (b.y - a.y) * t, 0);
  const lngLat = merc.toLngLat();
  return {
    lat: lngLat.lat,
    lon: lngLat.lng,
    zoom: from.zoom + (to.zoom - from.zoom) * t,
    bearing: shortestAngleLerp(from.bearing, to.bearing, t),
    pitch: from.pitch + (to.pitch - from.pitch) * t,
  };
}

export function easeAt(easing: MapsEasing, t: number): number {
  return (EASE_FNS[easing] || EASE_FNS["ease-in-out"])(t);
}

export function cameraAtHop(
  from: MapsCamera,
  to: MapsCamera,
  t: number,
  routePoints?: MapsRoutePoint[],
): MapsCamera {
  return routePoints && routePoints.length >= 2 ? cameraAlongRoute(from, to, routePoints, t) : lerpCamera(from, to, t);
}

export function cameraAlongRoute(from: MapsCamera, to: MapsCamera, points: MapsRoutePoint[], t: number): MapsCamera {
  const base = lerpCamera(from, to, t);
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

function raceIdle(map: MapLibreMap): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      map.off("idle", onIdle);
      map.off("error", onError);
      reject(new Error("idle-timeout"));
    }, IDLE_TIMEOUT_MS);
    const onIdle = () => {
      clearTimeout(timer);
      map.off("error", onError);
      resolve();
    };
    const onError = (event: { error?: { message?: string } }) => {
      clearTimeout(timer);
      map.off("idle", onIdle);
      reject(new Error(event.error?.message || "MapLibre export map failed"));
    };
    map.once("idle", onIdle);
    map.once("error", onError);
  });
}

async function waitIdleForFrame(map: MapLibreMap): Promise<void> {
  try {
    await raceIdle(map);
    return;
  } catch (err) {
    if (err instanceof Error && err.message !== "idle-timeout") throw err;
    if (map.areTilesLoaded()) return;
  }
  try {
    await raceIdle(map);
  } catch (err) {
    if (err instanceof Error && err.message !== "idle-timeout") throw err;
    if (map.areTilesLoaded()) return;
    throw new Error("Map tiles did not finish loading before a fly frame was captured.");
  }
}

export async function captureFlyFrames(opts: {
  width: number;
  height: number;
  from: MapsCamera;
  to: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  hiddenLayers?: MapsLayerFilterId[];
  duration: number;
  fps?: number;
  easing?: MapsEasing;
  routePoints?: MapsRoutePoint[];
  onFrame: (blob: Blob, index: number, count: number) => Promise<void>;
}): Promise<number> {
  const { width, height, from, to, styleId, highlights, hiddenLayers, duration, fps = 30, easing = "ease-in-out", routePoints, onFrame } = opts;
  const count = Math.max(2, Math.round(duration * fps));
  const { map, host } = await createExportMap({ width, height, camera: from, styleId, highlights, hiddenLayers });
  try {
    for (let i = 0; i < count; i++) {
      const t = easeAt(easing, i / (count - 1));
      const cam = cameraAtHop(from, to, t, routePoints);
      map.jumpTo({ center: [cam.lon, cam.lat], zoom: cam.zoom, bearing: cam.bearing, pitch: cam.pitch });
      await waitIdleForFrame(map);
      const blob = await stampOsmOnCanvas(map.getCanvas(), "image/jpeg", 0.95);
      await onFrame(blob, i, count);
    }
    return count;
  } finally {
    map.remove();
    host.remove();
  }
}
