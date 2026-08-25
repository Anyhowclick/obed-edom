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
  status: "queued" | "running" | "done" | "error";
  logs: string[];
  error?: string | null;
  result?: Record<string, unknown> | null;
  createdAt?: number;
  updatedAt?: number;
  artifacts?: Artifacts;
};

export type ChosenFile = { path: string; name: string };

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return data.detail || JSON.stringify(data);
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
  body: { folder?: string; path?: string; leftPath?: string; rightPath?: string }
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

export async function saveVisualSlots(
  jobId: string,
  slots: { leftIndex: number | null; rightIndex?: number | null; rightIndexes?: number[] }[]
): Promise<Job> {
  const res = await fetch(`/api/visual/${jobId}/slots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slots }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startVisualCheck(
  jobId: string,
  slots: { leftIndex: number | null; rightIndex?: number | null; rightIndexes?: number[] }[]
): Promise<Job> {
  const res = await fetch(`/api/visual/${jobId}/check`, {
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

export async function startVisual(leftPath: string, rightPath: string, fresh = false): Promise<Job> {
  const body = new FormData();
  body.set("left_path", leftPath);
  body.set("right_path", rightPath);
  if (fresh) body.set("fresh", "true");
  const res = await fetch("/api/visual", { method: "POST", body });
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

export async function getTemplates(): Promise<{ dskTemplate: string; dskTemplatePath: string }> {
  const res = await fetch("/api/templates");
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

/** One page's framing answer. `templateSlide` is set only when state is "pinned". */
export type FramingDecision = {
  wallIndex: number;
  state: "auto" | "pinned" | "deferred";
  templateSlide: number | null;
  /** Set instead of templateSlide when the page borrows a saved transform. */
  recipeId?: string | null;
};

/** A transform kept from a page that worked, for pages that cannot learn one. */
export type SavedRecipe = {
  id: string;
  label: string;
  source?: string;
  affine: { s: number; tx: number; ty: number };
};

export async function listRecipes(): Promise<SavedRecipe[]> {
  const res = await fetch("/api/recipes");
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()).recipes || [];
}

export async function deleteRecipe(id: string): Promise<void> {
  const res = await fetch(`/api/recipes/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res));
}

/** Keep the way a reviewed page came out. */
export async function saveRecipeFromPage(
  jobId: string,
  slide: number,
  label: string,
  templateSlide?: number | null
): Promise<SavedRecipe> {
  const body = new FormData();
  body.set("slide", String(slide));
  body.set("label", label);
  if (templateSlide != null) body.set("template_slide", String(templateSlide));
  const res = await fetch(`/api/resize/${jobId}/recipes`, { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()).recipe;
}

/** What one saved recipe would do to one page. Fetched on demand: a library of a
 *  dozen against a 158-page deck is 1,896 plans nobody looks at. */
export async function previewRecipe(
  jobId: string,
  slide: number,
  recipeId: string
): Promise<{ transform: { s: number; tx: number; ty: number }; rects: unknown[] }> {
  const body = new FormData();
  body.set("slide", String(slide));
  body.set("recipe_id", recipeId);
  const res = await fetch(`/api/resize/${jobId}/recipe-preview`, { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function saveResizeFramings(jobId: string, decisions: FramingDecision[]): Promise<Job> {
  const res = await fetch(`/api/resize/${jobId}/framings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Phase two: remap with the confirmed framings. Saves them first if given. */
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

export async function pollJob(id: string, onTick: (job: Job) => void): Promise<Job> {
  for (;;) {
    const job = await getJob(id);
    onTick(job);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, 600));
  }
}
