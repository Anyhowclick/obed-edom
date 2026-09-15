import { MercatorCoordinate, type CustomLayerInterface, type Map as MapLibreMap } from "maplibre-gl";
import { planBuildingsInk, type WireFeature } from "./borderlandsFacade";
import {
  buildingLayerActive,
  expandBoundsToPlanZoom,
  inkLayerMode,
  inkRebuildKey,
  shouldReplaceInkMesh,
  type CollectResult,
} from "./borderlandsInkPolicy";
import {
  composeLocalMatrix,
  effectivePixelRatio,
  halfWidthBufferPx,
  inkFullWidthCssPx,
  authoredZoomFromMap,
  INK_COLOR_RGB,
  INK_DEPTH_BIAS,
  matrixAsFloat64,
  type MercatorPoint,
} from "./borderlandsProjection";

export const BORDERLANDS_INK_LAYER_ID = "borderlands-ink";
export { planBuildingFacade, buildingExtents } from "./borderlandsFacade";
export { expandBoundsToPlanZoom, inkFragmentKey, inkLayerMode, inkPlanZoom, inkRebuildKey, shouldReplaceInkMesh } from "./borderlandsInkPolicy";

export type BorderlandsInkContext = {
  authoredZoomDelta: number;
  seamsOnly?: boolean;
};

export type InkDiagnostics = {
  styleGeneration: number;
  sourceRevision: number;
  actualZoom: number;
  authoredZoom: number;
  sourceFeatureCount: number;
  normalizedCount: number;
  duplicatesRemoved: number;
  invalidRings: number;
  slabsOmitted: number;
  selectedPosts: number;
  roofSegments: number;
  totalSegments: number;
  budgetDropped: number;
  rebuildMs: number;
  requestedGeneration: number;
  committedGeneration: number;
  renderedGeneration: number;
  effectivePixelRatio: number;
  signature: string;
};

type Waiter = {
  resolve: () => void;
  reject: (err: Error) => void;
  needed: number;
};

export type InkLayer = CustomLayerInterface & {
  vertexCount: number;
  setEnabled: (enabled: boolean) => void;
  setContext: (context: BorderlandsInkContext) => void;
  refresh: () => void;
  flush: () => void;
  isReadyForCapture: () => boolean;
  requestedGeneration: () => number;
  committedGeneration: () => number;
  renderedGeneration: () => number;
  acknowledgeRender: () => void;
  diagnostics: () => InkDiagnostics;
  waitUntilRendered: (opts?: { isCancelled?: () => boolean; deadlineMs?: number }) => Promise<void>;
};

const VERT = `#version 300 es
uniform mat4 u_matrix;
uniform vec2 u_viewport;
uniform float u_width;
uniform float u_aa;
uniform float u_depthBias;
in vec3 a_start;
in vec3 a_end;
in float a_side;
in float a_endFlag;
out float v_edge;
void main() {
  vec3 pos = mix(a_start, a_end, a_endFlag);
  vec3 other = mix(a_end, a_start, a_endFlag);
  vec4 clip = u_matrix * vec4(pos, 1.0);
  vec4 clipOther = u_matrix * vec4(other, 1.0);
  if (clip.w <= 0.0 && clipOther.w <= 0.0) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    v_edge = 1.0;
    return;
  }
  if (clip.w <= 0.0) {
    float denom = clipOther.w - clip.w;
    float t = denom != 0.0 ? clamp((1e-4 - clip.w) / denom, 0.0, 1.0) : 1.0;
    clip = mix(clip, clipOther, t);
  }
  vec2 ndc = clip.xy / clip.w;
  vec2 ndcOther = clipOther.xy / max(clipOther.w, 1e-4);
  vec2 dir = (ndcOther - ndc) * u_viewport;
  float len = length(dir);
  dir = len > 1e-4 ? dir / len : vec2(1.0, 0.0);
  vec2 n = vec2(-dir.y, dir.x);
  float halfW = u_width + u_aa;
  clip.xy += n * a_side * halfW * 2.0 / u_viewport * clip.w;
  clip.z -= u_depthBias * clip.w;
  v_edge = a_side;
  gl_Position = clip;
}`;

const FRAG = `#version 300 es
precision highp float;
uniform vec3 u_color;
uniform float u_width;
uniform float u_aa;
in float v_edge;
out vec4 fragColor;
void main() {
  float halfW = u_width + u_aa;
  float dist = abs(v_edge) * halfW;
  float alpha = u_aa <= 0.0 ? 1.0 : 1.0 - smoothstep(u_width, halfW, dist);
  fragColor = vec4(u_color * alpha, alpha);
}`;

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.warn("borderlands ink shader", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function mercator(lng: number, lat: number, altitude: number): MercatorPoint {
  const c = MercatorCoordinate.fromLngLat([lng, lat], altitude);
  return { x: c.x, y: c.y, z: c.z };
}

function pushVert(out: number[], a: MercatorPoint, b: MercatorPoint, side: number, endFlag: number): void {
  out.push(a.x, a.y, a.z, b.x, b.y, b.z, side, endFlag);
}

function pushSegment(out: number[], a: MercatorPoint, b: MercatorPoint): void {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  if (dx * dx + dy * dy + dz * dz < 1e-24) return;
  pushVert(out, a, b, -1, 0);
  pushVert(out, a, b, 1, 0);
  pushVert(out, a, b, -1, 1);
  pushVert(out, a, b, 1, 0);
  pushVert(out, a, b, 1, 1);
  pushVert(out, a, b, -1, 1);
}

function layerVisible(map: MapLibreMap, id: string): boolean {
  try {
    return !!map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none";
  } catch {
    return false;
  }
}

function buildingLayerSpec(map: MapLibreMap): { source: string; sourceLayer: string; minzoom?: number; maxzoom?: number; filter?: unknown } | null {
  const layer = map.getStyle()?.layers?.find((item) => item.id === "building-3d") as {
    source?: unknown;
    "source-layer"?: unknown;
    minzoom?: number;
    maxzoom?: number;
    filter?: unknown;
    layout?: { visibility?: unknown };
  } | undefined;
  if (!layer || typeof layer.source !== "string") return null;
  return {
    source: layer.source,
    sourceLayer: typeof layer["source-layer"] === "string" ? layer["source-layer"] : "building",
    minzoom: layer.minzoom,
    maxzoom: layer.maxzoom,
    filter: layer.filter,
  };
}

function buildingsEligible(map: MapLibreMap): boolean {
  const spec = buildingLayerSpec(map);
  return buildingLayerActive({
    hasLayer: !!map.getLayer("building-3d") && !!spec,
    visibility: layerVisible(map, "building-3d") ? "visible" : "none",
    minzoom: spec?.minzoom,
    maxzoom: spec?.maxzoom,
    zoom: map.getZoom(),
  });
}

function collectBuildings(map: MapLibreMap): CollectResult {
  if (!buildingsEligible(map)) return { kind: "unavailable" };
  const spec = buildingLayerSpec(map);
  if (!spec) return { kind: "unavailable" };
  const source = (map as MapLibreMap & { getSource?: (id: string) => { loaded?: () => boolean } | undefined }).getSource?.(spec.source);
  const sourceLoaded = typeof source?.loaded === "function" ? source.loaded() : true;
  try {
    const query = spec.filter
      ? map.querySourceFeatures(spec.source, { sourceLayer: spec.sourceLayer, filter: spec.filter as never })
      : map.querySourceFeatures(spec.source, { sourceLayer: spec.sourceLayer });
    const features: WireFeature[] = query.map((feature) => ({
      id: (feature as { id?: unknown }).id,
      geometry: feature.geometry as WireFeature["geometry"],
      properties: feature.properties || null,
      source: spec.source,
      sourceLayer: spec.sourceLayer,
    }));
    if (!map.areTilesLoaded() || !sourceLoaded) {
      return features.length ? { kind: "ok", features } : { kind: "loading" };
    }
    return { kind: "ok", features };
  } catch {
    return { kind: "error" };
  }
}

function canvasLayoutWidth(map: MapLibreMap): number {
  const canvas = map.getCanvas();
  return canvas.clientWidth || 0;
}

export function createBorderlandsInkLayer(map: MapLibreMap, initialContext: BorderlandsInkContext = { authoredZoomDelta: 0 }): InkLayer {
  let program: WebGLProgram | null = null;
  let vao: WebGLVertexArrayObject | null = null;
  let buffer: WebGLBuffer | null = null;
  let matrixLoc: WebGLUniformLocation | null = null;
  let viewportLoc: WebGLUniformLocation | null = null;
  let widthLoc: WebGLUniformLocation | null = null;
  let aaLoc: WebGLUniformLocation | null = null;
  let depthBiasLoc: WebGLUniformLocation | null = null;
  let colorLoc: WebGLUniformLocation | null = null;
  let startLoc = -1;
  let endLoc = -1;
  let sideLoc = -1;
  let endFlagLoc = -1;
  let verts = new Float32Array(0);
  let origin: MercatorPoint = { x: 0, y: 0, z: 0 };
  let vertexCount = 0;
  let cacheKey = "";
  let dirty = true;
  let ready = false;
  let compileFailed = false;
  let warnedCompile = false;
  let enabled = true;
  let moving = false;
  let cameraDirty = true;
  let sourceDirty = true;
  let sourceRevision = 0;
  let styleGeneration = 1;
  let requestedGen = 0;
  let committedGen = 0;
  let renderedGen = 0;
  let debounce = 0;
  let rebuilding = false;
  let rebuildAgain = false;
  let context = initialContext;
  let lastFeatureCount = 0;
  let lastCollectLng = NaN;
  let lastCollectLat = NaN;
  let lastDiag: InkDiagnostics = {
    styleGeneration: 1,
    sourceRevision: 0,
    actualZoom: 0,
    authoredZoom: 0,
    sourceFeatureCount: 0,
    normalizedCount: 0,
    duplicatesRemoved: 0,
    invalidRings: 0,
    slabsOmitted: 0,
    selectedPosts: 0,
    roofSegments: 0,
    totalSegments: 0,
    budgetDropped: 0,
    rebuildMs: 0,
    requestedGeneration: 0,
    committedGeneration: 0,
    renderedGeneration: 0,
    effectivePixelRatio: 1,
    signature: "",
  };
  const waiters: Waiter[] = [];

  function settleWaiters(): void {
    for (let i = waiters.length - 1; i >= 0; i--) {
      if (renderedGen >= waiters[i].needed) {
        waiters[i].resolve();
        waiters.splice(i, 1);
      }
    }
  }

  function failWaiters(err: Error): void {
    const pending = waiters.splice(0, waiters.length);
    for (const waiter of pending) waiter.reject(err);
  }

  function acknowledgeRender(): void {
    renderedGen = committedGen;
    lastDiag.renderedGeneration = renderedGen;
    settleWaiters();
  }

  function commit(local: number[], nextOrigin: MercatorPoint, signature: string): void {
    origin = nextOrigin;
    verts = new Float32Array(local);
    vertexCount = verts.length / 8;
    layer.vertexCount = vertexCount;
    dirty = true;
    committedGen = requestedGen;
    lastDiag.committedGeneration = committedGen;
    lastDiag.signature = signature;
    map.triggerRepaint();
  }

  function rebuildKey(): string {
    const center = map.getCenter();
    let bounds: { west?: number; south?: number; east?: number; north?: number } = {};
    try {
      const box = map.getBounds();
      bounds = { west: box.getWest(), south: box.getSouth(), east: box.getEast(), north: box.getNorth() };
    } catch {
      bounds = {};
    }
    const canvas = map.getCanvas();
    return inkRebuildKey({
      styleGeneration,
      sourceRevision,
      sourceReady: map.areTilesLoaded(),
      zoom: map.getZoom(),
      lng: center.lng,
      lat: center.lat,
      bearing: map.getBearing(),
      pitch: map.getPitch(),
      viewportW: canvas.clientWidth || 0,
      viewportH: canvas.clientHeight || 0,
      buildingsVisible: enabled && buildingsEligible(map),
      seamsOnly: !!context.seamsOnly,
      ...bounds,
    });
  }

  function rebuild(force = false): void {
    if (rebuilding) {
      rebuildAgain = true;
      return;
    }
    rebuilding = true;
    requestedGen += 1;
    lastDiag.requestedGeneration = requestedGen;
    if (!enabled) {
      cacheKey = rebuildKey();
      cameraDirty = false;
      sourceDirty = false;
      committedGen = requestedGen;
      lastDiag.committedGeneration = committedGen;
      rebuilding = false;
      return;
    }
    if (!buildingsEligible(map)) {
      cacheKey = rebuildKey();
      cameraDirty = false;
      sourceDirty = false;
      commit([], origin, "");
      rebuilding = false;
      return;
    }
    const key = rebuildKey();
    if (!force && key === cacheKey && committedGen > 0) {
      requestedGen = committedGen;
      lastDiag.requestedGeneration = requestedGen;
      rebuilding = false;
      return;
    }
    const collected = collectBuildings(map);
    if (collected.kind !== "ok") {
      requestedGen = Math.max(committedGen, requestedGen - 1);
      lastDiag.requestedGeneration = requestedGen;
      rebuilding = false;
      return;
    }
    if (!shouldReplaceInkMesh(collected, 0, force)) {
      requestedGen = Math.max(committedGen, requestedGen - 1);
      lastDiag.requestedGeneration = requestedGen;
      rebuilding = false;
      return;
    }
    const collectCenter = map.getCenter();
    const sameAnchor =
      Number.isFinite(lastCollectLng) &&
      Math.hypot(collectCenter.lng - lastCollectLng, collectCenter.lat - lastCollectLat) < 1e-4;
    if (
      !force &&
      committedGen > 0 &&
      sameAnchor &&
      collected.features.length < lastFeatureCount * 0.85
    ) {
      requestedGen = committedGen;
      lastDiag.requestedGeneration = requestedGen;
      rebuilding = false;
      return;
    }
    try {
      const started = performance.now();
      let viewBounds: { west: number; south: number; east: number; north: number } | undefined;
      try {
        const box = map.getBounds();
        viewBounds = expandBoundsToPlanZoom(
          { west: box.getWest(), south: box.getSouth(), east: box.getEast(), north: box.getNorth() },
          map.getZoom(),
        );
      } catch {
        viewBounds = undefined;
      }
      const planned = planBuildingsInk(collected.features, {
        bounds: viewBounds,
        padDeg: 0.002,
        seamsOnly: !!context.seamsOnly,
      });
      const center = map.getCenter();
      const nextOrigin = mercator(center.lng, center.lat, 0);
      const local: number[] = [];
      for (const seg of planned.segs) {
        const a = mercator(seg.a[0], seg.a[1], seg.a[2]);
        const b = mercator(seg.b[0], seg.b[1], seg.b[2]);
        pushSegment(local, {
          x: a.x - nextOrigin.x,
          y: a.y - nextOrigin.y,
          z: a.z - nextOrigin.z,
        }, {
          x: b.x - nextOrigin.x,
          y: b.y - nextOrigin.y,
          z: b.z - nextOrigin.z,
        });
      }
      cacheKey = key;
      cameraDirty = false;
      sourceDirty = false;
      lastFeatureCount = collected.features.length;
      lastCollectLng = collectCenter.lng;
      lastCollectLat = collectCenter.lat;
      lastDiag = {
        ...lastDiag,
        ...planned.diagnostics,
        styleGeneration,
        sourceRevision,
        actualZoom: map.getZoom(),
        authoredZoom: authoredZoomFromMap(map.getZoom(), context.authoredZoomDelta),
        rebuildMs: performance.now() - started,
        requestedGeneration: requestedGen,
      };
      commit(local, nextOrigin, planned.signature);
    } finally {
      rebuilding = false;
      if (rebuildAgain) {
        rebuildAgain = false;
        scheduleRebuild(true);
      }
    }
  }

  function scheduleRebuild(force = false): void {
    if (moving && !force) return;
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => rebuild(force), 80);
  }

  const onMoveStart = () => {
    moving = true;
    cameraDirty = true;
    window.clearTimeout(debounce);
    debounce = 0;
  };
  const onMoveEnd = () => {
    moving = false;
    cameraDirty = true;
    scheduleRebuild();
  };
  const onIdle = () => {
    if (moving) return;
    if (cameraDirty || sourceDirty || !cacheKey) scheduleRebuild();
  };
  const onResize = () => {
    cameraDirty = true;
    if (!moving) scheduleRebuild();
  };
  const onSourceData = (event: { dataType?: string; sourceDataType?: string; sourceId?: string }) => {
    if (event.dataType && event.dataType !== "source") return;
    if (event.sourceDataType === "visibility") return;
    const spec = buildingLayerSpec(map);
    if (spec && event.sourceId && event.sourceId !== spec.source) return;
    sourceDirty = true;
    sourceRevision += 1;
    if (!moving) scheduleRebuild();
  };

  const layer: InkLayer = {
    id: BORDERLANDS_INK_LAYER_ID,
    type: "custom",
    renderingMode: "3d",
    vertexCount: 0,
    setEnabled(next) {
      if (enabled === next) return;
      enabled = next;
      if (next) {
        cameraDirty = true;
        scheduleRebuild(true);
      } else {
        window.clearTimeout(debounce);
        committedGen = requestedGen;
        lastDiag.committedGeneration = committedGen;
        map.triggerRepaint();
      }
    },
    setContext(next) {
      const merged: BorderlandsInkContext = {
        authoredZoomDelta: next.authoredZoomDelta ?? context.authoredZoomDelta,
        seamsOnly: next.seamsOnly !== undefined ? next.seamsOnly : context.seamsOnly,
      };
      const meshChanged = !!context.seamsOnly !== !!merged.seamsOnly;
      context = merged;
      if (meshChanged) {
        cameraDirty = true;
        scheduleRebuild(true);
        return;
      }
      map.triggerRepaint();
    },
    refresh() {
      layer.flush();
    },
    flush() {
      window.clearTimeout(debounce);
      moving = false;
      const key = rebuildKey();
      if (key === cacheKey && committedGen > 0 && !cameraDirty && !sourceDirty) {
        requestedGen = committedGen;
        lastDiag.requestedGeneration = requestedGen;
        map.triggerRepaint();
        return;
      }
      rebuild(true);
    },
    isReadyForCapture() {
      return !compileFailed && renderedGen >= requestedGen && committedGen >= requestedGen;
    },
    requestedGeneration: () => requestedGen,
    committedGeneration: () => committedGen,
    renderedGeneration: () => renderedGen,
    acknowledgeRender,
    diagnostics() {
      return { ...lastDiag, renderedGeneration: renderedGen, committedGeneration: committedGen, requestedGeneration: requestedGen };
    },
    waitUntilRendered(opts = {}) {
      if (compileFailed) return Promise.reject(new Error("Borderlands ink could not be rendered."));
      if (renderedGen >= requestedGen) return Promise.resolve();
      const deadlineMs = opts.deadlineMs ?? 45000;
      return new Promise<void>((resolve, reject) => {
        let settled = false;
        const waiter: Waiter = {
          needed: requestedGen,
          resolve: () => finish(),
          reject: (err) => finish(err),
        };
        const finish = (err?: Error) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          window.clearInterval(cancelTimer);
          const at = waiters.indexOf(waiter);
          if (at >= 0) waiters.splice(at, 1);
          if (err) reject(err);
          else resolve();
        };
        const timer = window.setTimeout(() => finish(new Error("Borderlands ink render timed out.")), Math.max(1, deadlineMs));
        const cancelTimer = window.setInterval(() => {
          if (opts.isCancelled?.()) finish(new Error("Export cancelled."));
        }, 50);
        if (opts.isCancelled?.()) {
          finish(new Error("Export cancelled."));
          return;
        }
        waiters.push(waiter);
      });
    },
    onAdd(_map, gl) {
      map.on("movestart", onMoveStart);
      map.on("moveend", onMoveEnd);
      map.on("idle", onIdle);
      map.on("resize", onResize);
      map.on("sourcedata", onSourceData);
      const vs = compile(gl, gl.VERTEX_SHADER, VERT);
      const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
      if (!vs || !fs) {
        compileFailed = true;
        if (!warnedCompile) {
          warnedCompile = true;
          console.warn("borderlands ink: shader compile failed; 3D fill remains");
        }
        return;
      }
      const next = gl.createProgram();
      if (!next) return;
      gl.attachShader(next, vs);
      gl.attachShader(next, fs);
      gl.linkProgram(next);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(next, gl.LINK_STATUS)) {
        compileFailed = true;
        if (!warnedCompile) {
          warnedCompile = true;
          console.warn("borderlands ink program", gl.getProgramInfoLog(next));
        }
        gl.deleteProgram(next);
        return;
      }
      program = next;
      matrixLoc = gl.getUniformLocation(next, "u_matrix");
      viewportLoc = gl.getUniformLocation(next, "u_viewport");
      widthLoc = gl.getUniformLocation(next, "u_width");
      aaLoc = gl.getUniformLocation(next, "u_aa");
      depthBiasLoc = gl.getUniformLocation(next, "u_depthBias");
      colorLoc = gl.getUniformLocation(next, "u_color");
      startLoc = gl.getAttribLocation(next, "a_start");
      endLoc = gl.getAttribLocation(next, "a_end");
      sideLoc = gl.getAttribLocation(next, "a_side");
      endFlagLoc = gl.getAttribLocation(next, "a_endFlag");
      vao = gl.createVertexArray();
      buffer = gl.createBuffer();
      ready = true;
      rebuild();
    },
    onRemove(_map, gl) {
      window.clearTimeout(debounce);
      map.off("movestart", onMoveStart);
      map.off("moveend", onMoveEnd);
      map.off("idle", onIdle);
      map.off("resize", onResize);
      map.off("sourcedata", onSourceData);
      failWaiters(new Error("Borderlands ink layer removed."));
      if (program) gl.deleteProgram(program);
      if (buffer) gl.deleteBuffer(buffer);
      if (vao) gl.deleteVertexArray(vao);
      program = null;
      buffer = null;
      vao = null;
      ready = false;
      cacheKey = "";
      vertexCount = 0;
      layer.vertexCount = 0;
    },
    render(gl, options) {
      if (!enabled) {
        acknowledgeRender();
        return;
      }
      if (!ready || !program || !buffer || !vao || !options) return;
      const matrix = matrixAsFloat64(options.defaultProjectionData?.mainMatrix) || matrixAsFloat64(options.modelViewProjectionMatrix);
      if (!matrix) return;
      if (vertexCount < 4) {
        acknowledgeRender();
        return;
      }

      const prevVao = gl.getParameter(gl.VERTEX_ARRAY_BINDING) as WebGLVertexArrayObject | null;
      const prevProgram = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram | null;
      const prevArrayBuf = gl.getParameter(gl.ARRAY_BUFFER_BINDING) as WebGLBuffer | null;
      const prevDepthTest = gl.isEnabled(gl.DEPTH_TEST);
      const prevBlend = gl.isEnabled(gl.BLEND);
      const prevDepthMask = gl.getParameter(gl.DEPTH_WRITEMASK) as boolean;
      const prevBlendSrcRgb = gl.getParameter(gl.BLEND_SRC_RGB);
      const prevBlendDstRgb = gl.getParameter(gl.BLEND_DST_RGB);
      const prevBlendSrcA = gl.getParameter(gl.BLEND_SRC_ALPHA);
      const prevBlendDstA = gl.getParameter(gl.BLEND_DST_ALPHA);

      gl.useProgram(program);
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      if (dirty) {
        gl.bufferData(gl.ARRAY_BUFFER, verts, gl.DYNAMIC_DRAW);
        dirty = false;
      }
      const stride = 32;
      if (startLoc >= 0) {
        gl.enableVertexAttribArray(startLoc);
        gl.vertexAttribPointer(startLoc, 3, gl.FLOAT, false, stride, 0);
      }
      if (endLoc >= 0) {
        gl.enableVertexAttribArray(endLoc);
        gl.vertexAttribPointer(endLoc, 3, gl.FLOAT, false, stride, 12);
      }
      if (sideLoc >= 0) {
        gl.enableVertexAttribArray(sideLoc);
        gl.vertexAttribPointer(sideLoc, 1, gl.FLOAT, false, stride, 24);
      }
      if (endFlagLoc >= 0) {
        gl.enableVertexAttribArray(endFlagLoc);
        gl.vertexAttribPointer(endFlagLoc, 1, gl.FLOAT, false, stride, 28);
      }
      if (matrixLoc) gl.uniformMatrix4fv(matrixLoc, false, composeLocalMatrix(matrix, origin));
      if (viewportLoc) gl.uniform2f(viewportLoc, gl.drawingBufferWidth, gl.drawingBufferHeight);
      const ratio = effectivePixelRatio(gl.drawingBufferWidth, canvasLayoutWidth(map), map.getPixelRatio?.() || 1);
      const fullCss = inkFullWidthCssPx(authoredZoomFromMap(map.getZoom(), context.authoredZoomDelta));
      if (widthLoc) gl.uniform1f(widthLoc, halfWidthBufferPx(fullCss, ratio));
      if (aaLoc) gl.uniform1f(aaLoc, 0.5);
      if (depthBiasLoc) gl.uniform1f(depthBiasLoc, INK_DEPTH_BIAS);
      if (colorLoc) gl.uniform3f(colorLoc, INK_COLOR_RGB[0], INK_COLOR_RGB[1], INK_COLOR_RGB[2]);
      lastDiag.effectivePixelRatio = ratio;
      gl.enable(gl.DEPTH_TEST);
      gl.depthMask(false);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.drawArrays(gl.TRIANGLES, 0, vertexCount);

      if (prevDepthTest) gl.enable(gl.DEPTH_TEST);
      else gl.disable(gl.DEPTH_TEST);
      gl.depthMask(prevDepthMask);
      if (!prevBlend) gl.disable(gl.BLEND);
      gl.blendFuncSeparate(prevBlendSrcRgb, prevBlendDstRgb, prevBlendSrcA, prevBlendDstA);
      if (prevProgram) gl.useProgram(prevProgram);
      else gl.useProgram(null);
      gl.bindBuffer(gl.ARRAY_BUFFER, prevArrayBuf);
      gl.bindVertexArray(prevVao);
      acknowledgeRender();
    },
  };
  return layer;
}

/** Skip mid-stack road arrows/shields so ink runs after bridges and 3D buildings. */
export function inkBeforeLayerId(layers: Array<{ id: string; type?: string }> | undefined): string | undefined {
  return layers?.find((layer) => layer.type === "symbol" && !/arrow|shield/.test(layer.id))?.id;
}

function inkImplementation(map: MapLibreMap): InkLayer | undefined {
  const wrapped = map.getLayer(BORDERLANDS_INK_LAYER_ID) as { implementation?: InkLayer } | undefined;
  return wrapped?.implementation;
}

export function setBorderlandsInkEnabled(map: MapLibreMap, enabled: boolean): void {
  inkImplementation(map)?.setEnabled(enabled);
}

export function setBorderlandsInkContext(map: MapLibreMap, context: BorderlandsInkContext): void {
  inkImplementation(map)?.setContext(context);
}

export async function waitForBorderlandsInk(
  map: MapLibreMap,
  opts?: (() => boolean) | { isCancelled?: () => boolean; deadlineMs?: number }
): Promise<void> {
  const impl = inkImplementation(map);
  if (!impl) return;
  const options = typeof opts === "function" ? { isCancelled: opts } : opts || {};
  if (options.isCancelled?.()) throw new Error("Export cancelled.");
  impl.flush();
  map.triggerRepaint();
  await impl.waitUntilRendered(options);
}

export function syncBorderlandsInk(map: MapLibreMap, styleId: string, context?: BorderlandsInkContext): void {
  const mode = inkLayerMode(styleId);
  const next: BorderlandsInkContext = {
    authoredZoomDelta: context?.authoredZoomDelta ?? 0,
    seamsOnly: mode === "seams",
  };
  const has = !!map.getLayer(BORDERLANDS_INK_LAYER_ID);
  if (!mode) {
    if (has) map.removeLayer(BORDERLANDS_INK_LAYER_ID);
    return;
  }
  if (has) {
    setBorderlandsInkContext(map, next);
    return;
  }
  if (!map.getStyle()) return;
  try {
    map.addLayer(createBorderlandsInkLayer(map, next), inkBeforeLayerId(map.getStyle()?.layers));
  } catch (err) {
    console.warn("borderlands ink", err);
  }
}
