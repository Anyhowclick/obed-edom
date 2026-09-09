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

function ringsOf(geometry: { type: string; coordinates: unknown } | null | undefined): number[][][] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return geometry.coordinates as number[][][];
  if (geometry.type === "MultiPolygon") return (geometry.coordinates as number[][][][]).flat();
  return [];
}

export function isolateMaskGeometry(
  features: Admin0Feature[],
  highlights: string[]
): GeoJSON.Feature | null {
  const wanted = new Set(highlights.map((h) => h.trim().toUpperCase()).filter(Boolean));
  if (!wanted.size) return null;
  const rings: number[][][] = [WORLD_RING];
  for (const feat of features) {
    const id = String(feat.properties?.ADM0_A3 || "").toUpperCase();
    if (!id || !wanted.has(id)) continue;
    rings.push(...ringsOf(feat.geometry));
  }
  if (rings.length <= 1) return null;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: rings },
  };
}
