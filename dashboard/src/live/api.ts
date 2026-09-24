export type LiveOperation = "advance" | "goTo" | "hide" | "show" | "stop";
export type LiveCapability = { supported: boolean; reason?: string };
export type LiveSlide = { originalOrdinal: number; skipped: boolean; thumbnailUrl?: string; notes?: string };
export type LivePreparedDeck = { previewJobId: string; name: string; slides: number; sourceDigest: string };
export type LiveDisplay = { id: string; name: string; width: number; height: number; x: number; y: number; primary: boolean };
export type LiveCodec = { asset: string; codec: string | null; family: "h264" | "hevc" | "prores" | "av1" | "vp9" | "other" };
export type LiveNotCarried = { fromSlide: number; toSlide: number; asset: string; reason: string };
export type LiveContinuity ={ mode: "qualified" | "unsupported" | "off" | "pending"; reason?: string; version?: number; sha256?: string; scale?: number; notCarried?: LiveNotCarried[] };
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
  autoPlayDeferred?: string | null;
  continuity?: LiveContinuity;
  capabilities: Record<Exclude<LiveOperation, "stop">, LiveCapability>;
  slides: LiveSlide[];
  error?: string;
  output: {
    transport: "hdmi" | "fill-key";
    bridge?: "obs-managed" | "obs-cdp";
    width: number;
    height: number;
    alpha: boolean;
    audio: false;
    codecs?: LiveCodec[];
    codecWarnings?: string[];
    rateWarnings?: string[];
  };
};
export type LiveCommand = { requestId: string; operation: LiveOperation; slide?: number };
export type LiveResult = {
  requestId: string;
  outcome: "rejected" | "completed" | "accepted";
  reason?: string;
  state: LiveSnapshot;
};
export type LiveOutputMode = "screen" | "keyer";
export type LiveOutputRate = 25 | 30;
export type LiveKeyer = "external" | "off";
export type LiveOutputSettings = { akOutputMode: LiveOutputMode; akOutputRate: LiveOutputRate; akKeyer: LiveKeyer };
export type LiveEngineAction = "start" | "restart" | "check" | "show" | "quit" | "setupDevice" | "setupDone";
export type LiveEngineWarning = { id: string; severity: "block" | "warn" | "info"; text: string; action?: string };
export type LiveEngine = {
  state: "unavailable" | "stopped" | "starting" | "ready" | "blocked" | "stuck" | "quitting";
  reason?: string;
  obs: { path: string | null; version: string | null; pinned: string };
  rate: { output: number; canvas: number | null; source: number | null };
  device: { name: string | null; set: boolean };
  keyer: LiveKeyer;
  warnings: LiveEngineWarning[];
};
export interface LiveClient {
  state(): Promise<LiveSnapshot | null>;
  decks(): Promise<LivePreparedDeck[]>;
  displays(): Promise<LiveDisplay[]>;
  start(previewJobId: string, displayId?: string, continuity?: "off"): Promise<LiveSnapshot>;
  command(sessionId: string, command: LiveCommand): Promise<LiveResult>;
  engine(): Promise<LiveEngine>;
  engineAction(action: LiveEngineAction): Promise<LiveEngine>;
  outputSettings(): Promise<LiveOutputSettings>;
  saveOutputSettings(settings: LiveOutputSettings): Promise<LiveOutputSettings>;
}

async function request<T>(url: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(url, method === "GET" ? undefined : {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
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
  engine: () => request<LiveEngine>("/api/live/engine"),
  engineAction: (action) => request<LiveEngine>(`/api/live/engine/${action}`, undefined, "POST"),
  outputSettings: () => request<LiveOutputSettings>("/api/live/output-settings"),
  saveOutputSettings: (settings) => request<LiveOutputSettings>("/api/live/output-settings", settings, "PUT"),
};
