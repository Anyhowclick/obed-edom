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

export type HighlightPiece = { id: string; rings: number[][][] };

/**
 * One piece per highlight, grouped exactly as `countryClipRings` used to flatten them. `A1:`-
 * prefixed highlights select admin-1 features by `adm1_code` (compared verbatim — those codes
 * are case-sensitive); bare codes select admin-0.
 *
 * When any `A1:` region is present in the original highlights — even one later dropped as
 * nested inside an already-highlighted country — every highlighted country is emitted from
 * its own admin-1 rings instead of the 50m admin-0 outline, so the two never disagree along a
 * shared border. Regions nested inside an already-highlighted country are dropped as redundant,
 * their rings folded into the country's own piece (keyed by the ADM0 code).
 */
export function highlightPieces(
  features: Admin0Feature[],
  highlights: string[],
  admin1: Admin1Feature[] = []
): HighlightPiece[] {
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

  const pieces: HighlightPiece[] = [];
  const byId = new Map<string, HighlightPiece>();
  for (const feat of features) {
    const id = String(feat.properties?.ADM0_A3 || "").toUpperCase();
    if (!id || !adm0.has(id) || cutCountries.has(id)) continue;
    const piece: HighlightPiece = { id, rings: ringsOf(feat.geometry) };
    pieces.push(piece);
    byId.set(id, piece);
  }
  for (const feat of admin1) {
    const code = String(feat.properties?.adm1_code || "");
    const country = admin1Country(feat, code);
    if (!adm1.has(code) && !cutCountries.has(country)) continue;
    if (cutCountries.has(country)) {
      let piece = byId.get(country);
      if (!piece) {
        piece = { id: country, rings: [] };
        pieces.push(piece);
        byId.set(country, piece);
      }
      piece.rings.push(...ringsOf(feat.geometry));
    } else {
      pieces.push({ id: "A1:" + code, rings: ringsOf(feat.geometry) });
    }
  }
  return pieces;
}

/** Flattened rings to cut out of the isolate mask, in the same order `highlightPieces` emits them.
 * Same order holds while `admin1` features for a cut country stay contiguous (each cut country's
 * rings fold into the piece created at its first appearance); an interleaved `admin1` list would diverge. */
export function countryClipRings(
  features: Admin0Feature[],
  highlights: string[],
  admin1: Admin1Feature[] = []
): number[][][] {
  return highlightPieces(features, highlights, admin1).flatMap((p) => p.rings);
}

/** Bounding box of already-projected raster-pixel points, expanded by `bleed` and clamped to `[0,width]x[0,height]`; `null` when fully offscreen. */
export function pieceBox(
  points: [number, number][],
  width: number,
  height: number,
  bleed = 1
): { x: number; y: number; w: number; h: number } | null {
  if (!points.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  const x0 = Math.max(0, Math.floor(minX - bleed));
  const y0 = Math.max(0, Math.floor(minY - bleed));
  const x1 = Math.min(width, Math.ceil(maxX + bleed));
  const y1 = Math.min(height, Math.ceil(maxY + bleed));
  const w = x1 - x0;
  const h = y1 - y0;
  if (w < 1 || h < 1) return null;
  return { x: x0, y: y0, w, h };
}

export type PieceClip = {
  box: { x: number; y: number; w: number; h: number };
  ringsPx: [number, number][][];
  source: { sx: number; sy: number; sw: number; sh: number };
  dest: { dx: number; dy: number; dw: number; dh: number };
};

/** Pure geometry for one isolate cut-out piece: projects `rings` (lon/lat) through `project` at
 * `pixelRatio`, offsets by the capture crop, derives the tight bounding box via `pieceBox`, and
 * returns the clip-path points plus the `drawImage` source/dest rectangles a caller draws with.
 * No MapLibre import — `project` is the only hook into the map. Each piece clips independently
 * (a union of per-piece nonzero-winding fills, not one path over all rings), which only differs
 * from a single combined clip for overlapping polygons with opposing winding across two pieces —
 * not a shape Natural Earth data produces. */
export function pieceClip(
  rings: number[][][],
  project: (lonLat: [number, number]) => { x: number; y: number },
  pixelRatio: number,
  cropX: number,
  cropY: number,
  width: number,
  height: number,
  bleed = 1
): PieceClip | null {
  const ringsPx = rings.map((ring) =>
    ring.map(([lon, lat]) => {
      const { x, y } = project([lon, lat]);
      return [x * pixelRatio - cropX, y * pixelRatio - cropY] as [number, number];
    })
  );
  const box = pieceBox(ringsPx.flat(), width, height, bleed);
  if (!box) return null;
  return {
    box,
    ringsPx,
    source: { sx: cropX + box.x, sy: cropY + box.y, sw: box.w, sh: box.h },
    dest: { dx: box.x, dy: box.y, dw: box.w, dh: box.h },
  };
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
