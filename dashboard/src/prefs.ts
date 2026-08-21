import { useCallback, useState } from "react";

/** A boolean the operator sets once and keeps for the rest of the session. */
export function useSessionToggle(key: string, fallback: boolean): [boolean, (next: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw === "1") return true;
      if (raw === "0") return false;
    } catch {
      /* ignore */
    }
    return fallback;
  });

  const update = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        sessionStorage.setItem(key, next ? "1" : "0");
      } catch {
        /* ignore */
      }
    },
    [key]
  );

  return [value, update];
}

export const SHOW_INFO_KEY = "obed-edom.findings.showInfo";
export const SIDE_PANELS_KEY = "obed-edom.diff.sidePanels";
