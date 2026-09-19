export type LiveOperation = "advance" | "goTo" | "hide" | "show" | "stop";
export type LiveCapability = { supported: boolean; reason?: string };
export type LiveSlide = { originalOrdinal: number; skipped: boolean; thumbnailUrl?: string; notes?: string };
export type LivePreparedDeck = { previewJobId: string; name: string; slides: number; sourceDigest: string };
export type LiveDisplay = { id: string; name: string; width: number; height: number; x: number; y: number; primary: boolean };
export type LiveContinuity = { mode: "qualified" | "unsupported" | "off" | "pending"; reason?: string; version?: number; sha256?: string };
export type LiveSnapshot = {
  sessionId: string;
  revision: number;
  status: "loading" | "ready" | "busy" | "error" | "stopped";
  sourceDigest: string;
  exportKey: string;
  playerDigest: string;
  runtimeRevision: string | number;
  originalSlide: number | null;
  sceneId: string | null;
  buildIndex: number | null;
  outputVisible: boolean;
  continuity?: LiveContinuity;
  capabilities: Record<Exclude<LiveOperation, "stop">, LiveCapability>;
  slides: LiveSlide[];
  error?: string;
  output: { transport: "hdmi"; width: number; height: number; alpha: false; audio: false };
};
export type LiveCommand = { requestId: string; operation: LiveOperation; slide?: number };
export type LiveResult = {
  requestId: string;
  outcome: "rejected" | "completed" | "accepted";
  reason?: string;
  state: LiveSnapshot;
};
export interface LiveClient {
  state(): Promise<LiveSnapshot | null>;
  decks(): Promise<LivePreparedDeck[]>;
  displays(): Promise<LiveDisplay[]>;
  start(previewJobId: string, displayId?: string, continuity?: "off"): Promise<LiveSnapshot>;
  command(sessionId: string, command: LiveCommand): Promise<LiveResult>;
}

async function request<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Live output request failed (${response.status})`);
  return data as T;
}

export const liveClient: LiveClient = {
  state: () => request<LiveSnapshot | null>("/api/live"),
  decks: () => request<LivePreparedDeck[]>("/api/live/decks"),
  displays: () => request<LiveDisplay[]>("/api/live/displays"),
  start: (previewJobId, displayId, continuity) => request<LiveSnapshot>("/api/live", { previewJobId, ...(displayId ? { displayId } : {}), ...(continuity ? { continuity } : {}) }),
  command: (sessionId, command) => request<LiveResult>(`/api/live/${encodeURIComponent(sessionId)}/commands`, command),
};
