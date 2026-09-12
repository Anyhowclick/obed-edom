import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

const TARGET_PROPS = ["line-color", "text-color"] as const;
const LIFT = 96;
const KNEE = 160;
const EXPRESSION_OPS = ["interpolate", "step", "match", "case"];

type Rgba = { r: number; g: number; b: number; a: number };

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
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

function parseAlpha(token: string | undefined): number | null {
  if (token === undefined) return 1;
  const a = token.endsWith("%") ? parseFloat(token) / 100 : parseFloat(token);
  return Number.isFinite(a) && a >= 0 && a <= 1 ? a : null;
}

function parseChannel(token: string): number {
  return token.endsWith("%") ? parseFloat(token) * 2.55 : parseFloat(token);
}

function parseColor(value: string): Rgba | null {
  const trimmed = value.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(trimmed);
  if (hex) {
    const digits = hex[1].length === 3 ? hex[1].split("").map((d) => d + d) : [hex[1].slice(0, 2), hex[1].slice(2, 4), hex[1].slice(4, 6)];
    const [r, g, b] = digits.map((d) => parseInt(d, 16));
    return finite({ r, g, b, a: 1 });
  }
  const fn = /^(rgb|rgba|hsl|hsla)\(([^)]+)\)$/i.exec(trimmed);
  if (!fn) return null;
  const kind = fn[1].toLowerCase();
  // CSS Color 4 allows both "r, g, b" and "r g b" with an optional "/ a" alpha.
  const parts = fn[2].split(/[\s,/]+/).filter((part) => part.length > 0);
  if (parts.length < 3) return null;
  const a = parseAlpha(parts[3]);
  if (a === null) return null;
  if (kind === "rgb" || kind === "rgba") {
    const [r, g, b] = parts.slice(0, 3).map(parseChannel);
    return finite({ r, g, b, a });
  }
  const h = parseFloat(parts[0]);
  const s = parseFloat(parts[1]) / 100;
  const l = parseFloat(parts[2]) / 100;
  const [r, g, b] = hslToRgb(h, s, l);
  return finite({ r, g, b, a });
}

/** Continuous, strictly monotone lift: full LIFT at black, tapering linearly to
 * identity at KNEE and above. Applied exactly once, at style load. */
function liftMean(mean: number): number {
  return mean >= KNEE ? mean : mean + LIFT * (1 - mean / KNEE);
}

function brighten(rgba: Rgba): Rgba {
  if (rgba.a === 0) return rgba;
  const mean = (rgba.r + rgba.g + rgba.b) / 3;
  if (mean >= KNEE) return rgba;
  if (mean <= 0) return { r: LIFT, g: LIFT, b: LIFT, a: rgba.a };
  const factor = liftMean(mean) / mean;
  const scale = (c: number) => Math.max(0, Math.min(255, Math.round(c * factor)));
  return { r: scale(rgba.r), g: scale(rgba.g), b: scale(rgba.b), a: rgba.a };
}

function isOutputIndex(op: string, i: number, length: number): boolean {
  const last = length - 1;
  switch (op) {
    // ["interpolate", interpolation, input, stop, output, ...]
    case "interpolate":
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

/** Lifts grey road/rail/boundary/label line-and-text colours toward white with a
 * proportional, luminance-preserving scale; fills and backgrounds are never touched.
 * Only for the Dark style, applied after it is fetched. */
export function withBrighterDarkLines(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
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
