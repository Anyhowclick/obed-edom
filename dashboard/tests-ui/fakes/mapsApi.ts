import { vi } from "vitest";
import type { Job, MapsStateConflict, Settings } from "../../src/api";
import { makeJob } from "./doc";

const actual = await vi.importActual<typeof import("../../src/api")>("../../src/api");

type SaveMapsStateArgs = Parameters<typeof actual.saveMapsState>;
type PostMapsPngArgs = Parameters<typeof actual.postMapsPng>;
type PostMapsPngOpts = PostMapsPngArgs[2];
type RenameJobArgs = Parameters<typeof actual.renameJob>;
type GetJobArgs = Parameters<typeof actual.getJob>;
type BootstrapRowsArgs = Parameters<typeof actual.bootstrapMapsRows>;
type PollJobArgs = Parameters<typeof actual.pollJob>;

let saveConflictOnce: { conflict: MapsStateConflict } | null = null;
let saveCalls: Array<{ id: string; document: Record<string, unknown>; expectedRevision: number }> = [];

let staleOnce: { stateRevision: number } | null = null;
let postMapsPngCalls: PostMapsPngOpts[] = [];

let renameFailOnce: Error | null = null;
let renameCalls: Array<{ id: string; name: string }> = [];

let getJobResolution: Job | null = null;

let saveDeferOnce: Promise<Job> | null = null;

let bootstrapRowsFailOnce: Error | null = null;
let bootstrapRowsCalls: Array<{ id: string; body: BootstrapRowsArgs[1] }> = [];

let pollJobResolution: Job | null = null;

export const saveMapsState = vi.fn<typeof actual.saveMapsState>(async (id: SaveMapsStateArgs[0], document: SaveMapsStateArgs[1], expectedRevision: SaveMapsStateArgs[2]): Promise<Job> => {
  saveCalls.push({ id, document, expectedRevision });
  if (saveConflictOnce) {
    const { conflict } = saveConflictOnce;
    saveConflictOnce = null;
    throw new actual.MapsStateConflictError(conflict);
  }
  if (saveDeferOnce) {
    const deferred = saveDeferOnce;
    saveDeferOnce = null;
    return deferred;
  }
  return makeJob({ id, result: { ...document, stateRevision: expectedRevision + 1 } });
});

export const postMapsPng = vi.fn<typeof actual.postMapsPng>(async (id: PostMapsPngArgs[0], _blob: PostMapsPngArgs[1], opts: PostMapsPngOpts = {}): Promise<Job> => {
  postMapsPngCalls.push(opts);
  if (staleOnce) {
    const { stateRevision } = staleOnce;
    staleOnce = null;
    throw new actual.MapsStaleThumbnailError(stateRevision);
  }
  return makeJob({ id });
});

export const renameJob = vi.fn<typeof actual.renameJob>(async (id: RenameJobArgs[0], name: RenameJobArgs[1]): Promise<Job> => {
  renameCalls.push({ id, name });
  if (renameFailOnce) {
    const err = renameFailOnce;
    renameFailOnce = null;
    throw err;
  }
  return makeJob({ id, name });
});

export const getJob = vi.fn<typeof actual.getJob>(async (id: GetJobArgs[0]): Promise<Job> => {
  if (getJobResolution) return getJobResolution;
  return makeJob({ id });
});

export const bootstrapMapsRows = vi.fn<typeof actual.bootstrapMapsRows>(async (id: BootstrapRowsArgs[0], body: BootstrapRowsArgs[1]): Promise<Job> => {
  bootstrapRowsCalls.push({ id, body });
  if (bootstrapRowsFailOnce) {
    const err = bootstrapRowsFailOnce;
    bootstrapRowsFailOnce = null;
    throw err;
  }
  return makeJob({ id, status: "queued" });
});

export const pollJob = vi.fn<typeof actual.pollJob>(async (id: PollJobArgs[0], onTick: PollJobArgs[1]): Promise<Job> => {
  const job = pollJobResolution ?? makeJob({ id });
  onTick(job);
  return job;
});

export const getSettings = vi.fn<typeof actual.getSettings>(
  async (): Promise<Settings> => ({
    reuseThreshold: 0,
    reusePairings: false,
    reusePreviews: false,
    defaultExportDir: "",
  })
);

export function resetMapsApiScript() {
  saveConflictOnce = null;
  saveDeferOnce = null;
  saveCalls = [];
  staleOnce = null;
  postMapsPngCalls = [];
  renameFailOnce = null;
  renameCalls = [];
  getJobResolution = null;
  bootstrapRowsFailOnce = null;
  bootstrapRowsCalls = [];
  pollJobResolution = null;
  saveMapsState.mockClear();
  postMapsPng.mockClear();
  renameJob.mockClear();
  getJob.mockClear();
  bootstrapMapsRows.mockClear();
  pollJob.mockClear();
  getSettings.mockClear();
}

export const mapsApiScript = {
  saveMapsState: {
    conflictOnce(conflict: { document: Record<string, unknown>; stateRevision: number }) {
      saveConflictOnce = { conflict: { document: conflict.document, stateRevision: conflict.stateRevision } };
    },
    deferOnce(promise: Promise<Job>) {
      saveDeferOnce = promise;
    },
    get calls() {
      return saveCalls;
    },
  },
  postMapsPng: {
    staleOnce(opts: { stateRevision: number }) {
      staleOnce = opts;
    },
    get calls() {
      return postMapsPngCalls;
    },
  },
  renameJob: {
    failOnce(err: Error) {
      renameFailOnce = err;
    },
    get calls() {
      return renameCalls;
    },
  },
  getJob: {
    resolve(job: Job) {
      getJobResolution = job;
    },
  },
  bootstrapMapsRows: {
    failOnce(err: Error) {
      bootstrapRowsFailOnce = err;
    },
    get calls() {
      return bootstrapRowsCalls;
    },
  },
  pollJob: {
    resolve(job: Job) {
      pollJobResolution = job;
    },
  },
};
