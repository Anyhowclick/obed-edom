export const DEFAULT_HIGHLIGHT_COLOUR = "#e8772a";
/** Sentinel stored in `highlightColours` when a highlight keeps isolate/selection but paints no fill. */
export const HIGHLIGHT_NO_FILL = "none";

const HIGHLIGHT_CODE = /^(?:[A-Z]{3}|A1:[A-Z0-9+?_-]{1,16})$/;
const HEX_COLOUR = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

export function normaliseHighlightColour(value: unknown): string {
  if (typeof value !== "string") return DEFAULT_HIGHLIGHT_COLOUR;
  const trimmed = value.trim();
  const hex = trimmed.startsWith("#") ? trimmed.slice(1) : trimmed;
  if (/^[0-9a-fA-F]{6}$/.test(hex)) return `#${hex.toLowerCase()}`;
  if (/^[0-9a-fA-F]{3}$/.test(hex)) {
    const expanded = hex
      .split("")
      .map((c) => c + c)
      .join("");
    return `#${expanded.toLowerCase()}`;
  }
  return DEFAULT_HIGHLIGHT_COLOUR;
}

export function highlightCssVars(hex: string): Record<string, string> {
  const normalised = normaliseHighlightColour(hex);
  const r = parseInt(normalised.slice(1, 3), 16);
  const g = parseInt(normalised.slice(3, 5), 16);
  const b = parseInt(normalised.slice(5, 7), 16);
  return {
    "--maps-highlight": normalised,
    "--maps-highlight-soft": `rgba(${r},${g},${b},0.16)`,
    "--maps-highlight-edge": `rgba(${r},${g},${b},0.45)`,
    "--maps-highlight-ink": contrastInk(normalised),
  };
}

/** Ink that stays readable on a filled colour pill (WCAG relative luminance). */
export function contrastInk(hex: string): string {
  const normalised = normaliseHighlightColour(hex);
  const r = parseInt(normalised.slice(1, 3), 16);
  const g = parseInt(normalised.slice(3, 5), 16);
  const b = parseInt(normalised.slice(5, 7), 16);
  const linear = (channel: number) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
  };
  const luminance = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  return luminance > 0.179 ? "#0D1402" : "#FFFFFF";
}

let current = DEFAULT_HIGHLIGHT_COLOUR;

export function highlightColour(): string {
  return current;
}

export function setHighlightColour(next: string): void {
  current = normaliseHighlightColour(next);
}

export function isHighlightHex(value: unknown): value is string {
  return typeof value === "string" && HEX_COLOUR.test(value.trim());
}

export function isHighlightNone(value: unknown): value is string {
  return typeof value === "string" && value.trim().toLowerCase() === HIGHLIGHT_NO_FILL;
}

export function parseHighlightColourValue(value: unknown): string | null {
  if (isHighlightNone(value)) return HIGHLIGHT_NO_FILL;
  if (!isHighlightHex(value)) return null;
  return normaliseHighlightColour(value);
}

/** Highlights that still punch isolate / export clips, but must not paint fill or outline. */
export function filledHighlights(highlights: string[], colours?: Record<string, string>): string[] {
  if (!colours) return highlights;
  return highlights.filter((code) => !isHighlightNone(colours[code]));
}

export function parseHighlightCode(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const code = text.includes(":") ? text : text.toUpperCase();
  return HIGHLIGHT_CODE.test(code) ? code : null;
}

export function parseHighlightColours(raw: unknown): Record<string, string> | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const code = parseHighlightCode(key);
    const colour = parseHighlightColourValue(value);
    if (!code || !colour) continue;
    out[code] = colour;
  }
  return Object.keys(out).length ? out : undefined;
}

/** Stable, order-independent fingerprint of per-highlight overrides. */
export function highlightColoursKey(colours: Record<string, string> | undefined): string {
  const parsed = parseHighlightColours(colours);
  if (!parsed) return "";
  return Object.keys(parsed)
    .sort()
    .map((code) => `${code}:${parsed[code]}`)
    .join(",");
}

export type HighlightFill = { none: boolean; hex: string };

export function resolvedHighlightColour(
  code: string,
  colours: Record<string, string> | undefined,
  fallback: string = DEFAULT_HIGHLIGHT_COLOUR
): HighlightFill {
  const raw = colours?.[code];
  if (isHighlightNone(raw)) return { none: true, hex: normaliseHighlightColour(fallback) };
  if (isHighlightHex(raw)) return { none: false, hex: normaliseHighlightColour(raw) };
  return { none: false, hex: normaliseHighlightColour(fallback) };
}

function fillEquals(a: HighlightFill, b: HighlightFill): boolean {
  if (a.none && b.none) return true;
  if (a.none !== b.none) return false;
  return a.hex === b.hex;
}

export type HighlightMismatch = {
  leave: Array<{ code: string; fill: HighlightFill }>;
  join: Array<{ code: string; fill: HighlightFill }>;
  recolour: Array<{ code: string; from: HighlightFill; to: HighlightFill }>;
};

export function highlightMismatchEmpty(mismatch: HighlightMismatch): boolean {
  return mismatch.leave.length === 0 && mismatch.join.length === 0 && mismatch.recolour.length === 0;
}

/** Regions that differ between shots — added, removed, or the same id with a different fill. */
export function highlightMismatch(
  from: { highlights: string[]; highlightColours?: Record<string, string> },
  to: { highlights: string[]; highlightColours?: Record<string, string> },
  fallback: string = DEFAULT_HIGHLIGHT_COLOUR
): HighlightMismatch {
  const toSet = new Set(to.highlights);
  const fromSet = new Set(from.highlights);
  const leave = from.highlights
    .filter((code) => !toSet.has(code))
    .map((code) => ({ code, fill: resolvedHighlightColour(code, from.highlightColours, fallback) }));
  const join = to.highlights
    .filter((code) => !fromSet.has(code))
    .map((code) => ({ code, fill: resolvedHighlightColour(code, to.highlightColours, fallback) }));
  const recolour = from.highlights
    .filter((code) => toSet.has(code))
    .map((code) => ({
      code,
      from: resolvedHighlightColour(code, from.highlightColours, fallback),
      to: resolvedHighlightColour(code, to.highlightColours, fallback),
    }))
    .filter((item) => !fillEquals(item.from, item.to));
  return { leave, join, recolour };
}

export function pruneHighlightColours(
  highlights: string[],
  colours: Record<string, string> | undefined
): Record<string, string> | undefined {
  if (!colours) return undefined;
  const keep = new Set(highlights);
  const next: Record<string, string> = {};
  for (const [code, colour] of Object.entries(colours)) {
    if (keep.has(code)) next[code] = colour;
  }
  return Object.keys(next).length ? next : undefined;
}

/** MapLibre `match` on ADM0_A3 / adm1_code, falling back to the global colour. */
export function highlightColourExpression(
  idProperty: "ADM0_A3" | "adm1_code",
  fallback: string,
  overrides?: Record<string, string>
): string | unknown[] {
  const base = normaliseHighlightColour(fallback);
  const pairs: string[] = [];
  for (const [code, colour] of Object.entries(overrides || {})) {
    if (isHighlightNone(colour) || !isHighlightHex(colour)) continue;
    if (idProperty === "ADM0_A3") {
      if (code.startsWith("A1:")) continue;
      pairs.push(code, normaliseHighlightColour(colour));
    } else if (code.startsWith("A1:")) {
      pairs.push(code.slice(3), normaliseHighlightColour(colour));
    }
  }
  if (!pairs.length) return base;
  return ["match", ["get", idProperty], ...pairs, base];
}
