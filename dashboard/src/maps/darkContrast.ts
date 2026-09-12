import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

const TARGET_PROPS = ["line-color", "text-color"] as const;
const BRIGHTEN_SCALE = 2.6;
const BRIGHTEN_FLOOR = 70;
const EXPRESSION_OPS = ["interpolate", "step", "match", "case", "literal"];

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
  const a = parts[3] !== undefined ? parseFloat(parts[3]) : 1;
  if (kind === "rgb" || kind === "rgba") {
    const [r, g, b] = parts.slice(0, 3).map((p) => parseFloat(p));
    return finite({ r, g, b, a });
  }
  const h = parseFloat(parts[0]);
  const s = parseFloat(parts[1]) / 100;
  const l = parseFloat(parts[2]) / 100;
  const [r, g, b] = hslToRgb(h, s, l);
  return finite({ r, g, b, a });
}

// The floor doubles as the "already bright enough" cutoff: every lifted mean lands at
// or above it, so a second pass always sees mean >= BRIGHTEN_FLOOR and leaves it alone.
function brighten(rgba: Rgba): Rgba {
  const mean = (rgba.r + rgba.g + rgba.b) / 3;
  if (mean >= BRIGHTEN_FLOOR) return rgba;
  if (mean <= 0) return { r: BRIGHTEN_FLOOR, g: BRIGHTEN_FLOOR, b: BRIGHTEN_FLOOR, a: rgba.a };
  const target = Math.min(255, Math.max(mean * BRIGHTEN_SCALE, BRIGHTEN_FLOOR));
  const factor = target / mean;
  const scale = (c: number) => Math.max(0, Math.min(255, Math.round(c * factor)));
  return { r: scale(rgba.r), g: scale(rgba.g), b: scale(rgba.b), a: rgba.a };
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
      return value.map((item, i) => (i === 0 ? item : transformColorValue(item)));
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
