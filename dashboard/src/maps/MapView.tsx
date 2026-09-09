import "./maplibreWorker";
import { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { MapMouseEvent } from "maplibre-gl";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import { cameraAtHop } from "./captureFly";
import { applyLayerFilters } from "./layers";
import { addOverlays, applyHighlights, applyHillshade, applyIsolate, churchesGeo, ensureDropPinImages, ensureLandmarkImages, ensureLowZoomRaster, loadAdmin0, movieObjectsAt } from "./overlays";
import { resizeFromHandle } from "./objects";
import { OPENFREEMAP_STYLES, resolveOpenFreeMapStyle } from "./styles";
import { applyBoundaryZoomOffset } from "./tonerBoundaries";
import { installPatternById, installPatterns, paperGrainUrl, stylePatterns } from "./watercolourStyle";
import { mapsTransformRequest } from "./tileProxy";
import {
  clampZoom,
  minZoomForView,
  wrapLon,
  worldCopyWarning,
  type MapsCamera,
  type MapsChurch,
  type MapsCropId,
  type MapsEasing,
  type MapsIsolate,
  type MapsLayerFilterId,
  type MapsRoutePoint,
  type MapsStyleId,
} from "./types";

const WALL_W = 7680;
const FW_W = 1920;
const CG_W = 1920;
const CG_ORIGIN = 2880;
const PIN_LAYERS = ["churches-dots", "churches-drops", "churches-landmarks", "churches-labels"];
const COUNTRY_PICK_MAX_ZOOM = 7;
const ML_MIN_ZOOM = -2;
const ML_PREVIEW_MIN_ZOOM = -8;
const ML_MAX_ZOOM = 22;

// The map container is `.maps-map-band`, already sized to the authored aspect by CSS — the whole canvas is the band.
function previewSurfaceRect(map: MapLibreMap, _authoredWidth = WALL_W) {
  const container = map.getContainer();
  return { x: 0, y: 0, width: container.clientWidth, height: container.clientHeight };
}

function previewZoomDelta(map: MapLibreMap, authoredWidth = WALL_W): number {
  const width = previewSurfaceRect(map, authoredWidth).width;
  if (!width) return 0;
  return Math.log2(width / authoredWidth);
}

function objectPreviewScale(map: MapLibreMap, authoredWidth = WALL_W): number {
  const width = previewSurfaceRect(map, authoredWidth).width;
  return width > 0 ? width / authoredWidth : 1;
}

// The preview canvas is now sized to the export band exactly, so a whole-canvas grab is the export.
function captureCanvas(canvas: HTMLCanvasElement) {
  return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
}

function clampMapZoom(zoom: number): number {
  return Math.max(ML_PREVIEW_MIN_ZOOM, Math.min(ML_MAX_ZOOM, zoom));
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

function applyPreviewZoomLimits(map: MapLibreMap, minZoom: number, delta = previewZoomDelta(map)): number {
  if (!map.getContainer().clientWidth) return delta;
  const minZ = clampMapZoom(minZoom + delta);
  const maxZ = Math.max(minZ, clampMapZoom(22 + delta));
  try {
    if (map.getMinZoom() !== minZ) {
      if (minZ < ML_MIN_ZOOM) {
        (map as unknown as { transform: { setMinZoom: (zoom: number) => void } }).transform.setMinZoom(minZ);
      }
      else map.setMinZoom(minZ);
    }
    if (map.getMaxZoom() !== maxZ) map.setMaxZoom(maxZ);
  } catch (err) {
    console.warn("maplibre zoom limits", err);
  }
  return delta;
}

function recastPreviewCamera(
  map: MapLibreMap,
  deltaRef: { current: number },
  suppress: { current: boolean },
  minZoom: number,
  authoredHint?: number,
  authoredWidth = WALL_W
) {
  if (!map.getContainer().clientWidth) return;
  try {
    const authored = readCamera(map, deltaRef.current, minZoom, authoredHint);
    map.resize();
    const d = applyPreviewZoomLimits(map, minZoom, previewZoomDelta(map, authoredWidth));
    deltaRef.current = d;
    applyBoundaryZoomOffset(map, d);
    suppress.current = true;
    map.jumpTo(cameraView(map, authored, d, minZoom));
    map.once("moveend", () => {
      suppress.current = false;
    });
  } catch (err) {
    suppress.current = false;
    console.warn("maplibre recast", err);
  }
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
    width?: number;
    fromObjects?: MapsChurch[];
    toObjects?: MapsChurch[];
    objectTransition?: "fade" | "hold";
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

export const MapView = forwardRef<MapViewHandle, Props>(function MapView(
  {
    camera,
    styleId,
    highlights,
    churches,
    numberPins = false,
    crop,
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
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const suppress = useRef(false);
  const styleUrl = useRef(OPENFREEMAP_STYLES[styleId]);
  const styleIdentity = useRef(styleId);
  const styleReady = useRef(false);
  const overlayGeneration = useRef(0);
  const previewingRef = useRef(previewing);
  const callbacks = useRef({ onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onMoveObject, onResizeObject, onObjectCommit, onCgShift, onPreviewAbort });
  const overlay = useRef({ highlights, churches, selectedPinId, styleId, hiddenLayers, hillshade, isolate, numberPins });
  const cgDrag = useRef<{ x: number; shift: number; width: number } | null>(null);
  const objDrag = useRef<{ id: string; grabDx: number; grabDy: number; pointerId: number } | null>(null);
  const handleDrag = useRef<{ pointerId: number; startX: number; startSize: number } | null>(null);
  const [handlePos, setHandlePos] = useState<{ x: number; y: number; size: number } | null>(null);
  const hopAbort = useRef(false);
  const hopRaf = useRef(0);
  const hopResolve = useRef<(() => void) | null>(null);
  const deltaRef = useRef(0);
  const cameraRef = useRef(camera);
  const minZoomRef = useRef(minZoomForView());
  const authoredWidthRef = useRef(authoredWidth);
  const [texWarn, setTexWarn] = useState<string | null>(null);

  function finishHop() {
    if (hopRaf.current) {
      cancelAnimationFrame(hopRaf.current);
      hopRaf.current = 0;
    }
    suppress.current = false;
    const resolve = hopResolve.current;
    hopResolve.current = null;
    resolve?.();
  }

  previewingRef.current = previewing;
  cameraRef.current = camera;
  minZoomRef.current = minZoomForView();
  authoredWidthRef.current = authoredWidth;
  callbacks.current = { onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onMoveObject, onResizeObject, onObjectCommit, onCgShift, onPreviewAbort };
  overlay.current = { highlights, churches, selectedPinId, styleId, hiddenLayers, hillshade, isolate, numberPins };

  useImperativeHandle(ref, () => ({
    jumpTo(next) {
      const map = mapRef.current;
      if (!map) return;
      suppress.current = true;
      map.jumpTo(cameraView(map, next, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current));
      map.once("moveend", () => {
        suppress.current = false;
      });
    },
    easeTo(next, durationMs) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      return new Promise((resolve) => {
        suppress.current = true;
        // MapsTab passes milliseconds (duration * 1000); MapLibre easeTo is ms.
        map.easeTo({ ...cameraView(map, next, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current), duration: Math.max(0, durationMs) });
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
        map.flyTo({ ...cameraView(map, next, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current), duration: Math.max(0, durationMs) });
        map.once("moveend", () => {
          suppress.current = false;
          resolve();
        });
      });
    },
    animateHop({ from, to, durationMs, easing = "ease-in-out", routePoints, curve, flyZoom, easeIn, easeOut, width, fromObjects, toObjects, objectTransition }) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      hopAbort.current = false;
      finishHop();
      return Promise.all([ensureLandmarkImages(map, [...(fromObjects || []), ...(toObjects || [])], assetBaseUrl), Promise.resolve(ensureDropPinImages(map, [...(fromObjects || []), ...(toObjects || [])]))]).then(() => new Promise((resolve) => {
        const apply = (t: number) => {
          const cam = cameraAtHop(from, to, t, {
            easing,
            routePoints,
            curve,
            flyZoom,
            easeIn,
            easeOut,
            duration: durationMs / 1000,
            width,
          });
          if (fromObjects && map.getSource("churches")) {
            const objects = toObjects ? movieObjectsAt(fromObjects, toObjects, t, objectTransition) : fromObjects;
            (map.getSource("churches") as GeoJSONSource).setData(churchesGeo(objects, overlay.current.selectedPinId, overlay.current.numberPins, objectPreviewScale(map, authoredWidthRef.current)));
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
          apply(1);
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
          apply(t);
          if (t < 1) hopRaf.current = requestAnimationFrame(step);
          else finishHop();
        };
        hopRaf.current = requestAnimationFrame(step);
      }));
    },
    stop() {
      hopAbort.current = true;
      finishHop();
      mapRef.current?.stop();
    },
    getCamera() {
      const map = mapRef.current;
      return map ? readCamera(map, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current, cameraRef.current.zoom) : null;
    },
    getCgCamera(cgShiftX) {
      const map = mapRef.current;
      if (!map) return null;
      const current = readCamera(
        map,
        previewZoomDelta(map, authoredWidthRef.current),
        minZoomRef.current,
        cameraRef.current.zoom
      );
      const canvas = map.getCanvas();
      const shifted = map.unproject([
        canvas.clientWidth / 2 + (cgShiftX * canvas.clientWidth) / authoredWidthRef.current,
        canvas.clientHeight / 2,
      ]);
      return { ...current, lat: shifted.lat, lon: wrapLon(shifted.lng) };
    },
    captureBlob() {
      const map = mapRef.current;
      return map ? captureCanvas(map.getCanvas()) : Promise.resolve(null);
    },
    capturePreviewBlob() {
      const map = mapRef.current;
      return map ? captureCanvas(map.getCanvas()) : Promise.resolve(null);
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
      recastPreviewCamera(
        map,
        deltaRef,
        suppress,
        minZoomRef.current,
        cameraRef.current.zoom,
        authoredWidthRef.current
      );
      if (map.getSource("churches")) {
        (map.getSource("churches") as GeoJSONSource).setData(
          churchesGeo(overlay.current.churches, overlay.current.selectedPinId, overlay.current.numberPins, objectPreviewScale(map, authoredWidthRef.current))
        );
      }
    },
  }));

  useEffect(() => {
    if (!host.current) return;
    const hostEl = host.current;
    let cancelled = false;
    let map: MapLibreMap | null = null;
    const recast = () => {
      if (!map) return;
      recastPreviewCamera(
        map,
        deltaRef,
        suppress,
        minZoomRef.current,
        cameraRef.current.zoom,
        authoredWidthRef.current
      );
    };
    const ro = new ResizeObserver(() => recast());
    const onPointerUp = () => {
      if (!map || suppress.current || previewingRef.current) return;
      callbacks.current.onCameraCommit(readCamera(map, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current, cameraRef.current.zoom));
    };

    const onObjPointerDown = (event: PointerEvent) => {
      if (!map || previewingRef.current || event.shiftKey) return;
      const rect = map.getCanvas().getBoundingClientRect();
      const point: [number, number] = [event.clientX - rect.left, event.clientY - rect.top];
      const layers = PIN_LAYERS.filter((id) => map!.getLayer(id));
      const id = String((layers.length ? map.queryRenderedFeatures(point, { layers }) : [])[0]?.properties?.id || "");
      const church = id ? overlay.current.churches.find((c) => c.id === id) : undefined;
      if (!church) return;
      const anchor = map.project([church.lon, church.lat]);
      map.dragPan.disable();
      map.getCanvas().setPointerCapture(event.pointerId);
      objDrag.current = { id, grabDx: point[0] - anchor.x, grabDy: point[1] - anchor.y, pointerId: event.pointerId };
    };

    const onObjPointerMove = (event: PointerEvent) => {
      const drag = objDrag.current;
      if (!map || !drag || drag.pointerId !== event.pointerId) return;
      const rect = map.getCanvas().getBoundingClientRect();
      const lngLat = map.unproject([event.clientX - rect.left - drag.grabDx, event.clientY - rect.top - drag.grabDy]);
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
      const d0 = hostEl.clientWidth ? Math.log2(hostEl.clientWidth / authoredWidthRef.current) : 0;
      void resolveOpenFreeMapStyle(wantedStyle, d0).then((style) => {
        if (cancelled) return;
        if (overlay.current.styleId !== wantedStyle) {
          createMap(overlay.current.styleId);
          return;
        }
        const zMin = minZoomRef.current;
        deltaRef.current = d0;
        map = new MapLibreMap({
          container: hostEl,
          style,
          center: [camera.lon, camera.lat],
          zoom: mapZoomOf(camera.zoom, d0, zMin),
          bearing: camera.bearing,
          pitch: camera.pitch,
          renderWorldCopies: true,
          transformConstrain: (center, zoom) => ({ center, zoom: clampMapZoom(zoom) }),
          doubleClickZoom: false,
          boxZoom: false,
          minZoom: ML_MIN_ZOOM,
          maxZoom: ML_MAX_ZOOM,
          attributionControl: { compact: true },
          transformRequest: (url) => mapsTransformRequest(url),
          canvasContextAttributes: { preserveDrawingBuffer: true },
        });
        mapRef.current = map;
        styleUrl.current = OPENFREEMAP_STYLES[wantedStyle];
        styleIdentity.current = wantedStyle;

        function probeTex() {
          if (!map) return;
          const gl = map.getCanvas().getContext("webgl2") || map.getCanvas().getContext("webgl");
          if (!gl) return;
          const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
          if (typeof max === "number" && max < WALL_W) {
            const message = `GPU MAX_TEXTURE_SIZE is ${max}; 7680 plates will fail.`;
            console.warn(message);
            setTexWarn(message);
          }
        }

        function paintOverlays() {
          if (!map) return;
          const currentMap = map;
          const generation = ++overlayGeneration.current;
          styleReady.current = false;
          ensureLowZoomRaster(currentMap, overlay.current.styleId);
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
            objectPreviewScale(currentMap, authoredWidthRef.current),
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
          callbacks.current.onCameraCommit(readCamera(map, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current, cameraRef.current.zoom));
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
            map?.resize();
            if (map) {
              const zMin = minZoomRef.current;
              const d = applyPreviewZoomLimits(map, zMin, previewZoomDelta(map, authoredWidthRef.current));
              deltaRef.current = d;
              applyBoundaryZoomOffset(map, d);
              suppress.current = true;
              map.jumpTo(cameraView(map, cameraRef.current, d, zMin));
              map.once("moveend", () => {
                suppress.current = false;
              });
              ensureLowZoomRaster(map, overlay.current.styleId);
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
          map?.resize();
          if (map) {
            ensureLowZoomRaster(map, overlay.current.styleId);
            installPatterns(map, stylePatterns(overlay.current.styleId));
            applyLayerFilters(map, overlay.current.hiddenLayers);
            applyHillshade(map, overlay.current.hillshade);
          }
          void loadAdmin0().then(() => {
            if (mapRef.current === map) paintOverlays();
          });
        });
        map.on("moveend", commitCamera);
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
          if (authoredZoomOf(map, previewZoomDelta(map, authoredWidthRef.current), minZoomRef.current) >= COUNTRY_PICK_MAX_ZOOM) return;
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
        ro.observe(hostEl);
      });
    };
    createMap(styleId);

    return () => {
      cancelled = true;
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
    void resolveOpenFreeMapStyle(styleId, previewZoomDelta(map, authoredWidthRef.current)).then((style) => {
      if (mapRef.current !== map || styleIdentity.current !== styleId) return;
      map.setStyle(style, { diff: false });
      map.once("style.load", () => {
        map.resize();
        applyBoundaryZoomOffset(map, previewZoomDelta(map, authoredWidthRef.current));
        ensureLowZoomRaster(map, styleId);
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
      (map.getSource("churches") as GeoJSONSource).setData(churchesGeo(churches, selectedPinId, numberPins, objectPreviewScale(map, authoredWidthRef.current)));
    });
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
    recastPreviewCamera(
      map,
      deltaRef,
      suppress,
      minZoomRef.current,
      cameraRef.current.zoom,
      authoredWidthRef.current
    );
  }, [crop, authoredWidth]);

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
      setHandlePos(null);
      return;
    }
    const recompute = () => {
      const church = overlay.current.churches.find((c) => c.id === selectedPinId);
      if (!church || church.kind !== "landmark") {
        setHandlePos(null);
        return;
      }
      const scale = objectPreviewScale(map, authoredWidthRef.current);
      const size = church.size || 120;
      const width = size * scale;
      const anchor = map.project([church.lon, church.lat]);
      // icon-anchor is "bottom", so the anchor point is the bottom-center of the rendered image.
      setHandlePos({ x: anchor.x + width / 2, y: anchor.y, size });
    };
    recompute();
    map.on("move", recompute);
    map.on("render", recompute);
    return () => {
      map.off("move", recompute);
      map.off("render", recompute);
    };
  }, [selectedPinId, previewing, churches]);

  function onHandlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!handlePos) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    handleDrag.current = { pointerId: event.pointerId, startX: event.clientX, startSize: handlePos.size };
  }

  function onHandlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = handleDrag.current;
    const map = mapRef.current;
    if (!drag || !map || !selectedPinId) return;
    const scale = objectPreviewScale(map, authoredWidthRef.current);
    const size = resizeFromHandle({ x: drag.startX, y: 0 }, { x: event.clientX, y: 0 }, drag.startSize, scale);
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
    const rect = map.getCanvas().getBoundingClientRect();
    const lngLat = map.unproject([event.clientX - rect.left, event.clientY - rect.top]);
    return { lat: lngLat.lat, lon: lngLat.lng };
  }

  function onCgPointerDown(event: React.PointerEvent<HTMLElement>) {
    const map = mapRef.current;
    if (map && !event.shiftKey) {
      const rect = map.getCanvas().getBoundingClientRect();
      const point: [number, number] = [event.clientX - rect.left, event.clientY - rect.top];
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
    const band = event.currentTarget.closest(".maps-map-band");
    const width = band?.clientWidth || 1;
    event.currentTarget.setPointerCapture(event.pointerId);
    cgDrag.current = { x: event.clientX, shift: cgShiftX, width };
  }

  function onCgPointerMove(event: React.PointerEvent<HTMLElement>) {
    const drag = cgDrag.current;
    if (!drag) return;
    const dx = ((event.clientX - drag.x) * authoredWidthRef.current) / drag.width;
    callbacks.current.onCgShift(drag.shift + dx);
  }

  function onCgPointerUp(event: React.PointerEvent<HTMLElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    cgDrag.current = null;
  }

  const wrapWarn = worldCopyWarning(camera.zoom);
  const splitCg = authoredWidth <= CG_W;
  const fullWall = sidePanels && !splitCg;
  const surfaceWidth = splitCg ? CG_W : fullWall ? WALL_W : WALL_W - FW_W * 2;
  const surfaceOrigin = fullWall ? 0 : CG_ORIGIN - CG_W / 2;
  const cgLeft = ((CG_ORIGIN + cgShiftX - surfaceOrigin) / surfaceWidth) * 100;
  const cgWidth = (CG_W / surfaceWidth) * 100;
  const surfaceClass = splitCg ? "surface-cg" : fullWall ? "show-fw" : "center-only";

  return (
    <div
      className={`maps-map-frame ${surfaceClass}`}
      style={{ "--maps-surface-width": surfaceWidth } as React.CSSProperties}
    >
      <div className="maps-map-band">
        <div className="maps-map-host" ref={host} />
        {styleId === "watercolour" && (
          <div className="maps-paper-grain" style={{ backgroundImage: `url(${paperGrainUrl()})` }} />
        )}
        <div className="maps-crop-overlay">
          {splitCg ? (
            <div className="maps-crop-frame cg">
              <span className="maps-crop-cg-label">CG</span>
            </div>
          ) : fullWall ? (
            <div className="maps-crop-frame fw">
              <span className="maps-crop-fw-label">FW</span>
            </div>
          ) : (
            <div className="maps-crop-frame center" style={{ inset: 0 }} />
          )}
          {exportCg && !splitCg && (
            <div
              className="maps-crop-cg"
              style={{ left: `${cgLeft}%`, width: `${cgWidth}%` }}
              onPointerDown={onCgPointerDown}
              onPointerMove={onCgPointerMove}
              onPointerUp={onCgPointerUp}
              onPointerCancel={onCgPointerUp}
            >
              <span className="maps-crop-cg-label">CG</span>
            </div>
          )}
        </div>
        {handlePos && (
          <div
            className="maps-object-handle"
            style={{ left: handlePos.x, top: handlePos.y }}
            onPointerDown={onHandlePointerDown}
            onPointerMove={onHandlePointerMove}
            onPointerUp={onHandlePointerUp}
            onPointerCancel={onHandlePointerUp}
          />
        )}
      </div>
      <div className="maps-nav-margin top" />
      <div className="maps-nav-margin bottom" />
      {wrapWarn && <p className="maps-wrap-warn">{wrapWarn}</p>}
      {texWarn && <p className="maps-tex-warn">{texWarn}</p>}
    </div>
  );
});
