import type { MapsSaveStatus } from "./saveQueue";

export const MAPS_SAVE_STATUS_KEY = "obed-edom.maps.saveStatus";

const STATUSES = new Set<MapsSaveStatus>(["saved", "saving", "unsaved", "paused", "error"]);

type Stored = { jobId: string; status: MapsSaveStatus };

function readStored(): Stored | null {
  try {
    const raw = sessionStorage.getItem(MAPS_SAVE_STATUS_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as { jobId?: unknown; status?: unknown };
    if (typeof data.jobId !== "string" || !data.jobId) return null;
    if (typeof data.status !== "string" || !STATUSES.has(data.status as MapsSaveStatus)) return null;
    return { jobId: data.jobId, status: data.status as MapsSaveStatus };
  } catch {
    return null;
  }
}

export function loadMapsSaveStatus(jobId?: string | null): MapsSaveStatus {
  const stored = readStored();
  if (!stored) return "saved";
  if (jobId && stored.jobId !== jobId) return "saved";
  return stored.status;
}

export function writeMapsSaveStatus(jobId: string | null, status: MapsSaveStatus): void {
  if (!jobId) return;
  try {
    sessionStorage.setItem(MAPS_SAVE_STATUS_KEY, JSON.stringify({ jobId, status } satisfies Stored));
  } catch {
    /* ignore */
  }
}
