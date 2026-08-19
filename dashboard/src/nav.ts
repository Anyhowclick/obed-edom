import { createContext, useContext } from "react";

export type FeatureId = "generate" | "diff" | "dsk" | "resize";
export type TabId = FeatureId | "history";

export const FEATURE_LABELS: Record<FeatureId, string> = {
  generate: "Sermon Base Generator",
  diff: "Diff Checker",
  dsk: "DSK generator",
  resize: "CG resizer",
};

export const OPEN_IN_LABELS: Record<FeatureId, string> = {
  generate: "Open in Generator",
  diff: "Open in Diff Checker",
  dsk: "Open in DSK generator",
  resize: "Open in CG resizer",
};

type Nav = {
  openInFeature: (feature: FeatureId, jobId: string) => void;
  openRun: { feature: FeatureId; jobId: string } | null;
};

export const RunNavContext = createContext<Nav>({
  openInFeature: () => undefined,
  openRun: null,
});

export function useRunNav() {
  return useContext(RunNavContext);
}

export function asFeature(value: string | undefined): FeatureId | null {
  if (value === "generate" || value === "diff" || value === "dsk" || value === "resize") return value;
  return null;
}
