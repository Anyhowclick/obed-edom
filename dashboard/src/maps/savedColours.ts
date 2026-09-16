import { useEffect, useState } from "react";
import { DEFAULT_HIGHLIGHT_COLOUR, isHighlightHex, normaliseHighlightColour } from "./highlight";

export const SAVED_COLOURS_KEY = "obed-edom.maps.savedColours";
export const DEFAULT_SAVED_COLOUR = DEFAULT_HIGHLIGHT_COLOUR;

const listeners = new Set<() => void>();

function hexFromUnknown(item: unknown): string | null {
  if (typeof item === "string") {
    return isHighlightHex(item) ? normaliseHighlightColour(item) : null;
  }
  if (!item || typeof item !== "object") return null;
  const hex = (item as { hex?: unknown }).hex;
  return isHighlightHex(hex) ? normaliseHighlightColour(hex) : null;
}

export function parseSaved(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    const hex = hexFromUnknown(item);
    if (!hex || seen.has(hex)) continue;
    seen.add(hex);
    out.push(hex);
  }
  return out;
}

export function loadSavedColours(): string[] {
  const raw = localStorage.getItem(SAVED_COLOURS_KEY);
  if (raw == null) return [DEFAULT_SAVED_COLOUR];
  try {
    return parseSaved(JSON.parse(raw));
  } catch {
    return [DEFAULT_SAVED_COLOUR];
  }
}

export function writeSavedColours(next: string[]): string[] {
  const parsed = parseSaved(next);
  try {
    localStorage.setItem(SAVED_COLOURS_KEY, JSON.stringify(parsed));
  } catch {
    /* ignore quota */
  }
  listeners.forEach((listener) => listener());
  return parsed;
}

export function addSavedColour(saved: string[], hex: string): string[] {
  const normalised = normaliseHighlightColour(hex);
  if (saved.includes(normalised)) return saved;
  return [...saved, normalised];
}

export function removeSavedColour(saved: string[], hex: string): string[] {
  return saved.filter((item) => item !== normaliseHighlightColour(hex));
}

/** Shared palette so every colour field on the inspector stays in sync. */
export function useSavedColours(): [string[], (next: string[]) => void] {
  const [colours, setColours] = useState(loadSavedColours);
  useEffect(() => {
    const sync = () => setColours(loadSavedColours());
    listeners.add(sync);
    return () => {
      listeners.delete(sync);
    };
  }, []);
  return [colours, writeSavedColours];
}
