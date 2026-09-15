import { useState } from "react";
import { DskGenerator } from "./dsk/DskGenerator";
import { DskExporter } from "./dsk/DskExporter";

const SUB_TAB_KEY = "obed-edom.dsk.subtab";

type DskSubTab = "generator" | "exporter";

function loadSubTab(): DskSubTab {
  try {
    const raw = sessionStorage.getItem(SUB_TAB_KEY);
    if (raw === "generator" || raw === "exporter") return raw;
  } catch {
    /* ignore */
  }
  return "generator";
}

export function DskTab() {
  const [sub, setSub] = useState<DskSubTab>(loadSubTab);

  function choose(next: DskSubTab) {
    setSub(next);
    try {
      sessionStorage.setItem(SUB_TAB_KEY, next);
    } catch {
      /* ignore */
    }
  }

  return (
    <div>
      <h1>DSK</h1>
      <div className="seg">
        <button type="button" className={sub === "generator" ? "on" : ""} onClick={() => choose("generator")}>
          Generator
        </button>
        <button type="button" className={sub === "exporter" ? "on" : ""} onClick={() => choose("exporter")}>
          Exporter
        </button>
      </div>
      {sub === "generator" ? <DskGenerator /> : <DskExporter />}
    </div>
  );
}
