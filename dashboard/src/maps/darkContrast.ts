import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

const TARGET_PROPS = ["line-color", "text-color"] as const;
const LIFT = 96;
const KNEE = 160;
export const DARK_CONTRAST_KEY = "obed-edom:darkContrast";
export const DARK_CONTRAST_VERSION = 1;
const EXPRESSION_OPS = ["interpolate", "interpolate-hcl", "interpolate-lab", "step", "match", "case"];

type Rgba = { r: number; g: number; b: number; a: number };

function hslToRgb(hue: number, s: number, l: number): [number, number, number] {
  const h = ((hue % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r1, g1, b1] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [Math.round((r1 + m) * 255), Math.round((g1 + m) * 255), Math.round((b1 + m) * 255)];
}

function finite(rgba: Rgba): Rgba | null {
  return Number.isFinite(rgba.r) && Number.isFinite(rgba.g) && Number.isFinite(rgba.b) && Number.isFinite(rgba.a) ? rgba : null;
}

const NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;
const PERCENT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?%$/i;

function parseAlpha(token: string | undefined): number | null {
  if (token === undefined) return 1;
  let a: number;
  if (PERCENT.test(token)) a = parseFloat(token) / 100;
  else if (NUMBER.test(token)) a = parseFloat(token);
  else return null;
  return a >= 0 && a <= 1 ? a : null;
}

function parseChannel(token: string): number {
  if (PERCENT.test(token)) return parseFloat(token) * 2.55;
  if (NUMBER.test(token)) return parseFloat(token);
  return NaN;
}

/** CSS Color 4 allows "r, g, b[, a]" and "r g b[ / a]", but not a mix of the two. */
function splitArgs(body: string): string[] | null {
  const trimmed = body.trim();
  if (trimmed.includes(",")) {
    if (trimmed.includes("/")) return null;
    const parts = trimmed.split(",").map((part) => part.trim());
    return parts.every((part) => part.length > 0) ? parts : null;
  }
  const sides = trimmed.split("/");
  if (sides.length > 2) return null;
  const parts = sides[0].trim().split(/\s+/).filter((part) => part.length > 0);
  if (parts.length !== 3) return null;
  if (sides.length === 2) {
    const alpha = sides[1].trim().split(/\s+/).filter((part) => part.length > 0);
    if (alpha.length !== 1) return null;
    parts.push(alpha[0]);
  }
  return parts;
}

function parseColor(value: string): Rgba | null {
  const trimmed = value.trim();
  const hex = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(trimmed);
  if (hex) {
    const short = hex[1].length <= 4;
    const pairs = short ? hex[1].split("").map((d) => d + d) : (hex[1].match(/../g) as string[]);
    const [r, g, b] = pairs.slice(0, 3).map((d) => parseInt(d, 16));
    const a = pairs.length === 4 ? parseInt(pairs[3], 16) / 255 : 1;
    return finite({ r, g, b, a });
  }
  const fn = /^(rgb|rgba|hsl|hsla)\(([^)]+)\)$/i.exec(trimmed);
  if (!fn) return null;
  const kind = fn[1].toLowerCase();
  const parts = splitArgs(fn[2]);
  if (!parts || (parts.length !== 3 && parts.length !== 4)) return null;
  const a = parseAlpha(parts[3]);
  if (a === null) return null;
  if (kind === "rgb" || kind === "rgba") {
    const [r, g, b] = parts.slice(0, 3).map(parseChannel);
    return finite({ r, g, b, a });
  }
  if (!NUMBER.test(parts[0]) || !PERCENT.test(parts[1]) || !PERCENT.test(parts[2])) return null;
  const [r, g, b] = hslToRgb(parseFloat(parts[0]), parseFloat(parts[1]) / 100, parseFloat(parts[2]) / 100);
  return finite({ r, g, b, a });
}

/** Continuous, strictly monotone lift: full LIFT at black, tapering linearly to
 * identity at KNEE and above. Not idempotent, so the caller is guarded by a stamp. */
function liftMean(mean: number): number {
  return mean >= KNEE ? mean : mean + LIFT * (1 - mean / KNEE);
}

function brighten(rgba: Rgba): Rgba {
  if (rgba.a === 0) return rgba;
  const mean = (rgba.r + rgba.g + rgba.b) / 3;
  if (mean >= KNEE) return rgba;
  const delta = liftMean(mean) - mean;
  const shift = (c: number) => Math.max(0, Math.min(255, Math.round(c + delta)));
  return { r: shift(rgba.r), g: shift(rgba.g), b: shift(rgba.b), a: rgba.a };
}

function isOutputIndex(op: string, i: number, length: number): boolean {
  const last = length - 1;
  switch (op) {
    // ["interpolate", interpolation, input, stop, output, ...]
    case "interpolate":
    case "interpolate-hcl":
    case "interpolate-lab":
      return i >= 4 && i % 2 === 0;
    // ["step", input, default, stop, output, ...]
    case "step":
      return i >= 2 && i % 2 === 0;
    // ["match", input, label, output, ..., fallback]
    case "match":
      return (i >= 3 && i % 2 === 1) || i === last;
    // ["case", condition, output, ..., fallback]
    case "case":
      return (i >= 2 && i % 2 === 0) || i === last;
    default:
      return false;
  }
}

function transformColorValue(value: unknown): unknown {
  if (typeof value === "string") {
    const parsed = parseColor(value);
    if (!parsed) return value;
    const lifted = brighten(parsed);
    if (lifted.r === parsed.r && lifted.g === parsed.g && lifted.b === parsed.b && lifted.a === parsed.a) return value;
    return `rgba(${lifted.r},${lifted.g},${lifted.b},${lifted.a})`;
  }
  if (Array.isArray(value)) {
    const op = value[0];
    if (typeof op === "string" && EXPRESSION_OPS.includes(op)) {
      let changed = false;
      const next = value.map((item, i) => {
        if (!isOutputIndex(op, i, value.length)) return item;
        const transformed = transformColorValue(item);
        if (transformed !== item) changed = true;
        return transformed;
      });
      return changed ? next : value;
    }
  }
  return value;
}

/** Lifts grey road/rail/boundary/label line-and-text colours toward white with an
 * additive, chroma-preserving offset; fills and backgrounds are never touched.
 * Only for the Dark style, applied after it is fetched. Stamped, so a second pass is a no-op. */
export function withBrighterDarkLines(style: StyleSpecification): StyleSpecification {
  const metadata = (style.metadata ?? {}) as Record<string, unknown>;
  if (metadata[DARK_CONTRAST_KEY] === DARK_CONTRAST_VERSION) return style;
  return {
    ...style,
    metadata: { ...metadata, [DARK_CONTRAST_KEY]: DARK_CONTRAST_VERSION },
    layers: style.layers.map((layer): LayerSpecification => {
      const paint = (layer as { paint?: Record<string, unknown> }).paint;
      if (!paint) return layer;
      let changed = false;
      const nextPaint = { ...paint };
      for (const prop of TARGET_PROPS) {
        if (!(prop in paint)) continue;
        const brightened = transformColorValue(paint[prop]);
        if (brightened !== paint[prop]) {
          nextPaint[prop] = brightened;
          changed = true;
        }
      }
      return changed ? ({ ...layer, paint: nextPaint } as LayerSpecification) : layer;
    }),
  };
}
