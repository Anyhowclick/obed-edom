import { useState } from "react";
import { DiffTab } from "./tabs/DiffTab";
import { DskTab } from "./tabs/DskTab";
import { GeneratorTab } from "./tabs/GeneratorTab";
import { HistoryTab } from "./tabs/HistoryTab";
import { ResizeTab } from "./tabs/ResizeTab";
import { RunNavContext, type FeatureId, type TabId } from "./nav";

const TABS: { id: TabId; label: string }[] = [
  { id: "generate", label: "Sermon Base Generator" },
  { id: "diff", label: "Diff Checker" },
  { id: "dsk", label: "DSK generator" },
  { id: "resize", label: "CG resizer" },
  { id: "history", label: "Previous runs" },
];

export function App() {
  const [tab, setTab] = useState<TabId>("generate");
  const [openRun, setOpenRun] = useState<{ feature: FeatureId; jobId: string } | null>(null);

  function openInFeature(feature: FeatureId, jobId: string) {
    setOpenRun({ feature, jobId });
    setTab(feature);
  }

  return (
    <RunNavContext.Provider value={{ openInFeature, openRun }}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">Obed-Edom</div>
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-btn ${tab === item.id ? "active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </aside>
        <main className="main">
          <div className={tab === "generate" ? "pane" : "pane off"}>
            <GeneratorTab />
          </div>
          <div className={tab === "diff" ? "pane" : "pane off"}>
            <DiffTab />
          </div>
          <div className={tab === "dsk" ? "pane" : "pane off"}>
            <DskTab />
          </div>
          <div className={tab === "resize" ? "pane" : "pane off"}>
            <ResizeTab />
          </div>
          <div className={tab === "history" ? "pane" : "pane off"}>
            <HistoryTab active={tab === "history"} />
          </div>
        </main>
      </div>
    </RunNavContext.Provider>
  );
}
