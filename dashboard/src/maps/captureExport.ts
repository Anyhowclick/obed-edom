import "./maplibreWorker";
import { Map as MapLibreMap } from "maplibre-gl";
import { applyLayerFilters } from "./layers";
import { addOverlays, applyHillshade, ensureAdmin0Highlights, ensureLowZoomRaster } from "./overlays";
import { stampOsm } from "./stampOsm";
import { resolveOpenFreeMapStyle } from "./styles";
import { mapsTransformRequest } from "./tileProxy";
import { installPatternById, installPatterns, stylePatterns } from "./watercolourStyle";
import {
  type MapsCamera,
  type MapsChurch,
  type MapsLayerFilterId,
  type MapsStyleId,
} from "./types";

const HARD_CAP = 8192;
const TILE_WAIT_MS = 45000;

let cachedMaxTex: number | undefined;

function maxTextureSize(): number {
  if (cachedMaxTex != null) return cachedMaxTex;
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
  if (!gl) throw new Error("WebGL is unavailable; cannot capture export rasters.");
  try {
    const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    if (typeof max !== "number" || max < 1) throw new Error("GPU MAX_TEXTURE_SIZE is unknown.");
    cachedMaxTex = max;
    return max;
  } finally {
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}

export function waitEvent(
  map: MapLibreMap,
  name: "load" | "idle",
  timeoutMs = 45000,
  isCancelled?: () => boolean
): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (err?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearInterval(cancelTimer);
      map.off(name, onReady);
      if (err) reject(err);
      else resolve();
    };
    const timer = setTimeout(() => {
      if (name === "idle" && map.areTilesLoaded()) {
        finish();
        return;
      }
      finish(new Error(`MapLibre export map ${name} timed out.`));
    }, timeoutMs);
    const cancelTimer = setInterval(() => {
      if (isCancelled?.()) finish(new Error("Export cancelled."));
    }, 50);
    const onReady = () => finish();
    if (isCancelled?.()) {
      finish(new Error("Export cancelled."));
      return;
    }
    map.once(name, onReady);
  });
}

function waitForRender(map: MapLibreMap, timeoutMs: number, isCancelled?: () => boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const onRender = () => finish();
    const finish = (err?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearInterval(cancelTimer);
      map.off("render", onRender);
      if (err) reject(err);
      else resolve();
    };
    const timer = setTimeout(() => finish(new Error("MapLibre export map render timed out.")), timeoutMs);
    const cancelTimer = setInterval(() => {
      if (isCancelled?.()) finish(new Error("Export cancelled."));
    }, 50);
    if (isCancelled?.()) {
      finish(new Error("Export cancelled."));
      return;
    }
    map.once("render", onRender);
  });
}

export async function waitIdleForFrame(
  map: MapLibreMap,
  timeoutMs = TILE_WAIT_MS,
  isCancelled?: () => boolean
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  const nextRender = () => waitForRender(map, Math.max(1, deadline - Date.now()), isCancelled);
  map.triggerRepaint();
  await nextRender(); // in-view tile set now reflects this camera
  while (Date.now() < deadline) {
    if (isCancelled?.()) throw new Error("Export cancelled.");
    if (map.areTilesLoaded()) {
      map.triggerRepaint();
      await nextRender(); // guarantee a paint with those tiles
      return;
    }
    map.triggerRepaint();
    await nextRender();
  }
  throw new Error("Map tiles did not finish loading before a fly frame was captured.");
}

export type ExportMapOpts = {
  width: number;
  height: number;
  camera: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  hiddenLayers: MapsLayerFilterId[];
  hillshade?: boolean;
  churches?: MapsChurch[];
  numberPins?: boolean;
  assetBaseUrl?: string;
  isCancelled?: () => boolean;
};

export async function createExportMap(opts: ExportMapOpts): Promise<{ map: MapLibreMap; host: HTMLDivElement }> {
  const {
    width,
    height,
    camera,
    styleId,
    highlights,
    hiddenLayers,
    hillshade = false,
    churches,
    numberPins = false,
    assetBaseUrl,
    isCancelled,
  } = opts;
  const tex = maxTextureSize();
  const cap = Math.min(tex, HARD_CAP);
  if (width > cap || height > cap) {
    throw new Error(`Export raster ${width}×${height} exceeds GPU texture cap ${cap}.`);
  }
  const host = document.createElement("div");
  host.style.cssText = `position:fixed;left:-99999px;top:0;width:${width}px;height:${height}px;visibility:hidden;pointer-events:none;`;
  document.body.appendChild(host);
  const style = await resolveOpenFreeMapStyle(styleId);
  const map = new MapLibreMap({
    container: host,
    style,
    center: [camera.lon, camera.lat],
    zoom: camera.zoom,
    bearing: camera.bearing,
    pitch: camera.pitch,
    renderWorldCopies: true,
    transformConstrain: (center, zoom) => ({ center, zoom: Math.max(0, Math.min(22, zoom)) }),
    minZoom: 0,
    attributionControl: false,
    fadeDuration: 0,
    pixelRatio: 1,
    maxCanvasSize: [cap, cap],
    interactive: false,
    transformRequest: (url) => mapsTransformRequest(url),
    canvasContextAttributes: { preserveDrawingBuffer: true },
  });
  map.on("styleimagemissing", (event) => installPatternById(map, styleId, event.id));
  try {
    await waitEvent(map, "load", TILE_WAIT_MS, isCancelled);
    installPatterns(map, stylePatterns(styleId));
    ensureLowZoomRaster(map, styleId);
    applyLayerFilters(map, hiddenLayers);
    applyHillshade(map, hillshade);
    if (churches) {
      await addOverlays(map, highlights, churches, null, styleId, numberPins, assetBaseUrl);
    } else {
      await ensureAdmin0Highlights(map, highlights, styleId);
    }
    applyLayerFilters(map, hiddenLayers);
    applyHillshade(map, hillshade);
    await waitIdleForFrame(map, undefined, isCancelled);
    return { map, host };
  } catch (err) {
    map.remove();
    host.remove();
    throw err;
  }
}

export async function captureExportRaster(opts: ExportMapOpts): Promise<Blob> {
  const { map, host } = await createExportMap(opts);
  try {
    const raw = await new Promise<Blob>((resolve, reject) => {
      try {
        map.getCanvas().toBlob((blob) => {
          if (!blob) reject(new Error("Export canvas toBlob failed (CORS taint or empty)."));
          else resolve(blob);
        }, "image/png");
      } catch {
        reject(new Error("Map canvas is tainted (CORS). Cannot export."));
      }
    });
    return await stampOsm(raw, opts.hillshade === true, opts.styleId);
  } finally {
    map.remove();
    host.remove();
  }
}
