import { useState } from "react";
import { DiffTab } from "./tabs/DiffTab";
import { DskTab } from "./tabs/DskTab";
import { GeneratorTab } from "./tabs/GeneratorTab";
import { ResizeTab } from "./tabs/ResizeTab";

const TABS = [
  { id: "generate", label: "Sermon Base Generator" },
  { id: "diff", label: "Diff Checker" },
  { id: "dsk", label: "DSK generator" },
  { id: "resize", label: "CG resizer" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<TabId>("generate");
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Sermon slides</div>
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
        {tab === "generate" && <GeneratorTab />}
        {tab === "diff" && <DiffTab />}
        {tab === "dsk" && <DskTab />}
        {tab === "resize" && <ResizeTab />}
      </main>
    </div>
  );
}
