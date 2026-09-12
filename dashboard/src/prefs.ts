import { useCallback, useEffect, useState } from "react";
import { getSettings } from "./api";

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

/** A string the operator sets once and keeps for the rest of the session. */
export function useSessionPath(key: string, fallback = ""): [string, (next: string) => void] {
  const [value, setValue] = useState<string>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw !== null) return raw;
    } catch {
      /* ignore */
    }
    return fallback;
  });

  const update = useCallback(
    (next: string) => {
      setValue(next);
      try {
        sessionStorage.setItem(key, next);
      } catch {
        /* ignore */
      }
    },
    [key]
  );

  return [value, update];
}

let defaultExportDirRequest: Promise<string> | null = null;
let defaultExportDirVersion = 0;
const defaultExportDirListeners = new Set<() => void>();

/** Invalidates the shared default-export-dir fetch so every mounted `useDefaultExportDir` refetches. */
export function refreshDefaultExportDir(): void {
  defaultExportDirRequest = null;
  defaultExportDirVersion += 1;
  defaultExportDirListeners.forEach((listener) => listener());
}

/** The operator's persisted default export folder (`""` when unset), fetched once and shared. */
export function useDefaultExportDir(): string {
  const [value, setValue] = useState("");
  const [version, setVersion] = useState(defaultExportDirVersion);

  useEffect(() => {
    const listener = () => setVersion((v) => v + 1);
    defaultExportDirListeners.add(listener);
    return () => {
      defaultExportDirListeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!defaultExportDirRequest) {
      defaultExportDirRequest = getSettings()
        .then((settings) => settings.defaultExportDir || "")
        .catch(() => "");
    }
    defaultExportDirRequest.then((dir) => {
      if (!cancelled) setValue(dir);
    });
    return () => {
      cancelled = true;
    };
  }, [version]);

  return value;
}

export const SHOW_INFO_KEY = "obed-edom.findings.showInfo";
export const SIDE_PANELS_KEY = "obed-edom.diff.sidePanels";
export const MAPS_SIDE_PANELS_KEY = "obed-edom.maps.sidePanels";
export const MAPS_INSPECTOR_KEY = "obed-edom.maps.inspector";
export const LW_TEMPLATE_KEY = "obed-edom.generate.lwTemplate";
export const DSK_TEMPLATE_KEY = "obed-edom.generate.dskTemplate";

export type StoredFile = { path: string; name: string };

export function loadStoredFile(key: string): StoredFile | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const data = JSON.parse(raw) as StoredFile;
    if (data && typeof data.path === "string" && typeof data.name === "string" && data.path) {
      return data;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function saveStoredFile(key: string, file: StoredFile | null) {
  try {
    if (file) localStorage.setItem(key, JSON.stringify(file));
    else localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
