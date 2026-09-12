/** Row shape posted to `POST /api/maps/{id}/bootstrap-rows` (BootstrapRow in src/obed_edom/web/maps.py). */
export type MapsBootstrapRow = {
  name: string;
  place?: string;
  url?: string;
  lat?: number;
  lon?: number;
  kind?: ManualPinKind;
};

export type ManualMode = "slides" | "pins";
export type ManualPinKind = "dot" | "dropPin";

export type ManualRow = {
  key: string;
  name: string;
  place: string;
  url: string;
  lat: string;
  lon: string;
  kind: ManualPinKind;
};

export type ManualRowError = { key: string; index: number; message: string };

/** Web Mercator limit: the server clamps anything beyond this (clamp_lat in src/obed_edom/maps_geo.py). */
export const MANUAL_MAX_LAT = 85.05;

export function blankRow(seq: number): ManualRow {
  return { key: `r${seq}`, name: "", place: "", url: "", lat: "", lon: "", kind: "dropPin" };
}

export function rowIsEmpty(row: ManualRow): boolean {
  return !row.name.trim() && !row.place.trim() && !row.url.trim() && !row.lat.trim() && !row.lon.trim();
}

function coordinate(raw: string, limit: number): number | null {
  const value = Number(raw);
  if (!raw.trim() || !Number.isFinite(value) || Math.abs(value) > limit) return null;
  return value;
}

function rowError(row: ManualRow, index: number, mode: ManualMode): string | null {
  const name = row.name.trim();
  const lat = row.lat.trim();
  const lon = row.lon.trim();
  if (mode === "slides" && !name) return `Row ${index}: enter a name.`;
  if (mode === "pins" && !name && !row.place.trim() && !(lat && lon)) {
    return `Row ${index}: enter a name, a place or coordinates — a link on its own is not enough.`;
  }
  if (Boolean(lat) !== Boolean(lon)) return `Row ${index}: enter both a latitude and a longitude.`;
  if (lat && coordinate(lat, MANUAL_MAX_LAT) === null) {
    return `Row ${index}: latitude must be a number between -${MANUAL_MAX_LAT} and ${MANUAL_MAX_LAT}.`;
  }
  if (lon && coordinate(lon, 180) === null) return `Row ${index}: longitude must be a number between -180 and 180.`;
  return null;
}

export function validateManualRows(
  rows: ManualRow[],
  mode: ManualMode
): { payload: MapsBootstrapRow[]; errors: ManualRowError[] } {
  const entries = rows.filter((row) => !rowIsEmpty(row));
  if (!entries.length) return { payload: [], errors: [{ key: "", index: 0, message: "Add at least one entry." }] };
  const payload: MapsBootstrapRow[] = [];
  const errors: ManualRowError[] = [];
  entries.forEach((row, position) => {
    const index = position + 1;
    const message = rowError(row, index, mode);
    if (message) {
      errors.push({ key: row.key, index, message });
      return;
    }
    const name = row.name.trim();
    const entry: MapsBootstrapRow = { name: mode === "pins" ? name || "Pin" : name };
    if (row.place.trim()) entry.place = row.place.trim();
    if (row.url.trim()) entry.url = row.url.trim();
    if (row.lat.trim() && row.lon.trim()) {
      entry.lat = Number(row.lat);
      entry.lon = Number(row.lon);
    }
    if (mode === "pins") entry.kind = row.kind;
    payload.push(entry);
  });
  return { payload: errors.length ? [] : payload, errors };
}
