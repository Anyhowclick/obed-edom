import "./maplibreWorker";
import { Map as MapLibreMap } from "maplibre-gl";
import { applyLayerFilters } from "./layers";
import { ensureAdmin0Highlights, ensureLowZoomRaster } from "./overlays";
import { stampOsm } from "./stampOsm";
import { resolveOpenFreeMapStyle } from "./styles";
import { DEFAULT_HIDDEN_LAYERS, type MapsCamera, type MapsLayerFilterId, type MapsStyleId } from "./types";

const HARD_CAP = 8192;

function maxTextureSize(): number {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
  if (!gl) throw new Error("WebGL is unavailable; cannot capture export rasters.");
  const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  if (typeof max !== "number" || max < 1) throw new Error("GPU MAX_TEXTURE_SIZE is unknown.");
  return max;
}

export function waitEvent(map: MapLibreMap, name: "load" | "idle"): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (event: { error?: { message?: string } }) => {
      map.off(name, onReady);
      reject(new Error(event.error?.message || "MapLibre export map failed"));
    };
    const onReady = () => {
      map.off("error", onError);
      resolve();
    };
    map.once("error", onError);
    map.once(name, onReady);
  });
}

export type ExportMapOpts = {
  width: number;
  height: number;
  camera: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  hiddenLayers?: MapsLayerFilterId[];
};

export async function createExportMap(opts: ExportMapOpts): Promise<{ map: MapLibreMap; host: HTMLDivElement }> {
  const { width, height, camera, styleId, highlights, hiddenLayers = DEFAULT_HIDDEN_LAYERS } = opts;
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
    renderWorldCopies: false,
    attributionControl: false,
    fadeDuration: 0,
    pixelRatio: 1,
    maxCanvasSize: [cap, cap],
    interactive: false,
    canvasContextAttributes: { preserveDrawingBuffer: true },
  });
  try {
    await waitEvent(map, "load");
    ensureLowZoomRaster(map, styleId);
    applyLayerFilters(map, hiddenLayers);
    await ensureAdmin0Highlights(map, highlights, styleId);
    applyLayerFilters(map, hiddenLayers);
    await waitEvent(map, "idle");
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
    return await stampOsm(raw);
  } finally {
    map.remove();
    host.remove();
  }
}
