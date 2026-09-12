import { vi } from "vitest";
import type { Job, MapsStateConflict, Settings } from "../../src/api";
import { makeJob } from "./doc";

const actual = await vi.importActual<typeof import("../../src/api")>("../../src/api");

type SaveMapsStateArgs = Parameters<typeof actual.saveMapsState>;
type PostMapsPngArgs = Parameters<typeof actual.postMapsPng>;
type PostMapsPngOpts = PostMapsPngArgs[2];
type RenameJobArgs = Parameters<typeof actual.renameJob>;
type GetJobArgs = Parameters<typeof actual.getJob>;

let saveConflictOnce: { conflict: MapsStateConflict } | null = null;
let saveCalls: Array<{ id: string; document: Record<string, unknown>; expectedRevision: number }> = [];

let staleOnce: { stateRevision: number } | null = null;
let postMapsPngCalls: PostMapsPngOpts[] = [];

let renameFailOnce: Error | null = null;
let renameCalls: Array<{ id: string; name: string }> = [];

let getJobResolution: Job | null = null;

export const saveMapsState = vi.fn<typeof actual.saveMapsState>(async (id: SaveMapsStateArgs[0], document: SaveMapsStateArgs[1], expectedRevision: SaveMapsStateArgs[2]): Promise<Job> => {
  saveCalls.push({ id, document, expectedRevision });
  if (saveConflictOnce) {
    const { conflict } = saveConflictOnce;
    saveConflictOnce = null;
    throw new actual.MapsStateConflictError(conflict);
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
  saveCalls = [];
  staleOnce = null;
  postMapsPngCalls = [];
  renameFailOnce = null;
  renameCalls = [];
  getJobResolution = null;
  saveMapsState.mockClear();
  postMapsPng.mockClear();
  renameJob.mockClear();
  getJob.mockClear();
  getSettings.mockClear();
}

export const mapsApiScript = {
  saveMapsState: {
    conflictOnce(conflict: { document: Record<string, unknown>; stateRevision: number }) {
      saveConflictOnce = { conflict: { document: conflict.document, stateRevision: conflict.stateRevision } };
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
};
