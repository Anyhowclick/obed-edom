import { lazy, Suspense, useEffect, useState } from "react";
import { CheckTab } from "./tabs/CheckTab";
import { DskTab } from "./tabs/DskTab";
import { GeneratorTab } from "./tabs/GeneratorTab";
import { HistoryTab } from "./tabs/HistoryTab";
import { ResizeTab } from "./tabs/ResizeTab";
import { SettingsTab } from "./tabs/SettingsTab";
import { WatercolourTab } from "./tabs/WatercolourTab";
import {
  LayoutContext,
  RunNavContext,
  TAB_SHORT,
  loadSidebarCollapsed,
  saveSidebarCollapsed,
  type FeatureId,
  type TabId,
} from "./nav";

const MapsTab = lazy(() => import("./tabs/MapsTab").then((m) => ({ default: m.MapsTab })));

const TABS: { id: TabId; label: string }[] = [
  { id: "generate", label: "Sermon Base Generator" },
  { id: "check", label: "Sermon Checker" },
  { id: "dsk", label: "DSK Generator" },
  { id: "resize", label: "CG resizer" },
  { id: "maps", label: "Maps" },
  { id: "watercolour", label: "Watercolour" },
  { id: "history", label: "History" },
  { id: "settings", label: "Settings" },
];

export function App() {
  const [tab, setTab] = useState<TabId>("generate");
  const [openRun, setOpenRun] = useState<{ feature: FeatureId; jobId: string } | null>(null);
  const [sidebarCollapsed, setSidebarCollapsedState] = useState(loadSidebarCollapsed);
  const [focusMode, setFocusModeState] = useState(false);
  const [collapsedForFocus, setCollapsedForFocus] = useState(false);

  function setSidebarCollapsed(next: boolean) {
    setSidebarCollapsedState(next);
    saveSidebarCollapsed(next);
    if (!next) setCollapsedForFocus(false);
  }

  function setFocusMode(next: boolean) {
    setFocusModeState(next);
    if (next) {
      if (!sidebarCollapsed) {
        setSidebarCollapsedState(true);
        saveSidebarCollapsed(true);
        setCollapsedForFocus(true);
      }
      return;
    }
    if (collapsedForFocus) {
      setSidebarCollapsedState(false);
      saveSidebarCollapsed(false);
      setCollapsedForFocus(false);
    }
  }

  useEffect(() => {
    if (tab !== "check" && focusMode) setFocusMode(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  function openInFeature(feature: FeatureId, jobId: string) {
    setOpenRun({ feature, jobId });
    setTab(feature === "diff" ? "check" : feature);
  }

  function clearOpenRun() {
    setOpenRun(null);
  }

  return (
    <RunNavContext.Provider value={{ openInFeature, clearOpenRun, openRun }}>
      <LayoutContext.Provider value={{ sidebarCollapsed, setSidebarCollapsed, focusMode, setFocusMode }}>
      <div className={`app${sidebarCollapsed ? " sidebar-collapsed" : ""}${focusMode ? " focus-mode" : ""}`}>
        <aside className={`sidebar${sidebarCollapsed ? " collapsed" : ""}`}>
          <div className="sidebar-top">
            {!sidebarCollapsed && <div className="brand">Obed-Edom</div>}
            <button
              className="sidebar-toggle"
              type="button"
              title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
              aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            >
              {sidebarCollapsed ? "»" : "«"}
            </button>
          </div>
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-btn ${tab === item.id ? "active" : ""}`}
              title={item.label}
              onClick={() => {
                if (item.id !== tab) setOpenRun(null);
                setTab(item.id);
              }}
            >
              {sidebarCollapsed ? TAB_SHORT[item.id] : item.label}
            </button>
          ))}
        </aside>
        <main className="main">
          <div className={tab === "generate" ? "pane" : "pane off"}>
            <GeneratorTab />
          </div>
          <div className={tab === "check" ? "pane" : "pane off"}>
            <CheckTab />
          </div>
          <div className={tab === "dsk" ? "pane" : "pane off"}>
            <DskTab />
          </div>
          <div className={tab === "resize" ? "pane" : "pane off"}>
            <ResizeTab />
          </div>
          {tab === "maps" ? (
            <div className="pane maps-pane">
              <Suspense fallback={<p className="note">Loading maps…</p>}>
                <MapsTab />
              </Suspense>
            </div>
          ) : null}
          <div className={tab === "watercolour" ? "pane" : "pane off"}><WatercolourTab /></div>
          <div className={tab === "history" ? "pane" : "pane off"}>
            <HistoryTab active={tab === "history"} />
          </div>
          <div className={tab === "settings" ? "pane" : "pane off"}>
            <SettingsTab />
          </div>
        </main>
      </div>
      </LayoutContext.Provider>
    </RunNavContext.Provider>
  );
}
