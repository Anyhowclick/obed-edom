import { createContext, useContext } from "react";

export type FeatureId = "generate" | "diff" | "check" | "dsk" | "resize" | "maps";
export type TabId = FeatureId | "history" | "settings";

export const FEATURE_LABELS: Record<FeatureId, string> = {
  generate: "Sermon Base Generator",
  diff: "Sermon Checker",
  check: "Sermon Checker",
  dsk: "DSK Generator",
  resize: "CG resizer",
  maps: "Maps",
};

export const OPEN_IN_LABELS: Record<FeatureId, string> = {
  generate: "Open in Generator",
  diff: "Open in Sermon Checker",
  check: "Open in Sermon Checker",
  dsk: "Open in DSK Generator",
  resize: "Open in CG resizer",
  maps: "Open in Maps",
};

type Nav = {
  openInFeature: (feature: FeatureId, jobId: string) => void;
  clearOpenRun: () => void;
  openRun: { feature: FeatureId; jobId: string } | null;
};

export const RunNavContext = createContext<Nav>({
  openInFeature: () => undefined,
  clearOpenRun: () => undefined,
  openRun: null,
});

export function useRunNav() {
  return useContext(RunNavContext);
}

const SIDEBAR_KEY = "obed-edom.sidebar.collapsed";

export function loadSidebarCollapsed(): boolean {
  try {
    return sessionStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveSidebarCollapsed(collapsed: boolean) {
  try {
    sessionStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
}

type Layout = {
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (next: boolean) => void;
  focusMode: boolean;
  setFocusMode: (next: boolean) => void;
};

export const LayoutContext = createContext<Layout>({
  sidebarCollapsed: false,
  setSidebarCollapsed: () => undefined,
  focusMode: false,
  setFocusMode: () => undefined,
});

export function useLayout() {
  return useContext(LayoutContext);
}

export const TAB_SHORT: Record<TabId, string> = {
  generate: "Gen",
  check: "Chk",
  diff: "Diff",
  dsk: "DSK",
  resize: "CG",
  maps: "Map",
  history: "Hist",
  settings: "Set",
};

export function asFeature(value: string | undefined): FeatureId | null {
  if (value === "generate" || value === "diff" || value === "check" || value === "dsk" || value === "resize" || value === "maps") return value;
  return null;
}
