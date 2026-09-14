export const DEFAULT_HIGHLIGHT_COLOUR = "#e8772a";

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
  };
}

let current = DEFAULT_HIGHLIGHT_COLOUR;

export function highlightColour(): string {
  return current;
}

export function setHighlightColour(next: string): void {
  current = normaliseHighlightColour(next);
}
