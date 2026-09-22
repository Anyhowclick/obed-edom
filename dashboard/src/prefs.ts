import { useCallback, useEffect, useState } from "react";
import { getSettings } from "./api";
import { DEFAULT_HIGHLIGHT_COLOUR, normaliseHighlightColour } from "./maps/highlight";

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

let highlightColourRequest: Promise<string> | null = null;
let highlightColourVersion = 0;
const highlightColourListeners = new Set<() => void>();

/** Invalidates the shared highlight-colour fetch so every mounted `useHighlightColour` refetches. */
export function refreshHighlightColour(): void {
  highlightColourRequest = null;
  highlightColourVersion += 1;
  highlightColourListeners.forEach((listener) => listener());
}

/** The operator's persisted highlight colour, fetched once and shared. */
export function useHighlightColour(): string {
  const [value, setValue] = useState(DEFAULT_HIGHLIGHT_COLOUR);
  const [version, setVersion] = useState(highlightColourVersion);

  useEffect(() => {
    const listener = () => setVersion((v) => v + 1);
    highlightColourListeners.add(listener);
    return () => {
      highlightColourListeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!highlightColourRequest) {
      highlightColourRequest = getSettings()
        .then((settings) => normaliseHighlightColour(settings.highlightColour))
        .catch(() => DEFAULT_HIGHLIGHT_COLOUR);
    }
    highlightColourRequest.then((colour) => {
      if (!cancelled) setValue(colour);
    });
    return () => {
      cancelled = true;
    };
  }, [version]);

  return value;
}

/** Resolves the operator's persisted highlight colour, kicking off the shared fetch if needed. */
export function highlightColourReady(): Promise<string> {
  if (!highlightColourRequest) {
    highlightColourRequest = getSettings()
      .then((settings) => normaliseHighlightColour(settings.highlightColour))
      .catch(() => DEFAULT_HIGHLIGHT_COLOUR);
  }
  return highlightColourRequest;
}

export const SHOW_INFO_KEY = "obed-edom.findings.showInfo";
export const SIDE_PANELS_KEY = "obed-edom.diff.sidePanels";
export const MAPS_SIDE_PANELS_KEY = "obed-edom.maps.sidePanels";
export const MAPS_INSPECTOR_KEY = "obed-edom.maps.inspector";
export const MAPS_PICK_MODE_KEY = "obed-edom.maps.pickMode";
export const LW_TEMPLATE_KEY = "obed-edom.generate.lwTemplate";
export const DSK_TEMPLATE_KEY = "obed-edom.generate.dskTemplate";
export const DSK_WORKSPACE_KEY = "obed-edom.dsk.workspace";

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

const storedFileListeners = new Map<string, Set<() => void>>();

function notifyStoredFile(key: string) {
  storedFileListeners.get(key)?.forEach((listener) => listener());
}

/** A stored file kept in sync across every mounted subscriber on this key, in this tab and others. */
export function useStoredFile(key: string): [StoredFile | null, (file: StoredFile | null) => void] {
  const [value, setValue] = useState<StoredFile | null>(() => loadStoredFile(key));

  useEffect(() => {
    setValue(loadStoredFile(key));
    const listener = () => setValue(loadStoredFile(key));
    let listeners = storedFileListeners.get(key);
    if (!listeners) {
      listeners = new Set();
      storedFileListeners.set(key, listeners);
    }
    listeners.add(listener);
    const onStorage = (e: StorageEvent) => {
      if (e.key === key) listener();
    };
    window.addEventListener("storage", onStorage);
    return () => {
      listeners!.delete(listener);
      window.removeEventListener("storage", onStorage);
    };
  }, [key]);

  const update = useCallback(
    (file: StoredFile | null) => {
      saveStoredFile(key, file);
      notifyStoredFile(key);
    },
    [key]
  );

  return [value, update];
}
