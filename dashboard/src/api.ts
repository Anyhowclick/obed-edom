export type Flag = {
  severity: "info" | "warning" | "error";
  category: string;
  message: string;
  location?: string;
  resolved?: string | null;
};

export type Job = {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  logs: string[];
  error?: string | null;
  result?: Record<string, unknown> | null;
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

export async function reveal(path: string): Promise<void> {
  const body = new FormData();
  body.set("path", path);
  await fetch("/api/reveal", { method: "POST", body });
}

export async function generateDocx(files: File[]): Promise<Job[]> {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  const res = await fetch("/api/generate", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.jobs;
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function startDiff(
  leftPath: string,
  rightPath: string,
  leftLabel = "LW",
  rightLabel = "Other"
): Promise<Job> {
  const body = new FormData();
  body.set("left_path", leftPath);
  body.set("right_path", rightPath);
  body.set("left_label", leftLabel);
  body.set("right_label", rightLabel);
  const res = await fetch("/api/diff", { method: "POST", body });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function validateKeynote(
  path: string,
  opts?: { export?: boolean; rangeFrom?: number; rangeTo?: number }
): Promise<Job> {
  const body = new FormData();
  body.set("path", path);
  body.set("export", opts?.export ? "true" : "false");
  if (opts?.rangeFrom != null) body.set("range_from", String(opts.rangeFrom));
  if (opts?.rangeTo != null) body.set("range_to", String(opts.rangeTo));
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

export async function stubResize(): Promise<string> {
  const res = await fetch("/api/resize", { method: "POST" });
  const data = await res.json();
  return data.detail || "Not implemented";
}

export function previewUrl(jobId: string, deck: string, filename: string): string {
  return `/api/jobs/${jobId}/previews/${deck}/${encodeURIComponent(filename)}`;
}

export function diffImageUrl(jobId: string, side: "left" | "right" | "heat", filename: string): string {
  return `/api/diff/${jobId}/image/${side}/${encodeURIComponent(filename)}`;
}

export async function pollJob(id: string, onTick: (job: Job) => void): Promise<Job> {
  for (;;) {
    const job = await getJob(id);
    onTick(job);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, 600));
  }
}
