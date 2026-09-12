import "./maplibreWorker";
import { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { MapMouseEvent } from "maplibre-gl";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import { cameraAtHop } from "./captureFly";
import { applyLayerFilters } from "./layers";
import { addOverlays, applyHighlights, applyHillshade, applyIsolate, churchesGeo, ensureDropPinImages, ensureLandmarkImages, ensureLowZoomRaster, loadAdmin0, movieObjectsAt, withoutRevealed } from "./overlays";
import { exportGpuCap } from "./captureExport";
import { defaultObjectSize, effectiveObjectSize, resizeFromCorner, zoomSizeFactor, type ObjectCorner } from "./objects";
import { OPENFREEMAP_STYLES, resolveOpenFreeMapStyle } from "./styles";
import { applyAuthoredZoomGates } from "./tonerBoundaries";
import { installPatternById, installPatterns, paperGrainCss, paperGrainUrl, stylePatterns } from "./watercolourStyle";
import { mapsTransformRequest } from "./tileProxy";
import { BandOverlays } from "./BandOverlays";
import {
  BASE_FOV_DEG,
  cgDragDx,
  clampMapZoom,
  clampZoom,
  exportScale,
  exportZoomDelta,
  minZoomForView,
  ML_MAX_ZOOM,
  ML_MIN_ZOOM,
  previewLayout,
  snapCgShift,
  surfaceWidthOf,
  wrapLon,
  worldCopyWarning,
  type MapsCamera,
  type MapsChurch,
  type MapsCropId,
  type MapsEasing,
  type MapsFlight,
  type MapsIsolate,
  type MapsLayerFilterId,
  type MapsRoutePoint,
  type MapsStyleId,
  type PreviewLayout,
} from "./types";

const WALL_W = 7680;
const CG_W = 1920;
const CG_ORIGIN = 2880;
const PIN_LAYERS = ["churches-dots", "churches-drops", "churches-landmarks", "churches-labels"];
const COUNTRY_PICK_MAX_ZOOM = 7;

/** Pinned preview: CSS-px-per-authored-px is fixed at 1/exportScale(authoredWidth) — the same
 * density the export renders that slide's own capture surface at, so the captured region is
 * always 1920 CSS px wide (EXPORT_REF_WIDTH) at that density. "Show side panels" can still widen
 * the *visible* band beyond the capture (`surfaceWidth` > `authoredWidth`, framing context around
 * a centre-only slide) — the inner element then grows wider at the SAME density rather than
 * changing it, exactly like the old fov-widened full-frame host did. A CSS transform (k = band's
 * on-screen width ÷ inner's own CSS width) then scales that fixed-density surface to fit the band. */
function objectLayoutScale(authoredWidth: number): number {
  return 1 / exportScale(authoredWidth);
}

/** Converts a client-space pointer position into the map's own (untransformed) layout space,
 * so `map.project`/`map.unproject`/`queryRenderedFeatures` see the same coordinates MapLibre's
 * own internal event handling would (MapLibre's DOM.getScale already does this for native events;
 * this mirrors it for our own manual `getBoundingClientRect()` math). */
function toLayoutPoint(map: MapLibreMap, clientX: number, clientY: number): [number, number] {
  const canvas = map.getCanvas();
  const rect = canvas.getBoundingClientRect();
  const k = canvas.clientWidth ? rect.width / canvas.clientWidth : 1;
  return [(clientX - rect.left) / k, (clientY - rect.top) / k];
}

/** Screen-px-per-authored-px, for interpreting a raw pointer drag delta (object resize handles). */
function objectDragScale(map: MapLibreMap, authoredWidth: number): number {
  const canvas = map.getCanvas();
  const rect = canvas.getBoundingClientRect();
  const k = canvas.clientWidth ? rect.width / canvas.clientWidth : 1;
  return k * objectLayoutScale(authoredWidth);
}

function captureCanvas(canvas: HTMLCanvasElement, rect?: { x: number; y: number; width: number; height: number }) {
  if (!rect) {
    return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  }
  const scaleX = canvas.width / canvas.clientWidth;
  const scaleY = canvas.height / canvas.clientHeight;
  const output = document.createElement("canvas");
  output.width = Math.max(1, Math.round(rect.width * scaleX));
  output.height = Math.max(1, Math.round(rect.height * scaleY));
  const ctx = output.getContext("2d");
  if (!ctx) return Promise.resolve(null);
  ctx.drawImage(
    canvas,
    rect.x * scaleX,
    rect.y * scaleY,
    rect.width * scaleX,
    rect.height * scaleY,
    0,
    0,
    output.width,
    output.height
  );
  return new Promise<Blob | null>((resolve) => output.toBlob(resolve, "image/png"));
}

function authoredZoomOf(map: MapLibreMap, delta: number, minZoom: number, peggedAuthored?: number): number {
  const fromMap = clampZoom(map.getZoom() - delta, minZoom);
  if (peggedAuthored != null && map.getZoom() <= map.getMinZoom() + 1e-4) {
    return Math.min(fromMap, peggedAuthored);
  }
  return fromMap;
}

function mapZoomOf(authored: number, delta: number, minZoom: number): number {
  return clampMapZoom(clampZoom(authored, minZoom) + delta);
}

function readCamera(map: MapLibreMap, delta: number, minZoom: number, peggedAuthored?: number): MapsCamera {
  const center = map.getCenter();
  return {
    lat: center.lat,
    lon: wrapLon(center.lng),
    zoom: authoredZoomOf(map, delta, minZoom, peggedAuthored),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

function cameraView(_map: MapLibreMap, camera: MapsCamera, delta: number, minZoom: number) {
  return {
    center: [camera.lon, camera.lat] as [number, number],
    zoom: mapZoomOf(camera.zoom, delta, minZoom),
    bearing: camera.bearing,
    pitch: camera.pitch,
  };
}

function silentJump(map: MapLibreMap, suppress: { current: boolean }, view: Parameters<MapLibreMap["jumpTo"]>[0]): void {
  suppress.current = true;
  try {
    map.jumpTo(view);
  } finally {
    suppress.current = false;
  }
}

function silently(suppress: { current: boolean }, fn: () => void): void {
  const prev = suppress.current;
  suppress.current = true;
  try {
    fn();
  } finally {
    suppress.current = prev;
  }
}

function applyPreviewZoomLimits(map: MapLibreMap, minZoom: number, delta: number): void {
  const minZ = clampMapZoom(minZoom + delta);
  const maxZ = Math.max(minZ, clampMapZoom(22 + delta));
  try {
    if (map.getMinZoom() !== minZ) map.setMinZoom(minZ);
    if (map.getMaxZoom() !== maxZ) map.setMaxZoom(maxZ);
  } catch (err) {
    console.warn("maplibre zoom limits", err);
  }
}

/** Re-derives the map's zoom/limits/relief gates for a (possibly new) authored surface width.
 * Only needed when `authoredWidth` itself changes — window resizes only touch the CSS transform
 * and pixelRatio, never the camera, since the authored↔map zoom delta is now a pure function of
 * authoredWidth rather than the live container size. */
function applyAuthoredWidth(
  map: MapLibreMap,
  authoredWidth: number,
  minZoom: number,
  deltaRef: { current: number },
  suppress: { current: boolean },
  authoredHint?: number
) {
  const authored = readCamera(map, deltaRef.current, minZoom, authoredHint);
  const delta = exportZoomDelta(authoredWidth);
  applyPreviewZoomLimits(map, minZoom, delta);
  deltaRef.current = delta;
  applyAuthoredZoomGates(map, delta);
  silentJump(map, suppress, cameraView(map, authored, delta, minZoom));
}

export type MapViewHandle = {
  jumpTo: (camera: MapsCamera) => void;
  easeTo: (camera: MapsCamera, durationMs: number) => Promise<void>;
  flyTo: (camera: MapsCamera, durationMs?: number) => Promise<void>;
  animateHop: (opts: {
    from: MapsCamera;
    to: MapsCamera;
    durationMs: number;
    easing?: MapsEasing;
    routePoints?: MapsRoutePoint[];
    curve?: number;
    flyZoom?: number;
    easeIn?: number;
    easeOut?: number;
    flight?: MapsFlight;
    width?: number;
    fromObjects?: MapsChurch[];
    toObjects?: MapsChurch[];
    objectTransition?: "fade" | "hold";
    destinationPaintsReveal?: boolean;
  }) => Promise<void>;
  stop: () => void;
  getCamera: () => MapsCamera | null;
  getCgCamera: (cgShiftX: number) => MapsCamera | null;
  captureBlob: () => Promise<Blob | null>;
  capturePreviewBlob: () => Promise<Blob | null>;
  waitUntilIdle: (styleId?: MapsStyleId, timeoutMs?: number) => Promise<void>;
  resize: () => void;
};

type Props = {
  camera: MapsCamera;
  styleId: MapsStyleId;
  highlights: string[];
  churches: MapsChurch[];
  numberPins?: boolean;
  crop: MapsCropId;
  sidePanels: boolean;
  exportCg: boolean;
  hiddenLayers: MapsLayerFilterId[];
  hillshade: boolean;
  isolate?: MapsIsolate;
  cgShiftX: number;
  authoredWidth?: number;
  previewing: boolean;
  selectedPinId: string | null;
  onCameraCommit: (camera: MapsCamera) => void;
  onToggleCountry: (adm0: string) => void;
  onAddPin: (lat: number, lon: number) => void;
  onSelectPin: (id: string | null) => void;
  onEditPin: (id: string) => void;
  onMoveObject: (id: string, lat: number, lon: number) => void;
  onResizeObject: (id: string, size: number) => void;
  onObjectCommit: () => void;
  onCgShift: (dx: number) => void;
  onPreviewAbort?: () => void;
  assetBaseUrl?: string;
};

function pinIdFromEvent(event: MapMouseEvent, map: MapLibreMap): string {
  const layers = PIN_LAYERS.filter((id) => map.getLayer(id));
  const hits = layers.length ? map.queryRenderedFeatures(event.point, { layers }) : [];
  return String(hits[0]?.properties?.id || "");
}

export type MapViewProps = Props;

export const MapView = forwardRef<MapViewHandle, Props>(function MapView(
  {
    camera,
    styleId,
    highlights,
    churches,
    numberPins = false,
    sidePanels,
    exportCg,
    hiddenLayers,
    hillshade,
    isolate,
    cgShiftX,
    authoredWidth = WALL_W,
    previewing,
    selectedPinId,
    onCameraCommit,
    onToggleCountry,
    onAddPin,
    onSelectPin,
    onEditPin,
    onMoveObject,
    onResizeObject,
    onObjectCommit,
    onCgShift,
    onPreviewAbort,
    assetBaseUrl,
  },
  ref
) {
  const frame = useRef<HTMLDivElement>(null);
  const band = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const layoutRef = useRef<PreviewLayout>({ innerW: 0, innerH: 0, bandW: 0, bandH: 0, bandTop: 0, bandInnerH: 0, k: 1, fov: BASE_FOV_DEG });
  const [view, setView] = useState<{ k: number; bandTop: number; bandInnerH: number }>({
    k: layoutRef.current.k,
    bandTop: layoutRef.current.bandTop,
    bandInnerH: layoutRef.current.bandInnerH,
  });
  const mapRef = useRef<MapLibreMap | null>(null);
  const suppress = useRef(false);
  const styleUrl = useRef(OPENFREEMAP_STYLES[styleId]);
  const styleIdentity = useRef(styleId);
  const styleReady = useRef(false);
  const overlayGeneration = useRef(0);
  const previewingRef = useRef(previewing);
  const callbacks = useRef({ onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onMoveObject, onResizeObject, onObjectCommit, onCgShift, onPreviewAbort });
  const overlay = useRef({ highlights, churches, selectedPinId, styleId, hiddenLayers, hillshade, isolate, numberPins });
  const cgDrag = useRef<{ x: number; shift: number; width: number; surfaceWidth: number } | null>(null);
  const objDrag = useRef<{ id: string; grabDx: number; grabDy: number; pointerId: number } | null>(null);
  const handleDrag = useRef<{ pointerId: number; startX: number; startY: number; startSize: number; corner: ObjectCorner; aspect: number } | null>(null);
  const [boxPos, setBoxPos] = useState<{ x: number; y: number; w: number; h: number; size: number } | null>(null);
  const [cgSnapped, setCgSnapped] = useState(false);
  const hopAbort = useRef(false);
  const hopRaf = useRef(0);
  const hopResolve = useRef<(() => void) | null>(null);
  const hopRestore = useRef<(() => void) | null>(null);
  const hopSeq = useRef(0);
  const deltaRef = useRef(0);
  const cameraRef = useRef(camera);
  const minZoomRef = useRef(minZoomForView());
  const authoredWidthRef = useRef(authoredWidth);
  // The live authoredWidth prop, synced every render — animateHop's restore reads this rather
  // than a value closed over at call time, so it restores to whatever is current even if the
  // prop changed mid-hop.
  const propWidthRef = useRef(authoredWidth);
  // While a movie hop is animating, the render surface is pinned to the hop's own (wider) export
  // surface rather than the active slide's authoredWidth prop — see animateHop.
  const hopWidthRef = useRef<number | null>(null);
  const [hopWidth, setHopWidth] = useState<number | null>(null);
  const sidePanelsRef = useRef(sidePanels);
  const [texWarn, setTexWarn] = useState<string | null>(null);
  const [gpuWarn, setGpuWarn] = useState<string | null>(null);

  function finishHop() {
    if (hopRaf.current) {
      cancelAnimationFrame(hopRaf.current);
      hopRaf.current = 0;
    }
    suppress.current = false;
    hopSeq.current += 1;
    const restore = hopRestore.current;
    hopRestore.current = null;
    restore?.();
    const resolve = hopResolve.current;
    hopResolve.current = null;
    resolve?.();
  }

  previewingRef.current = previewing;
  cameraRef.current = camera;
  minZoomRef.current = minZoomForView();
  propWidthRef.current = authoredWidth;
  authoredWidthRef.current = hopWidthRef.current ?? authoredWidth;
  sidePanelsRef.current = sidePanels;
  callbacks.current = { onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onMoveObject, onResizeObject, onObjectCommit, onCgShift, onPreviewAbort };
  overlay.current = { highlights, churches, selectedPinId, styleId, hiddenLayers, hillshade, isolate, numberPins };

  /** Sizes/positions `.maps-map-inner` to fill the whole frame (not just the band) at the
   * export-exact density and widens MapLibre's fov to match (`previewLayout`), so the margins
   * above/below the band render live map instead of a dimmed void (regression: nav context). */
  function applyTransform(authoredW = authoredWidthRef.current, sidePanelsOn = sidePanelsRef.current) {
    const frameEl = frame.current;
    const innerEl = inner.current;
    const map = mapRef.current;
    if (!frameEl || !innerEl) return;
    const surfaceWidth = surfaceWidthOf(authoredW, sidePanelsOn);
    const L = previewLayout(frameEl.clientWidth, frameEl.clientHeight, surfaceWidth, exportScale(authoredW));
    if (L.innerW <= 0 || L.innerH <= 0) return;
    innerEl.style.width = `${L.innerW}px`;
    innerEl.style.height = `${L.innerH}px`;
    innerEl.style.transform = `translateY(${-L.bandTop * L.k}px) scale(${L.k})`;
    layoutRef.current = L;
    setView((prev) =>
      Math.abs(prev.k - L.k) < 1e-4 && Math.abs(prev.bandTop - L.bandTop) < 1e-4 && Math.abs(prev.bandInnerH - L.bandInnerH) < 1e-4
        ? prev
        : { k: L.k, bandTop: L.bandTop, bandInnerH: L.bandInnerH }
    );
    if (map) {
      silently(suppress, () => {
        try {
          map.resize();
        } catch (err) {
          console.warn("maplibre resize", err);
        }
        map.setVerticalFieldOfView(L.fov);
        const requested = L.k * (window.devicePixelRatio || 1);
        try {
          map.setPixelRatio(requested);
        } catch (err) {
          console.warn("maplibre setPixelRatio", err);
        }
        const canvas = map.getCanvas();
        const honoured = canvas.clientWidth ? canvas.width / canvas.clientWidth : requested;
        if (Math.abs(honoured - requested) > 0.01) {
          const message = `Preview pixel ratio clamped to ${honoured.toFixed(2)} (wanted ${requested.toFixed(2)}); this band is not capture-exact.`;
          console.warn(message);
          setTexWarn(message);
        } else {
          setTexWarn(null);
        }
      });
    }
  }

  function captureBand() {
    const map = mapRef.current;
    if (!map) return Promise.resolve(null);
    const canvas = map.getCanvas();
    const L = layoutRef.current;
    return captureCanvas(canvas, { x: 0, y: L.bandTop, width: canvas.clientWidth, height: L.bandInnerH });
  }

  useImperativeHandle(ref, () => ({
    jumpTo(next) {
      const map = mapRef.current;
      if (!map) return;
      silentJump(map, suppress, cameraView(map, next, deltaRef.current, minZoomRef.current));
    },
    easeTo(next, durationMs) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      return new Promise((resolve) => {
        suppress.current = true;
        // MapsTab passes milliseconds (duration * 1000); MapLibre easeTo is ms.
        map.easeTo({ ...cameraView(map, next, deltaRef.current, minZoomRef.current), duration: Math.max(0, durationMs) });
        map.once("moveend", () => {
          suppress.current = false;
          resolve();
        });
      });
    },
    flyTo(next, durationMs = 1200) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      return new Promise((resolve) => {
        suppress.current = true;
        map.flyTo({ ...cameraView(map, next, deltaRef.current, minZoomRef.current), duration: Math.max(0, durationMs) });
        map.once("moveend", () => {
          suppress.current = false;
          resolve();
        });
      });
    },
    animateHop({ from, to, durationMs, easing, routePoints, curve, flyZoom, easeIn, easeOut, flight, width, fromObjects, toObjects, objectTransition, destinationPaintsReveal = true }) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      hopAbort.current = false;
      finishHop();
      // Render the hop at its own export surface (mirrors captureFlyFrames), not the active
      // slide's authoredWidth prop, so a mixed-surface hop previews at the export's density.
      const priorWidth = authoredWidthRef.current;
      const hopSurfaceW = width || priorWidth;
      // Idempotent against the LIVE prop, not a value closed over at call time, so a restore
      // that fires after the prop has since changed still lands on the current surface.
      const applyHopWidth = (w: number) => {
        const authored = readCamera(map, deltaRef.current, minZoomRef.current, cameraRef.current.zoom);
        const next = w === propWidthRef.current ? null : w;
        hopWidthRef.current = next;
        setHopWidth(next);
        authoredWidthRef.current = w;
        const delta = exportZoomDelta(w);
        deltaRef.current = delta;
        applyPreviewZoomLimits(map, minZoomRef.current, delta);
        applyAuthoredZoomGates(map, delta);
        applyTransform(w, sidePanelsRef.current);
        silentJump(map, suppress, cameraView(map, authored, delta, minZoomRef.current));
      };
      if (hopSurfaceW !== priorWidth) {
        // Armed before applying the override so a synchronous throw inside applyHopWidth
        // still leaves finishHop() something to restore.
        hopRestore.current = () => applyHopWidth(propWidthRef.current);
        applyHopWidth(hopSurfaceW);
      }
      const toObjectsPainted = destinationPaintsReveal ? withoutRevealed(toObjects || []) : toObjects || [];
      const seq = ++hopSeq.current;
      return Promise.all([
        ensureLandmarkImages(map, [...(fromObjects || []), ...toObjectsPainted], assetBaseUrl),
        Promise.resolve().then(() => ensureDropPinImages(map, [...(fromObjects || []), ...toObjectsPainted])),
      ])
        .then(
          () =>
            new Promise<void>((resolve, reject) => {
              if (hopSeq.current !== seq) return resolve();
              const apply = (t: number) => {
                const cam = cameraAtHop(from, to, t, {
                  easing,
                  routePoints,
                  curve,
                  flyZoom,
                  easeIn,
                  easeOut,
                  flight,
                  duration: durationMs / 1000,
                  width,
                });
                if (fromObjects && map.getSource("churches")) {
                  const objects = toObjects ? movieObjectsAt(fromObjects, toObjects, t, objectTransition, destinationPaintsReveal) : fromObjects;
                  (map.getSource("churches") as GeoJSONSource).setData(churchesGeo(objects, overlay.current.selectedPinId, overlay.current.numberPins, objectLayoutScale(authoredWidthRef.current)));
                }
                map.jumpTo({
                  center: [cam.lon, cam.lat],
                  zoom: mapZoomOf(cam.zoom, deltaRef.current, minZoomRef.current),
                  bearing: cam.bearing,
                  pitch: cam.pitch,
                });
              };
              const duration = Math.max(0, durationMs);
              hopResolve.current = resolve;
              suppress.current = true;
              if (duration === 0) {
                try {
                  apply(1);
                } catch (err) {
                  reject(err);
                  return;
                }
                finishHop();
                return;
              }
              const start = performance.now();
              const step = (now: number) => {
                if (hopAbort.current) {
                  finishHop();
                  return;
                }
                const t = Math.min(1, (now - start) / duration);
                try {
                  apply(t);
                } catch (err) {
                  reject(err);
                  return;
                }
                if (t < 1) hopRaf.current = requestAnimationFrame(step);
                else finishHop();
              };
              hopRaf.current = requestAnimationFrame(step);
            })
        )
        .catch((err) => {
          if (hopSeq.current === seq) {
            finishHop();
            throw err;
          }
        });
    },
    stop() {
      hopAbort.current = true;
      finishHop();
      mapRef.current?.stop();
    },
    getCamera() {
      const map = mapRef.current;
      return map ? readCamera(map, deltaRef.current, minZoomRef.current, cameraRef.current.zoom) : null;
    },
    getCgCamera(cgShiftX) {
      const map = mapRef.current;
      if (!map) return null;
      const current = readCamera(map, deltaRef.current, minZoomRef.current, cameraRef.current.zoom);
      const canvas = map.getCanvas();
      const shifted = map.unproject([
        canvas.clientWidth / 2 + cgShiftX * objectLayoutScale(authoredWidthRef.current),
        canvas.clientHeight / 2,
      ]);
      return { ...current, lat: shifted.lat, lon: wrapLon(shifted.lng) };
    },
    captureBlob() {
      return captureBand();
    },
    capturePreviewBlob() {
      return captureBand();
    },
    waitUntilIdle(expectedStyleId, timeoutMs = 15000) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      const expected = expectedStyleId || styleIdentity.current;
      return new Promise((resolve, reject) => {
        let finished = false;
        let timer = 0;
        let poll = 0;
        const finish = () => {
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          window.clearInterval(poll);
          map.off("idle", check);
          resolve();
        };
        const fail = (message: string) => {
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          window.clearInterval(poll);
          map.off("idle", check);
          reject(new Error(message));
        };
        const check = () => {
          if (mapRef.current !== map || styleIdentity.current !== expected) return fail("Map style changed before capture was ready");
          if (styleReady.current && map.loaded() && map.areTilesLoaded()) finish();
        };
        map.on("idle", check);
        poll = window.setInterval(check, 50);
        timer = window.setTimeout(() => fail("Map did not become ready before capture timed out"), Math.max(250, timeoutMs));
        requestAnimationFrame(check);
      });
    },
    resize() {
      const map = mapRef.current;
      if (!map) return;
      applyTransform();
      if (map.getSource("churches")) {
        (map.getSource("churches") as GeoJSONSource).setData(
          churchesGeo(overlay.current.churches, overlay.current.selectedPinId, overlay.current.numberPins, objectLayoutScale(authoredWidthRef.current))
        );
      }
    },
  }));

  useEffect(() => {
    if (!host.current || !band.current || !inner.current || !frame.current) return;
    const hostEl = host.current;
    const innerEl = inner.current;
    const frameEl = frame.current;
    let cancelled = false;
    let map: MapLibreMap | null = null;
    const onPointerUp = () => {
      if (!map || suppress.current || previewingRef.current) return;
      callbacks.current.onCameraCommit(readCamera(map, deltaRef.current, minZoomRef.current, cameraRef.current.zoom));
    };

    const onCanvasMouseMove = (event: MapMouseEvent) => {
      if (!map || previewingRef.current || objDrag.current) return;
      const selectedPinId = overlay.current.selectedPinId;
      if (!selectedPinId) {
        map.getCanvas().style.cursor = "";
        return;
      }
      const layers = PIN_LAYERS.filter((id) => map!.getLayer(id));
      const hit = layers.length ? map.queryRenderedFeatures(event.point, { layers }) : [];
      const id = String(hit[0]?.properties?.id || "");
      const church = id ? overlay.current.churches.find((c) => c.id === id) : undefined;
      map.getCanvas().style.cursor = church && church.id === selectedPinId && church.kind === "landmark" ? "move" : "";
    };

    const onObjPointerDown = (event: PointerEvent) => {
      if (!map || previewingRef.current || event.shiftKey) return;
      const point = toLayoutPoint(map, event.clientX, event.clientY);
      const layers = PIN_LAYERS.filter((id) => map!.getLayer(id));
      const id = String((layers.length ? map.queryRenderedFeatures(point, { layers }) : [])[0]?.properties?.id || "");
      const church = id ? overlay.current.churches.find((c) => c.id === id) : undefined;
      if (!church) return;
      const anchor = map.project([church.lon, church.lat]);
      map.dragPan.disable();
      map.getCanvas().setPointerCapture(event.pointerId);
      objDrag.current = { id: church.id, grabDx: point[0] - anchor.x, grabDy: point[1] - anchor.y, pointerId: event.pointerId };
    };

    const onObjPointerMove = (event: PointerEvent) => {
      const drag = objDrag.current;
      if (!map || !drag || drag.pointerId !== event.pointerId) return;
      const point = toLayoutPoint(map, event.clientX, event.clientY);
      const lngLat = map.unproject([point[0] - drag.grabDx, point[1] - drag.grabDy]);
      callbacks.current.onMoveObject(drag.id, lngLat.lat, lngLat.lng);
    };

    const onObjPointerUp = (event: PointerEvent) => {
      const drag = objDrag.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      if (map?.getCanvas().hasPointerCapture(event.pointerId)) map.getCanvas().releasePointerCapture(event.pointerId);
      map?.dragPan.enable();
      objDrag.current = null;
      callbacks.current.onObjectCommit();
    };

    const createMap = (wantedStyle: MapsStyleId) => {
      const surfaceWidth0 = surfaceWidthOf(authoredWidthRef.current, sidePanelsRef.current);
      const L0 = previewLayout(frameEl.clientWidth, frameEl.clientHeight, surfaceWidth0, exportScale(authoredWidthRef.current));
      innerEl.style.width = `${L0.innerW}px`;
      innerEl.style.height = `${L0.innerH}px`;
      layoutRef.current = L0;
      setView({ k: L0.k, bandTop: L0.bandTop, bandInnerH: L0.bandInnerH });
      const d0 = exportZoomDelta(authoredWidthRef.current);
      void resolveOpenFreeMapStyle(wantedStyle, d0).then((style) => {
        if (cancelled) return;
        if (overlay.current.styleId !== wantedStyle) {
          createMap(overlay.current.styleId);
          return;
        }
        const surfaceWidth = surfaceWidthOf(authoredWidthRef.current, sidePanelsRef.current);
        const L = previewLayout(frameEl.clientWidth, frameEl.clientHeight, surfaceWidth, exportScale(authoredWidthRef.current));
        const d = exportZoomDelta(authoredWidthRef.current);
        if (L.innerW > 0 && L.innerH > 0) {
          innerEl.style.width = `${L.innerW}px`;
          innerEl.style.height = `${L.innerH}px`;
        }
        layoutRef.current = L;
        setView({ k: L.k, bandTop: L.bandTop, bandInnerH: L.bandInnerH });
        const zMin = minZoomRef.current;
        deltaRef.current = d;
        const k0 = L.k;
        let gpuCap = 4096;
        try {
          gpuCap = exportGpuCap();
        } catch (err) {
          console.warn("exportGpuCap", err);
        }
        map = new MapLibreMap({
          container: hostEl,
          style,
          center: [camera.lon, camera.lat],
          zoom: mapZoomOf(camera.zoom, d, zMin),
          bearing: camera.bearing,
          pitch: camera.pitch,
          renderWorldCopies: true,
          doubleClickZoom: false,
          boxZoom: false,
          minZoom: ML_MIN_ZOOM,
          maxZoom: ML_MAX_ZOOM,
          pixelRatio: k0 * (window.devicePixelRatio || 1),
          maxCanvasSize: [gpuCap, gpuCap],
          attributionControl: { compact: true },
          transformRequest: (url) => mapsTransformRequest(url),
          canvasContextAttributes: { preserveDrawingBuffer: true },
          transformConstrain: (center, zoom) => ({ center, zoom: clampMapZoom(zoom) }),
        });
        mapRef.current = map;
        styleUrl.current = OPENFREEMAP_STYLES[wantedStyle];
        styleIdentity.current = wantedStyle;
        innerEl.style.transform = `translateY(${-L.bandTop * L.k}px) scale(${L.k})`;
        map.setVerticalFieldOfView(L.fov);

        function probeTex() {
          if (!map) return;
          const gl = map.getCanvas().getContext("webgl2") || map.getCanvas().getContext("webgl");
          if (!gl) return;
          const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
          if (typeof max === "number" && max < WALL_W) {
            const message = `GPU MAX_TEXTURE_SIZE is ${max}; 7680 plates will fail.`;
            console.warn(message);
            setGpuWarn(message);
          }
        }

        function paintOverlays() {
          if (!map) return;
          const currentMap = map;
          const generation = ++overlayGeneration.current;
          styleReady.current = false;
          ensureLowZoomRaster(currentMap, overlay.current.styleId, deltaRef.current);
          installPatterns(currentMap, stylePatterns(overlay.current.styleId));
          applyLayerFilters(currentMap, overlay.current.hiddenLayers);
          applyHillshade(currentMap, overlay.current.hillshade);
          void addOverlays(
            currentMap,
            overlay.current.highlights,
            overlay.current.churches,
            overlay.current.selectedPinId,
            overlay.current.styleId,
            overlay.current.numberPins,
            assetBaseUrl,
            objectLayoutScale(authoredWidthRef.current),
            overlay.current.isolate
          ).then(() => {
            if (mapRef.current === currentMap && overlayGeneration.current === generation) {
              styleReady.current = true;
              currentMap.triggerRepaint();
            }
          });
        }

        function commitCamera() {
          if (!map || suppress.current || previewingRef.current) return;
          callbacks.current.onCameraCommit(readCamera(map, deltaRef.current, minZoomRef.current, cameraRef.current.zoom));
        }

        map.on("error", (event) => {
          const message = event.error?.message || "MapLibre error";
          console.warn("maplibre", message);
        });
        map.on("styleimagemissing", (event) => {
          if (map) installPatternById(map, overlay.current.styleId, event.id);
        });
        map.on("load", () => {
          probeTex();
          try {
            if (map) silently(suppress, () => map!.resize());
            if (map) {
              const zMin = minZoomRef.current;
              applyPreviewZoomLimits(map, zMin, deltaRef.current);
              applyAuthoredZoomGates(map, deltaRef.current);
              silentJump(map, suppress, cameraView(map, cameraRef.current, deltaRef.current, zMin));
              ensureLowZoomRaster(map, overlay.current.styleId, deltaRef.current);
              installPatterns(map, stylePatterns(overlay.current.styleId));
              applyLayerFilters(map, overlay.current.hiddenLayers);
              applyHillshade(map, overlay.current.hillshade);
            }
          } catch (err) {
            suppress.current = false;
            console.warn("maplibre load", err);
          }
          void loadAdmin0().then(() => {
            if (mapRef.current === map) paintOverlays();
          });
        });
        map.on("style.load", () => {
          if (map) silently(suppress, () => map!.resize());
          if (map) {
            ensureLowZoomRaster(map, overlay.current.styleId, deltaRef.current);
            installPatterns(map, stylePatterns(overlay.current.styleId));
            applyLayerFilters(map, overlay.current.hiddenLayers);
            applyHillshade(map, overlay.current.hillshade);
          }
          void loadAdmin0().then(() => {
            if (mapRef.current === map) paintOverlays();
          });
        });
        map.on("moveend", commitCamera);
        map.on("mousemove", onCanvasMouseMove);
        map.on("mouseout", () => {
          if (map) map.getCanvas().style.cursor = "";
        });
        map.on("click", (event) => {
          if (!map) return;
          if (previewingRef.current) {
            callbacks.current.onPreviewAbort?.();
            return;
          }
          if (event.originalEvent.shiftKey) {
            callbacks.current.onAddPin(event.lngLat.lat, event.lngLat.lng);
            return;
          }
          const pin = pinIdFromEvent(event, map);
          if (pin) {
            callbacks.current.onSelectPin(pin);
            return;
          }
          callbacks.current.onSelectPin(null);
          if (authoredZoomOf(map, deltaRef.current, minZoomRef.current) >= COUNTRY_PICK_MAX_ZOOM) return;
          if (!map.getLayer("admin0-fill")) return;
          const hits = map.queryRenderedFeatures(event.point, { layers: ["admin0-fill"] });
          const code = String(hits[0]?.properties?.ADM0_A3 || "");
          if (code) callbacks.current.onToggleCountry(code);
        });
        map.on("dblclick", (event) => {
          if (!map) return;
          const pin = pinIdFromEvent(event, map);
          if (pin) {
            event.preventDefault();
            callbacks.current.onEditPin(pin);
          }
        });
        map.getCanvas().addEventListener("pointerup", onPointerUp);
        map.getCanvas().addEventListener("pointerdown", onObjPointerDown);
        map.getCanvas().addEventListener("pointermove", onObjPointerMove);
        map.getCanvas().addEventListener("pointerup", onObjPointerUp);
        map.getCanvas().addEventListener("pointercancel", onObjPointerUp);
      });
    };
    createMap(styleId);
    const ro = new ResizeObserver(() => applyTransform());
    ro.observe(frameEl);

    return () => {
      cancelled = true;
      hopAbort.current = true;
      finishHop();
      ro.disconnect();
      map?.getCanvas().removeEventListener("pointerup", onPointerUp);
      map?.getCanvas().removeEventListener("pointerdown", onObjPointerDown);
      map?.getCanvas().removeEventListener("pointermove", onObjPointerMove);
      map?.getCanvas().removeEventListener("pointerup", onObjPointerUp);
      map?.getCanvas().removeEventListener("pointercancel", onObjPointerUp);
      map?.remove();
      mapRef.current = null;
    };
    // Construct once; later camera/style updates go through the ref and other effects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const url = OPENFREEMAP_STYLES[styleId];
    if (styleIdentity.current === styleId) return;
    styleUrl.current = url;
    styleIdentity.current = styleId;
    styleReady.current = false;
    void resolveOpenFreeMapStyle(styleId, deltaRef.current).then((style) => {
      if (mapRef.current !== map || styleIdentity.current !== styleId) return;
      map.setStyle(style, { diff: false });
      map.once("style.load", () => {
        silently(suppress, () => {
          map.resize();
          map.setVerticalFieldOfView(layoutRef.current.fov);
        });
        applyAuthoredZoomGates(map, deltaRef.current);
        ensureLowZoomRaster(map, styleId, deltaRef.current);
        applyLayerFilters(map, overlay.current.hiddenLayers);
        applyHillshade(map, overlay.current.hillshade);
      });
    });
  }, [styleId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("churches")) return;
    void ensureLandmarkImages(map, churches, assetBaseUrl).then(() => {
      ensureDropPinImages(map, churches);
      (map.getSource("churches") as GeoJSONSource).setData(churchesGeo(churches, selectedPinId, numberPins, objectLayoutScale(authoredWidthRef.current)));
    }).catch((err) => console.warn("landmark images", err));
  }, [churches, selectedPinId, numberPins, assetBaseUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("admin0")) return;
    applyHighlights(map, highlights);
    applyIsolate(map, highlights, isolate);
  }, [highlights, isolate?.mode, isolate?.strength]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (hopWidthRef.current != null) return;
    applyTransform(authoredWidth, sidePanels);
    applyAuthoredWidth(map, authoredWidth, minZoomRef.current, deltaRef, suppress, cameraRef.current.zoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authoredWidth, sidePanels]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyLayerFilters(map, hiddenLayers);
  }, [hiddenLayers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyHillshade(map, hillshade);
  }, [hillshade]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedPinId || previewing) {
      setBoxPos(null);
      return;
    }
    const recompute = () => {
      const church = overlay.current.churches.find((c) => c.id === selectedPinId);
      if (!church) {
        setBoxPos(null);
        return;
      }
      const scale = objectLayoutScale(authoredWidthRef.current);
      const size = church.size || defaultObjectSize(church.kind);
      const eff = effectiveObjectSize(church, map.getZoom() - deltaRef.current);
      const w = eff * scale;
      const anchor = map.project([church.lon, church.lat]);
      if (church.kind === "dot") {
        // circle layer is centre-anchored.
        setBoxPos({ x: anchor.x - w / 2, y: anchor.y - w / 2, w, h: w, size });
      } else if (church.kind === "dropPin") {
        const h = w * 1.08;
        // icon-anchor is "bottom": the anchor point is the bottom-center of the rendered pin.
        setBoxPos({ x: anchor.x - w / 2, y: anchor.y - h, w, h, size });
      } else {
        const h = w * ((church.assetHeight || 1) / (church.assetWidth || 1));
        // icon-anchor is "bottom", so the anchor point is the bottom-center of the rendered image.
        setBoxPos({ x: anchor.x - w / 2, y: anchor.y - h, w, h, size });
      }
    };
    recompute();
    map.on("move", recompute);
    map.on("render", recompute);
    return () => {
      map.off("move", recompute);
      map.off("render", recompute);
    };
  }, [selectedPinId, previewing, churches]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = "";
  }, [previewing, selectedPinId]);

  function onHandlePointerDown(corner: ObjectCorner) {
    return (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      if (!boxPos) return;
      const church = overlay.current.churches.find((c) => c.id === selectedPinId);
      const aspect = church?.kind === "landmark" ? (church?.assetHeight || 1) / (church?.assetWidth || 1) : church?.kind === "dropPin" ? 1.08 : 1;
      event.currentTarget.setPointerCapture(event.pointerId);
      handleDrag.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startSize: boxPos.size, corner, aspect };
    };
  }

  function onHandlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = handleDrag.current;
    const map = mapRef.current;
    if (!drag || !map || !selectedPinId) return;
    const church = overlay.current.churches.find((c) => c.id === selectedPinId);
    const zoomFactor = church?.scaleWithMap && church.sizeZoom != null ? zoomSizeFactor(church.sizeZoom, map.getZoom() - deltaRef.current) : 1;
    const scale = objectDragScale(map, authoredWidthRef.current) * zoomFactor;
    const size = resizeFromCorner(
      { x: drag.startX, y: drag.startY },
      { x: event.clientX, y: event.clientY },
      drag.startSize,
      scale,
      drag.corner,
      drag.aspect
    );
    callbacks.current.onResizeObject(selectedPinId, size);
  }

  function onHandlePointerUp(event: React.PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    handleDrag.current = null;
    callbacks.current.onObjectCommit();
  }

  function eventToLngLat(event: { clientX: number; clientY: number }): { lat: number; lon: number } | null {
    const map = mapRef.current;
    if (!map) return null;
    const point = toLayoutPoint(map, event.clientX, event.clientY);
    const lngLat = map.unproject(point);
    return { lat: lngLat.lat, lon: lngLat.lng };
  }

  function onCgPointerDown(event: React.PointerEvent<HTMLElement>) {
    const map = mapRef.current;
    if (map && !event.shiftKey) {
      const point = toLayoutPoint(map, event.clientX, event.clientY);
      const layers = PIN_LAYERS.filter((id) => map.getLayer(id));
      const hitId = String((layers.length ? map.queryRenderedFeatures(point, { layers }) : [])[0]?.properties?.id || "");
      const church = hitId ? overlay.current.churches.find((c) => c.id === hitId) : undefined;
      if (church) {
        const anchor = map.project([church.lon, church.lat]);
        map.dragPan.disable();
        map.getCanvas().setPointerCapture(event.pointerId);
        objDrag.current = { id: church.id, grabDx: point[0] - anchor.x, grabDy: point[1] - anchor.y, pointerId: event.pointerId };
        return;
      }
    }
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) {
      const at = eventToLngLat(event);
      if (at) callbacks.current.onAddPin(at.lat, at.lon);
      return;
    }
    const bandEl = event.currentTarget.closest(".maps-map-band");
    const width = bandEl?.clientWidth || 1;
    event.currentTarget.setPointerCapture(event.pointerId);
    cgDrag.current = { x: event.clientX, shift: cgShiftX, width, surfaceWidth: surfaceWidthOf(effectiveWidth, sidePanels) };
  }

  function onCgPointerMove(event: React.PointerEvent<HTMLElement>) {
    const drag = cgDrag.current;
    if (!drag) return;
    const dx = cgDragDx(event.clientX - drag.x, drag.surfaceWidth, drag.width);
    const next = snapCgShift(drag.shift + dx);
    setCgSnapped(next === 0);
    callbacks.current.onCgShift(next);
  }

  function onCgPointerUp(event: React.PointerEvent<HTMLElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    cgDrag.current = null;
    setCgSnapped(false);
  }

  // A movie hop overrides the render surface via refs only (see animateHop); mirror it into
  // state so the band/grain/crop overlay re-render at the hop's own surface too, instead of
  // staying pinned to the (possibly mismatched) authoredWidth prop for the hop's duration.
  const effectiveWidth = hopWidth ?? authoredWidth;
  const wrapWarn = worldCopyWarning(camera.zoom);
  const surfaceWidth = surfaceWidthOf(effectiveWidth, sidePanels);
  const splitCg = surfaceWidth === CG_W;
  const fullWall = surfaceWidth === WALL_W;
  const surfaceOrigin = fullWall ? 0 : CG_ORIGIN - CG_W / 2;
  const cgLeft = ((CG_ORIGIN + cgShiftX - surfaceOrigin) / surfaceWidth) * 100;
  const cgWidth = (CG_W / surfaceWidth) * 100;
  const surfaceClass = splitCg ? "surface-cg" : fullWall ? "show-fw" : "center-only";

  return (
    <div
      className={`maps-map-frame ${surfaceClass}`}
      style={{ "--maps-surface-width": surfaceWidth } as React.CSSProperties}
      ref={frame}
    >
      <div className="maps-map-band" ref={band}>
        <div className="maps-map-inner" ref={inner}>
          <div className="maps-map-host" ref={host} />
          {styleId === "watercolour" && (
            <div
              className="maps-paper-grain"
              style={{
                top: view.bandTop,
                height: view.bandInnerH,
                backgroundImage: `url(${paperGrainUrl()})`,
                ...paperGrainCss(surfaceWidth * objectLayoutScale(effectiveWidth), surfaceWidth),
              }}
            />
          )}
        </div>
        <BandOverlays
          splitCg={splitCg}
          fullWall={fullWall}
          exportCg={exportCg}
          cgLeft={cgLeft}
          cgWidth={cgWidth}
          cgSnapped={cgSnapped}
          box={boxPos}
          k={view.k}
          bandTop={view.bandTop}
          onCgPointerDown={onCgPointerDown}
          onCgPointerMove={onCgPointerMove}
          onCgPointerUp={onCgPointerUp}
          onHandlePointerDown={onHandlePointerDown}
          onHandlePointerMove={onHandlePointerMove}
          onHandlePointerUp={onHandlePointerUp}
        />
      </div>
      <div className="maps-nav-margin top" />
      <div className="maps-nav-margin bottom" />
      {wrapWarn && <p className="maps-wrap-warn">{wrapWarn}</p>}
      {texWarn && <p className="maps-tex-warn">{texWarn}</p>}
      {gpuWarn && <p className="maps-tex-warn">{gpuWarn}</p>}
    </div>
  );
});
