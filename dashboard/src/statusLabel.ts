import type { Job } from "./api";
import type { FeatureId } from "./nav";

export type StatusTone = "ok" | "busy" | "err";

type StatusPair = { done: string; running: string };

const FEATURE_STATUS: Record<FeatureId, StatusPair> = {
  generate: { done: "Generated", running: "Generating…" },
  dsk: { done: "Generated", running: "Generating…" },
  maps: { done: "Exported", running: "Exporting…" },
  resize: { done: "Resized", running: "Resizing…" },
  watercolour: { done: "Rendered", running: "Rendering…" },
  check: { done: "Checked", running: "Checking…" },
  diff: { done: "Checked", running: "Checking…" },
};

const GENERIC_STATUS: StatusPair = { done: "Done", running: "Working…" };

export function statusLabel(feature: string, status: Job["status"]): { text: string; tone: StatusTone } {
  if (status === "queued") return { text: "Queued", tone: "busy" };
  if (status === "error") return { text: "Failed", tone: "err" };
  const pair = FEATURE_STATUS[feature as FeatureId] || GENERIC_STATUS;
  if (status === "running") return { text: pair.running, tone: "busy" };
  return { text: pair.done, tone: "ok" };
}
