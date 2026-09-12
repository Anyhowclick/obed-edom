import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

const TARGET_PROPS = ["line-color", "text-color", "fill-outline-color"] as const;
const LUMINANCE_THRESHOLD = 140;
const BRIGHTEN_FACTOR = 0.6;

type Rgba = { r: number; g: number; b: number; a: number };

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r1, g1, b1] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [Math.round((r1 + m) * 255), Math.round((g1 + m) * 255), Math.round((b1 + m) * 255)];
}

function parseColor(value: string): Rgba | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim());
  if (hex) {
    const digits = hex[1].length === 3 ? hex[1].split("").map((d) => d + d) : [hex[1].slice(0, 2), hex[1].slice(2, 4), hex[1].slice(4, 6)];
    const [r, g, b] = digits.map((d) => parseInt(d, 16));
    return { r, g, b, a: 1 };
  }
  const fn = /^(rgb|rgba|hsl|hsla)\(([^)]+)\)$/i.exec(value.trim());
  if (!fn) return null;
  const kind = fn[1].toLowerCase();
  const parts = fn[2].split(",").map((part) => part.trim());
  const a = parts[3] !== undefined ? parseFloat(parts[3]) : 1;
  if (kind === "rgb" || kind === "rgba") {
    const [r, g, b] = parts.slice(0, 3).map((p) => parseFloat(p));
    return { r, g, b, a };
  }
  const [h, s, l] = [parseFloat(parts[0]), parseFloat(parts[1]) / 100, parseFloat(parts[2]) / 100];
  const [r, g, b] = hslToRgb(h, s, l);
  return { r, g, b, a };
}

function brighten(channel: number): number {
  return Math.round(channel + (255 - channel) * BRIGHTEN_FACTOR);
}

function maybeBrighten(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const parsed = parseColor(value);
  if (!parsed) return value;
  if ((parsed.r + parsed.g + parsed.b) / 3 >= LUMINANCE_THRESHOLD) return value;
  return `rgba(${brighten(parsed.r)},${brighten(parsed.g)},${brighten(parsed.b)},${parsed.a})`;
}

/** Lifts grey road/rail/boundary/label line-and-text colours toward white; fills and
 * backgrounds are never touched. Only for the Dark style, applied after it is fetched. */
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
        const brightened = maybeBrighten(paint[prop]);
        if (brightened !== paint[prop]) {
          nextPaint[prop] = brightened;
          changed = true;
        }
      }
      return changed ? ({ ...layer, paint: nextPaint } as LayerSpecification) : layer;
    }),
  };
}
