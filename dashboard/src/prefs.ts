import { useCallback, useEffect, useState } from "react";
import { getSettings, putSettings, type Settings } from "./api";
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
export const DSK_WORKSPACE_KEY = "obed-edom.dsk.workspace";

export type StoredFile = { path: string; name: string };
export type TemplateField = "lwTemplate" | "dskTemplate";

const LEGACY_TEMPLATE_KEYS: Record<TemplateField, string> = {
  lwTemplate: "obed-edom.generate.lwTemplate",
  dskTemplate: "obed-edom.generate.dskTemplate",
};

type StoredTemplates = Record<TemplateField, string>;

function readLegacyTemplate(field: TemplateField): string {
  try {
    const raw = localStorage.getItem(LEGACY_TEMPLATE_KEYS[field]);
    if (!raw) return "";
    const data = JSON.parse(raw) as Partial<StoredFile>;
    return typeof data?.path === "string" ? data.path : "";
  } catch {
    return "";
  }
}

function forgetLegacyTemplate(field: TemplateField) {
  try {
    localStorage.removeItem(LEGACY_TEMPLATE_KEYS[field]);
  } catch {
    /* ignore */
  }
}

function pickTemplates(settings: Partial<Settings>): StoredTemplates {
  return { lwTemplate: settings.lwTemplate || "", dskTemplate: settings.dskTemplate || "" };
}

/** Moves templates remembered by an older dashboard (browser storage) into settings.json, once. */
async function migrateLegacyTemplates(stored: StoredTemplates): Promise<StoredTemplates> {
  const patch: Partial<Settings> = {};
  for (const field of ["lwTemplate", "dskTemplate"] as const) {
    const legacy = readLegacyTemplate(field);
    if (legacy && !stored[field]) patch[field] = legacy;
  }
  if (!Object.keys(patch).length) return stored;
  const written = pickTemplates(await putSettings(patch));
  (Object.keys(patch) as TemplateField[]).forEach(forgetLegacyTemplate);
  return written;
}

const NO_TEMPLATES: StoredTemplates = { lwTemplate: "", dskTemplate: "" };
let templatesRequest: Promise<StoredTemplates> | null = null;
let templatesCache: StoredTemplates | null = null;
let templateWrites = 0;
const templateListeners = new Set<() => void>();

/** Invalidates the shared templates fetch so every mounted `useStoredTemplate` refetches. */
export function refreshStoredTemplates(): void {
  templatesRequest = null;
  templatesCache = null;
  templateListeners.forEach((listener) => listener());
}

function templatesReady(): Promise<StoredTemplates> {
  if (!templatesRequest) {
    const writesBefore = templateWrites;
    templatesRequest = getSettings()
      .then((settings) => {
        const stored = pickTemplates(settings);
        return migrateLegacyTemplates(stored).catch(() => stored);
      })
      .catch(() => NO_TEMPLATES)
      .then((stored) => {
        if (templateWrites === writesBefore) templatesCache = stored;
        templateListeners.forEach((listener) => listener());
        return templatesCache || stored;
      });
  }
  return templatesRequest;
}

function toStoredFile(path: string): StoredFile | null {
  return path ? { path, name: path.split("/").pop() || path } : null;
}

/** A template remembered in settings.json, so it survives any browser, tab, or profile on this Mac. */
export function useStoredTemplate(field: TemplateField): [StoredFile | null, (file: StoredFile | null) => Promise<void>] {
  const [value, setValue] = useState<StoredFile | null>(() => toStoredFile(templatesCache?.[field] || ""));

  useEffect(() => {
    const sync = () => {
      setValue(toStoredFile(templatesCache?.[field] || ""));
      if (!templatesRequest) void templatesReady();
    };
    templateListeners.add(sync);
    sync();
    return () => {
      templateListeners.delete(sync);
    };
  }, [field]);

  const update = useCallback(
    async (file: StoredFile | null) => {
      const path = file?.path || "";
      const previous = templatesCache || NO_TEMPLATES;
      templateWrites += 1;
      templatesCache = { ...previous, [field]: path };
      templateListeners.forEach((listener) => listener());
      try {
        templatesCache = pickTemplates(await putSettings({ [field]: path }));
      } catch (err) {
        templatesCache = previous;
        throw err;
      } finally {
        templateListeners.forEach((listener) => listener());
      }
    },
    [field]
  );

  return [value, update];
}
