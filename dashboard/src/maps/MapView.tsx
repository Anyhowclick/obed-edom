import "./maplibreWorker";
import { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { MapMouseEvent } from "maplibre-gl";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import { cameraAtHop } from "./captureFly";
import { applyLayerFilters } from "./layers";
import { applyHighlights, ensureAdmin0Highlights, ensureLowZoomRaster, loadAdmin0 } from "./overlays";
import { OPENFREEMAP_STYLES, resolveOpenFreeMapStyle } from "./styles";
import { mapsTransformRequest } from "./tileProxy";
import {
  WORLD_MIN_ZOOM,
  clampZoom,
  wrapLon,
  type MapsCamera,
  type MapsChurch,
  type MapsCropId,
  type MapsEasing,
  type MapsLayerFilterId,
  type MapsRoutePoint,
  type MapsStyleId,
} from "./types";

const WALL_W = 7680;
const FW_W = 1920;
const CG_W = 1920;
const CG_ORIGIN = 2880;
const PIN_LAYERS = ["churches-dots", "churches-drops", "churches-labels"];
const COUNTRY_PICK_MAX_ZOOM = 7;

/** MapLibre zoom is relative to the preview CSS width; cameras are authored for 7680. */
function previewZoomDelta(map: MapLibreMap): number {
  const width = map.getContainer().clientWidth;
  if (!width) return 0;
  return Math.log2(width / WALL_W);
}

function authoredZoomOf(map: MapLibreMap, delta = previewZoomDelta(map)): number {
  return clampZoom(map.getZoom() - delta);
}

function mapZoomOf(authored: number, delta: number): number {
  return clampZoom(authored) + delta;
}

function readCamera(map: MapLibreMap, delta = previewZoomDelta(map)): MapsCamera {
  const center = map.getCenter();
  return {
    lat: center.lat,
    lon: wrapLon(center.lng),
    zoom: authoredZoomOf(map, delta),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

function cameraView(map: MapLibreMap, camera: MapsCamera, delta = previewZoomDelta(map)) {
  return {
    center: [camera.lon, camera.lat] as [number, number],
    zoom: mapZoomOf(camera.zoom, delta),
    bearing: camera.bearing,
    pitch: camera.pitch,
  };
}

function applyPreviewZoomLimits(map: MapLibreMap, delta = previewZoomDelta(map)): number {
  map.setMinZoom(WORLD_MIN_ZOOM + delta);
  map.setMaxZoom(22 + delta);
  return delta;
}

function recastPreviewCamera(
  map: MapLibreMap,
  deltaRef: { current: number },
  suppress: { current: boolean }
) {
  if (!map.getContainer().clientWidth) return;
  const authored = readCamera(map, deltaRef.current);
  map.resize();
  const d = applyPreviewZoomLimits(map);
  deltaRef.current = d;
  suppress.current = true;
  map.jumpTo(cameraView(map, authored, d));
  map.once("moveend", () => {
    suppress.current = false;
  });
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
    flyZoom?: number;
    easeIn?: number;
    easeOut?: number;
  }) => Promise<void>;
  stop: () => void;
  getCamera: () => MapsCamera | null;
  captureBlob: () => Promise<Blob | null>;
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
  cgShiftX: number;
  previewing: boolean;
  selectedPinId: string | null;
  onCameraCommit: (camera: MapsCamera) => void;
  onToggleCountry: (adm0: string) => void;
  onAddPin: (lat: number, lon: number) => void;
  onSelectPin: (id: string | null) => void;
  onEditPin: (id: string) => void;
  onCgShift: (dx: number) => void;
  onPreviewAbort?: () => void;
};

function churchesGeo(churches: MapsChurch[], selectedPinId: string | null, numberPins = false): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: churches.map((church, index) => ({
      type: "Feature",
      properties: {
        id: church.id,
        name: numberPins ? `${index + 1}. ${church.name}` : church.name,
        color: church.color,
        kind: church.kind,
        sel: church.id === selectedPinId,
      },
      geometry: { type: "Point", coordinates: [church.lon, church.lat] },
    })),
  };
}

async function addOverlays(
  map: MapLibreMap,
  highlights: string[],
  churches: MapsChurch[],
  selectedPinId: string | null,
  styleId: MapsStyleId,
  numberPins: boolean
) {
  await ensureAdmin0Highlights(map, highlights, styleId);
  const pins = churchesGeo(churches, selectedPinId, numberPins);
  if (!map.getSource("churches")) {
    map.addSource("churches", { type: "geojson", data: pins, promoteId: "id" });
    map.addLayer({
      id: "churches-dots",
      type: "circle",
      source: "churches",
      paint: {
        "circle-radius": ["case", ["==", ["get", "kind"], "dropPin"], 7, 5],
        "circle-color": ["get", "color"],
        "circle-stroke-width": ["case", ["boolean", ["get", "sel"], false], 3, 1.25],
        "circle-stroke-color": ["case", ["boolean", ["get", "sel"], false], "#B8F64B", "#FFFFFF"],
      },
    });
    map.addLayer({
      id: "churches-drops",
      type: "symbol",
      source: "churches",
      filter: ["==", ["get", "kind"], "dropPin"],
      layout: {
        "text-field": "▼",
        "text-size": 11,
        "text-offset": [0, 0.85],
        "text-anchor": "top",
        "text-allow-overlap": true,
      },
      paint: { "text-color": ["get", "color"], "text-halo-color": "#07070A", "text-halo-width": 1 },
    });
    map.addLayer({
      id: "churches-labels",
      type: "symbol",
      source: "churches",
      layout: {
        "text-field": ["get", "name"],
        "text-size": 12,
        "text-offset": [0, 1.35],
        "text-anchor": "top",
      },
      paint: { "text-color": "#FFFFFF", "text-halo-color": "#07070A", "text-halo-width": 1.2 },
    });
  } else {
    (map.getSource("churches") as GeoJSONSource).setData(pins);
  }
  applyHighlights(map, highlights);
}

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
    cgShiftX,
    previewing,
    selectedPinId,
    onCameraCommit,
    onToggleCountry,
    onAddPin,
    onSelectPin,
    onEditPin,
    onCgShift,
    onPreviewAbort,
  },
  ref
) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const suppress = useRef(false);
  const styleUrl = useRef(OPENFREEMAP_STYLES[styleId]);
  const previewingRef = useRef(previewing);
  const callbacks = useRef({ onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onCgShift, onPreviewAbort });
  const overlay = useRef({ highlights, churches, selectedPinId, styleId, hiddenLayers, numberPins });
  const cgDrag = useRef<{ x: number; shift: number; width: number } | null>(null);
  const hopAbort = useRef(false);
  const hopRaf = useRef(0);
  const hopResolve = useRef<(() => void) | null>(null);
  const deltaRef = useRef(0);
  const cameraRef = useRef(camera);
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
  callbacks.current = { onCameraCommit, onToggleCountry, onAddPin, onSelectPin, onEditPin, onCgShift, onPreviewAbort };
  overlay.current = { highlights, churches, selectedPinId, styleId, hiddenLayers, numberPins };

  useImperativeHandle(ref, () => ({
    jumpTo(next) {
      const map = mapRef.current;
      if (!map) return;
      suppress.current = true;
      map.jumpTo(cameraView(map, next));
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
        map.easeTo({ ...cameraView(map, next), duration: Math.max(0, durationMs) });
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
        map.flyTo({ ...cameraView(map, next), duration: Math.max(0, durationMs) });
        map.once("moveend", () => {
          suppress.current = false;
          resolve();
        });
      });
    },
    animateHop({ from, to, durationMs, easing = "ease-in-out", routePoints, flyZoom, easeIn, easeOut }) {
      const map = mapRef.current;
      if (!map) return Promise.resolve();
      hopAbort.current = false;
      finishHop();
      return new Promise((resolve) => {
        const apply = (t: number) => {
          const cam = cameraAtHop(from, to, t, {
            easing,
            routePoints,
            flyZoom,
            easeIn,
            easeOut,
            duration: durationMs / 1000,
          });
          map.jumpTo({
            center: [cam.lon, cam.lat],
            zoom: mapZoomOf(cam.zoom, deltaRef.current),
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
      });
    },
    stop() {
      hopAbort.current = true;
      finishHop();
      mapRef.current?.stop();
    },
    getCamera() {
      return mapRef.current ? readCamera(mapRef.current) : null;
    },
    captureBlob() {
      const map = mapRef.current;
      if (!map) return Promise.resolve(null);
      return new Promise((resolve) => {
        map.getCanvas().toBlob((blob: Blob | null) => resolve(blob), "image/png");
      });
    },
    resize() {
      const map = mapRef.current;
      if (!map) return;
      recastPreviewCamera(map, deltaRef, suppress);
    },
  }));

  useEffect(() => {
    if (!host.current) return;
    const hostEl = host.current;
    let cancelled = false;
    let map: MapLibreMap | null = null;
    const recast = () => {
      if (!map) return;
      recastPreviewCamera(map, deltaRef, suppress);
    };
    const ro = new ResizeObserver(() => recast());
    const onPointerUp = () => {
      if (!map || suppress.current || previewingRef.current) return;
      callbacks.current.onCameraCommit(readCamera(map));
    };

    void resolveOpenFreeMapStyle(styleId).then((style) => {
      if (cancelled) return;
      const d0 = hostEl.clientWidth ? Math.log2(hostEl.clientWidth / WALL_W) : 0;
      deltaRef.current = d0;
      map = new MapLibreMap({
        container: hostEl,
        style,
        center: [camera.lon, camera.lat],
        zoom: mapZoomOf(camera.zoom, d0),
        bearing: camera.bearing,
        pitch: camera.pitch,
        renderWorldCopies: true,
        doubleClickZoom: false,
        boxZoom: false,
        minZoom: WORLD_MIN_ZOOM + d0,
        maxZoom: 22 + d0,
        attributionControl: { compact: true },
        transformRequest: (url) => mapsTransformRequest(url),
        canvasContextAttributes: { preserveDrawingBuffer: true },
      });
      mapRef.current = map;
      styleUrl.current = OPENFREEMAP_STYLES[styleId];

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
        ensureLowZoomRaster(map, overlay.current.styleId);
        applyLayerFilters(map, overlay.current.hiddenLayers);
        void addOverlays(
          map,
          overlay.current.highlights,
          overlay.current.churches,
          overlay.current.selectedPinId,
          overlay.current.styleId,
          overlay.current.numberPins
        );
      }

      function commitCamera() {
        if (!map || suppress.current || previewingRef.current) return;
        callbacks.current.onCameraCommit(readCamera(map));
      }

      map.on("error", (event) => {
        const message = event.error?.message || "MapLibre error";
        console.warn("maplibre", message);
      });
      map.on("load", () => {
        probeTex();
        map?.resize();
        if (map) {
          const d = applyPreviewZoomLimits(map);
          deltaRef.current = d;
          suppress.current = true;
          map.jumpTo(cameraView(map, cameraRef.current, d));
          map.once("moveend", () => {
            suppress.current = false;
          });
          ensureLowZoomRaster(map, overlay.current.styleId);
          applyLayerFilters(map, overlay.current.hiddenLayers);
        }
        void loadAdmin0().then(() => {
          if (mapRef.current === map) paintOverlays();
        });
      });
      map.on("style.load", () => {
        map?.resize();
        if (map) {
          ensureLowZoomRaster(map, overlay.current.styleId);
          applyLayerFilters(map, overlay.current.hiddenLayers);
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
        if (authoredZoomOf(map) >= COUNTRY_PICK_MAX_ZOOM) return;
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
      ro.observe(hostEl);
    });

    return () => {
      cancelled = true;
      ro.disconnect();
      map?.getCanvas().removeEventListener("pointerup", onPointerUp);
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
    if (styleUrl.current === url) return;
    styleUrl.current = url;
    void resolveOpenFreeMapStyle(styleId).then((style) => {
      if (mapRef.current !== map || styleUrl.current !== url) return;
      map.setStyle(style, { diff: false });
      map.once("style.load", () => {
        map.resize();
        ensureLowZoomRaster(map, styleId);
        applyLayerFilters(map, overlay.current.hiddenLayers);
      });
    });
  }, [styleId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("churches")) return;
    (map.getSource("churches") as GeoJSONSource).setData(churchesGeo(churches, selectedPinId, numberPins));
  }, [churches, selectedPinId, numberPins]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("admin0")) return;
    applyHighlights(map, highlights);
  }, [highlights]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    recastPreviewCamera(map, deltaRef, suppress);
  }, [crop, sidePanels]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyLayerFilters(map, hiddenLayers);
  }, [hiddenLayers]);

  function eventToLngLat(event: { clientX: number; clientY: number }): { lat: number; lon: number } | null {
    const map = mapRef.current;
    if (!map) return null;
    const rect = map.getCanvas().getBoundingClientRect();
    const lngLat = map.unproject([event.clientX - rect.left, event.clientY - rect.top]);
    return { lat: lngLat.lat, lon: lngLat.lng };
  }

  function onCgPointerDown(event: React.PointerEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) {
      const at = eventToLngLat(event);
      if (at) callbacks.current.onAddPin(at.lat, at.lon);
      return;
    }
    const band = event.currentTarget.closest(".maps-export-band");
    const width = band?.clientWidth || 1;
    event.currentTarget.setPointerCapture(event.pointerId);
    cgDrag.current = { x: event.clientX, shift: cgShiftX, width };
  }

  function onCgPointerMove(event: React.PointerEvent<HTMLElement>) {
    const drag = cgDrag.current;
    if (!drag) return;
    const dx = ((event.clientX - drag.x) * WALL_W) / drag.width;
    callbacks.current.onCgShift(drag.shift + dx);
  }

  function onCgPointerUp(event: React.PointerEvent<HTMLElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    cgDrag.current = null;
  }

  const cgLeft = ((CG_ORIGIN + cgShiftX) / WALL_W) * 100;
  const cgWidth = (CG_W / WALL_W) * 100;
  const wing = (FW_W / WALL_W) * 100;

  return (
    <div className={`maps-map-frame ${sidePanels ? "show-fw" : "center-only"}`}>
      <div className="maps-map-host" ref={host} />
      <div className="maps-nav-margin top" />
      <div className="maps-nav-margin bottom" />
      <div className="maps-export-band">
        <div className="maps-crop-overlay">
          {sidePanels ? (
            <div className="maps-crop-frame fw">
              <span className="maps-crop-fw-label">FW</span>
            </div>
          ) : (
            <>
              <div className="maps-crop-wing left" style={{ width: `${wing}%` }} />
              <div className="maps-crop-wing right" style={{ width: `${wing}%` }} />
              <div className="maps-crop-frame center" style={{ left: `${wing}%`, width: `${100 - wing * 2}%` }} />
            </>
          )}
          {exportCg && (
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
      </div>
      {texWarn && <p className="maps-tex-warn">{texWarn}</p>}
    </div>
  );
});
