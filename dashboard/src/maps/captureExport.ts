import "./maplibreWorker";
import { Map as MapLibreMap } from "maplibre-gl";
import { applyLayerFilters } from "./layers";
import {
  addOverlays,
  admin1FeaturesInPlay,
  highlightedCountries,
  applyHillshade,
  ensureAdmin0Highlights,
  ensureLowZoomRaster,
  loadAdmin0,
  loadAdmin1,
} from "./overlays";
import { isolatePairBaseVisibility, isolatePairCutoutVisibility } from "./captureIsolateVisibility";
import { highlightPieces, pieceClip } from "./isolate";
import { stampOsmCropOnCanvas } from "./stampOsm";
import { resolveOpenFreeMapStyle } from "./styles";
import { mapsTransformRequest } from "./tileProxy";
import { syncBorderlandsInk, waitForBorderlandsInk } from "./borderlandsInk";
import { installPatternById, installPatterns, stylePatterns } from "./watercolourStyle";
import {
  exportCamera,
  exportSurface,
  exportZoomDelta,
  type ExportSurface,
  type MapsCamera,
  type MapsChurch,
  type MapsIsolate,
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

/** GPU-supported `maxCanvasSize` cap, shared with the preview map so its pinned pixelRatio is
 * actually honoured rather than silently clamped (MapLibre's default maxCanvasSize is 4096). */
export function exportGpuCap(): number {
  return Math.min(maxTextureSize(), HARD_CAP);
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
      await waitForBorderlandsInk(map, { isCancelled, deadlineMs: Math.max(1, deadline - Date.now()) });
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
  /** Slide's authored surface width (WALL_W/CENTRE_W/CG_W), used to pick the render scale.
   * Defaults to `width`; morph plates pass this explicitly since a plate can be larger than
   * one authored surface (see `morphPlatePx`). */
  surfaceWidth?: number;
  camera: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  hiddenLayers: MapsLayerFilterId[];
  hillshade?: boolean;
  isolate?: MapsIsolate;
  churches?: MapsChurch[];
  numberPins?: boolean;
  assetBaseUrl?: string;
  isCancelled?: () => boolean;
  stamp?: boolean;
  /** Overrides the module-level highlight colour for this map only, so an in-progress export
   * keeps a single colour even if the operator's settings resolve mid-export. */
  highlightColour?: string;
  highlightColours?: Record<string, string>;
};

export async function createExportMap(
  opts: ExportMapOpts
): Promise<{ map: MapLibreMap; host: HTMLDivElement; surface: ExportSurface }> {
  const {
    width,
    height,
    camera,
    styleId,
    highlights,
    hiddenLayers,
    hillshade = false,
    isolate,
    churches,
    numberPins = false,
    assetBaseUrl,
    isCancelled,
    highlightColour: highlightColourOverride,
    highlightColours,
  } = opts;
  const surfaceWidth = opts.surfaceWidth ?? width;
  const surface = exportSurface(width, height, surfaceWidth);
  const zoomDelta = exportZoomDelta(surfaceWidth);
  const tex = maxTextureSize();
  const cap = Math.min(tex, HARD_CAP);
  if (surface.canvasWidth > cap || surface.canvasHeight > cap) {
    throw new Error(`Export raster ${surface.canvasWidth}×${surface.canvasHeight} exceeds GPU texture cap ${cap}.`);
  }
  const host = document.createElement("div");
  host.style.cssText = `position:fixed;left:-99999px;top:0;width:${surface.cssWidth}px;height:${surface.cssHeight}px;visibility:hidden;pointer-events:none;`;
  document.body.appendChild(host);
  const style = await resolveOpenFreeMapStyle(styleId, zoomDelta);
  const exportCam = exportCamera(camera, surfaceWidth);
  const map = new MapLibreMap({
    container: host,
    style,
    center: [exportCam.lon, exportCam.lat],
    zoom: exportCam.zoom,
    bearing: exportCam.bearing,
    pitch: exportCam.pitch,
    renderWorldCopies: true,
    transformConstrain: (center, zoom) => ({ center, zoom: Math.max(zoomDelta, Math.min(22 + zoomDelta, zoom)) }),
    minZoom: zoomDelta,
    attributionControl: false,
    fadeDuration: 0,
    pixelRatio: surface.pixelRatio,
    maxCanvasSize: [cap, cap],
    interactive: false,
    transformRequest: (url) => mapsTransformRequest(url),
    canvasContextAttributes: { preserveDrawingBuffer: true },
  });
  map.on("styleimagemissing", (event) => installPatternById(map, styleId, event.id));
  try {
    await waitEvent(map, "load", TILE_WAIT_MS, isCancelled);
    installPatterns(map, stylePatterns(styleId));
    syncBorderlandsInk(map, styleId, { authoredZoomDelta: zoomDelta });
    // Toner boundaries and relief gates are already baked into `style` at the authored offset
    // via resolveOpenFreeMapStyle above; only the JS-added ne2 fallback layer needs the offset here.
    ensureLowZoomRaster(map, styleId, zoomDelta);
    applyLayerFilters(map, hiddenLayers);
    applyHillshade(map, hillshade);
    const objectScale = 1 / surface.pixelRatio;
    if (churches) {
      await addOverlays(
        map,
        highlights,
        churches,
        null,
        styleId,
        numberPins,
        assetBaseUrl,
        objectScale,
        isolate,
        [],
        undefined,
        highlightColourOverride,
        highlightColours
      );
    } else {
      await ensureAdmin0Highlights(map, highlights, styleId, isolate, zoomDelta, [], undefined, highlightColourOverride, highlightColours);
    }
    applyLayerFilters(map, hiddenLayers);
    applyHillshade(map, hillshade);
    await waitIdleForFrame(map, undefined, isCancelled);
    return { map, host, surface };
  } catch (err) {
    map.remove();
    host.remove();
    throw err;
  }
}

export async function captureExportRaster(opts: ExportMapOpts): Promise<Blob> {
  const { map, host, surface } = await createExportMap(opts);
  try {
    return await stampOsmCropOnCanvas(
      map.getCanvas(),
      surface.cropX,
      surface.cropY,
      opts.width,
      opts.height,
      "image/png",
      1,
      opts.hillshade === true,
      opts.styleId,
      opts.stamp !== false
    );
  } finally {
    map.remove();
    host.remove();
  }
}

/** Highlighted slides render a second still: the highlighted area cut out of the base, so Keynote
 * can stack it above the mask with pins on top. Null when there is nothing highlighted.
 *
 * The base always drops the highlight. The cutout restores it so filled colours land in the piece;
 * no-fill (`none`) highlights stay map-style only. */
export async function captureIsolatePair(
  opts: ExportMapOpts
): Promise<{ base: Blob; pieces: { id: string; x: number; y: number; w: number; h: number; blob: Blob }[] } | null> {
  if (!opts.highlights.length) return null;
  const { map, host, surface } = await createExportMap(opts);
  try {
    isolatePairBaseVisibility(map, opts.highlights);
    await waitIdleForFrame(map, undefined, opts.isCancelled);
    const base = await stampOsmCropOnCanvas(
      map.getCanvas(),
      surface.cropX,
      surface.cropY,
      opts.width,
      opts.height,
      "image/png",
      1,
      opts.hillshade === true,
      opts.styleId,
      opts.stamp !== false
    );

    isolatePairCutoutVisibility(map, opts.highlights, opts.highlightColours);
    await waitIdleForFrame(map, undefined, opts.isCancelled);

    const admin0 = await loadAdmin0();
    if (opts.highlights.some((h) => h.startsWith("A1:"))) {
      await Promise.all(highlightedCountries(opts.highlights).map(loadAdmin1));
    }
    const highlightedPieces = highlightPieces(
      (admin0?.features || []) as never,
      opts.highlights,
      admin1FeaturesInPlay(opts.highlights)
    );
    const pr = surface.pixelRatio;
    const pieces: { id: string; x: number; y: number; w: number; h: number; blob: Blob }[] = [];
    for (const piece of highlightedPieces) {
      const clip = pieceClip(
        piece.rings,
        (lonLat) => map.project(lonLat),
        pr,
        surface.cropX,
        surface.cropY,
        opts.width,
        opts.height
      );
      if (!clip) continue;
      const { box, ringsPx, source, dest } = clip;
      const canvas = document.createElement("canvas");
      canvas.width = box.w;
      canvas.height = box.h;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("2D canvas context is unavailable for the isolate cut-out.");
      ctx.translate(-box.x, -box.y);
      ctx.beginPath();
      for (const ring of ringsPx) {
        ring.forEach(([px, py], index) => {
          if (index === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.closePath();
      }
      ctx.clip();
      ctx.drawImage(
        map.getCanvas(),
        source.sx,
        source.sy,
        source.sw,
        source.sh,
        dest.dx,
        dest.dy,
        dest.dw,
        dest.dh
      );
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Isolate cut-out toBlob failed."))), "image/png");
      });
      pieces.push({ id: piece.id, x: box.x, y: box.y, w: box.w, h: box.h, blob });
    }
    return { base, pieces };
  } finally {
    map.remove();
    host.remove();
  }
}
