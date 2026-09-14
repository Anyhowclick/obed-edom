export const OSM_ATTRIBUTION = "© OpenStreetMap contributors";
export const MAPTILER_ATTRIBUTION = "© MapTiler";
export const TERRAIN_ATTRIBUTION =
  "Elevation: Mapzen Terrain Tiles · SRTM & GMTED2010 data courtesy of the U.S. Geological Survey · ETOPO1 DOC/NOAA/NESDIS/NCEI";

function creditParts(styleId: string | undefined, terrain: boolean): string[] {
  const parts = [OSM_ATTRIBUTION];
  if (styleId?.startsWith("toner")) parts.push(MAPTILER_ATTRIBUTION);
  if (terrain) parts.push(TERRAIN_ATTRIBUTION);
  return parts;
}

export function creditLine(styleId: string | undefined, terrain: boolean): string {
  return creditParts(styleId, terrain).join(" · ");
}

export function creditLines(views: { style?: string; hillshade?: boolean }[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const view of views) {
    for (const part of creditParts(view.style, !!view.hillshade)) {
      if (!seen.has(part)) {
        seen.add(part);
        result.push(part);
      }
    }
  }
  return result;
}
