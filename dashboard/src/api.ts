export type Flag = {
  severity: "info" | "warning" | "error" | "success";
  category: string;
  message: string;
  location?: string;
  resolved?: string | null;
  rule?: string;
  title?: string;
  slide?: number | null;
  deck?: string;
  evidence?: string;
};

export type Artifacts = {
  ok: boolean;
  missing: string[];
  suggestedPath?: string | null;
};

export type Job = {
  id: string;
  kind: string;
  feature?: string;
  name?: string;
  status: "queued" | "running" | "done" | "error";
  logs: string[];
  error?: string | null;
  result?: Record<string, unknown> | null;
  createdAt?: number;
  updatedAt?: number;
  artifacts?: Artifacts;
};

export type ChosenFile = { path: string; name: string };

async function readError(res: Response, parsed?: unknown): Promise<string> {
  try {
    const data = parsed !== undefined ? parsed : await res.json();
    return (data as { detail?: string })?.detail || JSON.stringify(data);
  } catch {
    return res.statusText;
  }
}

export async function chooseKeynote(prompt: string): Promise<ChosenFile> {
  const body = new FormData();
  body.set("prompt", prompt);
  const res = await fetch("/api/choose-file", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function chooseFolder(prompt: string): Promise<ChosenFile> {
  const body = new FormData();
  body.set("prompt", prompt);
  const res = await fetch("/api/choose-folder", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function resolveDrop(name: string, size?: number): Promise<ChosenFile> {
  const body = new FormData();
  body.set("name", name);
  if (size != null && size > 0) body.set("size", String(size));
  const res = await fetch("/api/resolve-drop", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function reveal(path: string): Promise<void> {
  const body = new FormData();
  body.set("path", path);
  await fetch("/api/reveal", { method: "POST", body });
}

export async function generateDocx(
  files: File[],
  templates: { lwTemplate?: string; dskTemplate?: string }
): Promise<Job[]> {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  if (templates.lwTemplate) body.set("lw_template", templates.lwTemplate);
  if (templates.dskTemplate) body.set("dsk_template", templates.dskTemplate);
  const res = await fetch("/api/generate", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.jobs;
}

export async function listJobs(feature?: string): Promise<Job[]> {
  const qs = feature ? `?feature=${encodeURIComponent(feature)}` : "";
  const res = await fetch(`/api/jobs${qs}`);
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.jobs || [];
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function patchJob(id: string, result: Record<string, unknown>): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function renameJob(id: string, name: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}/name`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteJob(id: string): Promise<void> {
  const res = await fetch(`/api/jobs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res));
}

export async function deleteAllJobs(): Promise<number> {
  const res = await fetch("/api/jobs", { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return typeof data.deleted === "number" ? data.deleted : 0;
}

export async function relocateJob(
  id: string,
  body: { folder?: string; path?: string; leftPath?: string; rightPath?: string; destPath?: string; destPathCg?: string; destPathDsk?: string }
): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}/relocate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startDiffCheck(
  jobId: string,
  slots: { leftIndex: number | null; rightIndex?: number | null; rightIndexes?: number[] }[]
): Promise<Job> {
  const res = await fetch(`/api/diff/${jobId}/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slots }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type Settings = {
  reuseThreshold: number;
  reusePairings: boolean;
  reusePreviews: boolean;
};

export async function getSettings(): Promise<Settings> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function putSettings(next: Partial<Settings>): Promise<Settings> {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(next),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startDiff(
  leftPath: string,
  rightPath: string,
  leftLabel = "LW",
  rightLabel = "Other",
  fresh = false,
  outlinePath?: string,
  lwFinal = true
): Promise<Job> {
  const body = new FormData();
  body.set("left_path", leftPath);
  body.set("right_path", rightPath);
  body.set("left_label", leftLabel);
  body.set("right_label", rightLabel);
  if (outlinePath) body.set("outline_path", outlinePath);
  body.set("lw_final", lwFinal ? "true" : "false");
  if (fresh) body.set("fresh", "true");
  const res = await fetch("/api/diff", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startOutline(path: string): Promise<Job> {
  const body = new FormData();
  body.set("path", path);
  const res = await fetch("/api/outline", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function outlinePdfUrl(jobId: string): string {
  return `/api/jobs/${jobId}/outline.pdf`;
}

export async function validateKeynote(
  path: string,
  opts?: {
    export?: boolean;
    rangeFrom?: number;
    rangeTo?: number;
    slides?: number[];
    feature?: string;
    outlinePath?: string;
    lwFinal?: boolean;
  }
): Promise<Job> {
  const body = new FormData();
  body.set("path", path);
  body.set("export", opts?.export ? "true" : "false");
  if (opts?.slides?.length) body.set("slides", opts.slides.join(","));
  if (opts?.rangeFrom != null) body.set("range_from", String(opts.rangeFrom));
  if (opts?.rangeTo != null) body.set("range_to", String(opts.rangeTo));
  if (opts?.feature) body.set("feature", opts.feature);
  if (opts?.outlinePath) body.set("outline_path", opts.outlinePath);
  if (opts?.lwFinal != null) body.set("lw_final", opts.lwFinal ? "true" : "false");
  const res = await fetch("/api/validate-keynote", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function stubDsk(): Promise<string> {
  const res = await fetch("/api/dsk", { method: "POST" });
  const data = await res.json();
  return data.detail || "Not implemented";
}

export async function startResize(
  path: string,
  opts: {
    templatePath: string;
    rangeFrom?: number;
    rangeTo?: number;
    slides?: number[];
    export?: boolean;
    includeLists?: boolean;
    validate?: boolean;
  }
): Promise<Job> {
  const body = new FormData();
  body.set("path", path);
  body.set("template_path", opts.templatePath);
  if (opts.slides?.length) body.set("slides", opts.slides.join(","));
  if (opts.rangeFrom != null) body.set("range_from", String(opts.rangeFrom));
  if (opts.rangeTo != null) body.set("range_to", String(opts.rangeTo));
  body.set("export", opts.export === false ? "false" : "true");
  body.set("include_lists", opts.includeLists ? "true" : "false");
  body.set("validate", opts.validate === false ? "false" : "true");
  const res = await fetch("/api/resize", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** One page's framing answer. `templateSlide` only when pinned. `keepSideContent` is orthogonal. */
export type FramingDecision = {
  wallIndex: number;
  state: "auto" | "pinned" | "deferred";
  templateSlide: number | null;
  keepSideContent?: boolean;
};

export async function saveResizeFramings(jobId: string, decisions: FramingDecision[]): Promise<Job> {
  const res = await fetch(`/api/resize/${jobId}/framings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function applyResize(jobId: string, decisions?: FramingDecision[]): Promise<Job> {
  const res = await fetch(`/api/resize/${jobId}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(decisions ? { decisions } : {}),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function previewUrl(jobId: string, deck: string, filename: string): string {
  return `/api/jobs/${jobId}/previews/${deck}/${encodeURIComponent(filename)}`;
}

export function diffImageUrl(jobId: string, side: "left" | "right" | "heat", filename: string): string {
  return `/api/diff/${jobId}/image/${side}/${encodeURIComponent(filename)}`;
}

export function evidenceUrl(jobId: string, filename: string): string {
  return `/api/jobs/${jobId}/evidence/${encodeURIComponent(filename)}`;
}

export async function pollJob(
  id: string,
  onTick: (job: Job) => void,
  isCancelled?: () => boolean,
  onCancel?: () => Promise<Job>
): Promise<Job> {
  let cancelSent = false;
  const cancel = async (): Promise<Job | undefined> => {
    if (!isCancelled?.()) return undefined;
    if (!cancelSent) {
      cancelSent = true;
      try {
        const job = await onCancel?.();
        if (job && (job.status === "done" || job.status === "error")) {
          onTick(job);
          return job;
        }
      } catch {}
    }
    return undefined;
  };
  for (;;) {
    const cancelled = await cancel();
    if (cancelled) return cancelled;
    const job = await getJob(id);
    onTick(job);
    if (job.status === "done" || job.status === "error") return job;
    for (let waited = 0; waited < 600; waited += 50) {
      await new Promise((r) => setTimeout(r, 50));
      const cancelled = await cancel();
      if (cancelled) return cancelled;
    }
  }
}

export async function startMaps(): Promise<Job> {
  const res = await fetch("/api/maps", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type MapsStateConflict = {
  stateRevision: number;
  document: Record<string, unknown>;
};

export class MapsStateConflictError extends Error {
  readonly conflict: MapsStateConflict;

  constructor(conflict: MapsStateConflict) {
    super("This map changed elsewhere.");
    this.conflict = conflict;
  }
}

export async function saveMapsState(id: string, doc: Record<string, unknown>, expectedRevision: number): Promise<Job> {
  const res = await fetch(`/api/maps/${id}/state`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expectedRevision, document: doc }),
  });
  if (res.status === 409) {
    const data = await res.json().catch(() => null);
    const detail = data?.detail;
    if (detail && typeof detail === "object" && typeof detail.stateRevision === "number" && detail.document && typeof detail.document === "object") {
      throw new MapsStateConflictError(detail as MapsStateConflict);
    }
  }
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function downloadMapsSession(id: string): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`/api/maps/${id}/session`);
  if (!res.ok) throw new Error(await readError(res));
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return { blob: await res.blob(), filename: match?.[1] || `maps-${id}.obedmaps` };
}

export async function loadMapsSession(id: string, file: File): Promise<Job> {
  const body = new FormData();
  body.set("file", file);
  const res = await fetch(`/api/maps/${id}/session`, { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type MapsPngKind = "thumb" | "still" | "plate";

export type MapsExportPlan = {
  links: Array<Record<string, unknown>>;
  stills: Array<{
    slideId: string;
    style: string;
    camera: { lat: number; lon: number; zoom: number; bearing: number; pitch: number };
    highlights: string[];
    hiddenLayers?: string[];
    hillshade?: boolean;
    isolate?: unknown;
    width?: number;
    height?: number;
    synthetic?: boolean;
  }>;
  plates: Array<{
    plateId: string;
    plateW: number;
    plateH: number;
    slideIds: string[];
    camera: { lat: number; lon: number; zoom: number; bearing: number; pitch: number };
    style: string;
    highlights: string[];
    hiddenLayers?: string[];
    hillshade?: boolean;
    isolate?: unknown;
  }>;
  cg?: {
    links: Array<Record<string, unknown>>;
    stills: MapsExportPlan["stills"];
    plates: MapsExportPlan["plates"];
    affectedSlideIds?: string[];
  };
};

export class MapsStaleThumbnailError extends Error {
  readonly stateRevision: number;

  constructor(stateRevision: number) {
    super("Thumbnail revision is stale.");
    this.stateRevision = stateRevision;
  }
}

export async function postMapsPng(
  id: string,
  blob: Blob,
  opts: { kind?: MapsPngKind; slideId?: string; plateId?: string; audience?: "lw" | "cg"; variant?: "country"; revision?: number } = {}
): Promise<Job> {
  const params = new URLSearchParams();
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.slideId) params.set("slideId", opts.slideId);
  if (opts.plateId) params.set("plateId", opts.plateId);
  if (opts.audience) params.set("audience", opts.audience);
  if (opts.variant) params.set("variant", opts.variant);
  if (opts.revision !== undefined) params.set("revision", String(opts.revision));
  const res = await fetch(`/api/maps/${id}/png?${params.toString()}`, {
    method: "POST",
    body: blob,
  });
  if (res.status === 409) {
    const data = await res.json().catch(() => null);
    const detail = data?.detail;
    if (detail && typeof detail === "object" && detail.staleThumbnail && typeof detail.stateRevision === "number") {
      throw new MapsStaleThumbnailError(detail.stateRevision);
    }
    throw new Error(await readError(res, data ?? undefined));
  }
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function postMapsFrame(
  id: string,
  blob: Blob,
  opts: { slideId: string; index: number; count: number; fps: number; audience?: "lw" | "cg" }
): Promise<{ ok: true; index: number; count: number }> {
  const params = new URLSearchParams();
  params.set("slideId", opts.slideId);
  params.set("index", String(opts.index));
  params.set("count", String(opts.count));
  params.set("fps", String(opts.fps));
  if (opts.audience) params.set("audience", opts.audience);
  const res = await fetch(`/api/maps/${id}/frame?${params.toString()}`, {
    method: "POST",
    body: blob,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

type TileCacheBody = {
  countries?: string[];
  cameras?: Array<{ lat: number; lon: number; zoom: number; bearing?: number; pitch?: number }>;
  maxzoom?: number;
  width?: number;
  height?: number;
  terrain?: boolean;
  rels?: string[];
};

export async function prefetchMapsTiles(
  body: TileCacheBody
): Promise<{ ok: boolean; tiles: number; cached: number; fetched: number; failed: number }> {
  const res = await fetch("/api/maps/tile-cache/prefetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function planMapsTiles(body: TileCacheBody): Promise<{
  ok: boolean;
  rels: string[];
  tiles: number;
  cached: number;
  capped: boolean;
  cameras: number;
  camerasUsed: number;
}> {
  const res = await fetch("/api/maps/tile-cache/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function mapsTileCacheStats(): Promise<{ bytes: number; files: number }> {
  const res = await fetch("/api/maps/tile-cache");
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function clearMapsTileCache(): Promise<{ bytes: number; files: number }> {
  const res = await fetch("/api/maps/tile-cache", { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchMapsExportPlan(id: string): Promise<MapsExportPlan> {
  const res = await fetch(`/api/maps/${id}/export-plan`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function geocodeMaps(
  q: string
): Promise<{
  source: string;
  label: string;
  camera: { lat: number; lon: number; zoom: number; bearing: number; pitch: number };
}> {
  const res = await fetch(`/api/maps/geocode?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function bootstrapMapsCsv(id: string, file: File, replace = false): Promise<Job> {
  const body = new FormData();
  body.set("file", file);
  body.set("replace", replace ? "true" : "false");
  const res = await fetch(`/api/maps/${id}/bootstrap-csv`, { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function bootstrapMapsPinsCsv(id: string, file: File, slideId: string, audience: "lw" | "cg"): Promise<Job> {
  const body = new FormData();
  body.set("file", file);
  body.set("targetSlideId", slideId);
  body.set("audience", audience);
  const res = await fetch(`/api/maps/${id}/bootstrap-csv`, { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function addMapsLandmark(id: string, slideId: string, audience: "lw" | "cg", file: File): Promise<{ job: Job; churchId: string }> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`/api/maps/${encodeURIComponent(id)}/slides/${encodeURIComponent(slideId)}/landmark?audience=${audience}`, { method: "POST", body });
  if (!response.ok) throw new Error(await readError(response));
  const data = await response.json();
  const { churchId, ...job } = data as Record<string, unknown>;
  if (typeof churchId !== "string") throw new Error("The uploaded landmark response was incomplete.");
  return { job: job as Job, churchId };
}

export async function exportMaps(id: string, body?: { exportLw?: boolean; exportCg?: boolean; exportDsk?: boolean }): Promise<Job> {
  const res = await fetch(`/api/maps/${id}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function cancelMapsExport(id: string): Promise<Job> {
  const res = await fetch(`/api/maps/${id}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startWatercolour(
  files: File[],
  opts: { washSoftness: number; inkAmount: number; masks: Record<string, unknown> }
): Promise<Job> {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  body.set("wash_softness", String(opts.washSoftness));
  body.set("ink_amount", String(opts.inkAmount));
  body.set("masks", JSON.stringify(opts.masks));
  const res = await fetch("/api/watercolour", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchWatercolourPreview(
  opts: { washSoftness: number; inkAmount: number; file?: File; mask?: string },
  signal: AbortSignal
): Promise<Blob> {
  let res: Response;
  if (opts.file) {
    const body = new FormData();
    body.set("file", opts.file);
    body.set("wash_softness", String(opts.washSoftness));
    body.set("ink_amount", String(opts.inkAmount));
    if (opts.mask) body.set("mask", opts.mask);
    res = await fetch("/api/watercolour/preview", { method: "POST", body, signal });
  } else {
    res = await fetch(`/api/watercolour/preview?wash_softness=${opts.washSoftness}&ink_amount=${opts.inkAmount}`, { signal });
  }
  if (!res.ok) throw new Error(await readError(res));
  return res.blob();
}

export async function cancelWatercolour(id: string): Promise<Job> {
  const res = await fetch(`/api/watercolour/${id}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function addWatercolourToMap(jobId: string, itemId: string, mapsJobId: string, slideId: string): Promise<{ job: Job; churchId: string }> {
  const res = await fetch(`/api/watercolour/${jobId}/items/${itemId}/add-to-map/${mapsJobId}/${slideId}`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  const { churchId, ...job } = data as Record<string, unknown>;
  if (typeof churchId !== "string") throw new Error("The Watercolour add-to-map response was incomplete.");
  return { job: job as Job, churchId };
}

export function watercolourImageUrl(jobId: string, itemId: string, kind: "original" | "result"): string {
  return `/api/watercolour/${jobId}/items/${itemId}/${kind}`;
}

export async function fetchWatercolourSpec(jobId: string, itemId: string): Promise<unknown> {
  const res = await fetch(`/api/watercolour/${jobId}/items/${itemId}/spec`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.spec ?? null;
}

export async function fetchWatercolourOriginal(jobId: string, itemId: string, name: string): Promise<File> {
  const res = await fetch(watercolourImageUrl(jobId, itemId, "original"));
  if (!res.ok) throw new Error(await readError(res));
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type || "image/png" });
}

export function watercolourDownloadUrl(jobId: string): string {
  return `/api/watercolour/${jobId}/download`;
}
