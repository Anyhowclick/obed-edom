/** Admin-1 prefetch for Regions mode. A world-view query can see every country;
 * the merged GeoJSON source should not ingest the planet. */
export const REGION_PREFETCH_MAX = 16;

export type Admin0Hit = { properties?: { ADM0_A3?: string } | null };
export type Admin1Hit = { properties?: { adm1_code?: string } | null };

export function uniqueAdmin0Codes(hits: Admin0Hit[]): string[] {
  const codes: string[] = [];
  const seen = new Set<string>();
  for (const hit of hits) {
    const code = String(hit.properties?.ADM0_A3 || "");
    if (!code || seen.has(code)) continue;
    seen.add(code);
    codes.push(code);
  }
  return codes;
}

export function admin1CodeFromHits(hits: Admin1Hit[]): string {
  return String(hits[0]?.properties?.adm1_code || "");
}

/** Countries whose admin-1 must be loaded so a click anywhere in the viewport
 * can hit a region. The camera centre is often water (a Borneo frame between
 * Sabah and the peninsula), so a centre-only query loads nothing. When the
 * viewport is a world view, keep the camera country if there is one and fill
 * the remainder from whatever else is on screen. */
export function regionCountriesFromHits(
  visible: Admin0Hit[],
  centre: Admin0Hit[],
  max = REGION_PREFETCH_MAX
): string[] {
  const viewport = uniqueAdmin0Codes(visible);
  if (viewport.length <= max) return viewport;
  const head = uniqueAdmin0Codes(centre);
  const rest = viewport.filter((code) => !head.includes(code));
  return [...head, ...rest].slice(0, max);
}
