export type PortableStyle = { version: number; sources: Record<string, unknown>; layers: Array<Record<string, unknown>> };
export type PatternImage = { id: string; image: ImageData; options?: { pixelRatio?: number } };
export type PatternHost = { hasImage(id: string): boolean; addImage(id: string, image: ImageData, options?: object): void };
export type ScribbleSpec = { id: string; colour: string; angles: number[]; count: number; length: number; width: number; alpha: number; seed: number; size?: number };
export type ScribbleStroke = { x: number; y: number; angle: number; length: number; width: number; alpha: number; bend: number };

export function tonerPatterns(size = 32): PatternImage[] {
  const make = (id: string, draw: (ctx: CanvasRenderingContext2D) => void): PatternImage => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    ctx.clearRect(0, 0, size, size);
    ctx.strokeStyle = "rgba(20,20,20,.22)";
    ctx.fillStyle = "rgba(20,20,20,.18)";
    ctx.lineWidth = 1;
    draw(ctx);
    return { id, image: ctx.getImageData(0, 0, size, size) };
  };
  return [
    make("dash-t", (ctx) => { for (let i = -size; i < size * 2; i += 8) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i - size, size); ctx.stroke(); } }),
    make("dots-t", (ctx) => { for (let y = 4; y < size; y += 8) for (let x = 4; x < size; x += 8) { ctx.beginPath(); ctx.arc(x, y, 1, 0, Math.PI * 2); ctx.fill(); } }),
    make("cross-t", (ctx) => { for (let i = -size; i < size * 2; i += 8) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i - size, size); ctx.moveTo(i - size, 0); ctx.lineTo(i, size); ctx.stroke(); } }),
    make("hatch-t", (ctx) => { for (let i = -size; i < size * 2; i += 8) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i - size, size); ctx.stroke(); } }),
  ];
}

function scaledWidth(value: unknown, scale: number): unknown {
  if (typeof value === "number") return value * scale;
  if (!Array.isArray(value) || (value[0] !== "interpolate" && value[0] !== "step")) return value;
  const next = [...value];
  const firstOutput = value[0] === "interpolate" ? 4 : 2;
  for (let index = firstOutput; index < next.length; index += 2) {
    if (typeof next[index] === "number") next[index] = next[index] * scale;
  }
  return next;
}

function withScaledWidth(paint: Record<string, unknown>, scale: number): Record<string, unknown> {
  const width = scaledWidth(paint["line-width"], scale);
  return width === undefined ? paint : { ...paint, "line-width": width };
}

function withoutPattern(paint: Record<string, unknown>): Record<string, unknown> {
  const next = { ...paint };
  delete next["background-pattern"];
  delete next["fill-pattern"];
  return next;
}

function mulberry(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randn(rand: () => number): number {
  const u = 1 - rand();
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function field(n: number, rand: () => number): Float32Array {
  const f = new Float32Array(n * n);
  for (let i = 0; i < f.length; i++) f[i] = randn(rand);
  return f;
}

function blurWrap(src: Float32Array, n: number, radius: number, passes = 1): Float32Array {
  let cur = src;
  for (let pass = 0; pass < passes; pass++) {
    const tmp = new Float32Array(n * n);
    const out = new Float32Array(n * n);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        let sum = 0;
        for (let k = -radius; k <= radius; k++) sum += cur[y * n + ((x + k + n) % n)];
        tmp[y * n + x] = sum / (2 * radius + 1);
      }
    }
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        let sum = 0;
        for (let k = -radius; k <= radius; k++) sum += tmp[((y + k + n) % n) * n + x];
        out[y * n + x] = sum / (2 * radius + 1);
      }
    }
    cur = out;
  }
  return cur;
}

function normalise(values: Float32Array): Float32Array {
  let mean = 0;
  for (const value of values) mean += value;
  mean /= values.length;
  let variance = 0;
  for (const value of values) variance += (value - mean) * (value - mean);
  const sd = Math.sqrt(variance / values.length) + 1e-6;
  const out = new Float32Array(values.length);
  for (let i = 0; i < values.length; i++) out[i] = (values[i] - mean) / sd;
  return out;
}

/** Paper grain carries only tooth/fibre, as a multiply layer over the map background. */
export function paperGrainPixels(size = 1024, seed = 7): Uint8ClampedArray<ArrayBuffer> {
  const rand = mulberry(seed);
  const fibre = normalise(blurWrap(field(size, rand), size, 1));
  const tooth = normalise(field(size, rand));
  const pixels = new Uint8ClampedArray(size * size * 4);
  for (let i = 0; i < size * size; i++) {
    const h = 0.6 * fibre[i] + 0.4 * tooth[i];
    const v = 255 * (0.985 + 0.02 * h);
    pixels[i * 4] = v;
    pixels[i * 4 + 1] = v;
    pixels[i * 4 + 2] = v;
    pixels[i * 4 + 3] = 255;
  }
  return pixels;
}

let paperGrainCache: HTMLCanvasElement | null = null;

export function paperGrainCanvas(): HTMLCanvasElement {
  if (paperGrainCache) return paperGrainCache;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1024;
  canvas.getContext("2d")!.putImageData(new ImageData(paperGrainPixels(1024, 7), 1024, 1024), 0, 0);
  paperGrainCache = canvas;
  return canvas;
}

let paperGrainUrlCache: string | null = null;

export function paperGrainUrl(): string {
  if (!paperGrainUrlCache) paperGrainUrlCache = paperGrainCanvas().toDataURL();
  return paperGrainUrlCache;
}

/**
 * Preview counterpart to compositePaperGrain's 1024-authored-px tile. Every export path (full wall,
 * centre-only, CG crop) composites the pattern fresh onto its own output canvas starting at that
 * canvas's local (0,0) — the export never phases the tile by an authored-space origin. The preview
 * band matches by scaling the tile to previewWidth/authoredWidth and always anchoring it at the
 * band's own local (0,0), never at an authored offset like CG_ORIGIN.
 */
export function paperGrainCss(previewWidth: number, authoredWidth: number): { backgroundSize: string; backgroundPosition: string } {
  const ratio = authoredWidth > 0 ? previewWidth / authoredWidth : 1;
  const tile = 1024 * ratio;
  return { backgroundSize: `${tile}px ${tile}px`, backgroundPosition: "0px 0px" };
}

/** Restores globalCompositeOperation: stampOsm.ts reuses one scratch canvas and must paint the attribution bar normally afterwards. */
export function compositePaperGrain(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  const pattern = ctx.createPattern(paperGrainCanvas(), "repeat");
  if (!pattern) return;
  const previous = ctx.globalCompositeOperation;
  ctx.globalCompositeOperation = "multiply";
  ctx.fillStyle = pattern;
  ctx.fillRect(0, 0, width, height);
  ctx.globalCompositeOperation = previous;
}

/** Pencil scribble strokes: patchy via a wrapped low-frequency field, seeded so a spec always yields the same strokes. */
export function scribbleStrokes(spec: ScribbleSpec): ScribbleStroke[] {
  const { angles, count, length, width, alpha, seed, size = 512 } = spec;
  const rand = mulberry(seed);
  const n = 128;
  const patch = normalise(blurWrap(field(n, rand), n, 10, 2));
  const strokes: ScribbleStroke[] = [];
  for (let i = 0; i < count; i++) {
    const x = rand() * size;
    const y = rand() * size;
    const p = Math.max(0, Math.min(1, patch[((y * n) / size | 0) * n + (((x * n) / size) | 0)] * 0.25 + 0.8));
    if (rand() > p) continue;
    const angle = angles[(rand() * angles.length) | 0] + (rand() - 0.5) * 0.12;
    const strokeLength = length * (0.6 + 0.8 * rand());
    const bend = (rand() - 0.5) * 3;
    const strokeWidth = width * (0.7 + 0.6 * rand());
    const strokeAlpha = alpha * (0.5 + 0.9 * rand()) * (0.4 + 0.6 * p);
    strokes.push({ x, y, angle, length: strokeLength, width: strokeWidth, alpha: strokeAlpha, bend });
  }
  return strokes;
}

/** Draws each stroke at the nine wrap offsets so the tile repeats seamlessly; a stroke whose bounding box misses a given offset is skipped (output-identical, since it would render nothing). */
function scribbleImage(spec: ScribbleSpec): PatternImage {
  const { id, colour, size = 512 } = spec;
  const strokes = scribbleStrokes(spec);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.strokeStyle = colour;
  ctx.lineCap = "round";
  for (const stroke of strokes) {
    const { x, y, angle, length, width, alpha, bend } = stroke;
    const margin = length + width;
    const dx = (Math.cos(angle) * length) / 2;
    const dy = (Math.sin(angle) * length) / 2;
    ctx.lineWidth = width;
    ctx.globalAlpha = alpha;
    for (const ox of [-size, 0, size]) {
      if (x + ox + margin <= 0 || x + ox - margin >= size) continue;
      for (const oy of [-size, 0, size]) {
        if (y + oy + margin <= 0 || y + oy - margin >= size) continue;
        ctx.beginPath();
        ctx.moveTo(x + ox - dx, y + oy - dy);
        ctx.quadraticCurveTo(x + ox - dy * 0.1 * bend, y + oy + dx * 0.1 * bend, x + ox + dx, y + oy + dy);
        ctx.stroke();
      }
    }
  }
  return { id, image: ctx.getImageData(0, 0, size, size), options: { pixelRatio: 2 } };
}

const deg = (d: number) => (d * Math.PI) / 180;

export function watercolourPatterns(): PatternImage[] {
  return [
    scribbleImage({ id: "scribble-water", colour: "#3d86bd", angles: [deg(-26), deg(-14)], count: 1500, length: 70, width: 1.4, alpha: 0.42, seed: 11 }),
    scribbleImage({ id: "scribble-park", colour: "#7fa24a", angles: [deg(-26), deg(-20)], count: 600, length: 60, width: 1.3, alpha: 0.3, seed: 12 }),
    scribbleImage({ id: "scribble-wood", colour: "#6f9740", angles: [deg(-24), deg(-16)], count: 900, length: 55, width: 1.3, alpha: 0.32, seed: 13 }),
  ];
}

export const WATERCOLOUR_PATTERN_IDS = ["scribble-water", "scribble-park", "scribble-wood"] as const;

const patternCache = new Map<string, PatternImage[]>();

export function stylePatterns(styleId: string): PatternImage[] {
  const key = styleId.startsWith("toner") ? "toner" : styleId === "watercolour" ? "watercolour" : null;
  if (!key) return [];
  let cached = patternCache.get(key);
  if (!cached) {
    cached = key === "toner" ? tonerPatterns() : watercolourPatterns();
    patternCache.set(key, cached);
  }
  return cached;
}

export function installPatternById(host: PatternHost, styleId: string, imageId: string): void {
  const pattern = stylePatterns(styleId).find((candidate) => candidate.id === imageId);
  if (pattern && !host.hasImage(imageId)) host.addImage(pattern.id, pattern.image, pattern.options);
}

const PAPER = "#F5E8C9";
const WATER_FILL = "#DCEDF1";
const COAST = "rgba(70,95,115,0.55)";
const ICE = "#EEF1F2";
const PARK_FILL = "#E7EBCF";
const WOOD_FILL = "#E3E8C6";
const BUILDING = "#EAD8BE";
const EDGE = "rgba(110,85,65,0.45)";
const RESIDENTIAL = "#F0E2CC";
const AEROWAY_FILL = "#E9DCC6";
const PENCIL = "#5e4f43";
const BOUNDARY = "#8C7A6B";
const WATERWAY = "#3d86bd";
const RAIL = "#9E968B";
const PIER_PATH = "#BCA996";
const AEROWAY_LINE = "#D9C9AE";

const ROAD_OPACITY = [
  "interpolate", ["linear"], ["zoom"],
  10, ["match", ["get", "class"], ["motorway", "trunk", "primary"], 0.75, ["secondary", "tertiary"], 0.3, 0],
  13, ["match", ["get", "class"], ["motorway", "trunk", "primary"], 0.8, ["secondary", "tertiary"], 0.65, 0.12],
  15.5, ["match", ["get", "class"], ["motorway", "trunk", "primary", "secondary", "tertiary"], 0.8, 0.55],
];
const PATH_OPACITY = ["interpolate", ["linear"], ["zoom"], 13, 0, 15, 0.45];
const ROAD_COLOUR = [
  "match", ["get", "class"],
  "motorway", "#C8834A", "trunk", "#C8834A", "primary", "#C8834A",
  "secondary", "#D3A863", "tertiary", "#D3A863",
  "minor", "#CFBA92", "service", "#C9BAA2", "#CFBA92",
];

function isWaterFill(layer: Record<string, unknown>): boolean {
  return layer.type === "fill" && layer["source-layer"] === "water";
}

/** Moves land fills above the first water fill so `withHillshade`'s relief (spliced right before that water fill) is not occluded by opaque land. */
function liftLandFills(layers: Array<Record<string, unknown>>, landIds: Set<string>): Array<Record<string, unknown>> {
  const waterAt = layers.findIndex(isWaterFill);
  if (waterAt < 0) return layers;
  const before = layers.slice(0, waterAt);
  const after = layers.slice(waterAt);
  const land = after.filter((layer) => landIds.has(String(layer.id)));
  if (land.length === 0) return layers;
  const rest = after.filter((layer) => !landIds.has(String(layer.id)));
  return [...before, ...land, ...rest];
}

export function buildWatercolourStyle(base: PortableStyle, options: { sourceUrl?: string; glyphsUrl?: string } = {}): { style: PortableStyle } {
  const style = structuredClone(base);
  if (options.sourceUrl) {
    for (const source of Object.values(style.sources)) {
      if (source && typeof source === "object" && (source as { type?: unknown }).type === "vector") {
        const vector = source as { url?: string; tiles?: unknown };
        vector.url = options.sourceUrl;
        delete vector.tiles;
      }
    }
  }
  if (options.glyphsUrl) (style as PortableStyle & { glyphs?: string }).glyphs = options.glyphsUrl;
  const landIds = new Set<string>();
  const out: Array<Record<string, unknown>> = [];
  for (const layer of style.layers) {
    const next = structuredClone(layer);
    const originalPaint = (next.paint || {}) as Record<string, unknown>;
    const paint = withoutPattern(originalPaint);
    if (paint !== originalPaint && ("background-pattern" in originalPaint || "fill-pattern" in originalPaint)) next.paint = paint;
    const layerId = String(next.id || "");
    const sourceLayer = String(next["source-layer"] || "");
    const key = `${sourceLayer} ${layerId}`;
    if (next.type === "background") {
      next.paint = { ...paint, "background-color": PAPER };
    } else if (next.type === "fill" && (sourceLayer === "water" || /(^|[-_])water/.test(layerId))) {
      next.paint = { ...paint, "fill-color": WATER_FILL, "fill-opacity": 1, "fill-outline-color": COAST };
      out.push(next);
      out.push({ ...structuredClone(layer), id: `${layerId}-scribble`, paint: { "fill-pattern": "scribble-water", "fill-opacity": 0.95 } });
      continue;
    } else if (next.type === "fill" && /ice|glacier/.test(key)) {
      next.paint = { ...paint, "fill-color": ICE, "fill-opacity": 1 };
      landIds.add(layerId);
    } else if (next.type === "fill" && /park/.test(key)) {
      next.paint = { ...paint, "fill-color": PARK_FILL, "fill-opacity": 1 };
      landIds.add(layerId);
      out.push(next);
      const twinId = `${layerId}-scribble`;
      landIds.add(twinId);
      out.push({ ...structuredClone(layer), id: twinId, paint: { "fill-pattern": "scribble-park", "fill-opacity": 0.9 } });
      continue;
    } else if (next.type === "fill" && /wood/.test(key)) {
      next.paint = { ...paint, "fill-color": WOOD_FILL, "fill-opacity": 1 };
      landIds.add(layerId);
      out.push(next);
      const twinId = `${layerId}-scribble`;
      landIds.add(twinId);
      out.push({ ...structuredClone(layer), id: twinId, paint: { "fill-pattern": "scribble-wood", "fill-opacity": 0.9 } });
      continue;
    } else if (next.type === "fill" && /building/.test(key)) {
      next.paint = { ...paint, "fill-color": BUILDING, "fill-opacity": 0.9, "fill-outline-color": EDGE };
    } else if (next.type === "fill" && /residential/.test(key)) {
      next.paint = { ...paint, "fill-color": RESIDENTIAL, "fill-opacity": 1 };
      landIds.add(layerId);
    } else if (next.type === "fill" && /aeroway|pier/.test(key)) {
      next.paint = { ...paint, "fill-color": AEROWAY_FILL, "fill-opacity": 1 };
    } else if (next.type === "fill" && sourceLayer.includes("land")) {
      next.paint = { ...paint, "fill-color": PAPER, "fill-opacity": 1 };
      landIds.add(layerId);
    } else if (next.type === "line") {
      if (/boundary/.test(key)) {
        next.paint = { ...paint, "line-color": BOUNDARY, "line-opacity": 0.55, "line-dasharray": [3, 2] };
      } else if (/waterway/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 0.75), "line-color": WATERWAY, "line-opacity": 0.6 };
      } else if (/rail/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 0.7), "line-color": RAIL, "line-opacity": 0.6 };
      } else if (/pier|path/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 0.65), "line-color": PIER_PATH, "line-opacity": PATH_OPACITY };
      } else if (/aeroway/.test(key)) {
        next.paint = { ...withScaledWidth(paint, 0.7), "line-color": AEROWAY_LINE, "line-opacity": 0.8 };
      } else if (sourceLayer === "transportation") {
        if (/casing|outline/.test(layerId)) continue;
        next.paint = { ...withScaledWidth(paint, 0.5), "line-color": ROAD_COLOUR, "line-opacity": ROAD_OPACITY, "line-blur": 0.3 };
      }
    } else if (next.type === "symbol") {
      next.paint = { ...paint, "text-color": PENCIL, "text-halo-color": PAPER, "text-halo-width": 1.2 };
    }
    out.push(next);
  }
  style.layers = liftLandFills(out, landIds);
  return { style };
}

export function installPatterns(map: PatternHost, patterns: PatternImage[]): void {
  for (const pattern of patterns) if (!map.hasImage(pattern.id)) map.addImage(pattern.id, pattern.image, pattern.options);
}
