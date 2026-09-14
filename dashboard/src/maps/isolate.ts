const WORLD_RING: [number, number][] = [
  [-180, -85.05],
  [180, -85.05],
  [180, 85.05],
  [-180, 85.05],
  [-180, -85.05],
];

type Admin0Feature = {
  properties?: { ADM0_A3?: string } | null;
  geometry?: { type: string; coordinates: unknown } | null;
};

type Admin1Feature = {
  properties?: { adm0_a3?: string; adm1_code?: string } | null;
  geometry?: { type: string; coordinates: unknown } | null;
};

function admin1Country(feat: Admin1Feature, code: string): string {
  return String(feat.properties?.adm0_a3 || code.slice(0, 3)).toUpperCase();
}

function ringsOf(geometry: { type: string; coordinates: unknown } | null | undefined): number[][][] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return geometry.coordinates as number[][][];
  if (geometry.type === "MultiPolygon") return (geometry.coordinates as number[][][][]).flat();
  return [];
}

/**
 * Rings to cut out of the isolate mask. `A1:`-prefixed highlights select admin-1 features by
 * `adm1_code` (compared verbatim — those codes are case-sensitive); bare codes select admin-0.
 *
 * When any `A1:` region is present in the original highlights — even one later dropped as
 * nested inside an already-highlighted country — every highlighted country is emitted from
 * its own admin-1 rings instead of the 50m admin-0 outline, so the two never disagree along a
 * shared border. Regions nested inside an already-highlighted country are dropped as redundant.
 */
export function countryClipRings(
  features: Admin0Feature[],
  highlights: string[],
  admin1: Admin1Feature[] = []
): number[][][] {
  const adm0 = new Set<string>();
  const adm1 = new Set<string>();
  for (const raw of highlights) {
    const highlight = raw.trim();
    if (!highlight) continue;
    if (highlight.startsWith("A1:")) adm1.add(highlight.slice(3));
    else adm0.add(highlight.toUpperCase());
  }
  const hadAdmin1Highlight = adm1.size > 0;
  for (const code of [...adm1]) {
    const feat = admin1.find((item) => item.properties?.adm1_code === code);
    if (adm0.has(feat ? admin1Country(feat, code) : code.slice(0, 3).toUpperCase())) adm1.delete(code);
  }
  if (!adm0.size && !adm1.size) return [];

  const cut = hadAdmin1Highlight;
  const cutCountries = new Set<string>();
  if (cut) {
    for (const feat of admin1) {
      const country = String(feat.properties?.adm0_a3 || "").toUpperCase();
      if (country && adm0.has(country)) cutCountries.add(country);
    }
  }

  const rings: number[][][] = [];
  for (const feat of features) {
    const id = String(feat.properties?.ADM0_A3 || "").toUpperCase();
    if (!id || !adm0.has(id) || cutCountries.has(id)) continue;
    rings.push(...ringsOf(feat.geometry));
  }
  for (const feat of admin1) {
    const code = String(feat.properties?.adm1_code || "");
    const country = admin1Country(feat, code);
    if (!adm1.has(code) && !cutCountries.has(country)) continue;
    rings.push(...ringsOf(feat.geometry));
  }
  return rings;
}

export function isolateMaskGeometry(
  features: Admin0Feature[],
  highlights: string[],
  admin1: Admin1Feature[] = []
): GeoJSON.Feature | null {
  const rings = countryClipRings(features, highlights, admin1);
  if (!rings.length) return null;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [WORLD_RING, ...rings] },
  };
}
